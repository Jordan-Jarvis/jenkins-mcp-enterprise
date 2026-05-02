# Diagnostic Configuration

This file explains the diagnostic configuration layer used by `diagnose_build_failure`.

## What It Controls

The diagnostic configuration affects how `diagnose_build_failure`:
- searches for relevant failure content
- falls back to plain pattern matching
- generates recommendations
- limits concurrency, chunk counts, and output size

## How It Relates to the Main Server Config

The repo has two configuration concerns:

- `config/mcp-config.yml`: primary server config for Jenkins instances, cache, vector search, transport, and cleanup
- diagnostic config: settings used by `diagnose_build_failure`

The diagnostic config is not a separate startup requirement in the same way `mcp-config.yml` is. The code always loads a diagnostic config layer, but that layer can come from bundled defaults or from an override file you provide.

## Load Order

The code resolves diagnostic configuration in this order:

1. `JENKINS_MCP_DIAGNOSTIC_CONFIG=/path/to/file.yml`
2. `config/diagnostic-parameters.yml`
3. bundled defaults in `jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml`

When you pass:

```bash
--diagnostic-config /path/to/file.yml
```

the server sets `JENKINS_MCP_DIAGNOSTIC_CONFIG` before the loader runs, so it effectively feeds the first entry in that list.

## Project-Local Override Path

If you want a repo-local override, use:

```text
config/diagnostic-parameters.yml
```

If that file is absent, the server still works and uses bundled defaults.

## Common Ways To Use It

### Use bundled defaults only

```bash
python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml
```

### Use a project-local override

Create `config/diagnostic-parameters.yml`, then start the server normally:

```bash
python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml
```

### Use an explicit file path

```bash
python3 -m jenkins_mcp_enterprise.server \
  --config config/mcp-config.yml \
  --diagnostic-config /path/to/custom-diagnostic-parameters.yml
```

### Use an environment variable

```bash
export JENKINS_MCP_DIAGNOSTIC_CONFIG="/path/to/custom-diagnostic-parameters.yml"
python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml
```

## Recommended Approach

For most setups:

1. keep `config/mcp-config.yml` as the primary runtime config
2. rely on bundled diagnostic defaults first
3. add `config/diagnostic-parameters.yml` only when you need to tune diagnosis behavior

## Most Important Sections

- `semantic_search`: relevance thresholds and highlight limits
- `failure_patterns`: fallback text matching
- `recommendations`: condition-to-message mappings
- `build_processing`: concurrency and chunk limits
- `context`: token and truncation limits
- `summary`: summary formatting and failure counts

For details, see:
- [diagnostic-parameters-guide.md](diagnostic-parameters-guide.md)
- [diagnostic-parameters-quick-reference.md](diagnostic-parameters-quick-reference.md)

## Minimal Example

```yaml
semantic_search:
  min_diagnostic_score: 0.65
  max_total_highlights: 4

recommendations:
  max_recommendations: 5

build_processing:
  parallel:
    max_workers: 4
```

## Validation

```bash
python3 scripts/validate_diagnostic_config.py
```

## Reload in Python

```python
from jenkins_mcp_enterprise.diagnostic_config import reload_diagnostic_config

reload_diagnostic_config()
```
