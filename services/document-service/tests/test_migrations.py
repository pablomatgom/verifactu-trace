from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.config import database_schema


# `engine` has already run `alembic upgrade head`, so here we check what it left behind.
def test_schema_and_version_table_are_created_in_the_service_schema(
    engine: Engine, alembic_cfg: Config
):
    schema = database_schema()
    # The newest revision in migrations/versions/. Reading it from the scripts, instead of
    # writing "0001", means this test does not need editing with every new migration.
    head = ScriptDirectory.from_config(alembic_cfg).get_current_head()

    with engine.connect() as connection:
        # Every schema of the database.
        schemas = (
            connection.execute(text("SELECT schema_name FROM information_schema.schemata"))
            .scalars()
            .all()
        )
        
        # The version Alembic recorded, stored inside the service's own schema.
        version = connection.execute(
            text(f'SELECT version_num FROM "{schema}".alembic_version')
        ).scalar_one()

    assert schema in schemas
    assert version == head


def test_upgrade_can_run_twice(engine: Engine, alembic_cfg: Config):
    # Every replica runs the migrations on start, so a second run must find nothing to do.
    # The test passes if neither call raises.
    command.upgrade(alembic_cfg, "head")
    command.upgrade(alembic_cfg, "head")
