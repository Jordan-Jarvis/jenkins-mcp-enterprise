"""Simplified server registration using standardized tools"""

import argparse
import sys
from pathlib import Path
from typing import Dict

import yaml
from mcp.server.fastmcp import FastMCP

# Add an early stderr print to see if the script starts and stderr is captured.
print("jenkins_mcp_enterprise.PY: Script execution started.", file=sys.stderr)
sys.stderr.flush()

from .config import (
    CacheConfig,
    CleanupConfig,
    JenkinsConfig,
    MCPConfig,
    ServerConfig,
    VectorConfig,
)

# Import explicit dependency injection components
from .di_container import DIContainer
from .logging_config import setup_logging
from .tool_factory import ToolFactory

# Global variables for dependency injection (initialized in main)
container = None
tool_instances = None
mcp = None


def create_server(config=None, config_file_path=None) -> FastMCP:
    """Create and configure the MCP server"""
    # Setup logging
    setup_logging()

    # Initialize dependencies
    container = DIContainer(config, config_file_path)
    tool_factory = ToolFactory(container)
    tools = tool_factory.create_tools()

    # Create FastMCP server with settings for HTTP transport
    mcp = FastMCP("Jenkins MCP Server")
    
    # Configure host/port for HTTP transports via settings
    import os
    if os.environ.get('UVICORN_HOST'):
        mcp.settings.host = os.environ.get('UVICORN_HOST', '0.0.0.0')
    if os.environ.get('UVICORN_PORT'):
        mcp.settings.port = int(os.environ.get('UVICORN_PORT', 8000))
    
    # Add health check endpoint for Docker health checks
    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request):
        from starlette.responses import PlainTextResponse
        return PlainTextResponse("OK")

    # Get multi-Jenkins manager for roots support
    multi_jenkins_manager = container.get_multi_jenkins_manager()

    # Register MCP resources for Jenkins URL mapping
    register_jenkins_resources(mcp, multi_jenkins_manager)

    # Register tools using their standardized interface
    for tool in tools.values():
        register_tool_with_mcp(mcp, tool)

    return mcp


def register_jenkins_resources(mcp: FastMCP, multi_jenkins_manager) -> None:
    """Register MCP resources for Jenkins URL to credentials mapping"""

    @mcp.resource("jenkins://info")
    def jenkins_instances_info() -> dict:
        """Lists all available Jenkins instances with their URLs and descriptions"""
        instances = {}
        for instance_id, config in multi_jenkins_manager.instances_config.items():
            instances[instance_id] = {
                "url": config.url,
                "display_name": config.display_name or instance_id,
                "description": config.description or f"Jenkins instance: {config.url}",
                "username": config.username,
            }
        return {
            "available_instances": instances,
            "total": len(instances),
            "usage": "Reference Jenkins instances by URL - credentials will be automatically resolved",
        }

    @mcp.resource("jenkins://resolve/{url}")
    def resolve_jenkins_url(url: str) -> dict:
        """Resolves a Jenkins URL to find the corresponding instance configuration"""
        # Clean up the URL (remove trailing slashes, normalize)
        clean_url = url.rstrip("/")
        if not clean_url.startswith(("http://", "https://")):
            clean_url = f"https://{clean_url}"

        # Find matching instance
        for instance_id, config in multi_jenkins_manager.instances_config.items():
            config_url = config.url.rstrip("/")
            if clean_url == config_url:
                return {
                    "instance_id": instance_id,
                    "url": config.url,
                    "display_name": config.display_name or instance_id,
                    "description": config.description,
                    "username": config.username,
                    "has_credentials": bool(config.token),
                    "status": "configured",
                }

        return {
            "instance_id": None,
            "url": clean_url,
            "status": "not_configured",
            "message": f"No credentials configured for {clean_url}",
            "available_instances": list(multi_jenkins_manager.instances_config.keys()),
        }


def register_tool_with_mcp(mcp: FastMCP, tool) -> None:
    """Register a standardized tool with FastMCP"""

    # Create wrapper function that matches FastMCP's expected signature
    # Instead of **kwargs, we need to create a function with the exact parameters

    # Build function signature dynamically
    def create_tool_wrapper():
        # Create a function string that FastMCP can properly inspect
        # Separate required and optional parameters to ensure correct ordering
        required_params = []
        optional_params = []

        for param in tool.parameters:
            param_str = f"{param.name}: {param.param_type.__name__}"
            if param.required:
                required_params.append(param_str)
            else:
                if param.default is not None:
                    param_str += f" = {repr(param.default)}"
                else:
                    param_str += " = None"
                optional_params.append(param_str)

        # Combine with required params first, optional params last
        params = required_params + optional_params

        func_signature = f"async def tool_wrapper({', '.join(params)}):"

        # Create the function code
        kwargs_assignments = "\n".join(
            [f"    kwargs['{param.name}'] = {param.name}" for param in tool.parameters]
        )

        func_code = f"""{func_signature}
    # Build kwargs dict from individual parameters
    kwargs = {{}}
{kwargs_assignments}
    
    # Execute the tool
    result = tool.execute(**kwargs)
    if result.success:
        return result.data
    else:
        raise Exception(f"{{result.error_type}}: {{result.error_message}}")
"""

        # Create local namespace with tool reference
        namespace = {"tool": tool}

        # Execute the function definition
        exec(func_code, namespace)

        return namespace["tool_wrapper"]

    # Create the wrapper function
    tool_wrapper = create_tool_wrapper()

    # Set function name and docstring
    tool_wrapper.__name__ = tool.name
    tool_wrapper.__doc__ = tool.description

    # Register with MCP using the decorator
    mcp.tool(tool.name, tool.description)(tool_wrapper)


# Legacy function for backwards compatibility
def initialize_server():
    """Legacy initialization function for backwards compatibility"""
    global container, tool_instances, mcp

    # Initialize dependency injection container and create tools
    container = DIContainer()
    tool_factory = ToolFactory(container)
    tool_instances = tool_factory.create_tools()

    # Start cleanup manager after all dependencies are initialized
    container.start_cleanup_scheduler()

    # Create the standardized server
    mcp = create_server()


def load_config_from_yaml(config_path: str) -> MCPConfig:
    """Load configuration from YAML file"""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_file, "r") as f:
        config_data = yaml.safe_load(f)

    # Extract default instance for backward compatibility
    default_inst = config_data.get("default_instance", {})
    jenkins_config = JenkinsConfig(
        url=default_inst.get("url", ""),
        username=default_inst.get("username", ""),
        token=default_inst.get("token", ""),
        timeout=default_inst.get("timeout", 30),
        verify_ssl=default_inst.get("verify_ssl", True),
    )

    # Extract other configs
    vector_data = config_data.get("vector", {})
    vector_config = VectorConfig(
        host=vector_data.get(
            "host", vector_data.get("qdrant_host", "http://localhost:6333")
        ),
        collection_name=vector_data.get("collection_name", "jenkins-logs"),
        embedding_model=vector_data.get("embedding_model", "all-MiniLM-L6-v2"),
        chunk_size=vector_data.get("chunk_size", 50),
        chunk_overlap=vector_data.get("chunk_overlap", 5),
        top_k_default=vector_data.get("top_k_default", 5),
        timeout=vector_data.get("timeout", 30),
    )

    cache_data = config_data.get("cache", {})
    cache_config = CacheConfig(
        base_dir=Path(cache_data.get("cache_dir", "/tmp/mcp-jenkins")),
        max_size_mb=cache_data.get("max_size_mb", 1000),
        retention_days=cache_data.get("retention_days", 7),
        enable_compression=cache_data.get("compression", True),
    )

    server_data = config_data.get("server", {})
    server_config = ServerConfig(
        transport=server_data.get("transport", "stdio"),
        log_level=server_data.get("log_level", "INFO"),
        log_file=server_data.get("log_file", ""),
    )

    cleanup_data = config_data.get("cleanup", {})
    cleanup_config = CleanupConfig(
        schedule_interval_hours=cleanup_data.get("interval_hours", 24),
        retention_days=cleanup_data.get("retention_days", 7),
        max_concurrent_cleanups=cleanup_data.get("max_concurrent", 5),
    )

    return MCPConfig(
        jenkins=jenkins_config,
        cache=cache_config,
        vector=vector_config,
        server=server_config,
        cleanup=cleanup_config,
    )


def main():
    """Main entry point"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Jenkins MCP Server")
    parser.add_argument("--config", type=str, help="Path to YAML configuration file")
    parser.add_argument(
        "--diagnostic-config",
        type=str,
        help="Path to diagnostic parameters YAML file (overrides default bundled config)",
    )
    parser.add_argument(
        "--transport",
        type=str,
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--mount-path",
        type=str,
        default="/mcp",
        help="Mount path for HTTP transports (default: /mcp)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transports (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host for HTTP transports (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    print(
        f"Initializing Jenkins MCP Server (FastMCP) with {args.transport} transport...",
        file=sys.stderr,
    )
    sys.stderr.flush()

    # Set diagnostic config path if provided
    if args.diagnostic_config:
        import os

        os.environ["JENKINS_MCP_DIAGNOSTIC_CONFIG"] = args.diagnostic_config
        print(
            f"Using custom diagnostic config: {args.diagnostic_config}", file=sys.stderr
        )

    # Load config if provided
    config = None
    if args.config:
        try:
            config = load_config_from_yaml(args.config)
            print(f"Loaded configuration from: {args.config}", file=sys.stderr)
        except Exception as e:
            print(f"Failed to load config from {args.config}: {e}", file=sys.stderr)
            sys.exit(1)

    server = create_server(config, args.config)

    try:
        if args.transport in ["sse", "streamable-http"]:
            print(
                f"Starting Jenkins MCP Server (FastMCP) on {args.host}:{args.port} with {args.transport} transport...",
                file=sys.stderr,
            )
            # Host/port will be passed directly to mcp.run()
        else:
            print(
                "Starting Jenkins MCP Server (FastMCP) with stdio transport...",
                file=sys.stderr,
            )

        sys.stderr.flush()
        
        # Set environment variables for HTTP transports (FastMCP reads these)
        if args.transport in ["sse", "streamable-http"]:
            import os
            os.environ["UVICORN_HOST"] = args.host
            os.environ["UVICORN_PORT"] = str(args.port)
            server.run(transport=args.transport, mount_path=args.mount_path)
        else:
            server.run(transport=args.transport, mount_path=args.mount_path)
    except KeyboardInterrupt:
        print(
            "\nJenkins MCP Server shutting down due to KeyboardInterrupt...",
            file=sys.stderr,
        )
        sys.stderr.flush()
    except EOFError:
        print(
            "Jenkins MCP Server shutting down due to EOF on stdin (e.g., client disconnected).",
            file=sys.stderr,
        )
        sys.stderr.flush()
    except BrokenPipeError:
        print(
            "Jenkins MCP Server shutting down due to BrokenPipeError (e.g., client closed connection).",
            file=sys.stderr,
        )
        try:
            sys.stderr.flush()
        except:
            pass
    except Exception as e:
        import traceback

        print(
            f"An unhandled error occurred in server.run, causing server shutdown: {e}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
    finally:
        print("Jenkins MCP Server run loop finished. Cleaning up...", file=sys.stderr)
        print("Jenkins MCP Server stopped.", file=sys.stderr)
        sys.stderr.flush()


if __name__ == "__main__":
    print("jenkins_mcp_enterprise.PY: __main__ block entered.", file=sys.stderr)
    sys.stderr.flush()
    main()
