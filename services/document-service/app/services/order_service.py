from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import Document, DocumentLine, DocumentStatus, DocumentType
from app.repositories import counter_repository, document_repository
from app.services.numbering import SERIES, format_number

CENT = Decimal("0.01")


@dataclass
class OrderLineData:
    description: str
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal


@dataclass
class OrderData:
    customer_name: str
    customer_tax_id: str
    lines: list[OrderLineData]


def _round(amount: Decimal) -> Decimal:
    """Round to cents the way invoices do: half up, not the banker's rounding of round()."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_totals(lines: list[OrderLineData]) -> tuple[Decimal, Decimal, Decimal]:
    """Return (net, vat, total). VAT is rounded per line so the totals add up to the lines."""
    net = Decimal("0.00")
    vat = Decimal("0.00")
    for line in lines:
        line_net = _round(line.quantity * line.unit_price)
        net += line_net
        vat += _round(line_net * line.vat_rate / 100)
    return net, vat, net + vat


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
