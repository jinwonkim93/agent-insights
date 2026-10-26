"""Explicit schema upgrades. Run with a single deployment migration job."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect


def upgrade(engine):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as connection:
        inspector = inspect(connection)
        existing = set(inspector.get_table_names())
        owned = {"conversations", "topics", "facets", "discovery_locks"}
        if owned & existing and "alembic_version" not in existing:
            # Adopt only a complete legacy schema matching the frozen baseline.
            import importlib.util

            path = Path(__file__).parent / "migrations/versions/0001_initial.py"
            spec = importlib.util.spec_from_file_location("baseline", path)
            baseline = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(baseline)
            for table in baseline.metadata.sorted_tables:
                if table.name not in existing:
                    raise RuntimeError(
                        "Incomplete legacy schema; restore or repair before migrating"
                    )
                columns = {column["name"]: column for column in inspector.get_columns(table.name)}
                if set(columns) != set(table.columns.keys()):
                    raise RuntimeError("Legacy schema mismatch; manual migration required")
                for column in table.columns:
                    actual = columns[column.name]
                    if actual["type"]._type_affinity is not column.type._type_affinity:
                        raise RuntimeError("Legacy column type mismatch; manual migration required")
                expected_pk = {c.name for c in table.primary_key}
                if (
                    set(inspector.get_pk_constraint(table.name)["constrained_columns"])
                    != expected_pk
                ):
                    raise RuntimeError("Legacy primary key mismatch; manual migration required")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
