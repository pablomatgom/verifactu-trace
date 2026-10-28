"""Alembic environment: the script that `alembic upgrade`, `downgrade`, `revision`... run.

Alembic calls this file every time it needs to talk to the database. The standard template
reads the connection URL from alembic.ini; this one reads it from the environment instead
(through app.config), so the application and the migrations always use the same database.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.schema import CreateSchema

import app.models  # noqa: F401  (registers the tables on the metadata)
from app.config import database_schema, database_url
from app.db import Base

# The Alembic Config object: gives access to the values of alembic.ini.
config = context.config

# Set up Python logging from the [loggers] sections of alembic.ini.
# disable_existing_loggers=False keeps the loggers that the application already created.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Each service owns one PostgreSQL schema ("documents" here). Its tables and its
# alembic_version table live inside it, so services never share a migration history.
SCHEMA = database_schema()

# The models' metadata: what `alembic revision --autogenerate` compares against the real
# database to work out which migration to write.
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    """Filter used by autogenerate to decide which database objects it may look at.

    include_schemas=True (below) makes Alembic inspect every schema of the database. Without
    this filter it would see the tables of the other services and propose to drop them.
    """
    if type_ == "schema":
        return name == SCHEMA
    return True


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it.

    No database connection is opened: Alembic only needs the URL to know the SQL dialect.
    Useful to review what a migration would do, or to hand the script to a DBA.
    """
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,  # write the values inside the SQL text instead of bind parameters
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the pending migrations against the real database (the normal mode)."""
    # NullPool: this connection is used once and closed, so no connection pool is needed.
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Several replicas can start at the same time, and they would all try to create the
        # same tables. An advisory lock is a PostgreSQL mutex identified by a number: the first
        # replica takes it and migrates, the others wait here and, once they get in, find
        # nothing left to apply. hashtext() turns the name into the number the lock needs.
        # The lock belongs to the connection, so it survives the commits below.
        lock_name = f"alembic:{SCHEMA}"
        connection.execute(text("SELECT pg_advisory_lock(hashtext(:name))"), {"name": lock_name})
        try:
            # Alembic stores alembic_version inside the schema, so the schema must exist before
            # it starts. IF NOT EXISTS makes this a no-op when db/init already created it.
            # The commit makes the schema visible before Alembic opens its own transaction.
            connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
            connection.commit()

            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                # Where the alembic_version table lives: inside this service's schema.
                version_table_schema=SCHEMA,
                include_schemas=True,
                include_name=include_name,
            )
            # Alembic runs every pending migration inside one transaction (PostgreSQL supports
            # transactional DDL), so a migration that fails leaves nothing half applied.
            with context.begin_transaction():
                context.run_migrations()
            connection.commit()
        finally:
            # Always release the lock, even if a migration failed, so the next replica can
            # try. It would also be released when the connection closes, but this is explicit.
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": lock_name}
            )
            connection.commit()


# Alembic imports this file and expects it to run the migrations on import. The CLI
# decides the mode: `--sql` means offline, anything else means online.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
