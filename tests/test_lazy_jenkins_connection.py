import jenkins
import pytest

from jenkins_mcp_enterprise.config import JenkinsConfig
from jenkins_mcp_enterprise.exceptions import JenkinsConnectionError
from jenkins_mcp_enterprise.jenkins.connection_manager import JenkinsConnectionManager


def test_connection_manager_is_lazy_by_default(monkeypatch):
    """We should not hit Jenkins during initialization (important for Docker/README startup)."""

    def _boom(self):  # pragma: no cover
        raise RuntimeError("should not be called during init")

    monkeypatch.setattr(jenkins.Jenkins, "get_whoami", _boom)

    cfg = JenkinsConfig(
        url="https://jenkins-dev.example.com",
        username="dummy",
        token="dummy",
        timeout=1,
        verify_ssl=False,
    )

    mgr = JenkinsConnectionManager(cfg)
    assert mgr.client is not None
    assert mgr.session is not None


def test_connection_manager_can_fail_fast_when_requested(monkeypatch):
    """Optional fail-fast mode should validate connectivity/auth and raise on failure."""

    def _boom(self):  # pragma: no cover
        raise RuntimeError("boom")

    monkeypatch.setattr(jenkins.Jenkins, "get_whoami", _boom)

    cfg = JenkinsConfig(
        url="https://jenkins-dev.example.com",
        username="dummy",
        token="dummy",
        timeout=1,
        verify_ssl=False,
    )

    with pytest.raises(JenkinsConnectionError):
        JenkinsConnectionManager(cfg, validate_on_init=True)
