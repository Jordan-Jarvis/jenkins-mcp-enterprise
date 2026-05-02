"""Tools for enumerating and inspecting Jenkins builds.

These tools let callers select a specific build to act on *before* invoking
log/diagnostic tools:

- ``list_job_builds`` returns recent builds with filterable metadata so an AI
  assistant can pick one by description, duration, timestamp, or result.
- ``get_build_info`` returns metadata for a single build (or ``lastBuild``)
  when the caller already knows which build they want.

Both tools are thin wrappers around Jenkins' ``/api/json`` endpoint using the
already-authenticated HTTP session on ``JenkinsClient``.
"""

from typing import Any, Dict, List, Optional

import requests

from ..base import ParameterSpec
from ..jenkins.jenkins_client import JenkinsClient
from ..jenkins.job_name_utils import JobNameParser
from .base_tools import JenkinsOperationTool
from .common import CommonParameters

DEFAULT_LIST_TREE = (
    "builds[number,result,timestamp,duration,description,displayName,url]"
)
DEFAULT_LIST_COUNT = 25
MAX_LIST_COUNT = 500
MIN_LIST_COUNT = 1
DEFAULT_BUILDS_BEFORE = 3
DEFAULT_BUILDS_AFTER = 2


def _clamp_count(value: int) -> int:
    """Clamp ``count`` to ``[MIN_LIST_COUNT, MAX_LIST_COUNT]``.

    ``ParameterSpec("count", int, ..., default=DEFAULT_LIST_COUNT)`` at the
    tool boundary coerces numeric strings to ``int`` and supplies the default
    when the parameter is omitted, so this helper only has to enforce range.
    """
    return max(MIN_LIST_COUNT, min(value, MAX_LIST_COUNT))


class ListJobBuildsTool(JenkinsOperationTool):
    """Lists recent builds of a Jenkins job with metadata for filtering."""

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
        return "list_job_builds"

    @property
    def description(self) -> str:
        return (
            "Returns recent builds for a Jenkins job with metadata "
            "(number, result, timestamp, duration, description, displayName, url), "
            "so callers can pick a specific build by criteria before calling "
            "log-analysis tools. Can also return a small window of builds around "
            "a specific build number instead of the full recent list. Queries a "
            "single Jenkins instance per call "
            "(resolved from `jenkins_url`); does not aggregate across configured "
            "instances. IMPORTANT: jenkins_url is required because jobs are "
            "load-balanced across multiple Jenkins servers."
        )

    @property
    def parameters(self) -> List[ParameterSpec]:
        return [
            CommonParameters.job_name_param(),
            CommonParameters.jenkins_url_param(),
            ParameterSpec(
                "count",
                int,
                (
                    f"Maximum number of recent builds to return "
                    f"(default {DEFAULT_LIST_COUNT}, min {MIN_LIST_COUNT}, "
                    f"max {MAX_LIST_COUNT})."
                ),
                required=False,
                default=DEFAULT_LIST_COUNT,
            ),
            ParameterSpec(
                "tree",
                str,
                (
                    "Optional Jenkins 'tree' filter for the builds[] array, without "
                    "the trailing range. Example: 'builds[number,result,description]'. "
                    "When omitted, a default tree with common metadata fields is used."
                ),
                required=False,
                default="",
            ),
            ParameterSpec(
                "around_build_number",
                int,
                (
                    "Optional build number to center a build window around. "
                    "When provided, the response includes only nearby builds "
                    "from the fetched set."
                ),
                required=False,
                default=None,
            ),
            ParameterSpec(
                "before",
                int,
                (
                    "How many older builds to include before around_build_number "
                    f"(default {DEFAULT_BUILDS_BEFORE}). Ignored unless "
                    "around_build_number is provided."
                ),
                required=False,
                default=DEFAULT_BUILDS_BEFORE,
            ),
            ParameterSpec(
                "after",
                int,
                (
                    "How many newer builds to include after around_build_number "
                    f"(default {DEFAULT_BUILDS_AFTER}). Ignored unless "
                    "around_build_number is provided."
                ),
                required=False,
                default=DEFAULT_BUILDS_AFTER,
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        jenkins_url = kwargs["jenkins_url"]
        effective_count = _clamp_count(kwargs.get("count"))
        tree_override = (kwargs.get("tree") or "").strip()
        around_build_number: Optional[int] = kwargs.get("around_build_number")
        before = max(0, kwargs.get("before") or 0)
        after = max(0, kwargs.get("after") or 0)

        # Compute the canonical echo up-front so every return path shows the
        # same job_name value. to_jenkins_api_path() normalizes internally,
        # so pass raw input there and reuse normalized_job only in responses.
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
        base_url = jenkins_client.config.url.rstrip("/")
        base_tree = tree_override if tree_override else DEFAULT_LIST_TREE
        if around_build_number is not None and "number" not in base_tree:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "error": (
                    "around_build_number requires build numbers in the selected "
                    "tree. Include 'number' in the tree filter or omit the tree "
                    "override."
                ),
            }
        tree_value = f"{base_tree}{{0,{effective_count}}}"
        api_url = f"{base_url}/{api_job_path}/api/json"

        try:
            response = jenkins_client.connection.session.get(
                api_url,
                params={"tree": tree_value},
                timeout=jenkins_client.config.timeout,
            )
            if response.status_code == 404:
                return {
                    "job_name": normalized_job,
                    "jenkins_url": jenkins_url,
                    "api_url": api_url,
                    "error": (
                        "Job not found (HTTP 404). Verify the job_name and "
                        "that the account has permission to view it."
                    ),
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

        builds = payload.get("builds") or []
        if around_build_number is not None:
            match_index = next(
                (
                    idx
                    for idx, build in enumerate(builds)
                    if build.get("number") == around_build_number
                ),
                None,
            )
            if match_index is None:
                return {
                    "job_name": normalized_job,
                    "jenkins_url": jenkins_url,
                    "tree": tree_value,
                    "requested_count": effective_count,
                    "around_build_number": around_build_number,
                    "error": (
                        "around_build_number was not present in the fetched build "
                        "set. Increase count or query a more recent build."
                    ),
                }

            start = max(0, match_index - before)
            end = min(len(builds), match_index + after + 1)
            builds = builds[start:end]

        return {
            "job_name": normalized_job,
            "jenkins_url": jenkins_url,
            "tree": tree_value,
            "requested_count": effective_count,
            "around_build_number": around_build_number,
            "before": before,
            "after": after,
            "returned_count": len(builds),
            "builds": builds,
        }


class GetBuildInfoTool(JenkinsOperationTool):
    """Fetches metadata for a single Jenkins build (or ``lastBuild``)."""

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
        return "get_build_info"

    @property
    def description(self) -> str:
        return (
            "Returns metadata for a single Jenkins build (number, result, "
            "timestamp, duration, description, parameters, url, ...). When "
            "build_number is omitted, the job's 'lastBuild' is returned. "
            "Queries a single Jenkins instance per call (resolved from "
            "`jenkins_url`); does not aggregate across configured instances. "
            "IMPORTANT: jenkins_url is required because jobs are load-balanced "
            "across multiple Jenkins servers."
        )

    @property
    def parameters(self) -> List[ParameterSpec]:
        return [
            CommonParameters.job_name_param(),
            CommonParameters.jenkins_url_param(),
            ParameterSpec(
                "build_number",
                int,
                "Build number to fetch. If omitted, the job's 'lastBuild' is returned.",
                required=False,
                default=None,
            ),
            ParameterSpec(
                "depth",
                int,
                (
                    "Jenkins API 'depth' parameter controlling nested field "
                    "expansion (default 1). Ignored when 'tree' is provided."
                ),
                required=False,
                default=1,
            ),
            ParameterSpec(
                "tree",
                str,
                (
                    "Optional Jenkins 'tree' filter to restrict returned fields. "
                    "Example: 'number,result,timestamp,description'. "
                    "If omitted, 'depth' is used instead."
                ),
                required=False,
                default="",
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        jenkins_url = kwargs["jenkins_url"]
        build_number: Optional[int] = kwargs.get("build_number")
        depth = kwargs.get("depth") if kwargs.get("depth") is not None else 1
        tree_override = (kwargs.get("tree") or "").strip()

        # Compute the canonical echo up-front so every return path shows the
        # same job_name value. to_jenkins_api_path() normalizes internally,
        # so pass raw input there and reuse normalized_job only in responses.
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
        base_url = jenkins_client.config.url.rstrip("/")
        build_segment = str(build_number) if build_number is not None else "lastBuild"
        api_url = f"{base_url}/{api_job_path}/{build_segment}/api/json"
        params: Dict[str, Any] = (
            {"tree": tree_override} if tree_override else {"depth": depth}
        )

        try:
            response = jenkins_client.connection.session.get(
                api_url,
                params=params,
                timeout=jenkins_client.config.timeout,
            )
            if response.status_code == 404:
                return {
                    "job_name": normalized_job,
                    "jenkins_url": jenkins_url,
                    "requested_build_number": build_number,
                    "api_url": api_url,
                    "error": (
                        "Build not found (HTTP 404). The job may not exist, "
                        "have no builds yet, or the specified build number "
                        "may be out of range."
                    ),
                }
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as e:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "requested_build_number": build_number,
                "api_url": api_url,
                "error": f"Jenkins API request failed: {str(e)}",
            }
        except ValueError as e:
            return {
                "job_name": normalized_job,
                "jenkins_url": jenkins_url,
                "requested_build_number": build_number,
                "api_url": api_url,
                "error": f"Invalid JSON response from Jenkins: {str(e)}",
            }

        return {
            "job_name": normalized_job,
            "jenkins_url": jenkins_url,
            "requested_build_number": build_number,
            "resolved_build_number": payload.get("number"),
            "build": payload,
        }
