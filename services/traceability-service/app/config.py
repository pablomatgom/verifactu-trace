import os

DEFAULT_SCHEMA = "traceability"


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


def document_service_url() -> str:
    """Base URL of document-service, where the documents of a chain are asked for."""
    try:
        return os.environ["DOCUMENT_SERVICE_URL"]
    except KeyError:
        raise RuntimeError("The DOCUMENT_SERVICE_URL environment variable is not set") from None


def redis_url() -> str:
    """Connection URL of the Redis where the events are read from."""
    try:
        return os.environ["REDIS_URL"]
    except KeyError:
        raise RuntimeError("The REDIS_URL environment variable is not set") from None
