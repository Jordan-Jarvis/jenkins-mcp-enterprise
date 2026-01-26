"""MCP test infrastructure validation"""

import asyncio
import os
import shutil
import tempfile

import pytest
import pytest_asyncio

from .mcp_test_client import MCPTestClient
from .test_doubles import JenkinsTestDouble, QdrantTestDouble


class TestInfrastructure:
    """Test MCP infrastructure and protocol compliance"""


    @pytest.mark.asyncio
    async def test_jenkins_mcp_enterprise_startup(self, seeded_jenkins_test_env):
        """Test that MCP server starts up correctly"""
        config = seeded_jenkins_test_env.config

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Server should start without errors
            assert client.process is not None
            assert client.process.returncode is None  # Process should still be running

    @pytest.mark.asyncio
    async def test_mcp_protocol_compliance(self, seeded_jenkins_test_env):
        """Test MCP protocol compliance"""
        config = seeded_jenkins_test_env.config

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Test tools/list endpoint
            tools = await client.list_tools()

            assert isinstance(tools, list)
            assert len(tools) > 0

            # Each tool should have required MCP schema fields
            for tool in tools:
                assert "name" in tool
                assert "description" in tool
                assert "inputSchema" in tool

                schema = tool["inputSchema"]
                assert "type" in schema
                assert schema["type"] == "object"
                assert "properties" in schema

    @pytest.mark.asyncio
    async def test_json_rpc_format(self, seeded_jenkins_test_env):
        """Test JSON-RPC format compliance"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Test that responses follow JSON-RPC 2.0 format
            result = await client.call_tool(
                "get_job_parameters",
                {"job_name": "any-job", "jenkins_url": jenkins_url},
            )

            # Should have JSON-RPC 2.0 structure
            if result.get("isError"):
                assert "content" in result
            else:
                assert "jsonrpc" in result
                assert result["jsonrpc"] == "2.0"
                assert "id" in result
                assert "result" in result

    @pytest.mark.asyncio
    async def test_error_response_format(self, seeded_jenkins_test_env):
        """Test that error responses follow MCP format"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Trigger an error by calling with invalid parameters
            result = await client.call_tool(
                "trigger_build_async", {"jenkins_url": jenkins_url}
            )

            assert result.get("isError") is True
            assert "content" in result
            error_msg = result["content"][0]["text"].lower()
            assert "validation" in error_msg or "required" in error_msg

    @pytest.mark.asyncio
    async def test_tool_parameter_validation(self, seeded_jenkins_test_env):
        """Test that tool parameter validation works correctly"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            tools = await client.list_tools()

            # Find a tool with required parameters
            trigger_tool = None
            for tool in tools:
                if tool["name"] == "trigger_build_async":
                    trigger_tool = tool
                    break

            assert trigger_tool is not None

            # Check that job_name is required
            schema = trigger_tool["inputSchema"]
            assert "job_name" in schema["required"]

            # Test calling without required parameter
            result = await client.call_tool(
                "trigger_build_async", {"jenkins_url": jenkins_url}
            )
            assert result.get("isError") is True

            # Test calling with required parameter
            result = await client.call_tool(
                "trigger_build_async",
                {"job_name": "test-job", "jenkins_url": jenkins_url},
            )

            # Should either succeed or fail with a different error (not parameter validation)
            if result.get("isError"):
                error_msg = result["content"][0]["text"].lower()
                assert "required" not in error_msg and "job_name" not in error_msg

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, seeded_jenkins_test_env):
        """Test that server handles concurrent requests correctly"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Send multiple concurrent requests
            tasks = [
                client.list_tools(),
                client.call_tool(
                    "get_job_parameters",
                    {"job_name": "test-job", "jenkins_url": jenkins_url},
                ),
                client.call_tool(
                    "trigger_build_async",
                    {"job_name": "test-job", "jenkins_url": jenkins_url},
                ),
                client.list_tools(),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All should complete without exceptions
            for i, result in enumerate(results):
                assert not isinstance(
                    result, Exception
                ), f"Request {i} failed: {result}"

            # First and last results should be identical (tools list)
            assert results[0] == results[3]

    @pytest.mark.asyncio
    async def test_server_shutdown_cleanup(self, seeded_jenkins_test_env):
        """Test that server shuts down cleanly"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        client = MCPTestClient("jenkins_mcp_enterprise.server", config)

        # Start server
        await client.start_server()

        # Verify it's running
        assert client.process is not None
        assert client.process.returncode is None

        # Call a tool to verify it's responding
        result = await client.call_tool(
            "get_job_parameters",
            {"job_name": "test", "jenkins_url": jenkins_url},
        )
        assert "result" in result or result.get("isError")

        # Stop server
        await client.stop_server()

        # Verify it's stopped
        assert client.process.returncode is not None  # Process should have exited

    @pytest.mark.asyncio
    async def test_tool_execution_isolation(self, seeded_jenkins_test_env):
        """Test that tool executions are properly isolated"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Execute tools that might have side effects
            results = []

            for i in range(3):
                result = await client.call_tool(
                    "trigger_build_async",
                    {
                        "job_name": "isolation-test",
                        "params": {"TEST_ID": str(i)},
                        "jenkins_url": jenkins_url,
                    },
                )
                results.append(result)

            # Each execution should be independent
            for i, result in enumerate(results):
                if "result" in result:
                    # If successful, should have unique build numbers or similar
                    data = result["result"]
                    assert "job_name" in data
                    assert data["job_name"] == "isolation-test"

    @pytest.mark.asyncio
    async def test_large_response_handling(self, seeded_jenkins_test_env):
        """Test handling of large responses"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Request a potentially large response
            result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "test-job",
                    "build_number": 1,
                    "start_line": 0,
                    "end_line": 10000,  # Large range
                    "jenkins_url": jenkins_url,
                },
            )

            # Should handle large responses gracefully
            if "result" in result:
                log_data = result["result"]
                assert isinstance(log_data, dict)
            else:
                assert "content" in result
                assert "isError" in result

    @pytest.mark.asyncio
    async def test_request_timeout_handling(self, seeded_jenkins_test_env):
        """Test request timeout handling"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Test with very short timeout
            try:
                result = await client.call_tool(
                    "diagnose_build_failure",
                    {
                        "job_name": "test-job",
                        "build_number": 1,
                        "jenkins_url": jenkins_url,
                    },
                    timeout=0.1,
                )

                # If it completes, that's fine
                assert "result" in result or result.get("isError")

            except asyncio.TimeoutError:
                # Timeout is also acceptable behavior
                pass
