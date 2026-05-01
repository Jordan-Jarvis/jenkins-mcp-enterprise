"""Common utilities and patterns for MCP tools to eliminate code duplication."""

from typing import Any, Dict, List, Optional

from jenkins_mcp_enterprise.base import Build
from jenkins_mcp_enterprise.cache_manager import CacheManager
from jenkins_mcp_enterprise.jenkins.jenkins_client import JenkinsClient
from jenkins_mcp_enterprise.multi_jenkins_manager import MultiJenkinsManager
from jenkins_mcp_enterprise.tools.base_tools import ParameterSpec


class JenkinsResolver:
    """Common Jenkins instance resolution logic used across multiple tools."""

    def __init__(
        self,
        multi_jenkins_manager: Optional[MultiJenkinsManager],
        jenkins_client: Optional[JenkinsClient],
    ):
        self.multi_jenkins_manager = multi_jenkins_manager
        self.jenkins_client = jenkins_client

    def resolve_jenkins_client(
        self, jenkins_url: str, job_name: str, build_number: Optional[int] = None
    ) -> tuple[JenkinsClient, Dict[str, Any]]:
        """
        Resolve Jenkins client from URL.

        Returns:
            Tuple of (jenkins_client, error_dict)
            If successful, error_dict is None
            If failed, jenkins_client is None and error_dict contains error info
        """
        if self.multi_jenkins_manager:
            try:
                instance_id = self.multi_jenkins_manager.resolve_jenkins_url(
                    jenkins_url
                )
                jenkins_client = self.multi_jenkins_manager.get_jenkins_client(
                    instance_id
                )
                return jenkins_client, None
            except Exception as e:
                error_response = {
                    "job_name": job_name,
                    "jenkins_url": jenkins_url,
                    "error": f"Jenkins instance resolution failed: {str(e)}",
                    "instructions": self.multi_jenkins_manager.get_usage_instructions(),
                }
                if build_number is not None:
                    error_response["build_number"] = build_number
                return None, error_response
        else:
            return self.jenkins_client, None


class CommonParameters:
    """Common parameter definitions used across multiple tools."""

    @staticmethod
    def job_name_param() -> ParameterSpec:
        """Standard job_name parameter."""
        return ParameterSpec("job_name", str, "Name of the Jenkins job", required=True)

    @staticmethod
    def build_number_param() -> ParameterSpec:
        """Standard build_number parameter."""
        return ParameterSpec("build_number", int, "Build number", required=True)

    @staticmethod
    def jenkins_url_param() -> ParameterSpec:
        """Standard jenkins_url parameter."""
        return ParameterSpec(
            "jenkins_url",
            str,
            "Jenkins instance URL. Pass the configured Jenkins base URL "
            "(preferred) or a full Jenkins job/build URL rooted under that "
            "instance. REQUIRED - tools resolve exactly one Jenkins instance "
            "per call across multiple servers.",
            required=True,
        )

    @staticmethod
    def standard_build_params() -> List[ParameterSpec]:
        """Standard set of parameters for build-related tools."""
        return [
            CommonParameters.job_name_param(),
            CommonParameters.build_number_param(),
            CommonParameters.jenkins_url_param(),
        ]


class LogFetcher:
    """Common log fetching logic used across multiple tools."""

    def __init__(self, cache_manager: CacheManager, resolver: JenkinsResolver):
        self.cache_manager = cache_manager
        self.resolver = resolver

    def fetch_log(
        self, job_name: str, build_number: int, jenkins_url: str
    ) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Fetch log file for a build.

        Returns:
            Tuple of (log_path, error_dict)
            If successful, error_dict is None
            If failed, log_path is None and error_dict contains error info
        """
        jenkins_client, error = self.resolver.resolve_jenkins_client(
            jenkins_url, job_name, build_number
        )
        if error:
            return None, error

        build_obj = Build(job_name=job_name, build_number=build_number)
        try:
            log_path = self.cache_manager.fetch(jenkins_client, build_obj)
            return log_path, None
        except Exception as e:
            return None, {
                "job_name": job_name,
                "build_number": build_number,
                "jenkins_url": jenkins_url,
                "error": f"Failed to fetch log: {str(e)}",
            }


from ..utils import find_ripgrep
