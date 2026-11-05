import uuid

import pytest

from app.consumer import InvalidEntry, to_submission

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


def test_an_entry_becomes_the_submission_of_the_invoice():
    data = to_submission("1730000000000-0", entry())

    assert data.invoice_id == uuid.UUID(INVOICE_ID)
    assert data.invoice_number == "F-2026-000001"


def test_the_fields_this_service_does_not_need_are_ignored():
    fields = {"invoice_id": INVOICE_ID, "number": "F-2026-000001"}

    assert to_submission("1-0", fields) == to_submission("1-0", entry())


@pytest.mark.parametrize("field", ["invoice_id", "number"])
def test_an_entry_without_a_needed_field_is_invalid(field: str):
    fields = entry()
    del fields[field]

    with pytest.raises(InvalidEntry, match=field):
        to_submission("1-0", fields)


def test_an_entry_with_an_empty_field_is_invalid():
    fields = entry(number="")

    with pytest.raises(InvalidEntry, match="number"):
        to_submission("1-0", fields)


def test_an_entry_with_an_invoice_id_that_is_not_a_uuid_is_invalid():
    fields = entry(invoice_id="not-a-uuid")

    with pytest.raises(InvalidEntry, match="cannot be read"):
        to_submission("1-0", fields)
