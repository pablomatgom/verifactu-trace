"""create documents tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 20:35:24.224505
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
        "document_counters",
        sa.Column("series", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("series", "year"),
        schema="documents",
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("series", sa.String(length=10), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("customer_tax_id", sa.String(length=20), nullable=False),
        sa.Column("total_net", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_vat", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["documents.documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
        schema="documents",
    )
    op.create_index(
        "ix_documents_customer_tax_id",
        "documents",
        ["customer_tax_id"],
        unique=False,
        schema="documents",
    )
    op.create_index("ix_documents_type", "documents", ["type"], unique=False, schema="documents")
    op.create_table(
        "document_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_document_lines_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_document_lines_unit_price_not_negative"),
        sa.CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_document_lines_vat_rate"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="documents",
    )
    op.create_index(
        "ix_document_lines_document_id",
        "document_lines",
        ["document_id"],
        unique=False,
        schema="documents",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_document_lines_document_id", table_name="document_lines", schema="documents")
    op.drop_table("document_lines", schema="documents")
    op.drop_index("ix_documents_type", table_name="documents", schema="documents")
    op.drop_index("ix_documents_customer_tax_id", table_name="documents", schema="documents")
    op.drop_table("documents", schema="documents")
    op.drop_table("document_counters", schema="documents")
