import uuid

from app.documents_client import DocumentClient, DocumentRef
from app.exceptions import InconsistentChain, InvoiceNotFound

# The kinds of document of a chain, from the invoice back to where it comes from. Each document
# points to the next one with its `parent_id`.
CHAIN_TYPES = ("INVOICE", "DELIVERY_NOTE", "ORDER")


def get_chain(client: DocumentClient, invoice_id: uuid.UUID) -> list[DocumentRef]:
    """The documents behind an invoice in the order they were made: order, delivery note, invoice.

    It starts at the invoice and follows `parent_id` until the order, which has none. Raises
    InvoiceNotFound if `invoice_id` is not an invoice, InconsistentChain if the documents that
    document-service returns do not follow the invoice-note-order pattern, and
    DocumentServiceUnavailable (from the client) if document-service cannot answer.
    """
    chain: list[DocumentRef] = []
    next_id: uuid.UUID | None = invoice_id
    for expected_type in CHAIN_TYPES:
        if next_id is None:
            raise InconsistentChain(
                f"the chain of invoice {invoice_id} ends at {chain[-1].type} {chain[-1].id}"
            )
        document = client.get(next_id)
        if document is None:
            if not chain:
                raise InvoiceNotFound(f"invoice {invoice_id} does not exist")
            # A document that points to another one that does not exist: it cannot happen while
            # document-service keeps its references, so it is reported instead of hidden.
            raise InconsistentChain(f"{chain[-1].type} {chain[-1].id} points to a missing document")
        if document.type != expected_type:
            if not chain:
                raise InvoiceNotFound(
                    f"document {invoice_id} is not an invoice, its type is {document.type}"
                )
            raise InconsistentChain(
                f"{chain[-1].type} {chain[-1].id} points to a {document.type} where a {expected_type} "
                "was expected"
            )
        chain.append(document)
        next_id = document.parent_id
    if next_id is not None:
        raise InconsistentChain(f"the order of invoice {invoice_id} points to another document")
    # Built from the invoice back, returned from the order forward.
    chain.reverse()
    return chain
