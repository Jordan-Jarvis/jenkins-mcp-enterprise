# Diagnostic Parameters Quick Reference

Short reference for the settings most likely to matter when tuning `diagnose_build_failure`.

## Config Locations

The diagnostic config is loaded from the first path that exists:

1. `JENKINS_MCP_DIAGNOSTIC_CONFIG=/path/to/file.yml`
2. `config/diagnostic-parameters.yml`
3. `jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml`

## Most Useful Knobs

### Improve relevance

```yaml
semantic_search:
  min_diagnostic_score: 0.7
  max_total_highlights: 4
```

### Return more detail

```yaml
context:
  max_tokens_total: 15000
semantic_search:
  max_total_highlights: 8
recommendations:
  max_recommendations: 8
```

### Reduce runtime cost

```yaml
build_processing:
  parallel:
    max_workers: 2
    max_batch_size: 2
  chunks:
    max_total_chunks_analyzed: 400
context:
  max_tokens_total: 5000
```

### Improve fallback pattern matching

```yaml
failure_patterns:
  stack_trace_patterns:
    - "exception"
    - "caused by:"
    - "failed"
    - "timeout"
  max_fallback_patterns: 4
```

### Add organization-specific recommendations

```yaml
recommendations:
  patterns:
    auth_failure:
      conditions:
        - "authentication failed"
        - "token expired"
      message: "Authentication failure detected. Check token validity, secret rotation, and credential injection."
```

## Common Presets

### High detail

```yaml
build_processing:
  parallel: {max_batch_size: 8, max_workers: 6}
context: {max_tokens_total: 15000, truncation_threshold: 12000}
semantic_search: {max_total_highlights: 8, min_diagnostic_score: 0.5}
recommendations: {max_recommendations: 8}
```

### Constrained environment

```yaml
build_processing:
  parallel: {max_batch_size: 2, max_workers: 2}
  chunks: {max_total_chunks_analyzed: 300}
context: {max_tokens_total: 4000, truncation_threshold: 3000}
```

### Stricter matching

```yaml
semantic_search:
  min_diagnostic_score: 0.8
  max_results_per_query: 1
  max_total_highlights: 3
```

## Validation

```bash
python3 -c "import yaml; yaml.safe_load(open('config/diagnostic-parameters.yml'))"
python3 scripts/validate_diagnostic_config.py
```

## Reload in Python

```python
from jenkins_mcp_enterprise.diagnostic_config import reload_diagnostic_config

reload_diagnostic_config()
```

For more detail, see [diagnostic-parameters-guide.md](diagnostic-parameters-guide.md).
