"""Fixtures shared by every test of the service.

A fixture is a function that prepares something a test asks for by naming it as a parameter.
They chain: alembic_cfg -> engine -> session -> client.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db import get_engine, get_session
from app.documents_client import DocumentRef, get_document_client
from app.exceptions import DocumentServiceUnavailable
from app.main import app

# services/traceability-service/, two levels above this file (tests/conftest.py).
SERVICE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")  # built once for the whole test run
def alembic_cfg() -> Config:
    """Alembic configuration, so the tests can run migrations from Python."""
    config = Config(str(SERVICE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    return config


@pytest.fixture(scope="session")
def engine(alembic_cfg: Config) -> Engine:
    """Engine on the PostgreSQL of the tests, with every migration applied."""
    if not os.environ.get("DATABASE_URL"):
        # In CI a missing database must fail the build instead of skipping the tests.
        # Otherwise a broken CI setup would look like a green build with nothing tested.
        if os.environ.get("CI"):
            pytest.fail("DATABASE_URL is not set")
        # Locally, only the tests that need the database are skipped; the rest still run.
        pytest.skip("DATABASE_URL is not set: start a PostgreSQL and point it to it")

    # Same command the container runs on start. Doing it here also tests the migrations,
    # and creates the tables before any test needs them.
    command.upgrade(alembic_cfg, "head")
    return get_engine()


@pytest.fixture  # no scope: a fresh session for every test
def session(engine: Engine) -> Iterator[Session]:
    """Session whose changes are rolled back when the test ends."""
    with engine.connect() as connection:
        # Outer transaction that nobody commits: it is what gets rolled back at the end.
        transaction = connection.begin()

        # create_savepoint: if the code under test calls session.commit() (as a service will),
        # that only releases an inner savepoint and the outer transaction stays open, so
        # nothing is really saved so each test starts with the database as it was.
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            yield session  # the test runs here
        transaction.rollback()  # discard everything the test wrote


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    """Client of the Redis of the tests, skipped locally and a failure in CI without REDIS_URL."""
    if not os.environ.get("REDIS_URL"):
        # Same rule as the `engine` fixture: in CI a missing Redis must fail the build.
        if os.environ.get("CI"):
            pytest.fail("REDIS_URL is not set")
        pytest.skip("REDIS_URL is not set: start a Redis and point it to it")
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def offline_client() -> Iterator[TestClient]:
    """Test client with no database, for requests that are rejected before using it."""
    # The endpoint still asks for a session, so hand it a placeholder. If a test reaches the
    # database by mistake, it fails with an error instead of connecting somewhere.
    app.dependency_overrides[get_session] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """FastAPI test client that calls the app in-process, without starting a server."""
    # Whenever an endpoint asks for Depends(get_session), hand it the test session. The
    # endpoint does not change as it still asks for the same dependency.
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    # Remove the override so it does not leak into the next test.
    app.dependency_overrides.clear()


class FakeDocumentClient:
    """Stands in for document-service: it knows the documents the test adds to it."""

    def __init__(self) -> None:
        self.documents: dict[uuid.UUID, DocumentRef] = {}
        self.requested: list[uuid.UUID] = []
        self.unavailable = False

    def add(self, type: str, parent: DocumentRef | None = None) -> DocumentRef:
        number = f"{type[0]}-2026-{len(self.documents) + 1:06d}"
        document = DocumentRef(
            id=uuid.uuid4(),
            type=type,
            number=number,
            issue_date=date(2026, 10, 10 + len(self.documents)),
            parent_id=None if parent is None else parent.id,
        )
        self.documents[document.id] = document
        return document

    def add_chain(self) -> tuple[DocumentRef, DocumentRef, DocumentRef]:
        """An order, its delivery note and its invoice."""
        order = self.add("ORDER")
        delivery_note = self.add("DELIVERY_NOTE", order)
        return order, delivery_note, self.add("INVOICE", delivery_note)

    def get(self, document_id: uuid.UUID) -> DocumentRef | None:
        self.requested.append(document_id)
        if self.unavailable:
            raise DocumentServiceUnavailable("document-service cannot be reached")
        return self.documents.get(document_id)


@pytest.fixture
def documents() -> FakeDocumentClient:
    """A document-service with no documents yet."""
    return FakeDocumentClient()


@pytest.fixture
def documents_client(documents: FakeDocumentClient) -> Iterator[TestClient]:
    """Test client whose document-service is the `documents` fake. It needs no database."""
    app.dependency_overrides[get_document_client] = lambda: documents
    yield TestClient(app)
    app.dependency_overrides.clear()
