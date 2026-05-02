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

    def _call_client(self, operation_name: str, callback):
        """Execute a Jenkins client operation, refreshing the client once if stale."""
        try:
            return callback(self.connection.client)
        except Exception as e:
            should_refresh = getattr(
                self.connection, "should_refresh_on_error", lambda _error: False
            )
            if should_refresh(e):
                logger.warning(
                    "%s failed with a stale Jenkins session error; refreshing connection and retrying once: %s",
                    operation_name,
                    e,
                )
                self.connection.refresh_connection()
                return callback(self.connection.client)
            raise

    def _is_missing_queue_item_error(self, error: Exception) -> bool:
        """Return True when Jenkins no longer exposes the queue item."""
        error_type = type(error).__name__.lower()
        message = str(error).lower()
        return (
            "notfound" in error_type
            or "404" in message
            or "not found" in message
            or "does not exist" in message
            or "queue number" in message
        )

    def get_next_build_number(self, job_name: str) -> int:
        """Get the next build number for a job"""
        try:
            job_info = self._call_client(
                f"Get next build number for {job_name}",
                lambda client: client.get_job_info(job_name),
            )
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

        try:
            build_kwargs: Dict[str, Any] = {"parameters": params}
            if token is not None:
                build_kwargs["token"] = token

            queue_item_number = self._call_client(
                f"Trigger build for {job_name}",
                lambda client: client.build_job(job_name, **build_kwargs),
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
                queue_item = self._call_client(
                    f"Poll queue item {queue_item_number} for {job_name}",
                    lambda client: client.get_queue_item(queue_item_number),
                )

                if "executable" in queue_item and queue_item["executable"]:
                    build_number = queue_item["executable"]["number"]
                    logger.info(f"Build {job_name}#{build_number} started")
                    return build_number

                time.sleep(2)

            except Exception as e:
                if self._is_missing_queue_item_error(e):
                    # Queue item disappeared, try to find the build
                    return self._find_recent_build(job_name)
                else:
                    logger.warning(
                        f"Error checking queue item {queue_item_number}: {e}"
                    )
                    time.sleep(2)

        raise JenkinsConnectionError(
            f"Timeout waiting for build {job_name} to start after {timeout}s"
        )

    def _find_recent_build(self, job_name: str) -> int:
        """Find the most recent build for a job"""
        try:
            job_info = self._call_client(
                f"Find recent build for {job_name}",
                lambda client: client.get_job_info(job_name),
            )
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
            build_info = self._call_client(
                f"Get build info for {job_name}#{build_number}",
                lambda client: client.get_build_info(
                    job_name, build_number, depth=depth
                ),
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
            job_info = self._call_client(
                f"Get job parameters for {job_name}",
                lambda client: client.get_job_info(job_name),
            )
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
            self._call_client(
                f"Cancel build {job_name}#{build_number}",
                lambda client: client.stop_build(job_name, build_number),
            )
            logger.info(f"Cancelled build {job_name}#{build_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel build {job_name}#{build_number}: {e}")
            return False
