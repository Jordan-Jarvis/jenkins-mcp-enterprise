# Jenkins MCP Server Docker Image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies with better error handling and non-interactive mode
RUN export DEBIAN_FRONTEND=noninteractive && \
    apt-get update -y && \
    apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* \
    && rm -rf /var/tmp/*

# Copy requirements and install Python dependencies
COPY requirements.txt pyproject.toml ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy source code
COPY jenkins_mcp_enterprise/ ./jenkins_mcp_enterprise/
COPY tests/ ./tests/
COPY scripts/ ./scripts/
COPY README.md CLAUDE.md LICENSE ./

# Install the package in development mode
RUN pip3 install -e .

# Create directories for cache and logs
RUN mkdir -p /app/cache /app/logs

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash mcp
RUN chown -R mcp:mcp /app
USER mcp

# Default transport configuration
ENV MCP_TRANSPORT="stdio"
ENV MCP_PORT="8000"
ENV MCP_HOST="0.0.0.0"

# Expose port for HTTP transports
EXPOSE 8000

# Health check - different for different transports
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD if [ "$MCP_TRANSPORT" = "stdio" ]; then \
            python3 -c "import jenkins_mcp_enterprise.server; print('✅ MCP Server healthy')" || exit 1; \
        else \
            curl -f http://localhost:${MCP_PORT}/health || exit 1; \
        fi

# Use shell form to allow environment variable expansion
CMD python3 -m jenkins_mcp_enterprise.server --transport ${MCP_TRANSPORT} --port ${MCP_PORT} --host ${MCP_HOST}