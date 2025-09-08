# Dockerfile for Jenkins MCP Server
FROM python:3.11-slim

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
COPY requirements.txt ./
COPY pyproject.toml ./
COPY README.md ./
COPY jenkins_mcp_enterprise/ ./jenkins_mcp_enterprise/

# Install the package
RUN pip install -e .

# Copy configuration
COPY config/ ./config/

# Create cache directory
RUN mkdir -p /tmp/mcp-jenkins

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "from jenkins_mcp_enterprise.multi_jenkins_manager import MultiJenkinsManager; m = MultiJenkinsManager(); print('OK')" || exit 1

# Run the MCP server in HTTP mode (no proxy needed)  
EXPOSE 8000
CMD ["python3", "-m", "jenkins_mcp_enterprise.server", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000", "--config", "/app/config/mcp-config.yml"]