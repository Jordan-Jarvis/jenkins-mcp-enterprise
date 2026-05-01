import sys
from typing import Any, Dict, List

from ..base import Build, ParameterSpec
from ..cache_manager import CacheManager
from ..exceptions import VectorStoreError
from ..jenkins.jenkins_client import JenkinsClient
from ..logging_config import get_component_logger
from ..vector_manager import VectorManager
from .base_tools import JenkinsOperationTool
from .common import CommonParameters

# Get logger for this component
logger = get_component_logger("search_tool")


class SemanticSearchTool(JenkinsOperationTool):
    """Performs semantic similarity search on embedded log chunks for failure analysis"""

    def __init__(
        self,
        vector_manager: VectorManager,
        jenkins_client: JenkinsClient,
        cache_manager: CacheManager,
        multi_jenkins_manager=None,
    ):
        super().__init__(
            jenkins_client=jenkins_client, multi_jenkins_manager=multi_jenkins_manager
        )
        self.vector_manager = vector_manager
        self.jenkins_client = jenkins_client
        self.cache_manager = cache_manager
        self.multi_jenkins_manager = multi_jenkins_manager

    @property
    def name(self) -> str:
        return "semantic_search"

    @property
    def description(self) -> str:
        return "Finds relevant log content using AI similarity search on Jenkins build logs. Ideal for finding stack traces, error patterns, and failure causes. Available only when vector search is enabled. IMPORTANT: jenkins_url is required because jobs may be distributed across multiple Jenkins servers."

    @property
    def parameters(self) -> List[ParameterSpec]:
        return CommonParameters.standard_build_params() + [
            ParameterSpec("query_text", str, "Text to search for", required=True),
            ParameterSpec(
                "top_k",
                int,
                "Number of top results to return",
                required=False,
                default=5,
            ),
        ]

    def _execute_impl(self, **kwargs) -> Dict[str, Any]:
        job_name = kwargs["job_name"]
        build_number = kwargs["build_number"]
        jenkins_url = kwargs["jenkins_url"]
        query_text = kwargs["query_text"]
        top_k = kwargs["top_k"]

        if not self.vector_manager or getattr(
            self.vector_manager, "vector_search_disabled", True
        ):
            raise VectorStoreError(
                "Vector search is disabled for this server configuration"
            )

        # Resolve Jenkins instance from required URL
        try:
            instance_id = self.resolve_jenkins_instance(jenkins_url)
        except Exception as e:
            return [
                {
                    "error": f"Jenkins instance resolution failed: {str(e)}",
                    "instructions": self.get_instance_instructions(),
                }
            ]

        build_obj = Build(job_name=job_name, build_number=build_number)

        # Use the hierarchical search method instead of legacy query
        try:
            results = self.vector_manager.search_hierarchical(
                query_text=query_text, root_build=build_obj, top_k=top_k
            )

        except Exception as e:
            logger.error(f"Failed to search vectors ({job_name} #{build_number}): {e}")
            raise VectorStoreError(f"Cannot perform vector search: {e}") from e

        formatted_results = []
        for idx, result in enumerate(results):
            formatted_results.append(
                {
                    "build": {"job_name": job_name, "build_number": build_number},
                    "chunk_index": idx,
                    "text": result.get("content", ""),
                    "score": result.get("score", 0.0),
                    "metadata": result.get("payload", {}),
                }
            )

        return {
            "build": {"job_name": job_name, "build_number": build_number},
            "query_text": query_text,
            "top_k": top_k,
            "results_count": len(formatted_results),
            "results": formatted_results,
        }
