"""Job discovery and definition tools for Jenkins MCP."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from ..base import ParameterSpec
from ..cache_manager import CacheManager
from ..jenkins.jenkins_client import JenkinsClient
from ..jenkins.job_name_utils import JobNameParser
from .base_tools import JenkinsOperationTool
from .common import CommonParameters

DEFAULT_FIND_LIMIT = 25
MAX_FIND_LIMIT = 200
DEFAULT_INLINE_SCRIPT_CHARS = 20000


def _sanitize_path_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "unnamed"


def _clamp_find_limit(value: int) -> int:
    return max(1, min(value, MAX_FIND_LIMIT))


def _xml_editing_enabled(multi_jenkins_manager) -> bool:
    if not multi_jenkins_manager:
        return False
    return bool(multi_jenkins_manager.settings.get("enable_job_xml_editing", False))


def _xml_workspace_root(cache_manager: CacheManager, multi_jenkins_manager) -> Path:
    override = None
    if multi_jenkins_manager:
        override = multi_jenkins_manager.settings.get("job_xml_workspace_dir")
    if override:
        return Path(override).expanduser()
    return cache_manager.config.base_dir / "job-definitions"


def _job_xml_path(
    cache_manager: CacheManager,
    multi_jenkins_manager,
    instance_id: Optional[str],
    normalized_job_name: str,
) -> Path:
    workspace_root = _xml_workspace_root(cache_manager, multi_jenkins_manager)
    instance_segment = _sanitize_path_segment(instance_id or "default")
    job_parts = [
        _sanitize_path_segment(part)
        for part in normalized_job_name.split("/")
        if part.strip()
    ]
    if not job_parts:
        job_parts = ["unnamed-job"]
    return workspace_root / instance_segment / Path(*job_parts) / "config.xml"


def _extract_first_present(mapping: Dict[str, Any], *keys: str) -> Optional[Any]:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _extract_repo_url(scm_data: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(scm_data, dict):
        return None

    user_remote_configs = scm_data.get("userRemoteConfigs") or []
    for config in user_remote_configs:
        if isinstance(config, dict):
            url = _extract_first_present(config, "url", "remote")
            if url:
                return url

    return _extract_first_present(scm_data, "url", "remote")


def _extract_branch_specs(scm_data: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(scm_data, dict):
        return []

    branches = scm_data.get("branches") or []
    branch_specs: List[str] = []
    for branch in branches:
        if isinstance(branch, dict):
            name = branch.get("name")
            if name:
                branch_specs.append(name)
        elif isinstance(branch, str) and branch:
            branch_specs.append(branch)
    return branch_specs


def _extract_multibranch_source(
    payload: Dict[str, Any],
) -> tuple[Optional[str], List[str], Optional[str]]:
    repo_url = None
    branch_specs: List[str] = []
    script_path = None

    source_entries = payload.get("branchSources") or payload.get("sources") or []
    for entry in source_entries:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source") or entry.get("scm") or entry
        if isinstance(source, dict):
            if repo_url is None:
                repo_url = _extract_repo_url(source)
            if not branch_specs:
                branch_specs = _extract_branch_specs(source)

    project_factory = payload.get("projectFactory") or payload.get("factory") or {}
    if isinstance(project_factory, dict):
        script_path = project_factory.get("scriptPath")

    return repo_url, branch_specs, script_path


def _xml_text(node: Optional[ET.Element]) -> Optional[str]:
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _parse_job_definition_xml(xml_text: str) -> Dict[str, Any]:
    """Extract pipeline definition details directly from Jenkins job XML."""
    root = ET.fromstring(xml_text)
    result: Dict[str, Any] = {"job_xml_root_tag": root.tag}

    definition = root.find("definition")
    if definition is None:
        return result

    definition_class = definition.get("class")
    if definition_class:
        result["definition_class"] = definition_class

    if definition_class and "CpsScmFlowDefinition" in definition_class:
        result["definition_type"] = "scm_pipeline"
        result["script_path"] = _xml_text(definition.find("scriptPath"))
        remote_urls = [
            text
            for text in (
                _xml_text(node)
                for node in definition.findall(".//userRemoteConfigs/*/url")
            )
            if text
        ]
        branch_specs = [
            text
            for text in (
                _xml_text(node) for node in definition.findall(".//branches/*/name")
            )
            if text
        ]
        result["repo_url"] = remote_urls[0] if remote_urls else None
        result["branch_specs"] = branch_specs
    elif definition_class and "CpsFlowDefinition" in definition_class:
        result["definition_type"] = "inline_pipeline"
        result["inline_script"] = _xml_text(definition.find("script"))
    elif root.tag.endswith("WorkflowMultiBranchProject"):
        result["definition_type"] = "multibranch_pipeline"

    return result


class FindJobsTool(JenkinsOperationTool):
    """Find Jenkins jobs by name/path substring."""

    def __init__(
        self,
        jenkins_client: JenkinsClient,
        multi_jenkins_manager=None,
    ):
        super().__init__(
            jenkins_client=jenkins_client,
            multi_jenkins_manager=multi_jenkins_manager,
        )

    @property
    def name(self) -> str:
        return "find_jobs"

    @property
    def description(self) -> str:
        return (
            "Searches Jenkins jobs by name, full path, or URL so callers can find "
            "the exact pipeline/job identifier before triggering or inspecting it. "
            "Queries a single Jenkins instance per call (resolved from "
            "`jenkins_url`)."
        )

    @property
    def parameters(self) -> List[ParameterSpec]:
        return [
            CommonParameters.jenkins_url_param(),
            ParameterSpec(
                "query",
                str,
                "Case-insensitive substring to match against job name, full path, or URL.",
                required=True,
            ),
            ParameterSpec(
                "limit",
                int,
                f"Maximum number of matching jobs to return (default {DEFAULT_FIND_LIMIT}, max {MAX_FIND_LIMIT}).",
                required=False,
                default=DEFAULT_FIND_LIMIT,
            ),
            ParameterSpec(
                "folder",
                str,
                "Optional folder/job path prefix to constrain the search (for example 'team-a/services').",
                required=False,
                default="",
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        jenkins_url = kwargs["jenkins_url"]
        query = (kwargs["query"] or "").strip().lower()
        limit = _clamp_find_limit(kwargs.get("limit"))
        folder = JobNameParser.normalize_job_name(kwargs.get("folder") or "")

        try:
            instance_id = self.resolve_jenkins_instance(jenkins_url)
            jenkins_client = self.get_jenkins_client(instance_id)
        except Exception as e:
            return {
                "jenkins_url": jenkins_url,
                "query": kwargs["query"],
                "error": f"Jenkins instance resolution failed: {str(e)}",
                "instructions": self.get_instance_instructions(),
            }

        try:
            jobs = jenkins_client.list_jobs()
        except Exception as e:
            return {
                "jenkins_url": jenkins_url,
                "query": kwargs["query"],
                "error": f"Failed to list Jenkins jobs: {str(e)}",
            }

        matches: List[Dict[str, Any]] = []
        folder_prefix = f"{folder}/" if folder else ""
        for job in jobs:
            raw_name = (
                job.get("fullname")
                or job.get("fullName")
                or job.get("name")
                or job.get("displayName")
                or ""
            )
            normalized_name = JobNameParser.normalize_job_name(raw_name)
            if folder and not (
                normalized_name == folder or normalized_name.startswith(folder_prefix)
            ):
                continue

            haystacks = [
                normalized_name.lower(),
                str(job.get("name") or "").lower(),
                str(job.get("displayName") or "").lower(),
                str(job.get("url") or "").lower(),
            ]
            if query not in " ".join(haystacks):
                continue

            matches.append(
                {
                    "job_name": normalized_name,
                    "display_name": job.get("name") or normalized_name.split("/")[-1],
                    "url": job.get("url"),
                    "job_type": job.get("_class") or job.get("type"),
                    "color": job.get("color"),
                }
            )

            if len(matches) >= limit:
                break

        return {
            "jenkins_url": jenkins_url,
            "query": kwargs["query"],
            "folder": folder or None,
            "limit": limit,
            "returned_count": len(matches),
            "jobs": matches,
        }


class GetJobDefinitionTool(JenkinsOperationTool):
    """Inspect a Jenkins job definition and optionally stage config XML for editing."""

    def __init__(
        self,
        jenkins_client: JenkinsClient,
        cache_manager: CacheManager,
        multi_jenkins_manager=None,
    ):
        self.cache_manager = cache_manager
        super().__init__(
            jenkins_client=jenkins_client,
            multi_jenkins_manager=multi_jenkins_manager,
        )

    @property
    def name(self) -> str:
        return "get_job_definition"

    @property
    def description(self) -> str:
        return (
            "Inspects how a Jenkins job is defined. For SCM-backed pipelines, it "
            "returns source-control location details such as repository URL, branch "
            "spec, and Jenkinsfile/script path. For inline or XML-backed jobs, it "
            "returns the inline script when present and, if server-side XML editing "
            "is enabled, downloads the job config XML to a local workspace path and "
            "returns instructions for patching and re-uploading it."
        )

    @property
    def parameters(self) -> List[ParameterSpec]:
        return [
            CommonParameters.job_name_param(),
            CommonParameters.jenkins_url_param(),
            ParameterSpec(
                "max_inline_script_chars",
                int,
                (
                    "Maximum number of inline pipeline script characters to return "
                    f"(default {DEFAULT_INLINE_SCRIPT_CHARS}). Use 0 to omit the "
                    "inline script body."
                ),
                required=False,
                default=DEFAULT_INLINE_SCRIPT_CHARS,
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        jenkins_url = kwargs["jenkins_url"]
        max_inline_script_chars = max(0, kwargs.get("max_inline_script_chars") or 0)
        normalized_job = JobNameParser.normalize_job_name(job_name)

        try:
            instance_id = self.resolve_jenkins_instance(jenkins_url)
            jenkins_client = self.get_jenkins_client(instance_id)
        except Exception as e:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "error": f"Jenkins instance resolution failed: {str(e)}",
                "instructions": self.get_instance_instructions(),
            }

        api_job_path = JobNameParser.to_jenkins_api_path(job_name)
        api_url = f"{jenkins_client.config.url.rstrip('/')}/{api_job_path}/api/json"

        try:
            response = jenkins_client.connection.session.get(
                api_url,
                params={"depth": 2},
                timeout=jenkins_client.config.timeout,
            )
            if response.status_code == 404:
                return {
                    "job_name": normalized_job,
                    "jenkins_url": jenkins_url,
                    "api_url": api_url,
                    "error": "Job not found (HTTP 404).",
                }
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as e:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "api_url": api_url,
                "error": f"Jenkins API request failed: {str(e)}",
            }
        except ValueError as e:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "api_url": api_url,
                "error": f"Invalid JSON response from Jenkins: {str(e)}",
            }

        definition = payload.get("definition") or {}
        definition_class = str(definition.get("class") or "")
        scm_data = definition.get("scm") if isinstance(definition, dict) else None
        repo_url = _extract_repo_url(scm_data)
        branch_specs = _extract_branch_specs(scm_data)
        script_path = (
            definition.get("scriptPath") if isinstance(definition, dict) else None
        )
        inline_script = (
            definition.get("script") if isinstance(definition, dict) else None
        )

        definition_type = "job_config_xml"
        if "CpsScmFlowDefinition" in definition_class:
            definition_type = "scm_pipeline"
        elif "CpsFlowDefinition" in definition_class:
            definition_type = "inline_pipeline"
        elif "WorkflowMultiBranchProject" in str(payload.get("_class") or ""):
            definition_type = "multibranch_pipeline"
            mb_repo_url, mb_branch_specs, mb_script_path = _extract_multibranch_source(
                payload
            )
            repo_url = repo_url or mb_repo_url
            branch_specs = branch_specs or mb_branch_specs
            script_path = script_path or mb_script_path

        config_xml_text = None
        xml_edit_enabled = _xml_editing_enabled(self.multi_jenkins_manager)
        needs_xml_fallback = (
            not definition_class
            or (
                definition_type in {"job_config_xml", "multibranch_pipeline"}
                and not repo_url
                and not inline_script
                and not script_path
            )
            or (definition_type == "scm_pipeline" and (not repo_url or not script_path))
        )
        if needs_xml_fallback or xml_edit_enabled:
            try:
                config_xml_text = jenkins_client.get_job_config_xml(job_name)
            except Exception:
                config_xml_text = None

        if config_xml_text:
            parsed_xml = _parse_job_definition_xml(config_xml_text)
            definition_class = definition_class or parsed_xml.get("definition_class")
            definition_type = parsed_xml.get("definition_type") or definition_type
            repo_url = repo_url or parsed_xml.get("repo_url")
            branch_specs = branch_specs or parsed_xml.get("branch_specs") or []
            script_path = script_path or parsed_xml.get("script_path")
            inline_script = inline_script or parsed_xml.get("inline_script")

        inline_script_truncated = False
        if inline_script and max_inline_script_chars:
            if len(inline_script) > max_inline_script_chars:
                inline_script = inline_script[:max_inline_script_chars]
                inline_script_truncated = True
        elif max_inline_script_chars == 0:
            inline_script = None

        xml_edit_supported = definition_type != "scm_pipeline"
        local_xml_path = None
        edit_instructions = None

        if xml_edit_enabled and xml_edit_supported:
            try:
                xml_text = config_xml_text or jenkins_client.get_job_config_xml(
                    job_name
                )
                xml_path = _job_xml_path(
                    self.cache_manager,
                    self.multi_jenkins_manager,
                    instance_id,
                    normalized_job,
                )
                xml_path.parent.mkdir(parents=True, exist_ok=True)
                xml_path.write_text(xml_text, encoding="utf-8")
                local_xml_path = str(xml_path)
                edit_instructions = (
                    "Jenkins job XML was downloaded locally. Modify that file with "
                    "local patch/edit tools, then call `apply_job_xml_edit` with "
                    "the same `job_name`, `jenkins_url`, and this `local_xml_path` "
                    "to upload the edited config back to Jenkins."
                )
            except Exception as e:
                edit_instructions = (
                    f"XML editing is enabled, but XML download failed: {str(e)}"
                )
        elif definition_type == "scm_pipeline":
            edit_instructions = (
                "This job is SCM-backed. Modify the Jenkinsfile/script in source "
                "control at the returned repository/path instead of editing Jenkins "
                "job XML."
            )
        else:
            edit_instructions = (
                "Server-side XML editing is disabled. To enable it, set "
                "`settings.enable_job_xml_editing: true` in the MCP config."
            )

        return {
            "job_name": normalized_job,
            "jenkins_url": jenkins_url,
            "display_name": payload.get("displayName") or payload.get("name"),
            "job_type": payload.get("_class"),
            "definition_type": definition_type,
            "definition_class": definition_class or None,
            "description": payload.get("description"),
            "url": payload.get("url"),
            "disabled": payload.get("disabled"),
            "source_location": {
                "repo_url": repo_url,
                "branch_specs": branch_specs,
                "script_path": script_path,
            },
            "inline_script": inline_script,
            "inline_script_truncated": inline_script_truncated,
            "xml_editing_enabled": xml_edit_enabled,
            "xml_editing_supported": xml_edit_supported,
            "local_xml_path": local_xml_path,
            "edit_upload_tool": (
                "apply_job_xml_edit" if xml_edit_enabled and local_xml_path else None
            ),
            "edit_instructions": edit_instructions,
        }


class ApplyJobXmlEditTool(JenkinsOperationTool):
    """Upload a locally edited Jenkins job config XML back to Jenkins."""

    def __init__(
        self,
        jenkins_client: JenkinsClient,
        cache_manager: CacheManager,
        multi_jenkins_manager=None,
    ):
        self.cache_manager = cache_manager
        super().__init__(
            jenkins_client=jenkins_client,
            multi_jenkins_manager=multi_jenkins_manager,
        )

    @property
    def name(self) -> str:
        return "apply_job_xml_edit"

    @property
    def description(self) -> str:
        return (
            "Uploads a locally edited Jenkins job config XML back to Jenkins. This "
            "tool is intended for XML files previously downloaded by "
            "`get_job_definition` when server-side XML editing is enabled."
        )

    @property
    def parameters(self) -> List[ParameterSpec]:
        return [
            CommonParameters.job_name_param(),
            CommonParameters.jenkins_url_param(),
            ParameterSpec(
                "local_xml_path",
                str,
                "Absolute path to the locally edited Jenkins config XML file downloaded by get_job_definition.",
                required=True,
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        jenkins_url = kwargs["jenkins_url"]
        local_xml_path = kwargs["local_xml_path"]
        normalized_job = JobNameParser.normalize_job_name(job_name)

        if not _xml_editing_enabled(self.multi_jenkins_manager):
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "local_xml_path": local_xml_path,
                "error": (
                    "Server-side XML editing is disabled. Enable "
                    "`settings.enable_job_xml_editing: true` to use this tool."
                ),
            }

        try:
            instance_id = self.resolve_jenkins_instance(jenkins_url)
            jenkins_client = self.get_jenkins_client(instance_id)
        except Exception as e:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "local_xml_path": local_xml_path,
                "error": f"Jenkins instance resolution failed: {str(e)}",
                "instructions": self.get_instance_instructions(),
            }

        workspace_root = _xml_workspace_root(
            self.cache_manager, self.multi_jenkins_manager
        ).resolve()
        candidate_path = Path(local_xml_path).expanduser().resolve()
        try:
            candidate_path.relative_to(workspace_root)
        except ValueError:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "local_xml_path": local_xml_path,
                "error": (
                    "local_xml_path must be inside the configured Jenkins XML "
                    "workspace directory returned by get_job_definition."
                ),
            }

        if not candidate_path.exists():
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "local_xml_path": local_xml_path,
                "error": "local_xml_path does not exist.",
            }

        if candidate_path.suffix.lower() != ".xml":
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "local_xml_path": local_xml_path,
                "error": "local_xml_path must point to an XML file.",
            }

        try:
            xml_text = candidate_path.read_text(encoding="utf-8")
            jenkins_client.reconfig_job_xml(job_name, xml_text)
        except Exception as e:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "local_xml_path": local_xml_path,
                "error": f"Failed to upload edited Jenkins job XML: {str(e)}",
            }

        return {
            "job_name": normalized_job,
            "jenkins_url": jenkins_url,
            "local_xml_path": str(candidate_path),
            "updated": True,
            "message": "Uploaded edited Jenkins job XML back to Jenkins.",
        }
