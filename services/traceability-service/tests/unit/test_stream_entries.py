import uuid
from datetime import UTC, datetime

import pytest

from app.consumer import INVOICE_ISSUED_EVENT, InvalidEntry, to_event

INVOICE_ID = "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52"


def entry(**changes) -> dict[str, str]:
    """An `invoice.issued` entry as document-service publishes it."""
    fields = {
        "invoice_id": INVOICE_ID,
        "number": "F-2026-000001",
        "delivery_note_id": "9a7b2d1e-0c3f-4a55-8d1b-2f6e7c9a0b11",
        "order_id": "3f1c0b7a-5e2d-4c88-9a14-7b0d6e1f2a93",
        "total": "380.82",
        "issued_at": "2026-10-14T09:30:00+00:00",
    }
    return {**fields, **changes}


def test_an_entry_becomes_the_event_of_the_invoice():
    event = to_event("1730000000000-0", entry())

    assert event.document_id == uuid.UUID(INVOICE_ID)
    assert event.event_type == INVOICE_ISSUED_EVENT
    assert event.occurred_at == datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
    assert event.source_message_id == "1730000000000-0"


def test_the_payload_keeps_the_rest_of_the_fields_as_text():
    event = to_event("1-0", entry())

    # The invoice id is the document of the event, so it is not repeated in the payload.
    assert event.payload == {
        "number": "F-2026-000001",
        "delivery_note_id": "9a7b2d1e-0c3f-4a55-8d1b-2f6e7c9a0b11",
        "order_id": "3f1c0b7a-5e2d-4c88-9a14-7b0d6e1f2a93",
        "total": "380.82",
        "issued_at": "2026-10-14T09:30:00+00:00",
    }


@pytest.mark.parametrize(
    "field",
    ["invoice_id", "number", "delivery_note_id", "order_id", "total", "issued_at"],
)
def test_an_entry_without_a_field_is_invalid(field: str):
    fields = entry()
    del fields[field]

    with pytest.raises(InvalidEntry, match=field):
        to_event("1-0", fields)


def test_an_entry_with_an_empty_field_is_invalid():
    fields = entry(number="")

    with pytest.raises(InvalidEntry, match="number"):
        to_event("1-0", fields)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"invoice_id": "not-a-uuid"}, "cannot be read"),
        ({"issued_at": "yesterday"}, "cannot be read"),
        ({"issued_at": "2026-10-14T09:30:00"}, "time zone"),
    ],
)
def test_an_entry_with_a_value_that_cannot_be_read_is_invalid(changes: dict, reason: str):
    fields = entry(**changes)

    with pytest.raises(InvalidEntry, match=reason):
        to_event("1-0", fields)
