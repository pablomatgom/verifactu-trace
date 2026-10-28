import os

DEFAULT_SCHEMA = "documents"


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
