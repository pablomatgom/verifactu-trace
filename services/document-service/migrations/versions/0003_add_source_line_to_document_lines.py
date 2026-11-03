"""add source line to document lines

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03 14:01:18.779313
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "document_lines", sa.Column("source_line_id", sa.Uuid(), nullable=True), schema="documents"
    )
    op.create_index(
        "ix_document_lines_source_line_id",
        "document_lines",
        ["source_line_id"],
        unique=False,
        schema="documents",
    )
    # The constraint has a name so that downgrade can drop it.
    op.create_foreign_key(
        "fk_document_lines_source_line_id",
        "document_lines",
        "document_lines",
        ["source_line_id"],
        ["id"],
        source_schema="documents",
        referent_schema="documents",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_document_lines_source_line_id", "document_lines", schema="documents", type_="foreignkey"
    )
    op.drop_index(
        "ix_document_lines_source_line_id", table_name="document_lines", schema="documents"
    )
    op.drop_column("document_lines", "source_line_id", schema="documents")
