"""create submissions table

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05 00:40:37.851433
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_number", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("aeat_reference", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_submissions_attempts_not_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_id", name="uq_submissions_invoice_id"),
        schema="submissions",
    )
    op.create_index(
        "ix_submissions_status_next_attempt_at",
        "submissions",
        ["status", "next_attempt_at"],
        unique=False,
        schema="submissions",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_submissions_status_next_attempt_at", table_name="submissions", schema="submissions"
    )
    op.drop_table("submissions", schema="submissions")
