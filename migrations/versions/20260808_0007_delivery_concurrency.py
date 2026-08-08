"""add multi-tenant admission, fair scheduling and provider rate windows

Revision ID: 20260808_0007
Revises: 20260808_0006
Create Date: 2026-08-08
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260808_0007"
down_revision: str | None = "20260808_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_research_jobs_idempotency_key",
        "research_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_research_jobs_tenant_idempotency_key",
        "research_jobs",
        ["tenant_id", "idempotency_key"],
    )
    op.add_column(
        "research_jobs",
        sa.Column(
            "queue_class",
            sa.String(32),
            nullable=False,
            server_default="interactive",
        ),
    )
    op.add_column(
        "research_jobs",
        sa.Column(
            "priority", sa.Integer(), nullable=False, server_default="100"
        ),
    )
    op.create_table(
        "tenant_schedule",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column(
            "claim_count", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("last_claimed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "admission_audit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("retry_after_seconds", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_admission_audit_created", "admission_audit", ["created_at"]
    )
    op.create_index(
        "ix_admission_audit_scope_created",
        "admission_audit",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_table(
        "provider_rate_windows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limited_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "provider",
            "window_started_at",
            name="uq_provider_rate_window",
        ),
    )
    op.create_index(
        "ix_provider_rate_window_started",
        "provider_rate_windows",
        ["window_started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_rate_window_started", table_name="provider_rate_windows"
    )
    op.drop_table("provider_rate_windows")
    op.drop_index(
        "ix_admission_audit_scope_created", table_name="admission_audit"
    )
    op.drop_index("ix_admission_audit_created", table_name="admission_audit")
    op.drop_table("admission_audit")
    op.drop_table("tenant_schedule")
    op.drop_column("research_jobs", "priority")
    op.drop_column("research_jobs", "queue_class")
    op.drop_constraint(
        "uq_research_jobs_tenant_idempotency_key",
        "research_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_research_jobs_idempotency_key",
        "research_jobs",
        ["idempotency_key"],
    )
