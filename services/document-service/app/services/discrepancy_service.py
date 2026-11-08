import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from sqlalchemy.orm import Session

from app.exceptions import DocumentNotFound
from app.models import Document, DocumentType
from app.repositories import document_repository

# What is compared between a line and the line that comes from it.
QUANTITY = "quantity"
UNIT_PRICE = "unit_price"
VAT_RATE = "vat_rate"


@dataclass(frozen=True)
class LineRef:
    """One side of a difference: a line of a document and the value it has."""

    document_type: str
    number: str
    # Position of the line in its document, or None if the document has no such line.
    line: int | None
    value: Decimal


@dataclass(frozen=True)
class Discrepancy:
    """A value that is not the same in a line and in the line that comes from it."""

    field: str
    description: str
    source: LineRef
    target: LineRef


@dataclass(frozen=True)
class Reconciliation:
    """The documents that were compared, oldest first, and what does not match between them."""

    document: Document
    compared: list[Document]
    discrepancies: list[Discrepancy]


def compare(source: Document, target: Document) -> list[Discrepancy]:
    """The differences between a document and the one that comes from it.

    Each line of `source` is looked up in `target` through `source_line_id`, which is how a line
    says which line it comes from. Its quantity, price and VAT must be the same. A line of `source`
    that `target` does not have counts as a quantity of zero: it was ordered or delivered and then
    not delivered or billed. Lines of `target` that do not come from `source` are not compared.
    """
    coming_from = {line.source_line_id: line for line in target.lines if line.source_line_id}
    differences = []
    for line in source.lines:
        counterpart = coming_from.get(line.id)
        origin = LineRef(source.type, source.number, line.position, line.quantity)
        if counterpart is None:
            missing = LineRef(target.type, target.number, None, Decimal(0))
            differences.append(Discrepancy(QUANTITY, line.description, origin, missing))
            continue
        for field in (QUANTITY, UNIT_PRICE, VAT_RATE):
            expected, found = getattr(line, field), getattr(counterpart, field)
            if expected != found:
                differences.append(
                    Discrepancy(
                        field,
                        line.description,
                        LineRef(source.type, source.number, line.position, expected),
                        LineRef(target.type, target.number, counterpart.position, found),
                    )
                )
    return differences


def compare_chain(chain: Sequence[Document]) -> list[Discrepancy]:
    """The differences between each document of a chain (oldest first) and the next one.

    A corrective invoice is not compared with the invoice it rectifies: it differs from it on
    purpose, since it takes units back.
    """
    differences = []
    for source, target in pairwise(chain):
        if target.type != DocumentType.CORRECTIVE_INVOICE:
            differences.extend(compare(source, target))
    return differences


def find_discrepancies(session: Session, document_id: uuid.UUID) -> Reconciliation:
    """Compare the chain of a document: its order, its delivery note and itself, as they exist.

    Raises DocumentNotFound if there is no document with that id.
    """
    document = document_repository.get(session, document_id)
    if document is None:
        raise DocumentNotFound(f"document {document_id} does not exist")
    # Up the chain, from the document to its order.
    chain = [document]
    while chain[-1].parent_id is not None:
        parent = document_repository.get(session, chain[-1].parent_id)
        # The parent is a foreign key, so it exists.
        assert parent is not None
        chain.append(parent)
    chain.reverse()
    return Reconciliation(document, chain, compare_chain(chain))
