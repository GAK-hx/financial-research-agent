"""add PostgreSQL research job queue and leases

Revision ID: 20260726_0005
Revises: 20260726_0004
Create Date: 2026-07-26
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0005"
down_revision: str | None = "20260726_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "attempt_no", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "event_sequence",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(512)),
        sa.Column("result_payload", JSONB),
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
        sa.UniqueConstraint(
            "idempotency_key", name="uq_research_jobs_idempotency_key"
        ),
    )
    op.create_index(
        "ix_research_jobs_claim",
        "research_jobs",
        ["status", "available_at", "lease_expires_at", "created_at"],
    )
    op.create_index(
        "ix_research_jobs_scope",
        "research_jobs",
        ["tenant_id", "user_id", "session_id", "created_at"],
    )
    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("research_jobs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "run_id", "sequence", name="uq_job_events_sequence"
        ),
    )
    op.create_index(
        "ix_job_events_run_created",
        "job_events",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_events_run_created", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_research_jobs_scope", table_name="research_jobs")
    op.drop_index("ix_research_jobs_claim", table_name="research_jobs")
    op.drop_table("research_jobs")
