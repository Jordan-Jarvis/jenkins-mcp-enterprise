#!/bin/bash

# Jenkins MCP Enterprise Docker Startup Script
# This script starts the complete Jenkins MCP stack with Qdrant and proxy

set -e

echo "🚀 Starting Jenkins MCP Enterprise Stack..."

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
if [ ! -f "mcpconfig.docker.json" ]; then
    echo "❌ Error: mcpconfig.docker.json not found!"
    echo "Please create the MCP proxy configuration file."
    exit 1
fi

echo "✅ Configuration files found"
echo "📦 Building and starting containers..."

# Start the stack (rebuild to pick up changes)
docker-compose -f docker-compose.yml build --no-cache
docker-compose -f docker-compose.yml up -d

echo "⏳ Waiting for services to be healthy..."

# Wait for Qdrant to be ready
echo "   Waiting for Qdrant..."
timeout 60 bash -c 'until curl -s http://localhost:6333/healthz > /dev/null; do sleep 2; done' || {
    echo "❌ Qdrant failed to start"
    docker-compose -f docker-compose.yml logs qdrant
    exit 1
}

echo "✅ Services started successfully!"
echo ""
echo "🌐 Access points:"
echo "   - Qdrant Dashboard: http://localhost:6333/dashboard"
echo "   - MCP Proxy: http://localhost:3006"
echo ""
echo "📊 Service Status:"
docker-compose -f docker-compose.yml ps

echo ""
echo "📋 To stop the stack:"
echo "   docker-compose -f docker-compose.yml down"
echo ""
echo "📋 To view logs:"
echo "   docker-compose -f docker-compose.yml logs -f [service-name]"