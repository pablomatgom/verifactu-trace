import uuid

import pytest
from conftest import FakeDocumentClient
from fastapi.testclient import TestClient


def get_chain(client: TestClient, invoice_id: uuid.UUID | str):
    return client.get(f"/api/v1/traceability/documents/{invoice_id}/chain")


def test_the_chain_of_an_invoice_lists_the_order_the_delivery_note_and_the_invoice(
    documents_client: TestClient, documents: FakeDocumentClient
):
    order, delivery_note, invoice = documents.add_chain()

    response = get_chain(documents_client, invoice.id)

    assert response.status_code == 200
    assert response.json() == {
        "invoice_id": str(invoice.id),
        "chain": [
            {
                "type": document.type,
                "id": str(document.id),
                "number": document.number,
                "issue_date": document.issue_date.isoformat(),
            }
            for document in (order, delivery_note, invoice)
        ],
    }


def test_the_chain_goes_in_the_order_the_documents_were_made(
    documents_client: TestClient, documents: FakeDocumentClient
):
    _, _, invoice = documents.add_chain()

    chain = get_chain(documents_client, invoice.id).json()["chain"]

    assert [document["type"] for document in chain] == ["ORDER", "DELIVERY_NOTE", "INVOICE"]


def test_an_invoice_that_does_not_exist_returns_404(documents_client: TestClient):
    response = get_chain(documents_client, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INVOICE_NOT_FOUND"


def test_a_document_that_is_not_an_invoice_returns_404(
    documents_client: TestClient, documents: FakeDocumentClient
):
    order, _, _ = documents.add_chain()

    response = get_chain(documents_client, order.id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INVOICE_NOT_FOUND"


def test_documents_that_do_not_form_a_chain_return_502(
    documents_client: TestClient, documents: FakeDocumentClient
):
    invoice = documents.add("INVOICE")  # an invoice with no delivery note

    response = get_chain(documents_client, invoice.id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INCONSISTENT_CHAIN"


def test_a_document_service_that_is_down_returns_503(
    documents_client: TestClient, documents: FakeDocumentClient
):
    _, _, invoice = documents.add_chain()
    documents.unavailable = True

    response = get_chain(documents_client, invoice.id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DOCUMENT_SERVICE_UNAVAILABLE"


@pytest.mark.parametrize("invoice_id", ["not-a-uuid", "123"])
def test_an_identifier_that_is_not_a_uuid_returns_422_without_asking_document_service(
    documents_client: TestClient, documents: FakeDocumentClient, invoice_id: str
):
    response = get_chain(documents_client, invoice_id)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "invoice_id" in error["message"]
    assert documents.requested == []


def test_docs_describe_the_chain_and_its_errors(documents_client: TestClient):
    spec = documents_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/traceability/documents/{invoice_id}/chain"]["get"]
    for status in ("404", "422", "502", "503"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
    schemas = spec["components"]["schemas"]
    assert set(schemas["DocumentChainRead"]["properties"]) == {"invoice_id", "chain"}
    properties = schemas["ChainDocument"]["properties"]
    assert set(properties) == {"type", "id", "number", "issue_date"}
    assert all("description" in definition for definition in properties.values())
