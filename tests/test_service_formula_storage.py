# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9.7b-2 formula archive projection, round-trip, and source dispatch."""

from __future__ import annotations

import ast
import inspect
import re
import sqlite3
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, cast

import msgspec
import pytest

from formula_plot_bundle_helpers import dataset_bundle, formula_bundle_parts
from schema_downgrade import downgrade_to_v3
from verifier import attestation, canon, replay, schema
from verifier.limits import DEFAULT_LIMITS
from verifier.service import archive as archive_module
from verifier.service.archive import (
    ArchiveIntegrityError,
    ArchiveNotFoundError,
    ArchiveQuotaError,
    ArchiveReadLimitError,
    ArchiveStats,
    BlobKind,
    BlobWrite,
    DatasetPlotBundle,
    FormulaPlotBundle,
    PlotRole,
    PlotSourceKind,
    open_archive,
)
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATASET_ROLE_FIELDS = (
    ("raw_csv", "raw_csv"),
    ("raw_manifest", "raw_manifest"),
    ("canonical_spec", "canonical_spec"),
    ("plotted_table", "plotted_table"),
    ("verdict", "verdict"),
    ("vega_lite", "vega_lite"),
    ("svg", "svg"),
    ("vcert_payload", "vcert_payload"),
    ("tool_versions", "tool_versions"),
)
_FORMULA_ROLE_FIELDS = (
    ("canonical_spec", "canonical_spec"),
    ("formula_source", "formula_source"),
    ("plotted_table", "plotted_table"),
    ("verdict", "verdict"),
    ("matplotlib_script", "matplotlib_script"),
    ("vcert_payload", "vcert_payload"),
    ("tool_versions", "tool_versions"),
)
_DATASET_ROLES = {role for role, _field in _DATASET_ROLE_FIELDS}
_FORMULA_ROLES = {role for role, _field in _FORMULA_ROLE_FIELDS}
_ALL_ROLES = _DATASET_ROLES | _FORMULA_ROLES
_DATASET_ONLY_ROLES = _DATASET_ROLES - _FORMULA_ROLES
_FORMULA_ONLY_ROLES = _FORMULA_ROLES - _DATASET_ROLES
_SHARED_ROLES = _DATASET_ROLES & _FORMULA_ROLES


def _bundle_bytes(bundle: DatasetPlotBundle | FormulaPlotBundle) -> int:
    return sum(
        len(getattr(bundle, field.name))
        for field in fields(bundle)
        if field.name not in {"plot_id", "keyid"}
    )


def _database_connection(archive: archive_module.Archive) -> sqlite3.Connection:
    return sqlite3.connect(archive.database_path, autocommit=True)


def _formula_archive(tmp_path: Path) -> tuple[archive_module.Archive, Any]:
    parts = formula_bundle_parts()
    settings = Settings(data_dir=_ROOT / "data", state_dir=tmp_path / "formula-state")
    archive = open_archive(settings)
    return archive, parts


def _role_values(entries: object) -> tuple[tuple[str, str], ...]:
    return tuple(
        (cast("PlotRole", role).value, cast("str", field)) for role, field in cast("Any", entries)
    )


def _private(name: str) -> Any:
    return getattr(archive_module, name)


def _formula_source_role() -> PlotRole:
    return PlotRole("formula_source")


def _quoted_roles(fragment: str) -> set[str]:
    return set(re.findall(r"'([a-z_]+)'", fragment))


def _ddl_role_domains() -> tuple[set[str], set[str], set[str]]:
    check_text = archive_module._CREATE_PLOT_REFERENCES
    check_body = check_text.split("CHECK (role IN (", 1)[1].split("))", 1)[0]
    trigger = archive_module._CREATE_PLOT_SOURCE_GUARD
    dataset_body = trigger.split("source_kind = 'dataset'", 1)[1].split(
        ")) OR (source_kind = 'formula'", 1
    )[0]
    formula_body = trigger.split("source_kind = 'formula'", 1)[1].split(")))", 1)[0]
    return _quoted_roles(check_body), _quoted_roles(dataset_body), _quoted_roles(formula_body)


def test_p1_role_enum_maps_ddl_and_trigger_match_independent_hand_sets() -> None:
    assert tuple(role.value for role in PlotRole) == (
        "raw_csv",
        "raw_manifest",
        "canonical_spec",
        "plotted_table",
        "verdict",
        "vega_lite",
        "svg",
        "vcert_payload",
        "tool_versions",
        "formula_source",
        "matplotlib_script",
    )
    assert tuple(role.value for role in PlotRole) == tuple(
        BlobKind[role.name].value for role in PlotRole
    )
    assert _role_values(_private("_DATASET_PLOT_ROLE_FIELDS")) == _DATASET_ROLE_FIELDS
    assert _role_values(_private("_FORMULA_PLOT_ROLE_FIELDS")) == _FORMULA_ROLE_FIELDS
    assert set(_private("_PLOT_ROLE_FIELDS_BY_SOURCE")) == set(PlotSourceKind)
    assert (
        _role_values(_private("_PLOT_ROLE_FIELDS_BY_SOURCE")[PlotSourceKind.DATASET])
        == _DATASET_ROLE_FIELDS
    )
    assert (
        _role_values(_private("_PLOT_ROLE_FIELDS_BY_SOURCE")[PlotSourceKind.FORMULA])
        == _FORMULA_ROLE_FIELDS
    )
    check_roles, dataset_trigger_roles, formula_trigger_roles = _ddl_role_domains()
    assert check_roles == _ALL_ROLES
    assert dataset_trigger_roles == _DATASET_ROLES
    assert formula_trigger_roles == _FORMULA_ROLES
    assert "vcert_envelope" not in check_roles
    assert "ed25519_public_key" not in check_roles


def test_p7_dataset_and_formula_role_order_are_exact_and_separate() -> None:
    assert _role_values(_private("_DATASET_PLOT_ROLE_FIELDS")) == _DATASET_ROLE_FIELDS
    assert _role_values(_private("_FORMULA_PLOT_ROLE_FIELDS")) == _FORMULA_ROLE_FIELDS
    assert {"raw_csv", "raw_manifest", "vega_lite", "svg"} == _DATASET_ONLY_ROLES
    assert {"formula_source", "matplotlib_script"} == _FORMULA_ONLY_ROLES
    assert {
        "canonical_spec",
        "plotted_table",
        "verdict",
        "vcert_payload",
        "tool_versions",
    } == _SHARED_ROLES


def test_rd9_closed_role_map_refuses_forged_nonmember_natively() -> None:
    with pytest.raises(KeyError):
        _private("_PLOT_ROLE_FIELDS_BY_SOURCE")[cast("PlotSourceKind", "spreadsheet")]
    with pytest.raises(KeyError):
        _private("_PLOT_ROLES_BY_SOURCE")[cast("PlotSourceKind", object())]


def test_s3_replay_role_mirror_is_hand_stated_and_import_pure() -> None:
    assert tuple(cast("tuple[str, ...]", replay.PLOT_ROLE_VALUES)) == (
        "raw_csv",
        "raw_manifest",
        "canonical_spec",
        "plotted_table",
        "verdict",
        "vega_lite",
        "svg",
        "vcert_payload",
        "tool_versions",
        "formula_source",
        "matplotlib_script",
    )
    # Purity is about imports, not prose: replay's own docstring names the module it refuses to
    # import, so the check reads the import graph rather than the source text.
    imported = {
        name.name
        for node in ast.walk(ast.parse(inspect.getsource(replay)))
        for name in (node.names if isinstance(node, ast.Import) else [])
    } | {
        node.module or ""
        for node in ast.walk(ast.parse(inspect.getsource(replay)))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name.startswith("verifier.service") for name in imported)


def test_s5_formula_projection_uses_real_chain_and_exact_graph() -> None:
    parts = formula_bundle_parts()
    batch = archive_module._plot_bundle_batch(parts.bundle)
    assert len(batch.blobs) == 9
    assert len(batch.keys) == 1
    assert len(batch.plots) == 1
    assert len(batch.specs) == 1
    assert len(batch.plot_references) == 7
    assert batch.plots[0].source_kind is PlotSourceKind.FORMULA
    assert batch.plots[0].certificate.digest == f"sha256:{parts.bundle.plot_id}"
    assert batch.keys[0].keyid == parts.bundle.keyid
    assert tuple(reference.role.value for reference in batch.plot_references) == tuple(
        role for role, _field in _FORMULA_ROLE_FIELDS
    )
    assert {blob.kind.value for blob in batch.blobs} == _FORMULA_ROLES | {
        "vcert_envelope",
        "ed25519_public_key",
    }


def test_s5_formula_projection_routes_formula_spec_decoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = formula_bundle_parts()
    original = archive_module._decode_canonical_formula_spec
    calls = {"dataset": 0, "formula": 0}

    def dataset_bomb(_payload: bytes) -> object:
        calls["dataset"] += 1
        pytest.fail("dataset spec decoder reached formula projection")

    def formula_spy(payload: bytes) -> object:
        calls["formula"] += 1
        return original(payload)

    # Projection consults the per-mode decoder map, so the map entries are the spy seam.
    monkeypatch.setitem(
        archive_module._CANONICAL_SPEC_DECODERS, PlotSourceKind.DATASET, dataset_bomb
    )
    monkeypatch.setitem(
        archive_module._CANONICAL_SPEC_DECODERS, PlotSourceKind.FORMULA, formula_spy
    )
    archive_module._plot_bundle_batch(parts.bundle)
    assert calls == {"dataset": 0, "formula": 1}


def test_p6_storage_choke_message_is_absent_from_source() -> None:
    source_root = _ROOT / "src"
    needle = "formula plot bundle persistence arrives in M9.7b-2"
    sources = tuple(source_root.rglob("*.py"))
    assert sources
    assert not any(needle in path.read_text() for path in sources)
    assert any("class FormulaPlotBundle" in path.read_text() for path in sources)


def test_rd8_produced_formula_bundle_publishes_and_reads(tmp_path: Path) -> None:
    parts = formula_bundle_parts()
    producer = archive_module.__dict__.get("materialize_formula_plot_bundle")
    assert callable(producer)
    produced = producer(
        parts.artifact,
        parts.certificate,
        parts.bundle.vcert_envelope,
        parts.signer,
    )
    settings = Settings(data_dir=_ROOT / "data", state_dir=tmp_path / "produced-state")
    archive = open_archive(settings)

    archive.publish_plot(produced)
    assert archive.read_plot(produced.plot_id, max_bytes=_bundle_bytes(produced)) == produced


def test_d1_formula_publish_read_reopen_and_all_nine_carriers(tmp_path: Path) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    assert (
        archive.read_plot(parts.bundle.plot_id, max_bytes=_bundle_bytes(parts.bundle))
        == parts.bundle
    )
    assert (
        archive.read_plot_envelope(parts.bundle.plot_id, max_bytes=len(parts.bundle.vcert_envelope))
        == parts.bundle.vcert_envelope
    )
    assert archive.read_key(parts.bundle.keyid, max_bytes=len(parts.bundle.public_key)) == (
        parts.bundle.public_key
    )
    for role, field_name in _private("_FORMULA_PLOT_ROLE_FIELDS"):
        payload = getattr(parts.bundle, field_name)
        assert archive.read_plot_blob(parts.bundle.plot_id, role, max_bytes=len(payload)) == payload
    reopened = open_archive(Settings(data_dir=_ROOT / "data", state_dir=tmp_path / "formula-state"))
    assert (
        reopened.read_plot(parts.bundle.plot_id, max_bytes=_bundle_bytes(parts.bundle))
        == parts.bundle
    )


def test_d2_formula_stored_graph_has_exact_roles_and_alternate_edges(tmp_path: Path) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    with _database_connection(archive) as connection:
        plot = connection.execute(
            "SELECT certificate_digest, certificate_kind, keyid, source_kind FROM plots "
            "WHERE plot_id = ?",
            (parts.bundle.plot_id,),
        ).fetchone()
        roles = connection.execute(
            "SELECT role, blob_kind FROM plot_references WHERE plot_id = ? ORDER BY role",
            (parts.bundle.plot_id,),
        ).fetchall()
        key = connection.execute(
            "SELECT public_key_digest, public_key_kind FROM keys WHERE keyid = ?",
            (parts.bundle.keyid,),
        ).fetchone()
    assert plot == (
        f"sha256:{parts.bundle.plot_id}",
        "vcert_envelope",
        parts.bundle.keyid,
        "formula",
    )
    assert set(roles) == {(role, role) for role in _FORMULA_ROLES}
    assert not ({role for role, _kind in roles} & _DATASET_ONLY_ROLES)
    assert key == (parts.bundle.keyid, "ed25519_public_key")


def test_d1_both_modes_return_their_exact_concrete_bundle(tmp_path: Path) -> None:
    dataset_settings, dataset = dataset_bundle(tmp_path / "dataset")
    archive = open_archive(dataset_settings)
    formula = formula_bundle_parts().bundle
    archive.publish_plot(dataset)
    archive.publish_plot(formula)
    dataset_read: object = archive.read_plot(dataset.plot_id, max_bytes=_bundle_bytes(dataset))
    formula_read: object = archive.read_plot(formula.plot_id, max_bytes=_bundle_bytes(formula))
    assert type(dataset_read).__name__ == "DatasetPlotBundle"
    assert type(formula_read).__name__ == "FormulaPlotBundle"
    assert dataset_read == dataset
    assert formula_read == formula


def test_d6_identical_formula_publish_is_idempotent(tmp_path: Path) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    before = archive.stats()
    archive.publish_plot(parts.bundle)
    assert archive.stats() == before


def test_d6_rotated_formula_signature_deduplicates_seven_role_blobs(tmp_path: Path) -> None:
    archive, first_parts = _formula_archive(tmp_path)
    second_parts = formula_bundle_parts()
    first = first_parts.bundle
    second = replace(
        first,
        plot_id=second_parts.bundle.plot_id,
        keyid=second_parts.bundle.keyid,
        vcert_envelope=second_parts.bundle.vcert_envelope,
        public_key=second_parts.bundle.public_key,
    )
    archive.publish_plot(first)
    archive.publish_plot(second)
    shared_bytes = sum(len(getattr(first, field)) for _role, field in _FORMULA_ROLE_FIELDS)
    expected_bytes = (
        shared_bytes
        + len(first.vcert_envelope)
        + len(first.public_key)
        + len(second.vcert_envelope)
        + len(second.public_key)
    )
    assert archive.stats() == ArchiveStats(expected_bytes, 11, 2, 2, 0)
    assert archive.read_plot(first.plot_id, max_bytes=_bundle_bytes(first)) == first
    assert archive.read_plot(second.plot_id, max_bytes=_bundle_bytes(second)) == second


def test_d1_formula_aggregate_cap_precedes_blob_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)

    class TrackingConnection(sqlite3.Connection):
        blob_opens = 0

        def blobopen(self, *args: Any, **kwargs: Any) -> sqlite3.Blob:
            type(self).blob_opens += 1
            return super().blobopen(*args, **kwargs)

    monkeypatch.setattr(archive_module, "_CONNECTION_FACTORY", TrackingConnection)
    with pytest.raises(ArchiveReadLimitError, match="aggregate read limit"):
        archive.read_plot(parts.bundle.plot_id, max_bytes=_bundle_bytes(parts.bundle) - 1)
    assert TrackingConnection.blob_opens == 0
    assert archive.read_plot(parts.bundle.plot_id, max_bytes=_bundle_bytes(parts.bundle)) == (
        parts.bundle
    )
    assert TrackingConnection.blob_opens == 9


def test_d3_certificate_dispatch_uses_fixed_wrapper_per_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_settings, dataset = dataset_bundle(tmp_path / "dataset")
    archive = open_archive(dataset_settings)
    formula = formula_bundle_parts().bundle
    archive.publish_plot(dataset)
    archive.publish_plot(formula)
    original_dataset = attestation.verify_vcert
    original_formula = attestation.verify_vcert_v03
    seen: list[tuple[str, bytes, str, bool, str | None]] = []

    def dataset_spy(
        envelope: bytes,
        trusted_keys: dict[str, Any],
        *,
        limits: Any,
        require_canonical_envelope: bool,
        expected_keyid_hint: str | None,
    ) -> Any:
        seen.append(
            (
                "dataset",
                envelope,
                next(iter(trusted_keys)),
                require_canonical_envelope,
                expected_keyid_hint,
            )
        )
        return original_dataset(
            envelope,
            trusted_keys,
            limits=limits,
            require_canonical_envelope=require_canonical_envelope,
            expected_keyid_hint=expected_keyid_hint,
        )

    def formula_spy(
        envelope: bytes,
        trusted_keys: dict[str, Any],
        *,
        limits: Any,
        require_canonical_envelope: bool,
        expected_keyid_hint: str | None,
    ) -> Any:
        seen.append(
            (
                "formula",
                envelope,
                next(iter(trusted_keys)),
                require_canonical_envelope,
                expected_keyid_hint,
            )
        )
        return original_formula(
            envelope,
            trusted_keys,
            limits=limits,
            require_canonical_envelope=require_canonical_envelope,
            expected_keyid_hint=expected_keyid_hint,
        )

    monkeypatch.setattr(attestation, "verify_vcert", dataset_spy)
    monkeypatch.setattr(attestation, "verify_vcert_v03", formula_spy)
    assert (
        archive.read_certificate(dataset.plot_id, max_bytes=len(dataset.vcert_envelope))
        == dataset.vcert_envelope
    )
    assert (
        archive.read_certificate(formula.plot_id, max_bytes=len(formula.vcert_envelope))
        == formula.vcert_envelope
    )
    assert seen == [
        ("dataset", dataset.vcert_envelope, dataset.keyid, True, dataset.keyid),
        ("formula", formula.vcert_envelope, formula.keyid, True, formula.keyid),
    ]


def test_d3_formula_certificate_limit_uses_v03_mime_before_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    seen: list[str] = []
    original = attestation.envelope_byte_limit

    def limit_spy(max_payload_bytes: int, *, payload_type: str) -> int:
        seen.append(payload_type)
        return original(max_payload_bytes, payload_type=payload_type)

    monkeypatch.setattr(attestation, "envelope_byte_limit", limit_spy)
    monkeypatch.setattr(
        attestation,
        "verify_vcert_v03",
        lambda *_args, **_kwargs: pytest.fail("signature verification ran"),
    )
    # Both MIME strings are the same length today, so the two ceilings are numerically equal and
    # only the spied argument proves which one was selected. The cap must still be low enough to
    # bite before verification: the envelope ceiling carries base64 and JSON headroom over payload.
    tight = msgspec.structs.replace(
        DEFAULT_LIMITS, max_attestation_bytes=len(parts.bundle.vcert_envelope) // 4
    )
    with pytest.raises(ArchiveReadLimitError):
        archive.read_certificate(
            parts.bundle.plot_id,
            max_bytes=len(parts.bundle.vcert_envelope),
            limits=tight,
        )
    assert seen == [attestation.VCERT_V03_PAYLOAD_TYPE]


def test_d3_formula_certificate_never_falls_back_to_dataset_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    calls = {"dataset": 0, "formula": 0}

    def dataset_bomb(*_args: Any, **_kwargs: Any) -> Any:
        calls["dataset"] += 1
        pytest.fail("dataset wrapper reached")

    def formula_failure(*_args: Any, **_kwargs: Any) -> Any:
        calls["formula"] += 1
        msg = "forced formula verification failure"
        raise attestation.AttestationError(msg)

    monkeypatch.setattr(attestation, "verify_vcert", dataset_bomb)
    monkeypatch.setattr(attestation, "verify_vcert_v03", formula_failure)
    with pytest.raises(ArchiveIntegrityError, match="formula"):
        archive.read_certificate(parts.bundle.plot_id, max_bytes=len(parts.bundle.vcert_envelope))
    assert calls == {"dataset": 0, "formula": 1}


def test_d4_read_spec_dataset_short_circuits_formula_decoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, dataset = dataset_bundle(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(dataset)
    spec_id = canon.hash_spec(
        archive_module._decode_canonical_spec(dataset.canonical_spec)
    ).removeprefix("sha256:")
    calls = 0

    def formula_bomb(_payload: bytes) -> object:
        nonlocal calls
        calls += 1
        pytest.fail("formula decoder reached dataset spec")

    monkeypatch.setattr(archive_module, "_decode_canonical_formula_spec", formula_bomb)
    assert (
        archive.read_spec(spec_id, max_bytes=len(dataset.canonical_spec)) == dataset.canonical_spec
    )
    assert calls == 0


def test_d4_read_spec_formula_tries_dataset_then_formula(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    spec_id = canon.hash_spec(parts.spec).removeprefix("sha256:")
    original_dataset = schema.decode_spec
    original_formula = schema.decode_formula_spec
    calls: list[str] = []

    def dataset_spy(payload: bytes) -> object:
        calls.append("dataset")
        return original_dataset(payload)

    def formula_spy(payload: bytes) -> object:
        calls.append("formula")
        return original_formula(payload)

    # The mode-blind reader tries each schema decoder itself, so the schema entry points are the
    # seam; the canonical-form check runs once afterwards on whichever spec was accepted.
    monkeypatch.setattr(archive_module, "decode_spec", dataset_spy)
    monkeypatch.setattr(archive_module, "decode_formula_spec", formula_spy)
    assert archive.read_spec(spec_id, max_bytes=len(parts.bundle.canonical_spec)) == (
        parts.bundle.canonical_spec
    )
    assert calls == ["dataset", "formula"]


def test_d4_read_spec_unexpected_dataset_decoder_fault_propagates_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    spec_id = canon.hash_spec(parts.spec).removeprefix("sha256:")
    calls = 0

    class InjectedError(Exception):
        pass

    def dataset_failure(_payload: bytes) -> object:
        raise InjectedError

    def formula_bomb(_payload: bytes) -> object:
        nonlocal calls
        calls += 1
        pytest.fail("formula fallback reached unexpected fault")

    monkeypatch.setattr(archive_module, "decode_spec", dataset_failure)
    monkeypatch.setattr(archive_module, "decode_formula_spec", formula_bomb)
    with pytest.raises(InjectedError):
        archive.read_spec(spec_id, max_bytes=len(parts.bundle.canonical_spec))
    assert calls == 0


def test_d4_read_spec_refuses_jointly_when_no_language_admits_the_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exhausting both modes names both languages, never the last one tried."""
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    spec_id = canon.hash_spec(parts.spec).removeprefix("sha256:")

    def refuse(_payload: bytes) -> object:
        msg = "no language admits this payload"
        raise ValueError(msg)

    monkeypatch.setattr(archive_module, "decode_spec", refuse)
    monkeypatch.setattr(archive_module, "decode_formula_spec", refuse)
    with pytest.raises(
        ArchiveIntegrityError, match="not a valid VPlot or formula VPlot specification"
    ):
        archive.read_spec(spec_id, max_bytes=len(parts.bundle.canonical_spec))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "Input data was truncated"),
        (b"{}", "Object missing required field `version`"),
        (
            b'{"version":"vplot-0.1","version":"vplot-formula-0.1"}',
            "Invalid enum value",
        ),
        (
            b'{"version":["vplot-0.1","vplot-formula-0.1"]}',
            "Expected `str`, got `array` - at `$.version`",
        ),
    ],
)
def test_p8_both_spec_decoders_refuse_degenerate_shapes(payload: bytes, message: str) -> None:
    # The schema entry points carry msgspec's own text; the archive decoders that wrap them keep
    # their refusal in this project's own vocabulary. Pin both layers, each to what it owns.
    for decode in (schema.decode_spec, schema.decode_formula_spec):
        with pytest.raises(
            (msgspec.DecodeError, msgspec.ValidationError), match=re.escape(message)
        ):
            decode(payload)
    with pytest.raises(ArchiveIntegrityError, match="canonical spec is not a valid"):
        archive_module._decode_canonical_spec(payload)
    with pytest.raises(ArchiveIntegrityError, match="canonical spec is not a valid"):
        archive_module._decode_canonical_formula_spec(payload)


def test_p8_cross_mode_spec_decoder_messages_are_exact(tmp_path: Path) -> None:
    _dataset_settings, dataset = dataset_bundle(tmp_path)
    formula = formula_bundle_parts().bundle
    with pytest.raises(
        ArchiveIntegrityError,
        match=r"plot bundle canonical spec is not a valid VPlot specification",
    ) as dataset_error:
        archive_module._decode_canonical_spec(formula.canonical_spec)
    assert isinstance(dataset_error.value.__cause__, msgspec.ValidationError)
    assert str(dataset_error.value.__cause__) == (
        "Invalid enum value 'vplot-formula-0.1' - at `$.version`"
    )
    with pytest.raises(
        ArchiveIntegrityError,
        match=r"formula plot bundle canonical spec is not a valid formula VPlot specification",
    ) as formula_error:
        archive_module._decode_canonical_formula_spec(dataset.canonical_spec)
    assert isinstance(formula_error.value.__cause__, msgspec.ValidationError)
    assert str(formula_error.value.__cause__) == "Invalid enum value 'vplot-0.1' - at `$.version`"


def test_p4_plot_blob_absence_is_identical_across_modes_and_missing_rows(tmp_path: Path) -> None:
    dataset_settings, dataset = dataset_bundle(tmp_path / "dataset")
    archive = open_archive(dataset_settings)
    formula = formula_bundle_parts().bundle
    archive.publish_plot(dataset)
    archive.publish_plot(formula)
    assert (
        archive.read_plot_blob(
            formula.plot_id,
            _formula_source_role(),
            max_bytes=len(formula.formula_source),
        )
        == formula.formula_source
    )
    errors: list[ArchiveNotFoundError] = []
    for plot_id, role in (
        (dataset.plot_id, _formula_source_role()),
        (formula.plot_id, PlotRole.RAW_CSV),
    ):
        with pytest.raises(ArchiveNotFoundError) as caught:
            archive.read_plot_blob(plot_id, role, max_bytes=1_000_000)
        errors.append(caught.value)
    with _database_connection(archive) as connection:
        connection.execute(
            "DELETE FROM plot_references WHERE plot_id = ? AND role = ?",
            (formula.plot_id, _formula_source_role().value),
        )
    with pytest.raises(ArchiveNotFoundError) as missing:
        archive.read_plot_blob(
            formula.plot_id,
            _formula_source_role(),
            max_bytes=1_000_000,
        )
    assert [str(error) for error in (*errors, missing.value)] == [
        "archive address or typed reference was not found"
    ] * 3


def test_p4_plot_blob_absence_uses_one_typed_query_and_no_source_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    statements: list[str] = []

    class RecordingConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            statements.append(sql)
            return super().execute(sql, parameters)

    monkeypatch.setattr(archive_module, "_CONNECTION_FACTORY", RecordingConnection)
    assert (
        archive.read_plot_blob(
            parts.bundle.plot_id,
            _formula_source_role(),
            max_bytes=len(parts.bundle.formula_source),
        )
        == parts.bundle.formula_source
    )
    assert sum("FROM plot_references" in sql for sql in statements) == 1
    assert not any("FROM plots" in sql for sql in statements)


def test_rd7_formula_plot_envelope_is_source_neutral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, parts = _formula_archive(tmp_path)
    archive.publish_plot(parts.bundle)
    monkeypatch.setattr(
        archive_module,
        "_authenticate_archive_formula_certificate",
        lambda **_kwargs: pytest.fail("formula certificate decoder reached envelope byte read"),
    )
    assert (
        archive.read_plot_envelope(parts.bundle.plot_id, max_bytes=len(parts.bundle.vcert_envelope))
        == parts.bundle.vcert_envelope
    )


def test_d8_formula_publish_final_fault_restores_exact_prior_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, dataset = dataset_bundle(tmp_path / "dataset")
    archive = open_archive(settings)
    archive.publish_plot(dataset)
    before_stats = archive.stats()
    statements = {
        "blobs": "SELECT * FROM blobs ORDER BY 1, 2",
        "keys": "SELECT * FROM keys ORDER BY 1, 2",
        "plots": "SELECT * FROM plots ORDER BY 1, 2",
        "specs": "SELECT * FROM specs ORDER BY 1, 2",
        "plot_references": "SELECT * FROM plot_references ORDER BY 1, 2",
    }
    with _database_connection(archive) as connection:
        before_rows = {
            table: connection.execute(statement).fetchall()
            for table, statement in statements.items()
        }
    formula = formula_bundle_parts().bundle

    class InjectedError(Exception):
        pass

    def fail() -> None:
        raise InjectedError

    monkeypatch.setattr(archive_module, "_before_archive_commit", fail)
    with pytest.raises(InjectedError):
        archive.publish_plot(formula)
    assert archive.stats() == before_stats
    with _database_connection(archive) as connection:
        after_rows = {
            table: connection.execute(statement).fetchall()
            for table, statement in statements.items()
        }
    assert after_rows == before_rows


def test_d6_formula_quota_counts_all_nine_unique_carriers_and_rolls_back(tmp_path: Path) -> None:
    parts = formula_bundle_parts()
    expected = sum(
        len(getattr(parts.bundle, field.name))
        for field in fields(parts.bundle)
        if field.name not in {"plot_id", "keyid"}
    )
    exact_settings = Settings(
        data_dir=_ROOT / "data",
        state_dir=tmp_path / "exact",
        max_archive_bytes=expected,
    )
    exact = open_archive(exact_settings)
    exact.publish_plot(parts.bundle)
    assert exact.stats() == ArchiveStats(expected, 9, 1, 1, 0)
    tight_settings = Settings(
        data_dir=_ROOT / "data",
        state_dir=tmp_path / "tight",
        max_archive_bytes=expected - 1,
    )
    tight = open_archive(tight_settings)
    with pytest.raises(ArchiveQuotaError):
        tight.publish_plot(parts.bundle)
    assert tight.stats() == ArchiveStats(0, 0, 0, 0, 0)


def test_d6_equal_bytes_different_kinds_count_twice_at_batch_layer(tmp_path: Path) -> None:
    archive = open_archive(Settings(data_dir=_ROOT / "data", state_dir=tmp_path / "typed-identity"))
    payload = b"truthfully typed equal bytes"
    first = BlobWrite(BlobKind.VERDICT, payload)
    second = BlobWrite(BlobKind.TOOL_VERSIONS, payload)
    archive.publish(archive_module.ArchiveBatch(blobs=(first, second)))
    assert first.ref.digest == second.ref.digest
    assert first.ref.kind is not second.ref.kind
    assert archive.stats() == ArchiveStats(2 * len(payload), 2, 0, 0, 0)


def test_d7_migrated_v3_archive_reads_full_dataset_plot(tmp_path: Path) -> None:
    settings, dataset = dataset_bundle(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(dataset)
    with _database_connection(archive) as connection:
        downgrade_to_v3(connection)
    reopened = open_archive(settings)
    assert reopened.read_plot(dataset.plot_id, max_bytes=_bundle_bytes(dataset)) == dataset


def test_rd5_mode_flipped_dataset_row_has_mode_specific_new_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, dataset = dataset_bundle(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(dataset)
    with _database_connection(archive) as connection:
        connection.execute(
            "UPDATE plots SET source_kind = 'formula' WHERE plot_id = ?",
            (dataset.plot_id,),
        )
    with pytest.raises(ArchiveIntegrityError, match="every required role"):
        archive.read_plot(dataset.plot_id, max_bytes=_bundle_bytes(dataset))
    calls = 0
    original = attestation.verify_vcert_v03

    def formula_spy(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(attestation, "verify_vcert_v03", formula_spy)
    with pytest.raises(ArchiveIntegrityError, match="formula"):
        archive.read_certificate(dataset.plot_id, max_bytes=len(dataset.vcert_envelope))
    assert calls == 1
    assert (
        archive.read_plot_envelope(dataset.plot_id, max_bytes=len(dataset.vcert_envelope))
        == dataset.vcert_envelope
    )


def test_p9_unknown_source_mode_refuses_upstream_before_role_selection() -> None:
    key = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, b"k" * 32)
    plot_id = "a" * 64
    with pytest.raises(ArchiveIntegrityError, match="closed provenance modes"):
        archive_module._validated_plot_record(
            (f"sha256:{plot_id}", "vcert_envelope", key.ref.digest, "spreadsheet"),
            plot_id,
        )


def test_s6_storage_claim_docstrings_no_longer_describe_formula_as_future() -> None:
    module_doc = archive_module.__doc__ or ""
    source_doc = archive_module.PlotSourceKind.__doc__ or ""
    formula_doc = archive_module.FormulaPlotBundle.__doc__ or ""
    stale = (
        "Only ``dataset`` rows are produced",
        "construct + validate only",
        "persistence lands next",
        "Persistence arrives in M9.7b-2",
    )
    assert all(text not in module_doc + source_doc + formula_doc for text in stale)
    assert "formula" in module_doc.lower()
    assert "formula" in source_doc.lower()
    assert "formula" in formula_doc.lower()
