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
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db import get_engine, get_session
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
def client(session: Session) -> Iterator[TestClient]:
    """FastAPI test client that calls the app in-process, without starting a server."""
    # Whenever an endpoint asks for Depends(get_session), hand it the test session. The
    # endpoint does not change as it still asks for the same dependency.
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    # Remove the override so it does not leak into the next test.
    app.dependency_overrides.clear()
