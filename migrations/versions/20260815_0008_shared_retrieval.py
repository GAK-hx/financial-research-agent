"""add shared retrieval work, snapshots and validated analysis artifacts

Revision ID: 20260815_0008
Revises: 20260808_0007
Create Date: 2026-08-15
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260815_0008"
down_revision: str | None = "20260808_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retrieval_work_units",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("atomic_key", postgresql.JSONB(), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("waiter_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(256)),
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
            "key_hash", "generation", name="uq_retrieval_work_key_generation"
        ),
    )
    op.create_index(
        "ix_retrieval_work_claim",
        "retrieval_work_units",
        ["status", "lease_expires_at", "updated_at"],
    )
    op.create_index(
        "ix_retrieval_work_key",
        "retrieval_work_units",
        ["key_hash", "generation"],
    )
    op.create_table(
        "job_work_dependencies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("research_jobs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column(
            "work_unit_id",
            sa.String(64),
            sa.ForeignKey("retrieval_work_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cache_decision", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "run_id", "task_id", "work_unit_id", name="uq_job_work_dependency"
        ),
    )
    op.create_index(
        "ix_job_work_dependency_work",
        "job_work_dependencies",
        ["work_unit_id", "created_at"],
    )
    op.create_table(
        "retrieval_snapshots",
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        sa.Column(
            "work_unit_id",
            sa.String(64),
            sa.ForeignKey("retrieval_work_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("atomic_key", postgresql.JSONB(), nullable=False),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("watermark", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "key_hash", "generation", name="uq_retrieval_snapshot_generation"
        ),
    )
    op.create_index(
        "ix_retrieval_snapshot_expiry",
        "retrieval_snapshots",
        ["key_hash", "expires_at"],
    )
    op.create_table(
        "analysis_artifacts",
        sa.Column("artifact_id", sa.String(64), primary_key=True),
        sa.Column("analysis_key", sa.String(64), nullable=False),
        sa.Column("analysis_type", sa.String(64), nullable=False),
        sa.Column("subjects", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_dependencies", postgresql.JSONB(), nullable=False),
        sa.Column("skill_versions", postgresql.JSONB(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("validated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_key", name="uq_analysis_artifact_key"),
    )
    op.create_index(
        "ix_analysis_artifact_lookup",
        "analysis_artifacts",
        ["analysis_key", "validated", "expires_at"],
    )
    op.create_table(
        "artifact_dependencies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("analysis_artifacts.artifact_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            sa.String(64),
            sa.ForeignKey("retrieval_snapshots.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "artifact_id", "snapshot_id", name="uq_artifact_snapshot_dependency"
        ),
    )
    op.create_index(
        "ix_artifact_dependency_snapshot",
        "artifact_dependencies",
        ["snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_dependency_snapshot", table_name="artifact_dependencies")
    op.drop_table("artifact_dependencies")
    op.drop_index("ix_analysis_artifact_lookup", table_name="analysis_artifacts")
    op.drop_table("analysis_artifacts")
    op.drop_index("ix_retrieval_snapshot_expiry", table_name="retrieval_snapshots")
    op.drop_table("retrieval_snapshots")
    op.drop_index("ix_job_work_dependency_work", table_name="job_work_dependencies")
    op.drop_table("job_work_dependencies")
    op.drop_index("ix_retrieval_work_key", table_name="retrieval_work_units")
    op.drop_index("ix_retrieval_work_claim", table_name="retrieval_work_units")
    op.drop_table("retrieval_work_units")
