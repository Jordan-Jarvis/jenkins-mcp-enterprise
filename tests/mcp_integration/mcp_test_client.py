"""MCP test client for integration testing"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MCPTestClient:
    """Test client that communicates with MCP server via stdio JSON-RPC"""

    def __init__(
        self,
        server_script: str = "jenkins_mcp_enterprise.server",
        config: Optional[Any] = None,
    ):
        self.server_script = server_script
        self.config = config
        self.process: Optional[asyncio.subprocess.Process] = None
        self.request_id = 0
        self._reader_task = None
        self._responses = {}
        self._server_ready = False

    @property
    def server_ready(self) -> bool:
        """Return True if the server is initialized and ready."""
        return self._server_ready

    async def start_server(self) -> None:
        """Start the MCP server process"""
        env = os.environ.copy()

        # Disable vector search for testing
        env["DISABLE_VECTOR_SEARCH"] = "true"

        # Start the server. If a config file path is provided in the config object,
        # use it. Otherwise, let the server use its default.
        cmd = [sys.executable, "-m", self.server_script]
        # The config object is now the DI container, which holds the config file path
        if hasattr(self.config, "config_file_path") and self.config.config_file_path:
            cmd.extend(["--config", str(self.config.config_file_path)])
        elif isinstance(self.config, dict) and "config_file_path" in self.config:
            cmd.extend(["--config", self.config["config_file_path"]])
        logger.info(f"Starting MCP server with command: {cmd}")

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Start reader task
        self._reader_task = asyncio.create_task(self._read_responses())

        # Wait for server initialization
        await self._wait_for_server_ready()

    async def _wait_for_server_ready(self, timeout: float = 10.0):
        """Wait for server to be ready by sending initialization request"""
        start_time = time.time()

        # Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
                "clientInfo": {"name": "mcp-test-client", "version": "1.0.0"},
            },
        }

        await self._send_request(init_request)

        # Wait for initialize response
        while time.time() - start_time < timeout:
            if "init" in self._responses:
                response = self._responses["init"]
                if "result" in response:
                    self._server_ready = True
                    logger.info("MCP server initialized successfully")

                    # Send initialized notification
                    initialized_notif = {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    }
                    await self._send_request(initialized_notif)
                    return
                elif "error" in response:
                    raise RuntimeError(
                        f"Server initialization failed: {response['error']}"
                    )

            await asyncio.sleep(0.1)

        # If timeout is reached, read stderr for debugging info
        stderr = ""
        if self.process and self.process.stderr:
            stderr_data = await self.process.stderr.read()
            if stderr_data:
                stderr = stderr_data.decode("utf-8")

        raise TimeoutError(
            f"Server failed to initialize within timeout. Stderr: {stderr}"
        )

    async def _read_responses(self):
        """Continuously read responses from the server"""
        while self.process and not self.process.stdout.at_eof():
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    response = json.loads(line_str)
                    if "id" in response:
                        self._responses[response["id"]] = response
                        logger.debug(f"Received response for request {response['id']}")
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to decode JSON response: {line_str}, error: {e}"
                    )
            except Exception as e:
                logger.error(f"Error reading server response: {e}")
                break

    async def _send_request(self, request: Dict[str, Any]):
        """Send a request to the server"""
        if not self.process or not self.process.stdin:
            raise RuntimeError("Server process not started")

        request_json = json.dumps(request) + "\n"
        self.process.stdin.write(request_json.encode("utf-8"))
        await self.process.stdin.drain()
        logger.debug(
            f"Sent request: {request.get('method', 'unknown')} (id: {request.get('id', 'none')})"
        )

    async def stop_server(self) -> None:
        """Stop the MCP server process"""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self.process:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

            # Read any remaining stderr for debugging
            if self.process.stderr:
                stderr_data = await self.process.stderr.read()
                if stderr_data:
                    logger.debug(f"Server stderr: {stderr_data.decode('utf-8')}")

    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any], timeout: float = 30.0
    ) -> Dict[str, Any]:
        """Call a tool and return the result"""
        if not self._server_ready:
            raise RuntimeError("Server not ready. Did you call start_server()?")

        self.request_id += 1
        request_id = f"tool-{self.request_id}"

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        await self._send_request(request)

        # Wait for response
        start_time = time.time()
        while time.time() - start_time < timeout:
            if request_id in self._responses:
                response = self._responses.pop(request_id)
                if "error" in response:
                    raise RuntimeError(f"Tool call error: {response['error']}")
                return response.get("result", {})
            await asyncio.sleep(0.1)

        raise TimeoutError(f"Tool call {tool_name} timed out after {timeout}s")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools"""
        if not self._server_ready:
            raise RuntimeError("Server not ready. Did you call start_server()?")

        self.request_id += 1
        request_id = f"list-tools-{self.request_id}"

        request = {"jsonrpc": "2.0", "id": request_id, "method": "tools/list"}

        await self._send_request(request)

        # Wait for response
        start_time = time.time()
        while time.time() - start_time < 5.0:
            if request_id in self._responses:
                response = self._responses.pop(request_id)
                if "error" in response:
                    raise RuntimeError(f"List tools error: {response['error']}")
                return response.get("result", {}).get("tools", [])
            await asyncio.sleep(0.1)

        raise TimeoutError("List tools request timed out")

    async def __aenter__(self):
        await self.start_server()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop_server()
