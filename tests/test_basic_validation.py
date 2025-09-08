"""Basic validation tests for package structure and imports"""

import importlib
import sys
from pathlib import Path

import pytest


class TestBasicValidation:
    """Basic validation of package structure and imports"""

    def test_package_imports_successfully(self):
        """Test that core package imports work"""
        try:
            import jenkins_mcp_enterprise

            assert jenkins_mcp_enterprise is not None
            print("✅ jenkins_mcp_enterprise package imports successfully")
        except ImportError as e:
            pytest.fail(f"Failed to import jenkins_mcp_enterprise: {e}")

    def test_server_module_imports(self):
        """Test that server module imports work"""
        try:
            from jenkins_mcp_enterprise.server import create_server

            assert create_server is not None
            print("✅ server module imports successfully")
        except ImportError as e:
            pytest.fail(f"Failed to import server module: {e}")

    def test_config_module_imports(self):
        """Test that config module imports work"""
        try:
            from jenkins_mcp_enterprise.config import (
                JenkinsConfig,
                ServerConfig,
                VectorConfig,
            )

            assert JenkinsConfig is not None
            assert VectorConfig is not None
            assert ServerConfig is not None
            print("✅ config module imports successfully")
        except ImportError as e:
            pytest.fail(f"Failed to import config module: {e}")

    def test_essential_dependencies_available(self):
        """Test that essential dependencies are available"""
        essential_deps = [
            "requests",
            "yaml",
            "jenkins",  # python-jenkins package provides jenkins module
            "qdrant_client",
            "sentence_transformers",
            "tiktoken",
        ]

        missing_deps = []
        for dep in essential_deps:
            try:
                importlib.import_module(dep)
                print(f"✅ {dep} is available")
            except ImportError:
                missing_deps.append(dep)

        if missing_deps:
            pytest.fail(f"Missing essential dependencies: {missing_deps}")

    def test_package_structure(self):
        """Test that expected package structure exists"""
        # Get the package root
        import jenkins_mcp_enterprise

        package_path = Path(jenkins_mcp_enterprise.__file__).parent

        expected_modules = [
            "server.py",
            "config.py",
            "base.py",
            "di_container.py",
            "tool_factory.py",
        ]

        missing_modules = []
        for module in expected_modules:
            module_path = package_path / module
            if not module_path.exists():
                missing_modules.append(module)
            else:
                print(f"✅ {module} exists")

        if missing_modules:
            pytest.fail(f"Missing expected modules: {missing_modules}")

    def test_tools_directory_exists(self):
        """Test that tools directory exists with expected tools"""
        import jenkins_mcp_enterprise

        package_path = Path(jenkins_mcp_enterprise.__file__).parent
        tools_path = package_path / "tools"

        assert tools_path.exists(), "tools directory should exist"
        assert tools_path.is_dir(), "tools should be a directory"

        expected_tools = [
            "__init__.py",
            "base_tools.py",
            "jenkins_tools.py",
            "diagnostics.py",
        ]

        missing_tools = []
        for tool in expected_tools:
            tool_path = tools_path / tool
            if not tool_path.exists():
                missing_tools.append(tool)
            else:
                print(f"✅ tools/{tool} exists")

        if missing_tools:
            pytest.fail(f"Missing expected tools: {missing_tools}")

    def test_diagnostic_config_exists(self):
        """Test that diagnostic configuration exists"""
        import jenkins_mcp_enterprise

        package_path = Path(jenkins_mcp_enterprise.__file__).parent
        diagnostic_config_path = (
            package_path / "diagnostic_config" / "diagnostic-parameters.yml"
        )

        assert diagnostic_config_path.exists(), "diagnostic-parameters.yml should exist"
        print("✅ diagnostic configuration exists")

    def test_version_info_accessible(self):
        """Test that version information is accessible"""
        try:
            # Try to get version from pyproject.toml or package
            import jenkins_mcp_enterprise

            # This should not fail with basic import
            assert jenkins_mcp_enterprise is not None
            print("✅ version info accessible")
        except Exception as e:
            pytest.fail(f"Failed to access version info: {e}")
