import uuid
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.api.schemas.common import RequestModel, Text


class EventCreate(RequestModel):
    """The event to record in the chain of a document."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "document_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
                "event_type": "INVOICE_ISSUED",
                "occurred_at": "2026-10-14T09:30:00Z",
                "payload": {"number": "F-2026-000001", "total": "380.82"},
            }
        },
    )

    document_id: uuid.UUID = Field(description="Id of the document the event is about.")
    event_type: Text = Field(
        max_length=100, description="Kind of event, such as INVOICE_ISSUED. It is free text."
    )
    occurred_at: AwareDatetime | None = Field(
        default=None,
        description="When it happened, with its time zone. If omitted, the server uses now.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Data of the event. It is part of what the hash covers."
    )


class EventRead(BaseModel):
    """An event as it was recorded, with its position and its hashes in the chain."""

    id: uuid.UUID = Field(description="Id of the event, assigned by the server.")
    document_id: uuid.UUID = Field(description="Id of the document the event is about.")
    sequence: int = Field(description="Position in the document's chain, starting at 1.")
    event_type: str = Field(description="Kind of event.")
    occurred_at: datetime = Field(description="When it happened.")
    payload: dict[str, Any] = Field(description="Data of the event.")
    previous_hash: str = Field(
        description="Hash of the previous event of the document. For the first event, 64 zeros."
    )
    hash: str = Field(
        description="SHA-256 of the canonical content of this event followed by `previous_hash`."
    )


class EventHistory(BaseModel):
    """Every event of a document, in the order of its chain."""

    document_id: uuid.UUID = Field(description="Id of the document the events are about.")
    events: list[EventRead] = Field(
        description="The events, ordered by `sequence`: the first thing that happened first."
    )
