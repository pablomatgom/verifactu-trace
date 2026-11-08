import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Submission, SubmissionStatus

# The tests share the database, so each one works with the submissions of its own invoices
# and filters by something that only they have: the status plus the creation date.
EPOCH = datetime(2030, 1, 1, tzinfo=UTC)


def save_all(
    session: Session, statuses: list[SubmissionStatus], start: datetime
) -> list[Submission]:
    """One submission per status, created a minute apart from `start` (the first is the oldest)."""
    submissions = []
    for number, status in enumerate(statuses):
        submission = Submission(
            invoice_id=uuid.uuid4(),
            status=status,
            created_at=start + timedelta(minutes=number),
        )
        session.add(submission)
        submissions.append(submission)
    session.flush()
    return submissions


def search(client: TestClient, **params):
    return client.get("/api/v1/submissions", params=params)


def ids(response) -> list[str]:
    return [item["id"] for item in response.json()["items"]]


def test_the_list_shows_the_submissions_newest_first_with_the_page_data(
    client: TestClient, session: Session
):
    # Far in the future, so these are the newest of the table whatever else it holds.
    first, second, third = save_all(session, [SubmissionStatus.FAILED] * 3, EPOCH)

    response = search(client, size=3)

    assert response.status_code == 200
    body = response.json()
    assert ids(response) == [str(third.id), str(second.id), str(first.id)]
    assert (body["page"], body["size"]) == (1, 3)
    assert body["total"] >= 3


def test_filtering_by_status_returns_only_the_submissions_in_that_state(
    client: TestClient, session: Session
):
    start = EPOCH + timedelta(days=1)
    pending, failed, accepted, failed_again = save_all(
        session,
        [
            SubmissionStatus.PENDING,
            SubmissionStatus.FAILED,
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.FAILED,
        ],
        start,
    )

    response = search(client, status="FAILED", size=100)

    listed = ids(response)
    assert str(failed.id) in listed and str(failed_again.id) in listed
    assert str(pending.id) not in listed and str(accepted.id) not in listed
    assert {item["status"] for item in response.json()["items"]} == {"FAILED"}


def test_total_counts_the_submissions_that_meet_the_filters_in_all_the_pages(
    client: TestClient, session: Session
):
    session.execute(update(Submission).values(status=SubmissionStatus.ACCEPTED))
    save_all(session, [SubmissionStatus.RETRYING] * 5, EPOCH)

    body = search(client, status="RETRYING", size=2).json()

    assert (body["total"], len(body["items"])) == (5, 2)


def test_page_and_size_return_the_page_that_was_asked_for(client: TestClient, session: Session):
    session.execute(update(Submission).values(status=SubmissionStatus.ACCEPTED))
    submissions = save_all(session, [SubmissionStatus.FAILED] * 5, EPOCH)
    newest_first = [str(submission.id) for submission in reversed(submissions)]

    pages = [ids(search(client, status="FAILED", page=page, size=2)) for page in (1, 2, 3)]

    assert pages == [newest_first[0:2], newest_first[2:4], newest_first[4:5]]


def test_a_page_past_the_end_is_empty_but_keeps_the_total(client: TestClient, session: Session):
    session.execute(update(Submission).values(status=SubmissionStatus.ACCEPTED))
    save_all(session, [SubmissionStatus.FAILED] * 3, EPOCH)

    body = search(client, status="FAILED", page=9, size=2).json()

    assert (body["items"], body["total"], body["page"]) == ([], 3, 9)


def test_the_order_is_the_same_when_submissions_were_created_at_the_same_time(
    client: TestClient, session: Session
):
    # The id breaks the tie, so turning the pages never repeats or skips a submission.
    session.execute(update(Submission).values(status=SubmissionStatus.ACCEPTED))
    save_all(session, [SubmissionStatus.FAILED] * 5, EPOCH)
    session.execute(
        update(Submission).where(Submission.status == "FAILED").values(created_at=EPOCH)
    )

    seen = [
        i for page in (1, 2, 3) for i in ids(search(client, status="FAILED", page=page, size=2))
    ]

    assert len(seen) == len(set(seen)) == 5
    assert seen == sorted(seen, reverse=True)


def test_the_filters_add_up(client: TestClient, session: Session):
    failed, accepted = save_all(
        session, [SubmissionStatus.FAILED, SubmissionStatus.ACCEPTED], EPOCH
    )

    assert ids(search(client, invoice_id=failed.invoice_id, status="FAILED")) == [str(failed.id)]
    assert ids(search(client, invoice_id=accepted.invoice_id, status="FAILED")) == []


def test_filtering_by_an_invoice_returns_its_submission(client: TestClient, session: Session):
    submission, _ = save_all(session, [SubmissionStatus.SENT] * 2, EPOCH)

    body = search(client, invoice_id=submission.invoice_id).json()

    assert [item["id"] for item in body["items"]] == [str(submission.id)]
    assert body["total"] == 1


def test_the_items_have_the_shape_of_a_single_submission(client: TestClient, session: Session):
    submission, *_ = save_all(session, [SubmissionStatus.RETRYING], EPOCH)

    item = search(client, invoice_id=submission.invoice_id).json()["items"][0]

    assert item == client.get(f"/api/v1/submissions/{submission.id}").json()


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"status": "DONE"}, "status"),
        ({"status": "failed"}, "status"),
        ({"invoice_id": "123"}, "invoice_id"),
        ({"page": 0}, "page"),
        ({"page": "x"}, "page"),
        ({"size": 0}, "size"),
        ({"size": 101}, "size"),
    ],
)
def test_invalid_parameters_return_422(offline_client: TestClient, params: dict, field: str):
    response = search(offline_client, **params)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert field in error["message"]


def test_the_biggest_page_allowed_is_accepted(client: TestClient):
    assert search(client, size=100).status_code == 200


def test_docs_describe_the_list_its_parameters_and_its_error(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/submissions"]["get"]
    schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ErrorResponse")
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"invoice_id", "status", "page", "size"}
    assert all("description" in parameter for parameter in parameters.values())
    page = spec["components"]["schemas"]["SubmissionPageRead"]["properties"]
    assert set(page) == {"items", "page", "size", "total"}
