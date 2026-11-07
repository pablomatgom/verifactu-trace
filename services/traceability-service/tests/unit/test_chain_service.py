import pytest
from conftest import FakeDocumentClient

from app.exceptions import DocumentServiceUnavailable, InconsistentChain, InvoiceNotFound
from app.services import chain_service


def test_the_chain_of_an_invoice_goes_from_the_order_to_the_invoice(
    documents: FakeDocumentClient,
):
    order, delivery_note, invoice = documents.add_chain()

    assert chain_service.get_chain(documents, invoice.id) == [order, delivery_note, invoice]


def test_only_the_documents_of_the_chain_are_asked_for(documents: FakeDocumentClient):
    documents.add_chain()  # another chain that must not be touched
    order, delivery_note, invoice = documents.add_chain()
    documents.requested.clear()

    chain_service.get_chain(documents, invoice.id)

    assert documents.requested == [invoice.id, delivery_note.id, order.id]


def test_an_invoice_that_does_not_exist_is_not_found(documents: FakeDocumentClient):
    documents.add_chain()
    missing = FakeDocumentClient().add("INVOICE")

    with pytest.raises(InvoiceNotFound):
        chain_service.get_chain(documents, missing.id)


@pytest.mark.parametrize("index", [0, 1], ids=["order", "delivery_note"])
def test_a_document_that_is_not_an_invoice_is_not_found(documents: FakeDocumentClient, index: int):
    chain = documents.add_chain()

    with pytest.raises(InvoiceNotFound, match="not an invoice"):
        chain_service.get_chain(documents, chain[index].id)


def test_an_invoice_that_points_to_a_missing_delivery_note_is_inconsistent(
    documents: FakeDocumentClient,
):
    _, delivery_note, invoice = documents.add_chain()
    del documents.documents[delivery_note.id]

    with pytest.raises(InconsistentChain, match="missing"):
        chain_service.get_chain(documents, invoice.id)


def test_an_invoice_that_points_to_an_order_is_inconsistent(documents: FakeDocumentClient):
    order = documents.add("ORDER")
    invoice = documents.add("INVOICE", order)

    with pytest.raises(InconsistentChain, match="where a DELIVERY_NOTE"):
        chain_service.get_chain(documents, invoice.id)


def test_an_invoice_without_a_parent_is_inconsistent(documents: FakeDocumentClient):
    invoice = documents.add("INVOICE")

    with pytest.raises(InconsistentChain, match="ends at INVOICE"):
        chain_service.get_chain(documents, invoice.id)


def test_a_delivery_note_without_an_order_is_inconsistent(documents: FakeDocumentClient):
    delivery_note = documents.add("DELIVERY_NOTE")
    invoice = documents.add("INVOICE", delivery_note)

    with pytest.raises(InconsistentChain, match="ends at DELIVERY_NOTE"):
        chain_service.get_chain(documents, invoice.id)


def test_an_order_that_points_to_another_document_is_inconsistent(
    documents: FakeDocumentClient,
):
    # An order has no parent: if it had one the chain would not end where it should.
    other = documents.add("ORDER")
    order = documents.add("ORDER", other)
    delivery_note = documents.add("DELIVERY_NOTE", order)
    invoice = documents.add("INVOICE", delivery_note)

    with pytest.raises(InconsistentChain, match="points to another document"):
        chain_service.get_chain(documents, invoice.id)


def test_a_document_service_that_cannot_answer_is_reported(documents: FakeDocumentClient):
    _, _, invoice = documents.add_chain()
    documents.unavailable = True

    with pytest.raises(DocumentServiceUnavailable):
        chain_service.get_chain(documents, invoice.id)
