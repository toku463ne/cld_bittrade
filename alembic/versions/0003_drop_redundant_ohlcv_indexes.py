"""drop redundant single-column ohlcv indexes

Revision ID: 0003_ohlcv_idx
Revises: 0002_exec_ckpt
Create Date: 2026-05-31

The composite unique index uq_ohlcv_bar (product, timeframe, timestamp) already
serves every read path (filter by product+timeframe, ordered by timestamp). The
single-column indexes on product / timeframe / timestamp are redundant for reads
and only add write overhead on collection (the timeframe one is especially
useless: 4 distinct values). Drop them.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_ohlcv_idx"
down_revision: str | None = "0002_exec_ckpt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_ohlcv_product", table_name="ohlcv")
    op.drop_index("ix_ohlcv_timeframe", table_name="ohlcv")
    op.drop_index("ix_ohlcv_timestamp", table_name="ohlcv")


def downgrade() -> None:
    op.create_index("ix_ohlcv_product", "ohlcv", ["product"])
    op.create_index("ix_ohlcv_timeframe", "ohlcv", ["timeframe"])
    op.create_index("ix_ohlcv_timestamp", "ohlcv", ["timestamp"])
