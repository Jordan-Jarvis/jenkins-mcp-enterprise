"""End-to-end tool scenario testing"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from .mcp_test_client import MCPTestClient
from .test_doubles import JenkinsTestDouble, QdrantTestDouble

# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestToolScenarios:
    """Test realistic tool usage scenarios"""

    @pytest.fixture
    async def real_jenkins_config(self):
        """Configuration for testing against real Jenkins instance"""
        # Read credentials from test_jenkins_info.txt
        config = {
            "jenkins_url": "https://jenkins.example.com",
            "jenkins_user": "test.user@example.com",
            "jenkins_token": "test-token-placeholder",
            "cache_dir": "/tmp/test-mcp-jenkins-real",
        }
        return config

    @pytest.mark.asyncio
    async def test_list_tools(self, seeded_jenkins_test_env):
        """Test that all tools are properly exposed via MCP"""
        config = seeded_jenkins_test_env.config

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            tools = await client.list_tools()

            # Verify we have the expected tools
            tool_names = [tool["name"] for tool in tools]
            expected_tools = [
                "trigger_build",
                "trigger_build_async",
                "find_jobs",
                "get_log_context",
                "filter_errors_grep",
                "trigger_build_with_subs",
                "diagnose_build_failure",
                "get_jenkins_job_parameters",
                "get_job_definition",
            ]

            for expected in expected_tools:
                assert (
                    expected in tool_names
                ), f"Tool {expected} not found in {tool_names}"

            # Verify tool schemas are present
            for tool in tools:
                assert "name" in tool
                assert "description" in tool
                assert "inputSchema" in tool

    @pytest.mark.asyncio
    async def test_complete_build_workflow(self, seeded_jenkins_test_env):
        """Test complete workflow: trigger → wait → get logs → analyze"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # 1. Get job parameters first
            params_result = await client.call_tool(
                "get_jenkins_job_parameters",
                {"job_name": "sample-job", "jenkins_url": jenkins_url},
            )

            assert (
                "content" in params_result
            ), f"Tool call failed: {params_result.get('content')}"
            params_data = json.loads(params_result["content"][0]["text"])
            params = params_data.get("parameters", [])
            assert len(params) == 2  # BRANCH and DEPLOY_ENV
            assert params[0]["name"] == "BRANCH"
            assert params[1]["name"] == "DEPLOY_ENV"

            # 2. Trigger build with parameters
            trigger_result = await client.call_tool(
                "trigger_build",
                {
                    "job_name": "sample-job",
                    "params": {"BRANCH": "main", "DEPLOY_ENV": "dev"},
                    "build_complete_timeout": 5,
                    "jenkins_url": jenkins_url,
                },
            )

            if trigger_result.get("isError"):
                pytest.fail(f"Tool call failed: {trigger_result.get('content')}")
            assert (
                "content" in trigger_result
            ), f"Tool call failed: {trigger_result.get('content')}"
            trigger_data = json.loads(trigger_result["content"][0]["text"])
            assert "build_number" in trigger_data
            build_number = trigger_data["build_number"]

            # 3. Get log context
            log_result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "sample-job",
                    "build_number": build_number,
                    "start_line": 0,
                    "end_line": 10,
                    "jenkins_url": jenkins_url,
                },
            )

            assert (
                "content" in log_result
            ), f"Tool call failed: {log_result.get('content')}"
            log_data = json.loads(log_result["content"][0]["text"])
            assert "lines" in log_data
            assert len(log_data["lines"]) > 0

            # 4. Search for errors (should find none in success case)
            error_result = await client.call_tool(
                "filter_errors_grep",
                {
                    "job_name": "sample-job",
                    "build_number": build_number,
                    "pattern": "ERROR|FAILED|Exception",
                    "jenkins_url": jenkins_url,
                },
            )

            assert (
                "content" in error_result
            ), f"Tool call failed: {error_result.get('content')}"
            error_data = json.loads(error_result["content"][0]["text"])
            # Should find no errors in successful build
            assert len(error_data.get("error_blocks", [])) == 0

    @pytest.mark.asyncio
    async def test_build_failure_diagnosis(self, seeded_jenkins_test_env):
        """Test failure diagnosis workflow"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Diagnose the failed master build
            diagnose_result = await client.call_tool(
                "diagnose_build_failure",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "jenkins_url": jenkins_url,
                },
            )

            assert (
                "content" in diagnose_result
            ), f"Tool call failed: {diagnose_result.get('content')}"
            data = json.loads(diagnose_result["content"][0]["text"])

            # Verify diagnosis contains expected elements
            assert "build_summary" in data
            assert "FAILURE" in data["build_summary"]

            assert "sub_builds" in data
            assert len(data["sub_builds"]) > 0
            assert "error_analysis" in data
            assert "errors" in data["error_analysis"]
            assert len(data["error_analysis"]["errors"]) > 0
            assert "recommendations" in data
            assert len(data["recommendations"]) > 0

            # Error analysis should focus on the failing sub-build (not the root job)
            # when skip_successful_builds is true (default).
            assert all(
                e.get("job_name") != "QA_JOBS/master"
                for e in data["error_analysis"]["errors"]
            )

            # Should find ERROR messages in the failed build
            error_found = False
            for error in data["error_analysis"]["errors"]:
                if "ERROR" in error["match_text"]:
                    error_found = True
                    break
            assert error_found, "Should find ERROR in failed build"

            # Parent pointers should be removed from the tree output to save tokens
            # (hierarchy already implies parentage)
            tree = data.get("sub_build_information", {}).get("build_tree", {})
            if isinstance(tree, dict):
                assert "parent_job_name" not in tree
                assert "parent_build_number" not in tree

            assert "recommendations" in data
            assert len(data["recommendations"]) > 0

    @pytest.mark.asyncio
    async def test_diagnose_prunes_passing_branches_by_default(
        self, seeded_jenkins_test_env
    ):
        """By default (skip_successful_builds=True), only show paths leading to failures."""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            diagnose_result = await client.call_tool(
                "diagnose_build_failure",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "jenkins_url": jenkins_url,
                    # skip_successful_builds omitted (default True)
                },
            )

            assert "content" in diagnose_result
            data = json.loads(diagnose_result["content"][0]["text"])

            # In the seeded test data, sub-build-1 is SUCCESS and should be pruned
            # because it is not on a path to a failure.
            names = [b.get("job_name") for b in data.get("sub_builds", [])]
            assert "QA_JOBS/sub-build-1" not in names

            # The failing sub-build should remain.
            assert "QA_JOBS/sub-build-2" in names

    @pytest.mark.asyncio
    async def test_diagnose_includes_all_branches_when_skip_disabled(
        self, seeded_jenkins_test_env
    ):
        """When skip_successful_builds=False, the full tree (including passing branches) is shown."""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            diagnose_result = await client.call_tool(
                "diagnose_build_failure",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "jenkins_url": jenkins_url,
                    "skip_successful_builds": False,
                },
            )

            assert "content" in diagnose_result
            data = json.loads(diagnose_result["content"][0]["text"])

            names = [b.get("job_name") for b in data.get("sub_builds", [])]
            assert "QA_JOBS/sub-build-1" in names
            assert "QA_JOBS/sub-build-2" in names

    @pytest.mark.asyncio
    async def test_async_build_trigger(self, seeded_jenkins_test_env):
        """Test async build triggering"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            result = await client.call_tool(
                "trigger_build_async",
                {
                    "job_name": "sample-job",
                    "params": {"BRANCH": "feature-branch"},
                    "jenkins_url": jenkins_url,
                },
            )

            assert "content" in result, f"Tool call failed: {result.get('content')}"
            data = json.loads(result["content"][0]["text"])
            assert "build_number" in data
            assert "url" in data
            assert "estimated_cache_path" in data
            assert data["estimated_cache_path"].endswith(
                f"{data['build_number']}/console.log"
            )

    @pytest.mark.asyncio
    async def test_sub_build_traversal(self, seeded_jenkins_test_env):
        """Test sub-build discovery and traversal"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            result = await client.call_tool(
                "trigger_build_with_subs",
                {
                    "parent_job_name": "QA_JOBS/master",
                    "parent_build_number": 9,
                    "jenkins_url": jenkins_url,
                },
            )

            assert "content" in result, f"Tool call failed: {result.get('content')}"
            data = json.loads(result["content"][0]["text"])

            assert "parent_build" in data
            assert data["parent_build"]["job_name"] == "QA_JOBS/master"
            assert data["parent_build"]["build_number"] == 9

            assert "sub_builds" in data
            sub_builds = data["sub_builds"]

            # Should find the two sub-builds from test data
            assert len(sub_builds) >= 2

            # Check that sub-builds have expected structure
            for sub_build in sub_builds:
                assert "job_name" in sub_build
                assert "build_number" in sub_build
                assert "status" in sub_build
                assert "log_path" in sub_build
                assert "depth" in sub_build

    @pytest.mark.asyncio
    async def test_grep_pattern_search(self, seeded_jenkins_test_env):
        """Test grep pattern search on logs"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Search for compilation errors in failed build
            result = await client.call_tool(
                "filter_errors_grep",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "pattern": "ERROR.*failure",
                    "jenkins_url": jenkins_url,
                },
            )

            assert "content" in result, f"Tool call failed: {result.get('content')}"
            error_data = json.loads(result["content"][0]["text"])
            errors = error_data.get("error_blocks", [])

            # Should find errors in the failed build
            assert len(errors) > 0

            # Verify error structure
            for error in errors:
                assert "match_line" in error
                assert "match_text" in error
                assert "ERROR" in error["match_text"]

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires real Jenkins instance")
    async def test_real_jenkins_connection(self, real_jenkins_config):
        """Test connection to real Jenkins instance"""
        async with MCPTestClient(
            "jenkins_mcp_enterprise.server", real_jenkins_config
        ) as client:
            # Test listing tools
            tools = await client.list_tools()
            assert len(tools) > 0

            # Test getting build info for the known build
            result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "start_line": 0,
                    "end_line": 20,
                    "jenkins_url": real_jenkins_config["jenkins_url"],
                },
            )

            if not result.get("isError"):
                assert "lines" in result["result"]
                logger.info(
                    f"Successfully retrieved {len(result['result']['lines'])} lines from real Jenkins"
                )
            else:
                logger.warning(
                    f"Could not connect to real Jenkins: {result.get('content', 'Unknown error')}"
                )

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls(self, seeded_jenkins_test_env):
        """Test that multiple tools can be called concurrently"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Execute multiple tool calls concurrently
            tasks = [
                client.call_tool(
                    "get_jenkins_job_parameters",
                    {"job_name": "sample-job", "jenkins_url": jenkins_url},
                ),
                client.call_tool(
                    "get_log_context",
                    {
                        "job_name": "sample-job",
                        "build_number": 1,
                        "start_line": 0,
                        "end_line": 5,
                        "jenkins_url": jenkins_url,
                    },
                ),
                client.call_tool(
                    "filter_errors_grep",
                    {
                        "job_name": "QA_JOBS/master",
                        "build_number": 9,
                        "pattern": "ERROR",
                        "jenkins_url": jenkins_url,
                    },
                ),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All should succeed
            for i, result in enumerate(results):
                assert not isinstance(
                    result, Exception
                ), f"Task {i} raised exception: {result}"
                assert not result.get(
                    "isError"
                ), f"Task {i} failed: {result.get('content', 'Unknown error')}"
