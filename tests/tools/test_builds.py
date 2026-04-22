"""Unit tests for ``tools.builds`` (list_job_builds, get_build_info).

These tests do not talk to a real Jenkins server. They stub the
``JenkinsClient`` (and the underlying ``requests`` session) so we can assert
URL construction, parameter handling, error paths, and multi-instance
resolution behavior.
"""

from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import requests

from jenkins_mcp_enterprise.base import ToolResult
from jenkins_mcp_enterprise.tools.builds import (
    DEFAULT_LIST_COUNT,
    DEFAULT_LIST_TREE,
    MAX_LIST_COUNT,
    MIN_LIST_COUNT,
    GetBuildInfoTool,
    ListJobBuildsTool,
    _clamp_count,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    *,
    status_code: int = 200,
    json_payload=None,
    raise_on_json: Optional[Exception] = None,
) -> MagicMock:
    """Build a requests.Response-like MagicMock."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    if raise_on_json is not None:
        response.json.side_effect = raise_on_json
    else:
        response.json.return_value = json_payload if json_payload is not None else {}

    def _raise_for_status():
        if status_code >= 400:
            err = requests.HTTPError(f"HTTP {status_code}")
            err.response = response
            raise err

    response.raise_for_status.side_effect = _raise_for_status
    return response


def _make_jenkins_client(
    *,
    base_url: str = "https://jenkins.example.com",
    timeout: int = 30,
    get_response: Optional[MagicMock] = None,
    get_side_effect: Optional[Exception] = None,
) -> MagicMock:
    """Build a minimal JenkinsClient stand-in with ``.config`` and ``.connection.session``."""
    session = MagicMock()
    if get_side_effect is not None:
        session.get.side_effect = get_side_effect
    else:
        session.get.return_value = (
            get_response
            if get_response is not None
            else _make_response(json_payload={})
        )

    client = MagicMock()
    client.config = SimpleNamespace(url=base_url, timeout=timeout)
    client.connection = SimpleNamespace(session=session)
    return client


# ---------------------------------------------------------------------------
# _clamp_count
# ---------------------------------------------------------------------------


class TestClampCount:
    def test_clamps_below_min(self):
        assert _clamp_count(0) == MIN_LIST_COUNT
        assert _clamp_count(-50) == MIN_LIST_COUNT

    def test_clamps_above_max(self):
        assert _clamp_count(10_000) == MAX_LIST_COUNT

    def test_passthrough_valid(self):
        assert _clamp_count(50) == 50


# ---------------------------------------------------------------------------
# ListJobBuildsTool — static metadata
# ---------------------------------------------------------------------------


class TestListJobBuildsToolMetadata:
    def test_name(self):
        tool = ListJobBuildsTool(jenkins_client=_make_jenkins_client())
        assert tool.name == "list_job_builds"

    def test_description_mentions_url_requirement(self):
        tool = ListJobBuildsTool(jenkins_client=_make_jenkins_client())
        assert "jenkins_url" in tool.description

    def test_parameters_shape(self):
        tool = ListJobBuildsTool(jenkins_client=_make_jenkins_client())
        by_name = {p.name: p for p in tool.parameters}

        assert by_name["job_name"].required is True
        assert by_name["jenkins_url"].required is True
        assert by_name["count"].required is False
        assert by_name["count"].default == DEFAULT_LIST_COUNT
        assert by_name["tree"].required is False

    def test_mcp_schema_required_fields(self):
        tool = ListJobBuildsTool(jenkins_client=_make_jenkins_client())
        schema = tool.to_mcp_schema()
        required = schema["inputSchema"]["required"]
        assert "job_name" in required
        assert "jenkins_url" in required
        assert "count" not in required
        assert "tree" not in required


# ---------------------------------------------------------------------------
# ListJobBuildsTool — behavior
# ---------------------------------------------------------------------------


class TestListJobBuildsToolExecution:
    def test_happy_path_uses_default_tree_and_count(self):
        response = _make_response(
            json_payload={
                "builds": [
                    {"number": 3, "result": "SUCCESS"},
                    {"number": 2, "result": "FAILURE"},
                ]
            }
        )
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        result: ToolResult = tool.execute(
            job_name="TeamA/my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True
        data = result.data
        assert data["job_name"] == "TeamA/my-pipeline"
        assert data["requested_count"] == DEFAULT_LIST_COUNT
        assert data["returned_count"] == 2
        assert len(data["builds"]) == 2

        call = client.connection.session.get.call_args
        assert call.args[0] == (
            "https://jenkins.example.com/job/TeamA/job/my-pipeline/api/json"
        )
        assert call.kwargs["params"]["tree"] == (
            f"{DEFAULT_LIST_TREE}{{0,{DEFAULT_LIST_COUNT}}}"
        )
        assert call.kwargs["timeout"] == client.config.timeout

    def test_numeric_string_count_is_coerced_via_parameter_spec(self):
        """ParameterSpec(int) coerces ``count="42"`` to int before _clamp_count."""
        response = _make_response(json_payload={"builds": []})
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
            count="42",
        )

        assert result.success is True
        tree_arg = client.connection.session.get.call_args.kwargs["params"]["tree"]
        assert tree_arg.endswith("{0,42}")
        assert result.data["requested_count"] == 42

    def test_custom_count_is_applied_and_clamped(self):
        response = _make_response(json_payload={"builds": []})
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
            count=10_000,
        )

        tree_arg = client.connection.session.get.call_args.kwargs["params"]["tree"]
        assert tree_arg.endswith(f"{{0,{MAX_LIST_COUNT}}}")

    def test_custom_tree_override_is_used(self):
        response = _make_response(json_payload={"builds": []})
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        custom_tree = "builds[number,result,description]"
        tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
            count=5,
            tree=custom_tree,
        )

        tree_arg = client.connection.session.get.call_args.kwargs["params"]["tree"]
        assert tree_arg == f"{custom_tree}{{0,5}}"

    def test_empty_tree_override_falls_back_to_default(self):
        response = _make_response(json_payload={"builds": []})
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
            tree="   ",
        )

        tree_arg = client.connection.session.get.call_args.kwargs["params"]["tree"]
        assert tree_arg.startswith(DEFAULT_LIST_TREE)

    def test_base_url_trailing_slash_is_stripped(self):
        response = _make_response(json_payload={"builds": []})
        client = _make_jenkins_client(
            base_url="https://jenkins.example.com/",
            get_response=response,
        )
        tool = ListJobBuildsTool(jenkins_client=client)

        tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        api_url = client.connection.session.get.call_args.args[0]
        assert api_url == "https://jenkins.example.com/job/my-pipeline/api/json"

    def test_leading_slash_and_job_prefixes_are_normalized(self):
        response = _make_response(json_payload={"builds": []})
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        tool.execute(
            job_name="/job/TeamA/job/my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        api_url = client.connection.session.get.call_args.args[0]
        assert api_url == (
            "https://jenkins.example.com/job/TeamA/job/my-pipeline/api/json"
        )

    def test_missing_builds_key_returns_empty_list(self):
        response = _make_response(json_payload={})
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True
        assert result.data["builds"] == []
        assert result.data["returned_count"] == 0

    def test_404_returns_structured_error(self):
        response = _make_response(status_code=404, json_payload={})
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        result = tool.execute(
            job_name="missing-job",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True
        data = result.data
        assert "error" in data
        assert "404" in data["error"]
        assert "builds" not in data

    def test_request_exception_is_captured(self):
        client = _make_jenkins_client(get_side_effect=requests.ConnectionError("boom"))
        tool = ListJobBuildsTool(jenkins_client=client)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True  # tool returns an error dict, not a raised exc
        assert "Jenkins API request failed" in result.data["error"]
        assert "boom" in result.data["error"]

    def test_invalid_json_is_captured(self):
        response = _make_response(raise_on_json=ValueError("not json"))
        client = _make_jenkins_client(get_response=response)
        tool = ListJobBuildsTool(jenkins_client=client)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True
        assert "Invalid JSON response" in result.data["error"]

    def test_missing_required_param_returns_error_result(self):
        client = _make_jenkins_client()
        tool = ListJobBuildsTool(jenkins_client=client)

        result = tool.execute(jenkins_url="https://jenkins.example.com")

        assert result.success is False
        assert "job_name" in (result.error_message or "")

    def test_multi_instance_resolution_failure(self):
        manager = MagicMock()
        manager.resolve_jenkins_url.side_effect = ValueError("no matching instance")
        manager.get_usage_instructions.return_value = "configure instances in YAML"

        tool = ListJobBuildsTool(jenkins_client=None, multi_jenkins_manager=manager)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://unknown.example.com",
        )

        assert result.success is True  # structured error, not a raised exception
        assert "resolution failed" in result.data["error"]
        assert "instructions" in result.data

    def test_multi_instance_resolution_routes_to_resolved_client(self):
        response = _make_response(json_payload={"builds": []})
        resolved_client = _make_jenkins_client(
            base_url="https://jenkins-eu.example.com",
            get_response=response,
        )

        manager = MagicMock()
        manager.resolve_jenkins_url.return_value = "eu"
        manager.get_jenkins_client.return_value = resolved_client

        tool = ListJobBuildsTool(jenkins_client=None, multi_jenkins_manager=manager)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins-eu.example.com",
        )

        assert result.success is True
        manager.resolve_jenkins_url.assert_called_once_with(
            "https://jenkins-eu.example.com"
        )
        manager.get_jenkins_client.assert_called_once_with("eu")
        assert resolved_client.connection.session.get.called


# ---------------------------------------------------------------------------
# GetBuildInfoTool — static metadata
# ---------------------------------------------------------------------------


class TestGetBuildInfoToolMetadata:
    def test_name(self):
        tool = GetBuildInfoTool(jenkins_client=_make_jenkins_client())
        assert tool.name == "get_build_info"

    def test_parameters_shape(self):
        tool = GetBuildInfoTool(jenkins_client=_make_jenkins_client())
        by_name = {p.name: p for p in tool.parameters}

        assert by_name["job_name"].required is True
        assert by_name["jenkins_url"].required is True
        assert by_name["build_number"].required is False
        assert by_name["build_number"].default is None
        assert by_name["depth"].default == 1
        assert by_name["tree"].required is False


# ---------------------------------------------------------------------------
# GetBuildInfoTool — behavior
# ---------------------------------------------------------------------------


class TestGetBuildInfoToolExecution:
    def test_explicit_build_number_url(self):
        response = _make_response(
            json_payload={"number": 42, "result": "SUCCESS", "duration": 1000}
        )
        client = _make_jenkins_client(get_response=response)
        tool = GetBuildInfoTool(jenkins_client=client)

        result = tool.execute(
            job_name="TeamA/my-pipeline",
            jenkins_url="https://jenkins.example.com",
            build_number=42,
        )

        assert result.success is True
        data = result.data
        assert data["requested_build_number"] == 42
        assert data["resolved_build_number"] == 42
        assert data["build"]["result"] == "SUCCESS"

        call = client.connection.session.get.call_args
        assert call.args[0] == (
            "https://jenkins.example.com/job/TeamA/job/my-pipeline/42/api/json"
        )
        assert call.kwargs["params"] == {"depth": 1}

    def test_last_build_when_number_omitted(self):
        response = _make_response(json_payload={"number": 99, "result": "SUCCESS"})
        client = _make_jenkins_client(get_response=response)
        tool = GetBuildInfoTool(jenkins_client=client)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True
        data = result.data
        assert data["requested_build_number"] is None
        assert data["resolved_build_number"] == 99

        api_url = client.connection.session.get.call_args.args[0]
        assert api_url == (
            "https://jenkins.example.com/job/my-pipeline/lastBuild/api/json"
        )

    def test_tree_override_takes_precedence_over_depth(self):
        response = _make_response(json_payload={"number": 5})
        client = _make_jenkins_client(get_response=response)
        tool = GetBuildInfoTool(jenkins_client=client)

        tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
            build_number=5,
            depth=2,
            tree="number,result,description",
        )

        params = client.connection.session.get.call_args.kwargs["params"]
        assert params == {"tree": "number,result,description"}

    def test_custom_depth_is_forwarded(self):
        response = _make_response(json_payload={"number": 5})
        client = _make_jenkins_client(get_response=response)
        tool = GetBuildInfoTool(jenkins_client=client)

        tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
            build_number=5,
            depth=3,
        )

        params = client.connection.session.get.call_args.kwargs["params"]
        assert params == {"depth": 3}

    def test_404_returns_structured_error(self):
        response = _make_response(status_code=404, json_payload={})
        client = _make_jenkins_client(get_response=response)
        tool = GetBuildInfoTool(jenkins_client=client)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
            build_number=999,
        )

        assert result.success is True
        data = result.data
        assert "error" in data
        assert "404" in data["error"]
        assert "build" not in data
        # Error payload must echo the requested build number under the same
        # key used by the success payload (see PR #28 review feedback).
        assert data["requested_build_number"] == 999
        assert "build_number" not in data

    def test_request_exception_is_captured(self):
        client = _make_jenkins_client(
            get_side_effect=requests.Timeout("slow jenkins"),
        )
        tool = GetBuildInfoTool(jenkins_client=client)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True
        data = result.data
        assert "Jenkins API request failed" in data["error"]
        assert "slow jenkins" in data["error"]
        # No explicit build_number was passed, so the lastBuild path is used
        # and requested_build_number is None.
        assert data["requested_build_number"] is None
        assert "build_number" not in data

    def test_invalid_json_is_captured(self):
        response = _make_response(raise_on_json=ValueError("bad payload"))
        client = _make_jenkins_client(get_response=response)
        tool = GetBuildInfoTool(jenkins_client=client)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://jenkins.example.com",
        )

        assert result.success is True
        data = result.data
        assert "Invalid JSON response" in data["error"]
        assert data["requested_build_number"] is None
        assert "build_number" not in data

    def test_multi_instance_resolution_failure(self):
        manager = MagicMock()
        manager.resolve_jenkins_url.side_effect = ValueError("no matching instance")
        manager.get_usage_instructions.return_value = "configure instances"

        tool = GetBuildInfoTool(jenkins_client=None, multi_jenkins_manager=manager)

        result = tool.execute(
            job_name="my-pipeline",
            jenkins_url="https://unknown.example.com",
            build_number=1,
        )

        assert result.success is True
        assert "resolution failed" in result.data["error"]
        assert "instructions" in result.data


# ---------------------------------------------------------------------------
# Factory registration
# ---------------------------------------------------------------------------


def test_tools_are_registered_by_tool_factory():
    """Both new tools should appear in ``ToolFactory.create_tools`` output."""
    from jenkins_mcp_enterprise.di_container import DIContainer
    from jenkins_mcp_enterprise.tool_factory import ToolFactory

    # spec=DIContainer makes isinstance(mock, DIContainer) return True without
    # needing a real container (which would require a full config + Jenkins).
    container = MagicMock(spec=DIContainer)
    container.get_jenkins_client.return_value = MagicMock()
    container.get_cache_manager.return_value = MagicMock()
    vector_manager = MagicMock()
    vector_manager.vector_search_disabled = True
    container.get_vector_manager.return_value = vector_manager
    container.get_multi_jenkins_manager.return_value = None

    factory = ToolFactory(container)
    tools = factory.create_tools()

    assert "list_job_builds" in tools
    assert "get_build_info" in tools
    assert factory.get_tool_count() == 11
