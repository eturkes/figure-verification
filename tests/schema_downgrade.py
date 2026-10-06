# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Exact historic-schema downgrades for archive migration fixtures.

A fixture must reach the byte-exact stored DDL of the version it claims to be. Dropping later
objects from a table still carrying current text leaves a fake fixture that keeps passing while
testing nothing, so the v4 -> v3 step reverses all three table deltas in the stored text, and the
v5 -> v4 step drops every relation guard the v5 migration adds.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from verifier.service import archive as archive_module


def drop_relation_guards(connection: sqlite3.Connection) -> None:
    """Remove the v5 UPDATE/DELETE guards, as a raw writer of the database file could."""
    for _object_type, name, _table, _statement in archive_module._RELATION_GUARDS:
        connection.execute(f"DROP TRIGGER {name}")


@contextmanager
def relation_guards_lifted(connection: sqlite3.Connection, *guards: str) -> Iterator[None]:
    """Tamper as a raw writer would: drop exactly the named guards -- the ones the tamper crosses --
    for the block, then restore them, so the schema stays exact and no other guard is down."""
    if not guards:
        message = "name the guard(s) the tamper crosses"
        raise ValueError(message)
    statements = {name: sql for _kind, name, _table, sql in archive_module._RELATION_GUARDS}
    for name in guards:
        connection.execute(f"DROP TRIGGER {name}")
    try:
        yield
    finally:
        for name in guards:
            connection.execute(statements[name])


def downgrade_to_v4(connection: sqlite3.Connection) -> None:
    """Rewrite a v5 archive into an exact v4 one, in place, on an autocommit connection."""
    drop_relation_guards(connection)
    connection.execute("UPDATE meta SET schema_version = 4 WHERE singleton = 1")
    connection.execute("PRAGMA user_version=4")


def downgrade_to_v3(connection: sqlite3.Connection) -> None:
    """Rewrite a v5 archive into an exact v3 one, in place, on an autocommit connection."""
    downgrade_to_v4(connection)
    connection.execute("DROP TRIGGER plot_references_match_source")
    connection.execute("ALTER TABLE plots DROP COLUMN source_kind")
    connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, archive_module._CONFIG_OFF)
    try:
        connection.execute("PRAGMA writable_schema=ON")
        for name, statement in (
            ("blobs", archive_module._CREATE_BLOBS_V3),
            ("plot_references", archive_module._CREATE_PLOT_REFERENCES_V3),
            ("plots", archive_module._CREATE_PLOTS_V3),
        ):
            connection.execute(
                "UPDATE sqlite_schema SET sql = ? WHERE type = 'table' AND name = ?",
                (statement, name),
            )
        cookie = connection.execute("PRAGMA schema_version").fetchone()[0]
        connection.execute(f"PRAGMA schema_version={cookie + 1}")
        connection.execute("PRAGMA writable_schema=RESET")
    finally:
        connection.execute("PRAGMA writable_schema=OFF")
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, archive_module._CONFIG_ON)
    connection.execute("UPDATE meta SET schema_version = 3 WHERE singleton = 1")
    connection.execute("PRAGMA user_version=3")
