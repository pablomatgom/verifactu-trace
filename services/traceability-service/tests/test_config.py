import pytest

from app.config import database_url, document_service_url, redis_url

# These tests need no database: they only check how the URL is built from the environment.
# `monkeypatch` sets or removes an environment variable for the duration of one test and
# restores it afterwards, so the tests do not affect each other.


def test_database_url_selects_the_psycopg_driver(monkeypatch):
    # Compose passes a plain "postgresql://" URL. SQLAlchemy would pair it with psycopg2,
    # which is not installed, so config.py asks for psycopg 3 explicitly.
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@postgres:5432/db")

    assert database_url() == "postgresql+psycopg://user:pass@postgres:5432/db"


def test_database_url_keeps_an_explicit_driver(monkeypatch):
    # A URL that already names a driver must be left untouched.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@postgres:5432/db")

    assert database_url() == "postgresql+psycopg://user:pass@postgres:5432/db"


def test_database_url_is_required(monkeypatch):
    # No default on purpose: a missing URL must fail loudly instead of connecting somewhere
    # unexpected.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        database_url()


def test_redis_url_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")

    assert redis_url() == "redis://redis:6379/0"


def test_redis_url_is_required(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(RuntimeError, match="REDIS_URL"):
        redis_url()


def test_document_service_url_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DOCUMENT_SERVICE_URL", "http://document-service:8001")

    assert document_service_url() == "http://document-service:8001"


def test_document_service_url_is_required(monkeypatch):
    monkeypatch.delenv("DOCUMENT_SERVICE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DOCUMENT_SERVICE_URL"):
        document_service_url()
