import pytest
from fastapi.testclient import TestClient

# These requests are rejected before the endpoint runs, so they need no database.


def valid_order() -> dict:
    return {
        "customer": {"name": "Acme S.L.", "tax_id": "B12345678"},
        "lines": [{"description": "Widget", "quantity": 1, "unit_price": 10}],
    }


def message(response) -> str:
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    return error["message"]


def test_malformed_json_says_the_body_is_invalid(offline_client: TestClient):
    response = offline_client.post(
        "/api/v1/orders", content="not json", headers={"Content-Type": "application/json"}
    )

    # Not "0: JSON decode error": that 0 is the position of the error, not a field.
    assert message(response) == "body: JSON decode error"


def test_empty_body_says_the_body_is_missing(offline_client: TestClient):
    response = offline_client.post(
        "/api/v1/orders", content="", headers={"Content-Type": "application/json"}
    )

    assert message(response) == "body: Field required"


def test_nested_errors_name_the_whole_path(offline_client: TestClient):
    order = valid_order()
    order["lines"][0]["quantity"] = -1

    assert message(offline_client.post("/api/v1/orders", json=order)).startswith(
        "lines.0.quantity:"
    )


def test_several_errors_are_reported_together(offline_client: TestClient):
    order = valid_order()
    order["lines"][0]["quantity"] = -1
    order["customer"]["name"] = " "

    text = message(offline_client.post("/api/v1/orders", json=order))

    assert "lines.0.quantity" in text
    assert "customer.name" in text


@pytest.mark.parametrize(
    ("path", "field"),
    [
        (lambda order: order, "total"),
        (lambda order: order["customer"], "email"),
        (lambda order: order["lines"][0], "subtotal"),
    ],
)
def test_unknown_fields_are_rejected(offline_client: TestClient, path, field: str):
    order = valid_order()
    path(order)[field] = 5

    text = message(offline_client.post("/api/v1/orders", json=order))

    assert field in text
    assert "Extra inputs are not permitted" in text
