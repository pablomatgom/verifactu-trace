import os

DEFAULT_SCHEMA = "submissions"


def database_schema() -> str:
    """PostgreSQL schema owned by this service."""
    return os.environ.get("DATABASE_SCHEMA", DEFAULT_SCHEMA)


def database_url() -> str:
    """Connection URL in the form SQLAlchemy needs to use the psycopg 3 driver.

    Compose passes a plain `postgresql://` URL, which SQLAlchemy would resolve to psycopg2.
    """
    try:
        url = os.environ["DATABASE_URL"]
    except KeyError:
        raise RuntimeError("The DATABASE_URL environment variable is not set") from None
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def redis_url() -> str:
    """Connection URL of the Redis where the events are read from."""
    try:
        return os.environ["REDIS_URL"]
    except KeyError:
        raise RuntimeError("The REDIS_URL environment variable is not set") from None


def _number(name: str, default: str, kind: type[int] | type[float]) -> int | float:
    """A numeric setting from the environment, with a clear error if it is not a number."""
    value = os.environ.get(name, default)
    try:
        return kind(value)
    except ValueError:
        raise RuntimeError(
            f"The {name} environment variable must be a number, not {value!r}"
        ) from None


def max_attempts() -> int:
    """How many times a submission is tried before it is given up (state FAILED)."""
    return int(_number("SUBMISSION_MAX_ATTEMPTS", "5", int))


def retry_base_seconds() -> float:
    """Wait after the first failed attempt. It doubles after each one (see services/retry.py)."""
    return float(_number("SUBMISSION_RETRY_BASE_SECONDS", "5", float))


def aeat_simulation() -> str:
    """How the simulated AEAT answers: accept, reject, fail or flaky (see app/aeat.py)."""
    return os.environ.get("AEAT_SIMULATION", "accept")


def aeat_failure_rate() -> float:
    """With the `flaky` simulation, the probability (0 to 1) that an attempt fails."""
    return float(_number("AEAT_FAILURE_RATE", "0.5", float))
