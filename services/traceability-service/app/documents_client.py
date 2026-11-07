"""Client of document-service, the only service that holds the documents.

This service only keeps the events of the documents, so to rebuild a documentary chain it asks
document-service for the documents. The rest of the code depends on `DocumentClient`, not on
HTTP: the tests give it a fake one, and only the tests of `HttpDocumentClient` use the network.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from app.config import document_service_url
from app.exceptions import DocumentServiceUnavailable

# How long to wait for document-service. A request that waits longer is answered with a 503
# instead of keeping a worker busy.
TIMEOUT_SECONDS = 3


@dataclass(frozen=True)
class DocumentRef:
    """What the chain needs to know of a document."""

    id: uuid.UUID
    type: str
    number: str
    issue_date: date
    # The previous document of the chain, or None in an order.
    parent_id: uuid.UUID | None


class DocumentClient(Protocol):
    """Something that can look up a document. The services depend on this, not on HTTP."""

    def get(self, document_id: uuid.UUID) -> DocumentRef | None:
        """The document, or None if it does not exist.

        Raises DocumentServiceUnavailable if document-service cannot answer.
        """
        ...


class HttpDocumentClient:
    """Looks documents up with `GET /api/v1/documents/{id}` of document-service."""

    def __init__(self, base_url: str, timeout: float = TIMEOUT_SECONDS):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get(self, document_id: uuid.UUID) -> DocumentRef | None:
        url = f"{self._base_url}/api/v1/documents/{document_id}"
        try:
            with urlopen(url, timeout=self._timeout) as response:
                body = json.load(response)
        except HTTPError as error:
            # The error holds the body of the response open: close it so it does not leak.
            error.close()
            if error.code == 404:
                return None
            raise DocumentServiceUnavailable(
                f"document-service answered {error.code} to the request for {document_id}"
            ) from None
        except (URLError, OSError):
            # URLError covers a refused connection and a name that does not resolve; OSError, a
            # timeout or a connection that drops half way.
            raise DocumentServiceUnavailable("document-service cannot be reached") from None
        except ValueError:
            raise DocumentServiceUnavailable("document-service sent an unreadable body") from None
        return self._to_ref(body)

    @staticmethod
    def _to_ref(body: dict) -> DocumentRef:
        try:
            parent_id = body["parent_id"]
            return DocumentRef(
                id=uuid.UUID(body["id"]),
                type=body["type"],
                number=body["number"],
                issue_date=date.fromisoformat(body["issue_date"]),
                parent_id=None if parent_id is None else uuid.UUID(parent_id),
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            raise DocumentServiceUnavailable("document-service sent an unexpected body") from None


def get_document_client() -> DocumentClient:
    """Dependency of the endpoints that need the documents, like get_session is for the database.

    The tests replace it with a client that does not need document-service.
    """
    return HttpDocumentClient(document_service_url())
