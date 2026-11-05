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


class SubmissionAlreadyExists(DomainError):
    """The invoice already has a submission, and it is submitted once."""

    code = "SUBMISSION_ALREADY_EXISTS"
    status_code = 409
