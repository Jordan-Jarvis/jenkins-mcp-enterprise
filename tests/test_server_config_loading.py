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


def test_create_server_applies_configured_log_level_and_file(monkeypatch, tmp_path):
    """Regression test: server.log_level/log_file from --config YAML must
    actually reach setup_logging(), not just get parsed and ignored."""
    import jenkins_mcp_enterprise.server as server_mod
    from jenkins_mcp_enterprise.config_factory import ConfigFactory

    monkeypatch.setenv("DISABLE_VECTOR_SEARCH", "true")  # avoid touching real Qdrant

    calls = []
    monkeypatch.setattr(
        server_mod,
        "setup_logging",
        lambda level="INFO", log_file=None: calls.append((level, log_file)),
    )

    config = ConfigFactory.create_test_config()
    log_file = str(tmp_path / "server.log")
    config.server.log_level = "DEBUG"
    config.server.log_file = log_file

    server_mod.create_server(config=config, config_file_path=None)

    assert calls == [("DEBUG", log_file)]


def test_create_server_falls_back_to_default_logging_without_config(monkeypatch):
    """When create_server() is called with no config at all, it should keep
    using setup_logging()'s own defaults rather than raising."""
    import jenkins_mcp_enterprise.server as server_mod

    monkeypatch.setenv("DISABLE_VECTOR_SEARCH", "true")
    monkeypatch.setenv("JENKINS_URL", "http://test-jenkins:8080")
    monkeypatch.setenv("JENKINS_USER", "test-user")
    monkeypatch.setenv("JENKINS_TOKEN", "test-token")

    calls = []
    monkeypatch.setattr(
        server_mod,
        "setup_logging",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    server_mod.create_server(config=None, config_file_path=None)

    assert calls == [((), {})]


def test_module_import_does_not_lock_in_default_logging_handlers():
    """Regression test: importing jenkins_mcp_enterprise.logging_config (or
    anything that transitively imports it, e.g. server.py) must not itself
    attach handlers to the 'jenkins_mcp' logger — otherwise setup_logging()'s
    own already-configured guard makes create_server()'s later, real call
    (with the actual configured log_level/log_file) a silent no-op."""
    import logging

    jenkins_logger = logging.getLogger("jenkins_mcp")
    for handler in list(jenkins_logger.handlers):
        jenkins_logger.removeHandler(handler)

    import importlib

    import jenkins_mcp_enterprise.logging_config as logging_config_mod

    importlib.reload(logging_config_mod)

    assert jenkins_logger.handlers == []
