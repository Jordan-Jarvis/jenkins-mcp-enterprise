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


def test_trigger_build_retries_after_stale_crumb_error():
    client = Mock()
    client.build_job.side_effect = [
        Exception("403 Forbidden: No valid crumb was included in the request"),
        44,
    ]
    client.get_queue_item.return_value = {"executable": {"number": 9}}
    connection = SimpleNamespace(
        client=client,
        config=SimpleNamespace(url="http://jenkins.example", token="admin123"),
        should_refresh_on_error=lambda error: "crumb" in str(error).lower(),
        refresh_connection=Mock(),
    )

    manager = BuildManager(connection)
    build = manager.trigger_build("deep-01")

    assert client.build_job.call_count == 2
    connection.refresh_connection.assert_called_once_with()
    assert build.build_number == 9


def test_trigger_build_falls_back_when_queue_item_disappears():
    client = Mock()
    client.build_job.return_value = 45
    client.get_queue_item.side_effect = Exception("queue number[45] does not exist")
    client.get_job_info.return_value = {"lastBuild": {"number": 10}}
    connection = SimpleNamespace(
        client=client,
        config=SimpleNamespace(url="http://jenkins.example", token="admin123"),
    )

    manager = BuildManager(connection)
    build = manager.trigger_build("deep-01")

    client.get_job_info.assert_called_once_with("deep-01")
    assert build.build_number == 10
