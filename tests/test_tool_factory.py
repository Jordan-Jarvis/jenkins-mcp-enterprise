from unittest.mock import Mock

from jenkins_mcp_enterprise.di_container import DIContainer
from jenkins_mcp_enterprise.tool_factory import ToolFactory


class FakeContainer(DIContainer):
    def __init__(self, vector_search_disabled, xml_editing_enabled=False):
        self._jenkins_client = Mock()
        self._cache_manager = Mock()
        self._multi_jenkins_manager = Mock()
        self._multi_jenkins_manager.settings = {
            "enable_job_xml_editing": xml_editing_enabled
        }
        self._vector_manager = Mock()
        self._vector_manager.vector_search_disabled = vector_search_disabled

    def get_jenkins_client(self):
        return self._jenkins_client

    def get_cache_manager(self):
        return self._cache_manager

    def get_multi_jenkins_manager(self):
        return self._multi_jenkins_manager

    def get_vector_manager(self):
        return self._vector_manager


def test_tool_factory_omits_semantic_search_when_vector_search_disabled():
    factory = ToolFactory(FakeContainer(vector_search_disabled=True))

    tools = factory.create_tools()

    assert "semantic_search" not in tools
    assert "apply_job_xml_edit" not in tools
    assert factory.get_tool_count() == 13


def test_tool_factory_includes_semantic_search_when_vector_search_enabled():
    factory = ToolFactory(FakeContainer(vector_search_disabled=False))

    tools = factory.create_tools()

    assert "semantic_search" in tools
    assert factory.get_tool_count() == 14


def test_tool_factory_registers_xml_edit_tool_only_when_enabled():
    factory = ToolFactory(
        FakeContainer(vector_search_disabled=True, xml_editing_enabled=True)
    )

    tools = factory.create_tools()

    assert "apply_job_xml_edit" in tools
    assert factory.get_tool_count() == 14
