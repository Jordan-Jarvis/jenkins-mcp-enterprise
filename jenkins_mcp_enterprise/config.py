"""Centralized configuration management for Jenkins MCP Server"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .exceptions import ConfigurationError
from .logging_config import get_component_logger

logger = get_component_logger("config")


@dataclass
class JenkinsConfig:
    """Jenkins server configuration"""

    url: str
    username: str
    token: Optional[str] = None
    timeout: int = 30
    verify_ssl: bool = True

    def __post_init__(self):
        if not self.url:
            raise ConfigurationError("Jenkins URL is required")
        if not self.username:
            raise ConfigurationError("Jenkins username is required")
        if not self.url.startswith(("http://", "https://")):
            raise ConfigurationError("Jenkins URL must start with http:// or https://")


@dataclass
class CacheConfig:
    """Cache configuration"""

    base_dir: Path = field(default_factory=lambda: Path("/tmp/mcp-jenkins"))
    max_size_mb: int = 1000
    retention_days: int = 7
    enable_compression: bool = True

    def __post_init__(self):
        if self.max_size_mb <= 0:
            raise ConfigurationError("Cache max size must be positive")
        if self.retention_days <= 0:
            raise ConfigurationError("Cache retention days must be positive")


@dataclass
class VectorConfig:
    """Vector store configuration for Qdrant"""

    host: str = "http://localhost:6333"
    collection_name: str = "jenkins-logs"
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 50
    chunk_overlap: int = 5
    top_k_default: int = 5
    timeout: int = 30
    disable_vector_search: bool = False

    def __post_init__(self):
        if not self.host.startswith(("http://", "https://")):
            raise ConfigurationError("Vector host must start with http:// or https://")
        if not self.collection_name:
            raise ConfigurationError("Collection name is required")
        if self.chunk_size <= 0:
            raise ConfigurationError("Chunk size must be positive")


@dataclass
class ServerConfig:
    """MCP Server configuration"""

    name: str = "Jenkins MCP Server"
    version: str = "1.0.0"
    transport: str = "stdio"
    log_level: str = "INFO"
    log_file: Optional[str] = None

    def __post_init__(self):
        valid_transports = ["stdio", "streamable-http", "sse"]
        if self.transport not in valid_transports:
            raise ConfigurationError(f"Transport must be one of: {valid_transports}")
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_log_levels:
            raise ConfigurationError(f"Log level must be one of: {valid_log_levels}")


@dataclass
class CleanupConfig:
    """Cleanup configuration"""

    schedule_interval_hours: int = 24
    retention_days: int = 7
    max_concurrent_cleanups: int = 5

    def __post_init__(self):
        if self.schedule_interval_hours <= 0:
            raise ConfigurationError("Schedule interval must be positive")
        if self.retention_days <= 0:
            raise ConfigurationError("Retention days must be positive")


@dataclass
class MCPConfig:
    """Main configuration container"""

    jenkins: JenkinsConfig
    cache: CacheConfig = field(default_factory=CacheConfig)
    vector: VectorConfig = field(default_factory=VectorConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)

    @classmethod
    def from_env(cls) -> "MCPConfig":
        """Load configuration from environment variables"""
        jenkins_config = JenkinsConfig(
            url=os.getenv("JENKINS_URL", ""),
            username=os.getenv("JENKINS_USER", ""),
            token=os.getenv("JENKINS_TOKEN"),
            timeout=int(os.getenv("JENKINS_TIMEOUT", "30")),
            verify_ssl=os.getenv("JENKINS_VERIFY_SSL", "true").lower() == "true",
        )

        cache_config = CacheConfig(
            base_dir=Path(os.getenv("CACHE_DIR", "/tmp/mcp-jenkins")),
            max_size_mb=int(os.getenv("CACHE_MAX_SIZE_MB", "1000")),
            retention_days=int(os.getenv("CACHE_RETENTION_DAYS", "7")),
            enable_compression=os.getenv("CACHE_COMPRESSION", "true").lower() == "true",
        )

        # Qdrant configuration
        vector_host = os.getenv("QDRANT_HOST", "http://localhost:6333")

        vector_config = VectorConfig(
            host=vector_host,
            collection_name=os.getenv("VECTOR_COLLECTION_NAME", "jenkins-logs"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            chunk_size=int(os.getenv("CHUNK_SIZE", "50")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "55")),
            timeout=int(os.getenv("VECTOR_TIMEOUT", "300")),
        )

        server_config = ServerConfig(
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE"),
            transport=os.getenv("MCP_TRANSPORT", "stdio"),
        )

        cleanup_config = CleanupConfig(
            schedule_interval_hours=int(os.getenv("CLEANUP_INTERVAL_HOURS", "24")),
            retention_days=int(os.getenv("CLEANUP_RETENTION_DAYS", "7")),
            max_concurrent_cleanups=int(os.getenv("MAX_CONCURRENT_CLEANUPS", "5")),
        )

        return cls(
            jenkins=jenkins_config,
            cache=cache_config,
            vector=vector_config,
            server=server_config,
            cleanup=cleanup_config,
        )

    @classmethod
    def from_file(cls, config_path: Path) -> "MCPConfig":
        """Load configuration from JSON or YAML file"""
        if not config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")

        try:
            with open(config_path, "r") as f:
                if config_path.suffix.lower() in [".yml", ".yaml"]:
                    data = yaml.safe_load(f)
                else:
                    data = json.load(f)

            # Convert nested dictionaries to config objects
            jenkins_data = data.get("jenkins", {})
            jenkins_config = JenkinsConfig(**jenkins_data)

            cache_data = data.get("cache", {})
            if "base_dir" in cache_data:
                cache_data["base_dir"] = Path(cache_data["base_dir"])
            cache_config = CacheConfig(**cache_data)

            vector_config = VectorConfig(**data.get("vector", {}))
            server_config = ServerConfig(**data.get("server", {}))
            cleanup_config = CleanupConfig(**data.get("cleanup", {}))

            return cls(
                jenkins=jenkins_config,
                cache=cache_config,
                vector=vector_config,
                server=server_config,
                cleanup=cleanup_config,
            )
        except Exception as e:
            raise ConfigurationError(
                f"Failed to load configuration from {config_path}: {e}"
            ) from e

    def validate(self) -> None:
        """Validate the entire configuration"""
        try:
            # Validation happens in __post_init__ methods
            # Additional cross-config validation can go here
            if self.cleanup.retention_days > self.cache.retention_days:
                logger.warning(
                    "Cleanup retention is longer than cache retention. "
                    "This may leave orphaned vector data."
                )
        except Exception as e:
            raise ConfigurationError(f"Configuration validation failed: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for serialization"""
        return {
            "jenkins": {
                "url": self.jenkins.url,
                "username": self.jenkins.username,
                "token": self.jenkins.token,
                "timeout": self.jenkins.timeout,
                "verify_ssl": self.jenkins.verify_ssl,
            },
            "cache": {
                "base_dir": str(self.cache.base_dir),
                "max_size_mb": self.cache.max_size_mb,
                "retention_days": self.cache.retention_days,
                "enable_compression": self.cache.enable_compression,
            },
            "vector": {
                "host": self.vector.host,
                "collection_name": self.vector.collection_name,
                "embedding_model": self.vector.embedding_model,
                "chunk_size": self.vector.chunk_size,
                "chunk_overlap": self.vector.chunk_overlap,
                "top_k_default": self.vector.top_k_default,
                "timeout": self.vector.timeout,
            },
            "server": {
                "name": self.server.name,
                "version": self.server.version,
                "transport": self.server.transport,
                "log_level": self.server.log_level,
                "log_file": self.server.log_file,
            },
            "cleanup": {
                "schedule_interval_hours": self.cleanup.schedule_interval_hours,
                "retention_days": self.cleanup.retention_days,
                "max_concurrent_cleanups": self.cleanup.max_concurrent_cleanups,
            },
        }
