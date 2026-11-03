class DomainError(Exception):
    """A request that is well formed but breaks a rule of the business.

    Services raise these instead of returning error codes, and the API turns them into the common
    error body. `code` is the machine-readable code the client sees.
    """

    code = "DOMAIN_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ReferenceNotFound(DomainError):
    """The document the request refers to does not exist (or is not of the expected type)."""

    code = "REFERENCE_NOT_FOUND"


class InvalidOrderLine(DomainError):
    """The request refers to a line that the order does not have."""

    code = "INVALID_ORDER_LINE"


class DeliveryNoteAlreadyInvoiced(DomainError):
    """The delivery note already has an invoice, and it can only be invoiced once."""

    code = "DELIVERY_NOTE_ALREADY_INVOICED"


class QuantityExceeded(DomainError):
    """The delivered quantity of an order line would be greater than the ordered one."""

    code = "QUANTITY_EXCEEDED"
