import uuid
from itertools import pairwise

from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from app.services.hashing import GENESIS_HASH


def record(client: TestClient, document_id: str, event_type: str, **changes) -> dict:
    body = {"document_id": document_id, "event_type": event_type, **changes}
    response = client.post("/api/v1/traceability/events", json=body)
    assert response.status_code == 201
    return response.json()


def history(client: TestClient, document_id: str):
    return client.get(f"/api/v1/traceability/documents/{document_id}/events")


def test_history_returns_the_events_of_the_document_ordered_by_sequence(client: TestClient):
    document_id = str(uuid.uuid4())
    first = record(client, document_id, "INVOICE_ISSUED", payload={"number": "F-2026-000001"})
    second = record(client, document_id, "SUBMISSION_ACCEPTED")
    third = record(client, document_id, "VERIFIED")

    response = history(client, document_id)

    assert response.status_code == 200
    assert response.json() == {"document_id": document_id, "events": [first, second, third]}


def test_the_order_is_the_sequence_not_the_date_of_the_event(client: TestClient):
    document_id = str(uuid.uuid4())
    # The second event says it happened before the first: it was recorded after it all the same.
    record(client, document_id, "A", occurred_at="2026-10-14T09:30:00Z")
    record(client, document_id, "B", occurred_at="2026-10-01T09:30:00Z")

    events = history(client, document_id).json()["events"]

    assert [(event["sequence"], event["event_type"]) for event in events] == [(1, "A"), (2, "B")]


def test_the_order_is_asked_of_the_database_and_does_not_depend_on_how_it_reads_the_rows(
    client: TestClient, session: Session, engine: Engine
):
    document_id = str(uuid.uuid4())
    record(client, document_id, "A")
    statements: list[str] = []

    def keep(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    # PostgreSQL happens to read these rows in order through the index of the document, but
    # without an ORDER BY nothing guarantees it. A test on the rows could not tell, so look at
    # the query.
    event.listen(engine, "before_cursor_execute", keep)
    try:
        history(client, document_id)
    finally:
        event.remove(engine, "before_cursor_execute", keep)

    assert len(statements) == 1
    assert "ORDER BY" in statements[0]
    assert statements[0].endswith("trace_events.sequence")


def test_the_history_keeps_the_chain_of_hashes_so_it_can_be_audited(client: TestClient):
    document_id = str(uuid.uuid4())
    for event_type in ("A", "B", "C"):
        record(client, document_id, event_type)

    events = history(client, document_id).json()["events"]

    assert events[0]["previous_hash"] == GENESIS_HASH
    for previous, current in pairwise(events):
        assert current["previous_hash"] == previous["hash"]


def test_history_only_includes_the_events_of_that_document(client: TestClient):
    mine = str(uuid.uuid4())
    record(client, mine, "A")
    record(client, str(uuid.uuid4()), "OTHER")
    record(client, mine, "B")

    events = history(client, mine).json()["events"]

    assert [event["event_type"] for event in events] == ["A", "B"]
    assert {event["document_id"] for event in events} == {mine}


def test_a_document_without_events_returns_404(client: TestClient):
    document_id = str(uuid.uuid4())

    response = history(client, document_id)

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "EVENTS_NOT_FOUND"
    assert document_id in error["message"]


def test_an_identifier_that_is_not_a_uuid_returns_422(offline_client: TestClient):
    response = history(offline_client, "not-a-uuid")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "document_id" in error["message"]


def test_docs_describe_the_errors_of_the_history_with_the_common_error_body(
    offline_client: TestClient,
):
    spec = offline_client.get("/openapi.json").json()

    responses = spec["paths"]["/api/v1/traceability/documents/{document_id}/events"]["get"][
        "responses"
    ]
    for status in ("404", "422"):
        schema = responses[status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
