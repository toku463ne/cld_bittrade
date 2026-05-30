"""SQLAlchemy ORM models (schema definition).

Schema overview:

- :class:`OHLCV`            — collected/aggregated bars per (product, timeframe).
- :class:`SignFire`         — one row per detector fire, with its measured outcome.
- :class:`SignBenchmarkRun` — aggregate benchmark results per (sign/strategy, phase).
- :class:`Position`         — manually registered live positions.
- :class:`Trade`            — closed trades (live, registered by the human).

Migrations are managed by Alembic (``alembic/``). Never create tables directly
in production code paths; run ``alembic upgrade head``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class OHLCV(Base):
    """An OHLCV bar for a product/timeframe.

    Unique on (product, timeframe, timestamp) so re-collection is idempotent.
    """

    __tablename__ = "ohlcv"
    __table_args__ = (
        UniqueConstraint("product", "timeframe", "timestamp", name="uq_ohlcv_bar"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)


class Execution(Base):
    """A raw exchange execution (tick), stored to enable resumable history.

    Keyed by ``(product, id)`` where ``id`` is bitFlyer's monotonic execution id.
    Storing raw executions lets the OHLCV builder re-aggregate the complete,
    contiguous tick set so boundary bars are always correct across separately
    fetched ranges (see :mod:`src.data.history`). Inserts are idempotent
    (on-conflict-do-nothing on the primary key).
    """

    __tablename__ = "execution"

    product: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    exec_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)


class CollectionCheckpoint(Base):
    """Resumable-collection cursors for a product's raw execution stream.

    The execution stream is timeframe-independent, so one checkpoint exists per
    product. ``oldest_id`` is the deepest (smallest) execution id collected so
    far (the backward cursor); ``newest_id`` is the most recent (largest) id
    collected (the forward cursor).
    """

    __tablename__ = "collection_checkpoint"

    product: Mapped[str] = mapped_column(String(32), primary_key=True)
    oldest_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    newest_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oldest_exec_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    newest_exec_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SignFire(Base):
    """A single detector fire with its measured forward outcome.

    Outcome fields (``trend_dir`` / ``magnitude`` / ``signed_return``) follow the
    zigzag definition in ``docs/evaluation_guide.md`` §1. They are NULL until the
    benchmark pipeline computes them.
    """

    __tablename__ = "sign_fire"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sign_type: Mapped[str] = mapped_column(String(64), index=True)
    product: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    side: Mapped[str] = mapped_column(String(8))
    score: Mapped[float] = mapped_column(Float, default=1.0)

    # Outcome (filled by the benchmark pipeline; +1 up / -1 down).
    trend_dir: Mapped[int | None] = mapped_column(Integer, nullable=True)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    signed_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr_regime: Mapped[str | None] = mapped_column(String(8), nullable=True)


class SignBenchmarkRun(Base):
    """Aggregate benchmark output for a sign/strategy under a pipeline phase.

    ``phase`` is one of ``benchmark`` / ``validate`` / ``report`` / ``backtest``
    (the latter being OOS). ``period`` is the monthly walk-forward unit (or
    ``"pooled"`` for the aggregate row).
    """

    __tablename__ = "sign_benchmark_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sign_type: Mapped[str] = mapped_column(String(64), index=True)
    strategy: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    phase: Mapped[str] = mapped_column(String(16), index=True)
    period: Mapped[str] = mapped_column(String(16), default="pooled")

    n_events: Mapped[int] = mapped_column(Integer, default=0)
    dr: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev: Mapped[float | None] = mapped_column(Float, nullable=True)
    perm_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_dd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    spearman_rho: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Position(Base):
    """A manually registered open live position (minimum lot only)."""

    __tablename__ = "position"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(32), index=True)
    strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    side: Mapped[str] = mapped_column(String(8))
    size: Mapped[float] = mapped_column(Float, default=0.001)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class Trade(Base):
    """A closed live trade, registered by the human after manual execution."""

    __tablename__ = "trade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(32), index=True)
    strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    side: Mapped[str] = mapped_column(String(8))
    size: Mapped[float] = mapped_column(Float, default=0.001)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float] = mapped_column(Float)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
