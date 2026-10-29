from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.schemas.common import VALIDATION_ERROR_RESPONSE
from app.api.schemas.orders import CustomerOut, OrderCreate, OrderLineOut, OrderRead
from app.db import get_session
from app.models import Document
from app.services import order_service
from app.services.order_service import OrderData, OrderLineData

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


def _to_read(order: Document) -> OrderRead:
    return OrderRead(
        id=order.id,
        type=order.type,
        number=order.number,
        status=order.status,
        issue_date=order.issue_date,
        customer=CustomerOut(name=order.customer_name, tax_id=order.customer_tax_id),
        lines=[OrderLineOut.model_validate(line) for line in order.lines],
        total_net=order.total_net,
        total_vat=order.total_vat,
        total=order.total,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register an order",
    response_description="The order, with its id, its number and the calculated amounts.",
    responses=VALIDATION_ERROR_RESPONSE,
)
def create_order(body: OrderCreate, session: Annotated[Session, Depends(get_session)]) -> OrderRead:
    """Register an order with its customer and lines.

    The server assigns the id, the number (series `P`, year and a correlative counter), the
    date and the amounts. The request is rejected with a 422 if the order has no lines, a
    quantity is not greater than zero, a price is negative, or a field is missing or unknown.
    """
    # The service does not know the API schemas: translate them into its own plain data.
    data = OrderData(
        customer_name=body.customer.name,
        customer_tax_id=body.customer.tax_id,
        lines=[
            OrderLineData(
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
            )
            for line in body.lines
        ],
    )
    order = order_service.create_order(session, data)
    # Construct the response here while the session is still active to
    # avoid database errors when accessing lazy-loaded relationships later.
    return _to_read(order)
