"""Background task runner for the Maintenance tab.

Runs long operations (OHLCV download, benchmark pipeline) in a daemon thread and
captures loguru output into an in-memory ring buffer that the UI polls. Kept
deliberately simple — single concurrent task at a time.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable

from loguru import logger

_LOG_BUFFER: deque[str] = deque(maxlen=400)
_LOCK = threading.Lock()
_current: threading.Thread | None = None


def _sink(message: object) -> None:
    """loguru sink that appends formatted records to the ring buffer."""
    with _LOCK:
        _LOG_BUFFER.append(str(message).rstrip("\n"))


# Stream all loguru output into the buffer (in addition to stderr).
logger.add(_sink, level="INFO", format="{time:HH:mm:ss} | {level: <7} | {message}")


def get_log_text() -> str:
    """Return the buffered log lines as a single newline-joined string."""
    with _LOCK:
        return "\n".join(_LOG_BUFFER)


def is_running() -> bool:
    """Whether a background task is currently active."""
    return _current is not None and _current.is_alive()


def run_async(name: str, fn: Callable[[], None]) -> bool:
    """Start ``fn`` in a daemon thread if no task is running.

    Args:
        name: Human-readable task name (logged).
        fn: Zero-arg callable to run.

    Returns:
        ``True`` if started, ``False`` if a task was already running.
    """
    global _current
    if is_running():
        logger.warning("Task '{}' rejected — another task is running.", name)
        return False

    def _wrapped() -> None:
        logger.info("Task started: {}", name)
        try:
            fn()
            logger.info("Task finished: {}", name)
        except Exception as exc:  # noqa: BLE001 - surface to UI, never swallow
            logger.exception("Task '{}' failed: {}", name, exc)

    _current = threading.Thread(target=_wrapped, name=name, daemon=True)
    _current.start()
    return True
