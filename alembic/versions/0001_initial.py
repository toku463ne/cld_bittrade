"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-31

Creates the five core tables: ohlcv, sign_fire, sign_benchmark_run, position,
trade. Hand-written to match src/models.py.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ohlcv",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.UniqueConstraint("product", "timeframe", "timestamp", name="uq_ohlcv_bar"),
    )
    op.create_index("ix_ohlcv_product", "ohlcv", ["product"])
    op.create_index("ix_ohlcv_timeframe", "ohlcv", ["timeframe"])
    op.create_index("ix_ohlcv_timestamp", "ohlcv", ["timestamp"])

    op.create_table(
        "sign_fire",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sign_type", sa.String(length=64), nullable=False),
        sa.Column("product", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("trend_dir", sa.Integer(), nullable=True),
        sa.Column("magnitude", sa.Float(), nullable=True),
        sa.Column("signed_return", sa.Float(), nullable=True),
        sa.Column("atr_regime", sa.String(length=8), nullable=True),
    )
    op.create_index("ix_sign_fire_sign_type", "sign_fire", ["sign_type"])
    op.create_index("ix_sign_fire_product", "sign_fire", ["product"])
    op.create_index("ix_sign_fire_timeframe", "sign_fire", ["timeframe"])
    op.create_index("ix_sign_fire_fired_at", "sign_fire", ["fired_at"])

    op.create_table(
        "sign_benchmark_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sign_type", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=True),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False, server_default="pooled"),
        sa.Column("n_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dr", sa.Float(), nullable=True),
        sa.Column("mean_r", sa.Float(), nullable=True),
        sa.Column("ev", sa.Float(), nullable=True),
        sa.Column("perm_p", sa.Float(), nullable=True),
        sa.Column("sharpe", sa.Float(), nullable=True),
        sa.Column("sortino", sa.Float(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("max_dd", sa.Float(), nullable=True),
        sa.Column("total_return", sa.Float(), nullable=True),
        sa.Column("spearman_rho", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sbr_sign_type", "sign_benchmark_run", ["sign_type"])
    op.create_index("ix_sbr_strategy", "sign_benchmark_run", ["strategy"])
    op.create_index("ix_sbr_phase", "sign_benchmark_run", ["phase"])

    op.create_table(
        "position",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("size", sa.Float(), nullable=False, server_default="0.001"),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("note", sa.String(length=256), nullable=True),
    )
    op.create_index("ix_position_product", "position", ["product"])
    op.create_index("ix_position_status", "position", ["status"])

    op.create_table(
        "trade",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("size", sa.Float(), nullable=False, server_default="0.001"),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
    )
    op.create_index("ix_trade_product", "trade", ["product"])


def downgrade() -> None:
    op.drop_table("trade")
    op.drop_table("position")
    op.drop_table("sign_benchmark_run")
    op.drop_table("sign_fire")
    op.drop_table("ohlcv")
