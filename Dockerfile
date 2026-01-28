# Dockerfile for Jenkins MCP Server
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install ripgrep using package manager (handles all architectures)
RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies

COPY ./ ./

# Install the package
RUN pip3 install -r requirements.txt

# Optional: install vector/semantic search dependencies (large) behind a build-arg.
# This keeps the default image small and fast to build.
#
# Usage:
#   docker build -t jenkins_mcp_enterprise-server .
#   docker build -t jenkins_mcp_enterprise-server:vector --build-arg INSTALL_VECTOR_DEPS=true .
#
# When enabled, we preinstall CPU-only torch to avoid pulling nvidia CUDA wheels.
ARG INSTALL_VECTOR_DEPS=false
RUN if [ "$INSTALL_VECTOR_DEPS" = "true" ]; then \
      pip3 install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch && \
      pip3 install -e ".[vector]" ; \
    else \
      pip3 install -e . ; \
    fi

# Sanity check: ensure the MCP SDK is importable (prevents runtime failures like "No module named 'mcp'")
RUN python3 -c "import mcp; from mcp.server.fastmcp import FastMCP; print('✅ MCP SDK import OK')"
# Copy configuration
COPY config/ ./config/

# Create cache directory
RUN mkdir -p /tmp/mcp-jenkins

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "from jenkins_mcp_enterprise.multi_jenkins_manager import MultiJenkinsManager; m = MultiJenkinsManager(); print('OK')" || exit 1

# Run the MCP server in HTTP mode (no proxy needed)  
EXPOSE 8000
CMD ["python3", "-m","jenkins_mcp_enterprise.server", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000", "--config", "/app/config/mcp-config.yml"]