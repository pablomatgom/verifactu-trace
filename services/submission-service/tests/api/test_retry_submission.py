import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Submission, SubmissionStatus


def save(session: Session, status: SubmissionStatus, **values) -> Submission:
    submission = Submission(invoice_id=uuid.uuid4(), status=status, **values)
    session.add(submission)
    session.flush()
    return submission


def retry(client: TestClient, submission_id: uuid.UUID | str):
    return client.post(f"/api/v1/submissions/{submission_id}/retry")


@pytest.mark.parametrize("status", ["FAILED", "REJECTED"])
def test_retrying_a_failed_or_rejected_submission_returns_202_with_it_pending(
    client: TestClient, session: Session, status: str
):
    submission = save(
        session,
        SubmissionStatus(status),
        invoice_number="F-2026-000001",
        attempts=5,
        last_error="AEAT_UNAVAILABLE",
    )

    response = retry(client, submission.id)

    assert response.status_code == 202
    body = response.json()
    assert body["id"] == str(submission.id)
    assert body["invoice_number"] == "F-2026-000001"
    assert body["status"] == "PENDING"
    assert body["attempts"] == 0
    assert body["next_attempt_at"] is not None
    assert body["last_error"] == "AEAT_UNAVAILABLE"


def test_the_retry_is_visible_in_the_query_of_the_submission(client: TestClient, session: Session):
    submission = save(session, SubmissionStatus.FAILED, attempts=5)

    retry(client, submission.id)

    body = client.get(f"/api/v1/submissions/{submission.id}").json()
    assert (body["status"], body["attempts"]) == ("PENDING", 0)


def test_an_accepted_submission_cannot_be_retried(client: TestClient, session: Session):
    submission = save(session, SubmissionStatus.ACCEPTED, attempts=1, aeat_reference="SIM-1")

    response = retry(client, submission.id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "SUBMISSION_NOT_RETRYABLE"
    assert "ACCEPTED" in error["message"]
    body = client.get(f"/api/v1/submissions/{submission.id}").json()
    assert (body["status"], body["aeat_reference"]) == ("ACCEPTED", "SIM-1")


@pytest.mark.parametrize("status", ["PENDING", "SENT", "RETRYING"])
def test_a_submission_that_is_already_on_its_way_cannot_be_retried(
    client: TestClient, session: Session, status: str
):
    submission = save(session, SubmissionStatus(status), attempts=1)

    response = retry(client, submission.id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SUBMISSION_NOT_RETRYABLE"


def test_retrying_twice_in_a_row_is_refused_the_second_time(client: TestClient, session: Session):
    submission = save(session, SubmissionStatus.FAILED, attempts=5)

    assert retry(client, submission.id).status_code == 202
    assert retry(client, submission.id).status_code == 409


def test_a_submission_that_does_not_exist_returns_404(client: TestClient):
    response = retry(client, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SUBMISSION_NOT_FOUND"


@pytest.mark.parametrize("submission_id", ["not-a-uuid", "123"])
def test_an_identifier_that_is_not_a_uuid_returns_422(
    offline_client: TestClient, submission_id: str
):
    response = retry(offline_client, submission_id)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "submission_id" in error["message"]


def test_docs_describe_the_retry_and_its_errors(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/submissions/{submission_id}/retry"]["post"]
    assert "202" in operation["responses"]
    for status in ("404", "409", "422"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
