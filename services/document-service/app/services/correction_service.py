import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.events import EventPublisher
from app.exceptions import (
    InvalidInvoiceLine,
    NothingToCorrect,
    QuantityExceeded,
    ReferenceNotFound,
)
from app.models import Document, DocumentLine, DocumentStatus, DocumentType
from app.repositories import counter_repository, document_repository
from app.services.invoice_service import announce_issued
from app.services.numbering import SERIES, format_number
from app.services.pricing import LineData, calculate_totals


@dataclass
class CorrectedLineData:
    # Position of the invoice line that is corrected (1 is the first line of the invoice).
    invoice_line: int
    quantity: Decimal


@dataclass
class CorrectionData:
    invoice_id: uuid.UUID
    reason: str
    # None means everything that has not been corrected yet.
    lines: list[CorrectedLineData] | None = None


def _plain(quantity: Decimal) -> str:
    """Write a quantity without trailing zeros for the error messages: 6.000 -> 6."""
    return f"{quantity.normalize():f}"


def create_correction(
    session: Session, publisher: EventPublisher, data: CorrectionData
) -> Document:
    """Issue a corrective invoice of an invoice: check it, number it, save it and announce it.

    The invoice is not modified. The corrective invoice takes units back with negative quantities,
    at the prices of the invoice, so its totals are negative. Several corrective invoices can
    follow one invoice, but together they cannot take back more than it billed.
    """
    # Locking the invoice makes the check of what is left to correct and the insert one step for
    # concurrent requests, as the delivery notes do with their order.
    invoice = document_repository.get_for_update(session, data.invoice_id, DocumentType.INVOICE)
    if invoice is None:
        raise ReferenceNotFound(f"invoice {data.invoice_id} does not exist")

    invoice_lines = {line.position: line for line in invoice.lines}
    corrected = document_repository.corrected_quantities(session, invoice.id)

    taken_back: list[tuple[DocumentLine, Decimal]] = []
    if data.lines is None:
        for line in invoice.lines:
            pending = line.quantity - corrected.get(line.id, Decimal(0))
            if pending > 0:
                taken_back.append((line, pending))
        if not taken_back:
            raise NothingToCorrect(f"invoice {invoice.number} has already been fully rectified")
    else:
        for requested in data.lines:
            line = invoice_lines.get(requested.invoice_line)
            if line is None:
                raise InvalidInvoiceLine(f"the invoice has no line {requested.invoice_line}")
            already = corrected.get(line.id, Decimal(0))
            pending = line.quantity - already
            if requested.quantity > pending:
                raise QuantityExceeded(
                    f"line {requested.invoice_line}: {_plain(requested.quantity)} to correct but "
                    f"only {_plain(pending)} left (billed {_plain(line.quantity)}, "
                    f"already corrected {_plain(already)})"
                )
            taken_back.append((line, requested.quantity))

    today = date.today()
    series = SERIES[DocumentType.CORRECTIVE_INVOICE]
    number = counter_repository.next_number(session, series, today.year)

    # Negative quantities give negative totals with the same rounding as any invoice.
    net, vat, total = calculate_totals(
        [
            LineData(line.description, -quantity, line.unit_price, line.vat_rate)
            for line, quantity in taken_back
        ]
    )
    correction = Document(
        type=DocumentType.CORRECTIVE_INVOICE,
        series=series,
        number=format_number(series, today.year, number),
        status=DocumentStatus.ISSUED,
        issue_date=today,
        customer_name=invoice.customer_name,
        customer_tax_id=invoice.customer_tax_id,
        total_net=net,
        total_vat=vat,
        total=total,
        parent_id=invoice.id,
        correction_reason=data.reason,
        lines=[
            DocumentLine(
                position=position,
                description=line.description,
                quantity=-quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
                source_line_id=line.id,
            )
            for position, (line, quantity) in enumerate(taken_back, start=1)
        ],
    )
    document_repository.add(session, correction)
    # The delivery note and the order are those of the rectified invoice.
    delivery_note = invoice.parent
    assert delivery_note is not None
    session.commit()

    announce_issued(publisher, correction, delivery_note.id, delivery_note.parent_id)
    return correction
