#!/bin/bash

# Jenkins MCP Enterprise Docker Startup Script
# This script starts the Jenkins MCP stack with Qdrant (optional) using Docker Compose.

set -euo pipefail

echo "🚀 Starting Jenkins MCP Enterprise Stack..."

# Detect Docker Compose command (plugin preferred)
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker-compose)
else
    echo "❌ Error: Docker Compose is not installed."
    echo "Install Docker Desktop (recommended) or the Docker Compose plugin."
    exit 1
fi

COMPOSE_FILE="docker-compose.yml"

# Check if config file exists
if [ ! -f "config/mcp-config.yml" ]; then
    echo "❌ Error: config/mcp-config.yml not found!"
    echo ""
    echo "📋 Setup Instructions:"
    echo "1. Copy the example configuration:"
    echo "   cp config/mcp-config.example.yml config/mcp-config.yml"
    echo ""
    echo "2. Edit config/mcp-config.yml and configure your Jenkins instances:"
    echo "   - Add your Jenkins URLs"
    echo "   - Add your Jenkins API credentials"
    echo "   - Configure any other settings as needed"
    echo ""
    echo "3. Run this script again"
    echo ""
    echo "💡 The mcp-config.yml file contains your actual Jenkins credentials and should not be committed to git."
    exit 1
fi

# Validate the config file has content
if [ ! -s "config/mcp-config.yml" ]; then
    echo "❌ Error: config/mcp-config.yml is empty!"
    echo "Please configure your Jenkins instances in config/mcp-config.yml"
    exit 1
fi

# Check if proxy config exists  
echo "✅ Configuration file found"
echo "📦 Building and starting containers..."

# Start the stack (build to pick up changes)
"${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" up -d --build

echo "⏳ Waiting for services to be healthy..."

# Wait for Qdrant to be ready
if "${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" config --services | grep -qx "qdrant"; then
    echo "   Waiting for Qdrant..."
    timeout 60 bash -c 'until curl -sf http://localhost:6333/health > /dev/null; do sleep 2; done' || {
        echo "❌ Qdrant failed to start"
        "${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" logs qdrant
        exit 1
    }
fi

# Wait for server health endpoint (provided by FastMCP custom route)
echo "   Waiting for MCP server..."
timeout 60 bash -c 'until curl -sf http://localhost:8000/health > /dev/null; do sleep 2; done' || {
    echo "❌ MCP server failed to start"
    "${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" logs jenkins_mcp_enterprise-server
    exit 1
}

echo "✅ Services started successfully!"
echo ""
echo "🌐 Access points:"
echo "   - MCP Server (streamable HTTP): http://localhost:8000/mcp"
echo "   - MCP Server health: http://localhost:8000/health"
echo "   - Qdrant Dashboard: http://localhost:6333/dashboard"
echo "📊 Service Status:"
"${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" ps

echo ""
echo "📋 To stop the stack:"
echo "   ${DOCKER_COMPOSE[*]} -f $COMPOSE_FILE down"
echo ""
echo "📋 To view logs:"
echo "   ${DOCKER_COMPOSE[*]} -f $COMPOSE_FILE logs -f [service-name]"