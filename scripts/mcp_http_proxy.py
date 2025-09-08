#!/usr/bin/env python3
"""
HTTP Proxy for Jenkins MCP Server

This proxy converts HTTP requests to MCP stdio protocol for containerized deployment.
Useful for environments where stdio transport is not available.
"""

import asyncio
import json
import logging
import os
import subprocess
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Jenkins MCP Server HTTP Proxy",
    description="HTTP proxy for Jenkins MCP Server stdio transport",
    version="1.0.0",
)


class MCPStdioProxy:
    """Proxy that converts HTTP requests to MCP stdio communication"""

    def __init__(self, jenkins_mcp_enterprise_command: list):
        self.jenkins_mcp_enterprise_command = jenkins_mcp_enterprise_command
        self.process: Optional[subprocess.Popen] = None
        self.request_id_counter = 0

    async def start_jenkins_mcp_enterprise(self):
        """Start the MCP server process"""
        try:
            self.process = subprocess.Popen(
                self.jenkins_mcp_enterprise_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0,
            )
            logger.info(
                f"Started MCP server: {' '.join(self.jenkins_mcp_enterprise_command)}"
            )
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            raise

    async def send_request(
        self, method: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Send JSON-RPC request to MCP server"""
        if not self.process:
            await self.start_jenkins_mcp_enterprise()

        self.request_id_counter += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id_counter,
            "method": method,
            "params": params or {},
        }

        try:
            # Send request
            request_line = json.dumps(request) + "\n"
            self.process.stdin.write(request_line)
            self.process.stdin.flush()

            # Read response
            response_line = self.process.stdout.readline()
            if not response_line:
                raise Exception("No response from MCP server")

            response = json.loads(response_line.strip())
            return response

        except Exception as e:
            logger.error(f"Error communicating with MCP server: {e}")
            # Try to restart the process
            await self.stop_jenkins_mcp_enterprise()
            await self.start_jenkins_mcp_enterprise()
            raise HTTPException(
                status_code=500, detail=f"MCP server communication error: {e}"
            )

    async def stop_jenkins_mcp_enterprise(self):
        """Stop the MCP server process"""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None


# Initialize proxy
jenkins_mcp_enterprise_host = os.getenv(
    "jenkins_mcp_enterprise_HOST", "jenkins_mcp_enterprise-server"
)
mcp_command = [
    "docker",
    "exec",
    "-i",
    jenkins_mcp_enterprise_host,
    "python3",
    "-m",
    "jenkins_mcp_enterprise.server",
]
proxy = MCPStdioProxy(mcp_command)


@app.on_event("startup")
async def startup_event():
    """Initialize MCP server on startup"""
    await proxy.start_jenkins_mcp_enterprise()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up MCP server on shutdown"""
    await proxy.stop_jenkins_mcp_enterprise()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "jenkins_mcp_enterprise-proxy"}


@app.post("/mcp/initialize")
async def initialize():
    """Initialize MCP connection"""
    try:
        response = await proxy.send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "clientInfo": {
                    "name": "jenkins_mcp_enterprise-proxy",
                    "version": "1.0.0",
                },
            },
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/mcp/tools/list")
async def list_tools():
    """List available MCP tools"""
    try:
        response = await proxy.send_request("tools/list")
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mcp/tools/call")
async def call_tool(request: Request):
    """Call an MCP tool"""
    try:
        body = await request.json()
        tool_name = body.get("name")
        arguments = body.get("arguments", {})

        response = await proxy.send_request(
            "tools/call", {"name": tool_name, "arguments": arguments}
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/mcp/resources/list")
async def list_resources():
    """List available MCP resources"""
    try:
        response = await proxy.send_request("resources/list")
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mcp/resources/read")
async def read_resource(request: Request):
    """Read an MCP resource"""
    try:
        body = await request.json()
        uri = body.get("uri")

        response = await proxy.send_request("resources/read", {"uri": uri})
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other exceptions"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500, content={"error": "Internal server error", "detail": str(exc)}
    )


if __name__ == "__main__":
    port = int(os.getenv("PROXY_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info", access_log=True)
