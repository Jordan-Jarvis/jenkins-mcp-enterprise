"""Jenkins build triggering and monitoring"""

import time
from typing import Any, Dict, List, Optional

from ..base import Build
from ..exceptions import BuildNotFoundError, JenkinsConnectionError
from ..logging_config import get_component_logger
from .connection_manager import JenkinsConnectionManager

logger = get_component_logger("jenkins.build")


class BuildManager:
    """Handles Jenkins build operations"""

    def __init__(self, connection_manager: JenkinsConnectionManager):
        self.connection = connection_manager

    def get_next_build_number(self, job_name: str) -> int:
        """Get the next build number for a job"""
        try:
            job_info = self.connection.client.get_job_info(job_name)
            return job_info["nextBuildNumber"]
        except Exception as e:
            raise JenkinsConnectionError(
                f"Failed to get next build number for {job_name}: {e}"
            ) from e

    def trigger_build(
        self,
        job_name: str,
        params: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
    ) -> Build:
        """Trigger a Jenkins build and return build information"""
        if params is None:
            params = {}

        # Use provided token or fall back to configured token
        auth_token = token or self.connection.config.token

        try:
            # Check if job exists before triggering
            # It's better to attempt the build and handle the 404, as a separate
            # job_exists check can be slow and racy.
            # if not self.connection.client.job_exists(job_name):
            #     raise BuildNotFoundError(f"Job '{job_name}' not found.")

            queue_item_number = self.connection.client.build_job(
                job_name, parameters=params, token=auth_token
            )

            if not queue_item_number:
                raise JenkinsConnectionError(f"Failed to queue build for {job_name}")

            logger.info(f"Build queued for {job_name}, queue item: {queue_item_number}")

            # Wait for build to start and get build number
            build_number = self._wait_for_build_start(job_name, queue_item_number)

            return Build(
                job_name=job_name,
                build_number=build_number,
                status="STARTED",
                url=f"{self.connection.config.url}/job/{job_name}/{build_number}/",
                parameters=params,
            )

        except Exception as e:
            raise JenkinsConnectionError(
                f"Failed to trigger build for {job_name}: {e}"
            ) from e

    def _wait_for_build_start(
        self, job_name: str, queue_item_number: int, timeout: int = 120
    ) -> int:
        """Wait for a queued build to start and return the build number"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                queue_item = self.connection.client.get_queue_item(queue_item_number)

                if "executable" in queue_item and queue_item["executable"]:
                    build_number = queue_item["executable"]["number"]
                    logger.info(f"Build {job_name}#{build_number} started")
                    return build_number

                time.sleep(2)

            except Exception as e:
                # This can happen if the build starts and leaves the queue
                # before we can query it. In this case, we can try to find
                # the build number from the job's recent builds.
                logger.warning(
                    f"Queue item {queue_item_number} not found, attempting to find recent build for {job_name}"
                )
                try:
                    return self._find_recent_build(job_name)
                except BuildNotFoundError:
                    logger.warning(
                        f"Could not find recent build for {job_name} after queue item disappeared."
                    )
                    # Continue loop in case of a race condition
                    time.sleep(2)

        raise JenkinsConnectionError(
            f"Timeout waiting for build {job_name} to start after {timeout}s"
        )

    def _find_recent_build(self, job_name: str) -> int:
        """Find the most recent build for a job"""
        try:
            job_info = self.connection.client.get_job_info(job_name)
            if job_info["lastBuild"]:
                return job_info["lastBuild"]["number"]
            else:
                raise BuildNotFoundError(f"No builds found for job {job_name}")
        except Exception as e:
            raise JenkinsConnectionError(
                f"Failed to find recent build for {job_name}: {e}"
            ) from e

    def get_build_info(self, job_name: str, build_number: int, depth: int = 1) -> Build:
        """Get information about a specific build"""
        try:
            build_info = self.connection.client.get_build_info(
                job_name, build_number, depth=depth
            )

            # Determine status from build info
            status = "UNKNOWN"
            if build_info.get("result"):
                status = build_info["result"]
            elif build_info.get("building"):
                status = "BUILDING"

            return Build(
                job_name=job_name,
                build_number=build_number,
                status=status,
                url=build_info["url"],
                parameters=self._extract_parameters(build_info),
            )

        except Exception as e:
            raise BuildNotFoundError(
                f"Build {job_name}#{build_number} not found: {e}"
            ) from e

    def _extract_parameters(self, build_info: Dict[str, Any]) -> Dict[str, Any]:
        """Extract build parameters from build info"""
        parameters = {}
        for action in build_info.get("actions", []):
            if action.get("_class") == "hudson.model.ParametersAction":
                for param in action.get("parameters", []):
                    parameters[param["name"]] = param["value"]
        return parameters

    def wait_for_completion(
        self,
        job_name: str,
        build_number: int,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
    ) -> Build:
        """Wait for a build to complete and return final status"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            build = self.get_build_info(job_name, build_number)

            if build.status and build.status not in ["BUILDING", "STARTED"]:
                logger.info(
                    f"Build {job_name}#{build_number} completed with status: {build.status}"
                )
                return build

            logger.debug(f"Build {job_name}#{build_number} still running...")
            time.sleep(poll_interval)

        raise JenkinsConnectionError(
            f"Timeout waiting for build {job_name}#{build_number} to complete after {timeout}s"
        )

    def get_job_parameters(self, job_name: str) -> List[Dict[str, Any]]:
        """Get parameters definition for a job"""
        try:
            job_info = self.connection.client.get_job_info(job_name)
            parameters = []

            for action in job_info.get("actions", []):
                if action.get("_class") == "hudson.model.ParametersDefinitionProperty":
                    for param_def in action.get("parameterDefinitions", []):
                        parameters.append(
                            {
                                "name": param_def.get("name"),
                                "type": param_def.get("type"),
                                "description": param_def.get("description"),
                                "defaultValue": param_def.get(
                                    "defaultParameterValue", {}
                                ).get("value"),
                            }
                        )

            return parameters

        except Exception as e:
            raise JenkinsConnectionError(
                f"Failed to get job parameters for {job_name}: {e}"
            ) from e

    def cancel_build(self, job_name: str, build_number: int) -> bool:
        """Cancel a running build"""
        try:
            self.connection.client.stop_build(job_name, build_number)
            logger.info(f"Cancelled build {job_name}#{build_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel build {job_name}#{build_number}: {e}")
            return False
