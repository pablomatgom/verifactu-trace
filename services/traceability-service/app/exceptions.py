class DomainError(Exception):
    """A request that is well formed but breaks a rule of the business.

    Services raise these instead of returning error codes, and the API turns them into the common
    error body. `code` is the machine-readable code the client sees and `status_code` the HTTP
    status it is answered with.
    """

    code = "DOMAIN_ERROR"
    status_code = 422

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class EventsNotFound(DomainError):
    """The document has no events: either it does not exist or nothing happened to it yet.

    This service only knows the documents through their events (it does not hold the documents),
    so it cannot tell the two cases apart.
    """

    code = "EVENTS_NOT_FOUND"
    status_code = 404
