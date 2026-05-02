# Configuration guide

This directory contains the example config files and the diagnostic-configuration docs used by `diagnose_build_failure`.

## Start here

For normal setup, use:

```bash
cp config/mcp-config.example.yml config/mcp-config.yml
```

Then edit `config/mcp-config.yml` with:
- one or more Jenkins instances
- credentials for each instance
- optional server and cache settings

## Important files

- `mcp-config.example.yml`: main example for the server's runtime config
- `diagnostic-parameters-quick-reference.md`: short reference for diagnostic tuning
- `diagnostic-parameters-guide.md`: full diagnostic parameter guide
- `README-diagnostic-config.md`: overview of diagnostic configuration

## Diagnostic config validation

If you are changing the diagnostic tuning files, validate them directly:

```bash
python3 scripts/validate_diagnostic_config.py
```

The runtime server configuration used by this repository is the multi-instance YAML file in `mcp-config.example.yml`. Copy that file and edit it directly rather than generating a new config through the legacy CLI helper.

## Environment variables

Use environment variables only for system-level behavior, not Jenkins credentials.

Supported variables:
- `LOG_LEVEL`
- `DISABLE_VECTOR_SEARCH`
- `QDRANT_HOST`
- `CACHE_DIR`
- `JENKINS_MCP_DIAGNOSTIC_CONFIG`

Jenkins credentials should be kept in `mcp-config.yml`.

## Vector search

Vector search is optional and disabled by default.

To enable it, install the optional dependencies:

```bash
pip install "jenkins_mcp_enterprise[vector]"
```
