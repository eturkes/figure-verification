# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""P2 localized totality mutants and formula-linked attempt ordering."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from formula_plot_bundle_helpers import FormulaBundleParts, formula_bundle_parts
from verifier.limits import DEFAULT_LIMITS
from verifier.service import archive as archive_module
from verifier.service.archive import (
    AttemptArtifacts,
    AttemptBundle,
    AttemptDraft,
    AttemptOutcome,
    AttemptRoute,
    BlobKind,
    BlobRef,
    DatasetPlotBundle,
    FormulaPlotBundle,
    PlotRole,
    PlotSourceKind,
    materialize_attempt_bundle,
    open_archive,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.settings import Settings


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


# Merged from the M9.8b plot-union suite (polish p9); its private helpers carry a `_u`/`_U` prefix.


_U_ROOT = Path(__file__).resolve().parents[1]


_U_DATA = _U_ROOT / "data"


_U_TIME = datetime(2026, 8, 14, 1, 2, 3, 456789, tzinfo=UTC)


_U_FORMULA_ROUTE = AttemptRoute.VERIFY_FORMULA


_U_DATASET_ROLE_FIELDS = (
    (PlotRole.RAW_CSV, "raw_csv"),
    (PlotRole.RAW_MANIFEST, "raw_manifest"),
    (PlotRole.CANONICAL_SPEC, "canonical_spec"),
    (PlotRole.PLOTTED_TABLE, "plotted_table"),
    (PlotRole.VERDICT, "verdict"),
    (PlotRole.VEGA_LITE, "vega_lite"),
    (PlotRole.SVG, "svg"),
    (PlotRole.VCERT_PAYLOAD, "vcert_payload"),
    (PlotRole.TOOL_VERSIONS, "tool_versions"),
)


_U_FORMULA_ROLE_FIELDS = (
    (PlotRole.CANONICAL_SPEC, "canonical_spec"),
    (PlotRole.FORMULA_SOURCE, "formula_source"),
    (PlotRole.PLOTTED_TABLE, "plotted_table"),
    (PlotRole.VERDICT, "verdict"),
    (PlotRole.MATPLOTLIB_SCRIPT, "matplotlib_script"),
    (PlotRole.VCERT_PAYLOAD, "vcert_payload"),
    (PlotRole.TOOL_VERSIONS, "tool_versions"),
)


@dataclass(frozen=True, slots=True)
class _UFormulaAttemptParts:
    settings: Settings
    signer: Signer
    plot: FormulaPlotBundle
    bundle: AttemptBundle


def _u_required(module: ModuleType, name: str) -> object:
    assert name in module.__dict__, f"{name} is absent"
    return module.__dict__[name]


def _u_formula_parts(signing: Signer) -> FormulaBundleParts:
    builder = cast("Callable[..., FormulaBundleParts]", formula_bundle_parts)
    return builder(signing=signing)


def _u_formula_draft(
    plot: FormulaPlotBundle,
    *,
    route: AttemptRoute = _U_FORMULA_ROUTE,
    artifacts: AttemptArtifacts | None = None,
) -> AttemptDraft:
    if artifacts is None:
        artifacts = AttemptArtifacts(raw_spec=plot.canonical_spec, verdict=plot.verdict)
    return AttemptDraft(
        occurred_at=_U_TIME,
        route=route,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=artifacts,
        plot=cast("Any", plot),
    )


def _u_formula_attempt(
    tmp_path: Path,
    *,
    nonce: str = "a" * 32,
    publish: bool = False,
    settings: Settings | None = None,
) -> _UFormulaAttemptParts:
    if settings is None:
        settings = Settings(data_dir=_U_DATA, state_dir=tmp_path / "formula-state")
    signing = load_identity(settings).signer
    parts = _u_formula_parts(signing)
    plot = cast("FormulaPlotBundle", parts.bundle)
    bundle = materialize_attempt_bundle(
        _u_formula_draft(plot),
        signing,
        nonce=nonce,
        limits=settings.limits,
    )
    if publish:
        open_archive(settings).publish_attempt(bundle, limits=settings.limits)
    return _UFormulaAttemptParts(settings, signing, plot, bundle)


def _u_blob_entry(
    kind: BlobKind,
    payload: bytes,
    blob_id: int,
) -> tuple[BlobRef, Any]:
    reference = BlobRef("sha256:" + hashlib.sha256(payload).hexdigest(), kind)
    return reference, (blob_id, reference.digest, kind.value, len(payload))


def test_u41_plot_entries_carry_source_kind_and_accept_keywords() -> None:
    entries_type = cast("type[Any]", _u_required(archive_module, "_PlotEntries"))
    assert tuple(field.name for field in fields(entries_type)) == (
        "plot_id",
        "keyid",
        "source_kind",
        "certificate",
        "key",
        "roles",
    )
    certificate = _u_blob_entry(BlobKind.VCERT_ENVELOPE, b"certificate", 1)
    key = _u_blob_entry(BlobKind.ED25519_PUBLIC_KEY, b"k" * 32, 2)
    entries = entries_type(
        plot_id="0" * 64,
        keyid="sha256:" + "1" * 64,
        source_kind=PlotSourceKind.FORMULA,
        certificate=certificate,
        key=key,
        roles={},
    )
    assert entries.source_kind is PlotSourceKind.FORMULA


def test_u43_plot_bundle_type_map_is_total_and_exact() -> None:
    bundle_types = cast(
        "dict[PlotSourceKind, type[DatasetPlotBundle] | type[FormulaPlotBundle]]",
        _u_required(archive_module, "_PLOT_BUNDLE_TYPE_BY_SOURCE"),
    )
    assert set(bundle_types) == set(PlotSourceKind)
    assert bundle_types == {
        PlotSourceKind.DATASET: DatasetPlotBundle,
        PlotSourceKind.FORMULA: FormulaPlotBundle,
    }


def test_u44_plot_bundle_from_payloads_uses_formula_constructor_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_U_DATA, state_dir=tmp_path / "constructor-entry")
    plot = cast("FormulaPlotBundle", _u_formula_parts(load_identity(settings).signer).bundle)
    role_payloads = {
        role: cast("bytes", getattr(plot, field_name))
        for role, field_name in _U_FORMULA_ROLE_FIELDS
    }
    bundle_types = cast(
        "dict[PlotSourceKind, Callable[..., object]]",
        _u_required(archive_module, "_PLOT_BUNDLE_TYPE_BY_SOURCE"),
    )
    calls: list[dict[str, object]] = []

    def formula_spy(**kwargs: object) -> object:
        calls.append(kwargs)
        return plot

    monkeypatch.setitem(bundle_types, PlotSourceKind.FORMULA, formula_spy)
    constructor = cast(
        "Callable[..., object]",
        _u_required(archive_module, "_plot_bundle_from_payloads"),
    )
    result = constructor(
        PlotSourceKind.FORMULA,
        plot_id=plot.plot_id,
        keyid=plot.keyid,
        role_payloads=role_payloads,
        certificate_payload=plot.vcert_envelope,
        public_key=plot.public_key,
    )

    assert result is plot
    assert calls == [
        {
            "plot_id": plot.plot_id,
            "keyid": plot.keyid,
            **{field_name: role_payloads[role] for role, field_name in _U_FORMULA_ROLE_FIELDS},
            "vcert_envelope": plot.vcert_envelope,
            "public_key": plot.public_key,
        }
    ]


def test_u45_attempt_reader_aggregate_uses_formula_role_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = _u_formula_attempt(tmp_path, publish=True)
    role_fields = cast(
        "dict[PlotSourceKind, tuple[tuple[PlotRole, str], ...]]",
        _u_required(archive_module, "_PLOT_ROLE_FIELDS_BY_SOURCE"),
    )
    calls = {"reconstruct": 0}

    def reconstruction_bomb(*_args: object, **_kwargs: object) -> object:
        calls["reconstruct"] += 1
        pytest.fail("reconstruction ran after aggregate-role selection failed")

    monkeypatch.setitem(role_fields, PlotSourceKind.FORMULA, _U_DATASET_ROLE_FIELDS)
    monkeypatch.setattr(archive_module, "_plot_from_entries", reconstruction_bomb)
    with pytest.raises(KeyError) as error:
        open_archive(parts.settings).read_attempt(
            parts.bundle.attempt_id,
            max_bytes=parts.settings.max_archive_bytes,
            limits=parts.settings.limits,
        )
    assert error.value.args == (PlotRole.RAW_CSV,)
    assert calls == {"reconstruct": 0}


def test_u46_plot_from_entries_uses_formula_roles_and_constructor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_U_DATA, state_dir=tmp_path / "formula-reconstruct")
    plot = cast("FormulaPlotBundle", _u_formula_parts(load_identity(settings).signer).bundle)
    entries_type = cast("type[Any]", _u_required(archive_module, "_PlotEntries"))
    certificate = _u_blob_entry(BlobKind.VCERT_ENVELOPE, plot.vcert_envelope, 1)
    key = _u_blob_entry(BlobKind.ED25519_PUBLIC_KEY, plot.public_key, 2)
    roles = {
        role: _u_blob_entry(BlobKind(role.value), cast("bytes", getattr(plot, field_name)), index)
        for index, (role, field_name) in enumerate(_U_FORMULA_ROLE_FIELDS, start=3)
    }
    entries = entries_type(
        plot_id=plot.plot_id,
        keyid=plot.keyid,
        source_kind=PlotSourceKind.FORMULA,
        certificate=certificate,
        key=key,
        roles=roles,
    )
    payloads = {
        certificate[0]: plot.vcert_envelope,
        key[0]: plot.public_key,
        **{
            entry[0]: cast("bytes", getattr(plot, field_name))
            for (role, field_name), entry in zip(
                _U_FORMULA_ROLE_FIELDS, roles.values(), strict=True
            )
        },
    }
    calls: list[tuple[PlotSourceKind, dict[PlotRole, bytes]]] = []

    def constructor_spy(
        source_kind: PlotSourceKind,
        *,
        role_payloads: dict[PlotRole, bytes],
        **_kwargs: object,
    ) -> FormulaPlotBundle:
        calls.append((source_kind, role_payloads))
        return plot

    monkeypatch.setattr(archive_module, "_plot_bundle_from_payloads", constructor_spy)
    result = archive_module._plot_from_entries(entries, payloads)
    assert result is plot
    assert calls == [
        (
            PlotSourceKind.FORMULA,
            {
                role: cast("bytes", getattr(plot, field_name))
                for role, field_name in _U_FORMULA_ROLE_FIELDS
            },
        )
    ]
