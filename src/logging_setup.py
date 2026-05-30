"""Centralised loguru configuration.

Per CLAUDE.md coding standards: never suppress errors; log everything with
loguru. Import :func:`configure_logging` once at process entry points.
"""

from __future__ import annotations

import sys

from loguru import logger

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure the global loguru sink.

    Idempotent: repeated calls reset the single stderr sink to ``level``.

    Args:
        level: Minimum log level (e.g. ``"INFO"``, ``"DEBUG"``).
    """
    global _CONFIGURED
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        backtrace=True,
        diagnose=False,
    )
    _CONFIGURED = True
