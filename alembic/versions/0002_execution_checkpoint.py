"""raw executions + collection checkpoint

Revision ID: 0002_exec_ckpt
Revises: 0001_initial
Create Date: 2026-05-31

Adds the ``execution`` (raw tick) and ``collection_checkpoint`` tables that back
the resumable history extender (src/data/history.py).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_exec_ckpt"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution",
        sa.Column("product", sa.String(length=32), primary_key=True),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("exec_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("size", sa.Float(), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=True),
    )
    op.create_index("ix_execution_exec_date", "execution", ["exec_date"])

    op.create_table(
        "collection_checkpoint",
        sa.Column("product", sa.String(length=32), primary_key=True),
        sa.Column("oldest_id", sa.BigInteger(), nullable=True),
        sa.Column("newest_id", sa.BigInteger(), nullable=True),
        sa.Column("oldest_exec_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("newest_exec_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("collection_checkpoint")
    op.drop_index("ix_execution_exec_date", table_name="execution")
    op.drop_table("execution")
