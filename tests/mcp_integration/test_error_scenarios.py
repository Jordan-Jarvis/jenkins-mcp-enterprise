"""Test error handling and edge cases"""

import asyncio
import shutil
import tempfile

import pytest
import pytest_asyncio

from .mcp_test_client import MCPTestClient
from .test_doubles import JenkinsTestDouble, QdrantTestDouble


class TestErrorScenarios:
    """Test how tools handle various error conditions"""

    @pytest_asyncio.fixture
    async def test_environment(self):
        """Setup test environment"""
        cache_dir = tempfile.mkdtemp(prefix="test-mcp-jenkins-error-")

        jenkins = JenkinsTestDouble(port=18081)
        qdrant = QdrantTestDouble(port=16334)

        jenkins.start()
        qdrant.start()

        config = {
            "jenkins_url": f"http://localhost:{jenkins.port}",
            "jenkins_user": "test_user",
            "jenkins_token": "test_token",
            "qdrant_host": f"http://localhost:{qdrant.port}",
            "cache_dir": cache_dir,
            "log_level": "DEBUG",
        }

        yield {
            "config": config,
            "jenkins": jenkins,
            "qdrant": qdrant,
            "cache_dir": cache_dir,
        }

        jenkins.stop()
        qdrant.stop()
        shutil.rmtree(cache_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_jenkins_connection_failure(self):
        """Test behavior when Jenkins is unreachable"""
        config = {
            "jenkins_url": "http://localhost:19999",  # Unreachable port
            "jenkins_user": "test_user",
            "jenkins_token": "test_token",
            "qdrant_host": "http://localhost:16333",
            "cache_dir": "/tmp/test-mcp-jenkins",
            "log_level": "DEBUG",
        }

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            result = await client.call_tool(
                "trigger_build_async", {"job_name": "any-job"}
            )

            # Should get an error response
            assert "error" in result
            error_msg = result["error"]["message"].lower()
            assert any(
                word in error_msg
                for word in ["connection", "timeout", "refused", "unreachable"]
            )

    @pytest.mark.asyncio
    async def test_invalid_job_name(self, test_environment):
        """Test behavior with non-existent job"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            result = await client.call_tool(
                "trigger_build_async", {"job_name": "non-existent-job"}
            )

            # Should get an error response
            assert "error" in result
            error_msg = result["error"]["message"].lower()
            assert "not found" in error_msg or "404" in error_msg

    @pytest.mark.asyncio
    async def test_invalid_build_number(self, test_environment):
        """Test behavior with non-existent build number"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            result = await client.call_tool(
                "get_log_context", {"job_name": "sample-job", "build_number": 99999}
            )

            # Should get an error response
            assert "error" in result
            error_msg = result["error"]["message"].lower()
            assert "not found" in error_msg or "404" in error_msg

    @pytest.mark.asyncio
    async def test_missing_required_parameters(self, test_environment):
        """Test parameter validation for missing required parameters"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Missing job_name parameter
            result = await client.call_tool("trigger_build_async", {})

            assert "error" in result
            error_msg = result["error"]["message"].lower()
            assert "required" in error_msg or "missing" in error_msg

    @pytest.mark.asyncio
    async def test_invalid_parameter_types(self, test_environment):
        """Test parameter validation for incorrect types"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Invalid parameter type - build_number should be int, not string
            result = await client.call_tool(
                "get_log_context",
                {"job_name": "sample-job", "build_number": "not-a-number"},
            )

            assert "error" in result
            error_msg = result["error"]["message"].lower()
            assert (
                "parameter" in error_msg
                or "type" in error_msg
                or "invalid" in error_msg
            )

    @pytest.mark.asyncio
    async def test_invalid_parameter_values(self, test_environment):
        """Test parameter validation for invalid values"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Negative build number
            result = await client.call_tool(
                "get_log_context", {"job_name": "sample-job", "build_number": -1}
            )

            # Should either handle gracefully or return an error
            # We don't enforce this fails, but if it does, error should be clear
            if "error" in result:
                error_msg = result["error"]["message"].lower()
                assert "invalid" in error_msg or "negative" in error_msg

    @pytest.mark.asyncio
    async def test_large_parameter_values(self, test_environment):
        """Test behavior with unusually large parameter values"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Very large line range
            result = await client.call_tool(
                "get_log_context",
                {
                    "job_name": "sample-job",
                    "build_number": 1,
                    "start_line": 0,
                    "end_line": 1000000,  # 1 million lines
                },
            )

            # Should handle gracefully - either succeed with reasonable subset or fail gracefully
            if "error" in result:
                assert "result" not in result  # Shouldn't have both error and result
            else:
                assert "result" in result
                # If successful, should not actually return 1M lines
                if "lines" in result["result"]:
                    assert len(result["result"]["lines"]) < 100000

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls_error_isolation(self, test_environment):
        """Test that errors in one tool call don't affect others"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Run multiple calls - some good, some bad
            tasks = [
                client.call_tool(
                    "trigger_build_async", {"job_name": "sample-job"}
                ),  # Good
                client.call_tool(
                    "trigger_build_async", {"job_name": "non-existent"}
                ),  # Bad
                client.call_tool(
                    "get_job_parameters", {"job_name": "sample-job"}
                ),  # Good
                client.call_tool(
                    "get_log_context", {"job_name": "sample-job", "build_number": 99999}
                ),  # Bad
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Should have mix of successes and errors, no exceptions
            successes = 0
            errors = 0

            for result in results:
                assert not isinstance(result, Exception), f"Got exception: {result}"

                if "result" in result:
                    successes += 1
                elif "error" in result:
                    errors += 1

            assert successes >= 2, "Should have at least 2 successful calls"
            assert errors >= 2, "Should have at least 2 error calls"

    @pytest.mark.asyncio
    async def test_tool_timeout_handling(self, test_environment):
        """Test timeout scenarios"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Test very short timeout on a potentially slow operation
            try:
                result = await client.call_tool(
                    "diagnose_build_failure",
                    {"job_name": "QA_JOBS/master", "build_number": 9},
                    timeout=0.1,
                )  # Very short timeout

                # If it completes within timeout, that's fine
                assert "result" in result or "error" in result

            except TimeoutError:
                # Timeout is also acceptable behavior
                pass

    @pytest.mark.asyncio
    async def test_malformed_tool_calls(self, test_environment):
        """Test behavior with malformed tool call parameters"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Test with None values
            result = await client.call_tool(
                "get_log_context", {"job_name": None, "build_number": 1}
            )

            assert "error" in result

            # Test with missing arguments completely
            try:
                # This should fail at the protocol level
                result = await client.call_tool("trigger_build_async", None)
                assert "error" in result
            except (TypeError, AttributeError):
                # Also acceptable - fail fast on malformed calls
                pass

    @pytest.mark.asyncio
    async def test_vector_database_connection_failure(self, test_environment):
        """Test behavior when vector database is unavailable"""
        config = test_environment["config"]

        # Stop the Qdrant test double to simulate connection failure
        test_environment["qdrant"].stop()

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Vector search should fail gracefully
            result = await client.call_tool(
                "vector_search",
                {
                    "job_name": "QA_JOBS/master",
                    "build_number": 9,
                    "query_text": "error",
                    "top_k": 3,
                },
            )

            # Should get an error about vector database connection
            assert "error" in result
            error_msg = result["error"]["message"].lower()
            assert any(
                word in error_msg
                for word in ["connection", "vector", "database", "qdrant"]
            )

    @pytest.mark.asyncio
    async def test_cache_directory_permissions(self):
        """Test behavior when cache directory is not writable"""
        # Use /root as cache directory - should not be writable in most environments
        config = {
            "jenkins_url": "http://localhost:18080",
            "jenkins_user": "test_user",
            "jenkins_token": "test_token",
            "qdrant_host": "http://localhost:16333",
            "cache_dir": "/root/mcp-test-cache",  # Not writable
            "log_level": "DEBUG",
        }

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # This should either fail gracefully or handle the permission error
            result = await client.call_tool(
                "get_log_context", {"job_name": "sample-job", "build_number": 1}
            )

            # If it fails, should be a clear error about permissions/cache
            if "error" in result:
                error_msg = result["error"]["message"].lower()
                assert any(
                    word in error_msg
                    for word in ["permission", "cache", "directory", "write"]
                )

    @pytest.mark.asyncio
    async def test_unknown_tool_call(self, test_environment):
        """Test calling a non-existent tool"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            result = await client.call_tool(
                "non_existent_tool", {"some_param": "some_value"}
            )

            assert "error" in result
            error_msg = result["error"]["message"].lower()
            assert (
                "unknown" in error_msg
                or "not found" in error_msg
                or "invalid" in error_msg
            )

    @pytest.mark.asyncio
    async def test_server_initialization_failure(self):
        """Test behavior when server fails to initialize"""
        # Use completely invalid configuration
        config = {
            "jenkins_url": "not-a-valid-url",
            "jenkins_user": "",
            "jenkins_token": "",
            "qdrant_host": "also-not-valid",
            "cache_dir": "",
            "log_level": "DEBUG",
        }

        try:
            async with MCPTestClient(
                "jenkins_mcp_enterprise/server.py", config
            ) as client:
                # Try to call any tool - server might not even start properly
                result = await client.call_tool(
                    "trigger_build_async", {"job_name": "any-job"}
                )

                # If we get here, server started but should return errors
                assert "error" in result

        except Exception as e:
            # Server might fail to start entirely, which is also acceptable
            assert (
                "initialization" in str(e).lower()
                or "connection" in str(e).lower()
                or "timeout" in str(e).lower()
            )

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, test_environment):
        """Test that partial failures don't break entire workflows"""
        config = test_environment["config"]

        async with MCPTestClient("jenkins_mcp_enterprise/server.py", config) as client:
            # Diagnose a build where some operations might fail
            result = await client.call_tool(
                "diagnose_build_failure",
                {"job_name": "QA_JOBS/master", "build_number": 9},
            )

            # Should succeed with at least partial results even if some sub-operations fail
            assert "result" in result
            data = result["result"]

            # Should have basic information even if advanced features fail
            assert "job_name" in data
            assert "build_number" in data
            assert "overall_status_from_jenkins" in data

            # Even if vector indexing fails, should still have other data
            if data.get("vector_indexing_status") == "FAILURE":
                # Should still have heuristic findings or other analysis
                assert "heuristic_findings" in data or "log_analysis_status" in data
