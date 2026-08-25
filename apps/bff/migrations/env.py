"""Alembic environment for the separate BFF application database."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from bff.control_plane import Base
from bff.control_plane_config import ControlPlaneSettings

target_metadata = Base.metadata


def _application_database_url() -> str:
    settings = ControlPlaneSettings.from_environment()
    if not settings.enabled or settings.app_database_url is None:
        raise RuntimeError(
            "BFF_CONTROL_PLANE_ENABLED and APP_DATABASE_URL are required for migrations"
        )
    return settings.app_database_url


def run_migrations_offline() -> None:
    """Render SQL without opening a database connection."""

    context.configure(
        url=_application_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transactional_ddl=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the reviewable revision against the explicitly supplied app DB."""

    connectable = create_engine(_application_database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transactional_ddl=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
