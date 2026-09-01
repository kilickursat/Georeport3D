"""Shared PostGIS fixtures, gated by the same explicit opt-in as the migration test."""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from georeport3d.db.base import Base
from georeport3d.db.session import create_database_engine, create_session_factory

# Imported for its side effect: the models register themselves on `Base.metadata`,
# which is what the truncation fixture enumerates. Without this the metadata is empty
# and every test silently shares state again.
from georeport3d.db import models as _models  # noqa: F401  isort:skip


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


@pytest.fixture(autouse=True)
def clean_database(postgis_engine: Engine) -> Iterator[None]:
    """Give every test an empty database.

    The suite shares one database, and durable rows are exactly the point of these
    tests, so what one test leaves behind another one reads. That is not a
    hypothetical: a single job left in `GPU_RUNNING` by an API test held a GPU slot
    for the whole run, and twenty-three controller tests then failed admission for a
    reason none of them named.

    Truncation rather than a wrapping transaction, because admission takes a
    transaction-scoped advisory lock across two sessions and a second must be able to
    watch the first commit. An outer transaction would change the very concurrency
    these tests exist to check.

    Cleaning before rather than after also leaves the rows of a failing test in place
    to be inspected.
    """
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with postgis_engine.begin() as connection:
        # CASCADE covers the foreign keys between them; RESTART IDENTITY resets any
        # sequence so identifiers do not drift across a run.
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def session_factory(postgis_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(postgis_engine)
