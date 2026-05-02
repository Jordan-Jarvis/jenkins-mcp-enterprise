"""CLI utilities for configuration management"""

import argparse
import sys
from pathlib import Path

from .config_factory import ConfigFactory
from .exceptions import ConfigurationError
from .logging_config import setup_logging


def validate_config_command(args):
    """Validate configuration file or environment variables"""
    try:
        config_file = Path(args.config) if args.config else None
        config = ConfigFactory.create_config(config_file=config_file)

        print("✓ Configuration is valid")
        print(f"  Jenkins URL: {config.jenkins.url}")
        print(f"  Jenkins User: {config.jenkins.username}")
        print(f"  Cache Directory: {config.cache.base_dir}")
        print(f"  Cache Size Limit: {config.cache.max_size_mb} MB")
        print(f"  Cache Retention: {config.cache.retention_days} days")
        print(f"  Vector Host: {config.vector.host}")
        print(f"  Vector Collection: {config.vector.collection_name}")
        print(f"  Embedding Model: {config.vector.embedding_model}")
        print(f"  Chunk Size: {config.vector.chunk_size}")
        print(f"  Server Log Level: {config.server.log_level}")
        print(f"  Cleanup Interval: {config.cleanup.schedule_interval_hours} hours")
        print(f"  Cleanup Retention: {config.cleanup.retention_days} days")

    except ConfigurationError as e:
        print(f"✗ Configuration error: {e}")
        return 1
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return 1

    return 0


def show_config_command(args):
    """Show current configuration in JSON format"""
    try:
        config_file = Path(args.config) if args.config else None
        config = ConfigFactory.create_config(config_file=config_file)

        import json

        config_dict = config.to_dict()

        # Mask sensitive information
        if config_dict.get("jenkins", {}).get("token"):
            config_dict["jenkins"]["token"] = "***MASKED***"
        if config_dict.get("vector", {}).get("api_key"):
            config_dict["vector"]["api_key"] = "***MASKED***"

        print(json.dumps(config_dict, indent=2, default=str))

    except ConfigurationError as e:
        print(f"✗ Configuration error: {e}")
        return 1
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return 1

    return 0


def check_connections_command(args):
    """Test connections to external services"""
    try:
        config_file = Path(args.config) if args.config else None
        config = ConfigFactory.create_config(config_file=config_file)

        print("Testing connections...")

        # Test Jenkins connection
        try:
            import jenkins

            j = jenkins.Jenkins(
                config.jenkins.url,
                username=config.jenkins.username,
                password=config.jenkins.token,
            )
            whoami = j.get_whoami()
            print(
                f"✓ Jenkins connection successful (user: {whoami.get('fullName', 'unknown')})"
            )
        except Exception as e:
            print(f"✗ Jenkins connection failed: {e}")

        # Test vector store connection
        try:
            import requests

            response = requests.get(f"{config.vector.host}/health", timeout=5)
            if response.status_code == 200:
                print(f"✓ Vector store connection successful")
            else:
                print(f"✗ Vector store returned status {response.status_code}")
        except Exception as e:
            print(f"✗ Vector store connection failed: {e}")

        # Test cache directory
        try:
            config.cache.base_dir.mkdir(parents=True, exist_ok=True)
            test_file = config.cache.base_dir / ".test"
            test_file.write_text("test")
            test_file.unlink()
            print(f"✓ Cache directory is writable")
        except Exception as e:
            print(f"✗ Cache directory test failed: {e}")

    except ConfigurationError as e:
        print(f"✗ Configuration error: {e}")
        return 1
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return 1

    return 0


def create_example_config_command(args):
    """Create an example configuration file"""
    try:
        config_path = Path(args.output)

        # Check if file already exists
        if config_path.exists() and not args.force:
            print(f"✗ File {config_path} already exists. Use --force to overwrite.")
            return 1

        example_config = {
            "jenkins": {
                "url": "http://jenkins.example.com:8080",
                "username": "your_username",
                "token": "your_api_token",
                "timeout": 30,
                "verify_ssl": True,
            },
            "cache": {
                "base_dir": "/tmp/mcp-jenkins",
                "max_size_mb": 1000,
                "retention_days": 7,
                "enable_compression": True,
            },
            "vector": {
                "host": "http://localhost:6333",
                "collection_name": "jenkins-logs",
                "embedding_model": "all-MiniLM-L6-v2",
                "chunk_size": 50,
                "chunk_overlap": 5,
                "top_k_default": 5,
                "timeout": 30,
            },
            "server": {
                "name": "Jenkins MCP Server",
                "version": "1.0.0",
                "transport": "stdio",
                "log_level": "INFO",
                "log_file": None,
            },
            "cleanup": {
                "schedule_interval_hours": 24,
                "retention_days": 7,
                "max_concurrent_cleanups": 5,
            },
        }

        import json

        with open(config_path, "w") as f:
            json.dump(example_config, f, indent=2)

        print(f"✓ Example configuration created at {config_path}")
        print(
            "Remember to update the Jenkins credentials and other settings as needed."
        )

    except Exception as e:
        print(f"✗ Failed to create example config: {e}")
        return 1

    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Jenkins MCP Server Configuration Tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate configuration from environment variables
  python -m jenkins_mcp_enterprise.cli validate
  
  # Validate configuration from file
  python -m jenkins_mcp_enterprise.cli validate --config config.json
  
  # Show current configuration
  python -m jenkins_mcp_enterprise.cli show --config config.json
  
  # Test connections to external services
  python -m jenkins_mcp_enterprise.cli test --config config.json
  
  # Create example configuration file
  python -m jenkins_mcp_enterprise.cli create-example --output config.json
        """,
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate configuration")
    validate_parser.add_argument("--config", help="Path to configuration file")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show current configuration")
    show_parser.add_argument("--config", help="Path to configuration file")

    # Test command
    test_parser = subparsers.add_parser(
        "test", help="Test connections to external services"
    )
    test_parser.add_argument("--config", help="Path to configuration file")

    # Create example command
    create_parser = subparsers.add_parser(
        "create-example", help="Create example configuration file"
    )
    create_parser.add_argument(
        "--output",
        "-o",
        default="config.example.json",
        help="Output file path (default: config.example.json)",
    )
    create_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing file"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)

    if args.command == "validate":
        return validate_config_command(args)
    elif args.command == "show":
        return show_config_command(args)
    elif args.command == "test":
        return check_connections_command(args)
    elif args.command == "create-example":
        return create_example_config_command(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
