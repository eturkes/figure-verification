# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent v3→v5 conventional rebuild from frozen DDL; no verifier imports.

The three changed v3 table statements are historic literals pinned by test_service_archive.
The v5 golden fixes the destination structure: v4's tables and mode trigger plus v5's ten
relation guards. Temporary-table rename may quote table names;
comparison owns logical structure/rows, not SQLite's equivalent table-name spelling.
"""

import json
import sqlite3
from pathlib import Path
from typing import cast

SchemaObject = tuple[str, str, str, str]
_TABLES = (
    "meta",
    "blobs",
    "keys",
    "plots",
    "specs",
    "attempts",
    "plot_references",
    "attempt_references",
)
_GOLDEN = Path(__file__).resolve().parent / "golden"

DATASET_ROLES = (
    "raw_csv",
    "raw_manifest",
    "canonical_spec",
    "plotted_table",
    "verdict",
    "vega_lite",
    "svg",
    "vcert_payload",
    "tool_versions",
)
FORMULA_ROLES = (
    "canonical_spec",
    "formula_source",
    "plotted_table",
    "verdict",
    "matplotlib_script",
    "vcert_payload",
    "tool_versions",
)
MODE_TRIGGER = """CREATE TRIGGER plot_references_match_source
BEFORE INSERT ON plot_references
WHEN NOT EXISTS (
    SELECT 1 FROM plots WHERE plot_id = NEW.plot_id
    AND ((source_kind = 'dataset' AND NEW.role IN (
        'raw_csv', 'raw_manifest', 'canonical_spec', 'plotted_table', 'verdict',
        'vega_lite', 'svg', 'vcert_payload', 'tool_versions'
    )) OR (source_kind = 'formula' AND NEW.role IN (
        'canonical_spec', 'formula_source', 'plotted_table', 'verdict',
        'matplotlib_script', 'vcert_payload', 'tool_versions'
    )))
)
BEGIN
    SELECT RAISE(ABORT, 'archive plot reference crosses source');
END"""


class OracleError(Exception):
    """The input is not the contract's exact v3 archive."""


def schema_fixture(version: int) -> tuple[SchemaObject, ...]:
    """Load independent stored-DDL bytes, never production-derived constants."""
    raw = json.loads((_GOLDEN / f"archive_schema_v{version}.json").read_text())
    if not isinstance(raw, list) or not all(
        isinstance(row, list) and len(row) == 4 and all(isinstance(cell, str) for cell in row)
        for row in raw
    ):
        message = f"invalid v{version} DDL fixture"
        raise OracleError(message)
    return tuple((row[0], row[1], row[2], row[3]) for row in cast("list[list[str]]", raw))


def stored_schema(connection: sqlite3.Connection) -> tuple[SchemaObject, ...]:
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema "
        "WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()
    return cast("tuple[SchemaObject, ...]", tuple(rows))


def table_info(connection: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    return {name: connection.execute(f'PRAGMA table_info("{name}")').fetchall() for name in _TABLES}


def expected_table_info() -> dict[str, list[tuple[object, ...]]]:
    connection = sqlite3.connect(":memory:", autocommit=True)
    try:
        for _, _, _, statement in schema_fixture(5):
            connection.execute(statement)
        return table_info(connection)
    finally:
        connection.close()


def migrate(path: Path) -> None:
    """Rebuild all tables conventionally; preserve every old column and add dataset source tags."""
    connection = sqlite3.connect(path, autocommit=True)
    try:
        prior = schema_fixture(3)
        if stored_schema(connection) != tuple(sorted(prior)):
            message = "oracle input stored DDL is not exact v3"
            raise OracleError(message)
        if connection.execute("PRAGMA user_version").fetchone() != (3,) or connection.execute(
            "SELECT schema_version FROM meta WHERE singleton = 1"
        ).fetchone() != (3,):
            message = "oracle input version fields are not v3"
            raise OracleError(message)
        # Foreign-key toggles take effect outside transactions; content-copy triggers stay absent.
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            _rebuild(connection, prior)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("PRAGMA foreign_keys=ON")
    finally:
        connection.close()


def _rebuild(connection: sqlite3.Connection, prior: tuple[SchemaObject, ...]) -> None:
    target = schema_fixture(5)
    for kind, name, _, _ in prior:
        if kind in {"trigger", "index"}:
            connection.execute(f'DROP {kind.upper()} "{name}"')
    for kind, name, _, statement in target:
        if kind != "table":
            continue
        staged = f"rebuild_{name}"
        connection.execute(
            statement.replace(f"CREATE TABLE {name} (", f'CREATE TABLE "{staged}" (', 1)
        )
        columns = [
            cast("str", row[1]) for row in connection.execute(f'PRAGMA table_info("{name}")')
        ]
        selected = ", ".join(f'"{column}"' for column in columns)
        if name == "plots":
            selected += ", 'dataset'"
        connection.execute(f'INSERT INTO "{staged}" SELECT {selected} FROM "{name}"')  # noqa: S608
    for name in reversed(_TABLES):
        connection.execute(f'DROP TABLE "{name}"')
    for name in _TABLES:
        connection.execute(f'ALTER TABLE "rebuild_{name}" RENAME TO "{name}"')
    connection.execute("UPDATE meta SET schema_version = 5 WHERE singleton = 1")
    connection.execute("PRAGMA user_version=5")
    for kind, name, _, statement in target:
        if kind != "table":
            connection.execute(
                MODE_TRIGGER if name == "plot_references_match_source" else statement
            )
