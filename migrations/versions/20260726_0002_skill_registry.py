"""add versioned skill registry and immutable run snapshots

Revision ID: 20260726_0002
Revises: 20260724_0001
Create Date: 2026-07-26
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0002"
down_revision: str | None = "20260724_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("skill_type", sa.String(32), nullable=False),
        sa.Column("owner", sa.String(100), nullable=False),
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
        "skill_versions",
        sa.Column("version_id", sa.String(96), primary_key=True),
        sa.Column(
            "skill_id",
            sa.String(64),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("supersedes", sa.String(96)),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("deprecated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_versions_identity"),
    )
    op.create_index("ix_skill_versions_status", "skill_versions", ["status"])
    op.create_table(
        "skill_reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "version_id",
            sa.String(96),
            sa.ForeignKey("skill_versions.version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_skill_reviews_version", "skill_reviews", ["version_id", "created_at"]
    )
    op.create_table(
        "skill_activations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "version_id",
            sa.String(96),
            sa.ForeignKey("skill_versions.version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_skill_activations_version",
        "skill_activations",
        ["version_id", "created_at"],
    )
    op.create_table(
        "run_skill_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_version_id", sa.String(96), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "run_id",
            "skill_version_id",
            name="uq_run_skill_snapshot_version",
        ),
        sa.UniqueConstraint(
            "run_id", "position", name="uq_run_skill_snapshot_position"
        ),
    )


def downgrade() -> None:
    op.drop_table("run_skill_snapshots")
    op.drop_index("ix_skill_activations_version", table_name="skill_activations")
    op.drop_table("skill_activations")
    op.drop_index("ix_skill_reviews_version", table_name="skill_reviews")
    op.drop_table("skill_reviews")
    op.drop_index("ix_skill_versions_status", table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_table("skills")
