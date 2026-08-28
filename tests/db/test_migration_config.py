from __future__ import annotations

import ast
import configparser
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _parse_python(path: str) -> ast.Module:
    return ast.parse(_read(path), filename=path)


def test_migration_dependencies_have_supported_bounds() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        dependencies = tomllib.load(handle)["project"]["dependencies"]

    assert [item for item in dependencies if item.startswith("alembic")] == [
        "alembic>=1.16,<2"
    ]
    assert [item for item in dependencies if item.startswith("geoalchemy2")] == [
        "geoalchemy2>=0.18,<1"
    ]


def test_alembic_ini_is_safe_and_points_to_migrations() -> None:
    path = ROOT / "alembic.ini"
    assert path.is_file(), "alembic.ini must exist"

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    assert parser.get("alembic", "script_location") == "migrations"
    assert not parser.has_option("alembic", "sqlalchemy.url")

    text = path.read_text(encoding="utf-8").lower()
    assert "sqlalchemy.url" not in text
    assert "://" not in text
    assert "password" not in text


def test_declarative_base_has_deterministic_naming() -> None:
    tree = _parse_python("georeport3d/db/base.py")
    convention = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "NAMING_CONVENTION"
            for target in node.targets
        )
    )
    assert ast.literal_eval(convention.value) == {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }

    base_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Base"
    )
    assert [ast.unparse(base) for base in base_class.bases] == ["DeclarativeBase"]
    metadata = next(
        node
        for node in base_class.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "metadata"
            for target in node.targets
        )
    )
    assert ast.unparse(metadata.value) == "MetaData(naming_convention=NAMING_CONVENTION)"


def test_migration_environment_preserves_injected_url_and_uses_settings_default() -> None:
    tree = _parse_python("migrations/env.py")
    source = ast.unparse(tree)

    assert "target_metadata = Base.metadata" in source
    assert "Settings().database_url" in source
    assert "def run_migrations_offline()" in source
    assert "def run_migrations_online()" in source
    assert "poolclass=pool.NullPool" in source
    assert source.count("compare_type=True") == 2
    assert "literal_binds=True" in source
    assert "context.begin_transaction()" in source

    guarded_default = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and ast.unparse(node.test.operand.func) == "config.get_main_option"
    )
    assert ast.literal_eval(guarded_default.test.operand.args[0]) == "sqlalchemy.url"
    guarded_source = ast.unparse(ast.Module(body=guarded_default.body, type_ignores=[]))
    assert "Settings().database_url" in guarded_source
    assert "config.set_main_option" in guarded_source
    replace_call = next(
        node
        for node in ast.walk(guarded_default)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
    )
    assert [ast.literal_eval(argument) for argument in replace_call.args] == ["%", "%%"]

    engine_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "engine_from_config"
    )
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in engine_call.keywords}
    prefix = next(item.value for item in engine_call.keywords if item.arg == "prefix")
    assert ast.literal_eval(prefix) == "sqlalchemy."
    assert keywords["poolclass"] == "pool.NullPool"


def test_revision_template_is_complete_and_schema_free() -> None:
    text = _read("migrations/script.py.mako")

    for placeholder in (
        "${message}",
        "${up_revision}",
        "${down_revision | comma,n}",
        "${create_date}",
        "${imports if imports else \"\"}",
        "${upgrades if upgrades else \"pass\"}",
        "${downgrades if downgrades else \"pass\"}",
    ):
        assert placeholder in text
    assert "from alembic import op" in text
    assert "import sqlalchemy as sa" in text
    assert "def upgrade() -> None:" in text
    assert "def downgrade() -> None:" in text
    assert "create_table" not in text
    assert "CREATE EXTENSION" not in text


def test_compose_service_is_loopback_only_and_test_scoped() -> None:
    text = _read("compose.yaml")
    lines = text.splitlines()

    assert lines[0] == "# Local-test credentials only; never reuse in production."
    assert lines.count("services:") == 1
    assert lines.count("  db:") == 1
    assert "    image: postgis/postgis:17-3.5" in lines
    assert "      POSTGRES_DB: georeport3d_test" in lines
    assert "      POSTGRES_USER: postgres" in lines
    assert "      POSTGRES_PASSWORD: postgres" in lines
    assert '      - "127.0.0.1:5432:5432"' in lines
    assert (
        '      test: ["CMD-SHELL", "pg_isready -U postgres -d georeport3d_test"]'
        in lines
    )
    assert "      - georeport3d-postgis:/var/lib/postgresql/data" in lines
    assert lines.count("    volumes:") == 1
    assert lines.count("volumes:") == 1
    assert lines[-1] == "  georeport3d-postgis:"
    assert "0.0.0.0" not in text
    assert '      - "5432:5432"' not in lines
