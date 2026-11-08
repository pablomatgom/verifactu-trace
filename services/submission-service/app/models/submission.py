import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The status is a plain string, not a PostgreSQL ENUM, for the same reason as in document-service:
# adding a value to a native ENUM needs a migration with ALTER TYPE.


class SubmissionStatus(StrEnum):
    """Where a submission to the AEAT is."""

    PENDING = "PENDING"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"


class Submission(Base):
    """The submission of one invoice to the AEAT: its state, its attempts and its last error.

    A submission is created PENDING and a background worker sends it. It becomes SENT while an
    attempt is in progress, and then ACCEPTED or REJECTED (final), RETRYING (it will be tried
    again at `next_attempt_at`) or FAILED (final: the attempts ran out).
    """

    __tablename__ = "submissions"
    __table_args__ = (
        # An invoice is submitted once, whether the event arrives twice or someone also asks for
        # it by hand. It is also what makes consuming the event idempotent.
        UniqueConstraint("invoice_id", name="uq_submissions_invoice_id"),
        CheckConstraint("attempts >= 0", name="ck_submissions_attempts_not_negative"),
        # The worker looks for the submissions that are due, by status and date.
        Index("ix_submissions_status_next_attempt_at", "status", "next_attempt_at"),
        # The list of submissions (CU-16) is ordered by creation, newest first, and the id
        # breaks the ties. A btree is read backwards just as well as forwards, so this one
        # gives the order without sorting.
        Index("ix_submissions_created_at_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The invoice lives in document-service's schema, so it is not a foreign key: services only
    # share ids, never tables.
    invoice_id: Mapped[uuid.UUID]
    # Known when the submission comes from the event; empty when it is requested by hand.
    invoice_number: Mapped[str | None] = mapped_column(String(40), default=None)
    status: Mapped[str] = mapped_column(String(20), default=SubmissionStatus.PENDING)
    attempts: Mapped[int] = mapped_column(default=0)
    # When the worker may try it next. Empty once the submission is final.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Why the last attempt failed or was rejected, as a code such as AEAT_UNAVAILABLE.
    last_error: Mapped[str | None] = mapped_column(String(100), default=None)
    # What the AEAT answered when it accepted the invoice.
    aeat_reference: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
