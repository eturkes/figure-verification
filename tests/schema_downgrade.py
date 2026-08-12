# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Exact historic-schema downgrades for archive migration fixtures.

A fixture must reach the byte-exact stored DDL of the version it claims to be. Dropping later
objects from a table still carrying current text leaves a fake fixture that keeps passing while
testing nothing, so the v4 -> v3 step reverses all three table deltas in the stored text.
"""

import sqlite3

from verifier.service import archive as archive_module


def downgrade_to_v3(connection: sqlite3.Connection) -> None:
    """Rewrite a v4 archive into an exact v3 one, in place, on an autocommit connection."""
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
