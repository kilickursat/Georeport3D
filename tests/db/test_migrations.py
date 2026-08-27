"""Explicitly authorized integration check for a loopback PostGIS test database."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest


EXPECTED_TABLES = {
    "projects",
    "documents",
    "boreholes",
    "borehole_intervals",
    "evidence",
    "borehole_evidence",
    "borehole_interval_evidence",
    "inference_jobs",
    "usage_records",
    "inference_cache",
}


def _authorized_test_database_url() -> str:
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


@pytest.mark.integration
def test_upgrade_head_creates_postgis_schema() -> None:
    url = _authorized_test_database_url()

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            postgis_version = connection.execute(
                text("SELECT PostGIS_Version()")
            ).scalar_one()
            assert postgis_version
            tables = set(inspect(connection).get_table_names())
        assert EXPECTED_TABLES <= tables
    finally:
        engine.dispose()
