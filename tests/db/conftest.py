"""Shared PostGIS fixtures, gated by the same explicit opt-in as the migration test."""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from georeport3d.db.session import create_database_engine, create_session_factory


def authorized_test_database_url() -> str:
    """Refuse anything but an explicitly authorized loopback test database."""
    if os.getenv("GEOREPORT3D_RUN_POSTGIS_INTEGRATION") != "1":
        pytest.skip("PostGIS integration requires an explicit opt-in")

    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.fail("TEST_DATABASE_URL is required after integration opt-in")

    parsed = urlsplit(raw_url)
    database_name = parsed.path.removeprefix("/")
    if (
        parsed.scheme not in {"postgresql", "postgresql+psycopg"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or not database_name.endswith("_test")
    ):
        pytest.fail("integration URL must target a loopback PostgreSQL test database")
    return raw_url


@pytest.fixture(scope="session")
def postgis_engine() -> Iterator[Engine]:
    """Migrate the authorized test database once for the whole session."""
    url = authorized_test_database_url()

    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")

    engine = create_database_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT PostGIS_Version()"))
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(postgis_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(postgis_engine)
