import uuid
from decimal import Decimal

import pytest

from app.models import Document, DocumentLine, DocumentType
from app.services.discrepancy_service import compare, compare_chain


def make_line(position: int, source: DocumentLine | None = None, **changes) -> DocumentLine:
    values = {
        "description": f"Item {position}",
        "quantity": Decimal(10),
        "unit_price": Decimal("10.50"),
        "vat_rate": Decimal(21),
    }
    values.update(changes)
    return DocumentLine(
        id=uuid.uuid4(),
        position=position,
        source_line_id=None if source is None else source.id,
        **values,
    )


def make_document(kind: DocumentType, number: str, lines: list[DocumentLine]) -> Document:
    return Document(id=uuid.uuid4(), type=kind, number=number, lines=lines)


def make_chain(**changes) -> tuple[Document, Document, Document]:
    """An order, its delivery note and its invoice, each line coming from the one before.

    `changes` are applied to the first line of the delivery note and the invoice, so a test can
    break the chain in one place: `delivery_note={"quantity": 4}`, `invoice={...}`.
    """
    order = make_document(
        DocumentType.ORDER, "P-2026-000001", [make_line(1), make_line(2, quantity=Decimal(4))]
    )
    delivered = [
        make_line(1, order.lines[0], **changes.get("delivery_note", {})),
        make_line(2, order.lines[1], quantity=Decimal(4)),
    ]
    delivery_note = make_document(DocumentType.DELIVERY_NOTE, "A-2026-000001", delivered)
    billed = [
        make_line(
            1, delivered[0], **{**changes.get("delivery_note", {}), **changes.get("invoice", {})}
        ),
        make_line(2, delivered[1], quantity=Decimal(4)),
    ]
    invoice = make_document(DocumentType.INVOICE, "F-2026-000001", billed)
    return order, delivery_note, invoice


def test_a_coherent_chain_has_no_discrepancies():
    assert compare_chain(make_chain()) == []


def test_a_chain_of_one_document_has_nothing_to_compare():
    order, _, _ = make_chain()

    assert compare_chain([order]) == []


def test_a_quantity_that_differs_is_reported_with_both_sides():
    order = make_document(DocumentType.ORDER, "P-1", [make_line(1)])
    delivery_note = make_document(
        DocumentType.DELIVERY_NOTE, "A-1", [make_line(1, order.lines[0], quantity=Decimal(4))]
    )

    [difference] = compare(order, delivery_note)

    assert difference.field == "quantity"
    assert difference.description == "Item 1"
    assert (difference.source.document_type, difference.source.number) == ("ORDER", "P-1")
    assert (difference.source.line, difference.source.value) == (1, Decimal(10))
    assert (difference.target.document_type, difference.target.number) == ("DELIVERY_NOTE", "A-1")
    assert (difference.target.line, difference.target.value) == (1, Decimal(4))


@pytest.mark.parametrize(
    ("field", "value"),
    [("unit_price", Decimal("11.00")), ("vat_rate", Decimal(10))],
)
def test_a_price_or_a_vat_rate_that_differs_is_reported(field: str, value: Decimal):
    order = make_document(DocumentType.ORDER, "P-1", [make_line(1)])
    delivery_note = make_document(
        DocumentType.DELIVERY_NOTE, "A-1", [make_line(1, order.lines[0], **{field: value})]
    )

    [difference] = compare(order, delivery_note)

    assert difference.field == field
    assert difference.source.value == getattr(order.lines[0], field)
    assert difference.target.value == value


def test_every_field_that_differs_in_a_line_is_reported():
    order = make_document(DocumentType.ORDER, "P-1", [make_line(1)])
    delivery_note = make_document(
        DocumentType.DELIVERY_NOTE,
        "A-1",
        [
            make_line(
                1,
                order.lines[0],
                quantity=Decimal(1),
                unit_price=Decimal(1),
                vat_rate=Decimal(1),
            )
        ],
    )

    fields = [difference.field for difference in compare(order, delivery_note)]

    assert fields == ["quantity", "unit_price", "vat_rate"]


def test_the_same_value_written_with_other_decimals_is_not_a_difference():
    order = make_document(DocumentType.ORDER, "P-1", [make_line(1)])
    delivery_note = make_document(
        DocumentType.DELIVERY_NOTE,
        "A-1",
        [make_line(1, order.lines[0], quantity=Decimal("10.000"), unit_price=Decimal("10.5"))],
    )

    assert compare(order, delivery_note) == []


def test_a_line_that_the_next_document_lacks_counts_as_a_quantity_of_zero():
    order = make_document(DocumentType.ORDER, "P-1", [make_line(1), make_line(2)])
    delivery_note = make_document(DocumentType.DELIVERY_NOTE, "A-1", [make_line(1, order.lines[0])])

    [difference] = compare(order, delivery_note)

    assert difference.field == "quantity"
    assert (difference.source.line, difference.source.value) == (2, Decimal(10))
    assert (difference.target.line, difference.target.value) == (None, Decimal(0))
    assert difference.target.number == "A-1"


def test_a_line_that_does_not_come_from_the_previous_document_is_not_compared():
    order = make_document(DocumentType.ORDER, "P-1", [make_line(1)])
    delivery_note = make_document(
        DocumentType.DELIVERY_NOTE,
        "A-1",
        [make_line(1, order.lines[0]), make_line(2, quantity=Decimal(99))],
    )

    assert compare(order, delivery_note) == []


def test_each_document_is_compared_with_the_next_one_only():
    # The delivery note delivers 4 of 10; the invoice bills what the delivery note delivered.
    order, delivery_note, invoice = make_chain(delivery_note={"quantity": Decimal(4)})

    differences = compare_chain([order, delivery_note, invoice])

    assert [(d.field, d.source.document_type, d.target.document_type) for d in differences] == [
        ("quantity", "ORDER", "DELIVERY_NOTE")
    ]


def test_a_difference_between_the_delivery_note_and_the_invoice_is_reported_there():
    order, delivery_note, invoice = make_chain(invoice={"unit_price": Decimal("99.00")})

    differences = compare_chain([order, delivery_note, invoice])

    assert [(d.field, d.source.document_type, d.target.document_type) for d in differences] == [
        ("unit_price", "DELIVERY_NOTE", "INVOICE")
    ]
