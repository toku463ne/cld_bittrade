"""Dead-man's-switch ping: tell an external monitor that a run was healthy.

The auto-trader pings ``HEALTHCHECK_URL`` (e.g. a healthchecks.io check) at the end of
a run in which every book succeeded on fresh bars. The *absence* of pings is the alert:
the monitor notifies you when none arrive within its period + grace. This is the only
design that catches every silent failure. An alert sent from the box itself cannot
fire when the box has no network, which is what the 2026-09-06 to 09-21 DNS outage was:
two weeks with no orders and nothing to say so.

Unset ``HEALTHCHECK_URL`` = no-op (dev, backtests, tests).
"""

from __future__ import annotations

import os

import requests
from loguru import logger

_TIMEOUT_S = 10.0


def healthcheck_url() -> str | None:
    """The configured check URL, or None when monitoring is off."""
    url = os.environ.get("HEALTHCHECK_URL", "").strip()
    return url or None


def ping(message: str) -> bool:
    """POST one success ping carrying ``message`` as its body. Never raises.

    A failed ping is only logged. It must never cost a trading cycle, and a monitor
    that misses a ping errs toward a false alarm, which is the safe direction.

    Args:
        message: Short run summary, shown in the monitor's event log.

    Returns:
        True when the monitor accepted the ping; False when unconfigured or it failed.
    """
    url = healthcheck_url()
    if url is None:
        logger.debug("HEALTHCHECK_URL unset — no dead-man's-switch ping")
        return False
    try:
        resp = requests.post(url, data=message.encode("utf-8"), timeout=_TIMEOUT_S)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("healthcheck ping failed: {}", e)
        return False
    logger.info("healthcheck ping sent")
    return True
