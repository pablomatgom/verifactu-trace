"""order the list of documents with one index

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-07 17:27:18.321350
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # One index gives the order of the list (date, then number) and serves the filters by date, so
    # the one that only had the date is no longer needed.
    op.drop_index("ix_documents_issue_date", table_name="documents", schema="documents")
    op.create_index(
        "ix_documents_issue_date_number",
        "documents",
        ["issue_date", "number"],
        unique=False,
        schema="documents",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_documents_issue_date_number", table_name="documents", schema="documents")
    op.create_index(
        "ix_documents_issue_date",
        "documents",
        ["issue_date"],
        unique=False,
        schema="documents",
    )
