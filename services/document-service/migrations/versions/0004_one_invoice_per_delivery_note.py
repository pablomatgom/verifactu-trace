"""one invoice per delivery note

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03 18:06:46.579374
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Partial: it only applies to invoices, so many delivery notes can share their order as parent.
    op.create_index(
        "uq_documents_one_invoice_per_delivery_note",
        "documents",
        ["parent_id"],
        unique=True,
        schema="documents",
        postgresql_where=sa.text("type = 'INVOICE'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_documents_one_invoice_per_delivery_note",
        table_name="documents",
        schema="documents",
        postgresql_where=sa.text("type = 'INVOICE'"),
    )
