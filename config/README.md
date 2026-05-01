# Configuration

This directory contains the configuration files and configuration documentation for the Jenkins MCP server.

## Two Config Layers Used by the Server

| File | Use |
|------|-----|
| `mcp-config.yml` | Primary server configuration passed with `--config` |
| `diagnostic-parameters.yml` | Optional project-local diagnostic override for `diagnose_build_failure` |

The diagnostic layer always exists. If `config/diagnostic-parameters.yml` is absent, the code falls back to the bundled defaults in `jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml`.

## Reference Files in This Directory

| File | Use |
|------|-----|
| `mcp-config.example.yml` | Canonical template for the primary server config |
| `README-diagnostic-config.md` | How the diagnostic config layer is resolved |
| `diagnostic-parameters-guide.md` | Practical guide to tuning `diagnose_build_failure` |
| `diagnostic-parameters-quick-reference.md` | Short reference for common diagnostic overrides |
| `config.example.yaml` / `config.example.json` | Older generic examples retained for reference; prefer `mcp-config.example.yml` |

## Recommended Setup Flow

1. Copy the primary server config template:

```bash
cp config/mcp-config.example.yml config/mcp-config.yml
```

2. Set at least one Jenkins instance under `jenkins_instances`.

3. Set `settings.fallback_instance` to one of those configured instance ids.

4. If you want semantic search, set:

```yaml
vector:
  disable_vector_search: false
  host: "http://localhost:6333"
```

5. If you want to tune `diagnose_build_failure`, add `config/diagnostic-parameters.yml`.

6. Start the server with:

```bash
python -m jenkins_mcp_enterprise.server --config config/mcp-config.yml
```

The runtime server configuration used by this repository is the multi-instance YAML file in `mcp-config.example.yml`. Copy that file and edit it directly rather than generating a new config through the legacy CLI helper.

## Minimal Working Example

```yaml
jenkins_instances:
  production:
    url: "https://jenkins.example.com"
    username: "your.username@example.com"
    token: "your-api-token"
    display_name: "Production Jenkins"

settings:
  fallback_instance: "production"

vector:
  disable_vector_search: true
```

## Main Config Sections

### `jenkins_instances`

Per-instance Jenkins connection settings. In multi-Jenkins mode, tools resolve exactly one instance per call from the `jenkins_url` parameter.

Common fields:
- `url`
- `username`
- `token`
- `display_name`
- `timeout`
- `verify_ssl`
- `max_log_size`
- `default_timeout`

### `settings`

Global behavior:
- `fallback_instance`
- `enable_health_checks`
- `health_check_interval`
- `auto_discover_instances`
- `log_instance_switching`
- `log_health_checks`

### `vector`

Controls semantic search. If `disable_vector_search: true`, the `semantic_search` tool is not registered.

### `cache`

Controls cached log storage and cleanup behavior.

### `server`

Controls MCP transport and logging.

### `cleanup`

Controls periodic removal of old cache data.

## Diagnostic Config Layer

`diagnose_build_failure` reads its settings from the first diagnostic source that exists:

1. a path passed through `--diagnostic-config`
2. `JENKINS_MCP_DIAGNOSTIC_CONFIG`
3. `config/diagnostic-parameters.yml`
4. bundled defaults in `jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml`

The project-local override path is:

```text
config/diagnostic-parameters.yml
```

See:
- [diagnostic-parameters-guide.md](diagnostic-parameters-guide.md)
- [diagnostic-parameters-quick-reference.md](diagnostic-parameters-quick-reference.md)

## Useful CLI Commands

```bash
python -m jenkins_mcp_enterprise.cli create-example --output config/mcp-config.yml
python -m jenkins_mcp_enterprise.cli validate --config config/mcp-config.yml
python -m jenkins_mcp_enterprise.cli show --config config/mcp-config.yml
```

## Environment Variables

Only a small set of system-level environment variables are supported:
- `LOG_LEVEL`
- `DISABLE_VECTOR_SEARCH`
- `QDRANT_HOST`
- `CACHE_DIR`
- `JENKINS_MCP_DIAGNOSTIC_CONFIG`

Jenkins credentials should live in `mcp-config.yml`, not in environment variables.
