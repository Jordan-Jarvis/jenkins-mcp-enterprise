# Docker deployment

Use this path when you want to run the Jenkins MCP server in `streamable-http` mode with Docker Compose.

What this stack includes:
- `jenkins_mcp_enterprise-server` on `http://localhost:8000`
- `qdrant` on `http://localhost:6333`

Before you start:
- Docker must be running
- create `config/mcp-config.yml` from the checked-in example

## Quick start

```bash
cp config/mcp-config.example.yml config/mcp-config.yml
# edit config/mcp-config.yml with your Jenkins URLs and credentials

./start-jenkins_mcp_enterprise.sh
```

The helper script:
- validates that `config/mcp-config.yml` exists
- uses `docker compose` when available
- builds and starts the stack
- waits for the server health endpoint before returning

If you prefer raw Compose commands:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f jenkins_mcp_enterprise-server
docker compose down
```

## Endpoints

- MCP server health: `http://localhost:8000/health`
- MCP streamable HTTP endpoint: `http://localhost:8000/mcp`
- Qdrant dashboard: `http://localhost:6333/dashboard`

## Vector search

Vector search is disabled by default to keep builds smaller and faster.

To enable it:

```bash
INSTALL_VECTOR_DEPS=true DISABLE_VECTOR_SEARCH=false docker compose up -d --build
```

## Troubleshooting

If startup fails:

```bash
docker info
docker compose ps
docker compose logs -f jenkins_mcp_enterprise-server
docker compose logs -f qdrant
```

Port conflicts:
- change `8000:8000` in `docker-compose.yml` for the MCP server
- change `6333:6333` in `docker-compose.yml` for Qdrant
