import re
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Document, DocumentType


def sequence(document: dict) -> int:
    """The correlative part of a number: A-2026-000007 -> 7."""
    return int(document["number"].rsplit("-", 1)[1])


def create_order(client: TestClient) -> dict:
    """Register an order of 10 widgets (10.50 each, VAT 21) and 4 gadgets (100 each, VAT 10)."""
    order = {
        "customer": {"name": "Acme S.L.", "tax_id": "B12345678"},
        "lines": [
            {"description": "Widget", "quantity": 10, "unit_price": 10.5, "vat_rate": 21},
            {"description": "Gadget", "quantity": 4, "unit_price": 100, "vat_rate": 10},
        ],
    }
    return client.post("/api/v1/orders", json=order).json()


def delivery_note(order_id: str, *lines: tuple[int, float]) -> dict:
    """Body of a delivery note: each line is (position of the order line, quantity)."""
    return {
        "order_id": order_id,
        "lines": [{"order_line": line, "quantity": quantity} for line, quantity in lines],
    }


def post(client: TestClient, body: dict):
    return client.post("/api/v1/delivery-notes", json=body)


def test_create_delivery_note_returns_201_and_references_the_order(client: TestClient):
    order = create_order(client)

    response = post(client, delivery_note(order["id"], (1, 4)))

    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert re.fullmatch(rf"A-{date.today().year}-\d{{6}}", body["number"])
    assert body["type"] == "DELIVERY_NOTE"
    assert body["status"] == "ISSUED"
    assert body["issue_date"] == date.today().isoformat()
    assert body["order_id"] == order["id"]


def test_delivery_note_takes_the_customer_and_prices_from_the_order(client: TestClient):
    order = create_order(client)

    body = post(client, delivery_note(order["id"], (2, 3), (1, 4))).json()

    assert body["customer"] == {"name": "Acme S.L.", "tax_id": "B12345678"}
    # The lines keep the order the client sent, and point to the order line they deliver.
    assert body["lines"] == [
        {
            "position": 1,
            "order_line": 2,
            "description": "Gadget",
            "quantity": 3.0,
            "unit_price": 100.0,
            "vat_rate": 10.0,
        },
        {
            "position": 2,
            "order_line": 1,
            "description": "Widget",
            "quantity": 4.0,
            "unit_price": 10.5,
            "vat_rate": 21.0,
        },
    ]


def test_delivery_note_calculates_the_amounts_of_what_is_delivered(client: TestClient):
    order = create_order(client)

    body = post(client, delivery_note(order["id"], (1, 4), (2, 3))).json()

    # 4 x 10.50 = 42.00 (VAT 8.82) and 3 x 100.00 = 300.00 (VAT 30.00)
    assert body["total_net"] == 342.0
    assert body["total_vat"] == 38.82
    assert body["total"] == 380.82


def test_delivery_note_is_saved_linked_to_its_order(client: TestClient, session: Session):
    order = create_order(client)

    note_id = post(client, delivery_note(order["id"], (1, 4))).json()["id"]

    note = session.get(Document, uuid.UUID(note_id))
    assert note is not None
    assert note.type == DocumentType.DELIVERY_NOTE
    assert str(note.parent_id) == order["id"]
    # The line points to the order line it comes from.
    assert note.lines[0].source_line is not None
    assert note.lines[0].source_line.position == 1


def test_a_whole_order_can_be_delivered_at_once(client: TestClient):
    order = create_order(client)

    response = post(client, delivery_note(order["id"], (1, 10), (2, 4)))

    assert response.status_code == 201


def test_an_order_can_be_delivered_in_parts(client: TestClient):
    order = create_order(client)

    first = post(client, delivery_note(order["id"], (1, 4)))
    second = post(client, delivery_note(order["id"], (1, 6)))

    assert first.status_code == 201
    assert second.status_code == 201
    assert sequence(second.json()) == sequence(first.json()) + 1


def test_quantities_are_added_up_across_delivery_notes(client: TestClient):
    order = create_order(client)
    post(client, delivery_note(order["id"], (1, 4)))

    # 4 delivered + 7 requested is 11, and only 10 were ordered.
    response = post(client, delivery_note(order["id"], (1, 7)))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "QUANTITY_EXCEEDED"
    assert error["message"] == (
        "line 1: 7 requested but only 6 pending (ordered 10, already delivered 4)"
    )


def test_delivering_more_than_ordered_is_rejected_with_422(client: TestClient):
    order = create_order(client)

    response = post(client, delivery_note(order["id"], (2, 5)))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "QUANTITY_EXCEEDED"


def test_a_fully_delivered_line_accepts_nothing_more(client: TestClient):
    order = create_order(client)
    post(client, delivery_note(order["id"], (2, 4)))

    response = post(client, delivery_note(order["id"], (2, 0.001)))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "QUANTITY_EXCEEDED"


def test_a_line_that_exceeds_rejects_the_whole_delivery_note(client: TestClient):
    order = create_order(client)

    # The first line is fine, the second one is not: nothing is saved.
    rejected = post(client, delivery_note(order["id"], (1, 4), (2, 5)))
    # So the 4 widgets are still pending and all 10 can be delivered.
    accepted = post(client, delivery_note(order["id"], (1, 10)))

    assert rejected.status_code == 422
    assert accepted.status_code == 201


def test_order_that_does_not_exist_is_rejected_with_404(client: TestClient):
    response = post(client, delivery_note(str(uuid.uuid4()), (1, 1)))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REFERENCE_NOT_FOUND"


def test_a_document_that_is_not_an_order_is_rejected_with_404(client: TestClient):
    order = create_order(client)
    note = post(client, delivery_note(order["id"], (1, 1))).json()

    # A delivery note exists, but it is not an order that can be delivered.
    response = post(client, delivery_note(note["id"], (1, 1)))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REFERENCE_NOT_FOUND"


def test_a_line_the_order_does_not_have_is_rejected_with_422(client: TestClient):
    order = create_order(client)

    response = post(client, delivery_note(order["id"], (3, 1)))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_ORDER_LINE"
    assert error["message"] == "the order has no line 3"


def test_rejected_delivery_notes_do_not_use_a_number(client: TestClient):
    order = create_order(client)
    first = post(client, delivery_note(order["id"], (1, 1))).json()
    post(client, delivery_note(order["id"], (1, 100)))  # exceeds
    post(client, delivery_note(str(uuid.uuid4()), (1, 1)))  # no order
    second = post(client, delivery_note(order["id"], (1, 1))).json()

    assert sequence(second) == sequence(first) + 1


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"lines": [{"order_line": 1, "quantity": 1}]}, "order_id"),
        ({"order_id": "not-a-uuid", "lines": [{"order_line": 1, "quantity": 1}]}, "order_id"),
        ({"order_id": str(uuid.uuid4())}, "lines"),
        ({"order_id": str(uuid.uuid4()), "lines": []}, "lines"),
        (
            {"order_id": str(uuid.uuid4()), "lines": [{"order_line": 1, "quantity": 0}]},
            "lines.0.quantity",
        ),
        (
            {"order_id": str(uuid.uuid4()), "lines": [{"order_line": 0, "quantity": 1}]},
            "lines.0.order_line",
        ),
        (
            {"order_id": str(uuid.uuid4()), "lines": [{"order_line": 1}]},
            "lines.0.quantity",
        ),
    ],
)
def test_invalid_requests_are_rejected_with_422(client: TestClient, body: dict, field: str):
    response = post(client, body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert field in error["message"]


def test_an_order_line_cannot_appear_twice(client: TestClient):
    order = create_order(client)

    response = post(client, delivery_note(order["id"], (1, 1), (1, 2)))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "only appear once" in error["message"]


@pytest.mark.parametrize("field", ["unit_price", "total", "number", "customer"])
def test_values_that_come_from_the_order_cannot_be_sent(client: TestClient, field: str):
    order = create_order(client)
    body = delivery_note(order["id"], (1, 1)) | {field: "x"}

    response = post(client, body)

    assert response.status_code == 422
    assert field in response.json()["error"]["message"]
