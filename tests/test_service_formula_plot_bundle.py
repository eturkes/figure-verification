# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9.7b-1 source-tagged formula plot-bundle acceptance probes."""

import ast
import subprocess
import sys
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeAliasType, cast, get_args, get_type_hints

import msgspec
import pytest
from msgspec.structs import replace as struct_replace

from formula_plot_bundle_helpers import (
    canonical_specs,
    dataset_bundle,
    dataset_certificate,
    dataset_v03_certificate,
    different_digest,
    formula_bundle_parts,
    resign_formula_bundle,
)
from verifier import attestation, canon, render, vcert
from verifier.limits import DEFAULT_LIMITS
from verifier.schema import FormulaPlotSpec, VPlotSpec
from verifier.service import archive as archive_module
from verifier.service.archive import ArchiveIntegrityError
from verifier.service.identity import keyid_for_public_key, load_identity
from verifier.service.models import Verdict


def test_t01_real_chain_formula_bundle_validates() -> None:
    """T01: real-chain formula bundle validates in memory."""
    parts = formula_bundle_parts()
    archive_module._validate_plot_bundle(parts.bundle, DEFAULT_LIMITS)


def test_t02_formula_source_digest_mismatch_refuses() -> None:
    """T02: formula-source carrier digest mismatch refuses."""
    parts = formula_bundle_parts()
    formula_source = cast("vcert.FormulaSourceCert", parts.certificate.source)
    source = struct_replace(
        formula_source,
        formula_hash=different_digest(formula_source.formula_hash),
    )
    mutant = resign_formula_bundle(parts, struct_replace(parts.certificate, source=source))
    with pytest.raises(ArchiveIntegrityError, match="formula source"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t03_formula_spec_digest_mismatch_refuses() -> None:
    """T03: formula-spec carrier digest mismatch refuses."""
    parts = formula_bundle_parts()
    certificate = struct_replace(
        parts.certificate,
        spec_hash=different_digest(parts.certificate.spec_hash),
    )
    mutant = resign_formula_bundle(parts, certificate)
    with pytest.raises(ArchiveIntegrityError, match="spec"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t04_formula_table_digest_mismatch_refuses() -> None:
    """T04: plotted-table carrier digest mismatch refuses."""
    parts = formula_bundle_parts()
    certificate = struct_replace(
        parts.certificate,
        plotted_table_hash=different_digest(parts.certificate.plotted_table_hash),
    )
    mutant = resign_formula_bundle(parts, certificate)
    with pytest.raises(ArchiveIntegrityError, match="plotted table"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t05_formula_script_digest_mismatch_refuses() -> None:
    """T05: matplotlib-script carrier digest mismatch refuses."""
    parts = formula_bundle_parts()
    script_artifact = cast("vcert.MatplotlibScriptArtifactCert", parts.certificate.artifact)
    artifact = struct_replace(
        script_artifact,
        matplotlib_script_hash=different_digest(script_artifact.matplotlib_script_hash),
    )
    mutant = resign_formula_bundle(parts, struct_replace(parts.certificate, artifact=artifact))
    with pytest.raises(ArchiveIntegrityError, match="matplotlib script"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t06_formula_verdict_requires_verified_layer() -> None:
    """T06: formula verdict requires verified=true and layer=verify."""
    parts = formula_bundle_parts()
    for verdict in (
        Verdict(verified=False, layer="verify", results=parts.artifact.results),
        Verdict(verified=True, layer="decode", results=parts.artifact.results),
    ):
        mutant = replace(
            parts.bundle,
            verdict=msgspec.json.encode(verdict, order="deterministic"),
        )
        with pytest.raises(ArchiveIntegrityError, match="complete passing"):
            archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t07_formula_verdict_mixed_status_refuses() -> None:
    """T07: mixed pass/fail formula verdict refuses in archive validation."""
    parts = formula_bundle_parts()
    passed = parts.artifact.results[0]
    failed = struct_replace(passed, status="fail")
    verdict = Verdict(verified=True, layer="verify", results=(passed, failed))
    mutant = replace(
        parts.bundle,
        verdict=msgspec.json.encode(verdict, order="deterministic"),
    )
    with pytest.raises(ArchiveIntegrityError, match="complete passing"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t08_formula_tool_versions_must_match_certificate() -> None:
    """T08: decoded FormulaTcb must equal the authenticated certificate TCB."""
    parts = formula_bundle_parts()
    different_tcb = struct_replace(
        parts.certificate.tcb,
        verifier_version=parts.certificate.tcb.verifier_version + "-other",
    )
    mutant = replace(
        parts.bundle,
        tool_versions=msgspec.json.encode(different_tcb, order="deterministic"),
    )
    with pytest.raises(ArchiveIntegrityError, match="tool versions"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t09_formula_spec_noncanonical_bytes_refuse() -> None:
    """T09: mode-correct but noncanonical formula-spec JSON refuses."""
    parts = formula_bundle_parts()
    noncanonical = b" " + parts.bundle.canonical_spec
    mutant = replace(parts.bundle, canonical_spec=noncanonical)
    with pytest.raises(ArchiveIntegrityError, match="canonical spec bytes"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t10_formula_script_requires_utf8() -> None:
    """T10: hash-coherent non-UTF-8 matplotlib script refuses."""
    parts = formula_bundle_parts()
    script = b"\xff"
    artifact = struct_replace(
        parts.certificate.artifact,
        matplotlib_script_hash=canon.hash_matplotlib_script(script),
    )
    mutant = resign_formula_bundle(
        parts,
        struct_replace(parts.certificate, artifact=artifact),
        matplotlib_script=script,
    )
    with pytest.raises(ArchiveIntegrityError, match="UTF-8"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t11_formula_authentication_wrapper_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T11: formula authentication uses the fixed v0.3 wrapper and own-key arguments."""
    parts = formula_bundle_parts()
    original = attestation.verify_vcert_v03
    calls: list[tuple[Any, Any, Any, Any, Any]] = []

    def spy(envelope: bytes, trusted_keys: Any, **kwargs: Any) -> object:
        calls.append(
            (
                envelope,
                trusted_keys,
                kwargs["limits"],
                kwargs["require_canonical_envelope"],
                kwargs["expected_keyid_hint"],
            )
        )
        return original(envelope, trusted_keys, **kwargs)

    monkeypatch.setattr(attestation, "verify_vcert_v03", spy)
    archive_module._validate_plot_bundle(parts.bundle, DEFAULT_LIMITS)
    assert len(calls) == 1
    envelope, trusted_keys, limits, canonical, hint = calls[0]
    assert envelope == parts.bundle.vcert_envelope
    assert tuple(trusted_keys) == (parts.bundle.keyid,)
    assert limits is DEFAULT_LIMITS
    assert canonical is True
    assert hint == parts.bundle.keyid


def test_t12_formula_mode_refuses_dataset_v02_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T12: formula mode routes a dataset v0.2 envelope only to the v0.3 wrapper."""
    parts = formula_bundle_parts()
    certificate = dataset_certificate()
    envelope = attestation.sign_vcert(
        certificate, parts.signer.private_key, keyid=parts.signer.keyid
    )
    mutant = replace(
        parts.bundle,
        plot_id=__import__("hashlib").sha256(envelope).hexdigest(),
        vcert_payload=vcert.vcert_bytes(certificate),
        vcert_envelope=envelope,
    )
    calls = {"v02": 0, "v03": 0}
    original_v03 = attestation.verify_vcert_v03

    def v02_bomb(*_args: Any, **_kwargs: Any) -> object:
        calls["v02"] += 1
        msg = "wrong v0.2 wrapper"
        raise AssertionError(msg)

    def v03_spy(*args: Any, **kwargs: Any) -> object:
        calls["v03"] += 1
        return original_v03(*args, **kwargs)

    monkeypatch.setattr(attestation, "verify_vcert", v02_bomb)
    monkeypatch.setattr(attestation, "verify_vcert_v03", v03_spy)
    with pytest.raises(ArchiveIntegrityError):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)
    assert calls == {"v02": 0, "v03": 1}


def test_t13_dataset_mode_refuses_formula_v03_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T13: dataset mode routes a formula v0.3 envelope only to the v0.2 wrapper."""
    parts = formula_bundle_parts()
    dataset_type = archive_module.DatasetPlotBundle
    dataset_bundle = object.__new__(dataset_type)
    for name in dataset_type.__dataclass_fields__:
        value = getattr(parts.bundle, name, b"x")
        object.__setattr__(dataset_bundle, name, value)
    calls = {"v02": 0, "v03": 0}
    original_v02 = attestation.verify_vcert

    def v02_spy(*args: Any, **kwargs: Any) -> object:
        calls["v02"] += 1
        return original_v02(*args, **kwargs)

    def v03_bomb(*_args: Any, **_kwargs: Any) -> object:
        calls["v03"] += 1
        msg = "wrong v0.3 wrapper"
        raise AssertionError(msg)

    monkeypatch.setattr(attestation, "verify_vcert", v02_spy)
    monkeypatch.setattr(attestation, "verify_vcert_v03", v03_bomb)
    with pytest.raises(ArchiveIntegrityError):
        archive_module._validate_plot_bundle(dataset_bundle, DEFAULT_LIMITS)
    assert calls == {"v02": 1, "v03": 0}


def test_t14_formula_mode_refuses_dataset_family_v03_certificate() -> None:
    """T14: formula mode refuses the correlated dataset family inside VCert v0.3."""
    parts = formula_bundle_parts()
    certificate = dataset_v03_certificate()
    mutant = resign_formula_bundle(parts, certificate)
    with pytest.raises(ArchiveIntegrityError, match="formula"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t15_each_bundle_byte_field_has_class_specific_type_error(tmp_path: Path) -> None:
    """T15: every dataset/formula carrier gets its ratified class-specific TypeError."""
    parts = formula_bundle_parts()
    formula_fields = (
        "canonical_spec",
        "formula_source",
        "plotted_table",
        "verdict",
        "matplotlib_script",
        "vcert_payload",
        "vcert_envelope",
        "tool_versions",
        "public_key",
    )
    for name in formula_fields:
        with pytest.raises(TypeError, match=rf"formula plot bundle {name} must be bytes, got str"):
            replace(parts.bundle, **{name: "bad"})
    _settings, dataset = dataset_bundle(tmp_path)
    dataset_fields = tuple(
        field.name for field in fields(dataset) if field.name not in {"plot_id", "keyid"}
    )
    for name in dataset_fields:
        with pytest.raises(TypeError, match=rf"plot bundle {name} must be bytes, got str"):
            replace(dataset, **{name: "bad"})
    assert keyid_for_public_key(parts.bundle.public_key) == parts.bundle.keyid


def test_t16_plot_bundle_alias_is_nonconstructible() -> None:
    """T16: PlotBundle is the non-callable PEP-695 two-member union alias."""
    alias = archive_module.PlotBundle
    assert isinstance(alias, TypeAliasType)
    assert alias.__value__ == (archive_module.DatasetPlotBundle | archive_module.FormulaPlotBundle)
    with pytest.raises(TypeError):
        alias()  # type: ignore[operator]


def test_t17_dataset_bundle_subclass_refuses_at_publish_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T17: DatasetPlotBundle subclass refuses before validation or projection."""
    settings, bundle = dataset_bundle(tmp_path)
    child_type = type("DatasetChild", (type(bundle),), {})
    child = child_type(**{field.name: getattr(bundle, field.name) for field in fields(bundle)})
    calls = {"validate": 0, "batch": 0}
    original_validate = archive_module._validate_plot_bundle
    original_batch = archive_module._plot_bundle_batch

    def validate_spy(*args: Any, **kwargs: Any) -> object:
        calls["validate"] += 1
        return original_validate(*args, **kwargs)

    def batch_spy(*args: Any, **kwargs: Any) -> object:
        calls["batch"] += 1
        return original_batch(*args, **kwargs)

    monkeypatch.setattr(archive_module, "_validate_plot_bundle", validate_spy)
    monkeypatch.setattr(archive_module, "_plot_bundle_batch", batch_spy)
    archive = archive_module.open_archive(settings)
    with pytest.raises(TypeError, match=r"DatasetPlotBundle.*FormulaPlotBundle.*DatasetChild"):
        archive.publish_plot(child)
    assert calls == {"validate": 0, "batch": 0}


def test_t18_formula_bundle_subclass_refuses_at_publish_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T18: FormulaPlotBundle subclass refuses before validation or projection."""
    parts = formula_bundle_parts()
    child_type = type("FormulaChild", (type(parts.bundle),), {})
    child = child_type(
        **{field.name: getattr(parts.bundle, field.name) for field in fields(parts.bundle)}
    )
    settings, _dataset = dataset_bundle(tmp_path)
    calls = {"validate": 0, "batch": 0}
    monkeypatch.setattr(
        archive_module,
        "_validate_plot_bundle",
        lambda *_args: calls.__setitem__("validate", calls["validate"] + 1),
    )
    monkeypatch.setattr(
        archive_module,
        "_plot_bundle_batch",
        lambda *_args: calls.__setitem__("batch", calls["batch"] + 1),
    )
    archive = archive_module.open_archive(settings)
    with pytest.raises(TypeError, match=r"DatasetPlotBundle.*FormulaPlotBundle.*FormulaChild"):
        archive.publish_plot(child)
    assert calls == {"validate": 0, "batch": 0}


def test_t19_dataset_bundle_subclass_refuses_in_attempt_bundle(tmp_path: Path) -> None:
    """T19: AttemptBundle admits exact DatasetPlotBundle or None only."""
    _settings, bundle = dataset_bundle(tmp_path)
    child_type = type("DatasetChild", (type(bundle),), {})
    child = child_type(**{field.name: getattr(bundle, field.name) for field in fields(bundle)})
    artifacts = archive_module.AttemptArtifacts()
    manifest = archive_module.AttemptManifest(
        version="attempt-0.1",
        nonce="0" * 32,
        occurred_at="2026-01-01T00:00:00.000000Z",
        route=archive_module.AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=archive_module.AttemptOutcome.VERIFIED,
        plot_id=None,
        artifacts=(),
        plot_artifacts=(),
        keyid=bundle.keyid,
        verifier_version="test",
    )
    with pytest.raises(TypeError, match=r"DatasetPlotBundle or None.*DatasetChild"):
        archive_module.AttemptBundle(
            attempt_id="0" * 64,
            keyid=bundle.keyid,
            manifest=manifest,
            artifacts=artifacts,
            attempt_payload=b"{}",
            attempt_envelope=b"{}",
            public_key=bundle.public_key,
            plot=child,
        )


def test_t20_dataset_bundle_subclass_refuses_in_attempt_materializer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T20: attempt materialization refuses a DatasetPlotBundle subclass before signing."""
    settings, bundle = dataset_bundle(tmp_path)
    child_type = type("DatasetChild", (type(bundle),), {})
    child = child_type(**{field.name: getattr(bundle, field.name) for field in fields(bundle)})
    draft = archive_module.AttemptDraft(
        occurred_at=datetime.now(UTC),
        route=archive_module.AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=archive_module.AttemptOutcome.VERIFIED,
        artifacts=archive_module.AttemptArtifacts(),
        plot=child,
    )
    monkeypatch.setattr(attestation, "sign_dsse", lambda *_args, **_kwargs: pytest.fail("signed"))
    with pytest.raises(TypeError, match=r"DatasetPlotBundle or None.*DatasetChild"):
        archive_module.materialize_attempt_bundle(
            draft, load_identity(settings).signer, nonce="0" * 32
        )


def test_t21_dataset_spec_decoder_refuses_formula_mode() -> None:
    """T21: dataset canonical-spec decoder refuses canonical formula specs."""
    _dataset, formula = canonical_specs()
    with pytest.raises(ArchiveIntegrityError, match="valid VPlot specification"):
        archive_module._decode_canonical_spec(canon.spec_bytes(formula))


def test_t22_formula_spec_decoder_refuses_dataset_mode() -> None:
    """T22: formula canonical-spec decoder refuses canonical dataset specs."""
    dataset, _formula = canonical_specs()
    decoder = archive_module._decode_canonical_formula_spec
    with pytest.raises(ArchiveIntegrityError, match="formula"):
        decoder(canon.spec_bytes(dataset))


def test_t23_each_spec_decoder_accepts_its_mode() -> None:
    """T23: each per-mode spec decoder accepts and round-trips its canonical mode."""
    dataset, formula = canonical_specs()
    decoded_dataset = archive_module._decode_canonical_spec(canon.spec_bytes(dataset))
    decoded_formula = archive_module._decode_canonical_formula_spec(canon.spec_bytes(formula))
    assert type(decoded_dataset) is VPlotSpec
    assert type(decoded_formula) is FormulaPlotSpec
    assert canon.spec_bytes(decoded_dataset) == canon.spec_bytes(dataset)
    assert canon.spec_bytes(decoded_formula) == canon.spec_bytes(formula)


def test_t24_each_spec_decoder_refuses_noncanonical_bytes() -> None:
    """T24: both per-mode spec decoders refuse accepted noncanonical JSON."""
    dataset, formula = canonical_specs()
    with pytest.raises(ArchiveIntegrityError, match="canonical"):
        archive_module._decode_canonical_spec(b" " + canon.spec_bytes(dataset))
    with pytest.raises(ArchiveIntegrityError, match="canonical"):
        archive_module._decode_canonical_formula_spec(b" " + canon.spec_bytes(formula))


def test_t25_formula_table_noncanonical_bytes_refuse() -> None:
    """T25: hash-coherent noncanonical typed-NDJSON table refuses."""
    parts = formula_bundle_parts()
    header, separator, rows = parts.bundle.plotted_table.partition(b"\n")
    table = b" " + header + separator + rows
    certificate = struct_replace(
        parts.certificate, plotted_table_hash=canon.hash_table_bytes(table)
    )
    mutant = resign_formula_bundle(parts, certificate, plotted_table=table)
    with pytest.raises(ArchiveIntegrityError, match="canonical"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t26_formula_verdict_noncanonical_bytes_refuse() -> None:
    """T26: accepted noncanonical formula-verdict JSON refuses."""
    parts = formula_bundle_parts()
    mutant = replace(parts.bundle, verdict=b" " + parts.bundle.verdict)
    with pytest.raises(ArchiveIntegrityError, match="canonical deterministic JSON"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t27_formula_verdict_attempt_id_refuses() -> None:
    """T27: formula plot verdict must omit attempt_id."""
    parts = formula_bundle_parts()
    verdict = Verdict(
        verified=True, layer="verify", results=parts.artifact.results, attempt_id="a" * 64
    )
    mutant = replace(parts.bundle, verdict=msgspec.json.encode(verdict, order="deterministic"))
    with pytest.raises(ArchiveIntegrityError, match="omit attempt_id"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t28_formula_tool_versions_strict_shape_refuses() -> None:
    """T28: FormulaTcb decoder refuses unknown fields and wrong tagged kind."""
    parts = formula_bundle_parts()
    wire = msgspec.json.decode(parts.bundle.tool_versions)
    mutants = (
        msgspec.json.encode({**wire, "unknown": 1}, order="deterministic"),
        msgspec.json.encode({**wire, "kind": "dataset"}, order="deterministic"),
    )
    for payload in mutants:
        with pytest.raises(ArchiveIntegrityError, match="tool versions"):
            archive_module._validate_plot_bundle(
                replace(parts.bundle, tool_versions=payload), DEFAULT_LIMITS
            )


def test_t29_formula_tool_versions_noncanonical_bytes_refuse() -> None:
    """T29: accepted noncanonical FormulaTcb JSON refuses."""
    parts = formula_bundle_parts()
    with pytest.raises(ArchiveIntegrityError, match="canonical deterministic JSON"):
        archive_module._validate_plot_bundle(
            replace(parts.bundle, tool_versions=b" " + parts.bundle.tool_versions),
            DEFAULT_LIMITS,
        )


def test_t30_formula_certificate_checks_must_equal_verdict() -> None:
    """T30: ordered full certificate checks must equal the formula verdict results."""
    parts = formula_bundle_parts()
    certificate = struct_replace(parts.certificate, checks=parts.certificate.checks[:-1])
    mutant = resign_formula_bundle(parts, certificate)
    with pytest.raises(ArchiveIntegrityError, match="method-aware verdict"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t31_formula_check_method_must_match_registry() -> None:
    """T31: mutually wrong certificate/verdict methods still refuse against registry."""
    parts = formula_bundle_parts()
    result = parts.artifact.results[0]
    wrong_method = "construction" if result.method != "construction" else "z3_smt"
    wrong_result = struct_replace(result, method=wrong_method)
    wrong_check = struct_replace(parts.certificate.checks[0], method=wrong_method)
    verdict = Verdict(
        verified=True, layer="verify", results=(wrong_result, *parts.artifact.results[1:])
    )
    certificate = struct_replace(
        parts.certificate, checks=(wrong_check, *parts.certificate.checks[1:])
    )
    mutant = resign_formula_bundle(
        parts, certificate, verdict=msgspec.json.encode(verdict, order="deterministic")
    )
    with pytest.raises(ArchiveIntegrityError, match="registered verification method"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t32_formula_validation_never_calls_dataset_only_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T32: formula validation calls no dataset/manifest/disclosure helper."""
    parts = formula_bundle_parts()
    calls = {"dataset": 0, "manifest": 0, "transforms": 0}

    def bomb(name: str) -> object:
        def inner(*_args: Any, **_kwargs: Any) -> object:
            calls[name] += 1
            raise AssertionError(name)

        return inner

    monkeypatch.setattr(canon, "hash_dataset", bomb("dataset"))
    monkeypatch.setattr(canon, "hash_manifest", bomb("manifest"))
    monkeypatch.setattr(render, "disclosed_transforms", bomb("transforms"))
    archive_module._validate_plot_bundle(parts.bundle, DEFAULT_LIMITS)
    assert calls == {"dataset": 0, "manifest": 0, "transforms": 0}


def test_t33_formula_certificate_has_no_dataset_only_members() -> None:
    """T33: exact formula certificate variants lack dataset-only members."""
    parts = formula_bundle_parts()
    assert type(parts.certificate.source) is vcert.FormulaSourceCert
    assert type(parts.certificate.artifact) is vcert.MatplotlibScriptArtifactCert
    assert type(parts.certificate.tcb) is vcert.FormulaTcb
    fields_by_member = {
        field.name
        for member in (parts.certificate.source, parts.certificate.artifact, parts.certificate.tcb)
        for field in msgspec.structs.fields(type(member))
    }
    assert {"dataset_hash", "manifest_hash", "filters", "sorts"}.isdisjoint(fields_by_member)


def test_t34_malformed_formula_source_is_digest_bound_not_parsed() -> None:
    """T34: structurally malformed formula-source bytes may pass when digest-coherent."""
    parts = formula_bundle_parts()
    source_bytes = b"\xffnot-canonical-formula-source"
    source = struct_replace(
        parts.certificate.source, formula_hash=canon.hash_formula_source(source_bytes)
    )
    mutant = resign_formula_bundle(
        parts, struct_replace(parts.certificate, source=source), formula_source=source_bytes
    )
    archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t35_formula_source_hashes_exact_bytes_without_rederivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T35: archive hashes exact formula-source bytes without serializer/parser calls."""
    parts = formula_bundle_parts()
    original = canon.hash_formula_source
    seen: list[bytes] = []

    def hash_spy(payload: bytes) -> str:
        seen.append(payload)
        return original(payload)

    monkeypatch.setattr(canon, "hash_formula_source", hash_spy)
    monkeypatch.setattr(
        canon, "formula_source_bytes", lambda *_args: pytest.fail("re-derived formula source")
    )
    archive_module._validate_plot_bundle(parts.bundle, DEFAULT_LIMITS)
    assert seen == [parts.bundle.formula_source]


def test_t36_formula_batch_choke_precedes_dataset_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T36: _plot_bundle_batch first-statement choke raises ratified NotImplementedError."""
    parts = formula_bundle_parts()
    calls = 0

    def decoder_bomb(*_args: Any, **_kwargs: Any) -> object:
        nonlocal calls
        calls += 1
        msg = "dataset decoder reached"
        raise AssertionError(msg)

    monkeypatch.setattr(archive_module, "_decode_canonical_spec", decoder_bomb)
    with pytest.raises(NotImplementedError, match=r"M9\.7b-2"):
        archive_module._plot_bundle_batch(parts.bundle)
    assert calls == 0


def test_t37_publish_formula_reaches_sole_live_storage_choke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T37: publish_plot validates formula then reaches the sole live choke with zero rows."""
    parts = formula_bundle_parts()
    settings, _dataset = dataset_bundle(tmp_path)
    archive = archive_module.open_archive(settings)
    before = archive.stats()
    original_validate = archive_module._validate_plot_bundle
    original_batch = archive_module._plot_bundle_batch
    calls = {"validate": 0, "batch": 0}

    def validate_spy(*args: Any, **kwargs: Any) -> object:
        calls["validate"] += 1
        return original_validate(*args, **kwargs)

    def batch_spy(*args: Any, **kwargs: Any) -> object:
        calls["batch"] += 1
        return original_batch(*args, **kwargs)

    monkeypatch.setattr(archive_module, "_validate_plot_bundle", validate_spy)
    monkeypatch.setattr(archive_module, "_plot_bundle_batch", batch_spy)
    with pytest.raises(NotImplementedError, match=r"M9\.7b-2"):
        archive.publish_plot(parts.bundle)
    assert calls == {"validate": 1, "batch": 1}
    assert archive.stats() == before


def test_t39_dataset_validator_body_matches_baseline() -> None:
    """T39: isolated body-byte comparison matches baseline e432bd9."""
    script = __file__.replace(
        "test_service_formula_plot_bundle.py", "formula_plot_bundle_body_diff.py"
    )
    subprocess.run([sys.executable, script], check=True)  # noqa: S603 — fixed interpreter


def test_t40_no_production_formula_bundle_producer() -> None:
    """T40: src has no FormulaPlotBundle producer or formula bundle materializer."""
    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    calls: list[str] = []
    materializers: list[str] = []
    for path in (root / "src").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "FormulaPlotBundle"
            ):
                calls.append(f"{path}:{node.lineno}")
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "materialize_formula_plot_bundle"
            ):
                materializers.append(f"{path}:{node.lineno}")
    assert calls == []
    assert materializers == []


def test_t41_bundle_exports_and_field_orders() -> None:
    """T41: concrete exports and ratified exact field orders are pinned."""
    dataset_type = archive_module.DatasetPlotBundle
    formula_type = archive_module.FormulaPlotBundle
    assert {"DatasetPlotBundle", "FormulaPlotBundle", "PlotBundle"} <= set(archive_module.__all__)
    assert tuple(field.name for field in fields(dataset_type)) == (
        "plot_id",
        "keyid",
        "raw_csv",
        "raw_manifest",
        "canonical_spec",
        "plotted_table",
        "verdict",
        "vega_lite",
        "svg",
        "vcert_payload",
        "vcert_envelope",
        "tool_versions",
        "public_key",
    )
    assert tuple(field.name for field in fields(formula_type)) == (
        "plot_id",
        "keyid",
        "canonical_spec",
        "formula_source",
        "plotted_table",
        "verdict",
        "matplotlib_script",
        "vcert_payload",
        "vcert_envelope",
        "tool_versions",
        "public_key",
    )


def test_t42_dataset_preservation_manifest_matches_baseline() -> None:
    """T42: isolated finite dataset-observable manifest matches baseline e432bd9."""
    script = __file__.replace(
        "test_service_formula_plot_bundle.py", "formula_plot_bundle_dataset_manifest.py"
    )
    subprocess.run([sys.executable, script], check=True)  # noqa: S603 — fixed interpreter


def test_t43_formula_authentication_uses_bundle_self_consistency_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T43: formula authentication refuses address/key mutants without policy or DB lookup."""
    parts = formula_bundle_parts()
    other = formula_bundle_parts()
    monkeypatch.setattr(
        archive_module,
        "_connect",
        lambda *_args, **_kwargs: pytest.fail("DB lookup"),
        raising=False,
    )
    mutants = (
        replace(parts.bundle, public_key=other.bundle.public_key),
        replace(parts.bundle, keyid=other.bundle.keyid),
        replace(parts.bundle, plot_id="0" * 64),
    )
    for mutant in mutants:
        with pytest.raises(ArchiveIntegrityError):
            archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t44_attempt_layer_remains_dataset_concrete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T44: formula plots refuse at both attempt guards before signing or persistence."""
    parts = formula_bundle_parts()
    assert set(get_args(get_type_hints(archive_module.AttemptDraft)["plot"])) == {
        archive_module.DatasetPlotBundle,
        type(None),
    }
    assert set(get_args(get_type_hints(archive_module.AttemptBundle)["plot"])) == {
        archive_module.DatasetPlotBundle,
        type(None),
    }
    assert tuple(archive_module.AttemptRoute) == (
        archive_module.AttemptRoute.VERIFY_AND_RENDER,
        archive_module.AttemptRoute.PROPOSE_SPEC,
    )
    monkeypatch.setattr(attestation, "sign_dsse", lambda *_args, **_kwargs: pytest.fail("signed"))
    draft = archive_module.AttemptDraft(
        occurred_at=datetime.now(UTC),
        route=archive_module.AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=archive_module.AttemptOutcome.VERIFIED,
        artifacts=archive_module.AttemptArtifacts(),
        plot=parts.bundle,
    )
    with pytest.raises(TypeError, match=r"DatasetPlotBundle or None.*FormulaPlotBundle"):
        archive_module.materialize_attempt_bundle(draft, parts.signer, nonce="0" * 32)
    manifest = archive_module.AttemptManifest(
        version="attempt-0.1",
        nonce="0" * 32,
        occurred_at="2026-01-01T00:00:00.000000Z",
        route=archive_module.AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=archive_module.AttemptOutcome.VERIFIED,
        plot_id=None,
        artifacts=(),
        plot_artifacts=(),
        keyid=parts.signer.keyid,
        verifier_version="test",
    )
    with pytest.raises(TypeError, match=r"DatasetPlotBundle or None.*FormulaPlotBundle"):
        archive_module.AttemptBundle(
            attempt_id="0" * 64,
            keyid=parts.signer.keyid,
            manifest=manifest,
            artifacts=archive_module.AttemptArtifacts(),
            attempt_payload=b"{}",
            attempt_envelope=b"{}",
            public_key=parts.signer.public_key_bytes,
            plot=parts.bundle,
        )


def test_t45_bundle_validator_refuses_both_member_subclasses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T45: internal exact-type dispatch refuses both subclasses before authentication."""
    _settings, dataset = dataset_bundle(tmp_path)
    formula = formula_bundle_parts().bundle
    calls = {"dataset": 0, "formula": 0}
    monkeypatch.setattr(
        archive_module,
        "_authenticated_bundle_certificate",
        lambda *_args: calls.__setitem__("dataset", calls["dataset"] + 1),
    )
    monkeypatch.setattr(
        archive_module,
        "_authenticated_formula_bundle_certificate",
        lambda *_args: calls.__setitem__("formula", calls["formula"] + 1),
        raising=False,
    )
    for base, name in ((type(dataset), "DatasetChild"), (type(formula), "FormulaChild")):
        child_type = type(name, (base,), {})
        source = dataset if base is type(dataset) else formula
        child = child_type(**{field.name: getattr(source, field.name) for field in fields(source)})
        with pytest.raises(TypeError, match=rf"DatasetPlotBundle.*FormulaPlotBundle.*{name}"):
            archive_module._validate_plot_bundle(child, DEFAULT_LIMITS)
    assert calls == {"dataset": 0, "formula": 0}


def test_t46_formula_payload_and_envelope_ceilings_refuse() -> None:
    """T46: own-mode resource ceilings refuse before any signature work."""
    parts = formula_bundle_parts()
    payload = parts.bundle.vcert_payload
    tight = struct_replace(DEFAULT_LIMITS, max_attestation_bytes=len(payload) - 1)
    with pytest.raises(archive_module.ArchiveReadLimitError, match="VCert payload has"):
        archive_module._validate_plot_bundle(parts.bundle, tight)

    padded = parts.bundle.vcert_envelope + b" " * 4096
    oversized = replace(
        parts.bundle,
        vcert_envelope=padded,
        plot_id=__import__("hashlib").sha256(padded).hexdigest(),
    )
    exact = struct_replace(DEFAULT_LIMITS, max_attestation_bytes=len(payload))
    with pytest.raises(archive_module.ArchiveReadLimitError, match="VCert envelope has"):
        archive_module._validate_plot_bundle(oversized, exact)


def test_t47_formula_envelope_ceiling_uses_own_mime() -> None:
    """T47: the envelope ceiling is derived under the v0.3 payload type, not v0.2 by default."""
    seen: list[str] = []
    original = attestation.envelope_byte_limit

    def spy(max_payload_bytes: int, *, payload_type: str = attestation.VCERT_PAYLOAD_TYPE) -> int:
        seen.append(payload_type)
        return original(max_payload_bytes, payload_type=payload_type)

    parts = formula_bundle_parts()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(attestation, "envelope_byte_limit", spy)
        archive_module._validate_plot_bundle(parts.bundle, DEFAULT_LIMITS)
    # The archive's own pre-check plus attestation's internal ceiling both appear; a default-MIME
    # archive call would put the v0.2 type in this set even though the two are equal in length.
    assert set(seen) == {attestation.VCERT_V03_PAYLOAD_TYPE}


def test_t48_formula_payload_must_equal_authenticated_payload() -> None:
    """T48: a carried payload differing from the authenticated envelope payload refuses."""
    parts = formula_bundle_parts()
    mutant = replace(parts.bundle, vcert_payload=b"{}")
    with pytest.raises(ArchiveIntegrityError, match="differs from the authenticated"):
        archive_module._validate_plot_bundle(mutant, DEFAULT_LIMITS)


def test_t49_formula_defensive_keyid_and_canonical_payload_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T49: both post-verification defensive re-checks refuse when forced apart."""
    parts = formula_bundle_parts()
    monkeypatch.setattr(archive_module, "keyid_for_public_key", lambda _key: "sha256:" + "0" * 64)
    with pytest.raises(ArchiveIntegrityError, match="keyid does not address"):
        archive_module._validate_plot_bundle(parts.bundle, DEFAULT_LIMITS)

    monkeypatch.setattr(archive_module, "keyid_for_public_key", lambda _key: parts.bundle.keyid)
    monkeypatch.setattr(vcert, "vcert_v03_bytes", lambda _certificate: b"{}")
    with pytest.raises(ArchiveIntegrityError, match="not in the canonical deterministic JSON form"):
        archive_module._validate_plot_bundle(parts.bundle, DEFAULT_LIMITS)


def test_t50_mixed_certificate_family_is_unconstructible_and_undecodable() -> None:
    """T50: no single-member family cross survives construction or decoding.

    The archive's three-way narrowing in `_authenticated_formula_bundle_certificate` is redundant
    by design: `VCertV03` already correlates source/artifact/TCB, so only the whole-family swap of
    T14 can reach that check and neutering any one conjunct alone is unobservable. This pins the
    upstream invariant that redundancy leans on, on both the construct and the decode path.
    """
    parts = formula_bundle_parts()
    dataset = dataset_v03_certificate()
    crossings = (
        ("source", dataset.source),
        ("artifact", dataset.artifact),
        ("tcb", dataset.tcb),
    )
    for member, dataset_value in crossings:
        assert type(dataset_value) is not type(getattr(parts.certificate, member))
        with pytest.raises(ValueError, match="do not correlate"):
            struct_replace(parts.certificate, **{member: dataset_value})

    encoder = msgspec.json.Encoder(order="deterministic")
    decoder = msgspec.json.Decoder(vcert.VCertV03, strict=True)
    formula_fields = msgspec.json.decode(vcert.vcert_v03_bytes(parts.certificate))
    dataset_fields = msgspec.json.decode(vcert.vcert_v03_bytes(dataset))
    assert decoder.decode(encoder.encode(formula_fields)) == parts.certificate
    for member, _ in crossings:
        mixed = dict(formula_fields)
        mixed[member] = dataset_fields[member]
        with pytest.raises(msgspec.ValidationError, match="do not correlate"):
            decoder.decode(encoder.encode(mixed))
