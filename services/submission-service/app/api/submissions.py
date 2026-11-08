import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.submissions import SubmissionCreate, SubmissionPageRead, SubmissionRead
from app.db import get_session
from app.models import SubmissionStatus
from app.repositories.submission_repository import SubmissionFilters
from app.services import submission_service
from app.services.submission_service import SubmissionData

router = APIRouter(prefix="/api/v1/submissions", tags=["submissions"])

MAX_PAGE_SIZE = 100


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
    summary="List submissions",
    response_description="One page of submissions, the newest first.",
    responses={
        422: error_response(
            "A parameter is not valid: `invoice_id` is not a UUID, `status` is unknown, `page` is "
            "less than 1 or `size` is outside 1 to 100 (code VALIDATION_ERROR)."
        ),
    },
)
def list_submissions(
    session: Annotated[Session, Depends(get_session)],
    invoice_id: Annotated[
        uuid.UUID | None, Query(description="Only the submission of this invoice.")
    ] = None,
    status: Annotated[
        SubmissionStatus | None, Query(description="Only the submissions in this state.")
    ] = None,
    page: Annotated[int, Query(ge=1, description="Number of the page, starting at 1.")] = 1,
    size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Submissions per page, up to 100.")
    ] = 20,
) -> SubmissionPageRead:
    """List submissions, narrowed by the filters that are given.

    `status=FAILED` or `status=PENDING` gives the invoices that have not reached the AEAT. The
    filters add up: a submission must meet all of them. The newest come first, and the page is
    asked for with `page` and `size`. The answer carries `total`, the number of submissions that
    meet the filters in all the pages, so a client knows how many pages there are. A page past
    the end is empty, and so is the list of an invoice that has no submission or does not exist.
    """
    result = submission_service.list_submissions(
        session, SubmissionFilters(invoice_id=invoice_id, status=status), page, size
    )
    return SubmissionPageRead(
        items=[SubmissionRead.model_validate(item, from_attributes=True) for item in result.items],
        page=result.page,
        size=result.size,
        total=result.total,
    )


@router.post(
    "/{submission_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a submission",
    response_description="The submission, waiting to be sent again.",
    responses={
        404: error_response("The submission does not exist (code SUBMISSION_NOT_FOUND)."),
        409: error_response(
            "The submission is not FAILED or REJECTED (code SUBMISSION_NOT_RETRYABLE)."
        ),
        422: error_response("The identifier is not a valid UUID (code VALIDATION_ERROR)."),
    },
)
def retry_submission(
    submission_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> SubmissionRead:
    """Send a FAILED or REJECTED submission again, for when its cause has been corrected.

    The answer is `202` because the invoice is not sent yet: the submission goes back to PENDING,
    with its attempts from zero, and the background worker sends it. Only a FAILED or REJECTED
    submission can be retried: one that was ACCEPTED must not be sent twice, and a PENDING, SENT or
    RETRYING one is already on its way. Asking again before the worker has taken it is a 409.
    """
    submission = submission_service.retry_submission(session, submission_id)
    # Build the response while the session is still open.
    return SubmissionRead.model_validate(submission, from_attributes=True)
