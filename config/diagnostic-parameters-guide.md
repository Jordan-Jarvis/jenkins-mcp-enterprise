# Diagnostic Parameters Guide

This file explains the configuration that controls `diagnose_build_failure`.

The goal of this guide is not to document every internal default. It is to show the sections that matter most when you want to change diagnosis quality, latency, or output size.

## Where Configuration Is Loaded From

The diagnostic config is resolved in this order:

1. `JENKINS_MCP_DIAGNOSTIC_CONFIG=/path/to/file.yml`
2. `config/diagnostic-parameters.yml`
3. `jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml`

If you only need a small override, create `config/diagnostic-parameters.yml` and set the fields you want to change.

## What This Affects

These settings are used by `diagnose_build_failure` when it:
- inspects the root build and any discovered sub-builds
- extracts or searches log content
- generates highlights, summaries, and recommendations

## Sections That Matter Most

### `semantic_search`

Controls AI-style similarity search over indexed log chunks.

Use this when you want better failure highlighting than plain pattern matching.

Important fields:
- `search_queries`: natural-language queries used to find likely failure chunks
- `min_diagnostic_score`: minimum relevance score to keep a match
- `max_results_per_query`: cap per query
- `max_total_highlights`: overall cap for returned highlights
- `max_content_preview`: preview length included in the result

Notes:
- If vector search is disabled, semantic search is skipped.
- In that case the tool falls back to pattern-based extraction.

Example:

```yaml
semantic_search:
  search_queries:
    - "spring dependency conflict"
    - "connection timeout database"
    - "docker image pull failed"
  min_diagnostic_score: 0.7
  max_results_per_query: 1
  max_total_highlights: 4
```

### `failure_patterns`

Fallback text matching used when semantic search is disabled or when a simpler signal is enough.

Important fields:
- `stack_trace_patterns`
- `max_fallback_patterns`
- `max_pattern_preview`

Example:

```yaml
failure_patterns:
  stack_trace_patterns:
    - "exception"
    - "caused by:"
    - "compilation failed"
    - "permission denied"
  max_fallback_patterns: 4
  max_pattern_preview: 250
```

### `recommendations`

Maps detected content to plain-text guidance.

Important fields:
- `patterns`: condition-to-message mappings
- `priority_jobs`: which job names to emphasize as likely root causes
- `investigation_guidance`: standard follow-up instructions
- `max_recommendations`: cap on total output

Example:

```yaml
recommendations:
  patterns:
    spring_boot_conflict:
      conditions:
        - "spring"
        - "dependency"
        - "conflict"
      message: "Spring Boot conflict detected. Run 'mvn dependency:tree' and check for version mismatches."
  investigation_guidance: |
    Use `filter_errors_grep` on the failed build for more focused log analysis.
  max_recommendations: 5
```

### `build_processing`

Controls how aggressively the diagnostic path fans out across builds and log chunks.

Important fields:
- `parallel.max_workers`
- `parallel.max_batch_size`
- `chunks.max_total_chunks_analyzed`

Raise these when you want faster or broader analysis and can afford the load. Lower them when Jenkins, the MCP host, or the client is resource-constrained.

### `context`

Controls how much content is kept in memory and returned to the model.

Important fields:
- `max_tokens_total`
- `truncation_threshold`

If the output is too small or too aggressively trimmed, raise these values. If responses are too large or slow, lower them.

### `summary`

Controls the final build summary.

Important fields:
- `max_failures_displayed`
- `success_rate_precision`
- summary templates for failure lists and overflow handling

### `log_processing`

Controls cached log access and chunk extraction behavior.

Adjust this only if you are tuning around unusually large logs or storage constraints.

### `display` and `debugging`

These sections exist for output formatting and internal logging. They are useful when tuning readability or diagnosing why the diagnostic engine behaved a certain way, but most users do not need to change them first.

## Practical Tuning Patterns

### Reduce noise

Use stricter search and fewer highlights:

```yaml
semantic_search:
  min_diagnostic_score: 0.75
  max_total_highlights: 3
recommendations:
  max_recommendations: 4
```

### Increase detail

Use more chunks and allow more output:

```yaml
build_processing:
  chunks:
    max_total_chunks_analyzed: 2000
context:
  max_tokens_total: 15000
semantic_search:
  max_total_highlights: 8
```

### Reduce runtime cost

Lower concurrency and total work:

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

## Minimal Override Example

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
python3 -c "import yaml; yaml.safe_load(open('config/diagnostic-parameters.yml'))"
python3 scripts/validate_diagnostic_config.py
```

## Reloading in a Python Session

```python
from jenkins_mcp_enterprise.diagnostic_config import reload_diagnostic_config

reload_diagnostic_config()
```

## Recommended Workflow

1. Start with the bundled defaults.
2. Add a small override file in `config/diagnostic-parameters.yml`.
3. Change only the sections tied to the problem you are solving.
4. Re-run diagnosis on a representative failing build.
5. Tighten or relax the thresholds based on the actual output quality.
