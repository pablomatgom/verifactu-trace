"""Database access: the declarative base, the engine and the per-request session."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import database_schema, database_url


class Base(DeclarativeBase):
    """Parent class of every model (`class Document(Base): ...`).

    SQLAlchemy records each model's table in `Base.metadata`. Alembic reads that list
    (see migrations/env.py) to autogenerate migrations.
    """

    # Every table of this service lives in its own PostgreSQL schema. Setting it here means
    # the models do not have to repeat it, and none can end up in the wrong schema.
    metadata = MetaData(schema=database_schema())


@lru_cache
def get_engine() -> Engine:
    """Return the engine of the application: the URL plus a pool of open connections.

    lru_cache makes this run once, so the whole process shares a single engine and a single
    pool (a new engine per request would open a new connection every time). It also means the
    engine is created on first use, not on import, so importing this module does not need
    DATABASE_URL.
    """
    # pool_pre_ping checks that a pooled connection is still alive before handing it out,
    # and replaces it if it is not (for instance, after PostgreSQL restarted).
    return create_engine(database_url(), pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    The endpoint declares `session: Session = Depends(get_session)`. FastAPI runs this
    function up to the `yield` and hands the session over; when the response is done, it
    resumes here, the `with` closes the session and the connection goes back to the pool.

    It does not commit. Whoever completes a use case (the service layer) must call
    `session.commit()`, or the changes are discarded when the session closes.
    The tests replace this dependency with a session that rolls back (see tests/conftest.py).
    """
    with Session(get_engine()) as session:
        yield session
