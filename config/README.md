# Configuration Files

This directory contains configuration files and comprehensive documentation for the Jenkins MCP Server.

## 📚 Diagnostic Parameters Documentation

**NEW**: The Jenkins MCP server now includes a comprehensive diagnostic parameters system for the `diagnose_build_failure` tool. All diagnostic behavior is configurable through YAML files.

### Diagnostic Documentation

| File | Purpose | Target Audience |
|------|---------|----------------|
| **[diagnostic-parameters-guide.md](diagnostic-parameters-guide.md)** | Complete parameter guide with examples | Users needing detailed configuration |
| **[diagnostic-parameters-quick-reference.md](diagnostic-parameters-quick-reference.md)** | Condensed reference card | Users needing quick answers |
| **[README-diagnostic-config.md](README-diagnostic-config.md)** | Overview and getting started | New users |

### Validation Tool

```bash
# Validate diagnostic configuration
python3 scripts/validate_diagnostic_config.py
```

## Server Configuration Files

## Example Files

- `config.example.json` - Example configuration in JSON format
- `config.example.yaml` - Example configuration in YAML format

## Configuration Options

### Jenkins Configuration

- `url`: Jenkins server URL (required)
- `username`: Jenkins username (required)
- `token`: Jenkins API token (optional, but recommended)
- `timeout`: Request timeout in seconds (default: 30)
- `verify_ssl`: Whether to verify SSL certificates (default: true)

### Cache Configuration

- `base_dir`: Directory for caching build logs (default: /tmp/mcp-jenkins)
- `max_size_mb`: Maximum cache size in MB (default: 1000)
- `retention_days`: How long to keep cached files in days (default: 7)
- `enable_compression`: Whether to compress cached files (default: true)

### Vector Store Configuration

- `host`: Qdrant server URL (default: http://localhost:6333)
- `api_key`: API key for vector store (optional for local Qdrant)
- `collection_name`: Name of the vector collection (default: jenkins-logs)
- `dimension`: Vector dimension (default: 384)
- `metric`: Distance metric for similarity search (default: cosine)
- `embedding_model`: Embedding model name for semantic search (default: all-MiniLM-L6-v2)
- `chunk_size`: Text chunk size for vectorization (default: 500)
- `chunk_overlap`: Overlap between chunks (default: 50)
- `top_k_default`: Default number of results to return (default: 5)

### Server Configuration

- `name`: Server name (default: Jenkins MCP Server)
- `version`: Server version (default: 1.0.0)
- `transport`: MCP transport protocol - stdio, streamable-http, or sse (default: stdio)
- `log_level`: Logging level (default: INFO)
- `log_file`: Optional log file path (default: null - log to stderr)

### Cleanup Configuration

- `schedule_interval_hours`: How often to run cleanup in hours (default: 24)
- `retention_days`: How long to keep data before cleanup (default: 7)
- `max_concurrent_cleanups`: Maximum concurrent cleanup operations (default: 5)

## Environment Variables

Limited environment variables are supported for system-level configuration:

### Optional System Variables
- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)
- `DISABLE_VECTOR_SEARCH` - Set to "true" to disable vector search features
- `QDRANT_HOST` - Qdrant server URL for vector search
- `CACHE_DIR` - Base directory for caching build logs
- `JENKINS_MCP_DIAGNOSTIC_CONFIG` - Path to custom diagnostic parameters YAML

**Note on semantic search dependencies**: Vector/semantic search is **disabled by default** and the default install avoids large ML dependencies.
To enable vector search, install optional dependencies with:
`pip install jenkins_mcp_enterprise[vector]`

**Note**: Jenkins credentials must be configured in `mcp-config.yml`, not environment variables.

## Usage

### Using Configuration Files

```bash
# Validate configuration
python -m jenkins_mcp_enterprise.cli validate --config config/mcp-config.yml

# Show configuration
python -m jenkins_mcp_enterprise.cli show --config config/mcp-config.yml

# Test connections
python -m jenkins_mcp_enterprise.cli test --config config/mcp-config.yml
```

### Creating Your Own Configuration

```bash
# Create a new example configuration file
python -m jenkins_mcp_enterprise.cli create-example --output config/mcp-config.yml

# Edit the file with your settings
# Then validate it
python -m jenkins_mcp_enterprise.cli validate --config config/mcp-config.yml
```

## Configuration Priority

Configuration is loaded in the following priority order:
1. YAML configuration file (required for Jenkins credentials)
2. Environment variables (for system-level settings only)
3. Default values

Jenkins credentials must always be provided in the YAML configuration file.