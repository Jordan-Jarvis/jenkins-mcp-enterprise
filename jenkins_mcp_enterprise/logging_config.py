"""Centralized logging configuration for Jenkins MCP Server

This module provides a standardized logging system that replaces the
scattered print statements and silent failures throughout the codebase.

Key Features:
- Consistent log formatting across all components
- Configurable log levels and output destinations
- Structured logging for better debugging
- Support for both console and file logging
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: str = "INFO", log_file: Optional[str] = None
) -> logging.Logger:
    """Setup centralized logging for Jenkins MCP Server

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for log output

    Returns:
        Configured logger instance

    Raises:
        ValueError: If invalid log level is provided
    """
    # Validate log level
    try:
        numeric_level = getattr(logging, level.upper())
    except AttributeError:
        raise ValueError(f"Invalid log level: {level}")

    logger = logging.getLogger("jenkins_mcp")
    logger.setLevel(numeric_level)

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    # Create consistent formatter for all handlers
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    )

    # Console handler (stderr to avoid interfering with MCP stdio)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        try:
            # Ensure log directory exists
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(numeric_level)
            logger.addHandler(file_handler)

            logger.info(f"File logging enabled: {log_file}")
        except Exception as e:
            logger.error(f"Failed to setup file logging to {log_file}: {e}")
            # Continue without file logging rather than failing

    # Prevent propagation to root logger to avoid duplicate messages
    logger.propagate = False

    logger.info("Jenkins MCP Server logging initialized")
    return logger


def get_component_logger(component_name: str) -> logging.Logger:
    """Get a logger for a specific component

    Args:
        component_name: Name of the component (e.g., 'jenkins_client', 'cache_manager')

    Returns:
        Logger instance for the component
    """
    return logging.getLogger(f"jenkins_mcp.{component_name}")


# NOTE: intentionally NOT calling setup_logging() here. setup_logging()
# only attaches handlers once (it returns early if the logger already has
# any), so an eager call at import time — before create_server() has a
# chance to apply the real configured log_level/log_file — would silently
# lock in the defaults and make any later, properly-configured call a no-op.
# Handlers get attached by the first real call to setup_logging(), from
# create_server().
logger = logging.getLogger("jenkins_mcp")


def configure_logging_from_env() -> logging.Logger:
    """Configure logging from environment variables

    Environment Variables:
        JENKINS_MCP_LOG_LEVEL: Log level (default: INFO)
        JENKINS_MCP_LOG_FILE: Log file path (optional)

    Returns:
        Configured logger instance
    """
    import os

    log_level = os.getenv("JENKINS_MCP_LOG_LEVEL", "INFO")
    log_file = os.getenv("JENKINS_MCP_LOG_FILE")

    return setup_logging(level=log_level, log_file=log_file)


def log_exception(
    logger_instance: logging.Logger, message: str, exc: Exception
) -> None:
    """Helper function to log exceptions with consistent formatting

    Args:
        logger_instance: Logger to use for output
        message: Descriptive message about what was being attempted
        exc: Exception that occurred
    """
    logger_instance.error(f"{message}: {exc}", exc_info=True)


def log_performance(
    logger_instance: logging.Logger, operation: str, duration: float
) -> None:
    """Helper function to log performance metrics

    Args:
        logger_instance: Logger to use for output
        operation: Description of the operation
        duration: Time taken in seconds
    """
    logger_instance.info(f"Performance: {operation} completed in {duration:.2f}s")
