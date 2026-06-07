"""Centralized logging configuration for OpenHarness."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from typing import IO


DEFAULT_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_LOG_FILE_SIZE = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5


def get_log_level_from_env(default: int = logging.INFO) -> int:
    """Get log level from environment variable OPENHARNESS_LOG_LEVEL."""
    env_val = os.environ.get("OPENHARNESS_LOG_LEVEL", "").strip().upper()
    if env_val:
        return getattr(logging, env_val, default)
    return default


def setup_logging(
    level: int | None = None,
    format: str = DEFAULT_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
    stream: IO[str] = sys.stderr,
    log_file: str | None = None,
) -> None:
    """Configure logging for OpenHarness.

    Args:
        level: Logging level (e.g., logging.DEBUG, logging.INFO).
               If None, uses OPENHARNESS_LOG_LEVEL env var or INFO.
        format: Log message format string.
        date_format: Date/time format string.
        stream: Output stream for console logging.
        log_file: Optional file path for rotating file logging.
    """
    # Determine effective log level
    effective_level = level if level is not None else get_log_level_from_env()

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(effective_level)

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(format, datefmt=date_format)

    # Console handler
    console_handler = logging.StreamHandler(stream)
    console_handler.setLevel(effective_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_FILE_SIZE,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(effective_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for noisy_logger in ["urllib3", "requests", "httpx", "asyncio"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger with the given name, using OpenHarness logging conventions.

    Args:
        name: Logger name. If None, uses the caller's module name.

    Returns:
        Configured logger instance.
    """
    return logging.getLogger(name)


def log_function_call(logger: logging.Logger, level: int = logging.DEBUG):
    """Decorator to log function calls at the specified level."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            logger.log(
                level,
                "[%s] Calling with args=%s, kwargs=%s",
                func.__name__,
                args,
                kwargs,
            )
            try:
                result = func(*args, **kwargs)
                logger.log(level, "[%s] Returned: %s", func.__name__, result)
                return result
            except Exception as e:
                logger.log(
                    logging.ERROR,
                    "[%s] Raised exception: %s",
                    func.__name__,
                    str(e),
                )
                raise

        return wrapper

    return decorator
