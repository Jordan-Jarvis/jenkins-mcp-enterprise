"""Test fixtures and data factories for Jenkins MCP testing"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from jenkins_mcp_enterprise.config import (
    CacheConfig,
    JenkinsConfig,
    MCPConfig,
    VectorConfig,
)
from jenkins_mcp_enterprise.di_container import DIContainer
from jenkins_mcp_enterprise.jenkins.build_manager import BuildManager
from jenkins_mcp_enterprise.jenkins.log_fetcher import LogFetcher
from jenkins_mcp_enterprise.tool_factory import ToolFactory
from tests.mcp_integration.test_doubles import JenkinsTestDouble, QdrantTestDouble


@dataclass
class MockBuild:
    """Mock build data for testing"""

    job_name: str
    build_number: int
    status: str = "SUCCESS"
    url: str = ""

    def __post_init__(self):
        if not self.url:
            self.url = f"https://jenkins.example.com/job/{self.job_name.replace('/', '/job/')}/{self.build_number}/"


class BuildDataFactory:
    """Factory for creating test build data"""

    @staticmethod
    def create_successful_build(
        job_name: str = "test-job", build_number: int = 1
    ) -> MockBuild:
        return MockBuild(job_name=job_name, build_number=build_number, status="SUCCESS")

    @staticmethod
    def create_failed_build(
        job_name: str = "test-job", build_number: int = 1
    ) -> MockBuild:
        return MockBuild(job_name=job_name, build_number=build_number, status="FAILURE")

    @staticmethod
    def create_build_hierarchy() -> List[MockBuild]:
        """Create a test build hierarchy"""
        return [
            MockBuild("parent-job", 100, "FAILURE"),
            MockBuild("child-job-1", 50, "SUCCESS"),
            MockBuild("child-job-2", 25, "FAILURE"),
            MockBuild("grandchild-job", 10, "FAILURE"),
        ]


class LogDataFactory:
    """Factory for creating test log data"""

    @staticmethod
    def create_simple_log() -> str:
        return """
Started by user admin
Running in Jenkins version 2.400
Building on node agent-1
[Pipeline] Start of Pipeline
[Pipeline] stage
[Pipeline] { (Build)
+ gradle clean build
BUILD SUCCESSFUL in 2m 30s
[Pipeline] }
[Pipeline] End of Pipeline
Finished: SUCCESS
        """.strip()

    @staticmethod
    def create_failed_log() -> str:
        return """
Started by user admin
Running in Jenkins version 2.400
Building on node agent-1
[Pipeline] Start of Pipeline
[Pipeline] stage
[Pipeline] { (Build)
+ gradle clean build
> Task :test FAILED

FAILURE: Build failed with an exception.

* What went wrong:
Execution failed for task ':test'.
> There were failing tests. See the test report at: file:///path/to/report

* Try:
Run with --stacktrace option to get the stack trace.
Run with --info or --debug option to get more log output.

BUILD FAILED in 1m 45s
[Pipeline] }
[Pipeline] End of Pipeline
Finished: FAILURE
        """.strip()

    @staticmethod
    def create_java_exception_log() -> str:
        return """
Started by user admin
[Pipeline] Start of Pipeline
java.lang.NullPointerException: Cannot invoke method on null object
    at com.example.TestClass.testMethod(TestClass.java:42)
    at com.example.Runner.main(Runner.java:15)
Caused by: java.lang.IllegalStateException: Invalid state
    at com.example.StateManager.validateState(StateManager.java:123)
    ... 5 more
[Pipeline] End of Pipeline
Finished: FAILURE
        """.strip()


@pytest.fixture
def mock_jenkins_config():
    """Fixture providing mock Jenkins configuration"""
    return {
        "url": "https://jenkins.example.com",
        "username": "test_user",
        "token": "test_token",
        "timeout": 30,
        "verify_ssl": False,
    }


@dataclass
class TestEnvironment:
    """Test environment for integration tests"""

    container: "DIContainer"
    jenkins_double: "JenkinsTestDouble"
    qdrant: Optional["QdrantTestDouble"]
    config: Dict[str, Any]

    def get_jenkins_client(self):
        from jenkins_mcp_enterprise.jenkins.jenkins_client import JenkinsClient

        return self.container.get(JenkinsClient)

    def get_cache_manager(self):
        from jenkins_mcp_enterprise.cache_manager import CacheManager

        return self.container.get(CacheManager)

    def get_vector_manager(self):
        from jenkins_mcp_enterprise.vector_manager import VectorManager

        return self.container.get(VectorManager)

    def get_build_manager(self):
        return self.container.get(BuildManager)

    def get_log_fetcher(self):
        return self.container.get(LogFetcher)

    def add_jenkins_job(self, job_name, job_data):
        self.jenkins_double.add_job(job_name, job_data)

    def add_jenkins_build(self, job_name, build_number, build_data):
        self.jenkins_double.add_build(job_name, build_number, build_data)

    def add_console_log(self, job_name, build_number, log_content):
        self.jenkins_double.add_console_log(job_name, build_number, log_content)


@pytest.fixture
def jenkins_test_env():
    """Fixture providing test environment with DI container and test doubles"""
    # Use dynamic ports to avoid conflicts
    jenkins_double = JenkinsTestDouble(port=0)
    jenkins_double.start()

    qdrant_double = QdrantTestDouble(port=0)
    qdrant_double.start()
    qdrant_port = qdrant_double.server.server_port
    qdrant_double.port = qdrant_port

    # Ensure vector search is enabled for tests
    original_disable_vector = os.environ.get("DISABLE_VECTOR_SEARCH")
    os.environ["DISABLE_VECTOR_SEARCH"] = "false"

    cache_dir = tempfile.mkdtemp(prefix="mcp-cache-")

    # Create a temporary config file for the test.
    # This structure is for the MultiJenkinsManager to parse.
    config_content = f"""
    default_instance:
      id: "test_jenkins"
      url: "http://localhost:{jenkins_double.server.server_port}"
      username: "test"
      token: "test"
      verify_ssl: false
      timeout: 30

    jenkins_instances:
      test_jenkins:
        url: "http://localhost:{jenkins_double.server.server_port}"
        username: "test"
        token: "test"
        verify_ssl: false
        display_name: "Test Jenkins"
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yml") as tmp:
        tmp.write(config_content)
        config_file_path = tmp.name

    # Build explicit configuration for the DI container
    jenkins_config = JenkinsConfig(
        url=f"http://localhost:{jenkins_double.server.server_port}",
        username="test",
        token="test",
        verify_ssl=False,
    )
    cache_config = CacheConfig(
        base_dir=Path(cache_dir),
        max_size_mb=250,
        retention_days=3,
        enable_compression=True,
    )
    vector_config = VectorConfig(
        host=f"http://localhost:{qdrant_port}",
        collection_name="test-jenkins-logs",
        embedding_model="all-MiniLM-L6-v2",
        chunk_size=100,
        chunk_overlap=20,
        top_k_default=5,
        timeout=15,
    )
    mcp_config = MCPConfig(
        jenkins=jenkins_config, cache=cache_config, vector=vector_config
    )

    container = DIContainer(config=mcp_config, config_file_path=config_file_path)

    # Manually register components needed for integration tests
    jenkins_client = container.get_jenkins_client()

    build_manager = BuildManager(jenkins_client.connection)
    container._instances[BuildManager] = build_manager

    log_fetcher = LogFetcher(jenkins_client.connection)
    container._instances[LogFetcher] = log_fetcher

    tool_factory = ToolFactory(container)
    container._instances[ToolFactory] = tool_factory

    # Create the config dict for the MCPTestClient
    config_dict = mcp_config.to_dict()
    config_dict.update(
        {
            "config_file_path": config_file_path,
            "jenkins": {
                "url": jenkins_config.url,
                "username": jenkins_config.username,
                "token": jenkins_config.token,
                "timeout": jenkins_config.timeout,
                "verify_ssl": jenkins_config.verify_ssl,
            },
            "vector": {
                "host": vector_config.host,
                "collection_name": vector_config.collection_name,
                "embedding_model": vector_config.embedding_model,
                "chunk_size": vector_config.chunk_size,
                "chunk_overlap": vector_config.chunk_overlap,
                "top_k_default": vector_config.top_k_default,
                "timeout": vector_config.timeout,
            },
            "cache": {
                "base_dir": str(cache_config.base_dir),
                "max_size_mb": cache_config.max_size_mb,
                "retention_days": cache_config.retention_days,
                "enable_compression": cache_config.enable_compression,
            },
        }
    )

    env = TestEnvironment(
        container=container,
        jenkins_double=jenkins_double,
        qdrant=qdrant_double,
        config=config_dict,
    )

    try:
        yield env
    finally:
        jenkins_double.stop()
        qdrant_double.stop()
        os.unlink(config_file_path)
        shutil.rmtree(cache_dir, ignore_errors=True)

        if original_disable_vector is None:
            os.environ.pop("DISABLE_VECTOR_SEARCH", None)
        else:
            os.environ["DISABLE_VECTOR_SEARCH"] = original_disable_vector


@pytest.fixture
def sample_builds():
    """Fixture providing sample build data"""
    return BuildDataFactory.create_build_hierarchy()


@pytest.fixture
def sample_logs():
    """Fixture providing sample log data"""
    return {
        "success": LogDataFactory.create_simple_log(),
        "failure": LogDataFactory.create_failed_log(),
        "java_exception": LogDataFactory.create_java_exception_log(),
    }


@pytest.fixture
def seeded_jenkins_test_env(jenkins_test_env, sample_builds, sample_logs):
    """Fixture providing a test environment with pre-seeded Jenkins data"""
    env = jenkins_test_env

    # Seed with a simple job with parameters
    env.add_jenkins_job(
        "sample-job",
        {
            "name": "sample-job",
            "url": f"http://localhost:{env.jenkins_double.port}/job/sample-job/",
            "actions": [
                {
                    "_class": "hudson.model.ParametersDefinitionProperty",
                    "parameterDefinitions": [
                        {
                            "name": "BRANCH",
                            "type": "StringParameterDefinition",
                            "defaultParameterValue": {"value": "main"},
                        },
                        {
                            "name": "DEPLOY_ENV",
                            "type": "ChoiceParameterDefinition",
                            "choices": ["dev", "staging", "prod"],
                        },
                    ],
                }
            ],
            "property": [],
        },
    )
    env.add_jenkins_build("sample-job", 1, {"result": "SUCCESS"})
    env.add_console_log("sample-job", 1, sample_logs["success"])

    # Seed with a more complex job hierarchy for diagnosis tests
    env.add_jenkins_job(
        "QA_JOBS/master",
        {
            "name": "master",
            "url": f"http://localhost:{env.jenkins_double.port}/job/QA_JOBS/job/master/",
            "builds": [
                {
                    "number": 9,
                    "url": f"http://localhost:{env.jenkins_double.port}/job/QA_JOBS/job/master/9/",
                }
            ],
            "lastBuild": {"number": 9},
        },
    )
    env.add_jenkins_build(
        "QA_JOBS/master",
        9,
        {
            "number": 9,
            "result": "FAILURE",
            "url": f"http://localhost:{env.jenkins_double.port}/job/QA_JOBS/job/master/9/",
            "actions": [
                {},
                {
                    "nodes": [
                        {
                            "displayName": "Sub Build 1",
                            "url": "job/QA_JOBS/job/sub-build-1/1/",
                            "actions": [
                                {"description": "job » QA_JOBS/sub-build-1 #1"},
                                {},
                            ],
                        },
                        {
                            "displayName": "Sub Build 2",
                            "url": "job/QA_JOBS/job/sub-build-2/1/",
                            "actions": [
                                {"description": "job » QA_JOBS/sub-build-2 #1"},
                                {},
                            ],
                        },
                    ]
                },
                # Add explicit causes so strict downstream validation can confirm these
                # are true children of QA_JOBS/master#9.
                {
                    "causes": [
                        {
                            "upstreamProject": "QA_JOBS/master",
                            "upstreamBuild": 9,
                            "shortDescription": "Started by upstream project QA_JOBS/master build #9",
                        }
                    ]
                },
            ],
        },
    )
    # Create a log with a specific, searchable error
    failed_log_with_pattern = (
        sample_logs["failure"] + "\n[ERROR] A critical failure occurred."
    )
    env.add_console_log("QA_JOBS/master", 9, failed_log_with_pattern)

    # Add sub-builds triggered by the master build
    env.add_jenkins_job("QA_JOBS/sub-build-1", {"name": "sub-build-1"})
    env.add_jenkins_build(
        "QA_JOBS/sub-build-1",
        1,
        {
            "result": "SUCCESS",
            "actions": [
                {
                    "causes": [
                        {
                            "upstreamProject": "QA_JOBS/master",
                            "upstreamBuild": 9,
                            "shortDescription": "Started by upstream project QA_JOBS/master build #9",
                        }
                    ]
                }
            ],
        },
    )
    env.add_console_log("QA_JOBS/sub-build-1", 1, sample_logs["success"])

    env.add_jenkins_job("QA_JOBS/sub-build-2", {"name": "sub-build-2"})
    env.add_jenkins_build(
        "QA_JOBS/sub-build-2",
        1,
        {
            "result": "FAILURE",
            "actions": [
                {
                    "causes": [
                        {
                            "upstreamProject": "QA_JOBS/master",
                            "upstreamBuild": 9,
                            "shortDescription": "Started by upstream project QA_JOBS/master build #9",
                        }
                    ]
                }
            ],
        },
    )
    # Ensure the failing sub-build contains an explicit ERROR line so error analysis
    # can focus on this build (not the parent pipeline).
    env.add_console_log(
        "QA_JOBS/sub-build-2",
        1,
        sample_logs["failure"] + "\n[ERROR] Sub-build-2 failure marker\n",
    )

    return env
