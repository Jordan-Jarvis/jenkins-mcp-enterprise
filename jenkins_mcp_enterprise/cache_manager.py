import re  # Added for timestamp removal
import fcntl
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from .base import Build
from .config import CacheConfig
from .logging_config import get_component_logger

if TYPE_CHECKING:
    from .jenkins.jenkins_client import JenkinsClient
    from .vector_manager import VectorManager

logger = get_component_logger("cache_manager")


class CacheManager:
    # Regex to match common timestamp patterns at the beginning of a line
    # Covers:
    #   HH:MM:SS (optional .sss)
    #   YYYY-MM-DD HH:MM:SS (optional .sss or ,sss)
    #   [YYYY-MM-DDTHH:MM:SS(.sss)Z] (ISO 8601 like)
    TIMESTAMP_REGEX = re.compile(
        r"^\d{2}:\d{2}:\d{2}(\.\d{3})?\s*|"
        r"^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:[.,]\d{3,6})?\s*|"
        r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\]\s*"
    )

    def __init__(
        self, config: CacheConfig, vector_manager: Optional["VectorManager"] = None
    ):
        """
        Initializes the CacheManager with configuration.

        Args:
            config: Cache configuration containing directory, size limits, and retention settings
            vector_manager: Optional vector manager for automatic indexing
        """
        self.config = config
        
        # Generate unique instance UUID for multiple instance support
        self.instance_uuid = str(uuid.uuid4())[:8]  # Use short UUID for readability
        
        # Create instance-specific cache directory to avoid conflicts
        self.cache_dir = config.base_dir / f"instance-{self.instance_uuid}"
        
        self.max_size_mb = config.max_size_mb
        self.retention_days = config.retention_days
        self.enable_compression = config.enable_compression
        self.vector_manager = vector_manager

        logger.info(f"Cache manager initialized with instance UUID: {self.instance_uuid}")
        logger.info(f"Cache directory: {self.cache_dir}")

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, build: Build) -> Path:
        """
        Constructs the cache path for a given build's console log.

        Args:
            build: The Build object.

        Returns:
            The Path object for the console log file.
        """
        return self.cache_dir / build.job_name / str(build.build_number) / "console.log"

    def fetch(self, client: "JenkinsClient", build: Build) -> Path:
        """
        Fetches the console log for a build, caching it if not already present.
        Uses file locking to handle concurrent access safely.
        Automatically indexes the log for vector search if vector manager is available.

        Args:
            client: The JenkinsClient instance.
            build: The Build object.

        Returns:
            The Path to the cached console log file.
        """
        log_path = self.get_path(build)
        lock_path = log_path.with_suffix('.lock')
        
        # Check if file already exists (quick check before locking)
        if log_path.exists():
            return log_path
        
        # Use file locking for concurrent access safety
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(lock_path, 'w') as lock_file:
                # Try to acquire exclusive lock with timeout
                for attempt in range(10):  # Max 10 seconds wait
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except IOError:
                        if attempt == 9:  # Last attempt
                            logger.warning(f"Could not acquire lock for {build.job_name} #{build.build_number} after 10s")
                            # Proceed without lock as fallback
                            break
                        time.sleep(1)
                
                # Double-check if file was created by another process while we waited
                if log_path.exists():
                    return log_path
                
                # Fetch and process the log
                logger.info(f"Fetching log for {build.job_name} #{build.build_number}")
                raw_console_text = client.get_console_text(
                    build.job_name, build.build_number
                )

                # Store raw logs - timestamp processing moved to analysis phase for better performance
                processed_console_text = raw_console_text

                log_path.write_text(
                    processed_console_text, encoding="utf-8"
                )

                # Automatically index the log for vector search if available and enabled
                if self.vector_manager and not getattr(self.vector_manager, 'vector_search_disabled', True):
                    try:
                        logger.info(
                            f"Auto-indexing log for vector search: {build.job_name} #{build.build_number}"
                        )
                        self.vector_manager.index_build_log(build, log_path)
                        logger.info(
                            f"Successfully indexed log: {build.job_name} #{build.build_number}"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to auto-index log for vector search: {e}")

        finally:
            # Clean up lock file
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass  # Ignore cleanup errors

        return log_path

    def read_lines(self, path: Path) -> List[str]:
        """
        Reads all lines from a given file path.

        Args:
            path: The Path object of the file to read.

        Returns:
            A list of strings, where each string is a line from the file.
        """
        return path.read_text(
            encoding="utf-8"
        ).splitlines()  # Specify encoding and use splitlines()
