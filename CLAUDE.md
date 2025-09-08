# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a production-ready MCP (Model Context Protocol) server for Jenkins integration. The codebase uses modern Python patterns with proper dependency injection, error handling, and testing.

## Development Commands

### ⚠️ IMPORTANT: Development vs Production

**Development Mode:** Use `python3` commands for local development and testing
**Production Mode:** Use Docker deployment (recommended) for production environments

### Development Setup (Local Python)
```bash
# Start development environment with Qdrant
./scripts/start_dev_environment.sh

# Install dependencies (use python3)
python3 -m pip install -e .

# Or install with user flag if permissions issues
python3 -m pip install --user -e .

# Create configuration file from template
cp config/mcp-config.example.yml config/mcp-config.yml
# Edit config/mcp-config.yml with your Jenkins URLs and credentials

# Run MCP server locally with configuration
python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml
```

### ⚙️ Configuration File Usage

The `--config` option is **required** for most operations to specify your Jenkins instances and settings:

```bash
# All development commands should use --config
npx @modelcontextprotocol/inspector --cli --method tools/list --server jenkins-mcp --config inspector-config.json 
```

**Without `--config`:** The server will have no Jenkins instances configured and most tools will fail.

### Production Setup (Docker - Recommended)
```bash
# 1. Create configuration file from template
cp config/mcp-config.example.yml config/mcp-config.yml
# Edit config/mcp-config.yml with your Jenkins URLs and credentials

# 2. Copy environment template and configure
cp .env.example .env
# Edit .env if needed (optional for file-based config)

# 3. Start production stack
docker-compose up -d

# 4. Check deployment
docker-compose ps
docker-compose logs jenkins_mcp_enterprise-server

# 5. Stop stack
docker-compose down
```

### Testing
```bash
# Run unit tests (legacy - needs refactoring)
python3 -m pytest tests/

# Run MCP integration tests (preferred)
python3 -m pytest tests/mcp_integration/ -v

# Run performance tests
python3 scripts/run_integration_tests.py --performance

# Run with coverage
python3 scripts/run_integration_tests.py --coverage

# Run specific massive scale tests
python3 tests/test_massive_scale_integration.py
```

### MCP Inspector Usage for Testing

#### Development Mode (Local Python)
```bash
# Install MCP inspector for manual testing
npm install -g @modelcontextprotocol/inspector


# Use --cli flag for command-line interface
npx @modelcontextprotocol/inspector --cli --method tools/list --server jenkins-mcp --config inspector-config.json 
npx @modelcontextprotocol/inspector --cli --method tools/call --tool-name diagnose_build_failure --tool-arg job_name=QA_JOBS/master build_number=1225 custom_error_patterns='''["error"]''' --server jenkins-mcp --config inspector-config.json 
For more usage and info refer to: https://modelcontextprotocol.io/llms-full.txt


#### Production Mode (Docker - Required for Production Testing)
```bash
# 1. Ensure Docker stack is running


#### Common Docker MCP Patterns
```bash
# Test sub-build discovery
docker run --rm --network jenkins_mcp_enterprise_mcp-net jenkins_mcp_enterprise-jenkins_mcp_enterprise-server:latest python3 -c "
from jenkins_mcp_enterprise.jenkins.connection_manager import JenkinsConnectionManager
from jenkins_mcp_enterprise.jenkins.subbuild_discoverer import SubBuildDiscoverer
from jenkins_mcp_enterprise.config import JenkinsConfig

config = JenkinsConfig(url='https://your-jenkins.com', username='user', token='token', timeout=30, verify_ssl=False)
connection = JenkinsConnectionManager(config)
discoverer = SubBuildDiscoverer(connection)
subbuilds = discoverer.discover_subbuilds('job/name', 123)
print(f'Found {len(subbuilds)} sub-builds')
"

# Test console log analysis
docker run --rm --network jenkins_mcp_enterprise_mcp-net jenkins_mcp_enterprise-jenkins_mcp_enterprise-server:latest python3 -c "
# Get console log for analysis
response = connection.session.get(f'{config.url}/job/QA_JOBS/job/develop/2089/consoleText')
lines = response.text.split('\n')
print(f'Console log: {len(lines)} lines')
"
```

### Development Environment
```bash
# Start Qdrant vector database
./scripts/start_dev_environment.sh

# Check Qdrant health
curl http://localhost:6333/health

# Access Qdrant dashboard
open http://localhost:6333/dashboard

# Stop environment
docker-compose down
```

### Configuration Validation
```bash
# Validate configuration (use python3)
python3 -m jenkins_mcp_enterprise.cli validate --config config/mcp-config.yml

# Validate with custom config file
python3 -m jenkins_mcp_enterprise.cli validate --config config/my-config.yml
```

### Diagnostic Configuration

The `diagnose_build_failure` tool is fully configurable through YAML parameters with **advanced regex pattern support**. See comprehensive documentation:

- **[Quick Reference](config/diagnostic-parameters-quick-reference.md)** - Common parameters and quick fixes
- **[Complete Guide](config/diagnostic-parameters-guide.md)** - Detailed documentation with examples
- **[Regex Pattern Examples](config/diagnostic-parameters-guide.md#advanced-regex-pattern-configuration)** - Advanced data extraction patterns

```bash
# Validate current configuration
python3 scripts/validate_diagnostic_config.py

# Run with default bundled diagnostic parameters
python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml

# Run with custom diagnostic parameters (environment variable)
export JENKINS_MCP_DIAGNOSTIC_CONFIG="/path/to/custom-diagnostic-parameters.yml"
python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml

# Create user override (automatically detected)
cp jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml config/diagnostic-parameters.yml
# Edit config/diagnostic-parameters.yml as needed - see documentation for all options

# Quick performance tuning examples:
# High performance: max_workers=8, max_tokens_total=20000
# Resource constrained: max_workers=2, max_tokens_total=3000
# Detailed analysis: max_total_highlights=10, max_recommendations=10
```

### Key Environment Variables
```bash
# Jenkins Configuration: Use config/mcp-config.yml instead of environment variables
# Create config/mcp-config.yml with:
# jenkins_instances:
#   my-jenkins:
#     url: "https://your-jenkins-instance.com"
#     username: "your.username@domain.com"
#     token: "your-api-token"

# Optional System Configuration
DISABLE_VECTOR_SEARCH="true"  # Disable for testing without Qdrant
QDRANT_HOST="http://localhost:6333"
CACHE_DIR="/tmp/mcp-jenkins"
LOG_LEVEL="INFO"  # DEBUG, INFO, WARNING, ERROR

# Diagnostic Configuration (Optional)
JENKINS_MCP_DIAGNOSTIC_CONFIG="/path/to/custom-diagnostic-parameters.yml"  # Override bundled diagnostic config
```

### Dependency Issues & Solutions
```bash
# Qdrant client version that works
qdrant-client>=1.14.3

# If numpy conflicts occur (common with latest qdrant-client)
python3 -m pip install --user qdrant-client

# Test basic imports work
python3 -c "
import os
os.environ['DISABLE_VECTOR_SEARCH'] = 'true'
from jenkins_mcp_enterprise.vector_manager import QdrantVectorManager
print('✅ QdrantVectorManager imported successfully')
"
```

## Architecture

This MCP server uses a modular architecture with:

- **Connection Management**: Jenkins authentication and HTTP sessions
- **Build Management**: Pipeline triggering and monitoring
- **Log Processing**: Streaming retrieval and analysis of large logs
- **Vector Search**: Local Qdrant-based semantic search
- **Diagnostics**: AI-powered failure analysis

## Key Features

- Handle massive pipeline logs (10+ GB) via streaming
- Analyze deeply nested pipeline hierarchies
- Local vector search without external dependencies
- Type-safe tool implementations with proper error handling
- Comprehensive MCP integration testing

## Docker-Based MCP Diagnosis Workflow

### ⚠️ CRITICAL: Use Docker for Production MCP Operations

**Always use Docker containers for production MCP server interactions. Never use `python3` commands directly for production diagnosis.**

### Docker MCP Setup Checklist

1. **Environment Configuration**
   ```bash
   # Ensure .env file has correct settings
   QDRANT_HOST=http://qdrant:6333  # NOT localhost for Docker
   JENKINS_URL=https://your-jenkins-instance.com
   JENKINS_USER=your.user@domain.com
   JENKINS_TOKEN=your-api-token
   ```

2. **Docker Network Requirements**
   ```bash
   # Check network exists
   docker network ls | grep jenkins_mcp_enterprise_mcp-net
   
   # Qdrant must be accessible from MCP container
   docker run --rm --network jenkins_mcp_enterprise_mcp-net alpine ping -c 1 qdrant
   ```

3. **Container Health Verification**
   ```bash
   # Verify Qdrant connectivity
   docker run --rm --env-file .env --network jenkins_mcp_enterprise_mcp-net jenkins_mcp_enterprise-jenkins_mcp_enterprise-server:latest python3 -c "
   from jenkins_mcp_enterprise.vector_manager import QdrantVectorManager
   print('✅ Qdrant connection successful')
   "
   
   # Verify Jenkins connectivity
   docker run --rm --env-file .env --network jenkins_mcp_enterprise_mcp-net jenkins_mcp_enterprise-jenkins_mcp_enterprise-server:latest python3 -c "
   from jenkins_mcp_enterprise.jenkins.connection_manager import JenkinsConnectionManager
   from jenkins_mcp_enterprise.config import JenkinsConfig
   config = JenkinsConfig(url='https://jenkins-url.com', username='user', token='token', timeout=30, verify_ssl=False)
   connection = JenkinsConnectionManager(config)
   print('✅ Jenkins connection successful')
   "
   ```

### Jenkins Build Diagnosis Pattern

```bash
# Step 1: Test build accessibility
docker run --rm --env-file .env --network jenkins_mcp_enterprise_mcp-net jenkins_mcp_enterprise-jenkins_mcp_enterprise-server:latest python3 -c "
from jenkins_mcp_enterprise.jenkins.connection_manager import JenkinsConnectionManager
from jenkins_mcp_enterprise.config import JenkinsConfig

config = JenkinsConfig(url='$JENKINS_URL', username='$JENKINS_USER', token='$JENKINS_TOKEN', timeout=30, verify_ssl=False)
connection = JenkinsConnectionManager(config)

build_info = connection.client.get_build_info('job/name', build_number, depth=0)
print(f'Status: {build_info.get(\"result\")}')
print(f'URL: {build_info.get(\"url\")}')
"

# Step 2: Discover sub-builds
docker run --rm --network jenkins_mcp_enterprise_mcp-net jenkins_mcp_enterprise-jenkins_mcp_enterprise-server:latest python3 -c "
from jenkins_mcp_enterprise.jenkins.subbuild_discoverer import SubBuildDiscoverer
# ... discoverer code
subbuilds = discoverer.discover_subbuilds('job/name', build_number, max_depth=3)
print(f'Found {len(subbuilds)} sub-builds')
"

# Step 3: Analyze console logs
docker run --rm --env-file .env --network jenkins_mcp_enterprise_mcp-net jenkins_mcp_enterprise-jenkins_mcp_enterprise-server:latest python3 -c "
# Get console log and analyze failure patterns
response = connection.session.get(f'{config.url}/job/name/build_number/consoleText')
lines = response.text.split('\n')
error_patterns = ['FAILURE', 'ERROR', 'Exception', 'Traceback']
for pattern in error_patterns:
    matches = [i for i, line in enumerate(lines) if pattern in line]
    if matches: print(f'{pattern}: {len(matches)} occurrences')
"

# Step 4: Use MCP Inspector for structured diagnosis
npx @modelcontextprotocol/inspector --cli --method tools/call --tool-name diagnose_build_failure \
  docker run -i --rm --env-file .env --network jenkins_mcp_enterprise_mcp-net jenkins_mcp_enterprise-jenkins_mcp_enterprise-server:latest python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml << EOF
{"job_name": "job/name", "build_number": 123}
EOF
```

### Docker Troubleshooting

```bash
# Container won't start - check dependencies
docker-compose logs jenkins_mcp_enterprise-server

# Network connectivity issues
docker exec jenkins_mcp_enterprise-server ping qdrant
docker exec jenkins_mcp_enterprise-server curl http://qdrant:6333/health

# Qdrant connection failures
# ❌ Wrong: QDRANT_HOST=http://localhost:6333
# ✅ Correct: QDRANT_HOST=http://qdrant:6333

# MCP Inspector connection issues
# Ensure container runs interactively: docker run -i --rm
# Use correct network: --network jenkins_mcp_enterprise_mcp-net
# Pass environment: --env-file .env
```

### Sub-Build Discovery Implementation Notes

The sub-build discovery system uses a Tree API approach with the pattern:
```
/api/json?tree=actions[nodes[actions[description]]]
```

This reliably discovers hierarchical Jenkins pipelines by parsing build action descriptions in the format `"job » path #build"` and converts them to proper job paths for recursive analysis.

Key implementation detail: The working sub-build discovery was migrated from console log parsing to the more reliable Tree API method, significantly improving accuracy and performance.