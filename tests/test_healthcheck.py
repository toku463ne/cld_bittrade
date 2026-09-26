"""healthcheck.ping — a no-op when unconfigured, and never raises into the trading run."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from src.execution import healthcheck


def test_unset_url_is_a_silent_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCHECK_URL", raising=False)
    monkeypatch.setattr(healthcheck.requests, "post",
                        lambda *_a, **_k: pytest.fail("must not POST when unconfigured"))
    assert healthcheck.ping("ok") is False


def test_posts_the_summary_to_the_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, Any]] = []

    class _Resp:
        def raise_for_status(self) -> None:
            return None

    def post(url: str, data: Any = None, timeout: float = 0) -> _Resp:
        sent.append((url, data))
        assert timeout > 0, "a hung monitor must not hang the trading run"
        return _Resp()

    monkeypatch.setenv("HEALTHCHECK_URL", " https://hc-ping.com/abc \n")
    monkeypatch.setattr(healthcheck.requests, "post", post)
    assert healthcheck.ping("BTC bar_age=1.0min") is True
    assert sent == [("https://hc-ping.com/abc", b"BTC bar_age=1.0min")]


def test_a_failed_ping_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def post(*_a: Any, **_k: Any) -> Any:
        raise requests.ConnectionError("Failed to resolve 'hc-ping.com'")

    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/abc")
    monkeypatch.setattr(healthcheck.requests, "post", post)
    assert healthcheck.ping("ok") is False
