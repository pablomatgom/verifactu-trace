import pytest

from app.config import (
    aeat_failure_rate,
    aeat_simulation,
    database_url,
    max_attempts,
    redis_url,
    retry_base_seconds,
)

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


def test_the_retry_settings_have_defaults(monkeypatch):
    monkeypatch.delenv("SUBMISSION_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("SUBMISSION_RETRY_BASE_SECONDS", raising=False)

    assert max_attempts() == 5
    assert retry_base_seconds() == 5


def test_the_retry_settings_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("SUBMISSION_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("SUBMISSION_RETRY_BASE_SECONDS", "0.5")

    assert max_attempts() == 3
    assert retry_base_seconds() == 0.5


def test_a_setting_that_is_not_a_number_is_refused(monkeypatch):
    monkeypatch.setenv("SUBMISSION_MAX_ATTEMPTS", "many")

    with pytest.raises(RuntimeError, match="SUBMISSION_MAX_ATTEMPTS"):
        max_attempts()


def test_the_aeat_simulation_defaults_to_accepting(monkeypatch):
    monkeypatch.delenv("AEAT_SIMULATION", raising=False)
    monkeypatch.delenv("AEAT_FAILURE_RATE", raising=False)

    assert aeat_simulation() == "accept"
    assert aeat_failure_rate() == 0.5


def test_the_aeat_simulation_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("AEAT_SIMULATION", "flaky")
    monkeypatch.setenv("AEAT_FAILURE_RATE", "0.25")

    assert aeat_simulation() == "flaky"
    assert aeat_failure_rate() == 0.25
