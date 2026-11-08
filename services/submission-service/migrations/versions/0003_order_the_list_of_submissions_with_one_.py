"""order the list of submissions with one index

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The list is ordered by creation (then id), newest first: the index gives that order without
    # sorting. The filter by status is served by the index of the worker, which starts with it.
    op.create_index(
        "ix_submissions_created_at_id",
        "submissions",
        ["created_at", "id"],
        unique=False,
        schema="submissions",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_submissions_created_at_id", table_name="submissions", schema="submissions")
