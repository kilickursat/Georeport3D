"""Persist cache identity, enforce single-flight, and protect settled usage.

Revision ID: 20260831_0002
Revises: 20260827_0001
Create Date: 2026-08-31

Three changes, each closing a hole that only appears under concurrency or deletion:

`inference_jobs.cache_key` records the canonical work identity a job was admitted
for, so an idempotency replay can be compared against what it originally asked for
rather than trusted.

The partial unique index makes single-flight a database property. Two requests for
identical work that arrive together would otherwise each authorize a GPU and pay
twice for one result. Terminal rows are excluded so the same work may run again
later once it has settled.

The usage foreign key becomes RESTRICT. Usage rows are accounting facts about money
already spent, and cascading them away when a document is deleted would free budget
that is gone.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0002"
down_revision: str | Sequence[str] | None = "20260827_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Terminal states, spelled out rather than imported. A migration must keep meaning
# the same thing when the application's state machine later changes, otherwise
# re-running it against an old database would build a different index.
_LIVE_PREDICATE = (
    "cache_key IS NOT NULL AND state NOT IN "
    "('COMPLETED', 'REJECTED', 'CANCELLED', 'FAILED', 'BUDGET_EXCEEDED', 'TIMEOUT')"
)

# The name this project's naming convention produces. Never assume PostgreSQL's
# default `<table>_<column>_fkey` here: the baseline declared the constraint through
# metadata carrying a convention, so the deployed name follows that instead.
_USAGE_FK = "fk_usage_records_inference_job_id_inference_jobs"


def _usage_fk_name() -> str:
    """Resolve the live constraint name rather than trusting a spelling.

    A migration that drops a constraint by a guessed name fails on every database
    whose name differs, and the guess is invisible until it runs. Asking the catalog
    keeps this correct across a database built by the baseline migration and one
    built from metadata.
    """
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys("usage_records"):
        if foreign_key["constrained_columns"] == ["inference_job_id"]:
            name = foreign_key.get("name")
            if name:
                return str(name)
    return _USAGE_FK


def _swap_usage_fk(ondelete: str) -> None:
    op.drop_constraint(_usage_fk_name(), "usage_records", type_="foreignkey")
    op.create_foreign_key(
        _USAGE_FK,
        "usage_records",
        "inference_jobs",
        ["inference_job_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    op.add_column("inference_jobs", sa.Column("cache_key", sa.String(64), nullable=True))
    op.create_index(
        "uq_inference_jobs_live_cache_key",
        "inference_jobs",
        ["cache_key"],
        unique=True,
        postgresql_where=sa.text(_LIVE_PREDICATE),
    )

    _swap_usage_fk("RESTRICT")


def downgrade() -> None:
    # Restore the cascade before dropping the index and column, so a database left
    # at the previous revision behaves exactly as it did before this one ran.
    _swap_usage_fk("CASCADE")

    op.drop_index("uq_inference_jobs_live_cache_key", table_name="inference_jobs")
    op.drop_column("inference_jobs", "cache_key")
