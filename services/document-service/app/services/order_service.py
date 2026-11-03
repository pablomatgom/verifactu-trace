from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models import Document, DocumentLine, DocumentStatus, DocumentType
from app.repositories import counter_repository, document_repository
from app.services.numbering import SERIES, format_number
from app.services.pricing import LineData, calculate_totals


@dataclass
class OrderData:
    customer_name: str
    customer_tax_id: str
    lines: list[LineData]


def create_order(session: Session, data: OrderData) -> Document:
    """Register an order: number it, calculate its amounts and save it in one transaction."""
    today = date.today()
    # The number, the order and its lines are committed together: if saving fails, the
    # counter is rolled back too and the number is not lost.
    series = SERIES[DocumentType.ORDER]
    number = counter_repository.next_number(session, series, today.year)
    net, vat, total = calculate_totals(data.lines)

    order = Document(
        type=DocumentType.ORDER,
        series=series,
        number=format_number(series, today.year, number),
        status=DocumentStatus.ISSUED,
        issue_date=today,
        customer_name=data.customer_name,
        customer_tax_id=data.customer_tax_id,
        total_net=net,
        total_vat=vat,
        total=total,
        lines=[
            DocumentLine(
                position=position,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
            )
            for position, line in enumerate(data.lines, start=1)
        ],
    )
    document_repository.add(session, order)
    session.commit()
    return order
