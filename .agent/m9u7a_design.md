# M9.7a transcription recipe — archive schema v4

Consumed-once design file (M1 right-sizing rule): TRANSCRIBE, do not re-derive. **Delete on M9.7a close.**

## Provenance + trust boundary

- Recipe body below = verbatim extract of `spike-m9u7a-wschema`'s report, produced in worktree `wt/spike-m9u7a-wschema` off baseline `0f0a781` and green there on the full project gate (ruff format/check, mypy, 2,458 pytest @ 100% branch). SQLite 3.46.1.
- **NOT certified line-by-line by MAIN.** No "source-VERIFIED / drift-check DISCHARGED" stamp: MAIN read the probe matrix, the findings, and the verdict, not every emitted line. The recipe is a starting text; the project gate plus M9.7a's own review battery is what credits it. Migration code is judgment-bearing → MAIN re-authors it in the primary tree.
- Drift check before transcribing: `git diff --exit-code 0f0a781 -- src/verifier/service/archive.py tests/test_service_archive.py` (empty = the certified surface is byte-unchanged). Non-empty ⇒ re-derive against the current file instead of transcribing.
- The spike worktrees and `wt/*` branches are removed at session close; this file is the only surviving copy.

## MAIN additions NOT present in the recipe below

- **`plot_references_match_source` trigger** (decided after spike dispatch, so neither spike implemented or probed it). `BEFORE INSERT ON plot_references`, positive allowlist, no `else`/default arm: ABORT unless the referenced plot row exists AND `NEW.role` is in that `plots.source_kind`'s admitted role set (dataset = the 9 existing roles; formula = `canonical_spec, formula_source, plotted_table, verdict, matplotlib_script, vcert_payload, tool_versions`). Soundness precondition, verified: `_insert_batch_rows` (`archive.py:2591`) inserts `plots` BEFORE `plot_references`, and `PRAGMA foreign_keys=ON` (`:1570`) already forces that order, so the subquery always sees the row. This trigger is what discharges the "explicit `source_kind` column is driftable redundant state" objection — it makes tag↔role disagreement unrepresentable rather than merely checked in Python. It is a plain additive `CREATE TRIGGER`: no rebuild, no rewrite; create it in both the fresh-create path and `_migrate_v3_to_v4`, and add it to `_SCHEMA_OBJECTS` (absent from `_SCHEMA_OBJECTS_V3`).
- **Test suite.** The spike's gate ran 2,458 tests = baseline 2,457 + 1: its probes were ad-hoc scripts, NOT committed tests. M9.7a authors the real migration suite from scratch — the probe matrix is the scenario list, not the coverage. At minimum, one committed test per accept predicate: fresh-v4 create; v1/v2/v3 chain migrations asserting blob `(digest,kind,size,content)` equality, relation-row equality, `logical_blob_bytes` unchanged and `= SUM(size)`, `source_kind='dataset'` backfill; injected mid-migration failure rolling back to the prior version; `foreign_key_check`/`integrity_check`; unknown kind/role still ABORT; the mode-guard trigger refusing each cross-mode role; and the defensive-mode flag proven restored after migration.
- **Ordering pins.** Per the recurring project defect class, presence assertions are insufficient: pin the migration's step ORDER with call-counting bombs (defensive-off must precede the rewrite; the physical backfill must precede the NOT-NULL-bearing validation; `RESET` must follow COMMIT), and pin the exact-schema validator's REFUSAL against near-miss DDL text, not only its acceptance.

## Ruling recap (evidence in `.agent/roadmap.md` M9.7a)

Mechanism = direct `sqlite_schema` text rewrite under `PRAGMA writable_schema`; table rebuild REJECTED (2.00× permanent file growth, 3.00× peak, copies every content byte). The losing spike's own author concurred: "prefer peer writable-schema if equally safe; rebuild only fallback."

Hazards carried into the unit — each needs a pin: temporary SQLite **defensive-mode disable** (the mechanism's real integrity-posture price and its primary review target; keep the window inside one `BEGIN IMMEDIATE` and prove it restored); `plots.source_kind` needs a **physical backfill** (column-list rewrite alone leaves NOT-NULL integrity failures); **physical column order preserved** (appended column stays last); schema-cookie bump + `writable_schema=RESET` handling.

Cross-mechanism fact worth keeping (from the rebuild spike, correcting its own brief): **six** tables reference `blobs`, not five; and for a rebuild `PRAGMA foreign_keys=OFF` is a no-op inside an open transaction (needs `Connection.setconfig`), while `defer_foreign_keys` still fails at COMMIT.

---

## Transcription recipe

Runtime authority:

- SQLite: `3.46.1`
- Worktree import: `/run/host/home/eturkes/Projects/figure-verification/.scratch/worktrees/spike-m9u7a-wschema/src/verifier/service/archive.py`
- Verified expression: `verifier.service.archive.__file__ == '/run/host/home/eturkes/Projects/figure-verification/.scratch/worktrees/spike-m9u7a-wschema/src/verifier/service/archive.py'`

### 1. Final v4 DDL constants + exact v3 counterparts

`_CREATE_BLOBS` is the full v4 text; `_CREATE_BLOBS_V3` derives the byte-exact historic definition used by `_SCHEMA_OBJECTS_V3`.

```python
_CREATE_BLOBS = """CREATE TABLE blobs (
    blob_id INTEGER PRIMARY KEY,
    digest TEXT NOT NULL CHECK (
        length(digest) = 71
        AND substr(digest, 1, 7) = 'sha256:'
        AND substr(digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    kind TEXT NOT NULL CHECK (kind IN (
        'raw_csv', 'raw_manifest', 'canonical_spec', 'raw_spec', 'plotted_table',
        'verdict', 'vega_lite', 'svg', 'vcert_payload', 'vcert_envelope',
        'ed25519_public_key', 'tool_versions', 'formula_source', 'matplotlib_script',
        'model_request', 'model_response', 'model_reply', 'attempt_payload',
        'attempt_envelope'
    )),
    size INTEGER NOT NULL CHECK (size >= 0),
    content BLOB NOT NULL,
    UNIQUE (digest, kind),
    CHECK (size = length(content))
) STRICT"""
_CREATE_BLOBS_V3 = _CREATE_BLOBS.replace(
    (
        "'tool_versions', 'formula_source', 'matplotlib_script',\n        "
        "'model_request', 'model_response', 'model_reply', 'attempt_payload',\n        "
        "'attempt_envelope'"
    ),
    (
        "'tool_versions', 'model_request', 'model_response',\n        "
        "'model_reply', 'attempt_payload', 'attempt_envelope'"
    ),
)
```

`_CREATE_PLOT_REFERENCES` is the full v4 text; `_CREATE_PLOT_REFERENCES_V3` removes only the two v4 roles.

```python
_CREATE_PLOT_REFERENCES = """CREATE TABLE plot_references (
    plot_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN (
        'raw_csv', 'raw_manifest', 'canonical_spec', 'plotted_table', 'verdict',
        'vega_lite', 'svg', 'vcert_payload', 'tool_versions', 'formula_source',
        'matplotlib_script'
    )),
    blob_digest TEXT NOT NULL,
    blob_kind TEXT NOT NULL CHECK (blob_kind = role),
    PRIMARY KEY (plot_id, role),
    FOREIGN KEY (plot_id) REFERENCES plots(plot_id),
    FOREIGN KEY (blob_digest, blob_kind) REFERENCES blobs(digest, kind)
) STRICT, WITHOUT ROWID"""
_CREATE_PLOT_REFERENCES_V3 = _CREATE_PLOT_REFERENCES.replace(
    ", 'formula_source',\n        'matplotlib_script'", ""
)
```

`_CREATE_PLOTS` is the full v4 text. `source_kind` is last after `keyid`; `_CREATE_PLOTS_V3` removes exactly that physical-last column.

```python
_CREATE_PLOTS = """CREATE TABLE plots (
    plot_id TEXT PRIMARY KEY CHECK (
        length(plot_id) = 64 AND plot_id NOT GLOB '*[^0-9a-f]*'
    ),
    certificate_digest TEXT NOT NULL,
    certificate_kind TEXT NOT NULL CHECK (certificate_kind = 'vcert_envelope'),
    keyid TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('dataset', 'formula')),
    CHECK (certificate_digest = 'sha256:' || plot_id),
    FOREIGN KEY (certificate_digest, certificate_kind) REFERENCES blobs(digest, kind),
    FOREIGN KEY (keyid) REFERENCES keys(keyid)
) STRICT, WITHOUT ROWID"""
_CREATE_PLOTS_V3 = _CREATE_PLOTS.replace(
    "    source_kind TEXT NOT NULL CHECK (source_kind IN ('dataset', 'formula')),\n", ""
)
```

### 2. Final schema object definitions

```python
_SCHEMA_OBJECTS = (
    ("table", "meta", "meta", _CREATE_META),
    ("table", "blobs", "blobs", _CREATE_BLOBS),
    ("table", "keys", "keys", _CREATE_KEYS),
    ("table", "plots", "plots", _CREATE_PLOTS),
    ("table", "specs", "specs", _CREATE_SPECS),
    ("table", "attempts", "attempts", _CREATE_ATTEMPTS),
    ("table", "plot_references", "plot_references", _CREATE_PLOT_REFERENCES),
    ("table", "attempt_references", "attempt_references", _CREATE_ATTEMPT_REFERENCES),
    ("trigger", "blobs_track_logical_bytes", "blobs", _CREATE_BLOB_ACCOUNTING),
    ("trigger", "blobs_reject_update", "blobs", _CREATE_BLOB_UPDATE_GUARD),
    ("trigger", "blobs_reject_delete", "blobs", _CREATE_BLOB_DELETE_GUARD),
    ("index", "attempts_by_plot", "attempts", _CREATE_ATTEMPTS_BY_PLOT),
)
_SCHEMA_OBJECTS_V3 = (
    ("table", "meta", "meta", _CREATE_META),
    ("table", "blobs", "blobs", _CREATE_BLOBS_V3),
    ("table", "keys", "keys", _CREATE_KEYS),
    ("table", "plots", "plots", _CREATE_PLOTS_V3),
    ("table", "specs", "specs", _CREATE_SPECS),
    ("table", "attempts", "attempts", _CREATE_ATTEMPTS),
    ("table", "plot_references", "plot_references", _CREATE_PLOT_REFERENCES_V3),
    ("table", "attempt_references", "attempt_references", _CREATE_ATTEMPT_REFERENCES),
    ("trigger", "blobs_track_logical_bytes", "blobs", _CREATE_BLOB_ACCOUNTING),
    ("trigger", "blobs_reject_update", "blobs", _CREATE_BLOB_UPDATE_GUARD),
    ("trigger", "blobs_reject_delete", "blobs", _CREATE_BLOB_DELETE_GUARD),
    ("index", "attempts_by_plot", "attempts", _CREATE_ATTEMPTS_BY_PLOT),
)
_SCHEMA_OBJECTS_V2 = tuple(row for row in _SCHEMA_OBJECTS_V3 if row[1] != "attempts_by_plot")
_SCHEMA_OBJECTS_V1 = tuple(row for row in _SCHEMA_OBJECTS_V2 if row[1] != "specs")
```

### 3. Complete migration + dispatch

```python
def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    """Widen plot provenance roles and append a physically materialized source discriminator."""
    _validate_schema_version(
        connection,
        schema_version=_SCHEMA_VERSION_V3,
        schema_objects=_SCHEMA_OBJECTS_V3,
        verify_accounting=True,
    )
    connection.execute(
        "ALTER TABLE plots ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'dataset' "
        "CHECK (source_kind IN ('dataset', 'formula'))"
    )
    connection.execute("UPDATE plots SET source_kind = 'dataset'")

    connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, _CONFIG_OFF)
    try:
        connection.execute("PRAGMA writable_schema=ON")
        _require_connection_setting(
            "writable_schema", _read_scalar(connection, "PRAGMA writable_schema"), 1
        )
        for name, statement in (
            ("blobs", _CREATE_BLOBS),
            ("plot_references", _CREATE_PLOT_REFERENCES),
            ("plots", _CREATE_PLOTS),
        ):
            connection.execute(
                "UPDATE sqlite_schema SET sql = ? WHERE type = 'table' AND name = ?",
                (statement, name),
            )
        schema_cookie = connection.execute("PRAGMA schema_version").fetchone()[0]
        connection.execute(f"PRAGMA schema_version={schema_cookie + 1}")
        connection.execute("PRAGMA writable_schema=RESET")
    finally:
        try:
            connection.execute("PRAGMA writable_schema=OFF")
        finally:
            connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, _CONFIG_ON)
    connection.execute(
        "UPDATE meta SET schema_version = ? WHERE singleton = ?", (_SCHEMA_VERSION, 1)
    )
    connection.execute("PRAGMA user_version=4")
```

Exact post-edit `_create_or_validate_schema` dispatch/function:

```python
def _create_or_validate_schema(connection: sqlite3.Connection, *, max_spec_bytes: int) -> None:
    _require_read_limit(max_spec_bytes)
    with _immediate_transaction(connection):
        version = _read_scalar(connection, "PRAGMA user_version")
        if version == 0:
            if _schema_rows(connection):
                msg = "refusing an unversioned non-empty SQLite schema"
                raise ArchiveSchemaError(msg)
            for _object_type, _name, _table, statement in _SCHEMA_OBJECTS:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO meta(singleton, schema_version, logical_blob_bytes) VALUES (?, ?, ?)",
                (1, _SCHEMA_VERSION, 0),
            )
            connection.execute("PRAGMA user_version=4")
        elif version == 1:
            _migrate_v1_to_v2(connection, max_spec_bytes=max_spec_bytes)
            _migrate_v2_to_v3(connection)
            _migrate_v3_to_v4(connection)
        elif version == _SCHEMA_VERSION_V2:
            _migrate_v2_to_v3(connection)
            _migrate_v3_to_v4(connection)
        elif version == _SCHEMA_VERSION_V3:
            _migrate_v3_to_v4(connection)
        _validate_schema(connection, verify_accounting=True)
```

### 4. Every other production edit

Version constants — before:

```python
_SCHEMA_VERSION_V2 = 2
_SCHEMA_VERSION = 3
```

Version constants — after:

```python
_SCHEMA_VERSION_V2 = 2
_SCHEMA_VERSION_V3 = 3
_SCHEMA_VERSION = 4
```

`_migrate_v2_to_v3` — before (it used the moving current-version constant):

```python
def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    """Add the indexed lowest-attempt lookup derived from existing attempt rows."""
    _validate_schema_version(
        connection,
        schema_version=_SCHEMA_VERSION_V2,
        schema_objects=_SCHEMA_OBJECTS_V2,
        verify_accounting=True,
    )
    connection.execute(_CREATE_ATTEMPTS_BY_PLOT)
    connection.execute(
        "UPDATE meta SET schema_version = ? WHERE singleton = ?", (_SCHEMA_VERSION, 1)
    )
    connection.execute("PRAGMA user_version=3")
```

`_migrate_v2_to_v3` — after (it pins historic v3):

```python
def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    """Add the indexed lowest-attempt lookup derived from existing attempt rows."""
    _validate_schema_version(
        connection,
        schema_version=_SCHEMA_VERSION_V2,
        schema_objects=_SCHEMA_OBJECTS_V2,
        verify_accounting=True,
    )
    connection.execute(_CREATE_ATTEMPTS_BY_PLOT)
    connection.execute(
        "UPDATE meta SET schema_version = ? WHERE singleton = ?", (_SCHEMA_VERSION_V3, 1)
    )
    connection.execute("PRAGMA user_version=3")
```

`_put_plot` — before:

```python
def _put_plot(connection: sqlite3.Connection, record: PlotRecord) -> None:
    values = (
        record.plot_id,
        record.certificate.digest,
        record.certificate.kind.value,
        record.keyid,
    )
    _put_immutable_row(
        connection,
        _ImmutableWrite(
            select_sql=(
                "SELECT plot_id, certificate_digest, certificate_kind, keyid "
                "FROM plots WHERE plot_id = ?"
            ),
            insert_sql=(
                "INSERT INTO plots(plot_id, certificate_digest, certificate_kind, keyid) "
                "VALUES (?, ?, ?, ?)"
            ),
            identity=(record.plot_id,),
            values=values,
            subject="plot",
        ),
    )
```

`_put_plot` — after:

```python
def _put_plot(connection: sqlite3.Connection, record: PlotRecord) -> None:
    values = (
        record.plot_id,
        record.certificate.digest,
        record.certificate.kind.value,
        record.keyid,
        "dataset",
    )
    _put_immutable_row(
        connection,
        _ImmutableWrite(
            select_sql=(
                "SELECT plot_id, certificate_digest, certificate_kind, keyid, source_kind "
                "FROM plots WHERE plot_id = ?"
            ),
            insert_sql=(
                "INSERT INTO plots"
                "(plot_id, certificate_digest, certificate_kind, keyid, source_kind) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            identity=(record.plot_id,),
            values=values,
            subject="plot",
        ),
    )
```

Named source-model/read surfaces requested by MAIN were **byte-unchanged in this migration spike**; transcribe no change from this alternative:

- `BlobKind`: no `FORMULA_SOURCE` / `MATPLOTLIB_SCRIPT` enum members added; P6 tested SQL representability only.
- `PlotRecord`: no `source_kind` field added.
- `_validated_plot_record`: still returns `(BlobRef, keyid)` from the original 3-column read projection.
- `_PLOT_RECORD_COLUMNS = 3` remains unchanged.
- `_SELECT_PLOT_RECORD` remains unchanged:

```python
_SELECT_PLOT_RECORD = """SELECT certificate_digest, certificate_kind, keyid
FROM plots
WHERE plot_id = ?"""
```

- No `_INSERT_PLOT` module constant existed or was introduced; `_put_plot.insert_sql` is the only plot INSERT edit.
- No other `_SELECT_*`, `_INSERT_*`, or column-width constant changed.

These unchanged seams are deliberate spike scope, not the final M9.7 role model: MAIN must thread the adopted source-tagged bundle design separately rather than infer it from this migration patch.

### 5. Tests added or changed

- `test_create_reopen_uses_exact_strict_schema_and_connection_profile` — fresh exact schema/version is v4.
- `test_version_two_archive_migrates_partial_attempt_index_atomically` — fixture first becomes exact v3, then v2; chain ends exact v4.
- `test_version_three_archive_migrates_source_discriminator_and_role_checks` — **added**; direct v3 arm preserves stats, backfills `dataset`, emits exact v4.
- `test_unknown_schema_version_shape_meta_and_unversioned_database_fail_closed` — drift sentinel moved from now-valid 4 to unknown 5 for both `user_version` and meta.
- `test_version_one_archive_chains_spec_and_attempt_index_migrations_atomically` — fixture first becomes exact v3, then v1; chain ends exact v4.
- `test_version_one_migration_rejects_corrupt_spec_index_inputs` — corrupt-v1 matrix now starts from exact v3 DDL before v1 object drops.
- `test_cli_dispatch_validation_and_real_module_entry` — subprocess pins worktree `src`; shared venv `.pth` otherwise imports primary-tree v3 code.
- `test_public_artifact_schema_drift_is_logged_generic_500` — version-drift sentinel moved from 4 to 5.
- `_downgrade_to_v3` helper added in `tests/test_service_archive.py` and `tests/test_service_plot_bundle.py` — `ALTER ... DROP COLUMN source_kind`, exact historic DDL rewrite, schema-cookie bump, RESET; prevents fake “v1/v2” fixtures retaining v4 table text.

### 6. Hazards

- **Keep blob-kind order:** `tool_versions`, `formula_source`, `matplotlib_script`, `model_request` — exact-schema comparison is byte-sensitive.
- **Keep `source_kind` physically last after `keyid`:** `ALTER ADD COLUMN` appends record ordinal; moving it earlier remaps stored fields.
- **Keep temporary DEFAULT + physical UPDATE:** add `DEFAULT 'dataset'`, then `UPDATE plots SET source_kind='dataset'`, then rewrite away DEFAULT; skipping UPDATE makes old rows NULL after reload.
- **Keep one outer `BEGIN IMMEDIATE`:** every ALTER/data/schema/meta/version mutation must commit or roll back together; `_migrate_v3_to_v4` must not COMMIT.
- **Disable DEFENSIVE only around fixed schema writes:** this build ignores `writable_schema=ON` while defensive mode is ON; nested `finally` must restore DEFENSIVE even if OFF/RESET fails.
- **Keep schema-cookie bump before RESET:** direct `sqlite_schema` writes do not invalidate the live schema cache by themselves.
- **Keep `PRAGMA writable_schema=RESET` on success and `OFF` in `finally`:** RESET reloads/parses new DDL; OFF prevents the permissive mode surviving an exception path.
- **Keep final exact `_validate_schema` in the outer dispatcher:** malformed or drifted rewritten text must fail before COMMIT.
- **Keep historic v3 DDL byte-exact:** v1/v2 validation derives from `_SCHEMA_OBJECTS_V3`; deriving them from v4 objects without reversing all three table deltas rejects real old archives.
- **Do not treat SQL role representability as the source-model implementation:** `BlobKind`, `PlotRecord`, validation/read APIs remain dataset-only in this spike.
