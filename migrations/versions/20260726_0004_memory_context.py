"""add isolated memory and context manifests

Revision ID: 20260726_0004
Revises: 20260726_0003
Create Date: 2026-07-26
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0004"
down_revision: str | None = "20260726_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "tenant_id", sa.String(64), nullable=False, server_default="local"
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "user_id", sa.String(64), nullable=False, server_default="local"
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "session_id",
            sa.String(64),
            nullable=False,
            server_default="default",
        ),
    )
    op.create_table(
        "memory_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("session_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("memory_key", sa.String(64), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("source_run_id", sa.String(64)),
        sa.Column(
            "source_metadata", JSONB, nullable=False, server_default="{}"
        ),
        sa.Column(
            "explicitly_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "session_key",
            "kind",
            "memory_key",
            name="uq_memory_scope_key",
        ),
    )
    op.create_index(
        "ix_memory_scope_active",
        "memory_records",
        ["tenant_id", "user_id", "session_key", "kind", "status"],
    )
    op.create_index(
        "ix_memory_expiry", "memory_records", ["status", "expires_at"]
    )
    op.create_table(
        "memory_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("memory_id", sa.String(64)),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("session_key", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_memory_audit_scope_created",
        "memory_audit",
        ["tenant_id", "user_id", "session_key", "created_at"],
    )
    op.create_table(
        "context_manifests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("context_policy_id", sa.String(64), nullable=False),
        sa.Column("skill_versions", JSONB, nullable=False, server_default="[]"),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("included", JSONB, nullable=False, server_default="[]"),
        sa.Column("trimmed", JSONB, nullable=False, server_default="[]"),
        sa.Column("token_estimate_before", sa.Integer(), nullable=False),
        sa.Column("token_estimate_after", sa.Integer(), nullable=False),
        sa.Column("compression_ratio", sa.Float(), nullable=False),
        sa.Column("summary_id", sa.String(64)),
        sa.Column(
            "summary_depth", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("evidence_protection_hash", sa.String(64)),
        sa.Column(
            "evidence_protection_passed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("warnings", JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "run_id", "node_name", name="uq_context_manifest_run_node"
        ),
    )
    op.create_index(
        "ix_context_manifests_run",
        "context_manifests",
        ["run_id", "created_at"],
    )
    op.create_table(
        "context_summaries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("source_refs", JSONB, nullable=False, server_default="[]"),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("summary", JSONB, nullable=False),
        sa.Column("validation_passed", sa.Boolean(), nullable=False),
        sa.Column(
            "validation_errors", JSONB, nullable=False, server_default="[]"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("context_summaries")
    op.drop_index("ix_context_manifests_run", table_name="context_manifests")
    op.drop_table("context_manifests")
    op.drop_index(
        "ix_memory_audit_scope_created", table_name="memory_audit"
    )
    op.drop_table("memory_audit")
    op.drop_index("ix_memory_expiry", table_name="memory_records")
    op.drop_index("ix_memory_scope_active", table_name="memory_records")
    op.drop_table("memory_records")
    op.drop_column("runs", "session_id")
    op.drop_column("runs", "user_id")
    op.drop_column("runs", "tenant_id")
