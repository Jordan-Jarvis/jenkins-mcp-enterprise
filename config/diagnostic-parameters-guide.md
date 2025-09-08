# Jenkins MCP Diagnostic Parameters Guide

A comprehensive guide to configuring the `diagnose_build_failure` tool through the `diagnostic-parameters.yml` configuration system.

## Table of Contents

1. [Overview](#overview)
2. [Configuration Structure](#configuration-structure)
3. [Semantic Search Configuration](#semantic-search-configuration)
4. [Pattern Recognition Configuration](#pattern-recognition-configuration)
5. [Recommendations Engine Configuration](#recommendations-engine-configuration)
6. [Build Processing Configuration](#build-processing-configuration)
7. [Summary Generation Configuration](#summary-generation-configuration)
8. [Context and Token Management](#context-and-token-management)
9. [Log Processing Configuration](#log-processing-configuration)
10. [Heuristic Analysis Configuration](#heuristic-analysis-configuration)
11. [Error Analysis Configuration](#error-analysis-configuration)
12. [Vector Search Configuration](#vector-search-configuration)
13. [Display and Formatting Configuration](#display-and-formatting-configuration)
14. [Debugging and Logging Configuration](#debugging-and-logging-configuration)
15. [Real-World Examples](#real-world-examples)
16. [Best Practices](#best-practices)
17. [Troubleshooting](#troubleshooting)

## Overview

The diagnostic parameters system allows you to customize every aspect of how Jenkins build failures are analyzed. Instead of hard-coded values, all behavior is now configurable through a YAML file.

### Configuration File Locations

The system looks for configuration files in this priority order:

1. **Environment Variable**: `JENKINS_MCP_DIAGNOSTIC_CONFIG=/path/to/config.yml`
2. **User Override**: `config/diagnostic-parameters.yml` (in project root)
3. **Bundled Default**: `jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml`

### Loading Configuration

```python
from jenkins_mcp_enterprise.diagnostic_config import get_diagnostic_config

config = get_diagnostic_config()
# Configuration is automatically loaded and cached
```

## Configuration Structure

The configuration file is organized into logical sections that control different aspects of the diagnostic process:

```yaml
# Top-level sections
semantic_search:      # AI-powered failure detection
failure_patterns:     # Pattern-based fallback analysis
recommendations:      # Action recommendations system
build_processing:     # Performance and parallelization
summary:             # Report generation
context:             # Token and memory management
log_processing:      # File handling and caching
heuristics:          # Pattern matching algorithms
error_analysis:      # Error categorization
vector_search:       # Semantic search parameters
display:             # Output formatting
debugging:           # Diagnostic logging
```

## Semantic Search Configuration

Controls AI-powered semantic search for intelligent failure detection.

### Parameters

```yaml
semantic_search:
  # Search queries for semantic highlighting
  search_queries:
    - "java exception stack trace at"
    - "test failed junit assertion error"
    - "no such file"
    - "gradle build failed compilation error"
    - "jarsigner error runtime exception"
    - "timeout connection refused network"
    - "out of memory heap space"
    - "cannot find symbol compilation"
    - "permission denied access file"
  
  # Result limits
  max_results_per_query: 2      # Results per search query
  max_total_highlights: 5       # Total highlights in final report
  min_content_length: 50        # Minimum content length to consider
  min_diagnostic_score: 0.6     # Minimum relevance score (0.0-1.0)
  max_content_preview: 400      # Maximum preview length in characters
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search_queries` | List[str] | See above | Natural language queries for semantic search |
| `max_results_per_query` | int | 2 | Maximum results returned per search query |
| `max_total_highlights` | int | 5 | Total highlights displayed in final report |
| `min_content_length` | int | 50 | Minimum content length to include in results |
| `min_diagnostic_score` | float | 0.6 | Minimum similarity score (0.0 = any match, 1.0 = exact match) |
| `max_content_preview` | int | 400 | Maximum characters shown in content preview |

### Example: Custom Search Queries

```yaml
semantic_search:
  search_queries:
    # Java-specific failures
    - "nullpointerexception stack trace"
    - "classnotfoundexception missing dependency"
    
    # Database failures
    - "connection timeout database"
    - "sql syntax error query"
    
    # Network failures  
    - "connection refused timeout"
    - "certificate ssl error"
    
    # Docker/Container failures
    - "docker image pull failed"
    - "container exit code 1"
  
  # Stricter relevance filtering
  min_diagnostic_score: 0.75
  max_results_per_query: 1
```

## Pattern Recognition Configuration

Fallback system when semantic search is disabled or fails.

### Parameters

```yaml
failure_patterns:
  # Error patterns for fallback analysis
  stack_trace_patterns:
    - "stack trace"
    - "exception in thread"
    - "jarsigner error"
    - "keystore load"
    - "build failed"
    - "test failed"
    - "compilation failed"
  
  # Processing limits
  max_fallback_patterns: 3      # Maximum patterns to extract
  max_pattern_preview: 200      # Maximum preview length per pattern
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `stack_trace_patterns` | List[str] | See above | Text patterns indicating failures |
| `max_fallback_patterns` | int | 3 | Maximum number of patterns to extract and display |
| `max_pattern_preview` | int | 200 | Maximum characters shown per pattern match |

### Example: Extended Pattern Recognition

```yaml
failure_patterns:
  stack_trace_patterns:
    # Java patterns
    - "exception in thread"
    - "caused by:"
    - "at java."
    - "at org."
    
    # Build tool patterns
    - "build failed"
    - "compilation error"
    - "gradle build failed"
    - "maven build failure"
    
    # Test patterns
    - "test failed"
    - "assertion error"
    - "junit"
    - "testng"
    
    # Infrastructure patterns
    - "connection refused"
    - "timeout"
    - "permission denied"
    - "no such file"
    
  max_fallback_patterns: 5
  max_pattern_preview: 300
```

## Advanced Regex Pattern Configuration

The system supports sophisticated regex patterns with capture groups for automated data extraction and dynamic message generation.

### Regex Pattern Structure

```yaml
recommendations:
  patterns:
    pattern_name:
      conditions:
        - type: "regex"
          pattern: "regular_expression_with_(?P<name>groups)"
          message_template: "Template with {name} placeholders"
          flags: 2  # Optional: regex flags
      message: "Fallback message when interpolation fails"
```

### Capture Group Types

#### Named Capture Groups
Use Python's named group syntax for clear data extraction:

```yaml
timestamp_extraction:
  conditions:
    - type: "regex"
      pattern: "\\[(?P<date>\\d{4}-\\d{2}-\\d{2})\\s+(?P<time>\\d{2}:\\d{2}:\\d{2})\\]"
      message_template: "🕐 **Timestamp**: {date} at {time}"
  message: "Timestamp information detected"
```

#### Numbered Capture Groups
For simpler patterns, use numbered groups:

```yaml
error_codes:
  conditions:
    - type: "regex"
      pattern: "EXIT_CODE\\s+(\\d+)\\s+(.+)"
      message_template: "🚨 **Exit Code {group_1}**: {group_2}"
  message: "Exit code information"
```

### Message Template Interpolation

Templates support Python string formatting with captured group names:

- **Named Groups**: `{group_name}` using the exact name from `(?P<group_name>...)`
- **Numbered Groups**: `{group_1}`, `{group_2}`, etc. for unnamed groups
- **Fallback**: If interpolation fails, uses the main `message` field

### Regex Flags

Common regex flags (combine with bitwise OR):

```yaml
conditions:
  - type: "regex"
    pattern: "case_sensitive_pattern"
    flags: 0          # No flags
    
  - type: "regex"
    pattern: "case_insensitive"
    flags: 2          # re.IGNORECASE
    
  - type: "regex" 
    pattern: "multiline.*pattern"
    flags: 10         # re.IGNORECASE | re.MULTILINE (2 + 8)
```

### Performance Considerations

- **Compiled Patterns**: Regex patterns are compiled once and cached for performance
- **Error Handling**: Invalid patterns are logged but don't break the system
- **Timeout Protection**: Complex patterns are protected by processing limits
- **Memory Efficient**: Only successful matches store captured groups

### Example: Comprehensive Build Analysis

```yaml
recommendations:
  patterns:
    # Extract build version and duration
    build_info:
      conditions:
        - type: "regex"
          pattern: "Build\\s+(?P<version>\\d+\\.\\d+\\.\\d+).*?completed in (?P<duration>\\d+)m(?P<seconds>\\d+)s"
          message_template: "🏗️ **Build {version}**: Completed in {duration}m{seconds}s"
      message: "Build information extracted"
    
    # Parse error messages with severity
    error_categorization:
      conditions:
        - type: "regex"
          pattern: "\\[(?P<severity>ERROR|WARN|INFO)\\].*?(?P<component>[A-Za-z0-9_]+):\\s*(?P<message>[^\\n]+)"
          message_template: "{severity} in {component}: {message}"
      message: "Error categorization with details"
    
    # Extract test results
    test_summary:
      conditions:
        - type: "regex"
          pattern: "Tests run:\\s*(?P<total>\\d+),\\s*Failures:\\s*(?P<failures>\\d+),\\s*Errors:\\s*(?P<errors>\\d+)"
          message_template: "🧪 **Test Results**: {total} total, {failures} failures, {errors} errors"
      message: "Test execution summary"
    
    # Database connection details
    db_connection:
      conditions:
        - type: "regex"
          pattern: "Connected to (?P<db_type>\\w+) at (?P<host>[^:]+):(?P<port>\\d+)/(?P<database>\\w+)"
          message_template: "🗄️ **Database**: {db_type} at {host}:{port}/{database}"
      message: "Database connection established"
```

### Migration from Simple Patterns

Converting existing simple patterns to regex patterns:

```yaml
# Before: Simple string matching
old_pattern:
  conditions:
    - "build failed"
  message: "Build failure detected"

# After: Regex with data extraction
new_pattern:
  conditions:
    - type: "regex"
      pattern: "build\\s+(?P<phase>\\w+)\\s+failed.*?error:\\s*(?P<error>[^\\n]+)"
      message_template: "🚨 **Build Failed**: {phase} phase - {error}"
  message: "Build failure with detailed information"
```

### Troubleshooting Regex Patterns

#### Common Issues

1. **No Matches**: Pattern too specific or incorrect escaping
2. **Invalid Regex**: Syntax errors in pattern
3. **Missing Groups**: Template references non-existent groups
4. **Performance**: Complex patterns causing slow processing

#### Debug Configuration

```yaml
debugging:
  log_levels:
    pattern_matching: "DEBUG"  # Enable detailed pattern matching logs
  error_reporting:
    include_stack_traces: true  # Show regex compilation errors
```

#### Testing Patterns

```python
# Test regex patterns before deployment
import re

pattern = r"build\s+(?P<phase>\w+)\s+failed"
test_content = "build compile failed with errors"

match = re.search(pattern, test_content, re.IGNORECASE)
if match:
    print(f"Groups: {match.groupdict()}")
    template = "Build Failed: {phase} phase"
    print(f"Result: {template.format(**match.groupdict())}")
```

## Recommendations Engine Configuration

Generates actionable recommendations based on detected failure patterns.

### Parameters

```yaml
recommendations:
  # Pattern-based recommendation mappings
  patterns:
    keystore_issues:
      conditions:
        - "keystore load"
        - "appletkeystore"
      message: "🔑 **Keystore Issue**: Missing AppletKeyStore file. Check if /data/jenkins/AppletKeyStore exists on build agents."
    
    gradle_build_failures:
      conditions:
        - "build failed"
        - "gradle"
      message: "🛠️ **Gradle Build**: Run with --debug for detailed error info. Check for dependency conflicts."
  
  # Priority job patterns
  priority_jobs:
    product_app_pattern: "django_build"
    max_priority_builds: 3
    priority_message_template: "🎯 **Priority**: Focus on {job_pattern} builds {build_numbers} - these are the deepest failure points."
  
  # Investigation guidance
  investigation_guidance: |
    🔍 **Next Steps**: Use `filter_errors_grep` tool on specific failed builds for detailed error analysis.
  
  # Limits
  max_recommendations: 6
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `patterns` | Dict | See above | Pattern-to-recommendation mappings |
| `priority_jobs` | Dict | See above | Priority job identification settings |
| `investigation_guidance` | str | See above | Standard investigation text |
| `max_recommendations` | int | 6 | Maximum recommendations in final report |

### Pattern Condition Types

Conditions support multiple formats for flexible pattern matching:

1. **Single String**: `"gradle"` - matches if "gradle" appears in content
2. **OR Conditions**: `["test failed", "junit"]` - matches if ANY condition is found
3. **AND Conditions**: Use separate items for AND logic
4. **Regex with Capture Groups**: Advanced pattern matching with data extraction

#### Regex Pattern Format

```yaml
conditions:
  - type: "regex"
    pattern: "build_number:\\s*(?P<build_num>\\d+)"
    message_template: "📋 **Build Number**: {build_num}"
    flags: 2  # Optional: re.IGNORECASE (default)
```

**Regex Pattern Fields:**
- `type`: Must be "regex" for regex patterns
- `pattern`: Regular expression with optional named capture groups
- `message_template`: Template string using captured group names
- `flags`: Optional regex flags (default: re.IGNORECASE)

**Named Capture Groups:**
- Use `(?P<name>pattern)` syntax for named groups
- Access in templates with `{name}` placeholders
- Automatically available for message interpolation

**Numbered Capture Groups:**
- Use `(pattern)` for numbered groups
- Accessed as `{group_1}`, `{group_2}`, etc.
- Fallback when named groups not used

### Example: Custom Recommendations

```yaml
recommendations:
  patterns:
    # Traditional string patterns
    docker_failures:
      conditions:
        - ["docker", "container"]
        - "image pull"
      message: "🐳 **Docker Issue**: Container or image problems. Check Docker daemon and registry connectivity."
    
    # Regex patterns with capture groups
    version_extraction:
      conditions:
        - type: "regex"
          pattern: "version:\\s*(?P<version>[0-9]+\\.[0-9]+\\.[0-9]+)"
          message_template: "📦 **Version Detected**: {version}"
      message: "Version information extracted from build logs"
    
    error_code_detection:
      conditions:
        - type: "regex"
          pattern: "error_code:\\s*(?P<code>\\d+).*?message:\\s*(?P<msg>[^\\n]+)"
          message_template: "⚠️ **Error {code}**: {msg}"
      message: "Detailed error information captured"
    
    build_timing:
      conditions:
        - type: "regex"
          pattern: "build took (?P<duration>\\d+)m(?P<seconds>\\d+)s"
          message_template: "⏱️ **Build Duration**: {duration} minutes {seconds} seconds"
      message: "Build timing analysis"
    
    database_connectivity:
      conditions:
        - ["database", "sql"]
        - ["connection", "timeout"]
      message: "🗄️ **Database**: Connection issues detected. Verify database server availability and credentials."
    
    ssl_certificate_issues:
      conditions:
        - ["ssl", "certificate"]
        - ["handshake", "trust"]
      message: "🔒 **SSL Certificate**: Certificate validation failed. Update certificates or configure trust store."
    
    memory_exhaustion:
      conditions:
        - ["out of memory", "heap space"]
      message: "💾 **Memory**: Increase JVM heap size with -Xmx flag. Consider memory profiling for optimization."
    
    network_connectivity:
      conditions:
        - ["connection refused", "network unreachable"]
      message: "🌐 **Network**: Connectivity issues. Check firewall rules, DNS resolution, and service availability."
  
  priority_jobs:
    product_app_pattern: "production-app"
    max_priority_builds: 5
    priority_message_template: "⚠️ **CRITICAL**: Production app builds {build_numbers} failed - immediate attention required!"
  
  investigation_guidance: |
    🔍 **Investigation Steps**:
    1. Review the deepest failed builds first
    2. Use `filter_errors_grep` with specific error patterns
    3. Check recent changes in failed components
    4. Verify infrastructure dependencies
    
    📋 **Common Commands**:
    - `filter_errors_grep` for detailed log analysis
    - `ripgrep_search` for pattern matching
    - `navigate_log` for section jumping
  
  max_recommendations: 8
```

## Build Processing Configuration

Controls performance, parallelization, and resource usage.

### Parameters

```yaml
build_processing:
  # Parallel processing settings
  parallel:
    max_batch_size: 5      # Process up to 5 builds concurrently
    max_workers: 5         # Maximum number of worker threads
  
  # Chunk processing limits
  chunks:
    max_chunks_for_analysis: 10       # Top chunks for fallback analysis
    max_chunks_for_content: 20        # Max chunks for recommendations
    max_total_chunks_analyzed: 1000   # Global limit for chunk processing
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_batch_size` | int | 5 | Concurrent builds processed simultaneously |
| `max_workers` | int | 5 | Thread pool size for parallel processing |
| `max_chunks_for_analysis` | int | 10 | Chunks used for fallback pattern analysis |
| `max_chunks_for_content` | int | 20 | Chunks sampled for recommendations |
| `max_total_chunks_analyzed` | int | 1000 | Global chunk processing limit |

### Example: Performance Tuning

```yaml
build_processing:
  parallel:
    # High-performance configuration
    max_batch_size: 10
    max_workers: 8
  
  chunks:
    # Detailed analysis configuration
    max_chunks_for_analysis: 20
    max_chunks_for_content: 50
    max_total_chunks_analyzed: 2000
```

```yaml
build_processing:
  parallel:
    # Resource-constrained configuration
    max_batch_size: 2
    max_workers: 3
  
  chunks:
    # Lightweight analysis
    max_chunks_for_analysis: 5
    max_chunks_for_content: 10
    max_total_chunks_analyzed: 500
```

## Summary Generation Configuration

Controls how build analysis summaries are formatted and displayed.

### Parameters

```yaml
summary:
  # Build summary settings
  max_failures_displayed: 5
  failure_list_template: "  - {job_name} #{build_number} ({status})\n"
  overflow_message_template: "  ... and {count} more failures\n"
  
  # Success rate calculation
  success_rate_precision: 1    # Decimal places for success rate percentage
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_failures_displayed` | int | 5 | Maximum failed builds shown in summary |
| `failure_list_template` | str | See above | Format string for each failure entry |
| `overflow_message_template` | str | See above | Message when failures exceed display limit |
| `success_rate_precision` | int | 1 | Decimal places in success rate percentage |

### Template Variables

- `{job_name}`: Jenkins job name
- `{build_number}`: Build number
- `{status}`: Build status (FAILURE, SUCCESS, etc.)
- `{count}`: Number of additional failures (overflow template)

### Example: Custom Summary Formatting

```yaml
summary:
  max_failures_displayed: 10
  failure_list_template: "❌ {job_name} build #{build_number} - {status}\n"
  overflow_message_template: "📊 Plus {count} additional failures (use detailed view for complete list)\n"
  success_rate_precision: 2
```

## Context and Token Management

Manages memory usage and content processing limits.

### Parameters

```yaml
context:
  # Token limits for various operations
  max_tokens_total: 10000
  max_tokens_per_chunk: 1000
  truncation_threshold: 8000
  
  # Chunk value scoring
  high_value_chunk_threshold: 0.7
  chunk_scoring_weights:
    error_keywords: 0.4
    stack_trace_indicators: 0.3
    failure_context: 0.3
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_tokens_total` | int | 10000 | Total token budget for analysis |
| `max_tokens_per_chunk` | int | 1000 | Maximum tokens per log chunk |
| `truncation_threshold` | int | 8000 | When to start truncating content |
| `high_value_chunk_threshold` | float | 0.7 | Score threshold for high-value chunks |
| `chunk_scoring_weights` | Dict[str, float] | See above | Weights for chunk value calculation |

### Example: Memory-Optimized Configuration

```yaml
context:
  # Conservative memory usage
  max_tokens_total: 5000
  max_tokens_per_chunk: 500
  truncation_threshold: 4000
  
  high_value_chunk_threshold: 0.8
  chunk_scoring_weights:
    error_keywords: 0.5      # Prioritize error detection
    stack_trace_indicators: 0.4
    failure_context: 0.1
```

## Log Processing Configuration

Controls file handling, caching, and log retrieval.

### Parameters

```yaml
log_processing:
  # File handling
  cache_validation:
    min_file_size: 1         # Minimum file size in bytes
    encoding: "utf-8"        # File encoding
    error_handling: "ignore" # Error handling strategy
  
  # Processing limits
  max_parallel_log_fetches: 5
  log_fetch_timeout: 30      # seconds
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_file_size` | int | 1 | Minimum valid file size in bytes |
| `encoding` | str | "utf-8" | Text encoding for log files |
| `error_handling` | str | "ignore" | How to handle encoding errors |
| `max_parallel_log_fetches` | int | 5 | Concurrent log fetch operations |
| `log_fetch_timeout` | int | 30 | Timeout in seconds for log retrieval |

### Example: Robust Log Processing

```yaml
log_processing:
  cache_validation:
    min_file_size: 100       # Require at least 100 bytes
    encoding: "utf-8"
    error_handling: "replace" # Replace bad characters
  
  max_parallel_log_fetches: 3  # Conservative for stability
  log_fetch_timeout: 60        # Longer timeout for large logs
```

## Heuristic Analysis Configuration

Controls pattern matching algorithms and scoring.

### Parameters

```yaml
heuristics:
  # Pattern matching settings
  case_sensitive: false
  context_window_default: 5
  
  # Pattern categories and weights
  pattern_categories:
    critical_errors:
      weight: 1.0
      patterns:
        - "FATAL"
        - "CRITICAL"
        - "SEVERE"
    
    build_failures:
      weight: 0.9
      patterns:
        - "BUILD FAILED"
        - "COMPILATION ERROR"
    
    test_failures:
      weight: 0.8
      patterns:
        - "TEST FAILED"
        - "ASSERTION ERROR"
    
    infrastructure_issues:
      weight: 0.7
      patterns:
        - "CONNECTION REFUSED"
        - "TIMEOUT"
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `case_sensitive` | bool | false | Whether pattern matching is case-sensitive |
| `context_window_default` | int | 5 | Default lines of context around matches |
| `pattern_categories` | Dict | See above | Categorized patterns with weights |

### Example: Extended Heuristic Categories

```yaml
heuristics:
  case_sensitive: false
  context_window_default: 10
  
  pattern_categories:
    security_errors:
      weight: 1.0
      patterns:
        - "SECURITY VIOLATION"
        - "AUTHENTICATION FAILED"
        - "UNAUTHORIZED ACCESS"
        - "CERTIFICATE INVALID"
    
    performance_issues:
      weight: 0.6
      patterns:
        - "SLOW QUERY"
        - "PERFORMANCE WARNING"
        - "MEMORY LEAK"
        - "CPU THRESHOLD"
    
    configuration_errors:
      weight: 0.8
      patterns:
        - "CONFIG ERROR"
        - "INVALID PROPERTY"
        - "MISSING CONFIGURATION"
        - "PARSE ERROR"
```

## Error Analysis Configuration

Controls error categorization and status handling.

### Parameters

```yaml
error_analysis:
  # Skip conditions
  skip_successful_builds_default: true
  success_status_values:
    - "SUCCESS"
    - "STABLE"
  
  # Status mapping
  status_mappings:
    building: "IN_PROGRESS"
    unknown: "UNKNOWN"
    error_fetching: "ERROR_FETCHING_STATUS"
  
  # Error categorization
  error_categories:
    network: ["connection", "timeout", "refused", "unreachable"]
    compilation: ["cannot find symbol", "compilation error", "syntax error"]
    test: ["test failed", "assertion", "junit", "testng"]
    dependency: ["artifact not found", "dependency", "repository"]
    memory: ["out of memory", "heap space", "gc overhead"]
    permission: ["permission denied", "access denied", "unauthorized"]
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip_successful_builds_default` | bool | true | Default value for skipping successful builds |
| `success_status_values` | List[str] | See above | Build statuses considered successful |
| `status_mappings` | Dict[str, str] | See above | Status normalization mappings |
| `error_categories` | Dict[str, List[str]] | See above | Error classification patterns |

### Example: Extended Error Categorization

```yaml
error_analysis:
  skip_successful_builds_default: false  # Analyze all builds
  success_status_values:
    - "SUCCESS"
    - "STABLE"
    - "UNSTABLE"  # Include unstable as success
  
  error_categories:
    database:
      - "sql error"
      - "database connection"
      - "transaction failed"
      - "deadlock"
    
    docker:
      - "docker build failed"
      - "image not found"
      - "container exited"
      - "volume mount"
    
    security:
      - "certificate"
      - "ssl handshake"
      - "authentication"
      - "authorization"
    
    infrastructure:
      - "server unreachable"
      - "service unavailable"
      - "load balancer"
      - "dns resolution"
```

## Vector Search Configuration

Controls semantic search behavior and indexing.

### Parameters

```yaml
vector_search:
  # Search parameters
  hierarchical_search:
    default_top_k: 10
    min_score_threshold: 0.5
    max_search_depth: 5
  
  # Indexing settings
  indexing:
    chunk_overlap: 50
    max_chunk_size: 1000
    min_chunk_size: 100
  
  # Fallback behavior
  fallback_enabled: true
  fallback_max_patterns: 5
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `default_top_k` | int | 10 | Default number of search results |
| `min_score_threshold` | float | 0.5 | Minimum similarity score for results |
| `max_search_depth` | int | 5 | Maximum search depth in hierarchy |
| `chunk_overlap` | int | 50 | Character overlap between chunks |
| `max_chunk_size` | int | 1000 | Maximum characters per chunk |
| `min_chunk_size` | int | 100 | Minimum characters per chunk |
| `fallback_enabled` | bool | true | Enable fallback when vector search fails |
| `fallback_max_patterns` | int | 5 | Maximum patterns in fallback mode |

## Display and Formatting Configuration

Controls output appearance and hierarchy visualization.

### Parameters

```yaml
display:
  # Hierarchy visualization
  hierarchy:
    indent_spaces_per_depth: 4
    connector_symbol: "└── "
    prefix_adjustment: 2
  
  # Status formatting
  status_display:
    unknown_placeholder: "UNKNOWN"
    url_placeholder: "No URL"
    failure_indicator: "FAILURE"
  
  # Content truncation
  truncation:
    max_display_length: 400
    truncation_suffix: "..."
    min_meaningful_length: 50
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `indent_spaces_per_depth` | int | 4 | Spaces per hierarchy level |
| `connector_symbol` | str | "└── " | Symbol connecting hierarchy items |
| `prefix_adjustment` | int | 2 | Additional spacing adjustment |
| `unknown_placeholder` | str | "UNKNOWN" | Text for unknown status |
| `url_placeholder` | str | "No URL" | Text when URL unavailable |
| `failure_indicator` | str | "FAILURE" | Status text indicating failure |
| `max_display_length` | int | 400 | Maximum content display length |
| `truncation_suffix` | str | "..." | Suffix for truncated content |
| `min_meaningful_length` | int | 50 | Minimum content length before truncation |

### Example: Custom Display Formatting

```yaml
display:
  hierarchy:
    indent_spaces_per_depth: 6
    connector_symbol: "├── "
    prefix_adjustment: 1
  
  status_display:
    unknown_placeholder: "❓ STATUS_UNKNOWN"
    url_placeholder: "🔗 URL_NOT_AVAILABLE"
    failure_indicator: "❌ FAILED"
  
  truncation:
    max_display_length: 500
    truncation_suffix: " [truncated...]"
    min_meaningful_length: 100
```

## Debugging and Logging Configuration

Controls diagnostic logging and performance monitoring.

### Parameters

```yaml
debugging:
  # Log levels for different components
  log_levels:
    semantic_search: "DEBUG"
    pattern_matching: "INFO"
    build_processing: "INFO"
    cache_operations: "INFO"
  
  # Performance monitoring
  performance:
    log_processing_times: true
    track_chunk_counts: true
    monitor_memory_usage: false
  
  # Error reporting
  error_reporting:
    include_stack_traces: false
    max_error_message_length: 200
    aggregate_similar_errors: true
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `log_levels` | Dict[str, str] | See above | Component-specific log levels |
| `log_processing_times` | bool | true | Log operation timing information |
| `track_chunk_counts` | bool | true | Track chunk processing statistics |
| `monitor_memory_usage` | bool | false | Monitor memory consumption |
| `include_stack_traces` | bool | false | Include stack traces in error reports |
| `max_error_message_length` | int | 200 | Maximum length of error messages |
| `aggregate_similar_errors` | bool | true | Group similar errors together |

## Real-World Examples

### Example 1: Java/Spring Boot Environment with Regex Patterns

```yaml
# Configuration optimized for Java/Spring Boot applications
semantic_search:
  search_queries:
    - "springframework exception autowired"
    - "java.lang.NullPointerException stack trace"
    - "org.springframework.boot startup failed"
    - "maven dependency resolution failed"
    - "junit test assertion error"
    - "hibernate database connection"
    - "tomcat server startup error"
  max_results_per_query: 3
  min_diagnostic_score: 0.65

recommendations:
  patterns:
    # Traditional patterns
    spring_boot_startup:
      conditions:
        - ["springframework", "boot"]
        - "startup failed"
      message: "🍃 **Spring Boot**: Application startup failed. Check configuration, dependencies, and bean wiring."
    
    maven_dependency:
      conditions:
        - "maven"
        - ["dependency", "artifact not found"]
      message: "📦 **Maven**: Dependency resolution issues. Update repositories or version conflicts."
    
    # Regex patterns for detailed extraction
    java_exception_analysis:
      conditions:
        - type: "regex"
          pattern: "(?P<exception>\\w+Exception).*?at (?P<location>[a-zA-Z0-9.]+)\\((?P<file>[^:]+):(?P<line>\\d+)\\)"
          message_template: "☕ **Java Exception**: {exception} at {location} ({file}:{line})"
      message: "Java exception with stack trace details"
    
    maven_version_conflict:
      conditions:
        - type: "regex"
          pattern: "artifact (?P<artifact>[^:]+:[^:]+):(?P<version>[0-9.]+)"
          message_template: "📦 **Maven Artifact**: {artifact} version {version}"
      message: "Maven dependency version information"
    
    junit_test_failure:
      conditions:
        - type: "regex"
          pattern: "(?P<test_class>[a-zA-Z0-9.]+)\\.(?P<test_method>\\w+).*?AssertionError:\\s*(?P<message>[^\\n]+)"
          message_template: "🧪 **Test Failed**: {test_class}.{test_method} - {message}"
      message: "JUnit test failure details"

error_analysis:
  error_categories:
    spring_framework:
      - "springframework"
      - "bean creation"
      - "autowired"
      - "component scan"
    
    hibernate_jpa:
      - "hibernate"
      - "entitymanager"
      - "transaction"
      - "schema validation"
```

### Example 2: Docker/Kubernetes Environment

```yaml
# Configuration for containerized applications
semantic_search:
  search_queries:
    - "docker build failed dockerfile"
    - "kubernetes pod crash loopback"
    - "container image pull failed"
    - "volume mount permission denied"
    - "service discovery dns error"
    - "ingress controller nginx error"

recommendations:
  patterns:
    docker_build:
      conditions:
        - "docker build"
        - "failed"
      message: "🐳 **Docker Build**: Check Dockerfile syntax, base image availability, and build context."
    
    k8s_pod_issues:
      conditions:
        - ["kubernetes", "pod"]
        - ["crashloopbackoff", "imagepullbackoff"]
      message: "⚓ **Kubernetes**: Pod issues detected. Check resource limits, image tags, and secrets."
    
    volume_permissions:
      conditions:
        - "volume"
        - "permission denied"
      message: "💾 **Volume**: Permission issues with mounted volumes. Check user IDs and access modes."

error_analysis:
  error_categories:
    kubernetes:
      - "pod"
      - "service"
      - "deployment"
      - "configmap"
      - "secret"
    
    docker:
      - "dockerfile"
      - "image"
      - "container"
      - "registry"
```

### Example 3: High-Performance Configuration

```yaml
# Configuration for large-scale environments with many builds
build_processing:
  parallel:
    max_batch_size: 15
    max_workers: 12
  chunks:
    max_chunks_for_analysis: 30
    max_chunks_for_content: 100
    max_total_chunks_analyzed: 5000

context:
  max_tokens_total: 20000
  max_tokens_per_chunk: 2000
  truncation_threshold: 15000

log_processing:
  max_parallel_log_fetches: 10
  log_fetch_timeout: 120

summary:
  max_failures_displayed: 15
  success_rate_precision: 2

debugging:
  performance:
    log_processing_times: true
    track_chunk_counts: true
    monitor_memory_usage: true
```

### Example 4: Resource-Constrained Configuration

```yaml
# Configuration for limited resource environments
build_processing:
  parallel:
    max_batch_size: 2
    max_workers: 2
  chunks:
    max_chunks_for_analysis: 5
    max_chunks_for_content: 10
    max_total_chunks_analyzed: 200

context:
  max_tokens_total: 3000
  max_tokens_per_chunk: 300
  truncation_threshold: 2500

semantic_search:
  max_results_per_query: 1
  max_total_highlights: 3
  max_content_preview: 200

summary:
  max_failures_displayed: 3

recommendations:
  max_recommendations: 4
```

## Best Practices

### 1. Performance Tuning

- **Monitor Resource Usage**: Enable performance monitoring in development
- **Adjust Parallelism**: Scale `max_workers` based on available CPU cores
- **Token Management**: Set appropriate token limits based on available memory
- **Chunk Processing**: Balance analysis depth with processing time

### 2. Search Query Optimization

- **Specific Queries**: Use specific, targeted search queries for better results
- **Domain-Specific**: Customize queries for your technology stack
- **Score Thresholds**: Adjust `min_diagnostic_score` based on result quality
- **Result Limits**: Balance comprehensiveness with readability

### 3. Pattern Recognition

- **Incremental Expansion**: Start with core patterns and expand gradually
- **Test Coverage**: Ensure patterns cover your common failure modes
- **Weight Adjustment**: Fine-tune category weights based on importance
- **Regular Updates**: Keep patterns updated with new failure modes

### 4. Recommendations

- **Actionable**: Ensure recommendations provide clear next steps
- **Context-Aware**: Include relevant context (job names, error types)
- **Prioritized**: Order recommendations by impact and likelihood
- **Tool Integration**: Reference appropriate diagnostic tools

### 5. Configuration Management

- **Version Control**: Keep configurations in version control
- **Environment-Specific**: Use different configs for different environments
- **Documentation**: Document custom patterns and their purposes
- **Testing**: Test configuration changes in non-production environments

## Troubleshooting

### Common Issues

#### 1. No Semantic Search Results

**Symptoms**: Empty `semantic_search_highlights` in output

**Solutions**:
```yaml
semantic_search:
  min_diagnostic_score: 0.3  # Lower threshold
  search_queries:
    - "error"                # More generic queries
    - "failed"
    - "exception"
```

#### 2. Performance Issues

**Symptoms**: Slow diagnosis, timeouts

**Solutions**:
```yaml
build_processing:
  parallel:
    max_batch_size: 3        # Reduce parallelism
    max_workers: 3
context:
  max_tokens_total: 5000     # Reduce token usage
log_processing:
  max_parallel_log_fetches: 3
```

#### 3. Missing Recommendations

**Symptoms**: No recommendations generated

**Solutions**:
```yaml
recommendations:
  patterns:
    generic_failure:
      conditions:
        - "failed"
      message: "❌ **Build Failed**: General build failure detected."
```

#### 4. Truncated Content

**Symptoms**: Important information cut off

**Solutions**:
```yaml
context:
  max_tokens_total: 15000    # Increase limits
  truncation_threshold: 12000
display:
  truncation:
    max_display_length: 800
```

### Debug Configuration

Enable detailed logging to troubleshoot issues:

```yaml
debugging:
  log_levels:
    semantic_search: "DEBUG"
    pattern_matching: "DEBUG"
    build_processing: "DEBUG"
    cache_operations: "DEBUG"
  
  performance:
    log_processing_times: true
    track_chunk_counts: true
    monitor_memory_usage: true
  
  error_reporting:
    include_stack_traces: true
    max_error_message_length: 500
    aggregate_similar_errors: false
```

### Configuration Validation

Test your configuration:

```bash
# Validate configuration syntax
python3 -c "
import yaml
with open('diagnostic-parameters.yml') as f:
    config = yaml.safe_load(f)
print('✅ Configuration valid')
"

# Test configuration loading
python3 -c "
from jenkins_mcp_enterprise.diagnostic_config import get_diagnostic_config
config = get_diagnostic_config()
print(f'✅ Loaded {len(config.get_semantic_search_queries())} search queries')
"
```

## Configuration Hot-Reload

Reload configuration without restarting the server:

```python
from jenkins_mcp_enterprise.diagnostic_config import reload_diagnostic_config

# Reload configuration
reload_diagnostic_config()
print("✅ Configuration reloaded")
```

This comprehensive guide should help you understand and customize every aspect of the diagnostic parameters system. Start with the default configuration and gradually customize it based on your specific environment and requirements.