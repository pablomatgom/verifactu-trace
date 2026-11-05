from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.submissions import SubmissionCreate, SubmissionRead
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
