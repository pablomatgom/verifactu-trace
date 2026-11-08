import logging
import re
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.events import EventPublishError, get_publisher
from app.main import app


def issue_invoice(client: TestClient) -> dict:
    """An invoice for 4 widgets (10.50, VAT 21) and 3 gadgets (100.00, VAT 10)."""
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
    delivery_note = client.post(
        "/api/v1/delivery-notes",
        json={
            "order_id": order["id"],
            "lines": [{"order_line": 1, "quantity": 4}, {"order_line": 2, "quantity": 3}],
        },
    ).json()
    return client.post("/api/v1/invoices", json={"delivery_note_id": delivery_note["id"]}).json()


def correct(client: TestClient, invoice_id: uuid.UUID | str, **body):
    body.setdefault("reason", "Returned goods")
    return client.post(f"/api/v1/invoices/{invoice_id}/corrections", json=body)


def test_a_corrective_invoice_references_the_invoice_and_takes_units_back(client: TestClient):
    invoice = issue_invoice(client)

    response = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 2}])

    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert re.fullmatch(rf"R-{date.today().year}-\d{{6}}", body["number"])
    assert body["type"] == "CORRECTIVE_INVOICE"
    assert body["status"] == "ISSUED"
    assert body["issue_date"] == date.today().isoformat()
    assert body["corrects_invoice_id"] == invoice["id"]
    assert body["reason"] == "Returned goods"
    assert body["customer"] == invoice["customer"]
    assert body["lines"] == [
        {
            "position": 1,
            "invoice_line": 1,
            "description": "Widget",
            "quantity": -2.0,
            "unit_price": 10.5,
            "vat_rate": 21.0,
        }
    ]
    # 2 x 10.50 = 21.00 of base and 4.41 of VAT, with the sign of what is taken back.
    assert (body["total_net"], body["total_vat"], body["total"]) == (-21.0, -4.41, -25.41)


def test_without_lines_everything_that_was_not_corrected_is_taken_back(client: TestClient):
    invoice = issue_invoice(client)

    body = correct(client, invoice["id"]).json()

    assert [(line["invoice_line"], line["quantity"]) for line in body["lines"]] == [
        (1, -4.0),
        (2, -3.0),
    ]
    # The corrective invoice cancels the invoice out: the same amounts, with the opposite sign.
    assert body["total_net"] == -invoice["total_net"]
    assert body["total_vat"] == -invoice["total_vat"]
    assert body["total"] == -invoice["total"]


def test_the_invoice_is_not_modified(client: TestClient):
    invoice = issue_invoice(client)
    before = client.get(f"/api/v1/documents/{invoice['id']}").json()

    correct(client, invoice["id"])

    assert client.get(f"/api/v1/documents/{invoice['id']}").json() == before


def test_the_corrective_invoice_can_be_read_like_any_document(client: TestClient):
    invoice = issue_invoice(client)
    created = correct(client, invoice["id"], lines=[{"invoice_line": 2, "quantity": 1}]).json()

    document = client.get(f"/api/v1/documents/{created['id']}").json()

    assert (document["type"], document["parent_id"]) == ("CORRECTIVE_INVOICE", invoice["id"])
    [line] = document["lines"]
    assert (line["source_line"], line["quantity"]) == (2, -1.0)


def test_a_corrective_invoice_is_listed_under_its_type_and_series(client: TestClient):
    invoice = issue_invoice(client)
    created = correct(client, invoice["id"]).json()

    by_type = client.get("/api/v1/documents", params={"type": "CORRECTIVE_INVOICE", "size": 100})
    by_series = client.get("/api/v1/documents", params={"series": "R", "size": 100})

    assert created["id"] in [item["id"] for item in by_type.json()["items"]]
    assert created["id"] in [item["id"] for item in by_series.json()["items"]]
    invoices = client.get("/api/v1/documents", params={"type": "INVOICE", "size": 100})
    assert created["id"] not in [item["id"] for item in invoices.json()["items"]]


def test_an_invoice_can_have_several_corrective_invoices_with_their_own_numbers(
    client: TestClient,
):
    invoice = issue_invoice(client)

    first = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 1}]).json()
    second = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 1}]).json()

    assert first["id"] != second["id"]
    assert int(second["number"].rsplit("-", 1)[1]) == int(first["number"].rsplit("-", 1)[1]) + 1
    assert first["corrects_invoice_id"] == second["corrects_invoice_id"] == invoice["id"]


def test_together_they_cannot_take_back_more_than_the_invoice_billed(client: TestClient):
    invoice = issue_invoice(client)
    correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 3}])

    response = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 2}])

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "QUANTITY_EXCEEDED"
    assert "only 1 left" in error["message"]
    assert "billed 4" in error["message"]
    assert "already corrected 3" in error["message"]


def test_the_last_unit_can_be_taken_back(client: TestClient):
    invoice = issue_invoice(client)
    correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 3}])

    response = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 1}])

    assert response.status_code == 201


def test_without_lines_only_what_is_left_is_taken_back(client: TestClient):
    invoice = issue_invoice(client)
    correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 3}])

    body = correct(client, invoice["id"]).json()

    assert [(line["invoice_line"], line["quantity"]) for line in body["lines"]] == [
        (1, -1.0),
        (2, -3.0),
    ]


def test_an_invoice_that_is_fully_rectified_has_nothing_left_to_correct(client: TestClient):
    invoice = issue_invoice(client)
    correct(client, invoice["id"])

    response = correct(client, invoice["id"])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NOTHING_TO_CORRECT"


def test_a_line_that_the_invoice_does_not_have_returns_422(client: TestClient):
    invoice = issue_invoice(client)

    response = correct(client, invoice["id"], lines=[{"invoice_line": 3, "quantity": 1}])

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_INVOICE_LINE"
    assert "no line 3" in error["message"]


def test_a_rejected_request_leaves_no_corrective_invoice_and_no_number_used(client: TestClient):
    invoice = issue_invoice(client)
    first = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 1}]).json()

    correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 99}])
    second = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 1}]).json()

    assert int(second["number"].rsplit("-", 1)[1]) == int(first["number"].rsplit("-", 1)[1]) + 1


@pytest.mark.parametrize("kind", ["order", "delivery_note", "corrective_invoice", "missing"])
def test_only_an_invoice_can_be_rectified(client: TestClient, kind: str):
    invoice = issue_invoice(client)
    delivery_note = client.get(f"/api/v1/documents/{invoice['id']}").json()["parent_id"]
    order = client.get(f"/api/v1/documents/{delivery_note}").json()["parent_id"]
    target = {
        "order": order,
        "delivery_note": delivery_note,
        "corrective_invoice": correct(client, invoice["id"]).json()["id"],
        "missing": str(uuid.uuid4()),
    }[kind]

    response = correct(client, target)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REFERENCE_NOT_FOUND"


def test_the_corrective_invoice_announces_itself_as_an_invoice_that_was_issued(
    client: TestClient, publisher
):
    invoice = issue_invoice(client)
    delivery_note_id = client.get(f"/api/v1/documents/{invoice['id']}").json()["parent_id"]
    order_id = client.get(f"/api/v1/documents/{delivery_note_id}").json()["parent_id"]
    publisher.events.clear()

    created = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 2}]).json()

    [(stream, fields)] = publisher.events
    assert stream == "invoice.issued"
    assert fields == {
        "invoice_id": created["id"],
        "number": created["number"],
        # The delivery note and the order are those of the invoice it rectifies.
        "delivery_note_id": delivery_note_id,
        "order_id": order_id,
        "total": "-25.41",
        "issued_at": fields["issued_at"],
    }
    issued_at = datetime.fromisoformat(fields["issued_at"])
    assert issued_at.tzinfo is not None
    assert issued_at.astimezone(UTC).date() == datetime.now(UTC).date()


def test_no_event_is_published_when_the_request_is_rejected(client: TestClient, publisher):
    invoice = issue_invoice(client)
    publisher.events.clear()

    correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 99}])
    correct(client, str(uuid.uuid4()))

    assert publisher.events == []


def test_it_is_issued_even_if_the_event_cannot_be_published(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    class DownPublisher:
        def publish(self, stream: str, fields: dict[str, str]) -> None:
            raise EventPublishError("redis is down")

    invoice = issue_invoice(client)
    app.dependency_overrides[get_publisher] = lambda: DownPublisher()

    with caplog.at_level(logging.ERROR):
        response = correct(client, invoice["id"])

    assert response.status_code == 201
    assert "was not published" in caplog.text


def test_a_corrective_invoice_cannot_be_cancelled(client: TestClient):
    invoice = issue_invoice(client)
    created = correct(client, invoice["id"]).json()

    response = client.post(f"/api/v1/documents/{created['id']}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_CANCELLABLE"
    assert client.get(f"/api/v1/documents/{created['id']}").json()["status"] == "ISSUED"


def test_the_discrepancies_of_a_corrective_invoice_do_not_count_what_it_takes_back(
    client: TestClient,
):
    invoice = issue_invoice(client)
    created = correct(client, invoice["id"], lines=[{"invoice_line": 1, "quantity": 2}]).json()

    body = client.get(f"/api/v1/documents/{created['id']}/discrepancies").json()

    assert [document["type"] for document in body["compared"]] == [
        "ORDER",
        "DELIVERY_NOTE",
        "INVOICE",
        "CORRECTIVE_INVOICE",
    ]
    # Only the two partial deliveries (4 of 10 widgets, 3 of 4 gadgets) remain: nothing about the
    # correction.
    assert [d["target"]["document_type"] for d in body["discrepancies"]] == [
        "DELIVERY_NOTE",
        "DELIVERY_NOTE",
    ]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "reason"),
        ({"reason": "   "}, "reason"),
        ({"reason": "x" * 301}, "reason"),
        ({"reason": "ok", "lines": []}, "lines"),
        ({"reason": "ok", "lines": [{"invoice_line": 1, "quantity": 0}]}, "quantity"),
        ({"reason": "ok", "lines": [{"invoice_line": 1, "quantity": -1}]}, "quantity"),
        ({"reason": "ok", "lines": [{"invoice_line": 1, "quantity": 1.0001}]}, "quantity"),
        ({"reason": "ok", "lines": [{"invoice_line": 0, "quantity": 1}]}, "invoice_line"),
        ({"reason": "ok", "lines": [{"invoice_line": 1}]}, "quantity"),
        (
            {
                "reason": "ok",
                "lines": [
                    {"invoice_line": 1, "quantity": 1},
                    {"invoice_line": 1, "quantity": 2},
                ],
            },
            "only appear once",
        ),
        ({"reason": "ok", "total": 5}, "total"),
        ({"reason": "ok", "number": "R-1"}, "number"),
    ],
)
def test_invalid_requests_return_422(offline_client: TestClient, body: dict, field: str):
    response = (
        correct(offline_client, uuid.uuid4(), **body)
        if "reason" in body
        else (offline_client.post(f"/api/v1/invoices/{uuid.uuid4()}/corrections", json=body))
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert field in error["message"]


@pytest.mark.parametrize("invoice_id", ["not-a-uuid", "123"])
def test_an_identifier_that_is_not_a_uuid_returns_422(offline_client: TestClient, invoice_id: str):
    response = correct(offline_client, invoice_id)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "invoice_id" in error["message"]


def test_docs_describe_the_corrective_invoice_and_its_errors(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/invoices/{invoice_id}/corrections"]["post"]
    assert "201" in operation["responses"]
    for status in ("404", "422"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
    schemas = spec["components"]["schemas"]
    for name in ("CorrectionCreate", "CorrectionLineIn", "CorrectionRead", "CorrectionLineOut"):
        properties = schemas[name]["properties"]
        assert all("description" in definition for definition in properties.values()), name
