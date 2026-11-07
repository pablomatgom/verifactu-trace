"""index the columns of the list of documents

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-07 00:06:40.361746
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The columns the list of documents (CU-5) filters by. type and customer_tax_id have one already.
    op.create_index(
        "ix_documents_issue_date", "documents", ["issue_date"], unique=False, schema="documents"
    )
    op.create_index(
        "ix_documents_series", "documents", ["series"], unique=False, schema="documents"
    )
    op.create_index(
        "ix_documents_status", "documents", ["status"], unique=False, schema="documents"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_documents_status", table_name="documents", schema="documents")
    op.drop_index("ix_documents_series", table_name="documents", schema="documents")
    op.drop_index("ix_documents_issue_date", table_name="documents", schema="documents")
