"""add gateway policy decisions and transactional budget ledger

Revision ID: 20260726_0003
Revises: 20260726_0002
Create Date: 2026-07-26
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0003"
down_revision: str | None = "20260726_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("resource", sa.String(128), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_policy_decisions_run_created",
        "policy_decisions",
        ["run_id", "created_at"],
    )
    op.create_table(
        "run_budgets",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column(
            "limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "reserved",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "committed",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "budget_entries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reservation_key", sa.String(256), nullable=False, unique=True),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("actual_amount", sa.BigInteger()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_budget_entries_run_resource",
        "budget_entries",
        ["run_id", "resource"],
    )
    for table in ("model_calls", "tool_calls"):
        op.add_column(table, sa.Column("gateway_version", sa.String(32)))
        op.add_column(table, sa.Column("policy_decision_id", sa.String(64)))
        op.add_column(table, sa.Column("budget_entry_id", sa.String(64)))
        op.add_column(
            table,
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        )
    op.add_column("model_calls", sa.Column("input_tokens", sa.Integer()))
    op.add_column("model_calls", sa.Column("output_tokens", sa.Integer()))
    op.add_column("model_calls", sa.Column("total_tokens", sa.Integer()))
    op.add_column("model_calls", sa.Column("usage_estimated", sa.Boolean()))
    op.add_column("model_calls", sa.Column("cost_microunits", sa.BigInteger()))


def downgrade() -> None:
    op.drop_column("model_calls", "cost_microunits")
    op.drop_column("model_calls", "usage_estimated")
    op.drop_column("model_calls", "total_tokens")
    op.drop_column("model_calls", "output_tokens")
    op.drop_column("model_calls", "input_tokens")
    for table in ("tool_calls", "model_calls"):
        op.drop_column(table, "attempt_count")
        op.drop_column(table, "budget_entry_id")
        op.drop_column(table, "policy_decision_id")
        op.drop_column(table, "gateway_version")
    op.drop_index("ix_budget_entries_run_resource", table_name="budget_entries")
    op.drop_table("budget_entries")
    op.drop_table("run_budgets")
    op.drop_index(
        "ix_policy_decisions_run_created", table_name="policy_decisions"
    )
    op.drop_table("policy_decisions")
