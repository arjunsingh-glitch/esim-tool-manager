"""Logging setup for the Automated Tool Manager."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

DEFAULT_LOG_FILE = Path("tool_manager.log")


def setup_logger(
    name: str = "tool_manager",
    log_file: Optional[Path] = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """
    Configure and return a logger that writes to console and a log file.

    Args:
        name: Logger name.
        log_file: Path to the log file. Defaults to ``tool_manager.log`` in cwd.
        level: Minimum logging level.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_path = log_file or DEFAULT_LOG_FILE
    try:
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Could not open log file %s: %s", file_path, exc)

    return logger
