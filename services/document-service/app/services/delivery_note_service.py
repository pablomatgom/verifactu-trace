import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.exceptions import InvalidOrderLine, QuantityExceeded, ReferenceNotFound
from app.models import Document, DocumentLine, DocumentStatus, DocumentType
from app.repositories import counter_repository, document_repository
from app.services.numbering import SERIES, format_number
from app.services.pricing import LineData, calculate_totals


@dataclass
class DeliveredLineData:
    # Position of the order line that is delivered (1 is the first line of the order).
    order_line: int
    quantity: Decimal


@dataclass
class DeliveryNoteData:
    order_id: uuid.UUID
    lines: list[DeliveredLineData]


def _plain(quantity: Decimal) -> str:
    """Write a quantity without trailing zeros for the error messages: 6.000 -> 6."""
    return f"{quantity.normalize():f}"


def create_delivery_note(session: Session, data: DeliveryNoteData) -> Document:
    """Register a delivery note of an order: check it, number it and save it in one transaction."""
    # Locking the order makes the check and the insert one step for concurrent requests.
    order = document_repository.get_for_update(session, data.order_id, DocumentType.ORDER)
    if order is None:
        raise ReferenceNotFound(f"order {data.order_id} does not exist")

    order_lines = {line.position: line for line in order.lines}
    delivered = document_repository.delivered_quantities(session, order.id)

    # The quantities are added up across delivery notes, so an order can be delivered in parts
    # but never beyond what was ordered.
    for requested in data.lines:
        order_line = order_lines.get(requested.order_line)
        if order_line is None:
            raise InvalidOrderLine(f"the order has no line {requested.order_line}")
        already = delivered.get(order_line.id, Decimal(0))
        pending = order_line.quantity - already
        if requested.quantity > pending:
            raise QuantityExceeded(
                f"line {requested.order_line}: {_plain(requested.quantity)} requested but only "
                f"{_plain(pending)} pending (ordered {_plain(order_line.quantity)}, "
                f"already delivered {_plain(already)})"
            )

    today = date.today()
    series = SERIES[DocumentType.DELIVERY_NOTE]
    number = counter_repository.next_number(session, series, today.year)

    # Description, price and VAT are not sent by the client: they are the ones of the order line.
    lines = [(order_lines[requested.order_line], requested.quantity) for requested in data.lines]
    net, vat, total = calculate_totals(
        [
            LineData(line.description, quantity, line.unit_price, line.vat_rate)
            for line, quantity in lines
        ]
    )

    delivery_note = Document(
        type=DocumentType.DELIVERY_NOTE,
        series=series,
        number=format_number(series, today.year, number),
        status=DocumentStatus.ISSUED,
        issue_date=today,
        customer_name=order.customer_name,
        customer_tax_id=order.customer_tax_id,
        total_net=net,
        total_vat=vat,
        total=total,
        parent_id=order.id,
        lines=[
            DocumentLine(
                position=position,
                description=line.description,
                quantity=quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
                source_line_id=line.id,
            )
            for position, (line, quantity) in enumerate(lines, start=1)
        ],
    )
    document_repository.add(session, delivery_note)
    session.commit()
    return delivery_note
