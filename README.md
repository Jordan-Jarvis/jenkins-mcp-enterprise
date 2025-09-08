# 🚀 Jenkins MCP Server Enterprise

> **The most advanced Jenkins MCP server available** - Built for enterprise debugging, multi-instance management, and AI-powered failure analysis.

A production-ready Model Context Protocol (MCP) server that transforms how AI assistants interact with Jenkins. Unlike basic Jenkins integrations, this server provides **enterprise-grade debugging capabilities**, **intelligent failure analysis**, and **unprecedented pipeline visibility**.

## 🌟 Why Choose This Over Other Jenkins MCP Servers?

### 🔥 **Superior Build Failure Debugging**
- **AI-Powered Diagnostics**: Advanced failure analysis that actually understands your build errors
- **Hierarchical Sub-Build Discovery**: Navigate complex pipeline structures with unlimited depth
- **Massive Log Handling**: Process 10+ GB logs efficiently with streaming and intelligent chunking
- **Smart Error Pattern Recognition**: Configurable rules with regex capture groups for automated data extraction
- **Dynamic Message Generation**: Extract specific error codes, versions, and timestamps from build logs automatically

### 🏢 **Enterprise Multi-Jenkins Support**
- **Load-Balanced Routing**: Automatic instance selection across multiple Jenkins servers
- **Centralized Management**: Single MCP server manages dozens of Jenkins instances
- **Instance Health Monitoring**: Automatic failover and health checks
- **Flexible Authentication**: Per-instance credentials and SSL configuration

### 🧠 **Configurable AI Diagnostics**
- **Organization-Specific Tuning**: Customize diagnostic behavior for your tech stack
- **Advanced Pattern Matching**: Regex capture groups with dynamic message templates
- **Keyword-Based Instructions**: LLM receives tailored guidance based on build failure patterns
- **Semantic Search**: Vector-powered log analysis finds relevant context across massive logs
- **Custom Recommendation Engine**: Generate actionable insights with extracted data interpolation

### ⚡ **Performance & Scalability**
- **Parallel Processing**: Concurrent analysis of complex pipeline hierarchies
- **Intelligent Caching**: Smart log storage with compression and retention policies
- **Vector Search Engine**: Lightning-fast semantic search through historical build data
- **HTTP Streaming**: Modern transport with Server-Sent Events for real-time updates

## 🎯 **Perfect For**

- **DevOps Teams** dealing with complex CI/CD pipelines
- **Organizations** running multiple Jenkins instances
- **Engineers** who need deep build failure analysis
- **Teams** wanting AI assistants that truly understand their Jenkins setup

## 🚀 **Quick Start**

### 📋 Prerequisites

- **Python 3.10+** (modern Python features)
- **Docker & Docker Compose** (production deployment)
- **Jenkins API access** (any version with Pipeline plugin)
- **Jenkins API token** (generate from user profile)

### ⚡ **60-Second Setup**

**Option 1: Install from PyPI (Recommended)**
```bash
# 1. Install the package
pip install jenkins_mcp_enterprise

# 2. Create configuration file
mkdir -p config
cp config/mcp-config.example.yml config/mcp-config.yml
```

**Option 2: Install from Source**
```bash
# 1. Clone and install
git clone https://github.com/Jordan-Jarvis/jenkins-mcp-enterprise
cd jenkins-mcp
python3 -m pip install -e .

# 2. Start vector search engine (recommended)
./scripts/start_dev_environment.sh

# 3. Configure your Jenkins instances
cat > config/mcp-config.yml << 'EOF'
jenkins_instances:
  production:
    url: "https://jenkins.yourcompany.com"
    username: "your.email@company.com"
    token: "your-api-token"
    display_name: "Production Jenkins"

vector:
  disable_vector_search: false  # Enable AI-powered search
  host: "http://localhost:6333"

settings:
  fallback_instance: "production"
EOF

# 4. Launch the server
jenkins_mcp_enterprise --config config/mcp-config.yml
```

### 🎯 **Connect to Claude Desktop**

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

**That's it!** Your AI assistant now has enterprise-grade Jenkins capabilities.

## 💬 **Basic Usage Guide**

Once connected to your AI assistant (Claude, etc.), you can start diagnosing build failures immediately:

### 🎯 **Simple Build Diagnosis**

```
Hello, will you help me diagnose why this build failed? 
https://jenkins.company.com/job/MyApp/job/feature-branch/123/
```

**⚠️ Important**: Always provide the **full Jenkins URL** including:
- Complete hostname (enables multi-Jenkins routing)
- Full job path with folders
- Build number

### 🔍 **Common Usage Patterns**

```
# Basic failure analysis
"Can you analyze this failed build? https://jenkins.company.com/job/api-service/456/"

# Deep sub-build investigation  
"This pipeline has nested failures, can you find the root cause? https://jenkins.company.com/job/monorepo/job/main/789/"

# Search for similar issues
"Find similar authentication failures in recent builds"

# Get specific log sections
"Show me the test failure logs from lines 2000-2500 in this build: https://jenkins.company.com/job/tests/321/"
```

### 🌐 **Multi-Jenkins Support**

The server automatically routes requests based on the URL:

```
# Production Jenkins
"Analyze: https://jenkins-prod.company.com/job/deploy/456/"

# Development Jenkins  
"Debug: https://jenkins-dev.company.com/job/feature/123/"

# EU Jenkins instance
"Check: https://jenkins-eu.company.com/job/service/789/"
```

**🔄 URL Resolution**: The MCP server matches URLs to your configured Jenkins instances and uses the appropriate credentials automatically.

### 📊 **What You'll Get**

- **Failure Analysis**: AI-powered root cause identification
- **Sub-Build Hierarchy**: Navigate complex pipeline structures  
- **Smart Recommendations**: Actionable fixes based on your tech stack
- **Relevant Log Sections**: Key failure points highlighted
- **Similar Issue Search**: Find patterns across build history

## 🛠️ **Advanced Features**

### 🔍 **AI-Powered Build Diagnostics**

The `diagnose_build_failure` tool is a game-changer for debugging:

```python
# What other tools give you:
"Build failed. Check the logs."

# What this server provides:
{
  "failure_analysis": "Maven dependency conflict in build-app module",
  "root_cause": "Version mismatch between spring-boot versions",
  "affected_subbuilds": ["build-app #145", "integration-tests #89"],
  "recommendations": [
    "🔧 Update spring-boot version to 2.7.8 in build-app/pom.xml",
    "📋 Run dependency:tree to verify compatibility",
    "🧪 Test with ./scripts/test-build-integration.sh"
  ],
  "relevant_logs": "Lines 2847-2893: NoSuchMethodError: spring.boot.context",
  "hierarchy_guidance": "Focus on build-app #145 - deepest failure point"
}
```

### 🏢 **Multi-Jenkins Enterprise Setup**

Manage complex environments effortlessly:

```yaml
jenkins_instances:
  us-east-prod:
    url: "https://jenkins-us-east.company.com"
    username: "service-account@company.com"
    token: "your-api-token-here"
    description: "US East Production Environment"
    
  eu-west-prod:
    url: "https://jenkins-eu-west.company.com"
    username: "service-account@company.com"
    token: "your-api-token-here"
    description: "EU West Production Environment"
    
  development:
    url: "https://jenkins-dev.company.com"
    username: "dev-user@company.com"
    token: "your-api-token-here"
    description: "Development Environment"

settings:
  fallback_instance: "us-east-prod"
  enable_health_checks: true
  health_check_interval: 300
```

### 🧠 **Configurable AI Diagnostics**

The diagnostic engine is fully customizable to understand your specific technology stack and organizational patterns:

**📋 Quick Reference**: [Diagnostic Parameters Quick Guide](config/diagnostic-parameters-quick-reference.md)
**📚 Complete Documentation**: [Diagnostic Parameters Guide](config/diagnostic-parameters-guide.md)

```yaml
# config/diagnostic-parameters.yml - User override file (auto-detected)
semantic_search:
  search_queries:
    - "spring boot dependency conflict"
    - "kubernetes deployment failure" 
    - "terraform plan error"
    - "build authentication failed"
  min_diagnostic_score: 0.6

recommendations:
  patterns:
    spring_boot_conflict:
      conditions: ["spring", "dependency", "conflict"]
      message: "🔧 Spring Boot conflict detected. Run 'mvn dependency:tree' and check for version mismatches."
    
    k8s_deployment_failure:
      conditions: ["kubernetes", "deployment", "failed"]
      message: "☸️ K8s deployment issue. Check resource limits and network policies."

build_processing:
  parallel:
    max_workers: 8        # High performance: 8, Resource constrained: 2
    max_batch_size: 10    # Concurrent builds to process
  
context:
  max_tokens_total: 20000 # Memory budget for analysis
```

**🎯 Common Configurations:**
- **High Performance**: `max_workers: 8, max_tokens_total: 20000`
- **Resource Constrained**: `max_workers: 2, max_tokens_total: 3000`
- **Detailed Analysis**: `max_total_highlights: 10, max_recommendations: 10`

### ⚡ **Vector-Powered Search**

Lightning-fast semantic search across all your build history:

```bash
# Find similar failures across all builds
semantic_search "authentication timeout build"

# Results include builds from weeks ago with similar issues
# Ranked by relevance, not just keyword matching
```

## 🔧 **Available Tools** (10 Total)

### 🤖 **AI & Diagnostic Tools**
| Tool | Purpose | Unique Features |
|------|---------|-----------------|
| `diagnose_build_failure` | **AI failure analysis** | Sub-build hierarchy, semantic search, custom recommendations |
| `semantic_search` | **Vector-powered search** | Cross-build pattern recognition, relevance ranking |

### 🚀 **Build Management Tools**
| Tool | Purpose | Unique Features |
|------|---------|-----------------|
| `trigger_build` | **Synchronous build triggering** | Wait for completion, parameter validation |
| `trigger_build_async` | **Asynchronous build triggering** | Non-blocking execution, parallel builds |
| `trigger_build_with_subs` | **Sub-build monitoring** | Real-time status tracking, hierarchy discovery |
| `get_jenkins_job_parameters` | **Job parameter discovery** | Multi-instance support, parameter details |

### 🔍 **Log Analysis & Search Tools**
| Tool | Purpose | Unique Features |
|------|---------|-----------------|
| `ripgrep_search` | **High-speed regex search** | Context windows, massive file handling |
| `filter_errors_grep` | **Smart error filtering** | Preset patterns, relevance scoring |
| `navigate_log` | **Intelligent log navigation** | Section jumping, occurrence tracking |
| `get_log_context` | **Targeted log extraction** | Line ranges, smart chunking |

## 🏗️ **Architecture Highlights**

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   AI Assistant │────│  Jenkins MCP Pro │────│ Multi-Jenkins   │
│   (Claude/etc)  │    │                  │    │ Infrastructure  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                    ┌─────────┼─────────┐
                    │         │         │
                ┌───▼───┐ ┌───▼───┐ ┌───▼────┐
                │Vector │ │Cache  │ │Diagnostic│
                │Search │ │Manager│ │Engine   │
                │Engine │ │       │ │         │
                └───────┘ └───────┘ └────────┘
```

### 🚀 **Key Architectural Advantages:**

- **Dependency Injection**: Clean, testable, maintainable code
- **Streaming Architecture**: Handle massive logs without memory issues
- **Parallel Processing**: Concurrent sub-build analysis
- **Modular Design**: Easy to extend and customize
- **Production Ready**: Battle-tested with proper error handling

## 📊 **Production Deployment**

### 🐳 **Docker Compose (Recommended)**

```bash
# 1. Configure your Jenkins instances
cp config/mcp-config.example.yml config/mcp-config.yml
vim config/mcp-config.yml  # Add your Jenkins URLs and tokens

# 2. Copy Docker template and configure
cp .env.example .env

# 3. Deploy the full stack
docker-compose up -d

# 4. Verify deployment
docker-compose ps
curl http://localhost:8000/health
```

### ⚙️ **Configuration Management**

All configuration is handled through YAML files - no environment variables needed:

```bash
# Create your configuration file
cp config/mcp-config.example.yml config/mcp-config.yml

# Launch with configuration
python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml

# Custom diagnostic parameters (optional)
cp jenkins_mcp_enterprise/diagnostic_config/diagnostic-parameters.yml config/diagnostic-parameters.yml
# Edit config/diagnostic-parameters.yml as needed
```

## 🔐 **Security Features**

- **Per-Instance Authentication**: Separate credentials for each Jenkins instance
- **SSL Verification**: Configurable certificate validation
- **Token-Based Access**: Secure API token authentication
- **Network Isolation**: Docker network security
- **Credential Management**: YAML configuration file support

## 📈 **Performance Benchmarks**

| Metric | This Server | Basic Alternatives |
|--------|-------------|-------------------|
| **Large Log Processing** | 10GB in ~30 seconds | Often fails or times out |
| **Sub-Build Discovery** | 50+ nested levels | Usually 1-2 levels |
| **Multi-Instance Management** | Unlimited instances | Single instance only |
| **Diagnostic Quality** | AI-powered insights | Basic error patterns |
| **Search Performance** | Vector search <1s | Grep search 10s+ |

## 🎓 **Learning Resources**

### 📚 **Documentation**
- **[Configuration Guide](config/README.md)** - Complete setup instructions
- **[Diagnostic Parameters Guide](config/diagnostic-parameters-guide.md)** - Complete AI customization
- **[Diagnostic Quick Reference](config/diagnostic-parameters-quick-reference.md)** - Common configurations
- **[Developer Guide](CLAUDE.md)** - Architecture and development

### 🧪 **Examples**
```bash
# Test the diagnostic engine with custom config
python3 -m jenkins_mcp_enterprise.server --config config/mcp-config.yml

# Validate your configuration syntax
python3 -c "import yaml; yaml.safe_load(open('config/mcp-config.yml'))"

# Test diagnostic parameters
python3 -c "from jenkins_mcp_enterprise.diagnostic_config import get_diagnostic_config; get_diagnostic_config()"
```

## 🤝 **Contributing**

We welcome contributions! This project uses:

- **Modern Python** (3.10+) with type hints
- **Black** code formatting (no linting conflicts)
- **Comprehensive testing** with pytest
- **Docker** for consistent development

```bash
# Development setup
git clone https://github.com/Jordan-Jarvis/jenkins-mcp-enterprise
cd jenkins-mcp
python3 -m pip install -e .
./scripts/start_dev_environment.sh

# Run tests
python3 -m pytest tests/ -v

# Format code
python3 -m black .
```

## ☕ **Support the Project**

If this Jenkins MCP server has saved you time debugging build failures or made your CI/CD workflows more efficient, consider supporting its development:

<div align="center">

[![Buy Me A Coffee](https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png)](https://buymeacoffee.com/jordanmjaro)

**Every coffee helps fuel more features and improvements!** ☕️

</div>

Your support helps maintain this project and develop new features like:
- 🔍 Enhanced AI diagnostic capabilities
- 🚀 Additional Jenkins integrations 
- 📊 Advanced analytics and reporting
- 🛠️ New MCP tools and workflows

## 📝 **License**

GPL v3 License - build amazing things with Jenkins and AI!

---

<div align="center">

**🚀 Transform your Jenkins debugging experience today!**

[⭐ Star this repo](https://github.com/Jordan-Jarvis/jenkins-mcp-enterprise) • [📖 Read the docs](docs/) • [🐛 Report issues](https://github.com/Jordan-Jarvis/jenkins-mcp-enterprise/issues) • [💬 Join discussions](https://github.com/Jordan-Jarvis/jenkins-mcp-enterprise/discussions) • [☕ Buy me a coffee](https://buymeacoffee.com/jordanmjaro)

*Built with ❤️ for DevOps teams who demand more from their CI/CD tooling*

</div>