# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""P2 localized totality mutants and formula-linked attempt ordering."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from verifier.limits import DEFAULT_LIMITS
from verifier.service import archive as archive_module
from verifier.service.archive import PlotSourceKind


def _set(module: ModuleType, name: str, value: object) -> None:
    setattr(module, name, value)


def _load_mutant(tmp_path: Path, label: str, pattern: str, replacement: str) -> ModuleType:
    source_path = Path(archive_module.__file__)
    source = source_path.read_text()
    mutated, count = re.subn(pattern, replacement, source, count=1, flags=re.DOTALL)
    assert count == 1
    path = tmp_path / f"archive_{label}.py"
    path.write_text(mutated)
    # Deliberately outside the ``verifier`` package: coverage measures that package by name, so a
    # mutant registered inside it would enter the 100% gate as thousands of unexecuted statements.
    name = f"archive_mutant_m9u7b2_{label}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, one: object = None):
        self.one = one

    def fetchone(self) -> object:
        return self.one


def _plot_entries(module: ModuleType, mode: Any) -> tuple[Any, Any, dict[Any, Any]]:
    plot_id = "a" * 64
    keyid = "sha256:" + "b" * 64
    certificate = module.BlobRef(f"sha256:{plot_id}", module.BlobKind.VCERT_ENVELOPE)
    key = module.BlobRef(keyid, module.BlobKind.ED25519_PUBLIC_KEY)
    certificate_entry = (
        certificate,
        (1, certificate.digest, certificate.kind.value, 1),
    )
    key_entry = (key, (2, key.digest, key.kind.value, 32))
    role_rows = {}
    for index, (role, _field) in enumerate(module._PLOT_ROLE_FIELDS_BY_SOURCE[mode], start=3):
        reference = module.BlobRef(
            "sha256:" + f"{index:x}".rjust(64, "c"),
            module.BlobKind(role.value),
        )
        role_rows[role] = (
            reference,
            (index, reference.digest, reference.kind.value, len(role.value)),
        )
    return certificate_entry, key_entry, role_rows


def _record_connection(module: ModuleType, mode: Any) -> Any:
    plot_id = "a" * 64
    keyid = "sha256:" + "b" * 64

    class Connection:
        def execute(self, statement: str, _parameters: object) -> _Result:
            if statement == module._SELECT_PLOT_RECORD:
                return _Result((f"sha256:{plot_id}", "vcert_envelope", keyid, mode.value))
            raise AssertionError(statement)

    return Connection()


def test_mode_dispatch_maps_stay_exactly_total_over_the_closed_source_kind_enum() -> None:
    """Both maps are documented total; pin the hand-stated key set so widening either fails."""
    expected = {PlotSourceKind.DATASET, PlotSourceKind.FORMULA}
    assert set(PlotSourceKind) == expected
    assert set(archive_module._CANONICAL_SPEC_DECODERS) == expected
    assert set(archive_module._ARCHIVE_CERTIFICATE_AUTHENTICATORS) == expected
    assert len({id(arm) for arm in archive_module._CANONICAL_SPEC_DECODERS.values()}) == 2
    assert (
        len({id(arm) for arm in archive_module._ARCHIVE_CERTIFICATE_AUTHENTICATORS.values()}) == 2
    )


def test_p2_site1_totality_uses_formula_roles_not_whole_enum(tmp_path: Path) -> None:
    assert hasattr(archive_module, "_PLOT_ROLES_BY_SOURCE")
    module = _load_mutant(
        tmp_path,
        "site1",
        r"set\(role_rows\) != _PLOT_ROLES_BY_SOURCE\[source_kind\]",
        "set(role_rows) != set(PlotRole)",
    )
    certificate_entry, key_entry, role_rows = _plot_entries(module, module.PlotSourceKind.FORMULA)

    class Result:
        def __init__(self, *, one: object = None, many: list[tuple[object, ...]] | None = None):
            self.one = one
            self.many = [] if many is None else many

        def fetchone(self) -> object:
            return self.one

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.many

    class Connection:
        def execute(self, statement: str, _parameters: object) -> Result:
            if statement == module._SELECT_EXACT_BLOB:
                return Result(one=certificate_entry[1])
            if statement == module._SELECT_KEY_BLOB:
                return Result(one=key_entry[1])
            if statement == module._SELECT_PLOT_REFERENCES:
                return Result(many=[(role.value, *entry[1]) for role, entry in role_rows.items()])
            raise AssertionError(statement)

    with pytest.raises(module.ArchiveIntegrityError, match="every required role"):
        module._plot_bundle_blob_rows(
            Connection(),
            "a" * 64,
            certificate_entry[0],
            key_entry[0].digest,
            source_kind=module.PlotSourceKind.FORMULA,
        )


def test_p2_site2_aggregate_entries_use_dataset_roles_not_whole_enum(tmp_path: Path) -> None:
    assert hasattr(archive_module, "_DATASET_PLOT_ROLE_FIELDS")
    module = _load_mutant(
        tmp_path,
        "site2",
        r"\*\(role_rows\[role\] for role, _[A-Za-z_]+ in role_fields\)",
        "*(role_rows[role] for role in PlotRole)",
    )
    entries = _plot_entries(module, module.PlotSourceKind.DATASET)
    _set(module, "_plot_bundle_blob_rows", lambda *_args, **_kwargs: entries)
    _set(module, "_consume_blob", lambda *_args, **_kwargs: pytest.fail("blob read ran"))
    with pytest.raises(KeyError):
        module._read_complete_plot_bundle(
            _record_connection(module, module.PlotSourceKind.DATASET),
            "a" * 64,
            max_bytes=1_000_000,
        )


def test_p2_site3_payload_reads_use_dataset_roles_not_whole_enum(tmp_path: Path) -> None:
    assert hasattr(archive_module, "_FORMULA_PLOT_ROLE_FIELDS")
    module = _load_mutant(
        tmp_path,
        "site3",
        r"\{\s*role: read_entry\(role_rows\[role\]\)\s*"
        r"for role, _[A-Za-z_]+ in role_fields\s*\}",
        "{role: read_entry(role_rows[role]) for role in PlotRole}",
    )
    entries = _plot_entries(module, module.PlotSourceKind.DATASET)
    _set(module, "_plot_bundle_blob_rows", lambda *_args, **_kwargs: entries)
    _set(module, "_consume_blob", lambda *_args, **_kwargs: b"x")
    with pytest.raises(KeyError):
        module._read_complete_plot_bundle(
            _record_connection(module, module.PlotSourceKind.DATASET),
            "a" * 64,
            max_bytes=1_000_000,
        )


def test_p2_site4_attempt_reconstruction_uses_source_roles(tmp_path: Path) -> None:
    assert hasattr(archive_module, "_PLOT_ROLE_FIELDS_BY_SOURCE")
    module = _load_mutant(
        tmp_path,
        "site4",
        r"\{\s*role: payloads\[entries\.roles\[role\]\[0\]\]\s*"
        r"for role, _[A-Za-z_]+ in _PLOT_ROLE_FIELDS_BY_SOURCE\[entries\.source_kind\]\s*\}",
        "{role: payloads[entries.roles[role][0]] for role in PlotRole}",
    )
    certificate, key, role_rows = _plot_entries(module, module.PlotSourceKind.DATASET)
    entries = module._PlotEntries(
        "a" * 64,
        key[0].digest,
        module.PlotSourceKind.DATASET,
        certificate,
        key,
        role_rows,
    )
    payloads = {reference: b"x" for reference, _row in (certificate, key, *role_rows.values())}
    with pytest.raises(KeyError):
        module._plot_from_entries(entries, payloads)


def test_p2_site5_attempt_aggregate_entries_use_source_roles(tmp_path: Path) -> None:
    assert hasattr(archive_module, "_PLOT_ROLE_FIELDS_BY_SOURCE")
    module = _load_mutant(
        tmp_path,
        "site5",
        r"\*\(\s*plot_role_rows\[role\]\s*for role, _[A-Za-z_]+\s*"
        r"in _PLOT_ROLE_FIELDS_BY_SOURCE\[plot_source_kind\]\s*\)",
        "*(plot_role_rows[role] for role in PlotRole)",
    )
    plot_entries = _plot_entries(module, module.PlotSourceKind.DATASET)
    attempt_ref = module.BlobRef("sha256:" + "d" * 64, module.BlobKind.ATTEMPT_ENVELOPE)
    key_ref = module.BlobRef("sha256:" + "e" * 64, module.BlobKind.ED25519_PUBLIC_KEY)
    _set(
        module,
        "_validated_attempt_record",
        lambda *_args: (attempt_ref, key_ref.digest, "a" * 64),
    )
    _set(
        module,
        "_attempt_bundle_blob_rows",
        lambda *_args: (
            (attempt_ref, (20, attempt_ref.digest, attempt_ref.kind.value, 1)),
            (key_ref, (21, key_ref.digest, key_ref.kind.value, 32)),
            {},
        ),
    )
    _set(
        module,
        "_validated_plot_record",
        lambda *_args: (
            plot_entries[0][0],
            plot_entries[1][0].digest,
            module.PlotSourceKind.DATASET,
        ),
    )
    _set(module, "_plot_bundle_blob_rows", lambda *_args, **_kwargs: plot_entries)
    _set(
        module,
        "_read_unique_entries",
        lambda *_args, **_kwargs: pytest.fail("payload reads ran"),
    )

    class Connection:
        def execute(self, _statement: str, _parameters: object) -> _Result:
            return _Result((1,))

    with pytest.raises(KeyError):
        module._read_complete_attempt_bundle(
            Connection(),
            "f" * 64,
            max_bytes=1_000_000,
            limits=DEFAULT_LIMITS,
        )


class _ReachedPlotRowsError(Exception):
    """Raised by the plot-row spy to end the read at the seam under test."""


def test_rd7_formula_linked_attempt_reads_through_its_own_source_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attempt reader carries the plot record's stored mode into the row read."""
    captured: dict[str, Any] = {}
    attempt_ref = archive_module.BlobRef(
        "sha256:" + "d" * 64, archive_module.BlobKind.ATTEMPT_ENVELOPE
    )
    key_ref = archive_module.BlobRef(
        "sha256:" + "e" * 64, archive_module.BlobKind.ED25519_PUBLIC_KEY
    )
    certificate = archive_module.BlobRef(
        "sha256:" + "a" * 64, archive_module.BlobKind.VCERT_ENVELOPE
    )
    monkeypatch.setattr(
        archive_module,
        "_validated_attempt_record",
        lambda *_args: (attempt_ref, key_ref.digest, "a" * 64),
    )
    monkeypatch.setattr(
        archive_module,
        "_attempt_bundle_blob_rows",
        lambda *_args: (
            (attempt_ref, (20, attempt_ref.digest, attempt_ref.kind.value, 1)),
            (key_ref, (21, key_ref.digest, key_ref.kind.value, 32)),
            {},
        ),
    )
    monkeypatch.setattr(
        archive_module,
        "_validated_plot_record",
        lambda *_args: (certificate, key_ref.digest, PlotSourceKind.FORMULA),
    )

    def rows_spy(
        _connection: object,
        _plot_id: str,
        _certificate: object,
        _keyid: str,
        source_kind: Any,
    ) -> object:
        captured["source_kind"] = source_kind
        raise _ReachedPlotRowsError

    monkeypatch.setattr(archive_module, "_plot_bundle_blob_rows", rows_spy)

    class Connection:
        def execute(self, _statement: str, _parameters: object) -> _Result:
            return _Result((1,))

    with pytest.raises(_ReachedPlotRowsError):
        archive_module._read_complete_attempt_bundle(
            cast("Any", Connection()),
            "f" * 64,
            max_bytes=1_000_000,
            limits=DEFAULT_LIMITS,
        )
    assert captured == {"source_kind": PlotSourceKind.FORMULA}
