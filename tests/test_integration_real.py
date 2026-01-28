"""Integration tests using real implementations and dependency injection"""

import os
import tempfile

import pytest
from tests.conftest import BuildDataFactory, LogDataFactory

# Application imports are moved into test functions to avoid circular dependencies.


class TestDependencyInjectionIntegration:
    """Test DI container with real configuration and components"""

    def test_di_container_with_test_config(self, seeded_jenkins_test_env):
        """Test that DI container properly wires components with test config"""
        from jenkins_mcp_enterprise.jenkins.jenkins_client import JenkinsClient
        from jenkins_mcp_enterprise.cache_manager import CacheManager
        from jenkins_mcp_enterprise.tool_factory import ToolFactory

        container = seeded_jenkins_test_env.container

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

    def test_cache_manager_integration(self, seeded_jenkins_test_env):
        """Test cache manager with real filesystem operations"""
        from jenkins_mcp_enterprise.cache_manager import CacheManager
        from jenkins_mcp_enterprise.jenkins.jenkins_client import JenkinsClient

        cache_manager = seeded_jenkins_test_env.container.get(CacheManager)
        jenkins_client = seeded_jenkins_test_env.container.get(JenkinsClient)

        # Setup a build and its log in the test double
        build_data = BuildDataFactory.create_successful_build("cache-test-job", 1)
        log_content = "This is the log content."
        seeded_jenkins_test_env.add_jenkins_job(
            "cache-test-job", {"name": "cache-test-job", "nextBuildNumber": 2}
        )
        seeded_jenkins_test_env.add_jenkins_build("cache-test-job", 1, build_data)
        seeded_jenkins_test_env.add_console_log("cache-test-job", 1, log_content)

        # Create a Build object to pass to the cache manager
        from jenkins_mcp_enterprise.base import Build

        build = Build(job_name="cache-test-job", build_number=1)

        # 1. First fetch should get from Jenkins and cache it
        log_path = cache_manager.fetch(jenkins_client, build)
        assert log_path.exists()

        lines = cache_manager.read_lines(log_path)
        assert lines[0] == "This is the log content."

        # 2. Second fetch should return the cached path without calling Jenkins again
        # To verify, we can check the modification time
        initial_mod_time = log_path.stat().st_mtime
        time.sleep(0.1)
        log_path_2 = cache_manager.fetch(jenkins_client, build)
        assert log_path_2.stat().st_mtime == initial_mod_time

    def test_tool_factory_integration(self, seeded_jenkins_test_env):
        """Test tool factory creates tools with proper dependencies"""
        from jenkins_mcp_enterprise.tool_factory import ToolFactory

        tool_factory = seeded_jenkins_test_env.container.get(ToolFactory)

        # Get all available tools
        tools = tool_factory.create_tools()

        assert len(tools) > 0

        # Verify specific tools exist
        tool_names = list(tools.keys())
        expected_tools = [
            "trigger_build",
            "get_build_status",
            "get_log_context",
            "get_sub_builds",
            "get_job_parameters",
        ]

        for expected_tool in expected_tools:
            assert expected_tool in tool_names

    def test_end_to_end_build_workflow(self, seeded_jenkins_test_env):
        """Test complete build workflow using real components"""
        from jenkins_mcp_enterprise.jenkins.build_manager import BuildManager
        from jenkins_mcp_enterprise.jenkins.log_fetcher import LogFetcher
        from jenkins_mcp_enterprise.cache_manager import CacheManager

        # Setup test job
        seeded_jenkins_test_env.add_jenkins_job(
            "workflow-job",
            {"name": "workflow-job", "nextBuildNumber": 1, "buildable": True},
        )

        # Get components
        build_manager = seeded_jenkins_test_env.container.get(BuildManager)
        log_fetcher = seeded_jenkins_test_env.container.get(LogFetcher)
        cache_manager = seeded_jenkins_test_env.container.get(CacheManager)

        # 1. Trigger build
        queue_item_id = build_manager.trigger_build("workflow-job")
        assert queue_item_id is not None

        # 2. Simulate build completion
        build_data = BuildDataFactory.create_successful_build("workflow-job", 1)
        log_content = LogDataFactory.create_simple_log()

        seeded_jenkins_test_env.jenkins_double.add_build("workflow-job", 1, build_data)
        seeded_jenkins_test_env.jenkins_double.add_console_log(
            "workflow-job", 1, log_content
        )

        # 3. Get build info
        build_info = build_manager.get_build_info("workflow-job", 1)
        assert build_info.result == "SUCCESS"

        # 4. Get logs
        logs = log_fetcher.get_console_log("workflow-job", 1)
        assert any("Finished: SUCCESS" in line for line in logs)

        # 5. Verify cache worked
        from jenkins_mcp_enterprise.base import Build

        build = Build(job_name="workflow-job", build_number=1)
        log_path = cache_manager.get_path(build)
        assert log_path.exists()


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
            from jenkins_mcp_enterprise.config import MCPConfig

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
            from jenkins_mcp_enterprise.config import MCPConfig

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

    def test_config_with_di_container(self, seeded_jenkins_test_env):
        """Test using custom config with DI container"""
        container = seeded_jenkins_test_env.container
        config = seeded_jenkins_test_env.config

        from jenkins_mcp_enterprise.jenkins.jenkins_client import JenkinsClient
        from jenkins_mcp_enterprise.cache_manager import CacheManager

        # Components should use the custom config
        jenkins_client = container.get(JenkinsClient)
        cache_manager = container.get(CacheManager)

        assert (
            jenkins_client.connection.config.username == config["jenkins"]["username"]
        )
        assert str(cache_manager.cache_dir).startswith(config["cache"]["base_dir"])


class TestErrorHandlingIntegration:
    """Test error handling across components"""

    def test_jenkins_connection_error_handling(self, seeded_jenkins_test_env):
        """Test handling of Jenkins connection errors"""
        from jenkins_mcp_enterprise.jenkins.jenkins_client import JenkinsClient

        # Stop the Jenkins test double to simulate connection failure
        seeded_jenkins_test_env.jenkins_double.stop()

        jenkins_client = seeded_jenkins_test_env.container.get(JenkinsClient)

        # Operations should handle connection errors gracefully
        with pytest.raises(Exception):  # Should raise appropriate exception
            jenkins_client.get_build_info("any-job", 1)

    @pytest.mark.skip(
        reason="This test requires root permissions to fail, which is not reliable."
    )
    def test_cache_permission_error_handling(self):
        """Test handling of cache permission errors"""
        pass

    def test_build_not_found_error_handling(self, seeded_jenkins_test_env):
        """Test handling of build not found errors"""
        from jenkins_mcp_enterprise.jenkins.build_manager import BuildManager
        from jenkins_mcp_enterprise.jenkins.log_fetcher import LogFetcher

        build_manager = seeded_jenkins_test_env.container.get(BuildManager)
        log_fetcher = seeded_jenkins_test_env.container.get(LogFetcher)

        # Should raise appropriate errors for non-existent builds
        with pytest.raises(Exception):
            build_manager.get_build_info("nonexistent-job", 999)

        with pytest.raises(Exception):
            log_fetcher.get_console_log("nonexistent-job", 999)


class TestPerformanceIntegration:
    """Test performance characteristics with real implementations"""

    def test_large_log_handling(self, seeded_jenkins_test_env):
        """Test handling of large console logs"""
        from jenkins_mcp_enterprise.jenkins.log_fetcher import LogFetcher

        # Create large log content (simulate 1MB log)
        large_log = "Log line with some content\n" * 40000  # ~1MB

        seeded_jenkins_test_env.add_jenkins_job(
            "large-log-job", {"name": "large-log-job", "nextBuildNumber": 2}
        )
        build_data = BuildDataFactory.create_successful_build("large-log-job", 1)
        seeded_jenkins_test_env.add_jenkins_build("large-log-job", 1, build_data)
        seeded_jenkins_test_env.add_console_log("large-log-job", 1, large_log)

        log_fetcher = seeded_jenkins_test_env.container.get(LogFetcher)

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

    def test_concurrent_operations(self, seeded_jenkins_test_env):
        """Test concurrent operations don't interfere"""
        import threading
        import time
        from jenkins_mcp_enterprise.jenkins.build_manager import BuildManager

        # Setup multiple jobs
        for i in range(5):
            job_name = f"concurrent-job-{i}"
            seeded_jenkins_test_env.add_jenkins_job(
                job_name,
                {"name": job_name, "nextBuildNumber": 1, "buildable": True},
            )

            build_data = BuildDataFactory.create_successful_build(job_name, 1)
            seeded_jenkins_test_env.add_jenkins_build(job_name, 1, build_data)

        build_manager = seeded_jenkins_test_env.container.get(BuildManager)
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
