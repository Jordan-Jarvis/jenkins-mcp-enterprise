# Jenkins MCP Enterprise Server - Docker Deployment

This repo includes a Docker Compose stack for running the Jenkins MCP Enterprise Server in **streamable HTTP** mode, plus an optional **Qdrant** container for vector search.

## Quick Start

### 1. Configure your Jenkins instances

```bash
cp config/mcp-config.example.yml config/mcp-config.yml
# edit config/mcp-config.yml with your Jenkins URLs + credentials
```

### 2. Start the stack

```bash
./start-jenkins_mcp_enterprise.sh
```

Or run Docker Compose directly:

```bash
docker compose up -d --build
```

### 3. Access services

- **MCP Server health**: `http://localhost:8000/health`
- **MCP Streamable HTTP endpoint**: `http://localhost:8000/mcp`
- **Qdrant Dashboard**: `http://localhost:6333/dashboard`

## What’s in the stack

- **`docker-compose.yml`**: Compose file (server + qdrant)
- **`Dockerfile`**: Jenkins MCP Enterprise server container
- **`start-jenkins_mcp_enterprise.sh`**: convenience script

## Common commands

```bash
# Start / rebuild
docker compose up -d --build

# Status
docker compose ps

# Logs
docker compose logs -f
docker compose logs -f jenkins_mcp_enterprise-server
docker compose logs -f qdrant

# Stop / remove
docker compose down
```

## Troubleshooting

```bash
# Confirm Docker is working
docker info

# Rebuild from scratch
docker compose build --no-cache

# View server logs
docker compose logs -f jenkins_mcp_enterprise-server
```

## Port conflicts

- **Server**: change the `8000:8000` mapping in `docker-compose.yml`
- **Qdrant**: change the `6333:6333` mapping in `docker-compose.yml`