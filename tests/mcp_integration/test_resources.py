"""MCP resources integration tests.

These tests validate that the MCP server exposes expected resources and that
resources/read returns usable metadata.

Why these tests exist:
- Tools rely on `jenkins_url` routing.
- Resources are intended to provide metadata/UX hints (not secrets).
- Historically, resources were not covered by the integration suite.
"""

import asyncio
import json
import time

import pytest

from .mcp_test_client import MCPTestClient


async def _send_json_rpc(client: MCPTestClient, request: dict) -> None:
    """Send a raw JSON-RPC request using the test client's transport."""
    await client._send_request(request)


async def _wait_for_response(
    client: MCPTestClient, request_id: str, timeout: float = 5.0
) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        if request_id in client._responses:
            return client._responses.pop(request_id)
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for response id={request_id}")


def _extract_json_from_contents(contents: list) -> dict | None:
    """Extract JSON payload from MCP resources/read contents.

    FastMCP may return JSON resources either as:
    - {"json": <dict>}
    - {"mimeType": "application/json", "text": "{...json...}"}
    """
    for item in contents:
        if isinstance(item, dict) and "json" in item and isinstance(item["json"], dict):
            return item["json"]

    for item in contents:
        if (
            isinstance(item, dict)
            and item.get("mimeType") == "application/json"
            and isinstance(item.get("text"), str)
        ):
            try:
                parsed = json.loads(item["text"])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue

    return None


@pytest.mark.asyncio
async def test_resources_list_includes_jenkins_instances(seeded_jenkins_test_env):
    config = seeded_jenkins_test_env.config

    async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
        client.request_id += 1
        request_id = f"resources-list-{client.request_id}"
        await _send_json_rpc(
            client,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "resources/list",
                "params": {},
            },
        )

        response = await _wait_for_response(client, request_id)
        assert "error" not in response
        result = response.get("result", {})

        # FastMCP returns a list of resources and optionally templates.
        resources = result.get("resources", [])
        templates = result.get("resourceTemplates", [])

        # Ensure `jenkins://instances` is present as either a concrete resource or template.
        uris = {r.get("uri") for r in resources if isinstance(r, dict)}
        template_uris = {t.get("uriTemplate") for t in templates if isinstance(t, dict)}

        assert (
            "jenkins://instances" in uris or "jenkins://instances" in template_uris
        ), f"Expected jenkins://instances in resources/list. Got uris={uris}, templates={template_uris}"


@pytest.mark.asyncio
async def test_resources_read_instances_returns_metadata_only(seeded_jenkins_test_env):
    config = seeded_jenkins_test_env.config

    async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
        client.request_id += 1
        request_id = f"resources-read-{client.request_id}"
        await _send_json_rpc(
            client,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "resources/read",
                "params": {"uri": "jenkins://instances"},
            },
        )

        response = await _wait_for_response(client, request_id)
        assert "error" not in response

        # MCP resources/read returns `contents` which can contain JSON or text.
        result = response.get("result", {})
        contents = result.get("contents", [])
        assert contents, f"Expected contents from resources/read, got: {result}"

        json_payload = _extract_json_from_contents(contents)
        assert json_payload is not None, f"Expected JSON content, got: {contents}"

        assert "instances" in json_payload
        assert isinstance(json_payload["instances"], list)

        # Ensure we are not leaking credentials.
        # (We still allow a boolean has_credentials.)
        sample = json_payload["instances"][0] if json_payload["instances"] else {}
        assert "token" not in sample
        assert "username" not in sample
        assert "has_credentials" in sample


@pytest.mark.asyncio
async def test_resources_read_instance_by_key(seeded_jenkins_test_env):
    config = seeded_jenkins_test_env.config

    async with MCPTestClient("jenkins_mcp_enterprise.server", config) as client:
        # First read the instances list
        client.request_id += 1
        list_id = f"resources-read-{client.request_id}"
        await _send_json_rpc(
            client,
            {
                "jsonrpc": "2.0",
                "id": list_id,
                "method": "resources/read",
                "params": {"uri": "jenkins://instances"},
            },
        )
        list_response = await _wait_for_response(client, list_id)
        assert "error" not in list_response

        list_contents = list_response.get("result", {}).get("contents", [])
        json_payload = _extract_json_from_contents(list_contents)

        assert json_payload and json_payload.get("instances")
        instance_uri = json_payload["instances"][0]["uri"]

        # Now read that instance
        client.request_id += 1
        read_id = f"resources-read-{client.request_id}"
        await _send_json_rpc(
            client,
            {
                "jsonrpc": "2.0",
                "id": read_id,
                "method": "resources/read",
                "params": {"uri": instance_uri},
            },
        )

        read_response = await _wait_for_response(client, read_id)
        assert "error" not in read_response

        read_contents = read_response.get("result", {}).get("contents", [])
        instance_json = _extract_json_from_contents(read_contents)

        assert instance_json is not None
        assert instance_json.get("status") == "configured"
        assert "url" in instance_json
        assert "display_name" in instance_json
        assert "token" not in instance_json
        assert "username" not in instance_json
