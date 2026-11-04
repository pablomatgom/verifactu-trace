import re
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.services.hashing import GENESIS_HASH, canonical_content, compute_hash


def post(client: TestClient, **changes):
    body = {"document_id": str(uuid.uuid4()), "event_type": "INVOICE_ISSUED", **changes}
    return client.post("/api/v1/traceability/events", json=body)


def test_record_an_event_returns_201_with_its_sequence_and_hashes(client: TestClient):
    document_id = str(uuid.uuid4())

    response = post(
        client,
        document_id=document_id,
        occurred_at="2026-10-14T09:30:00Z",
        payload={"number": "F-2026-000001", "total": "380.82"},
    )

    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert body["document_id"] == document_id
    assert body["event_type"] == "INVOICE_ISSUED"
    assert body["occurred_at"] == "2026-10-14T09:30:00Z"
    assert body["payload"] == {"number": "F-2026-000001", "total": "380.82"}
    assert body["sequence"] == 1
    # The first event of a document uses the initial hash as its previous hash.
    assert body["previous_hash"] == GENESIS_HASH
    assert re.fullmatch(r"[0-9a-f]{64}", body["hash"])


def test_the_hash_is_the_sha256_of_the_content_and_the_previous_hash(client: TestClient):
    document_id = uuid.uuid4()
    occurred_at = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)

    body = post(
        client, document_id=str(document_id), occurred_at="2026-10-14T09:30:00Z", payload={"a": 1}
    ).json()

    content = canonical_content(document_id, 1, "INVOICE_ISSUED", occurred_at, {"a": 1})
    assert body["hash"] == compute_hash(content, GENESIS_HASH)


def test_events_of_the_same_document_are_chained_in_the_order_they_arrive(client: TestClient):
    document_id = str(uuid.uuid4())

    first = post(client, document_id=document_id, event_type="A").json()
    second = post(client, document_id=document_id, event_type="B").json()
    third = post(client, document_id=document_id, event_type="C").json()

    assert [first["sequence"], second["sequence"], third["sequence"]] == [1, 2, 3]
    assert second["previous_hash"] == first["hash"]
    assert third["previous_hash"] == second["hash"]


def test_a_new_document_starts_its_own_chain(client: TestClient):
    post(client)

    other = post(client).json()

    assert other["sequence"] == 1
    assert other["previous_hash"] == GENESIS_HASH


def test_the_date_and_the_payload_are_optional(client: TestClient):
    before = datetime.now(UTC)

    body = post(client).json()

    assert body["payload"] == {}
    # Without a date the server uses now.
    assert before <= datetime.fromisoformat(body["occurred_at"]) <= datetime.now(UTC)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "document_id"),
        ({"document_id": "not-a-uuid", "event_type": "A"}, "document_id"),
        ({"document_id": str(uuid.uuid4())}, "event_type"),
        ({"document_id": str(uuid.uuid4()), "event_type": "  "}, "event_type"),
        ({"document_id": str(uuid.uuid4()), "event_type": "A" * 101}, "event_type"),
        ({"document_id": str(uuid.uuid4()), "event_type": "A", "occurred_at": "x"}, "occurred_at"),
        # A date without a time zone is ambiguous, and the hash covers the exact instant.
        (
            {
                "document_id": str(uuid.uuid4()),
                "event_type": "A",
                "occurred_at": "2026-10-14T09:30",
            },
            "occurred_at",
        ),
        ({"document_id": str(uuid.uuid4()), "event_type": "A", "payload": []}, "payload"),
        ({"document_id": str(uuid.uuid4()), "event_type": "A", "hash": "x"}, "hash"),
        ({"document_id": str(uuid.uuid4()), "event_type": "A", "sequence": 5}, "sequence"),
    ],
)
def test_invalid_requests_are_rejected_with_422(offline_client: TestClient, body: dict, field: str):
    response = offline_client.post("/api/v1/traceability/events", json=body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert field in error["message"]


def test_a_body_that_is_not_json_is_rejected_with_422(offline_client: TestClient):
    response = offline_client.post(
        "/api/v1/traceability/events",
        content="{not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
