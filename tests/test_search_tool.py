from unittest.mock import Mock

from jenkins_mcp_enterprise.tools.search import SemanticSearchTool


def test_semantic_search_returns_structured_results():
    vector_manager = Mock()
    vector_manager.vector_search_disabled = False
    vector_manager.search_hierarchical.return_value = [
        {
            "content": "ERROR: synthetic failure marker",
            "score": 0.93,
            "payload": {"job_name": "job", "build_number": 1},
        }
    ]

    tool = SemanticSearchTool(
        vector_manager=vector_manager,
        jenkins_client=Mock(),
        cache_manager=Mock(),
        multi_jenkins_manager=Mock(),
    )
    tool.resolve_jenkins_instance = Mock(return_value="demo")

    result = tool.execute(
        job_name="job",
        build_number=1,
        jenkins_url="http://jenkins.example",
        query_text="What caused the failure?",
        top_k=3,
    )

    assert result.success is True
    assert result.data["results_count"] == 1
    assert result.data["results"][0]["text"] == "ERROR: synthetic failure marker"
    assert result.data["results"][0]["score"] == 0.93


def test_semantic_search_fails_cleanly_when_vector_search_disabled():
    vector_manager = Mock()
    vector_manager.vector_search_disabled = True

    tool = SemanticSearchTool(
        vector_manager=vector_manager,
        jenkins_client=Mock(),
        cache_manager=Mock(),
        multi_jenkins_manager=Mock(),
    )

    result = tool.execute(
        job_name="job",
        build_number=1,
        jenkins_url="http://jenkins.example",
        query_text="What caused the failure?",
        top_k=3,
    )

    assert result.success is False
    assert "Vector search is disabled" in result.error_message
