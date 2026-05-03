[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/jordan-jarvis-jenkins-mcp-enterprise-badge.png)](https://mseep.ai/app/jordan-jarvis-jenkins-mcp-enterprise)

# Jenkins MCP Server Enterprise

> Jenkins MCP server for multi-instance routing, build diagnostics, and optional vector search.

A Model Context Protocol (MCP) server for Jenkins that provides build management, log inspection, failure diagnostics, and multi-instance configuration. The maintained setup paths in this repository are source install and Docker/Compose.

## What It Does

- Trigger builds synchronously or asynchronously
- Find jobs before triggering or inspecting them
- Inspect job definitions and source locations
- Retrieve logs and run targeted log-search tools
- Discover downstream and sub-build hierarchies
- Inspect recent builds or a window around a specific build
- Diagnose build failures with configurable recommendations
- Route each tool call to the correct Jenkins instance based on `jenkins_url`
- Expose `semantic_search` only when vector search is enabled
- Expose `apply_job_edit` only when server-side job editing is enabled

## Quick Start

### Prerequisites

- Python 3.10+
- Jenkins API access
- Jenkins username and API token
- Docker and Docker Compose if you want container deployment
- Qdrant if you want `semantic_search`

### Install from Source

```bash
git clone https://github.com/Jordan-Jarvis/jenkins-mcp-enterprise
cd jenkins-mcp-enterprise
python3 -m pip install -e .
```

### Understand the Two Config Layers

The server uses two configuration layers:

- Primary server config: `config/mcp-config.yml`
- Diagnostic config: loaded from one of:
  - `--diagnostic-config /path/to/file.yml`
  - `JENKINS_MCP_DIAGNOSTIC_CONFIG=/path/to/file.yml`
  - `config/diagnostic-parameters.yml`
  - bundled defaults in `jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml`

You always need the primary server config. You only need a project-local diagnostic config file if you want to override the bundled diagnostic defaults.

### Create the Primary Server Config

```bash
mkdir -p config
cp config/mcp-config.example.yml config/mcp-config.yml
```

Edit `config/mcp-config.yml` with your Jenkins URLs and credentials.

If you want the optional Jenkins-managed job edit workflow for non-SCM-backed jobs, also set:

```yaml
settings:
  enable_job_editing: true
  job_edit_workspace_dir: "/tmp/mcp-jenkins/job-definitions"
```

### Optional Project-Local Diagnostic Override

Create this only if you want to tune `diagnose_build_failure`:

```bash
cat > config/diagnostic-parameters.yml << 'ENDDIAG'
semantic_search:
  min_diagnostic_score: 0.65
  max_total_highlights: 4

recommendations:
  max_recommendations: 5
ENDDIAG
```

If you want semantic search, start the local vector stack and set `disable_vector_search: false` with `vector.host: "http://localhost:6333"`:

```bash
./scripts/start_dev_environment.sh
```

### Docker and Compose

```bash
cp config/mcp-config.example.yml config/mcp-config.yml
./start-jenkins_mcp_enterprise.sh
```

See [README-Docker.md](README-Docker.md) for the container deployment flow.

### Start the Server

```bash
jenkins_mcp_enterprise --config config/mcp-config.yml
```

### Connect to Claude Desktop

Add to `~/.claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jenkins": {
      "command": "jenkins_mcp_enterprise",
      "args": ["--config", "config/mcp-config.yml"]
    }
  }
}
```

## Usage Notes

- Pass full Jenkins build URLs when a tool or prompt relies on `jenkins_url`.
- In multi-Jenkins setups, each tool call resolves exactly one configured instance from `jenkins_url`. The server does not fan out across all configured Jenkins instances for a single call.
- `semantic_search` is available only when vector search is enabled.
- `apply_job_edit` is available only when `settings.enable_job_editing: true`.
- `get_job_definition` returns SCM location details for SCM-backed pipelines. For inline pipelines, it stages a local Groovy file for patch/edit/upload. For other Jenkins-managed jobs, it stages `config.xml`.
- `diagnose_build_failure` always uses a diagnostic config layer. If you do not provide a project-local override, the bundled defaults are used.
- The Docker image includes `ripgrep`, so `ripgrep_search` and `navigate_log` work in container deployments.

## Common Usage Patterns

```text
Analyze this failed build: https://jenkins.company.com/job/api-service/456/
Find the root cause in this nested pipeline: https://jenkins.company.com/job/monorepo/job/main/789/
Show me the test failure section from this build: https://jenkins.company.com/job/tests/321/
Find similar authentication failures in recent builds
```

## Available Tools

| Tool | Purpose |
|------|---------|
| `trigger_build` | Start a build and wait for completion |
| `trigger_build_async` | Queue a build without waiting for completion |
| `trigger_build_with_subs` | Trigger a build and track downstream/sub-build execution |
| `get_jenkins_job_parameters` | Inspect job parameters before triggering builds |
| `find_jobs` | Search jobs by name, path, or URL on one resolved Jenkins instance |
| `list_job_builds` | List recent builds for a job, or a small window around a target build number |
| `get_build_info` | Fetch metadata for a specific build or `lastBuild` |
| `get_job_definition` | Inspect whether a job is SCM-backed, inline, multibranch, or XML-backed |
| `ripgrep_search` | Search logs with regex and context windows |
| `filter_errors_grep` | Filter logs with common error-oriented patterns |
| `navigate_log` | Jump to sections or occurrences inside a log |
| `get_log_context` | Fetch targeted log ranges or chunks |
| `diagnose_build_failure` | AI-assisted failure diagnosis using logs, hierarchy data, and configured recommendations |
| `semantic_search` | Vector-backed similarity search across log chunks when vector search is enabled |
| `apply_job_edit` | Upload a locally edited staged job definition back to Jenkins when job editing is enabled |

## Configuration Documentation

- [Configuration Guide](config/README.md)
- [Diagnostic Config Overview](config/README-diagnostic-config.md)
- [Diagnostic Parameters Guide](config/diagnostic-parameters-guide.md)
- [Diagnostic Parameters Quick Reference](config/diagnostic-parameters-quick-reference.md)

## Development

```bash
# Start local supporting services when vector search is enabled
./scripts/start_dev_environment.sh

# Run tests
python3 -m pytest tests/ -v

# Format code
python3 -m black .
```

## License

GPL v3
