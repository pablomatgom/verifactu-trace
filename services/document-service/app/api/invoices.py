from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.invoices import InvoiceCreate, InvoiceLineOut, InvoiceRead
from app.api.schemas.orders import CustomerOut
from app.db import get_session
from app.events import EventPublisher, get_publisher
from app.models import Document
from app.services import invoice_service
from app.services.invoice_service import InvoiceData

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


def _to_read(invoice: Document) -> InvoiceRead:
    # An invoice always has its delivery note, and the delivery note its order.
    delivery_note = invoice.parent
    assert delivery_note is not None
    assert delivery_note.parent_id is not None
    return InvoiceRead(
        id=invoice.id,
        type=invoice.type,
        number=invoice.number,
        status=invoice.status,
        issue_date=invoice.issue_date,
        delivery_note_id=delivery_note.id,
        order_id=delivery_note.parent_id,
        customer=CustomerOut(name=invoice.customer_name, tax_id=invoice.customer_tax_id),
        lines=[
            InvoiceLineOut(
                position=line.position,
                # source_line is the delivery note line this one bills.
                delivery_note_line=line.source_line.position,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
            )
            for line in invoice.lines
        ],
        total_net=invoice.total_net,
        total_vat=invoice.total_vat,
        total=invoice.total,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Issue an invoice",
    response_description="The invoice, with its id, its number and the calculated amounts.",
    responses={
        404: error_response("The delivery note does not exist (code REFERENCE_NOT_FOUND)."),
        422: error_response(
            "The request is not valid (VALIDATION_ERROR), or the delivery note already has an "
            "invoice (DELIVERY_NOTE_ALREADY_INVOICED)."
        ),
    },
)
def create_invoice(
    body: InvoiceCreate,
    session: Annotated[Session, Depends(get_session)],
    publisher: Annotated[EventPublisher, Depends(get_publisher)],
) -> InvoiceRead:
    """Issue the invoice of a delivery note.

    The invoice bills what the delivery note delivered, with the customer and the prices of the
    order. The server assigns the id, the number (series `F`, year and a correlative counter
    without gaps), the date and the amounts. A delivery note can only be invoiced once.

    Once the invoice is saved, the event `invoice.issued` is published so that the other services
    can react to it. If it cannot be published the invoice is still issued.
    """
    invoice = invoice_service.create_invoice(
        session, publisher, InvoiceData(delivery_note_id=body.delivery_note_id)
    )
    # Construct the response here while the session is still active to
    # avoid database errors when accessing lazy-loaded relationships later.
    return _to_read(invoice)
