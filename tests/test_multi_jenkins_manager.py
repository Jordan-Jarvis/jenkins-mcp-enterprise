from pathlib import Path

import pytest
import yaml

from jenkins_mcp_enterprise.exceptions import ConfigurationError
from jenkins_mcp_enterprise.multi_jenkins_manager import MultiJenkinsManager


def _write_config(tmp_path: Path, instances: dict) -> str:
    config_path = tmp_path / "jenkins-instances.yml"
    config_path.write_text(yaml.safe_dump({"jenkins_instances": instances}))
    return str(config_path)


def _instance(url: str) -> dict:
    return {
        "url": url,
        "username": "tester",
        "token": "secret",
        "display_name": url,
    }


def test_resolve_jenkins_url_accepts_base_url_and_trailing_slash(tmp_path: Path):
    manager = MultiJenkinsManager(
        _write_config(
            tmp_path,
            {"prod": _instance("https://jenkins.example.com")},
        )
    )

    assert manager.resolve_jenkins_url("https://jenkins.example.com") == "prod"
    assert manager.resolve_jenkins_url("https://jenkins.example.com/") == "prod"


def test_resolve_jenkins_url_accepts_full_job_and_build_urls(tmp_path: Path):
    manager = MultiJenkinsManager(
        _write_config(
            tmp_path,
            {"prod": _instance("https://jenkins.example.com")},
        )
    )

    assert (
        manager.resolve_jenkins_url(
            "https://jenkins.example.com/job/TeamA/job/my-pipeline"
        )
        == "prod"
    )
    assert (
        manager.resolve_jenkins_url(
            "https://jenkins.example.com/job/TeamA/job/my-pipeline/123/"
        )
        == "prod"
    )


def test_resolve_jenkins_url_accepts_encoded_full_urls(tmp_path: Path):
    manager = MultiJenkinsManager(
        _write_config(
            tmp_path,
            {"prod": _instance("https://jenkins.example.com")},
        )
    )

    assert (
        manager.resolve_jenkins_url(
            "https://jenkins.example.com/job/release%252F2.2.0/123/"
        )
        == "prod"
    )


def test_resolve_jenkins_url_accepts_context_path_and_api_urls(tmp_path: Path):
    manager = MultiJenkinsManager(
        _write_config(
            tmp_path,
            {"corp": _instance("https://ci.example.com/jenkins")},
        )
    )

    assert manager.resolve_jenkins_url("https://ci.example.com/jenkins") == "corp"
    assert (
        manager.resolve_jenkins_url("https://ci.example.com/jenkins/api/json") == "corp"
    )
    assert (
        manager.resolve_jenkins_url(
            "https://ci.example.com/jenkins/job/TeamA/job/my-pipeline/123/api/json"
        )
        == "corp"
    )


def test_resolve_jenkins_url_accepts_missing_scheme_when_match_is_unique(
    tmp_path: Path,
):
    manager = MultiJenkinsManager(
        _write_config(
            tmp_path,
            {"corp": _instance("http://ci.example.com/jenkins")},
        )
    )

    assert (
        manager.resolve_jenkins_url("ci.example.com/jenkins/job/example/42") == "corp"
    )


def test_resolve_jenkins_url_reports_ambiguous_matches(tmp_path: Path):
    manager = MultiJenkinsManager(
        _write_config(
            tmp_path,
            {
                "http": _instance("http://ci.example.com/jenkins"),
                "https": _instance("https://ci.example.com/jenkins"),
            },
        )
    )

    with pytest.raises(ConfigurationError) as exc_info:
        manager.resolve_jenkins_url("ci.example.com/jenkins/job/example/42")

    assert "Multiple Jenkins instances match URL" in str(exc_info.value)
    assert "http://ci.example.com/jenkins" in str(exc_info.value)
    assert "https://ci.example.com/jenkins" in str(exc_info.value)


def test_resolve_jenkins_url_reports_helpful_no_match_message(tmp_path: Path):
    manager = MultiJenkinsManager(
        _write_config(
            tmp_path,
            {"prod": _instance("https://jenkins.example.com")},
        )
    )

    with pytest.raises(ConfigurationError) as exc_info:
        manager.resolve_jenkins_url("https://other.example.com/job/example/42")

    message = str(exc_info.value)
    assert "No Jenkins instance configured for URL" in message
    assert "https://jenkins.example.com" in message
    assert "full Jenkins job/build URL" in message
