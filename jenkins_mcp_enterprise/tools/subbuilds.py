from pathlib import Path
from typing import Any, Dict, List

from ..base import ParameterSpec, SubBuild
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

        # Use the RECURSIVE discovery method from SubBuildDiscoverer with higher max_depth
        try:
            sub_builds_objects: List[SubBuild] = jenkins_client.discover_subbuilds(
                parent_job_name,
                parent_build_number,
                max_depth=15,  # Increase depth to catch deeply nested builds
            )
        except Exception as e:
            # If discovery fails, log the error but continue with empty list
            # This prevents the entire tool from failing due to one bad sub-build
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                f"Sub-build discovery failed for {parent_job_name}#{parent_build_number}: {e}"
            )
            sub_builds_objects = []

        # Add progress logging and optional limiting for large pipelines
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"Processing {len(sub_builds_objects)} discovered sub-builds for {parent_job_name}#{parent_build_number}"
        )

        results = []
        for i, sub_build in enumerate(sub_builds_objects):
            # Log progress every 10 items
            if i % 10 == 0 and i > 0:
                logger.info(f"Processed {i}/{len(sub_builds_objects)} sub-builds...")

            # Check if this is a pipeline stage vs a real Jenkins job
            is_pipeline_stage = self._is_pipeline_stage(sub_build, parent_job_name)

            # Try to fetch logs, but handle pipeline stages gracefully
            log_path_obj = None
            log_error = None

            if not is_pipeline_stage:
                try:
                    log_path_obj = self.cache_manager.fetch(jenkins_client, sub_build)
                except Exception as e:
                    log_error = str(e)
                    # For real jobs that fail to fetch logs, this is still an error we want to record
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f"Failed to fetch log for {sub_build.job_name}#{sub_build.build_number}: {e}"
                    )
            else:
                # For pipeline stages, don't try to fetch logs as they're not real Jenkins jobs
                log_path_obj = "N/A (Pipeline Stage)"

            # Final status check - only for real jobs, not pipeline stages
            current_status = sub_build.status
            if not is_pipeline_stage and (
                current_status == "UNKNOWN"
                or current_status == "RUNNING"
                or not current_status
            ):
                try:
                    build_info = jenkins_client.get_build_info(
                        sub_build.job_name, sub_build.build_number, depth=0
                    )
                    final_status = build_info.get("result")
                    if final_status is None and build_info.get("building", False):
                        final_status = "RUNNING"
                    current_status = final_status or current_status or "UNKNOWN"
                except Exception:
                    current_status = sub_build.status

            # Process log path
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
                    "job_name": sub_build.job_name,
                    "build_number": sub_build.build_number,
                    "status": current_status,
                    "log_path": processed_log_path,
                    "url": sub_build.url,
                    "depth": sub_build.depth,
                    "parent_job_name": sub_build.parent_job_name,
                    "parent_build_number": sub_build.parent_build_number,
                    "is_pipeline_stage": is_pipeline_stage,
                }
            )

        return {
            "parent_build": {
                "job_name": parent_job_name,
                "build_number": parent_build_number,
            },
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
