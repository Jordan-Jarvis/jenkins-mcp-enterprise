#!/bin/sh
set -eu

CACHE_DIR="${CACHE_DIR:-/tmp/mcp-jenkins}"
MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_PORT="${MCP_PORT:-8000}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_CONFIG="${MCP_CONFIG:-}"

mkdir -p "$CACHE_DIR" /app/cache /app/logs
chown -R mcp:mcp "$CACHE_DIR" /app/cache /app/logs

cmd="exec python3 -m jenkins_mcp_enterprise.server --transport \"$MCP_TRANSPORT\" --port \"$MCP_PORT\" --host \"$MCP_HOST\""
if [ -n "$MCP_CONFIG" ] && [ -f "$MCP_CONFIG" ]; then
    cmd="$cmd --config \"$MCP_CONFIG\""
fi

exec su -s /bin/sh mcp -c "$cmd"
