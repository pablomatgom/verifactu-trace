import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Submission, SubmissionStatus

NEXT_ATTEMPT = datetime(2026, 10, 14, 9, 34, tzinfo=UTC)


def save(session: Session, **values) -> Submission:
    """Save a submission straight in the database, in whatever state the test needs."""
    submission = Submission(invoice_id=values.pop("invoice_id", uuid.uuid4()), **values)
    session.add(submission)
    session.flush()
    return submission


def get(client: TestClient, submission_id: uuid.UUID | str):
    return client.get(f"/api/v1/submissions/{submission_id}")


def list_for(client: TestClient, invoice_id: uuid.UUID | str):
    return client.get("/api/v1/submissions", params={"invoice_id": str(invoice_id)})


def test_a_retrying_submission_shows_its_status_attempts_and_last_error(
    client: TestClient, session: Session
):
    submission = save(
        session,
        invoice_number="F-2026-000001",
        status=SubmissionStatus.RETRYING,
        attempts=2,
        next_attempt_at=NEXT_ATTEMPT,
        last_error="AEAT_UNAVAILABLE",
    )

    response = get(client, submission.id)

    assert response.status_code == 200
    assert response.json() == {
        "id": str(submission.id),
        "invoice_id": str(submission.invoice_id),
        "invoice_number": "F-2026-000001",
        "status": "RETRYING",
        "attempts": 2,
        "next_attempt_at": "2026-10-14T09:34:00Z",
        "last_error": "AEAT_UNAVAILABLE",
        "aeat_reference": None,
    }


def test_an_accepted_submission_shows_the_reference_of_the_aeat(
    client: TestClient, session: Session
):
    submission = save(
        session,
        status=SubmissionStatus.ACCEPTED,
        attempts=1,
        aeat_reference="AEAT-123",
    )

    body = get(client, submission.id).json()

    assert (body["status"], body["attempts"], body["aeat_reference"]) == ("ACCEPTED", 1, "AEAT-123")
    assert body["next_attempt_at"] is None
    assert body["last_error"] is None


def test_a_submission_that_does_not_exist_returns_404(client: TestClient):
    missing = uuid.uuid4()

    response = get(client, missing)

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "SUBMISSION_NOT_FOUND"
    assert str(missing) in error["message"]


def test_the_status_follows_the_submission_as_the_worker_changes_it(
    client: TestClient, session: Session
):
    submission = save(session, status=SubmissionStatus.PENDING)
    assert get(client, submission.id).json()["status"] == "PENDING"

    submission.status = SubmissionStatus.ACCEPTED
    submission.attempts = 1
    session.flush()

    body = get(client, submission.id).json()
    assert (body["status"], body["attempts"]) == ("ACCEPTED", 1)


def test_a_submission_requested_through_the_api_can_be_read_back(client: TestClient):
    invoice_id = str(uuid.uuid4())
    created = client.post("/api/v1/submissions", json={"invoice_id": invoice_id}).json()

    assert get(client, created["id"]).json() == created


def test_the_submissions_of_an_invoice_are_listed_by_invoice_id(
    client: TestClient, session: Session
):
    submission = save(session, status=SubmissionStatus.FAILED, attempts=5, last_error="X")
    save(session)  # the submission of another invoice must not appear

    response = list_for(client, submission.invoice_id)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(submission.id)]
    assert (items[0]["status"], items[0]["attempts"]) == ("FAILED", 5)


def test_an_invoice_without_submissions_gets_an_empty_list(client: TestClient):
    response = list_for(client, uuid.uuid4())

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}


def test_the_list_has_the_same_shape_as_a_single_submission(client: TestClient, session: Session):
    submission = save(session, status=SubmissionStatus.SENT, attempts=1)

    item = list_for(client, submission.invoice_id).json()["items"][0]

    assert item == get(client, submission.id).json()


@pytest.mark.parametrize("submission_id", ["not-a-uuid", "123"])
def test_an_identifier_that_is_not_a_uuid_returns_422(
    offline_client: TestClient, submission_id: str
):
    response = get(offline_client, submission_id)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "submission_id" in error["message"]


def test_the_invoice_id_of_the_listing_must_be_a_uuid(offline_client: TestClient):
    response = offline_client.get("/api/v1/submissions", params={"invoice_id": "not-a-uuid"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "invoice_id" in error["message"]


def test_docs_describe_the_query_of_one_submission_and_its_errors(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/submissions/{submission_id}"]["get"]
    for status in ("404", "422"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
