import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# The docstrings of these two enums appear in the public API documentation (/docs), so they
# describe the values for a client. Notes for developers go in comments, like this one.
#
# Orders, delivery notes and invoices share one table: the API treats them as one resource
# (`/documents`), and each one points to the previous document of the chain.
# The columns are plain strings, not a PostgreSQL ENUM: adding a value to a native ENUM needs a
# migration with ALTER TYPE, whereas here it only needs a new member.


class DocumentType(StrEnum):
    """Kind of document of the chain order -> delivery note -> invoice."""

    ORDER = "ORDER"


class DocumentStatus(StrEnum):
    """Lifecycle state of a document."""

    ISSUED = "ISSUED"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(20))
    series: Mapped[str] = mapped_column(String(10))
    # Human-readable and unique, such as P-2026-000001 (series, year, correlative number).
    number: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=DocumentStatus.ISSUED)
    issue_date: Mapped[date] = mapped_column(Date)

    customer_name: Mapped[str] = mapped_column(String(200))
    customer_tax_id: Mapped[str] = mapped_column(String(20))

    total_net: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_vat: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    # The previous document of the chain (an order has none; a delivery note points to its order).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["DocumentLine"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentLine.position",
    )

    __table_args__ = (
        Index("ix_documents_type", "type"),
        Index("ix_documents_customer_tax_id", "customer_tax_id"),
    )


class DocumentLine(Base):
    __tablename__ = "document_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    # Order of the line inside its document, starting at 1.
    position: Mapped[int]
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    document: Mapped[Document] = relationship(back_populates="lines")

    # The API validates these values too; the database is the last line of defence.
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_document_lines_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_document_lines_unit_price_not_negative"),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_document_lines_vat_rate"),
        Index("ix_document_lines_document_id", "document_id"),
    )
