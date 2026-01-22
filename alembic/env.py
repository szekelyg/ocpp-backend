from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

from app.core.config import settings
from app.db.base import Base
from app.db import models  # fontos: ettől regisztrálódnak a modellek

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_migration_url() -> str:
    """
    Alembic (sync) → psycopg URL kell.
    App runtime (async) → asyncpg marad.
    """
    url = settings.database_url

    # async → sync driver csere migrációhoz
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    url = url.replace("postgresql+asyncpg", "postgresql+psycopg")

    return url


def run_migrations_offline() -> None:
    url = get_migration_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # ide is beégetjük a jó URL-t
    config.set_main_option("sqlalchemy.url", get_migration_url())

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()