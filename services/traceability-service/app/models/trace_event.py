import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TraceEvent(Base):
    """One event of a document, chained to the previous event of the same document.

    Each document has its own chain: `sequence` counts from 1, `previous_hash` is the `hash` of
    the previous event (or the initial hash for the first one) and `hash` is calculated from the
    content of this event plus `previous_hash`, so changing any stored event breaks every hash
    after it. See app/services/hashing.py.
    """

    __tablename__ = "trace_events"
    __table_args__ = (
        # The chain of a document has no gaps and no repeated positions. This is the last
        # defence if two events of the same document were ever saved at the same time.
        # It also serves the queries by document, so there is no separate index on document_id.
        UniqueConstraint("document_id", "sequence", name="uq_trace_events_document_sequence"),
        UniqueConstraint("source_message_id", name="uq_trace_events_source_message_id"),
        CheckConstraint("sequence >= 1", name="ck_trace_events_sequence_positive"),
        CheckConstraint("length(hash) = 64", name="ck_trace_events_hash_length"),
        CheckConstraint("length(previous_hash) = 64", name="ck_trace_events_previous_hash_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The document the event is about. It lives in another service's schema, so it is not a
    # foreign key: services only share ids, never tables.
    document_id: Mapped[uuid.UUID]
    sequence: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(100))
    # When it happened (the source's clock), as opposed to `created_at`, when it was recorded.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    previous_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    # Id of the Redis stream entry the event came from. A message can be delivered twice (the
    # consumer may crash before acknowledging it), and this makes recording it idempotent.
    # Events that do not come from the stream (the endpoint) leave it empty.
    source_message_id: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
