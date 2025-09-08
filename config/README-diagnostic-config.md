# Diagnostic Configuration System

## Overview

The Jenkins MCP server now uses a configurable diagnostic parameters system to eliminate hard-coded values in the `diagnose_build_failure` tool. All diagnostic behavior can now be customized through the `diagnostic-parameters.yml` configuration file.

## 📚 Documentation

- **[Complete Parameter Guide](diagnostic-parameters-guide.md)** - Comprehensive documentation with examples and real-world configurations
- **[Quick Reference](diagnostic-parameters-quick-reference.md)** - Condensed reference for common parameters and quick fixes

## Configuration File Location

- Primary: `/config/diagnostic-parameters.yml`
- Module: `jenkins_mcp_enterprise/diagnostic_config/`

## Key Configuration Sections

### Semantic Search
- Search query patterns for failure analysis
- Result limits and scoring thresholds
- Content preview lengths

### Pattern Recognition  
- Failure pattern detection rules
- Fallback analysis parameters
- Pattern matching limits

### Advanced Regex Patterns
- Regex capture groups for data extraction
- Dynamic message templates with interpolation
- Named and numbered group support
- Performance-optimized pattern compilation

### Recommendations Engine
- Pattern-based recommendation mappings with smart data extraction
- Priority job identification
- Investigation guidance text
- Template-based dynamic message generation

### Build Processing
- Parallel processing limits
- Chunk analysis parameters
- Token management

### Display and Formatting
- Hierarchy visualization settings
- Status formatting rules
- Content truncation rules

## Usage

### Default Configuration (Bundled)
The diagnostic parameters are automatically loaded from the bundled configuration:

```python
from jenkins_mcp_enterprise.diagnostic_config import get_diagnostic_config

config = get_diagnostic_config()
search_queries = config.get_semantic_search_queries()
failure_patterns = config.get_failure_patterns()
recommendations = config.get_pattern_recommendations()
```

### Custom Configuration

#### Method 1: Environment Variable
```bash
export JENKINS_MCP_DIAGNOSTIC_CONFIG="/path/to/custom-diagnostic-parameters.yml"
python3 -m jenkins_mcp_enterprise.server
```

#### Method 2: Command Line Argument
```bash
python3 -m jenkins_mcp_enterprise.server --diagnostic-config /path/to/custom-diagnostic-parameters.yml
```

#### Method 3: User Override Directory
Place your custom `diagnostic-parameters.yml` in the project's `config/` directory to automatically override the bundled defaults.

## Benefits

1. **Flexibility**: All diagnostic behavior is now configurable
2. **Maintainability**: No more hard-coded values scattered through the code
3. **Customization**: Different environments can use different diagnostic parameters
4. **Hot-reload**: Configuration can be reloaded without restart
5. **Extensibility**: Easy to add new configuration parameters

## Migration

All hard-coded values from the original `diagnose_build_failure` tool have been extracted to the YAML configuration:

- Semantic search queries (9 patterns)
- Failure pattern recognition (7 patterns) 
- Recommendation mappings (6 categories)
- **Regex pattern support** with capture groups and message templates
- Processing limits and thresholds
- Display formatting rules
- Investigation guidance text

### New Regex Pattern Features

The system now supports advanced regex patterns for automated data extraction:

- **Named Capture Groups**: Extract specific data using `(?P<name>pattern)` syntax
- **Message Templates**: Dynamic message generation with `{captured_group}` placeholders
- **Backward Compatibility**: Existing string patterns continue to work unchanged
- **Performance Optimization**: Compiled regex patterns are cached for efficiency
- **Error Handling**: Invalid patterns are logged but don't break the system

## Configuration Hot-Reload

```python
from jenkins_mcp_enterprise.diagnostic_config import reload_diagnostic_config
reload_diagnostic_config()  # Reload without server restart
```

## Next Steps

1. **Start with the [Quick Reference](diagnostic-parameters-quick-reference.md)** for immediate configuration needs
2. **Read the [Complete Guide](diagnostic-parameters-guide.md)** for detailed parameter explanations and examples
3. **Customize** your configuration based on your technology stack and environment
4. **Test** changes in a development environment before deploying to production

## Support

For questions about configuration parameters or troubleshooting, refer to the comprehensive documentation or check the debugging section in the complete guide.