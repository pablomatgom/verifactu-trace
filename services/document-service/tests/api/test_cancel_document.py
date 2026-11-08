import uuid

import pytest
from fastapi.testclient import TestClient


def create_order(client: TestClient, quantity: int = 10) -> dict:
    return client.post(
        "/api/v1/orders",
        json={
            "customer": {"name": "Acme S.L.", "tax_id": "B12345678"},
            "lines": [
                {"description": "Widget", "quantity": quantity, "unit_price": 10, "vat_rate": 21}
            ],
        },
    ).json()


def deliver(client: TestClient, order_id: str, quantity: int = 4):
    return client.post(
        "/api/v1/delivery-notes",
        json={"order_id": order_id, "lines": [{"order_line": 1, "quantity": quantity}]},
    )


def create_delivery_note(client: TestClient, quantity: int = 4) -> dict:
    order = create_order(client)
    return deliver(client, order["id"], quantity).json()


def invoice(client: TestClient, delivery_note_id: str):
    return client.post("/api/v1/invoices", json={"delivery_note_id": delivery_note_id})


def cancel(client: TestClient, document_id: uuid.UUID | str):
    return client.post(f"/api/v1/documents/{document_id}/cancel")


def status_of(client: TestClient, document_id: str) -> str:
    return client.get(f"/api/v1/documents/{document_id}").json()["status"]


def test_an_order_without_delivery_notes_can_be_cancelled(client: TestClient):
    order = create_order(client)

    response = cancel(client, order["id"])

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["type"], body["status"]) == (order["id"], "ORDER", "CANCELLED")
    assert body["number"] == order["number"]
    assert len(body["lines"]) == 1
    assert status_of(client, order["id"]) == "CANCELLED"


def test_a_delivery_note_without_invoice_can_be_cancelled(client: TestClient):
    delivery_note = create_delivery_note(client)

    response = cancel(client, delivery_note["id"])

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["parent_id"] == delivery_note["order_id"]


def test_the_response_is_the_same_as_the_query_of_the_document(client: TestClient):
    delivery_note = create_delivery_note(client)

    response = cancel(client, delivery_note["id"])

    assert response.json() == client.get(f"/api/v1/documents/{delivery_note['id']}").json()


def test_cancelling_a_delivery_note_leaves_its_order_as_it_was(client: TestClient):
    delivery_note = create_delivery_note(client)

    cancel(client, delivery_note["id"])

    assert status_of(client, delivery_note["order_id"]) == "ISSUED"


def test_an_invoice_cannot_be_cancelled(client: TestClient):
    delivery_note = create_delivery_note(client)
    issued = invoice(client, delivery_note["id"]).json()

    response = cancel(client, issued["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_NOT_CANCELLABLE"
    assert "rectified" in error["message"]
    assert status_of(client, issued["id"]) == "ISSUED"


def test_a_delivery_note_with_an_invoice_cannot_be_cancelled(client: TestClient):
    delivery_note = create_delivery_note(client)
    invoice(client, delivery_note["id"])

    response = cancel(client, delivery_note["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_NOT_CANCELLABLE"
    assert "already has an invoice" in error["message"]
    assert status_of(client, delivery_note["id"]) == "ISSUED"


def test_an_order_with_an_invoiced_delivery_note_cannot_be_cancelled(client: TestClient):
    delivery_note = create_delivery_note(client)
    invoice(client, delivery_note["id"])

    response = cancel(client, delivery_note["order_id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_CANCELLABLE"
    assert status_of(client, delivery_note["order_id"]) == "ISSUED"


def test_an_order_with_a_delivery_note_that_is_not_cancelled_cannot_be_cancelled(
    client: TestClient,
):
    delivery_note = create_delivery_note(client)

    response = cancel(client, delivery_note["order_id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_NOT_CANCELLABLE"
    assert delivery_note["number"] in error["message"]
    assert "cancel them first" in error["message"]
    assert status_of(client, delivery_note["order_id"]) == "ISSUED"


def test_an_order_can_be_cancelled_once_its_delivery_notes_are(client: TestClient):
    order = create_order(client)
    first = deliver(client, order["id"], 3).json()
    second = deliver(client, order["id"], 3).json()
    cancel(client, first["id"])
    assert cancel(client, order["id"]).status_code == 409  # the second one is still alive

    cancel(client, second["id"])

    assert cancel(client, order["id"]).status_code == 200


@pytest.mark.parametrize("kind", ["order", "delivery_note"])
def test_a_document_cannot_be_cancelled_twice(client: TestClient, kind: str):
    delivery_note = create_delivery_note(client)
    document_id = delivery_note["order_id"] if kind == "order" else delivery_note["id"]
    if kind == "order":
        cancel(client, delivery_note["id"])
    cancel(client, document_id)

    response = cancel(client, document_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_NOT_CANCELLABLE"
    assert "already cancelled" in error["message"]


def test_no_delivery_note_can_be_made_from_a_cancelled_order(client: TestClient):
    order = create_order(client)
    cancel(client, order["id"])

    response = deliver(client, order["id"])

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "REFERENCE_CANCELLED"
    assert order["number"] in error["message"]


def test_no_invoice_can_be_made_from_a_cancelled_delivery_note(client: TestClient):
    delivery_note = create_delivery_note(client)
    cancel(client, delivery_note["id"])

    response = invoice(client, delivery_note["id"])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REFERENCE_CANCELLED"


def test_cancelling_a_delivery_note_frees_what_it_delivered(client: TestClient):
    order = create_order(client, quantity=10)
    delivery_note = deliver(client, order["id"], 10).json()
    assert deliver(client, order["id"], 1).json()["error"]["code"] == "QUANTITY_EXCEEDED"

    cancel(client, delivery_note["id"])

    again = deliver(client, order["id"], 10)
    assert again.status_code == 201


def test_cancelled_documents_are_listed_under_their_status(client: TestClient):
    order = create_order(client)
    cancel(client, order["id"])

    cancelled = client.get("/api/v1/documents", params={"status": "CANCELLED", "size": 100})
    issued = client.get("/api/v1/documents", params={"status": "ISSUED", "size": 100})

    assert order["id"] in [item["id"] for item in cancelled.json()["items"]]
    assert order["id"] not in [item["id"] for item in issued.json()["items"]]


def test_a_document_that_does_not_exist_returns_404(client: TestClient):
    response = cancel(client, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


@pytest.mark.parametrize("document_id", ["not-a-uuid", "123"])
def test_an_identifier_that_is_not_a_uuid_returns_422(offline_client: TestClient, document_id: str):
    response = cancel(offline_client, document_id)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "document_id" in error["message"]


def test_docs_describe_the_cancellation_and_its_errors(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/documents/{document_id}/cancel"]["post"]
    assert "200" in operation["responses"]
    for status in ("404", "409", "422"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
