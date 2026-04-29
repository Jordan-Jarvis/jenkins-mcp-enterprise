import sys


def test_streamable_http_cli_applies_host_port_and_path(monkeypatch):
    """
    Regression test for #13: --host/--port/--mount-path must be applied for streamable-http.

    We stub create_server to avoid constructing the full DI container/tooling.
    """
    import jenkins_mcp_enterprise.server as server_mod

    class DummySettings:
        def __init__(self):
            self.host = "127.0.0.1"
            self.port = 8000
            self.streamable_http_path = "/mcp"

    class DummyServer:
        def __init__(self):
            self.settings = DummySettings()
            self.run_calls: list[dict] = []

        def run(self, transport="stdio", mount_path=None):
            self.run_calls.append({"transport": transport, "mount_path": mount_path})

    dummy = DummyServer()

    def fake_create_server(config=None, config_file_path=None):
        return dummy

    monkeypatch.setattr(server_mod, "create_server", fake_create_server)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jenkins_mcp_enterprise",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "1234",
            "--mount-path",
            "/custom",
        ],
    )

    server_mod.main()

    assert dummy.settings.host == "0.0.0.0"
    assert dummy.settings.port == 1234
    assert dummy.settings.streamable_http_path == "/custom"
    assert dummy.run_calls == [{"transport": "streamable-http", "mount_path": None}]
