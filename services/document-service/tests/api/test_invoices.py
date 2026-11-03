import logging
import re
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.events import INVOICE_ISSUED, EventPublishError, get_publisher
from app.main import app
from app.models import Document, DocumentType


def sequence(document: dict) -> int:
    """The correlative part of a number: F-2026-000007 -> 7."""
    return int(document["number"].rsplit("-", 1)[1])


def issue_delivery_note(client: TestClient) -> dict:
    """Register an order and deliver part of it: 4 of 10 widgets and 3 of 4 gadgets."""
    order = client.post(
        "/api/v1/orders",
        json={
            "customer": {"name": "Acme S.L.", "tax_id": "B12345678"},
            "lines": [
                {"description": "Widget", "quantity": 10, "unit_price": 10.5, "vat_rate": 21},
                {"description": "Gadget", "quantity": 4, "unit_price": 100, "vat_rate": 10},
            ],
        },
    ).json()
    return client.post(
        "/api/v1/delivery-notes",
        json={
            "order_id": order["id"],
            "lines": [{"order_line": 1, "quantity": 4}, {"order_line": 2, "quantity": 3}],
        },
    ).json()


def post(client: TestClient, delivery_note_id: str):
    return client.post("/api/v1/invoices", json={"delivery_note_id": delivery_note_id})


def test_issue_invoice_returns_201_and_references_the_delivery_note(client: TestClient):
    delivery_note = issue_delivery_note(client)

    response = post(client, delivery_note["id"])

    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert re.fullmatch(rf"F-{date.today().year}-\d{{6}}", body["number"])
    assert body["type"] == "INVOICE"
    assert body["status"] == "ISSUED"
    assert body["issue_date"] == date.today().isoformat()
    assert body["delivery_note_id"] == delivery_note["id"]
    # The invoice also says which order the chain started from.
    assert body["order_id"] == delivery_note["order_id"]


def test_invoice_bills_what_the_delivery_note_delivered(client: TestClient):
    delivery_note = issue_delivery_note(client)

    body = post(client, delivery_note["id"]).json()

    assert body["customer"] == {"name": "Acme S.L.", "tax_id": "B12345678"}
    assert body["lines"] == [
        {
            "position": 1,
            "delivery_note_line": 1,
            "description": "Widget",
            "quantity": 4.0,
            "unit_price": 10.5,
            "vat_rate": 21.0,
        },
        {
            "position": 2,
            "delivery_note_line": 2,
            "description": "Gadget",
            "quantity": 3.0,
            "unit_price": 100.0,
            "vat_rate": 10.0,
        },
    ]


def test_invoice_calculates_the_taxable_base_the_vat_and_the_total(client: TestClient):
    delivery_note = issue_delivery_note(client)

    body = post(client, delivery_note["id"]).json()

    # 4 x 10.50 = 42.00 (VAT 8.82) and 3 x 100.00 = 300.00 (VAT 30.00)
    assert body["total_net"] == 342.0
    assert body["total_vat"] == 38.82
    assert body["total"] == 380.82
    assert body["total"] == delivery_note["total"]


def test_invoice_is_saved_linked_to_its_delivery_note(client: TestClient, session: Session):
    delivery_note = issue_delivery_note(client)

    invoice_id = post(client, delivery_note["id"]).json()["id"]

    invoice = session.get(Document, uuid.UUID(invoice_id))
    assert invoice is not None
    assert invoice.type == DocumentType.INVOICE
    assert str(invoice.parent_id) == delivery_note["id"]
    # Every line points to the delivery note line it bills.
    assert [line.source_line.position for line in invoice.lines] == [1, 2]


def test_invoices_get_consecutive_numbers_without_gaps(client: TestClient):
    first = post(client, issue_delivery_note(client)["id"]).json()
    second = post(client, issue_delivery_note(client)["id"]).json()
    third = post(client, issue_delivery_note(client)["id"]).json()

    assert [sequence(second) - sequence(first), sequence(third) - sequence(second)] == [1, 1]


def test_rejected_invoices_do_not_use_a_number(client: TestClient):
    delivery_note = issue_delivery_note(client)
    first = post(client, delivery_note["id"]).json()
    post(client, delivery_note["id"])  # already invoiced
    post(client, str(uuid.uuid4()))  # no delivery note
    second = post(client, issue_delivery_note(client)["id"]).json()

    # The two rejected requests left no gap in the numbering.
    assert sequence(second) == sequence(first) + 1


def test_delivery_note_that_does_not_exist_is_rejected_with_404(client: TestClient):
    response = post(client, str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REFERENCE_NOT_FOUND"


@pytest.mark.parametrize("kind", ["order", "invoice"])
def test_a_document_that_is_not_a_delivery_note_is_rejected_with_404(client: TestClient, kind: str):
    delivery_note = issue_delivery_note(client)
    documents = {
        "order": delivery_note["order_id"],
        "invoice": post(client, delivery_note["id"]).json()["id"],
    }

    response = post(client, documents[kind])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REFERENCE_NOT_FOUND"


def test_a_delivery_note_cannot_be_invoiced_twice(client: TestClient):
    delivery_note = issue_delivery_note(client)
    post(client, delivery_note["id"])

    response = post(client, delivery_note["id"])

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "DELIVERY_NOTE_ALREADY_INVOICED"
    assert delivery_note["number"] in error["message"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "delivery_note_id"),
        ({"delivery_note_id": "not-a-uuid"}, "delivery_note_id"),
        ({"delivery_note_id": str(uuid.uuid4()), "lines": []}, "lines"),
        ({"delivery_note_id": str(uuid.uuid4()), "total": 1}, "total"),
        ({"delivery_note_id": str(uuid.uuid4()), "series": "F"}, "series"),
    ],
)
def test_invalid_requests_are_rejected_with_422(client: TestClient, body: dict, field: str):
    response = client.post("/api/v1/invoices", json=body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert field in error["message"]


def test_the_invoice_issued_event_is_published(client: TestClient, publisher):
    delivery_note = issue_delivery_note(client)

    invoice = post(client, delivery_note["id"]).json()

    assert publisher.events == [
        (
            INVOICE_ISSUED,
            {
                "invoice_id": invoice["id"],
                "number": invoice["number"],
                "delivery_note_id": delivery_note["id"],
                "order_id": delivery_note["order_id"],
                "total": "380.82",
                "issued_at": publisher.events[0][1]["issued_at"],
            },
        )
    ]
    assert publisher.events[0][1]["issued_at"].startswith(date.today().isoformat())


def test_no_event_is_published_when_the_invoice_is_rejected(client: TestClient, publisher):
    delivery_note = issue_delivery_note(client)
    post(client, delivery_note["id"])
    publisher.events.clear()

    post(client, delivery_note["id"])  # already invoiced
    post(client, str(uuid.uuid4()))  # no delivery note

    assert publisher.events == []


def test_the_invoice_is_issued_even_if_the_event_cannot_be_published(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    class DownPublisher:
        def publish(self, stream: str, fields: dict[str, str]) -> None:
            raise EventPublishError("redis is down")

    delivery_note = issue_delivery_note(client)
    app.dependency_overrides[get_publisher] = lambda: DownPublisher()

    with caplog.at_level(logging.ERROR):
        response = post(client, delivery_note["id"])

    # A failure of whoever reacts to the invoice must not stop invoices from being issued.
    assert response.status_code == 201
    assert "was not published" in caplog.text
    assert response.json()["number"] in caplog.text
