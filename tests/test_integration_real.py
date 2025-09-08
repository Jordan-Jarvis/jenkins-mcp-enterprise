"""Integration tests using real implementations and dependency injection"""

import os
import tempfile

import pytest

from jenkins_mcp_enterprise.cache_manager import CacheManager
from jenkins_mcp_enterprise.config import MCPConfig
from jenkins_mcp_enterprise.di_container import DIContainer
from jenkins_mcp_enterprise.jenkins.jenkins_client import JenkinsClient
from jenkins_mcp_enterprise.tool_factory import ToolFactory
from jenkins_mcp_enterprise.vector_manager import QdrantVectorManager
from .test_fixtures import BuildDataFactory, LogDataFactory, jenkins_test_env


class TestDependencyInjectionIntegration:
    """Test DI container with real configuration and components"""

    def test_di_container_with_test_config(self):
        """Test that DI container properly wires components with test config"""
        with jenkins_test_env() as env:
            container = env.container

            # Verify all major components can be resolved
            jenkins_client = container.get(JenkinsClient)
            cache_manager = container.get(CacheManager)
            tool_factory = container.get(ToolFactory)

            assert jenkins_client is not None
            assert cache_manager is not None
            assert tool_factory is not None

            # Verify singletons work properly
            jenkins_client2 = container.get(JenkinsClient)
            assert jenkins_client is jenkins_client2

    def test_cache_manager_integration(self):
        """Test cache manager with real filesystem operations"""
        with jenkins_test_env() as env:
            cache_manager = env.get_cache_manager()

            # Test caching build info
            test_key = "test_build_info"
            test_data = {"build_number": 123, "result": "SUCCESS"}

            # Cache should work
            cache_manager.set(test_key, test_data)
            retrieved_data = cache_manager.get(test_key)

            assert retrieved_data == test_data

            # Test cache expiration
            cache_manager.set(test_key, test_data, expire_seconds=1)
            assert cache_manager.get(test_key) == test_data

            # After expiration time, should be None
            import time

            time.sleep(1.1)
            assert cache_manager.get(test_key) is None

    def test_tool_factory_integration(self):
        """Test tool factory creates tools with proper dependencies"""
        with jenkins_test_env() as env:
            tool_factory = env.container.get(ToolFactory)

            # Get all available tools
            tools = tool_factory.get_all_tools()

            assert len(tools) > 0

            # Verify specific tools exist
            tool_names = [tool.NAME for tool in tools]
            expected_tools = [
                "trigger_jenkins_build",
                "get_jenkins_build_status",
                "get_jenkins_console_log",
                "get_jenkins_sub_builds",
                "get_jenkins_job_parameters",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names

    def test_end_to_end_build_workflow(self):
        """Test complete build workflow using real components"""
        with jenkins_test_env() as env:
            # Setup test job
            env.add_jenkins_job(
                "workflow-job",
                {"name": "workflow-job", "nextBuildNumber": 1, "buildable": True},
            )

            # Get components
            build_manager = env.get_build_manager()
            log_fetcher = env.get_log_fetcher()
            cache_manager = env.get_cache_manager()

            # 1. Trigger build
            queue_item_id = build_manager.trigger_build("workflow-job")
            assert queue_item_id is not None

            # 2. Simulate build completion
            build_data = BuildDataFactory.successful_build("workflow-job", 1)
            log_content = LogDataFactory.successful_pipeline_log()

            env.add_jenkins_build("workflow-job", 1, build_data)
            env.add_console_log("workflow-job", 1, log_content)

            # 3. Get build info
            build_info = build_manager.get_build_info("workflow-job", 1)
            assert build_info.result == "SUCCESS"

            # 4. Get logs
            logs = log_fetcher.get_console_log("workflow-job", 1)
            assert "Finished: SUCCESS" in logs

            # 5. Cache should work
            cache_key = f"build_workflow-job_1"
            cache_manager.set(cache_key, build_info.to_dict())
            cached_build = cache_manager.get(cache_key)
            assert cached_build["result"] == "SUCCESS"


class TestConfigurationIntegration:
    """Test configuration loading and validation"""

    def test_config_from_environment(self):
        """Test loading configuration from environment variables"""
        # Set environment variables
        test_env = {
            "JENKINS_URL": "http://test-jenkins:8080",
            "JENKINS_USER": "test-user",
            "JENKINS_TOKEN": "test-token",
            "CACHE_DIR": "/tmp/test-cache",
            "LOG_LEVEL": "DEBUG",
        }

        # Temporarily set environment
        original_env = {}
        for key, value in test_env.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            config = MCPConfig.from_env()

            assert config.jenkins.url == "http://test-jenkins:8080"
            assert config.jenkins.username == "test-user"
            assert config.jenkins.token == "test-token"
            assert str(config.cache.base_dir) == "/tmp/test-cache"
            assert config.server.log_level == "DEBUG"

        finally:
            # Restore original environment
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_config_validation(self):
        """Test configuration validation"""
        # Test will be done with environment variables since MCPConfig uses from_env()
        import os

        # Valid config via environment
        test_env = {
            "JENKINS_URL": "http://jenkins.example.com",
            "JENKINS_USER": "user",
            "JENKINS_TOKEN": "token",
        }

        original_env = {}
        for key, value in test_env.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            config = MCPConfig.from_env()
            assert config.jenkins.url == "http://jenkins.example.com"
            assert config.jenkins.username == "user"
            assert config.jenkins.token == "token"
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_config_with_di_container(self):
        """Test using custom config with DI container"""
        # Use environment variables for custom config
        import os

        temp_dir = tempfile.mkdtemp()

        test_env = {
            "JENKINS_URL": "http://localhost:18080",
            "JENKINS_USER": "custom-user",
            "JENKINS_TOKEN": "custom-token",
            "JENKINS_VERIFY_SSL": "false",
            "CACHE_DIR": temp_dir,
            "CACHE_MAX_SIZE_MB": "50",
        }

        original_env = {}
        for key, value in test_env.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            config = MCPConfig.from_env()
            container = DIContainer()
            container.register_config(config)

            # Components should use the custom config
            jenkins_client = container.get(JenkinsClient)
            cache_manager = container.get(CacheManager)

            assert (
                jenkins_client.connection_manager.config.jenkins.username
                == "custom-user"
            )
            assert str(cache_manager.cache_dir) == temp_dir
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class TestErrorHandlingIntegration:
    """Test error handling across components"""

    def test_jenkins_connection_error_handling(self):
        """Test handling of Jenkins connection errors"""
        with jenkins_test_env() as env:
            # Stop the Jenkins test double to simulate connection failure
            env.jenkins_double.stop()

            jenkins_client = env.get_jenkins_client()

            # Operations should handle connection errors gracefully
            with pytest.raises(Exception):  # Should raise appropriate exception
                jenkins_client.get_build_info("any-job", 1)

    def test_cache_permission_error_handling(self):
        """Test handling of cache permission errors"""
        # Create config with unwritable cache directory via environment
        import os

        test_env = {
            "JENKINS_URL": "http://localhost:18080",
            "JENKINS_USER": "test",
            "JENKINS_TOKEN": "test",
            "CACHE_DIR": "/root/unwritable",  # Should be unwritable
            "CACHE_MAX_SIZE_MB": "100",
        }

        original_env = {}
        for key, value in test_env.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            config = MCPConfig.from_env()
            container = DIContainer()
            container.register_config(config)

            # Cache manager should handle permission errors gracefully
            cache_manager = container.get(CacheManager)

            # Should not crash, might fall back to memory caching or disable caching
            try:
                cache_manager.set("test_key", {"test": "data"})
                # If it doesn't raise an exception, it handled the error gracefully
            except PermissionError:
                # If it raises PermissionError, that's also acceptable error handling
                pass
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_build_not_found_error_handling(self):
        """Test handling of build not found errors"""
        with jenkins_test_env() as env:
            build_manager = env.get_build_manager()
            log_fetcher = env.get_log_fetcher()

            # Should raise appropriate errors for non-existent builds
            with pytest.raises(Exception):
                build_manager.get_build_info("nonexistent-job", 999)

            with pytest.raises(Exception):
                log_fetcher.get_console_log("nonexistent-job", 999)


class TestPerformanceIntegration:
    """Test performance characteristics with real implementations"""

    def test_large_log_handling(self):
        """Test handling of large console logs"""
        with jenkins_test_env() as env:
            # Create large log content (simulate 1MB log)
            large_log = "Log line with some content\n" * 40000  # ~1MB

            build_data = BuildDataFactory.successful_build("large-log-job", 1)
            env.add_jenkins_build("large-log-job", 1, build_data)
            env.add_console_log("large-log-job", 1, large_log)

            log_fetcher = env.get_log_fetcher()

            # Should handle large logs without crashing
            import time

            start_time = time.time()

            log_content = log_fetcher.get_console_log("large-log-job", 1)

            end_time = time.time()

            # Verify content is correct
            assert len(log_content) > 900000  # Should be close to 1MB
            assert "Log line with some content" in log_content

            # Should complete in reasonable time (less than 5 seconds for 1MB)
            assert (end_time - start_time) < 5.0

    def test_concurrent_operations(self):
        """Test concurrent operations don't interfere"""
        with jenkins_test_env() as env:
            import threading
            import time

            # Setup multiple jobs
            for i in range(5):
                job_name = f"concurrent-job-{i}"
                env.add_jenkins_job(
                    job_name,
                    {"name": job_name, "nextBuildNumber": 1, "buildable": True},
                )

                build_data = BuildDataFactory.successful_build(job_name, 1)
                env.add_jenkins_build(job_name, 1, build_data)

            build_manager = env.get_build_manager()
            results = {}
            errors = []

            def worker(job_index):
                try:
                    job_name = f"concurrent-job-{job_index}"
                    build_info = build_manager.get_build_info(job_name, 1)
                    results[job_index] = build_info.result
                except Exception as e:
                    errors.append((job_index, str(e)))

            # Start concurrent threads
            threads = []
            for i in range(5):
                thread = threading.Thread(target=worker, args=(i,))
                threads.append(thread)
                thread.start()

            # Wait for completion
            for thread in threads:
                thread.join()

            # Verify all operations succeeded
            assert len(errors) == 0, f"Errors occurred: {errors}"
            assert len(results) == 5
            assert all(result == "SUCCESS" for result in results.values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
