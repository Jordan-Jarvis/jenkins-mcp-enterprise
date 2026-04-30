#!/usr/bin/env python3
"""
Multi-Jenkins Instance Manager for MCP Roots Implementation
"""

import os
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .config import JenkinsConfig
from .exceptions import ConfigurationError
from .jenkins.jenkins_client import JenkinsClient
from .logging_config import get_component_logger

logger = get_component_logger("multi_jenkins")


@dataclass
class JenkinsInstanceConfig:
    """Configuration for a single Jenkins instance"""

    id: str
    url: str
    username: str
    token: str
    display_name: str
    description: str = ""
    timeout: int = 30
    verify_ssl: bool = True
    max_log_size: int = 100000000  # 100MB default
    default_timeout: int = 120


class MultiJenkinsManager:
    """Manages multiple Jenkins instances for MCP roots support"""

    def __init__(self, config_file: Optional[str] = None):
        # Auto-detect config file if not provided
        if config_file is None:
            # Get the project root directory (parent of jenkins_mcp_enterprise)
            project_root = Path(__file__).parent.parent

            # Try new unified config first, then fallback to old config
            mcp_config = project_root / "config" / "mcp-config.yml"
            jenkins_config = project_root / "config" / "jenkins-instances.yml"

            if mcp_config.exists():
                config_file = str(mcp_config)
            else:
                config_file = str(jenkins_config)

        self.config_file = config_file
        self.instances_config: Dict[str, JenkinsInstanceConfig] = {}
        self.clients: Dict[str, JenkinsClient] = {}
        self.active_roots: List[str] = []
        self.settings: Dict[str, Any] = {}
        self._lock = threading.Lock()

        self._load_instances_config()

    def _load_instances_config(self):
        """Load Jenkins instances configuration"""
        config_path = Path(self.config_file)

        if not config_path.exists():
            logger.warning(f"Jenkins instances config not found: {config_path}")
            self._create_default_config(config_path)

        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

                # Load global settings
                self.settings = config.get("settings", {})

                # Parse jenkins instances
                instances_raw = config.get("jenkins_instances", {})
                logger.info(f"Found {len(instances_raw)} jenkins instances in config")
                for instance_id, instance_data in instances_raw.items():
                    try:
                        # Resolve environment variables
                        resolved_config = self._resolve_env_vars(instance_data)

                        # Validate required fields before creating instance
                        if not resolved_config.get("url"):
                            logger.error(f"No URL for Jenkins instance {instance_id}")
                            continue
                        if not resolved_config.get("username"):
                            logger.error(
                                f"No username for Jenkins instance {instance_id}"
                            )
                            continue
                        if not resolved_config.get("token"):
                            logger.error(f"No token for Jenkins instance {instance_id}")
                            continue

                        # Create instance config
                        self.instances_config[instance_id] = JenkinsInstanceConfig(
                            id=instance_id,
                            url=resolved_config["url"],
                            username=resolved_config["username"],
                            token=resolved_config["token"],
                            display_name=resolved_config.get(
                                "display_name", instance_id
                            ),
                            description=resolved_config.get("description", ""),
                            timeout=resolved_config.get("timeout", 30),
                            verify_ssl=resolved_config.get("verify_ssl", True),
                            max_log_size=resolved_config.get("max_log_size", 100000000),
                            default_timeout=resolved_config.get("default_timeout", 120),
                        )

                        logger.info(
                            f"Successfully loaded Jenkins instance: {instance_id} -> {resolved_config['url']}"
                        )

                    except Exception as e:
                        logger.error(
                            f"Failed to load Jenkins instance {instance_id}: {e}"
                        )
                        continue

                # Handle default instance if present
                if "default_instance" in config:
                    default_config = self._resolve_env_vars(config["default_instance"])
                    logger.info(f"Processing default instance: {default_config}")
                    if default_config.get("url") and default_config.get("username"):
                        default_id = default_config.get("id", "default")
                        if not default_config.get("token"):
                            logger.error(
                                f"No token for default Jenkins instance: {default_config}"
                            )
                        else:
                            self.instances_config[default_id] = JenkinsInstanceConfig(
                                id=default_id,
                                url=default_config["url"],
                                username=default_config["username"],
                                token=default_config["token"],
                                display_name=default_config.get(
                                    "display_name", "Default Jenkins"
                                ),
                                description=default_config.get("description", ""),
                                timeout=default_config.get("timeout", 30),
                                verify_ssl=default_config.get("verify_ssl", True),
                            )
                            logger.info(
                                f"Successfully loaded default Jenkins instance: {default_id}"
                            )
                    else:
                        logger.warning(
                            f"Invalid default instance config: missing url or username"
                        )

                logger.info(f"Loaded {len(self.instances_config)} Jenkins instances")

        except Exception as e:
            logger.error(f"Failed to load Jenkins instances config: {e}")
            self.instances_config = {}

    def _resolve_env_vars(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve environment variables in configuration values"""
        resolved = {}

        for key, value in config_dict.items():
            if (
                isinstance(value, str)
                and value.startswith("${")
                and value.endswith("}")
            ):
                env_var = value[2:-1]  # Remove ${ and }
                resolved_value = os.getenv(env_var)
                if resolved_value is None:
                    logger.warning(
                        f"Environment variable {env_var} not set for config key {key}"
                    )
                    resolved_value = ""  # Use empty string as fallback
                resolved[key] = resolved_value
            else:
                resolved[key] = value

        return resolved

    def _create_default_config(self, config_path: Path):
        """Create a default configuration file"""
        config_path.parent.mkdir(parents=True, exist_ok=True)

        default_config = {
            "jenkins_instances": {
                "default": {
                    "url": os.getenv("JENKINS_URL", "http://localhost:8080"),
                    "username": os.getenv("JENKINS_USER", "admin"),
                    "token": "${JENKINS_TOKEN}",
                    "display_name": "Default Jenkins",
                    "description": "Default Jenkins instance",
                }
            }
        }

        with open(config_path, "w") as f:
            yaml.dump(default_config, f, default_flow_style=False)

        logger.info(f"Created default Jenkins instances config: {config_path}")

    def get_available_roots(self) -> List[Dict[str, str]]:
        """Get all available Jenkins instances as MCP roots"""
        roots = []

        for instance_id, config in self.instances_config.items():
            roots.append(
                {
                    "uri": f"jenkins://{instance_id}/",
                    "name": config.display_name or instance_id,
                    "description": config.description
                    or f"Jenkins instance at {config.url}",
                }
            )

        return roots

    def set_active_roots(self, root_uris: List[str]) -> None:
        """Set which Jenkins instances are currently active"""
        self.active_roots = []

        for root_uri in root_uris:
            if root_uri.startswith("jenkins://"):
                instance_id = root_uri.replace("jenkins://", "").rstrip("/")
                if instance_id in self.instances_config:
                    self.active_roots.append(instance_id)
                    logger.info(f"Activated Jenkins instance: {instance_id}")
                else:
                    logger.warning(f"Unknown Jenkins instance in root: {instance_id}")

        if not self.active_roots and self.instances_config:
            # Fallback to first available instance
            self.active_roots = [list(self.instances_config.keys())[0]]
            logger.info(
                f"No valid roots specified, using fallback: {self.active_roots[0]}"
            )

    @staticmethod
    def _normalize_url_path(path: str) -> str:
        """Normalize a URL path for Jenkins instance matching."""
        decoded = urllib.parse.unquote(path or "")
        if decoded in ("", "/"):
            return ""
        return decoded.rstrip("/")

    @classmethod
    def _parse_jenkins_url_for_matching(
        cls, url: str
    ) -> tuple[Optional[str], str, str]:
        """Parse a Jenkins URL or URL-like string into matchable parts."""
        decoded = urllib.parse.unquote((url or "").strip())
        if not decoded:
            raise ConfigurationError("No Jenkins URL provided")

        has_scheme = decoded.startswith(("http://", "https://"))
        parse_target = decoded if has_scheme else f"//{decoded.lstrip('/')}"
        parsed = urllib.parse.urlsplit(parse_target)
        netloc = parsed.netloc.lower()
        if not netloc:
            raise ConfigurationError(f"Invalid Jenkins URL: {url}")

        scheme = parsed.scheme.lower() if has_scheme and parsed.scheme else None
        path = cls._normalize_url_path(parsed.path)
        return scheme, netloc, path

    @classmethod
    def _candidate_base_paths(cls, path: str) -> List[str]:
        """Generate Jenkins base-path candidates from a base/job/build URL path."""
        normalized = cls._normalize_url_path(path)
        candidates: List[str] = [normalized]

        for marker in ("/job/", "/view/"):
            if marker in normalized:
                candidates.append(cls._normalize_url_path(normalized.split(marker, 1)[0]))

        if "/api/" in normalized:
            candidates.append(cls._normalize_url_path(normalized.split("/api/", 1)[0]))

        deduped: List[str] = []
        for candidate in candidates:
            if candidate not in deduped:
                deduped.append(candidate)

        return deduped

    def resolve_jenkins_url(self, url: str) -> str:
        """Resolve a Jenkins URL to an instance ID, with validation"""
        input_scheme, input_netloc, input_path = self._parse_jenkins_url_for_matching(url)
        candidate_paths = self._candidate_base_paths(input_path)
        matches: List[tuple[str, JenkinsInstanceConfig]] = []

        for instance_id, config in self.instances_config.items():
            config_scheme, config_netloc, config_path = self._parse_jenkins_url_for_matching(
                config.url
            )
            if input_netloc != config_netloc:
                continue
            if input_scheme and config_scheme and input_scheme != config_scheme:
                continue
            if config_path not in candidate_paths:
                continue
            matches.append((instance_id, config))

        if len(matches) > 1:
            available_urls = [cfg.url for _, cfg in matches]
            raise ConfigurationError(
                "Multiple Jenkins instances match URL: "
                f"{url}\nMatching Jenkins instances:\n"
                + "\n".join([f"  - {cfg_url}" for cfg_url in available_urls])
                + "\n\nSpecify the exact Jenkins base URL to disambiguate."
            )

        if len(matches) == 1:
            instance_id, config = matches[0]
            if not config.token or not config.username:
                available_urls = [cfg.url for cfg in self.instances_config.values()]
                raise ConfigurationError(
                    f"No credentials configured for Jenkins instance at {config.url}. "
                    f"Available Jenkins instances with credentials: {available_urls}"
                )
            return instance_id

        # No match found - provide helpful error
        available_urls = [cfg.url for cfg in self.instances_config.values()]
        raise ConfigurationError(
            f"No Jenkins instance configured for URL: {url}\n"
            f"Available Jenkins instances:\n"
            + "\n".join([f"  - {url}" for url in available_urls])
            + "\n\nUse one of the configured Jenkins base URLs above, or any full Jenkins "
            "job/build URL rooted under one of those bases."
        )

    def get_usage_instructions(self) -> str:
        """Get instructions for LLMs on how to specify Jenkins instances"""
        if not self.instances_config:
            return "No Jenkins instances are configured. Please configure Jenkins instances in the MCP config file."

        instances = [
            f"  - {config.url} ({config.display_name or id})"
            for id, config in self.instances_config.items()
        ]

        return (
            f"Available Jenkins instances ({len(self.instances_config)} configured):\n"
            + "\n".join(instances)
            + "\n\nPass the configured Jenkins base URL above (preferred), or a full "
            "Jenkins job/build URL rooted under one of those bases. "
            "For example: 'https://jenkins.example.com' or "
            "'https://jenkins.example.com/job/example/123/'."
        )

    def get_jenkins_client(self, instance_id: Optional[str] = None) -> JenkinsClient:
        """Get Jenkins client for specified instance or active root"""

        with self._lock:
            # Resolve instance ID
            if instance_id is None:
                if self.active_roots:
                    instance_id = self.active_roots[0]  # Use first active root
                else:
                    # Use fallback instance from settings
                    fallback = self.settings.get("fallback_instance")
                    if fallback and fallback in self.instances_config:
                        instance_id = fallback
                    elif self.instances_config:
                        instance_id = list(self.instances_config.keys())[0]
                    else:
                        raise ConfigurationError("No Jenkins instances configured")

            # Validate instance exists
            if instance_id not in self.instances_config:
                available = list(self.instances_config.keys())
                raise ConfigurationError(
                    f"Unknown Jenkins instance: {instance_id}. Available: {available}"
                )

            # Return cached client or create new one
            if instance_id not in self.clients:
                self.clients[instance_id] = self._create_client(instance_id)

            return self.clients[instance_id]

    def _create_client(self, instance_id: str) -> JenkinsClient:
        """Create a new Jenkins client for the specified instance"""
        instance_config = self.instances_config[instance_id]

        # Validate required fields
        if not instance_config.token:
            raise ConfigurationError(
                f"No token configured for Jenkins instance {instance_id}"
            )

        if not instance_config.url:
            raise ConfigurationError(
                f"No URL configured for Jenkins instance {instance_id}"
            )

        config = JenkinsConfig(
            url=instance_config.url,
            username=instance_config.username,
            token=instance_config.token,
            timeout=instance_config.timeout,
            verify_ssl=instance_config.verify_ssl,
        )

        logger.info(
            f"Created Jenkins client for instance: {instance_id} ({config.url})"
        )
        return JenkinsClient(config)

    def resolve_instance_from_uri(self, uri: str) -> str:
        """Extract Jenkins instance ID from a resource URI"""
        if uri.startswith("jenkins://"):
            # Extract instance from URI like jenkins://prod/logs/job/build
            parts = uri.replace("jenkins://", "").split("/")
            if parts:
                return parts[0]

        # Fallback to active root
        if self.active_roots:
            return self.active_roots[0]

        # Final fallback
        return (
            list(self.instances_config.keys())[0]
            if self.instances_config
            else "default"
        )

    def get_instance_info(self, instance_id: str) -> Dict[str, str]:
        """Get information about a specific Jenkins instance"""
        if instance_id not in self.instances_config:
            raise ValueError(f"Unknown Jenkins instance: {instance_id}")

        config = self.instances_config[instance_id]
        return {
            "id": instance_id,
            "url": config.url,
            "display_name": config.display_name or instance_id,
            "description": config.description or "",
            "active": str(instance_id in self.active_roots),
        }

    def health_check(self, instance_id: Optional[str] = None) -> Dict[str, bool]:
        """Check health of Jenkins instance(s)"""
        results = {}

        instances_to_check = (
            [instance_id] if instance_id else list(self.instances_config.keys())
        )

        for inst_id in instances_to_check:
            try:
                client = self.get_jenkins_client(inst_id)
                # Simple health check - get Jenkins version
                version = client.connection.client.get_version()
                results[inst_id] = bool(version)
                logger.info(
                    f"Jenkins instance {inst_id} is healthy (version: {version})"
                )
            except Exception as e:
                results[inst_id] = False
                logger.error(f"Jenkins instance {inst_id} health check failed: {e}")

        return results


# Global instance for use throughout the application
multi_jenkins_manager = None


def get_multi_jenkins_manager() -> MultiJenkinsManager:
    """Get the global multi-Jenkins manager instance"""
    if multi_jenkins_manager is None:
        raise RuntimeError(
            "MultiJenkinsManager not initialized. Use DIContainer to initialize it properly."
        )
    return multi_jenkins_manager


def set_multi_jenkins_manager(manager: MultiJenkinsManager) -> None:
    """Set the global multi-Jenkins manager instance"""
    global multi_jenkins_manager
    multi_jenkins_manager = manager
