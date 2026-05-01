from types import SimpleNamespace
from unittest.mock import Mock

from jenkins_mcp_enterprise.jenkins.build_manager import BuildManager


def test_trigger_build_does_not_reuse_config_token_as_job_trigger_token():
    client = Mock()
    client.build_job.return_value = 42
    client.get_queue_item.return_value = {"executable": {"number": 7}}
    connection = SimpleNamespace(
        client=client,
        config=SimpleNamespace(url="http://jenkins.example", token="admin123"),
    )

    manager = BuildManager(connection)
    build = manager.trigger_build("deep-01")

    client.build_job.assert_called_once_with("deep-01", parameters={})
    assert build.build_number == 7
    assert build.url == "http://jenkins.example/job/deep-01/7/"


def test_trigger_build_passes_explicit_job_trigger_token():
    client = Mock()
    client.build_job.return_value = 43
    client.get_queue_item.return_value = {"executable": {"number": 8}}
    connection = SimpleNamespace(
        client=client,
        config=SimpleNamespace(url="http://jenkins.example", token="admin123"),
    )

    manager = BuildManager(connection)
    build = manager.trigger_build("deep-01", token="build-trigger-token")

    client.build_job.assert_called_once_with(
        "deep-01",
        parameters={},
        token="build-trigger-token",
    )
    assert build.build_number == 8
    assert build.url == "http://jenkins.example/job/deep-01/8/"
