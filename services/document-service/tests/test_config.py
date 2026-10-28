import pytest

from app.config import database_url

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
