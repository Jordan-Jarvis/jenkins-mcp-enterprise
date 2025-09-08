"""Configuration factory for different deployment scenarios"""

from pathlib import Path
from typing import Optional

from .config import (
    CacheConfig,
    CleanupConfig,
    JenkinsConfig,
    MCPConfig,
    ServerConfig,
    VectorConfig,
)
from .exceptions import ConfigurationError
from .logging_config import get_component_logger

logger = get_component_logger("config_factory")


class ConfigFactory:
    """Factory for creating configuration instances"""

    @staticmethod
    def create_config(
        config_file: Optional[Path] = None, use_env: bool = True
    ) -> MCPConfig:
        """
        Create configuration with the following priority:
        1. Configuration file (if provided)
        2. Environment variables (if use_env=True)
        3. Default values
        """
        if config_file:
            logger.info(f"Loading configuration from file: {config_file}")
            config = MCPConfig.from_file(config_file)
        elif use_env:
            logger.info("Loading configuration from environment variables")
            config = MCPConfig.from_env()
        else:
            raise ConfigurationError("No configuration source specified")

        config.validate()
        logger.info("Configuration loaded and validated successfully")
        return config

    @staticmethod
    def create_test_config(jenkins_config: Optional[JenkinsConfig] = None) -> MCPConfig:
        """Create a configuration suitable for testing"""
        if jenkins_config is None:
            jenkins_config = JenkinsConfig(
                url="http://test-jenkins:8080", username="test_user", token="test_token"
            )

        cache_config = CacheConfig(
            base_dir=Path("/tmp/test-mcp-jenkins"), retention_days=1
        )

        vector_config = VectorConfig(
            host="http://test-qdrant:6333",
            collection_name="test-jenkins-logs",
        )

        return MCPConfig(
            jenkins=jenkins_config, cache=cache_config, vector=vector_config
        )

    @staticmethod
    def create_development_config() -> MCPConfig:
        """Create a configuration suitable for development"""
        jenkins_config = JenkinsConfig(
            url="http://localhost:8080", username="dev_user", token="dev_token"
        )

        cache_config = CacheConfig(
            base_dir=Path("/tmp/dev-mcp-jenkins"), max_size_mb=500, retention_days=3
        )

        vector_config = VectorConfig(
            host="http://localhost:6333", collection_name="dev-jenkins-logs"
        )

        return MCPConfig(
            jenkins=jenkins_config, cache=cache_config, vector=vector_config
        )

    @staticmethod
    def create_production_config() -> MCPConfig:
        """Create a configuration suitable for production (requires environment variables)"""
        # For production, we require all configuration to come from environment
        # This ensures secrets are not hardcoded
        try:
            config = MCPConfig.from_env()
            config.validate()

            # Additional production-specific validation
            if not config.jenkins.token:
                raise ConfigurationError("Jenkins token is required for production")
            if config.jenkins.url.startswith("http://localhost"):
                raise ConfigurationError("Production cannot use localhost Jenkins URL")
            if config.vector.host.startswith("http://localhost"):
                logger.warning(
                    "Production is using localhost vector store - this may not be intended"
                )

            return config
        except Exception as e:
            raise ConfigurationError(f"Production configuration failed: {e}")

    @staticmethod
    def merge_configs(base_config: MCPConfig, override_config: MCPConfig) -> MCPConfig:
        """Merge two configurations, with override_config taking precedence"""
        # This is useful for situations where you want to start with a base
        # configuration and override specific values
        merged_dict = base_config.to_dict()
        override_dict = override_config.to_dict()

        # Deep merge the dictionaries
        def deep_merge(base: dict, override: dict) -> dict:
            result = base.copy()
            for key, value in override.items():
                if (
                    key in result
                    and isinstance(result[key], dict)
                    and isinstance(value, dict)
                ):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        merged_dict = deep_merge(merged_dict, override_dict)

        # Recreate the configuration from the merged dictionary
        jenkins_config = JenkinsConfig(**merged_dict["jenkins"])

        cache_data = merged_dict["cache"]
        cache_data["base_dir"] = Path(cache_data["base_dir"])
        cache_config = CacheConfig(**cache_data)

        vector_config = VectorConfig(**merged_dict["vector"])
        server_config = ServerConfig(**merged_dict["server"])
        cleanup_config = CleanupConfig(**merged_dict["cleanup"])

        merged_config = MCPConfig(
            jenkins=jenkins_config,
            cache=cache_config,
            vector=vector_config,
            server=server_config,
            cleanup=cleanup_config,
        )

        merged_config.validate()
        return merged_config
