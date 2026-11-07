import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.models import TraceEvent


def record(client: TestClient, document_id: str, event_type: str, **changes) -> dict:
    body = {"document_id": document_id, "event_type": event_type, **changes}
    response = client.post("/api/v1/traceability/events", json=body)
    assert response.status_code == 201
    return response.json()


def verify(client: TestClient, document_id: str):
    return client.get(f"/api/v1/traceability/documents/{document_id}/verification")


def record_chain(client: TestClient, length: int = 3) -> str:
    document_id = str(uuid.uuid4())
    for number in range(1, length + 1):
        record(client, document_id, f"EVENT_{number}", payload={"number": number})
    return document_id


def tamper(session: Session, document_id: str, sequence: int, **values) -> None:
    """Change a stored event directly in the database, as someone with access to it could."""
    session.execute(
        update(TraceEvent)
        .where(TraceEvent.document_id == uuid.UUID(document_id), TraceEvent.sequence == sequence)
        .values(**values)
    )
    session.expire_all()


def test_an_intact_chain_is_valid(client: TestClient):
    document_id = record_chain(client, length=3)

    response = verify(client, document_id)

    assert response.status_code == 200
    assert response.json() == {
        "document_id": document_id,
        "valid": True,
        "events_checked": 3,
        "first_invalid_sequence": None,
    }


def test_the_events_recorded_by_the_service_verify_after_a_round_trip_through_the_database(
    client: TestClient,
):
    # The hash is computed from what the service received and verified from what PostgreSQL
    # returns, so the values that could come back different (dates with microseconds in another
    # time zone, floats, nested data, accents) must not break it.
    document_id = str(uuid.uuid4())
    record(
        client,
        document_id,
        "INVOICE_ISSUED",
        occurred_at="2026-10-14T11:30:00.123456+02:00",
        payload={
            "total": 380.82,
            "ratio": 1.0,
            "big": 12345678901234567890,
            "customer": {"name": "Ñandú y Cía, S.L.", "tags": ["a", "ñ", None, True]},
            "empty": {},
        },
    )
    record(client, document_id, "NEXT")

    assert verify(client, document_id).json()["valid"] is True


def test_a_changed_payload_is_detected_on_that_event(client: TestClient, session: Session):
    document_id = record_chain(client, length=4)
    tamper(session, document_id, 2, payload={"number": 999})

    body = verify(client, document_id).json()

    assert body["valid"] is False
    assert body["first_invalid_sequence"] == 2
    assert body["events_checked"] == 4


def test_a_changed_event_type_is_detected(client: TestClient, session: Session):
    document_id = record_chain(client, length=3)
    tamper(session, document_id, 3, event_type="SOMETHING_ELSE")

    body = verify(client, document_id).json()

    assert (body["valid"], body["first_invalid_sequence"]) == (False, 3)


def test_a_changed_hash_is_detected(client: TestClient, session: Session):
    document_id = record_chain(client, length=3)
    tamper(session, document_id, 1, hash="f" * 64)

    body = verify(client, document_id).json()

    assert (body["valid"], body["first_invalid_sequence"]) == (False, 1)


def test_a_deleted_event_is_detected_on_the_one_after_it(client: TestClient, session: Session):
    document_id = record_chain(client, length=4)
    session.execute(
        delete(TraceEvent).where(
            TraceEvent.document_id == uuid.UUID(document_id), TraceEvent.sequence == 2
        )
    )
    session.expire_all()

    body = verify(client, document_id).json()

    assert (body["valid"], body["first_invalid_sequence"]) == (False, 3)
    assert body["events_checked"] == 3


def test_only_the_first_invalid_event_is_reported(client: TestClient, session: Session):
    document_id = record_chain(client, length=5)
    tamper(session, document_id, 4, payload={"number": 4000})
    tamper(session, document_id, 2, payload={"number": 2000})

    body = verify(client, document_id).json()

    assert body["first_invalid_sequence"] == 2


def test_verifying_one_document_does_not_look_at_the_chain_of_another(
    client: TestClient, session: Session
):
    broken = record_chain(client, length=3)
    intact = record_chain(client, length=3)
    tamper(session, broken, 2, payload={"number": 999})

    assert verify(client, broken).json()["valid"] is False
    assert verify(client, intact).json()["valid"] is True


def test_verifying_does_not_change_the_chain(client: TestClient, session: Session):
    document_id = record_chain(client, length=3)
    tamper(session, document_id, 2, payload={"number": 999})
    before = client.get(f"/api/v1/traceability/documents/{document_id}/events").json()

    verify(client, document_id)

    after = client.get(f"/api/v1/traceability/documents/{document_id}/events").json()
    assert after == before


def test_a_document_without_events_returns_404(client: TestClient):
    document_id = str(uuid.uuid4())

    response = verify(client, document_id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EVENTS_NOT_FOUND"


@pytest.mark.parametrize("document_id", ["not-a-uuid", "123"])
def test_an_identifier_that_is_not_a_uuid_returns_422(offline_client: TestClient, document_id: str):
    response = verify(offline_client, document_id)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "document_id" in error["message"]


def test_docs_describe_the_verification_and_its_errors(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/traceability/documents/{document_id}/verification"]["get"]
    for status in ("404", "422"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
    properties = spec["components"]["schemas"]["ChainVerificationRead"]["properties"]
    assert set(properties) == {"document_id", "valid", "events_checked", "first_invalid_sequence"}
    assert all("description" in definition for definition in properties.values())
