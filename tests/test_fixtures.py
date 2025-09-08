"""Test fixtures and data factories for Jenkins MCP testing"""

import pytest
from dataclasses import dataclass
from typing import Dict, List, Optional
from pathlib import Path


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
    def create_successful_build(job_name: str = "test-job", build_number: int = 1) -> MockBuild:
        return MockBuild(
            job_name=job_name,
            build_number=build_number,
            status="SUCCESS"
        )
    
    @staticmethod
    def create_failed_build(job_name: str = "test-job", build_number: int = 1) -> MockBuild:
        return MockBuild(
            job_name=job_name,
            build_number=build_number,
            status="FAILURE"
        )
    
    @staticmethod
    def create_build_hierarchy() -> List[MockBuild]:
        """Create a test build hierarchy"""
        return [
            MockBuild("parent-job", 100, "FAILURE"),
            MockBuild("child-job-1", 50, "SUCCESS"),
            MockBuild("child-job-2", 25, "FAILURE"),
            MockBuild("grandchild-job", 10, "FAILURE")
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
        "verify_ssl": False
    }


@pytest.fixture
def jenkins_test_env():
    """Fixture providing test environment configuration"""
    return {
        "jenkins_url": "http://localhost:18083",
        "timeout": 5,
        "verify_ssl": False
    }


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
        "java_exception": LogDataFactory.create_java_exception_log()
    }