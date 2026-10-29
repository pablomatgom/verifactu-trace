import re
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentLine


def sequence(order: dict) -> int:
    """The correlative part of an order number: P-2026-000007 -> 7."""
    return int(order["number"].rsplit("-", 1)[1])


def valid_order() -> dict:
    return {
        "customer": {"name": "Acme S.L.", "tax_id": "B12345678"},
        "lines": [
            {"description": "Widget", "quantity": 2, "unit_price": 10.5, "vat_rate": 21},
            {"description": "Gadget", "quantity": 1, "unit_price": 100, "vat_rate": 10},
        ],
    }


def test_create_order_returns_201_with_id_and_number(client: TestClient):
    response = client.post("/api/v1/orders", json=valid_order())

    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])  # raises if it is not a valid UUID
    assert re.fullmatch(rf"P-{date.today().year}-\d{{6}}", body["number"])
    assert body["type"] == "ORDER"
    assert body["status"] == "ISSUED"
    assert body["issue_date"] == date.today().isoformat()
    assert body["customer"] == {"name": "Acme S.L.", "tax_id": "B12345678"}


def test_create_order_calculates_the_amounts(client: TestClient):
    body = client.post("/api/v1/orders", json=valid_order()).json()

    # 2 x 10.50 = 21.00 (VAT 4.41) and 1 x 100.00 (VAT 10.00)
    assert body["total_net"] == 121.0
    assert body["total_vat"] == 14.41
    assert body["total"] == 135.41
    assert [line["position"] for line in body["lines"]] == [1, 2]
    assert body["lines"][0] == {
        "position": 1,
        "description": "Widget",
        "quantity": 2.0,
        "unit_price": 10.5,
        "vat_rate": 21.0,
    }


def test_create_order_saves_the_order_and_its_lines(client: TestClient, session: Session):
    order_id = client.post("/api/v1/orders", json=valid_order()).json()["id"]

    order = session.get(Document, uuid.UUID(order_id))
    assert order is not None
    assert order.customer_name == "Acme S.L."
    lines = (
        select(func.count()).select_from(DocumentLine).where(DocumentLine.document_id == order.id)
    )
    assert session.scalar(lines) == 2


def test_orders_get_consecutive_numbers(client: TestClient):
    first = client.post("/api/v1/orders", json=valid_order()).json()
    second = client.post("/api/v1/orders", json=valid_order()).json()

    assert sequence(second) == sequence(first) + 1
    assert first["id"] != second["id"]


def test_vat_rate_defaults_to_21(client: TestClient):
    order = valid_order()
    del order["lines"][0]["vat_rate"]

    body = client.post("/api/v1/orders", json=order).json()

    assert body["lines"][0]["vat_rate"] == 21.0


def test_order_without_lines_is_rejected_with_422(client: TestClient):
    order = valid_order() | {"lines": []}

    response = client.post("/api/v1/orders", json=order)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "lines" in error["message"]


def test_negative_quantity_is_rejected_with_422(client: TestClient):
    order = valid_order()
    order["lines"][0]["quantity"] = -1

    response = client.post("/api/v1/orders", json=order)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "lines.0.quantity" in error["message"]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"quantity": 0}, "lines.0.quantity"),
        ({"unit_price": -0.01}, "lines.0.unit_price"),
        ({"unit_price": 1.234}, "lines.0.unit_price"),
        ({"vat_rate": 101}, "lines.0.vat_rate"),
        ({"description": "   "}, "lines.0.description"),
    ],
)
def test_invalid_line_values_are_rejected(client: TestClient, change: dict, field: str):
    order = valid_order()
    order["lines"][0].update(change)

    response = client.post("/api/v1/orders", json=order)

    assert response.status_code == 422
    assert field in response.json()["error"]["message"]


@pytest.mark.parametrize("missing", ["customer", "lines"])
def test_missing_fields_are_rejected(client: TestClient, missing: str):
    order = valid_order()
    del order[missing]

    response = client.post("/api/v1/orders", json=order)

    assert response.status_code == 422
    assert missing in response.json()["error"]["message"]


def test_rejected_order_does_not_use_a_number(client: TestClient):
    first = client.post("/api/v1/orders", json=valid_order()).json()
    client.post("/api/v1/orders", json=valid_order() | {"lines": []})
    second = client.post("/api/v1/orders", json=valid_order()).json()

    assert sequence(second) == sequence(first) + 1
