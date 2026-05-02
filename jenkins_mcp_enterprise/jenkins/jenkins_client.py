"""Unified Jenkins client using decomposed services"""

from typing import Any, Dict, List, Optional

from ..base import Build, SubBuild
from ..config import JenkinsConfig
from .build_manager import BuildManager
from .connection_manager import JenkinsConnectionManager
from .log_fetcher import LogFetcher
from .subbuild_discoverer import SubBuildDiscoverer


class JenkinsClient:
    """Unified Jenkins client using decomposed services"""

    def __init__(self, config: JenkinsConfig):
        self.config = config
        self.connection = JenkinsConnectionManager(config)
        self.build_manager = BuildManager(self.connection)
        self.log_fetcher = LogFetcher(self.connection)
        self.subbuild_discoverer = SubBuildDiscoverer(self.connection)

    # Build Management Methods
    def get_next_build_number(self, job_name: str) -> int:
        """Get the next build number for a job"""
        return self.build_manager.get_next_build_number(job_name)

    def trigger_build(
        self,
        job_name: str,
        params: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
    ) -> Build:
        """Trigger a Jenkins build and return build information"""
        return self.build_manager.trigger_build(job_name, params, token)

    def get_build_info(self, job_name: str, build_number: int, depth: int = 1) -> Build:
        """Get information about a specific build"""
        return self.build_manager.get_build_info(job_name, build_number, depth)

    def get_build_info_dict(
        self, job_name: str, build_number: int, depth: int = 1
    ) -> Dict[str, Any]:
        """Get raw build information as dictionary (compatibility method)"""
        return self.connection.client.get_build_info(
            job_name, build_number, depth=depth
        )

    def wait_for_completion(
        self,
        job_name: str,
        build_number: int,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
    ) -> Build:
        """Wait for a build to complete and return final status"""
        return self.build_manager.wait_for_completion(
            job_name, build_number, poll_interval, timeout
        )

    def get_job_parameters(self, job_name: str) -> List[Dict[str, Any]]:
        """Get parameters definition for a job"""
        return self.build_manager.get_job_parameters(job_name)

    def cancel_build(self, job_name: str, build_number: int) -> bool:
        """Cancel a running build"""
        return self.build_manager.cancel_build(job_name, build_number)

    # Log Fetching Methods
    def get_console_log(
        self,
        job_name: str,
        build_number: int,
        start_line: int = 0,
        end_line: Optional[int] = None,
    ) -> List[str]:
        """Fetch console log lines for a build"""
        return self.log_fetcher.get_console_log(
            job_name, build_number, start_line, end_line
        )

    def get_log_size(self, job_name: str, build_number: int) -> int:
        """Get the number of lines in the console log"""
        return self.log_fetcher.get_log_size(job_name, build_number)

    def get_log_chunk(
        self,
        job_name: str,
        build_number: int,
        start_byte: int = 0,
        max_bytes: int = 1024 * 1024,
    ) -> str:
        """Get a chunk of log content by byte range for streaming large logs"""
        return self.log_fetcher.get_log_chunk(
            job_name, build_number, start_byte, max_bytes
        )

    def stream_log_lines(
        self,
        job_name: str,
        build_number: int,
        poll_interval: float = 2.0,
        max_lines: Optional[int] = None,
    ):
        """Generator that yields new log lines as they appear (for live builds)"""
        return self.log_fetcher.stream_log_lines(
            job_name, build_number, poll_interval, max_lines
        )

    # Sub-Build Discovery Methods
    def discover_subbuilds(
        self, parent_job_name: str, parent_build_number: int, max_depth: int = 5
    ) -> List[SubBuild]:
        """Discover all sub-builds for a parent build"""
        return self.subbuild_discoverer.discover_subbuilds(
            parent_job_name, parent_build_number, max_depth
        )

    def get_build_hierarchy(
        self, root_job_name: str, root_build_number: int, max_depth: int = 5
    ) -> Dict[str, Any]:
        """Get the complete build hierarchy as a nested structure"""
        return self.subbuild_discoverer.get_build_hierarchy(
            root_job_name, root_build_number, max_depth
        )

    def find_failed_subbuilds(
        self, parent_job_name: str, parent_build_number: int, max_depth: int = 5
    ) -> List[SubBuild]:
        """Find all failed sub-builds in the hierarchy"""
        return self.subbuild_discoverer.find_failed_subbuilds(
            parent_job_name, parent_build_number, max_depth
        )

    # Connection Management
    def test_connection(self) -> bool:
        """Test if the Jenkins connection is working"""
        return self.connection.test_connection()

    def authenticate(self) -> bool:
        """Test authentication explicitly"""
        return self.connection.authenticate()

    def get_server_info(self) -> Dict[str, Any]:
        """Get Jenkins server information"""
        return self.connection.get_server_info()

    # Compatibility Methods (for existing code)
    def get_whoami(self) -> Dict[str, Any]:
        """Get current user information (compatibility method)"""
        return self.connection.client.get_whoami()

    def get_job_info(self, job_name: str) -> Dict[str, Any]:
        """Get job information (compatibility method)"""
        return self.connection.client.get_job_info(job_name)

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all jobs visible to the configured Jenkins account."""
        return self.connection.client.get_all_jobs()

    def get_job_config_xml(self, job_name: str) -> str:
        """Download the Jenkins job config XML for a job."""
        return self.connection.client.get_job_config(job_name)

    def reconfig_job_xml(self, job_name: str, config_xml: str) -> bool:
        """Upload a modified Jenkins job config XML for a job."""
        self.connection.client.reconfig_job(job_name, config_xml)
        return True

    def get_build_console_output(self, job_name: str, build_number: int) -> str:
        """Get console output as single string (compatibility method)"""
        lines = self.get_console_log(job_name, build_number)
        return "\n".join(lines)

    def get_console_text(self, job_name: str, build_number: int) -> str:
        """Get console text as single string (compatibility method)"""
        return self.get_build_console_output(job_name, build_number)

    def list_sub_builds(self, parent: Build) -> List[SubBuild]:
        """
        List all sub-builds for a parent build (compatibility method).
        This is a wrapper around discover_subbuilds for backward compatibility.
        """
        return self.discover_subbuilds(parent.job_name, parent.build_number)

    def list_pipeline_runs(self, parent: Build) -> List[SubBuild]:
        """
        List pipeline runs for a parent build (compatibility method).
        This is an alias for list_sub_builds as the new implementation
        handles both traditional sub-builds and pipeline runs.
        """
        return self.list_sub_builds(parent)

    @property
    def jenkins_url(self) -> str:
        """Get Jenkins URL (compatibility property)"""
        return self.config.url

    @property
    def jenkins_user(self) -> str:
        """Get Jenkins username (compatibility property)"""
        return self.config.username

    @property
    def jenkins_token(self) -> Optional[str]:
        """Get Jenkins token (compatibility property)"""
        return self.config.token

    @property
    def timeout(self) -> int:
        """Get timeout setting (compatibility property)"""
        return self.config.timeout
