"""Runtime configuration loaded exclusively from environment variables.

Config is provided via ``.env`` files (``.env.dev`` / ``.env.bt``) passed to
``uv run --env-file``. API keys are NEVER hardcoded. See CLAUDE.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _get_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable.

    Args:
        name: Environment variable name.
        default: Value to use when the variable is unset.

    Returns:
        The parsed boolean.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable view of the active environment configuration.

    Attributes:
        env_name: Logical environment name (``dev`` or ``bt``).
        database_url: SQLAlchemy database URL.
        use_live_api: When ``True``, real bitFlyer endpoints are used instead of
            the mock layer. Defaults to ``False`` for safety.
        allow_orders: Second, independent gate for *order placement* (beyond
            ``use_live_api``, which only enables live reads). BOTH must be true to
            send/cancel orders, and the trade CLIs still require an explicit
            ``--execute`` flag. Defaults to ``False``.
        product_code: The only traded instrument (``FX_BTC_JPY``).
        bitflyer_api_key: bitFlyer API key (only meaningful when ``use_live_api``).
        bitflyer_api_secret: bitFlyer API secret (only meaningful when ``use_live_api``).
        gmo_api_key: GMO Coin API key (leverage venue; long/short on all three assets).
        gmo_api_secret: GMO Coin API secret.
        log_level: loguru log level.
    """

    env_name: str
    database_url: str
    use_live_api: bool
    allow_orders: bool
    product_code: str
    bitflyer_api_key: str
    bitflyer_api_secret: str
    gmo_api_key: str
    gmo_api_secret: str
    log_level: str

    @property
    def is_backtest(self) -> bool:
        """Whether this is the backtest environment."""
        return self.env_name == "bt"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from the current process environment.

    Returns:
        A cached :class:`Settings` instance.

    Raises:
        RuntimeError: If ``DATABASE_URL`` is not set.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Run via "
            "`uv run --env-file .env.dev ...` or `--env-file .env.bt ...`."
        )
    return Settings(
        env_name=os.getenv("ENV_NAME", "dev"),
        database_url=database_url,
        use_live_api=_get_bool("USE_LIVE_API", default=False),
        allow_orders=_get_bool("ALLOW_ORDERS", default=False),
        product_code=os.getenv("PRODUCT_CODE", "FX_BTC_JPY"),
        bitflyer_api_key=os.getenv("BITFLYER_API_KEY", ""),
        bitflyer_api_secret=os.getenv("BITFLYER_API_SECRET", ""),
        gmo_api_key=os.getenv("GMO_API_KEY", ""),
        gmo_api_secret=os.getenv("GMO_API_SECRET", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
