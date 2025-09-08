"""End-to-end tool scenario testing"""

import asyncio
import logging
import os
from pathlib import Path

import pytest

from .mcp_test_client import MCPTestClient
from .test_doubles import JenkinsTestDouble, QdrantTestDouble

# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestToolScenarios:
    """Test realistic tool usage scenarios"""

    @pytest.fixture
    async def test_environment(self):
        """Setup complete test environment"""
        # Start test doubles
        jenkins = JenkinsTestDouble(port=18080)
        qdrant = QdrantTestDouble(port=16333)

        jenkins.start()
        qdrant.start()

        # Configure MCP client
        config = {
            "jenkins_url": "http://localhost:18080",
            "jenkins_user": "test_user",
            "jenkins_token": "test_token",
            "cache_dir": "/tmp/test-mcp-jenkins",
        }

        yield {"config": config, "jenkins": jenkins, "qdrant": qdrant}

        # Cleanup
        jenkins.stop()
        qdrant.stop()

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
    async def test_list_tools(self, test_environment):
        """Test that all tools are properly exposed via MCP"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            tools = await client.list_tools()

            # Verify we have the expected tools
            tool_names = [tool["name"] for tool in tools]
            expected_tools = [
                "trigger_build",
                "trigger_build_async",
                "get_log_context",
                "filter_errors_grep",
                "trigger_build_with_subs",
                "diagnose_build_failure",
                "get_jenkins_job_parameters",
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
    async def test_complete_build_workflow(self, test_environment):
        """Test complete workflow: trigger → wait → get logs → analyze"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # 1. Get job parameters first
            params_result = await client.call_tool(
                "get_jenkins_job_parameters", {"job_name": "sample-job"}
            )

            assert params_result["success"] is True
            params = params_result["data"]
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
                },
            )

            assert trigger_result["success"] is True
            assert "build_number" in trigger_result["data"]
            build_number = trigger_result["data"]["build_number"]

            # 3. Get log context
            log_result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "sample-job",
                    "build_number": build_number,
                    "start_line": 0,
                    "end_line": 10,
                },
            )

            assert log_result["success"] is True
            assert "lines" in log_result["data"]
            assert len(log_result["data"]["lines"]) > 0

            # 4. Search for errors (should find none in success case)
            error_result = await client.call_tool(
                "filter_errors_grep",
                {
                    "job_name": "sample-job",
                    "build_number": build_number,
                    "pattern": "ERROR|FAILED|Exception",
                },
            )

            assert error_result["success"] is True
            # Should find no errors in successful build
            assert len(error_result["data"]) == 0

    @pytest.mark.asyncio
    async def test_build_failure_diagnosis(self, test_environment):
        """Test failure diagnosis workflow"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Diagnose the failed master  build
            diagnose_result = await client.call_tool(
                "diagnose_build_failure",
                {"job_name": "QA_JOBS/master", "build_number": 9},
            )

            assert diagnose_result["success"] is True
            data = diagnose_result["data"]

            # Verify diagnosis contains expected elements
            assert "build_status" in data
            assert data["build_status"]["result"] == "FAILURE"

            assert "error_analysis" in data
            assert "errors" in data["error_analysis"]
            assert len(data["error_analysis"]["errors"]) > 0

            # Should find ERROR messages in the failed build
            error_found = False
            for error in data["error_analysis"]["errors"]:
                if "ERROR" in error["text"]:
                    error_found = True
                    break
            assert error_found, "Should find ERROR in failed build"

            assert "recommendations" in data
            assert len(data["recommendations"]) > 0

    @pytest.mark.asyncio
    async def test_async_build_trigger(self, test_environment):
        """Test async build triggering"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            result = await client.call_tool(
                "trigger_build_async",
                {"job_name": "sample-job", "params": {"BRANCH": "feature-branch"}},
            )

            assert result["success"] is True
            data = result["data"]
            assert "build_number" in data
            assert "url" in data
            assert "estimated_cache_path" in data
            assert data["estimated_cache_path"].endswith(f"{data['build_number']}.log")

    @pytest.mark.asyncio
    async def test_sub_build_traversal(self, test_environment):
        """Test sub-build discovery and traversal"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            result = await client.call_tool(
                "trigger_build_with_subs",
                {"parent_job_name": "QA_JOBS/master", "parent_build_number": 9},
            )

            assert result["success"] is True
            data = result["data"]

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
    async def test_grep_pattern_search(self, test_environment):
        """Test grep pattern search on logs"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Search for compilation errors in failed build
            result = await client.call_tool(
                "filter_errors_grep",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "pattern": "ERROR.*failure",
                },
            )

            assert result["success"] is True
            errors = result["data"]

            # Should find errors in the failed build
            assert len(errors) > 0

            # Verify error structure
            for error in errors:
                assert "line_number" in error
                assert "text" in error
                assert "ERROR" in error["text"]

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
                },
            )

            if result["success"]:
                assert "lines" in result["data"]
                logger.info(
                    f"Successfully retrieved {len(result['data']['lines'])} lines from real Jenkins"
                )
            else:
                logger.warning(
                    f"Could not connect to real Jenkins: {result.get('error_message', 'Unknown error')}"
                )

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls(self, test_environment):
        """Test that multiple tools can be called concurrently"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Execute multiple tool calls concurrently
            tasks = [
                client.call_tool(
                    "get_jenkins_job_parameters", {"job_name": "sample-job"}
                ),
                client.call_tool(
                    "get_log_context",
                    {
                        "job_name": "sample-job",
                        "build_number": 1,
                        "start_line": 0,
                        "end_line": 5,
                    },
                ),
                client.call_tool(
                    "filter_errors_grep",
                    {
                        "job_name": "QA_JOBS/master",
                        "build_number": 9,
                        "pattern": "ERROR",
                    },
                ),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All should succeed
            for i, result in enumerate(results):
                assert not isinstance(
                    result, Exception
                ), f"Task {i} raised exception: {result}"
                assert (
                    result["success"] is True
                ), f"Task {i} failed: {result.get('error_message', 'Unknown error')}"
