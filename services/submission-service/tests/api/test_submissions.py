import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Submission, SubmissionStatus


def post(client: TestClient, invoice_id: str | None = None):
    return client.post("/api/v1/submissions", json={"invoice_id": invoice_id or str(uuid.uuid4())})


def test_request_a_submission_returns_202_with_the_pending_submission(client: TestClient):
    invoice_id = str(uuid.uuid4())

    response = post(client, invoice_id)

    assert response.status_code == 202
    body = response.json()
    uuid.UUID(body["id"])
    assert body["invoice_id"] == invoice_id
    assert body["invoice_number"] is None
    assert body["status"] == "PENDING"
    assert body["attempts"] == 0
    assert body["last_error"] is None
    assert body["aeat_reference"] is None
    # It is due right away: the worker will take it on its next look.
    assert abs(datetime.fromisoformat(body["next_attempt_at"]) - datetime.now(UTC)).seconds < 60


def test_the_submission_is_saved(client: TestClient, session: Session):
    submission_id = post(client).json()["id"]

    submission = session.get(Submission, uuid.UUID(submission_id))

    assert submission is not None
    assert submission.status == SubmissionStatus.PENDING


def test_an_invoice_cannot_be_submitted_twice(client: TestClient):
    invoice_id = str(uuid.uuid4())
    post(client, invoice_id)

    response = post(client, invoice_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "SUBMISSION_ALREADY_EXISTS"
    assert invoice_id in error["message"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "invoice_id"),
        ({"invoice_id": "not-a-uuid"}, "invoice_id"),
        ({"invoice_id": str(uuid.uuid4()), "status": "ACCEPTED"}, "status"),
        ({"invoice_id": str(uuid.uuid4()), "attempts": 3}, "attempts"),
    ],
)
def test_invalid_requests_are_rejected_with_422(offline_client: TestClient, body: dict, field: str):
    response = offline_client.post("/api/v1/submissions", json=body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert field in error["message"]


def test_a_body_that_is_not_json_is_rejected_with_422(offline_client: TestClient):
    response = offline_client.post(
        "/api/v1/submissions", content="{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
