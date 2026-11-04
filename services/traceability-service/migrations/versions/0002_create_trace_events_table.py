"""create trace_events table

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04 00:02:07.494480
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "trace_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("source_message_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(hash) = 64", name="ck_trace_events_hash_length"),
        sa.CheckConstraint(
            "length(previous_hash) = 64", name="ck_trace_events_previous_hash_length"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_trace_events_sequence_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "sequence", name="uq_trace_events_document_sequence"),
        sa.UniqueConstraint("source_message_id", name="uq_trace_events_source_message_id"),
        schema="traceability",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("trace_events", schema="traceability")
