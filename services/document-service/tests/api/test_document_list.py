import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, update
from sqlalchemy.orm import Session

from app.models import Document

# The database of the tests may hold other documents, so every test works with a customer of its
# own (a tax id nobody else uses) and filters by it.


def new_tax_id() -> str:
    return "T" + uuid.uuid4().hex[:10].upper()


def create_order(client: TestClient, tax_id: str, name: str = "Acme S.L.") -> dict:
    response = client.post(
        "/api/v1/orders",
        json={
            "customer": {"name": name, "tax_id": tax_id},
            "lines": [{"description": "Widget", "quantity": 2, "unit_price": 10.5}],
        },
    )
    assert response.status_code == 201
    return response.json()


def create_chain(client: TestClient, tax_id: str) -> tuple[dict, dict, dict]:
    """An order, its delivery note and its invoice, all for the same customer."""
    order = create_order(client, tax_id)
    delivery_note = client.post(
        "/api/v1/delivery-notes",
        json={"order_id": order["id"], "lines": [{"order_line": 1, "quantity": 2}]},
    ).json()
    invoice = client.post("/api/v1/invoices", json={"delivery_note_id": delivery_note["id"]}).json()
    return order, delivery_note, invoice


def set_issue_date(session: Session, document: dict, issue_date: date) -> None:
    """Move a document to another day, since the server always issues them with today's date."""
    session.execute(
        update(Document)
        .where(Document.id == uuid.UUID(document["id"]))
        .values(issue_date=issue_date)
    )
    session.expire_all()


def numbers(response) -> list[str]:
    return [item["number"] for item in response.json()["items"]]


def list_documents(client: TestClient, **params):
    return client.get("/api/v1/documents", params=params)


def test_list_returns_the_page_with_its_envelope(client: TestClient):
    tax_id = new_tax_id()
    order = create_order(client, tax_id)

    response = list_documents(client, customer=tax_id)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": order["id"],
                "type": "ORDER",
                "number": order["number"],
                "status": "ISSUED",
                "issue_date": order["issue_date"],
                "parent_id": None,
                "customer": {"name": "Acme S.L.", "tax_id": tax_id},
                "total_net": 21.0,
                "total_vat": 4.41,
                "total": 25.41,
            }
        ],
        "page": 1,
        "size": 20,
        "total": 1,
    }


def test_list_does_not_include_the_lines(client: TestClient):
    tax_id = new_tax_id()
    create_order(client, tax_id)

    item = list_documents(client, customer=tax_id).json()["items"][0]

    assert "lines" not in item


def test_list_without_matches_returns_an_empty_page(client: TestClient):
    response = list_documents(client, customer=new_tax_id())

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}


def test_filter_by_type(client: TestClient):
    tax_id = new_tax_id()
    order, delivery_note, invoice = create_chain(client, tax_id)

    for document in (order, delivery_note, invoice):
        response = list_documents(client, customer=tax_id, type=document["type"])
        assert numbers(response) == [document["number"]]


def test_filter_by_the_tax_id_of_the_customer(client: TestClient):
    tax_id = new_tax_id()
    mine = create_order(client, tax_id)
    create_order(client, new_tax_id())

    response = list_documents(client, customer=tax_id)

    assert numbers(response) == [mine["number"]]


def test_filter_by_part_of_the_name_of_the_customer_ignores_capitals(client: TestClient):
    name = "Zyxwv Distribuciones " + uuid.uuid4().hex[:8]
    mine = create_order(client, new_tax_id(), name=name)
    create_order(client, new_tax_id(), name="Other Customer")

    response = list_documents(client, customer="DISTRIBUCIONES " + name[-8:].upper())

    assert numbers(response) == [mine["number"]]


@pytest.mark.parametrize("wildcard", ["%", "_", "Zy%v"])
def test_the_wildcards_of_like_match_only_themselves(client: TestClient, wildcard: str):
    create_order(client, new_tax_id(), name="Zyxwv Distribuciones")

    response = list_documents(client, customer=wildcard)

    # Without escaping, % would match every customer and _ every name.
    assert response.json()["total"] == 0


def test_filter_by_series(client: TestClient):
    tax_id = new_tax_id()
    order, delivery_note, invoice = create_chain(client, tax_id)

    assert numbers(list_documents(client, customer=tax_id, series="P")) == [order["number"]]
    assert numbers(list_documents(client, customer=tax_id, series="A")) == [delivery_note["number"]]
    assert numbers(list_documents(client, customer=tax_id, series="F")) == [invoice["number"]]
    assert list_documents(client, customer=tax_id, series="Z").json()["total"] == 0


def test_filter_by_status(client: TestClient):
    tax_id = new_tax_id()
    create_chain(client, tax_id)

    assert list_documents(client, customer=tax_id, status="ISSUED").json()["total"] == 3


def test_filter_by_dates_includes_both_ends(client: TestClient, session: Session):
    tax_id = new_tax_id()
    days = {
        date(2026, 1, 10): create_order(client, tax_id),
        date(2026, 2, 10): create_order(client, tax_id),
        date(2026, 3, 10): create_order(client, tax_id),
    }
    for day, document in days.items():
        set_issue_date(session, document, day)

    def between(**params) -> set[str]:
        return {
            item["issue_date"]
            for item in list_documents(client, customer=tax_id, **params).json()["items"]
        }

    assert between(**{"from": "2026-02-10"}) == {"2026-02-10", "2026-03-10"}
    assert between(to="2026-02-10") == {"2026-01-10", "2026-02-10"}
    assert between(**{"from": "2026-02-10", "to": "2026-02-10"}) == {"2026-02-10"}
    assert between(**{"from": "2026-01-11", "to": "2026-02-09"}) == set()


def test_the_filters_add_up(client: TestClient):
    tax_id = new_tax_id()
    create_order(client, tax_id)
    _, delivery_note, _ = create_chain(client, tax_id)
    create_chain(client, new_tax_id())

    response = list_documents(client, customer=tax_id, type="DELIVERY_NOTE", series="A")

    assert numbers(response) == [delivery_note["number"]]


def test_the_newest_come_first(client: TestClient, session: Session):
    tax_id = new_tax_id()
    old = create_order(client, tax_id)
    middle = create_order(client, tax_id)
    new = create_order(client, tax_id)
    set_issue_date(session, old, date(2026, 1, 1))
    set_issue_date(session, middle, date(2026, 6, 1))
    set_issue_date(session, new, date(2026, 6, 1))

    response = list_documents(client, customer=tax_id)

    # Two documents of the same day are ordered by their number, the highest first.
    assert numbers(response) == [new["number"], middle["number"], old["number"]]


def test_pagination_splits_the_list_into_pages(client: TestClient):
    tax_id = new_tax_id()
    created = [create_order(client, tax_id)["number"] for _ in range(5)]
    newest_first = list(reversed(created))

    pages = [list_documents(client, customer=tax_id, page=page, size=2) for page in (1, 2, 3)]

    assert [numbers(page) for page in pages] == [
        newest_first[0:2],
        newest_first[2:4],
        newest_first[4:],
    ]
    for number, page in enumerate(pages, start=1):
        body = page.json()
        assert (body["page"], body["size"], body["total"]) == (number, 2, 5)


def test_a_page_past_the_end_is_empty_but_keeps_the_total(client: TestClient):
    tax_id = new_tax_id()
    create_order(client, tax_id)

    body = list_documents(client, customer=tax_id, page=2, size=20).json()

    assert body == {"items": [], "page": 2, "size": 20, "total": 1}


def test_the_list_costs_two_queries_whatever_the_size_of_the_page(
    client: TestClient, session: Session, engine: Engine
):
    tax_id = new_tax_id()
    for _ in range(4):
        create_order(client, tax_id)
    session.expire_all()
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = list_documents(client, customer=tax_id)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert response.json()["total"] == 4
    # One to count and one to read the page: nothing is loaded for each document.
    assert len(statements) == 2


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"type": "RECEIPT"}, "type"),
        ({"status": "DELETED"}, "status"),
        ({"from": "yesterday"}, "from"),
        ({"to": "2026-13-45"}, "to"),
        ({"page": 0}, "page"),
        ({"page": "one"}, "page"),
        ({"size": 0}, "size"),
        ({"size": 101}, "size"),
        ({"customer": ""}, "customer"),
        ({"series": "X" * 11}, "series"),
    ],
)
def test_invalid_parameters_are_rejected_with_422(
    offline_client: TestClient, params: dict, field: str
):
    response = list_documents(offline_client, **params)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert field in error["message"]


def test_a_start_date_after_the_end_date_is_rejected_with_422(client: TestClient):
    response = list_documents(client, **{"from": "2026-05-02", "to": "2026-05-01"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_DATE_RANGE"
    assert "2026-05-02" in error["message"]
    assert "2026-05-01" in error["message"]


def test_the_largest_page_size_is_accepted(client: TestClient):
    response = list_documents(client, customer=new_tax_id(), size=100)

    assert response.status_code == 200
    assert response.json()["size"] == 100
