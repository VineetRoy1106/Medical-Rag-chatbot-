"""
Curalink — Centralized Logging
Structured logging for every pipeline stage.
Import get_logger() in any module.
"""

import logging
import sys
import os
from datetime import datetime


def get_logger(name: str) -> logging.Logger:
    """
    Returns a named logger with consistent formatting.
    Usage:
        from observability.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Stage complete", extra={"stage": "hyde", "ms": 320})
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG if os.getenv("DEBUG") else logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False

    return logger


# Module-level logger for quick use
log = get_logger("curalink")
