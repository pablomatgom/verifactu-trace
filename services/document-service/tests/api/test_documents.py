import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session


def issue_chain(client: TestClient) -> tuple[dict, dict, dict]:
    """Register an order, deliver part of it (lines 2 and 1 only) and invoice the delivery."""
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
    # The second order line goes first, so the delivery note positions differ from the order's.
    delivery_note = client.post(
        "/api/v1/delivery-notes",
        json={
            "order_id": order["id"],
            "lines": [{"order_line": 2, "quantity": 3}, {"order_line": 1, "quantity": 4}],
        },
    ).json()
    invoice = client.post("/api/v1/invoices", json={"delivery_note_id": delivery_note["id"]}).json()
    return order, delivery_note, invoice


def get(client: TestClient, document_id: str):
    return client.get(f"/api/v1/documents/{document_id}")


def test_get_an_order_returns_200_with_its_data(client: TestClient):
    order, _, _ = issue_chain(client)

    response = get(client, order["id"])

    assert response.status_code == 200
    assert response.json() == {
        "id": order["id"],
        "type": "ORDER",
        "number": order["number"],
        "status": "ISSUED",
        "issue_date": order["issue_date"],
        "parent_id": None,
        "customer": {"name": "Acme S.L.", "tax_id": "B12345678"},
        "lines": [
            {
                "position": 1,
                "source_line": None,
                "description": "Widget",
                "quantity": 10.0,
                "unit_price": 10.5,
                "vat_rate": 21.0,
            },
            {
                "position": 2,
                "source_line": None,
                "description": "Gadget",
                "quantity": 4.0,
                "unit_price": 100.0,
                "vat_rate": 10.0,
            },
        ],
        "total_net": order["total_net"],
        "total_vat": order["total_vat"],
        "total": order["total"],
    }


def test_get_a_delivery_note_points_to_its_order_and_to_the_lines_it_delivers(client: TestClient):
    order, delivery_note, _ = issue_chain(client)

    body = get(client, delivery_note["id"]).json()

    assert body["type"] == "DELIVERY_NOTE"
    assert body["number"] == delivery_note["number"]
    assert body["parent_id"] == order["id"]
    # The Gadget is the second line of the order and the first of the delivery note.
    assert [
        (line["position"], line["source_line"], line["description"]) for line in body["lines"]
    ] == [
        (1, 2, "Gadget"),
        (2, 1, "Widget"),
    ]


def test_get_an_invoice_points_to_its_delivery_note_and_to_the_lines_it_bills(client: TestClient):
    _, delivery_note, invoice = issue_chain(client)

    body = get(client, invoice["id"]).json()

    assert body["type"] == "INVOICE"
    assert body["number"] == invoice["number"]
    assert body["parent_id"] == delivery_note["id"]
    assert [(line["position"], line["source_line"]) for line in body["lines"]] == [(1, 1), (2, 2)]
    assert (body["total_net"], body["total_vat"], body["total"]) == (
        invoice["total_net"],
        invoice["total_vat"],
        invoice["total"],
    )


def test_the_chain_can_be_walked_from_the_invoice_to_the_order(client: TestClient):
    order, _, invoice = issue_chain(client)

    types = []
    current = get(client, invoice["id"]).json()
    while True:
        types.append(current["type"])
        if current["parent_id"] is None:
            break
        current = get(client, current["parent_id"]).json()

    assert types == ["INVOICE", "DELIVERY_NOTE", "ORDER"]
    assert current["id"] == order["id"]


def test_a_document_that_does_not_exist_returns_404(client: TestClient):
    document_id = str(uuid.uuid4())

    response = get(client, document_id)

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_NOT_FOUND"
    assert document_id in error["message"]


def test_an_identifier_that_is_not_a_uuid_returns_422(offline_client: TestClient):
    response = get(offline_client, "not-a-uuid")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "document_id" in error["message"]


def test_the_lines_are_loaded_in_a_fixed_number_of_queries(
    client: TestClient, session: Session, engine: Engine
):
    # Three documents with two lines each: if every line triggered its own query to find the line
    # it comes from, the count would grow with the lines.
    _, _, invoice = issue_chain(client)
    session.expire_all()  # forget what the requests above loaded, so the GET must query again
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = get(client, invoice["id"])
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert response.status_code == 200
    assert len(statements) <= 3
