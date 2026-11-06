from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.schemas.common import ErrorBody, ErrorResponse
from app.exceptions import DomainError, NotFound


def _describe(error: dict) -> str:
    """Turn one Pydantic error into text such as `lines: List should have at least 1 item`."""
    # loc starts with "body" (where the data came from), followed by the path to the field.
    parts = [str(part) for part in error["loc"] if part != "body"]
    if error["type"] == "json_invalid":
        # Here loc ends with the position of the syntax error in the text, which is not a field.
        parts = []
    # An error about the body as a whole (invalid JSON, missing body) has no field path.
    path = ".".join(parts) or "body"
    return f"{path}: {error['msg']}"


def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Answer 422 with the common error body of the API contract.

    FastAPI's default is {"detail": [...]}; the README defines {"error": {"code", "message"}}.
    """
    message = "; ".join(_describe(error) for error in exc.errors())
    body = ErrorResponse(error=ErrorBody(code="VALIDATION_ERROR", message=message))
    return JSONResponse(status_code=422, content=body.model_dump())


def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Answer a business rule error with the common error body.

    Something that does not exist is a 404; any other broken rule is a 422.
    """
    status_code = 404 if isinstance(exc, NotFound) else 422
    body = ErrorResponse(error=ErrorBody(code=exc.code, message=exc.message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    """Register the error handlers for the FastAPI app."""
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(DomainError, domain_error_handler)
