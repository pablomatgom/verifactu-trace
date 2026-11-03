"""Fixtures shared by every test of the service.

A fixture is a function that prepares something a test asks for by naming it as a parameter.
They chain: alembic_cfg -> engine -> session -> client.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db import get_engine, get_session
from app.events import EventPublisher, get_publisher
from app.main import app

# services/document-service/, two levels above this file (tests/conftest.py).
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


class FakePublisher:
    """Publisher that keeps the events in a list instead of sending them to Redis."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str]]] = []

    def publish(self, stream: str, fields: dict[str, str]) -> None:
        self.events.append((stream, fields))


@pytest.fixture
def publisher() -> FakePublisher:
    """The publisher the endpoints get in the tests. Ask for it to see what was published."""
    return FakePublisher()


@pytest.fixture
def offline_client(publisher: EventPublisher) -> Iterator[TestClient]:
    """Test client with no database, for requests that are rejected before using it."""
    # The endpoint still asks for a session, so hand it a placeholder. If a test reaches the
    # database by mistake, it fails with an error instead of connecting somewhere.
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[get_publisher] = lambda: publisher
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client(session: Session, publisher: EventPublisher) -> Iterator[TestClient]:
    """FastAPI test client that calls the app in-process, without starting a server."""
    # Whenever an endpoint asks for Depends(get_session), hand it the test session. The
    # endpoint does not change as it still asks for the same dependency.
    app.dependency_overrides[get_session] = lambda: session
    # The same for the publisher: no test needs a Redis unless it asks for one on purpose.
    app.dependency_overrides[get_publisher] = lambda: publisher
    yield TestClient(app)
    # Remove the override so it does not leak into the next test.
    app.dependency_overrides.clear()
