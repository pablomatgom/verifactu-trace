import json
import socket
import threading
import uuid
from collections.abc import Iterator
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.documents_client import HttpDocumentClient
from app.exceptions import DocumentServiceUnavailable

DOCUMENT_ID = uuid.UUID("5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52")
PARENT_ID = uuid.UUID("9a7b2d1e-3c55-4e0f-8b21-7d6c5a4b3e10")
# The body document-service sends: the client reads only part of it.
DOCUMENT = {
    "id": str(DOCUMENT_ID),
    "type": "INVOICE",
    "number": "F-2026-000001",
    "status": "ISSUED",
    "issue_date": "2026-10-14",
    "parent_id": str(PARENT_ID),
    "lines": [],
}


class FakeDocumentService:
    """A real HTTP server on a free local port, whose answer each test chooses."""

    def __init__(self) -> None:
        self.status = 200
        self.body: bytes = json.dumps(DOCUMENT).encode()
        self.paths: list[str] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                service.paths.append(self.path)
                self.send_response(service.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(service.body)))
                self.end_headers()
                self.wfile.write(service.body)

            def log_message(self, format, *args):
                """Keep the output of the tests clean."""

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join()


@pytest.fixture
def service() -> Iterator[FakeDocumentService]:
    fake = FakeDocumentService()
    fake.start()
    yield fake
    fake.stop()


@pytest.fixture
def http_client(service: FakeDocumentService) -> HttpDocumentClient:
    return HttpDocumentClient(service.url, timeout=2)


def test_it_reads_the_document_from_the_body(http_client: HttpDocumentClient):
    document = http_client.get(DOCUMENT_ID)

    assert document is not None
    assert (document.id, document.type) == (DOCUMENT_ID, "INVOICE")
    assert document.number == "F-2026-000001"
    assert document.issue_date == date(2026, 10, 14)
    assert document.parent_id == PARENT_ID


def test_it_asks_for_the_document_by_its_id(
    http_client: HttpDocumentClient, service: FakeDocumentService
):
    http_client.get(DOCUMENT_ID)

    assert service.paths == [f"/api/v1/documents/{DOCUMENT_ID}"]


def test_the_base_url_may_end_with_a_slash(service: FakeDocumentService):
    HttpDocumentClient(service.url + "/", timeout=2).get(DOCUMENT_ID)

    assert service.paths == [f"/api/v1/documents/{DOCUMENT_ID}"]


def test_an_order_has_no_parent(http_client: HttpDocumentClient, service: FakeDocumentService):
    service.body = json.dumps({**DOCUMENT, "type": "ORDER", "parent_id": None}).encode()

    document = http_client.get(DOCUMENT_ID)

    assert document is not None
    assert document.parent_id is None


def test_a_document_that_does_not_exist_is_none(
    http_client: HttpDocumentClient, service: FakeDocumentService
):
    service.status = 404
    service.body = b'{"error": {"code": "DOCUMENT_NOT_FOUND", "message": "x"}}'

    assert http_client.get(DOCUMENT_ID) is None


@pytest.mark.parametrize("status", [500, 502, 503, 422])
def test_any_other_error_status_means_it_is_unavailable(
    http_client: HttpDocumentClient, service: FakeDocumentService, status: int
):
    service.status = status

    with pytest.raises(DocumentServiceUnavailable, match=str(status)):
        http_client.get(DOCUMENT_ID)


@pytest.mark.parametrize(
    "body",
    [
        b"this is not json",
        b"[]",
        b"{}",
        json.dumps({**DOCUMENT, "id": "not-a-uuid"}).encode(),
        json.dumps({**DOCUMENT, "issue_date": "yesterday"}).encode(),
        json.dumps({**DOCUMENT, "parent_id": 7}).encode(),
    ],
    ids=["not-json", "list", "empty", "bad-id", "bad-date", "bad-parent"],
)
def test_a_body_that_cannot_be_read_means_it_is_unavailable(
    http_client: HttpDocumentClient, service: FakeDocumentService, body: bytes
):
    service.body = body

    with pytest.raises(DocumentServiceUnavailable):
        http_client.get(DOCUMENT_ID)


def test_a_service_that_is_down_means_it_is_unavailable():
    # Bind a port and close it right away, so nothing is listening there.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    client = HttpDocumentClient(f"http://127.0.0.1:{port}", timeout=2)

    with pytest.raises(DocumentServiceUnavailable, match="cannot be reached"):
        client.get(DOCUMENT_ID)


def test_a_service_that_does_not_answer_in_time_means_it_is_unavailable():
    # It accepts the connection (the backlog) but never answers.
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        port = silent.getsockname()[1]

        client = HttpDocumentClient(f"http://127.0.0.1:{port}", timeout=0.3)

        with pytest.raises(DocumentServiceUnavailable, match="cannot be reached"):
            client.get(DOCUMENT_ID)
