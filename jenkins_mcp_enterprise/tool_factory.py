"""Tool factory for explicit dependency injection

This module provides a clean factory for creating tool instances with
their required dependencies explicitly injected, replacing the
reflection-based approach.

Key Features:
- Explicit dependency injection for all tools
- Type-safe tool creation
- Clear mapping between tools and their dependencies
- Proper error handling for missing dependencies
"""

from typing import Dict

from .base import Tool
from .di_container import DIContainer
from .tools.diagnostics import DiagnoseBuildFailureTool
from .tools.jenkins_tools import GetJobParametersTool
from .tools.logs import FilterErrorsTool, LogContextTool
from .tools.ripgrep_tool import NavigateLogTool, RipgrepSearchTool
from .tools.search import SemanticSearchTool
from .tools.subbuilds import SubBuildTraversalTool

# Import all tool classes
from .tools.trigger import AsyncBuildTool, TriggerBuildTool


class ToolFactory:
    """Factory for creating tool instances with explicit dependency injection.

    This factory creates all tools with their required dependencies
    explicitly injected, eliminating the need for reflection-based
    dependency discovery.
    """

    def __init__(self, container: DIContainer) -> None:
        """Initialize the tool factory with a dependency container.

        Args:
            container: The dependency injection container with all required managers

        Raises:
            TypeError: If container is not a DIContainer instance
        """
        if not isinstance(container, DIContainer):
            raise TypeError("container must be a DIContainer instance")

        self.container = container

    def create_tools(self) -> Dict[str, Tool]:
        """Create all tool instances with their dependencies explicitly injected.

        Returns:
            Dictionary mapping tool names to their instances

        Raises:
            ValueError: If any required dependencies are missing from the container
        """
        # Get all required dependencies from the container
        jenkins_client = self.container.get_jenkins_client()
        cache_manager = self.container.get_cache_manager()
        vector_manager = self.container.get_vector_manager()
        multi_jenkins_manager = self.container.get_multi_jenkins_manager()

        # Create tool instances with explicit dependency injection
        tools = {}

        # Tools requiring only JenkinsClient (now with multi-instance support)
        trigger_tool = TriggerBuildTool(
            jenkins_client=jenkins_client, multi_jenkins_manager=multi_jenkins_manager
        )
        tools[trigger_tool.name] = trigger_tool

        get_params_tool = GetJobParametersTool(
            jenkins_client=jenkins_client, multi_jenkins_manager=multi_jenkins_manager
        )
        tools[get_params_tool.name] = get_params_tool

        # Tools requiring JenkinsClient and CacheManager (now with multi-instance support)
        async_tool = AsyncBuildTool(
            jenkins_client=jenkins_client,
            cache_manager=cache_manager,
            multi_jenkins_manager=multi_jenkins_manager,
        )
        tools[async_tool.name] = async_tool

        subbuild_tool = SubBuildTraversalTool(
            jenkins_client=jenkins_client,
            cache_manager=cache_manager,
            multi_jenkins_manager=multi_jenkins_manager,
        )
        tools[subbuild_tool.name] = subbuild_tool

        log_context_tool = LogContextTool(
            cache_manager=cache_manager,
            jenkins_client=jenkins_client,
            multi_jenkins_manager=multi_jenkins_manager,
        )
        tools[log_context_tool.name] = log_context_tool

        filter_errors_tool = FilterErrorsTool(
            cache_manager=cache_manager,
            jenkins_client=jenkins_client,
            multi_jenkins_manager=multi_jenkins_manager,
        )
        tools[filter_errors_tool.name] = filter_errors_tool

        # Ripgrep-based navigation tools
        ripgrep_tool = RipgrepSearchTool(
            cache_manager=cache_manager,
            jenkins_client=jenkins_client,
            multi_jenkins_manager=multi_jenkins_manager,
        )
        tools[ripgrep_tool.name] = ripgrep_tool

        navigate_tool = NavigateLogTool(
            cache_manager=cache_manager,
            jenkins_client=jenkins_client,
            multi_jenkins_manager=multi_jenkins_manager,
        )
        tools[navigate_tool.name] = navigate_tool

        # Tools requiring JenkinsClient, CacheManager, and VectorManager (now with multi-instance support)
        # Only register semantic search tool if vector search is enabled
        if not getattr(vector_manager, 'vector_search_disabled', True):
            semantic_search_tool = SemanticSearchTool(
                vector_manager=vector_manager,
                jenkins_client=jenkins_client,
                cache_manager=cache_manager,
                multi_jenkins_manager=multi_jenkins_manager,
            )
            tools[semantic_search_tool.name] = semantic_search_tool

        diagnose_tool = DiagnoseBuildFailureTool(
            jenkins_client=jenkins_client,
            cache_manager=cache_manager,
            vector_manager=vector_manager,
            multi_jenkins_manager=multi_jenkins_manager,
        )
        tools[diagnose_tool.name] = diagnose_tool

        # Validate that all tools have proper names
        self._validate_tool_names(tools)

        return tools

    def _validate_tool_names(self, tools: Dict[str, Tool]) -> None:
        """Validate that all tool instances have proper name properties.

        Args:
            tools: Dictionary of tool instances to validate

        Raises:
            ValueError: If any tool is missing its name property or has mismatched names
        """
        for tool_name, tool_instance in tools.items():
            if not hasattr(tool_instance, "name"):
                raise ValueError(
                    f"Tool instance {tool_instance.__class__.__name__} "
                    f"is missing the required name property"
                )

            if tool_instance.name != tool_name:
                raise ValueError(
                    f"Tool {tool_instance.__class__.__name__} has name '{tool_instance.name}' "
                    f"but was registered under '{tool_name}'"
                )

    def get_tool_count(self) -> int:
        """Get the expected number of tools that should be created.

        Returns:
            The number of tools this factory creates
        """
        # Base tools count (without vector search tools)
        base_count = 9
        
        # Add vector search tools if enabled
        vector_manager = self.container.get_vector_manager()
        if not getattr(vector_manager, 'vector_search_disabled', True):
            base_count += 1  # semantic_search tool
            
        return base_count
