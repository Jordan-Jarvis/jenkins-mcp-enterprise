# Diagnostic Parameters Quick Reference

A condensed reference for the most commonly used diagnostic parameters.

## Quick Configuration Locations

```bash
# Environment variable
export JENKINS_MCP_DIAGNOSTIC_CONFIG="/path/to/config.yml"

# User override (auto-detected)
config/diagnostic-parameters.yml

# Default location
jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml
```

## Essential Parameters

### Performance Tuning

```yaml
build_processing:
  parallel:
    max_batch_size: 5          # Concurrent builds (2-15)
    max_workers: 5             # Thread pool size (2-12)
  chunks:
    max_total_chunks_analyzed: 1000  # Processing limit (200-5000)

context:
  max_tokens_total: 10000      # Memory budget (3000-20000)
  truncation_threshold: 8000   # When to truncate (2500-15000)
```

### Search Configuration

```yaml
semantic_search:
  min_diagnostic_score: 0.6    # Relevance threshold (0.3-0.8)
  max_total_highlights: 5      # Results shown (3-10)
  search_queries:              # Customize for your tech stack
    - "your specific error patterns"
```

### Common Patterns

```yaml
failure_patterns:
  stack_trace_patterns:        # Fallback when semantic search disabled
    - "exception"
    - "error"
    - "failed"
    - "timeout"
```

### Custom Recommendations

```yaml
recommendations:
  patterns:
    # Simple string patterns
    your_pattern_name:
      conditions:
        - "error pattern to match"
        - ["option1", "option2"]  # OR condition
      message: "🔧 **Your Fix**: Description of solution"
    
    # Regex patterns with capture groups
    regex_pattern_name:
      conditions:
        - type: "regex"
          pattern: "error_code:\\s*(?P<code>\\d+)"
          message_template: "⚠️ **Error {code}**: Specific error detected"
      message: "Fallback message if template fails"
  max_recommendations: 6       # Total shown (4-10)
```

## Quick Customization Templates

### High Performance
```yaml
build_processing:
  parallel: {max_batch_size: 10, max_workers: 8}
context: {max_tokens_total: 20000, truncation_threshold: 15000}
```

### Resource Constrained
```yaml
build_processing:
  parallel: {max_batch_size: 2, max_workers: 2}
context: {max_tokens_total: 3000, truncation_threshold: 2500}
```

### Detailed Analysis
```yaml
semantic_search: {max_total_highlights: 10, min_diagnostic_score: 0.4}
recommendations: {max_recommendations: 10}
summary: {max_failures_displayed: 10}
```

### Quick Debug
```yaml
debugging:
  log_levels: {semantic_search: "DEBUG", pattern_matching: "DEBUG"}
  performance: {log_processing_times: true, track_chunk_counts: true}
```

## Regex Pattern Templates

### Basic Regex Pattern
```yaml
pattern_name:
  conditions:
    - type: "regex"
      pattern: "your_regex_pattern_here"
      message_template: "Message with {captured_groups}"
  message: "Fallback message"
```

### Common Regex Examples
```yaml
# Extract version numbers
version_detection:
  conditions:
    - type: "regex"
      pattern: "version:\\s*(?P<version>\\d+\\.\\d+\\.\\d+)"
      message_template: "📦 **Version**: {version}"

# Parse error codes
error_codes:
  conditions:
    - type: "regex"
      pattern: "error\\s+(\\d+):\\s*(.+)"
      message_template: "🚨 **Error {group_1}**: {group_2}"

# Build timing
build_duration:
  conditions:
    - type: "regex"
      pattern: "completed in (?P<minutes>\\d+)m(?P<seconds>\\d+)s"
      message_template: "⏱️ **Duration**: {minutes}m{seconds}s"
```

## Technology-Specific Quick Configs

### Java/Spring Boot
```yaml
semantic_search:
  search_queries:
    - "springframework exception"
    - "java.lang.NullPointerException"
    - "maven dependency"
    - "junit test failed"

# Regex patterns for Java stack traces
recommendations:
  patterns:
    java_exceptions:
      conditions:
        - type: "regex"
          pattern: "(?P<exception>\\w+Exception).*?at (?P<class>[a-zA-Z0-9.]+)\\((?P<file>[^:]+):(?P<line>\\d+)\\)"
          message_template: "☕ **{exception}**: at {class} ({file}:{line})"
      message: "Java exception detected"
```

### Docker/Kubernetes
```yaml
semantic_search:
  search_queries:
    - "docker build failed"
    - "kubernetes pod crash"
    - "image pull failed"
    - "volume mount permission"
```

### Python/Django
```yaml
semantic_search:
  search_queries:
    - "python traceback"
    - "django.core.exceptions"
    - "pip install failed"
    - "import error module"
```

### Node.js
```yaml
semantic_search:
  search_queries:
    - "npm install failed"
    - "node error ENOENT"
    - "javascript TypeError"
    - "webpack build failed"
```

## Common Issue Fixes

### No Results → Lower Threshold
```yaml
semantic_search:
  min_diagnostic_score: 0.3
```

### Too Slow → Reduce Parallelism
```yaml
build_processing:
  parallel: {max_batch_size: 3, max_workers: 3}
```

### Truncated Content → Increase Limits
```yaml
context:
  max_tokens_total: 15000
display:
  truncation: {max_display_length: 800}
```

### Memory Issues → Reduce Usage
```yaml
context: {max_tokens_total: 5000}
build_processing:
  chunks: {max_total_chunks_analyzed: 500}
```

## Hot Reload Configuration

```python
from jenkins_mcp_enterprise.diagnostic_config import reload_diagnostic_config
reload_diagnostic_config()
```

## Validation

```bash
# Syntax check
python3 -c "import yaml; yaml.safe_load(open('diagnostic-parameters.yml'))"

# Load test
python3 -c "from jenkins_mcp_enterprise.diagnostic_config import get_diagnostic_config; get_diagnostic_config()"
```

For complete parameter documentation, see `diagnostic-parameters-guide.md`.