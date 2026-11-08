import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import DocumentLine


def create_order(client: TestClient) -> dict:
    return client.post(
        "/api/v1/orders",
        json={
            "customer": {"name": "Acme S.L.", "tax_id": "B12345678"},
            "lines": [
                {"description": "Widget", "quantity": 10, "unit_price": 10.5, "vat_rate": 21},
                {"description": "Gadget", "quantity": 4, "unit_price": 100, "vat_rate": 10},
            ],
        },
    ).json()


def deliver(client: TestClient, order: dict, widgets: int = 10, gadgets: int = 4) -> dict:
    return client.post(
        "/api/v1/delivery-notes",
        json={
            "order_id": order["id"],
            "lines": [
                {"order_line": 1, "quantity": widgets},
                {"order_line": 2, "quantity": gadgets},
            ],
        },
    ).json()


def issue_chain(client: TestClient, widgets: int = 10) -> tuple[dict, dict, dict]:
    order = create_order(client)
    delivery_note = deliver(client, order, widgets=widgets)
    invoice = client.post("/api/v1/invoices", json={"delivery_note_id": delivery_note["id"]}).json()
    return order, delivery_note, invoice


def discrepancies(client: TestClient, document_id: uuid.UUID | str):
    return client.get(f"/api/v1/documents/{document_id}/discrepancies")


def change_line(session: Session, document_id: str, position: int, **values) -> None:
    """Change a stored line directly in the database, as a bug or someone with access could."""
    session.execute(
        update(DocumentLine)
        .where(
            DocumentLine.document_id == uuid.UUID(document_id), DocumentLine.position == position
        )
        .values(**values)
    )
    session.expire_all()


def test_a_coherent_chain_has_an_empty_list_and_lists_its_three_documents(client: TestClient):
    order, delivery_note, invoice = issue_chain(client)

    response = discrepancies(client, invoice["id"])

    assert response.status_code == 200
    assert response.json() == {
        "document_id": invoice["id"],
        "compared": [
            {"type": "ORDER", "id": order["id"], "number": order["number"]},
            {"type": "DELIVERY_NOTE", "id": delivery_note["id"], "number": delivery_note["number"]},
            {"type": "INVOICE", "id": invoice["id"], "number": invoice["number"]},
        ],
        "discrepancies": [],
    }


def test_a_delivery_note_that_delivers_less_than_the_order_is_a_quantity_difference(
    client: TestClient,
):
    order, delivery_note, invoice = issue_chain(client, widgets=4)

    body = discrepancies(client, invoice["id"]).json()

    assert body["discrepancies"] == [
        {
            "field": "quantity",
            "description": "Widget",
            "source": {
                "document_type": "ORDER",
                "number": order["number"],
                "line": 1,
                "value": 10.0,
            },
            "target": {
                "document_type": "DELIVERY_NOTE",
                "number": delivery_note["number"],
                "line": 1,
                "value": 4.0,
            },
        }
    ]


def test_a_changed_quantity_in_the_delivery_note_is_reported_between_it_and_the_invoice(
    client: TestClient, session: Session
):
    _, delivery_note, invoice = issue_chain(client)
    change_line(session, delivery_note["id"], 2, quantity=3)

    differences = discrepancies(client, invoice["id"]).json()["discrepancies"]

    pairs = {
        (d["source"]["document_type"], d["target"]["document_type"], d["field"])
        for d in differences
    }
    assert pairs == {
        ("ORDER", "DELIVERY_NOTE", "quantity"),
        ("DELIVERY_NOTE", "INVOICE", "quantity"),
    }
    assert {d["description"] for d in differences} == {"Gadget"}


def test_a_changed_price_and_vat_in_the_invoice_are_reported(client: TestClient, session: Session):
    _, delivery_note, invoice = issue_chain(client)
    change_line(session, invoice["id"], 1, unit_price=99, vat_rate=4)

    differences = discrepancies(client, invoice["id"]).json()["discrepancies"]

    assert [(d["field"], d["source"]["value"], d["target"]["value"]) for d in differences] == [
        ("unit_price", 10.5, 99.0),
        ("vat_rate", 21.0, 4.0),
    ]
    assert {d["source"]["number"] for d in differences} == {delivery_note["number"]}
    assert {d["target"]["number"] for d in differences} == {invoice["number"]}


def test_a_delivery_note_is_compared_with_its_order_only(client: TestClient):
    order, delivery_note, _ = issue_chain(client, widgets=4)

    body = discrepancies(client, delivery_note["id"]).json()

    assert [document["type"] for document in body["compared"]] == ["ORDER", "DELIVERY_NOTE"]
    assert [d["field"] for d in body["discrepancies"]] == ["quantity"]
    assert body["discrepancies"][0]["source"]["number"] == order["number"]


def test_an_order_has_nothing_to_be_compared_with(client: TestClient):
    order = create_order(client)

    body = discrepancies(client, order["id"]).json()

    assert [document["id"] for document in body["compared"]] == [order["id"]]
    assert body["discrepancies"] == []


def test_the_other_chains_are_not_looked_at(client: TestClient, session: Session):
    _, broken, _ = issue_chain(client)
    _, _, intact_invoice = issue_chain(client)
    change_line(session, broken["id"], 1, quantity=1)

    assert discrepancies(client, intact_invoice["id"]).json()["discrepancies"] == []


def test_the_query_does_not_change_the_documents(client: TestClient, session: Session):
    _, delivery_note, invoice = issue_chain(client)
    change_line(session, delivery_note["id"], 1, quantity=1)
    before = client.get(f"/api/v1/documents/{invoice['id']}").json()

    discrepancies(client, invoice["id"])

    assert client.get(f"/api/v1/documents/{invoice['id']}").json() == before


def test_a_document_that_does_not_exist_returns_404(client: TestClient):
    response = discrepancies(client, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


@pytest.mark.parametrize("document_id", ["not-a-uuid", "123"])
def test_an_identifier_that_is_not_a_uuid_returns_422(offline_client: TestClient, document_id: str):
    response = discrepancies(offline_client, document_id)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "document_id" in error["message"]


def test_docs_describe_the_discrepancies_and_their_errors(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/documents/{document_id}/discrepancies"]["get"]
    for status in ("404", "422"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
    schemas = spec["components"]["schemas"]
    assert set(schemas["DiscrepancyReport"]["properties"]) == {
        "document_id",
        "compared",
        "discrepancies",
    }
    for name in ("DiscrepancyRead", "LineRefRead", "ComparedDocument", "DiscrepancyReport"):
        properties = schemas[name]["properties"]
        assert all("description" in definition for definition in properties.values()), name
