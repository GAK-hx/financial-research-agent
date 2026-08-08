"""add governed knowledge events and memory history

Revision ID: 20260808_0006
Revises: 20260726_0005
Create Date: 2026-08-08
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260808_0006"
down_revision: str | None = "20260726_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "context_manifests",
        sa.Column(
            "token_estimator_version",
            sa.String(64),
            nullable=False,
            server_default="utf8_bytes_v1",
        ),
    )
    op.create_table(
        "knowledge_source_cursors",
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("cursor_value", sa.String(512)),
        sa.Column("high_watermark", sa.DateTime(timezone=True)),
        sa.Column("source_rank", sa.Integer(), nullable=False),
        sa.Column("license_name", sa.String(128), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "knowledge_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("canonical_key", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("source_record_id", sa.String(256), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_rank", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_version", sa.String(32), nullable=False),
        sa.Column("extraction_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("raw_locator", sa.Text(), nullable=False),
        sa.Column("evidence_refs", JSONB, nullable=False, server_default="[]"),
        sa.Column("entity_evidence", JSONB, nullable=False, server_default="[]"),
        sa.Column("supersedes", sa.String(64)),
        sa.Column("conflict_group", sa.String(64)),
        sa.Column("rejection_reason", sa.String(256)),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "source_id",
            "source_record_id",
            "raw_version",
            name="uq_knowledge_event_source_version",
        ),
    )
    op.create_index(
        "ix_knowledge_events_active_symbol_time",
        "knowledge_events",
        ["status", "symbol", "published_at"],
    )
    op.create_index(
        "ix_knowledge_events_canonical",
        "knowledge_events",
        ["canonical_key", "status"],
    )
    op.create_index(
        "ix_knowledge_events_content_hash", "knowledge_events", ["content_hash"]
    )
    op.create_table(
        "knowledge_event_transitions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(64),
            sa.ForeignKey("knowledge_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_knowledge_event_transitions_event",
        "knowledge_event_transitions",
        ["event_id", "created_at"],
    )
    op.create_table(
        "memory_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("memory_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("source_run_id", sa.String(64)),
        sa.Column("source_metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("memory_id", "version", name="uq_memory_versions_identity"),
    )
    op.create_index(
        "ix_memory_versions_memory", "memory_versions", ["memory_id", "version"]
    )
    op.execute(
        """
        INSERT INTO memory_versions (
            id, memory_id, version, status, value, source_type, source_id,
            source_run_id, source_metadata, created_at
        )
        SELECT
            md5(id || ':' || version::text), id, version, status, value,
            source_type, source_id, source_run_id, source_metadata, updated_at
        FROM memory_records
        ON CONFLICT (memory_id, version) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_memory_versions_memory", table_name="memory_versions")
    op.drop_table("memory_versions")
    op.drop_index(
        "ix_knowledge_event_transitions_event",
        table_name="knowledge_event_transitions",
    )
    op.drop_table("knowledge_event_transitions")
    op.drop_index("ix_knowledge_events_content_hash", table_name="knowledge_events")
    op.drop_index("ix_knowledge_events_canonical", table_name="knowledge_events")
    op.drop_index("ix_knowledge_events_active_symbol_time", table_name="knowledge_events")
    op.drop_table("knowledge_events")
    op.drop_table("knowledge_source_cursors")
    op.drop_column("context_manifests", "token_estimator_version")
