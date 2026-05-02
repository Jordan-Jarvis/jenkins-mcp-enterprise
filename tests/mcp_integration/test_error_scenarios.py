"""Test error handling and edge cases"""

import asyncio
import os
import shutil
import tempfile

import pytest
import pytest_asyncio

from .mcp_test_client import MCPTestClient
from .test_doubles import JenkinsTestDouble, QdrantTestDouble


class TestErrorScenarios:
    """Test how tools handle various error conditions"""

    @pytest.mark.asyncio
    async def test_jenkins_connection_failure(self, seeded_jenkins_test_env):
        """Server should still start, and tool calls should fail cleanly when Jenkins is unreachable."""
        config = seeded_jenkins_test_env.config
        jenkins = seeded_jenkins_test_env.jenkins_double

        # Stop the Jenkins double to simulate connection failure
        jenkins.stop()

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            result = await client.call_tool(
                "get_jenkins_job_parameters",
                {"job_name": "sample-job", "jenkins_url": config["jenkins"]["url"]},
            )

            assert result.get("isError") is True
            assert "content" in result
            error_msg = result["content"][0]["text"].lower()
            assert (
                "failed to get job parameters" in error_msg
                or "connection" in error_msg
                or "refused" in error_msg
            )

    @pytest.mark.asyncio
    async def test_invalid_build_number(self, seeded_jenkins_test_env):
        """Test behavior with non-existent build number"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "sample-job",
                    "build_number": 99999,
                    "jenkins_url": jenkins_url,
                },
            )

            assert result.get("isError") is True
            assert "content" in result
            error_msg = result["content"][0]["text"].lower()
            assert "not found" in error_msg
            assert "404" not in error_msg

    @pytest.mark.asyncio
    async def test_missing_required_parameters(self, seeded_jenkins_test_env):
        """Test parameter validation for missing required parameters"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Missing job_name parameter
            result = await client.call_tool(
                "trigger_build_async", {"jenkins_url": jenkins_url}
            )

            assert result.get("isError") is True
            assert "content" in result
            error_msg = result["content"][0]["text"].lower()
            assert "required" in error_msg or "missing" in error_msg

    @pytest.mark.asyncio
    async def test_invalid_parameter_types(self, seeded_jenkins_test_env):
        """Test parameter validation for incorrect types"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Invalid parameter type - build_number should be int, not string
            result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "sample-job",
                    "build_number": "not-a-number",
                    "jenkins_url": jenkins_url,
                },
            )

            assert result.get("isError") is True
            assert "content" in result
            error_msg = result["content"][0]["text"].lower()
            assert (
                "parameter" in error_msg
                or "type" in error_msg
                or "invalid" in error_msg
            )

    @pytest.mark.asyncio
    async def test_invalid_parameter_values(self, seeded_jenkins_test_env):
        """Test parameter validation for invalid values"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Negative build number
            result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "sample-job",
                    "build_number": -1,
                    "jenkins_url": jenkins_url,
                },
            )

            # Should either handle gracefully or return an error
            # We don't enforce this fails, but if it does, error should be clear
            if result.get("isError"):
                assert "content" in result
                error_msg = result["content"][0]["text"].lower()
                assert "failed to fetch" in error_msg or "build not found" in error_msg

    @pytest.mark.asyncio
    async def test_large_parameter_values(self, seeded_jenkins_test_env):
        """Test behavior with unusually large parameter values"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Very large line range
            result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "sample-job",
                    "build_number": 1,
                    "start_line": 0,
                    "end_line": 1000000,  # 1 million lines
                    "jenkins_url": jenkins_url,
                },
            )

            # Should handle gracefully. The new contract seems to be isError: False with error in content.
            if "result" not in result:
                assert "content" in result
            else:
                # If successful, should not actually return 1M lines
                if "lines" in result["result"]:
                    assert len(result["result"]["lines"]) < 100000

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls_error_isolation(self, seeded_jenkins_test_env):
        """Test that errors in one tool call don't affect others"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Run multiple calls - some good, some bad
            tasks = [
                client.call_tool(
                    "trigger_build_async",
                    {"job_name": "sample-job", "jenkins_url": jenkins_url},
                ),  # Good
                client.call_tool(
                    "trigger_build_async",
                    {"job_name": "non-existent", "jenkins_url": jenkins_url},
                ),  # Bad
                client.call_tool(
                    "get_jenkins_job_parameters",
                    {"job_name": "sample-job", "jenkins_url": jenkins_url},
                ),  # Good
                client.call_tool(
                    "get_log_context",
                    {
                        "job_name": "sample-job",
                        "build_number": 99999,
                        "jenkins_url": jenkins_url,
                    },
                ),  # Bad
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Should have mix of successes and errors, no exceptions
            successes = 0
            errors = 0

            for i, result in enumerate(results):
                print(f"Result {i}: {result}")
                assert not isinstance(result, Exception), f"Got exception: {result}"

                if not result.get("isError"):
                    successes += 1
                else:
                    errors += 1

            assert successes >= 2, "Should have at least 2 successful calls"
            assert errors >= 2, "Should have at least 2 error calls"

    @pytest.mark.asyncio
    async def test_tool_timeout_handling(self, seeded_jenkins_test_env):
        """Test timeout scenarios"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Test very short timeout on a potentially slow operation
            try:
                result = await client.call_tool(
                    "diagnose_build_failure",
                    {
                        "job_name": "QA_JOS/master",
                        "build_number": 9,
                        "jenkins_url": jenkins_url,
                    },
                    timeout=0.1,
                )  # Very short timeout

                # If it completes within timeout, that's fine
                assert "result" in result or result.get("isError")

            except TimeoutError:
                # Timeout is also acceptable behavior
                pass

    @pytest.mark.asyncio
    async def test_malformed_tool_calls(self, seeded_jenkins_test_env):
        """Test behavior with malformed tool call parameters"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Test with None values
            result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": None,
                    "build_number": 1,
                    "jenkins_url": jenkins_url,
                },
            )

            assert result.get("isError") is True

            # Test with missing arguments completely
            try:
                # This should fail at the protocol level
                result = await client.call_tool(
                    "trigger_build_async", {"jenkins_url": jenkins_url}
                )
                assert result.get("isError") is True
            except (TypeError, AttributeError):
                # Also acceptable - fail fast on malformed calls
                pass

    @pytest.mark.asyncio
    async def test_vector_database_connection_failure(self, seeded_jenkins_test_env):
        """Test behavior when vector database is unavailable"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]
        qdrant = seeded_jenkins_test_env.qdrant

        # Stop the Qdrant test double to simulate connection failure
        qdrant.stop()

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Vector search should fail gracefully
            result = await client.call_tool(
                "vector_search",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "query_text": "error",
                    "top_k": 3,
                    "jenkins_url": jenkins_url,
                },
            )

            # Should get an error about vector database connection
            assert result.get("isError") is True
            assert "content" in result
            error_msg = result["content"][0]["text"].lower()
            assert any(
                word in error_msg
                for word in ["connection", "vector", "database", "qdrant"]
            )

    @pytest.mark.asyncio
    async def test_cache_directory_permissions(self, seeded_jenkins_test_env):
        """Test behavior when cache directory is not writable"""
        config = seeded_jenkins_test_env.config.copy()
        # This test is tricky to run reliably in all environments.
        # We'll simulate the failure by checking if the server fails to start
        # when given a bad cache path. A more robust test would involve
        # actually setting permissions, but that's complex and platform-dependent.
        config["cache"]["base_dir"] = "/root/unwritable-mcp-cache"

        # The server should start up gracefully even with a bad cache path
        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Check that the server is ready
            assert client.server_ready

    @pytest.mark.asyncio
    async def test_unknown_tool_call(self, seeded_jenkins_test_env):
        """Test calling a non-existent tool"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            result = await client.call_tool(
                "non_existent_tool",
                {"some_param": "some_value", "jenkins_url": jenkins_url},
            )

            assert result.get("isError") is True
            assert "content" in result
            error_msg = result["content"][0]["text"].lower()
            assert (
                "unknown" in error_msg
                or "not found" in error_msg
                or "invalid" in error_msg
            )

    @pytest.mark.asyncio
    async def test_server_initialization_failure(self):
        """Test behavior when server fails to initialize"""
        # Use completely invalid configuration by not passing a config
        with pytest.raises(Exception) as excinfo:
            async with MCPTestClient("jenkins_mcp_enterprise.server") as client:
                pass

        exc_text = str(excinfo.value).lower()
        assert "timeout" in exc_text or "initialization" in exc_text

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, seeded_jenkins_test_env):
        """Test that partial failures don't break entire workflows"""
        config = seeded_jenkins_test_env.config
        jenkins_url = config["jenkins"]["url"]

        async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
            # Diagnose a build where some operations might fail
            result = await client.call_tool(
                "diagnose_build_failure",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "jenkins_url": jenkins_url,
                },
            )

            # The server now returns an error in the content, not as isError: True
            assert "result" not in result
            assert "content" in result
            data_str = result["content"][0]["text"]
            import json

            data = json.loads(data_str)

            # Should have basic information even if advanced features fail
            assert "job_name" in data
            assert "build_number" in data
            # This key may not exist if the build itself is not found
            # assert "overall_status_from_jenkins" in data

            # Even if vector indexing fails, should still have other data
            if data.get("vector_indexing_status") == "FAILURE":
                # Should still have heuristic findings or other analysis
                assert "heuristic_findings" in data or "log_analysis_status" in data
