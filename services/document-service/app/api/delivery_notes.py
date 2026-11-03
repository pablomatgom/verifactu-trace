from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.delivery_notes import (
    DeliveryNoteCreate,
    DeliveryNoteLineOut,
    DeliveryNoteRead,
)
from app.api.schemas.orders import CustomerOut
from app.db import get_session
from app.models import Document
from app.services import delivery_note_service
from app.services.delivery_note_service import DeliveredLineData, DeliveryNoteData

router = APIRouter(prefix="/api/v1/delivery-notes", tags=["delivery-notes"])


def _to_read(delivery_note: Document) -> DeliveryNoteRead:
    # parent_id is None only for an order, and a delivery note always has its order.
    assert delivery_note.parent_id is not None
    return DeliveryNoteRead(
        id=delivery_note.id,
        type=delivery_note.type,
        number=delivery_note.number,
        status=delivery_note.status,
        issue_date=delivery_note.issue_date,
        order_id=delivery_note.parent_id,
        customer=CustomerOut(
            name=delivery_note.customer_name, tax_id=delivery_note.customer_tax_id
        ),
        lines=[
            DeliveryNoteLineOut(
                position=line.position,
                # source_line is the order line this one delivers.
                order_line=line.source_line.position,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
            )
            for line in delivery_note.lines
        ],
        total_net=delivery_note.total_net,
        total_vat=delivery_note.total_vat,
        total=delivery_note.total,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register a delivery note",
    response_description="The delivery note, with its id, its number and the calculated amounts.",
    responses={
        404: error_response("The order does not exist (code REFERENCE_NOT_FOUND)."),
        422: error_response(
            "The request is not valid (VALIDATION_ERROR), refers to a line the order does not "
            "have (INVALID_ORDER_LINE), or delivers more than was ordered (QUANTITY_EXCEEDED)."
        ),
    },
)
def create_delivery_note(
    body: DeliveryNoteCreate, session: Annotated[Session, Depends(get_session)]
) -> DeliveryNoteRead:
    """Register a delivery note that references an order.

    Each line says how much of an order line is delivered. An order can be delivered in several
    delivery notes, but the quantities of all of them added up cannot exceed the ordered ones.
    The server copies the customer and the prices from the order and assigns the id, the number
    (series `A`), the date and the amounts.
    """
    data = DeliveryNoteData(
        order_id=body.order_id,
        lines=[
            DeliveredLineData(order_line=line.order_line, quantity=line.quantity)
            for line in body.lines
        ],
    )
    delivery_note = delivery_note_service.create_delivery_note(session, data)
    # Construct the response here while the session is still active to
    # avoid database errors when accessing lazy-loaded relationships later.
    return _to_read(delivery_note)
