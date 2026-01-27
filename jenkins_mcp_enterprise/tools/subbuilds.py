from pathlib import Path
from typing import Any, Dict, List

from ..base import ParameterSpec, SubBuild
from ..jenkins.build_tree import annotate_build_tree, flatten_build_tree
from ..cache_manager import CacheManager
from ..jenkins.jenkins_client import JenkinsClient
from ..jenkins.job_name_utils import JobNameParser
from .base_tools import JenkinsOperationTool


class SubBuildTraversalTool(JenkinsOperationTool):
    """Lists sub-build statuses and cached log paths for a parent build"""

    def __init__(
        self,
        jenkins_client: JenkinsClient,
        cache_manager: CacheManager,
        multi_jenkins_manager=None,
    ):
        super().__init__(
            jenkins_client=jenkins_client, multi_jenkins_manager=multi_jenkins_manager
        )
        self.cache_manager = cache_manager

    @property
    def name(self) -> str:
        return "trigger_build_with_subs"

    @property
    def description(self) -> str:
        return "Lists sub-build statuses and cached log paths for a given parent build. Fetches logs for sub-builds, including nested ones. IMPORTANT: jenkins_url is required because jobs are load-balanced across multiple Jenkins servers."

    @property
    def parameters(self) -> List[ParameterSpec]:
        return [
            ParameterSpec(
                "parent_job_name", str, "Name of the parent Jenkins job", required=True
            ),
            ParameterSpec(
                "parent_build_number", int, "Parent build number", required=True
            ),
            ParameterSpec(
                "jenkins_url",
                str,
                "Jenkins instance URL (e.g., 'https://jenkins.example.com'). REQUIRED - jobs are load-balanced across multiple servers.",
                required=True,
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        parent_job_name = kwargs["parent_job_name"]
        parent_build_number = kwargs["parent_build_number"]
        jenkins_url = kwargs["jenkins_url"]

        # Normalize job name to handle various formats
        original_job_name = parent_job_name
        parent_job_name = JobNameParser.normalize_job_name(parent_job_name)

        # Resolve Jenkins instance
        try:
            instance_id = self.resolve_jenkins_instance(jenkins_url)
            jenkins_client = self.get_jenkins_client(instance_id)
        except Exception as e:
            return {
                "parent_job_name": parent_job_name,
                "parent_build_number": parent_build_number,
                "jenkins_url": jenkins_url,
                "original_job_name": original_job_name,
                "error": f"Jenkins instance resolution failed: {str(e)}",
                "instructions": self.get_instance_instructions(),
            }

        # Canonical: build an explicit subtree structure from the discovery layer.
        # We keep the legacy flat list (`sub_builds`) for backward compatibility,
        # but the *source of truth* becomes `build_tree`.
        try:
            build_tree = jenkins_client.get_build_hierarchy(
                parent_job_name, parent_build_number, max_depth=15
            )
            annotate_build_tree(build_tree)
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                f"Sub-build hierarchy discovery failed for {parent_job_name}#{parent_build_number}: {e}"
            )
            build_tree = {
                "job_name": parent_job_name,
                "build_number": parent_build_number,
                "status": "UNKNOWN",
                "url": None,
                "depth": 0,
                "children": [],
            }

        # Add progress logging
        import logging

        logger = logging.getLogger(__name__)
        flat_nodes = flatten_build_tree(build_tree)
        # Exclude root from "sub_builds" list
        sub_nodes = [n for n in flat_nodes if n.get("depth", 0) != 0]

        logger.info(
            f"Processing {len(sub_nodes)} discovered sub-builds for {parent_job_name}#{parent_build_number}"
        )

        results = []
        for i, node in enumerate(sub_nodes):
            if i % 10 == 0 and i > 0:
                logger.info(f"Processed {i}/{len(sub_nodes)} sub-builds...")

            job_name = node.get("job_name")
            build_number = int(node.get("build_number") or 0)

            # Keep pipeline-stage heuristic for now (tree discovery can surface stage-like nodes)
            is_pipeline_stage = self._is_pipeline_stage(
                SubBuild(
                    job_name=job_name,
                    build_number=build_number,
                    url=node.get("url"),
                    status=node.get("status"),
                ),
                parent_job_name,
            )

            log_path_obj = None
            log_error = None

            if not is_pipeline_stage:
                try:
                    # Cache manager expects a Build-like object; SubBuild is fine.
                    log_path_obj = self.cache_manager.fetch(
                        jenkins_client,
                        SubBuild(
                            job_name=job_name,
                            build_number=build_number,
                            url=node.get("url"),
                            status=node.get("status"),
                        ),
                    )
                except Exception as e:
                    log_error = str(e)
                    logger.warning(
                        f"Failed to fetch log for {job_name}#{build_number}: {e}"
                    )
            else:
                log_path_obj = "N/A (Pipeline Stage)"

            if log_path_obj is None:
                processed_log_path = (
                    f"ERROR: {log_error}" if log_error else "No log available"
                )
            elif isinstance(log_path_obj, Path):
                processed_log_path = str(log_path_obj.as_posix())
            else:
                processed_log_path = str(log_path_obj)

            results.append(
                {
                    "job_name": job_name,
                    "build_number": build_number,
                    "status": node.get("status") or "UNKNOWN",
                    "log_path": processed_log_path,
                    "url": node.get("url"),
                    "depth": int(node.get("depth") or 0),
                    "parent_job_name": node.get("parent_job_name"),
                    "parent_build_number": node.get("parent_build_number"),
                    "is_pipeline_stage": is_pipeline_stage,
                    # New canonical failure field name
                    "failed": bool(node.get("failed", False)),
                }
            )

        return {
            "parent_build": {
                "job_name": parent_job_name,
                "build_number": parent_build_number,
            },
            "build_tree": build_tree,
            "sub_builds_count": len(results),
            "sub_builds": results,
        }

    def _is_pipeline_stage(self, sub_build: SubBuild, parent_job_name: str) -> bool:
        """
        Determine if a sub-build represents a pipeline stage rather than a real Jenkins job.

        Pipeline stages typically have job names that:
        1. Start with the parent job name as a prefix
        3. Are discovered via the Workflow API rather than traditional build triggers

        Args:
            sub_build: The SubBuild object to check
            parent_job_name: The name of the parent job

        Returns:
            True if this appears to be a pipeline stage, False if it's a real Jenkins job
        """
        job_name = sub_build.job_name

        # Pipeline stages typically start with the parent job name
        if not job_name.startswith(parent_job_name + "/"):
            return False

        # Extract the stage part after the parent job name
        stage_part = job_name[len(parent_job_name) + 1 :]

        # Common pipeline stage patterns
        pipeline_stage_indicators = [
            "jenkinsfile setup",
            "declarative: checkout scm",
            "declarative: tool install",
            "declarative: post actions",
            "stage-",
            "parallel",
            "deploy",
        ]

        # Check if the stage part matches common pipeline stage patterns
        stage_part_lower = stage_part.lower()
        for indicator in pipeline_stage_indicators:
            if indicator in stage_part_lower:
                return True

        # Additional heuristic: if the build number is very low (0-20) and it's nested,
        # it's likely a stage ID rather than a real build number
        if sub_build.build_number <= 20 and "/" in stage_part:
            return True

        # If URL contains "/execution/node/" it's definitely a pipeline stage
        if sub_build.url and "/execution/node/" in sub_build.url:
            return True

        return False
