"""Alembic's settings for running migrations (database schema changes).

Run from the repo root: alembic -c server/db/alembic.ini upgrade head

Each file in versions/ is one step; its ``down_revision`` names the step before it, so the steps
form a single chain.

MERGE-CRITICAL: after merging another branch's migrations the chain must still be single. Two files
with the same ``down_revision`` make "upgrade head" fail with "Multiple head revisions". Fix it by
pointing the newer file's ``down_revision`` at the other branch's last step (or with ``alembic merge
heads``). Check with: alembic -c server/db/alembic.ini heads
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from server.db.config import DATABASE_URL
from server.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use the app's database unless a caller (e.g. a test building a throwaway
# database) has already pointed alembic somewhere else.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Write the migration SQL out instead of running it (``alembic upgrade --sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply the migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
