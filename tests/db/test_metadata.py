"""Import-safe source contract for the authoritative PostGIS baseline."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "georeport3d" / "db" / "models.py"
MIGRATION = ROOT / "migrations" / "versions" / "20260827_0001_baseline.py"
TABLES = {
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


class MetadataSourceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.models = MODELS.read_text(encoding="utf-8")
        self.migration = MIGRATION.read_text(encoding="utf-8")

    def test_models_declare_exact_baseline_tables(self) -> None:
        tree = ast.parse(self.models)
        tables = {
            ast.literal_eval(statement.value)
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            for statement in node.body
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__tablename__"
                for target in statement.targets
            )
        }
        self.assertEqual(tables, TABLES)

    def test_native_geometry_is_never_falsely_wgs84(self) -> None:
        combined = self.models + self.migration
        self.assertNotIn("4326", combined)
        self.assertNotIn("POINTZ", combined.upper())
        for required in (
            'geometry_type="POINT"',
            "srid=-1",
            "spatial_index=False",
            "paired_xy",
            "geometry_has_native_identity",
            "geometry_srid_matches",
            "ST_SRID(geom_project) = srid",
            'postgresql_using="gist"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

    def test_schema_keeps_provenance_cost_and_validation_contracts(self) -> None:
        combined = self.models + self.migration
        for required in (
            "ondelete=\"CASCADE\"",
            "primary_key=True",
            "Numeric(12, 6)",
            "JSONB",
            "depth_order",
            "confidence_range",
            "rqd_range",
            "estimated_usd_nonnegative",
            "reserved_usd_nonnegative",
            "actual_seconds_nonnegative",
            "actual_usd_nonnegative",
            "uq_documents_project_sha256",
            "uq_boreholes_project_borehole",
            "uq_inference_jobs_idempotency_key",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

    def test_migration_is_explicit_ordered_and_keeps_shared_extension(self) -> None:
        tree = ast.parse(self.migration)
        self.assertIn('revision: str = "20260827_0001"', self.migration)
        self.assertIn("down_revision: str | Sequence[str] | None = None", self.migration)
        self.assertIn('CREATE EXTENSION IF NOT EXISTS postgis', self.migration)
        self.assertNotIn("DROP EXTENSION", self.migration.upper())
        for table in TABLES:
            with self.subTest(table=table):
                self.assertIn(f'"{table}"', self.migration)
                self.assertIn(f'op.drop_table("{table}")', self.migration)
        compile(tree, str(MIGRATION), "exec")


if __name__ == "__main__":
    unittest.main()
