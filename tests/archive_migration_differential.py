# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""p3/p43: regenerate M9.7a's seven archive shapes and compare rewrite versus rebuild.

Run: uv run --locked python tests/archive_migration_differential.py
Gate: tests/test_archive_migration_differential.py runs three small shapes + a row-loss probe.
Logical sections must match BOTH the independent v3→v4 expectation and each other. Rootpages
of every pre-existing object must survive the shipped rewrite. Trigger text may differ only
between the frozen shipped form and the independently authored oracle form; both must implement
the closed dataset/formula role matrix. Physical sizes are expected-divergent: compare the
rewrite with its v3 input, report the rebuild size, never demand equality between mechanisms.

This is SQL-storage equivalence, not certificate authenticity: publish() carries synthetic
opaque envelopes. The lost corpus's exact bytes are unavailable; these are reconstructed shapes.
"""

import argparse
import hashlib
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import verifier
from oracle_archive_migration import (
    DATASET_ROLES,
    FORMULA_ROLES,
    MODE_TRIGGER,
    OracleError,
    expected_table_info,
    migrate,
    schema_fixture,
    stored_schema,
    table_info,
)
from schema_downgrade import downgrade_to_v3
from verifier.service.archive import (
    Archive,
    ArchiveBatch,
    AttemptRecord,
    AttemptReference,
    AttemptRole,
    BlobKind,
    BlobWrite,
    KeyRecord,
    PlotRecord,
    PlotReference,
    PlotRole,
    PlotSourceKind,
    SpecRecord,
)

_ROOT = Path(__file__).resolve().parent.parent
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
# Counts exclude meta (one row). Each case must actually exercise its stated shape.
_SHAPES = {
    "empty": (0, 0, 0, 0, 0, 0, 0),
    "zero-plots": (2, 0, 0, 1, 0, 0, 0),
    "one-plot-full-roles": (11, 1, 1, 1, 0, 9, 0),
    "shared-dedup": (12, 1, 2, 1, 0, 18, 0),
    "attempt-with-plot": (17, 1, 1, 1, 1, 9, 8),
    "attempt-without-plot": (11, 1, 0, 1, 1, 0, 8),
    "large-200": (220, 1, 1, 1, 1, 9, 8),
}
_PLOT_FIELDS = (
    (PlotRole.RAW_CSV, "csv"),
    (PlotRole.RAW_MANIFEST, "manifest"),
    (PlotRole.CANONICAL_SPEC, "spec"),
    (PlotRole.PLOTTED_TABLE, "table"),
    (PlotRole.VERDICT, "verdict"),
    (PlotRole.VEGA_LITE, "vega"),
    (PlotRole.SVG, "svg"),
    (PlotRole.VCERT_PAYLOAD, "payload"),
    (PlotRole.TOOL_VERSIONS, "versions"),
)
_ATTEMPT_FIELDS = (
    (AttemptRole.RAW_CSV, "csv"),
    (AttemptRole.RAW_MANIFEST, "manifest"),
    (AttemptRole.RAW_SPEC, "raw_spec"),
    (AttemptRole.VERDICT, "verdict"),
    (AttemptRole.MODEL_REQUEST, "request"),
    (AttemptRole.MODEL_RESPONSE, "response"),
    (AttemptRole.MODEL_REPLY, "reply"),
    (AttemptRole.ATTEMPT_PAYLOAD, "attempt_payload"),
)
_LOGICAL = (
    "table_info",
    "rows",
    "blob_content_sha256",
    "logical_blob_bytes",
    "meta",
    "user_version",
    "foreign_key_check",
    "integrity_check",
)
_SECTIONS = (
    *_LOGICAL,
    "rootpages",
    "trigger_behavior",
    "trigger_sql_form",
    "file_size",
    "page_count",
)
_LARGE_BLOB_BYTES = 36_000
_QUOTA = 1 << 30


@dataclass(frozen=True, slots=True)
class Snapshot:
    sections: dict[str, object]
    rootpages: dict[str, int]
    triggers: dict[str, str]
    file_size: int
    page_count: int


@dataclass(frozen=True, slots=True)
class Result:
    case: str
    cells: dict[str, str]
    failures: tuple[str, ...]
    metrics: str


def _archive(state: Path) -> Archive:
    return Archive(state, max_logical_bytes=_QUOTA, max_spec_bytes=1 << 20)


def _batch(tag: str, *, plot: bool, attempt: bool, shared: bool = False) -> ArchiveBatch:
    content_tag = "shared" if shared else tag
    payloads = {
        "key": BlobWrite(BlobKind.ED25519_PUBLIC_KEY, b"K" * 32),
        "certificate": BlobWrite(BlobKind.VCERT_ENVELOPE, f"certificate:{tag}".encode()),
        "attempt": BlobWrite(BlobKind.ATTEMPT_ENVELOPE, f"attempt:{tag}".encode()),
        "csv": BlobWrite(BlobKind.RAW_CSV, f"name,value\n{content_tag},0.2\n".encode()),
        "manifest": BlobWrite(BlobKind.RAW_MANIFEST, f'{{"dataset":"{content_tag}"}}'.encode()),
        "spec": BlobWrite(BlobKind.CANONICAL_SPEC, f'{{"spec":"{content_tag}"}}'.encode()),
        "table": BlobWrite(BlobKind.PLOTTED_TABLE, f'[["{content_tag}","0.2"]]'.encode()),
        "verdict": BlobWrite(BlobKind.VERDICT, b"same bytes under two truthful kinds"),
        "vega": BlobWrite(BlobKind.VEGA_LITE, b'{"mark":"bar"}'),
        "svg": BlobWrite(BlobKind.SVG, "<svg>日本語</svg>".encode()),
        "payload": BlobWrite(BlobKind.VCERT_PAYLOAD, b'{"certificate":"v0.2"}'),
        "versions": BlobWrite(BlobKind.TOOL_VERSIONS, b'{"verifier":"fixture"}'),
        "raw_spec": BlobWrite(BlobKind.RAW_SPEC, b"same bytes under two truthful kinds"),
        "request": BlobWrite(BlobKind.MODEL_REQUEST, b'{"messages":[]}'),
        "response": BlobWrite(BlobKind.MODEL_RESPONSE, b'{"choices":[]}'),
        "reply": BlobWrite(BlobKind.MODEL_REPLY, b"{}"),
        "attempt_payload": BlobWrite(BlobKind.ATTEMPT_PAYLOAD, b'{"attempt":"v0.1"}'),
    }
    selected = {"key", "spec"}
    if plot:
        selected.update(name for _, name in _PLOT_FIELDS)
        selected.add("certificate")
    if attempt:
        selected.update(name for _, name in _ATTEMPT_FIELDS)
        selected.add("attempt")
    keyid = payloads["key"].ref.digest
    plot_id = payloads["certificate"].ref.digest.removeprefix("sha256:")
    attempt_id = payloads["attempt"].ref.digest.removeprefix("sha256:")
    return ArchiveBatch(
        blobs=tuple(blob for name, blob in payloads.items() if name in selected),
        keys=(KeyRecord(keyid, payloads["key"].ref),),
        plots=(PlotRecord(plot_id, payloads["certificate"].ref, keyid, PlotSourceKind.DATASET),)
        if plot
        else (),
        specs=(
            SpecRecord(payloads["spec"].ref.digest.removeprefix("sha256:"), payloads["spec"].ref),
        ),
        attempts=(
            AttemptRecord(attempt_id, payloads["attempt"].ref, keyid, plot_id if plot else None),
        )
        if attempt
        else (),
        plot_references=tuple(
            PlotReference(plot_id, role, payloads[name].ref) for role, name in _PLOT_FIELDS
        )
        if plot
        else (),
        attempt_references=tuple(
            AttemptReference(attempt_id, role, payloads[name].ref) for role, name in _ATTEMPT_FIELDS
        )
        if attempt
        else (),
    )


def _build(case: str, state: Path) -> Path:
    archive = _archive(state)
    if case == "zero-plots":
        spec = BlobWrite(BlobKind.CANONICAL_SPEC, b'{"standalone":true}')
        archive.publish(
            ArchiveBatch(
                blobs=(spec, BlobWrite(BlobKind.RAW_CSV, b"")),
                specs=(SpecRecord(spec.ref.digest.removeprefix("sha256:"), spec.ref),),
            )
        )
    elif case == "shared-dedup":
        first = _batch("shared-first", plot=True, attempt=False, shared=True)
        archive.publish(first)
        archive.publish(_batch("shared-second", plot=True, attempt=False, shared=True))
        archive.publish(first)
    elif case in {"one-plot-full-roles", "attempt-with-plot", "attempt-without-plot", "large-200"}:
        archive.publish(
            _batch(case, plot=case != "attempt-without-plot", attempt=case != "one-plot-full-roles")
        )
        if case == "large-200":
            extras = tuple(
                BlobWrite(
                    BlobKind.RAW_CSV, f"large-{index:03d}\n".encode().ljust(_LARGE_BLOB_BYTES, b"x")
                )
                for index in range(200)
            )
            boundaries = (
                BlobWrite(BlobKind.RAW_CSV, b""),
                BlobWrite(BlobKind.RAW_CSV, b"\x00\xff"),
                BlobWrite(BlobKind.RAW_MANIFEST, "日́本".encode()),
            )
            archive.publish(ArchiveBatch(blobs=(*extras, *boundaries)))
    elif case != "empty":
        message = f"unknown corpus case: {case}"
        raise OracleError(message)
    connection = sqlite3.connect(archive.database_path, autocommit=True)
    try:
        counts = tuple(
            connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]  # noqa: S608
            for name in _TABLES[1:]
        )
        if counts != _SHAPES[case]:
            message = f"corpus shape {case}: expected {_SHAPES[case]}, got {counts}"
            raise OracleError(message)
        downgrade_to_v3(connection)
        if stored_schema(connection) != tuple(sorted(schema_fixture(3))):
            message = f"corpus {case}: downgrade did not reach exact v3 DDL"
            raise OracleError(message)
    finally:
        connection.close()
    return archive.database_path


def _snapshot(path: Path) -> Snapshot:
    connection = sqlite3.connect(path, autocommit=True)
    try:
        rows = {
            name: connection.execute(
                "SELECT blob_id, digest, kind, size FROM blobs ORDER BY blob_id"
                if name == "blobs"
                else f'SELECT * FROM "{name}" ORDER BY 1, 2'  # noqa: S608
            ).fetchall()
            for name in _TABLES
        }
        contents = tuple(
            (blob_id, digest, kind, hashlib.sha256(content).hexdigest())
            for blob_id, digest, kind, content in connection.execute(
                "SELECT blob_id, digest, kind, content FROM blobs ORDER BY blob_id"
            )
        )
        sections: dict[str, object] = {
            "table_info": table_info(connection),
            "rows": rows,
            "blob_content_sha256": contents,
            "logical_blob_bytes": (
                connection.execute(
                    "SELECT logical_blob_bytes FROM meta WHERE singleton = 1"
                ).fetchone()[0],
                connection.execute("SELECT COALESCE(SUM(size), 0) FROM blobs").fetchone()[0],
            ),
            "meta": connection.execute("SELECT * FROM meta ORDER BY singleton").fetchall(),
            "user_version": connection.execute("PRAGMA user_version").fetchone(),
            "foreign_key_check": connection.execute("PRAGMA foreign_key_check").fetchall(),
            "integrity_check": connection.execute("PRAGMA integrity_check").fetchall(),
        }
        rootpages = dict(connection.execute("SELECT name, rootpage FROM sqlite_schema").fetchall())
        triggers = dict(
            connection.execute(
                "SELECT name, sql FROM sqlite_schema WHERE type = 'trigger'"
            ).fetchall()
        )
        return Snapshot(
            sections,
            rootpages,
            triggers,
            path.stat().st_size,
            connection.execute("PRAGMA page_count").fetchone()[0],
        )
    finally:
        connection.close()


def _expected(prior: Snapshot) -> dict[str, object]:
    sections = dict(prior.sections)
    rows = dict(cast("dict[str, list[tuple[object, ...]]]", sections["rows"]))
    rows["plots"] = [(*row, "dataset") for row in rows["plots"]]
    rows["meta"] = [(singleton, 4, logical) for singleton, _, logical in rows["meta"]]
    sections.update(
        table_info=expected_table_info(), rows=rows, meta=rows["meta"], user_version=(4,)
    )
    if prior.sections["foreign_key_check"] != [] or prior.sections["integrity_check"] != [("ok",)]:
        message = "v3 corpus failed foreign-key/integrity checks"
        raise OracleError(message)
    logical = cast("tuple[int, int]", prior.sections["logical_blob_bytes"])
    if logical[0] != logical[1]:
        message = "v3 corpus logical-byte counter disagrees with blob sizes"
        raise OracleError(message)
    return sections


def _put_blob(connection: sqlite3.Connection, kind: str, content: bytes) -> str:
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    connection.execute(
        "INSERT OR IGNORE INTO blobs(digest, kind, size, content) VALUES (?, ?, ?, ?)",
        (digest, kind, len(content), content),
    )
    return digest


def _trigger_behavior(path: Path) -> dict[tuple[str, str], bool]:
    connection = sqlite3.connect(path, autocommit=True)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN")
    outcomes: dict[tuple[str, str], bool] = {}
    try:
        keyid = _put_blob(connection, "ed25519_public_key", b"P" * 32)
        connection.execute(
            "INSERT OR IGNORE INTO keys VALUES (?, ?, ?)", (keyid, keyid, "ed25519_public_key")
        )
        roles = tuple(dict.fromkeys((*DATASET_ROLES, *FORMULA_ROLES)))
        digests = {role: _put_blob(connection, role, role.encode()) for role in roles}
        for source in ("dataset", "formula"):
            envelope = _put_blob(connection, "vcert_envelope", f"trigger-parent:{source}".encode())
            plot_id = envelope.removeprefix("sha256:")
            connection.execute(
                "INSERT INTO plots VALUES (?, ?, ?, ?, ?)",
                (plot_id, envelope, "vcert_envelope", keyid, source),
            )
            for role in (*roles, "formula_sourc", "future_role", ""):
                outcomes[source, role] = _reference_admitted(
                    connection, plot_id, role, digests.get(role, digests["raw_csv"])
                )
        outcomes["absent-parent", "canonical_spec"] = _reference_admitted(
            connection, "0" * 64, "canonical_spec", digests["canonical_spec"]
        )
    finally:
        connection.execute("ROLLBACK")
        connection.close()
    return outcomes


def _reference_admitted(
    connection: sqlite3.Connection, plot_id: str, role: str, digest: str
) -> bool:
    connection.execute("SAVEPOINT reference_probe")
    try:
        connection.execute(
            "INSERT INTO plot_references VALUES (?, ?, ?, ?)", (plot_id, role, digest, role)
        )
    except sqlite3.IntegrityError:
        return False
    else:
        return True
    finally:
        connection.execute("ROLLBACK TO reference_probe")
        connection.execute("RELEASE reference_probe")


def _expected_behavior() -> dict[tuple[str, str], bool]:
    roles = tuple(
        dict.fromkeys((*DATASET_ROLES, *FORMULA_ROLES, "formula_sourc", "future_role", ""))
    )
    result = {
        (source, role): role in admitted
        for source, admitted in (("dataset", DATASET_ROLES), ("formula", FORMULA_ROLES))
        for role in roles
    }
    result["absent-parent", "canonical_spec"] = False
    return result


def _compare(case: str, root: Path, *, plant_row_loss: bool) -> Result:
    source = _build(case, root / "input")
    before = _snapshot(source)
    expected = _expected(before)
    paths: list[Path] = []
    for arm in ("rewrite", "rebuild"):
        state = root / arm
        state.mkdir(mode=0o700)
        destination = state / source.name
        shutil.copy2(source, destination)
        # Both mechanisms receive byte-identical complete SQLite files, not merely equal queries.
        if (
            hashlib.sha256(destination.read_bytes()).digest()
            != hashlib.sha256(source.read_bytes()).digest()
        ):
            message = f"{case}: migration inputs differ"
            raise OracleError(message)
        paths.append(destination)
    rewrite, rebuild = paths
    _archive(rewrite.parent)
    migrate(rebuild)
    if plant_row_loss:
        connection = sqlite3.connect(rebuild, autocommit=True)
        try:
            cursor = connection.execute(
                "DELETE FROM specs WHERE spec_id = (SELECT spec_id FROM specs LIMIT 1)"
            )
            if cursor.rowcount != 1:
                message = f"{case}: row-loss probe needs one spec row"
                raise OracleError(message)
        finally:
            connection.close()
    actual, oracle = _snapshot(rewrite), _snapshot(rebuild)
    checks = {
        section: actual.sections[section] == oracle.sections[section] == expected[section]
        for section in _LOGICAL
    }
    checks["rootpages"] = {
        name: actual.rootpages.get(name) for name in before.rootpages
    } == before.rootpages
    checks["trigger_behavior"] = (
        _trigger_behavior(rewrite) == _trigger_behavior(rebuild) == _expected_behavior()
    )
    shipped_triggers = {name: sql for kind, name, _, sql in schema_fixture(4) if kind == "trigger"}
    oracle_triggers = dict(shipped_triggers, plot_references_match_source=MODE_TRIGGER)
    checks["trigger_sql_form"] = (
        actual.triggers == shipped_triggers and oracle.triggers == oracle_triggers
    )
    cells = {section: "PASS" if passed else "FAIL" for section, passed in checks.items()}
    for section, prior, shipped, reference in (
        ("file_size", before.file_size, actual.file_size, oracle.file_size),
        ("page_count", before.page_count, actual.page_count, oracle.page_count),
    ):
        cells[section] = f"EXPECTED-DIVERGENT({prior}→{shipped}/{reference})"
        checks[section] = shipped == prior
        if not checks[section]:
            cells[section] += ";FAIL(rewrite changed v3 allocation)"
    total_rows = sum(_SHAPES[case]) + 1
    logical_bytes = cast("tuple[int, int]", before.sections["logical_blob_bytes"])[0]
    metrics = f"{case}: blobs={_SHAPES[case][0]} rows={total_rows} logical_bytes={logical_bytes}"
    return Result(
        case, cells, tuple(section for section, passed in checks.items() if not passed), metrics
    )


def _require_local_import() -> None:
    loaded = Path(verifier.__file__).resolve()
    if not loaded.is_relative_to(_ROOT / "src"):
        message = f"vacuous differential: imported {loaded}; expected {_ROOT / 'src'}"
        raise OracleError(message)


def main(argv: Sequence[str] | None = None) -> int:
    """Print every comparison section; rc 0 = pass, 1 = divergence, 2 = invalid setup."""
    parser = argparse.ArgumentParser(
        description="Compare archive v3→v4 rewrite and independent rebuild."
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(_SHAPES),
        help="Run this case. Repeat for a subset.",
    )
    parser.add_argument(
        "--plant-row-loss",
        action="store_true",
        help="Remove one oracle spec row to test comparison failure.",
    )
    args = parser.parse_args(argv)
    selected = tuple(dict.fromkeys(cast("list[str] | None", args.case) or _SHAPES))
    results: list[Result] = []
    try:
        _require_local_import()
        scratch = _ROOT / ".scratch"
        scratch.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="archive-v3-v4-", dir=scratch) as directory:
            for case in selected:
                root = Path(directory) / case
                root.mkdir(mode=0o700)
                results.append(_compare(case, root, plant_row_loss=args.plant_row_loss))
    except (OracleError, sqlite3.DatabaseError, OSError) as error:
        sys.stdout.write(f"setup failed: {error}\n")
        return 2
    sys.stdout.write(
        "rule: logical=both arms equal independent v3→v4 expectation; "
        "physical=expected-divergent, rewrite preserves input allocation\n"
    )
    for result in results:
        sys.stdout.write(f"{result.metrics}\n")
    sys.stdout.write("section | " + " | ".join(selected) + "\n")
    for section in _SECTIONS:
        sys.stdout.write(
            section + " | " + " | ".join(result.cells[section] for result in results) + "\n"
        )
    failures = [f"{result.case}:{section}" for result in results for section in result.failures]
    for failure in failures:
        sys.stdout.write(f"comparison failed: {failure}\n")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
