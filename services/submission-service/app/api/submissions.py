import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.submissions import SubmissionCreate, SubmissionList, SubmissionRead
from app.db import get_session
from app.services import submission_service
from app.services.submission_service import SubmissionData

router = APIRouter(prefix="/api/v1/submissions", tags=["submissions"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request the submission of an invoice",
    response_description="The submission, waiting to be sent.",
    responses={
        409: error_response(
            "The invoice already has a submission (code SUBMISSION_ALREADY_EXISTS)."
        ),
        422: error_response("The request is not valid (code VALIDATION_ERROR)."),
    },
)
def create_submission(
    body: SubmissionCreate, session: Annotated[Session, Depends(get_session)]
) -> SubmissionRead:
    """Ask for the invoice to be sent to the AEAT.

    Normally this is not needed: every invoice that is issued is submitted automatically when
    this service receives the `invoice.issued` event. The request answers `202` because the
    invoice is not sent yet: it is registered as PENDING and a background worker sends it, and
    retries it with a growing wait if the AEAT fails. The submission is not checked against the
    invoices themselves, which belong to another service.
    """
    submission = submission_service.create_submission(
        session, SubmissionData(invoice_id=body.invoice_id)
    )
    # Build the response while the session is still open.
    return SubmissionRead.model_validate(submission, from_attributes=True)


@router.get(
    "/{submission_id}",
    summary="Get a submission",
    response_description="The submission, with its status, its attempts and its last error.",
    responses={
        404: error_response("The submission does not exist (code SUBMISSION_NOT_FOUND)."),
        422: error_response("The identifier is not a valid UUID (code VALIDATION_ERROR)."),
    },
)
def get_submission(
    submission_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> SubmissionRead:
    """Get where a submission to the AEAT is.

    `status` says whether the invoice was accepted or rejected, is waiting or failed for good.
    While it is RETRYING, `next_attempt_at` says when it will be tried again and `last_error`
    why the last attempt failed.
    """
    submission = submission_service.get_submission(session, submission_id)
    # Build the response while the session is still open.
    return SubmissionRead.model_validate(submission, from_attributes=True)


@router.get(
    "",
    summary="List the submissions of an invoice",
    response_description="The submissions of the invoice.",
    responses={
        422: error_response(
            "`invoice_id` is missing or is not a valid UUID (code VALIDATION_ERROR)."
        ),
    },
)
def list_submissions(
    invoice_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> SubmissionList:
    """List the submissions of an invoice.

    An invoice has one submission at most, so the list has one item or none. An invoice that
    has no submission, or that does not exist, gets an empty list and not a 404: a filter that
    matches nothing is not an error. `invoice_id` is required for now.
    """
    submissions = submission_service.list_by_invoice(session, invoice_id)
    return SubmissionList(
        items=[SubmissionRead.model_validate(item, from_attributes=True) for item in submissions]
    )
