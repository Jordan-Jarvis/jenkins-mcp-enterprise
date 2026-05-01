"""Regression tests for YAML config loading paths."""

from jenkins_mcp_enterprise.server import load_config_from_yaml


def test_load_config_from_yaml_uses_fallback_instance_when_default_missing(tmp_path):
    config_path = tmp_path / "mcp-config.yml"
    config_path.write_text("""
jenkins_instances:
  demo:
    url: "http://jenkins-example:8080"
    username: "admin"
    token: "admin123"
settings:
  fallback_instance: "demo"
""".strip())

    config = load_config_from_yaml(str(config_path))

    assert config.jenkins.url == "http://jenkins-example:8080"
    assert config.jenkins.username == "admin"
    assert config.jenkins.token == "admin123"
