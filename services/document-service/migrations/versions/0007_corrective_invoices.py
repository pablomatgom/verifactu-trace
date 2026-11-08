"""corrective invoices

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-08 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "documents",
        sa.Column("correction_reason", sa.String(length=300), nullable=True),
        schema="documents",
    )
    # A corrective invoice takes units back, so its lines have a negative quantity. Zero is still
    # forbidden. The API keeps demanding a positive quantity in the other documents.
    op.drop_constraint(
        "ck_document_lines_quantity_positive", "document_lines", type_="check", schema="documents"
    )
    op.create_check_constraint(
        "ck_document_lines_quantity_not_zero",
        "document_lines",
        "quantity <> 0",
        schema="documents",
    )


def downgrade() -> None:
    """Downgrade schema.

    It fails if there is already a corrective invoice, whose lines have a negative quantity.
    """
    op.drop_constraint(
        "ck_document_lines_quantity_not_zero", "document_lines", type_="check", schema="documents"
    )
    op.create_check_constraint(
        "ck_document_lines_quantity_positive",
        "document_lines",
        "quantity > 0",
        schema="documents",
    )
    op.drop_column("documents", "correction_reason", schema="documents")
