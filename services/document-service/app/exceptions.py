class DomainError(Exception):
    """A request that is well formed but breaks a rule of the business.

    Services raise these instead of returning error codes, and the API turns them into the common
    error body. `code` is the machine-readable code the client sees.
    """

    code = "DOMAIN_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    """Something the request asks for or refers to does not exist: the API answers 404."""


class Conflict(DomainError):
    """The request clashes with the state the document is in: the API answers 409."""


class ReferenceNotFound(NotFound):
    """The document the request refers to does not exist (or is not of the expected type)."""

    code = "REFERENCE_NOT_FOUND"


class DocumentNotFound(NotFound):
    """The document that is asked for does not exist."""

    code = "DOCUMENT_NOT_FOUND"


class InvalidOrderLine(DomainError):
    """The request refers to a line that the order does not have."""

    code = "INVALID_ORDER_LINE"


class DeliveryNoteAlreadyInvoiced(DomainError):
    """The delivery note already has an invoice, and it can only be invoiced once."""

    code = "DELIVERY_NOTE_ALREADY_INVOICED"


class InvalidDateRange(DomainError):
    """The list is asked for documents from a date that is later than its end date."""

    code = "INVALID_DATE_RANGE"


class QuantityExceeded(DomainError):
    """The delivered quantity of an order line would be greater than the ordered one."""

    code = "QUANTITY_EXCEEDED"


class DocumentNotCancellable(Conflict):
    """The document cannot be cancelled: it is an invoice, it is already cancelled or it is in use."""

    code = "DOCUMENT_NOT_CANCELLABLE"


class ReferenceCancelled(DomainError):
    """The document the request refers to was cancelled, so nothing new can come from it."""

    code = "REFERENCE_CANCELLED"


class InvalidInvoiceLine(DomainError):
    """The request refers to a line that the invoice does not have."""

    code = "INVALID_INVOICE_LINE"


class NothingToCorrect(DomainError):
    """Everything on the invoice has already been rectified, so there is nothing left to correct."""

    code = "NOTHING_TO_CORRECT"
