# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9.10 formula service route: diff-blind contract matrix."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import fields
from pathlib import Path
from types import ModuleType
from typing import Any, cast, get_args

import msgspec
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from httpx import Response
from litestar import Litestar
from litestar.testing import TestClient

from verifier import attestation, checks, formal, matplotlib_script, vcert
from verifier import eval as eval_module
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import decode_formula_spec
from verifier.service import archive as archive_module
from verifier.service import pipeline as pipeline_module
from verifier.service.app import create_app
from verifier.service.archive import (
    Archive,
    AttemptBundle,
    AttemptDraft,
    AttemptOutcome,
    AttemptRoute,
    FormulaPlotBundle,
    open_archive,
)
from verifier.service.identity import Signer
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_ROOT = Path(__file__).resolve().parent.parent
_FORMULA_GOOD = _ROOT / "examples" / "formula_good_specs"
_JSON = {"content-type": "application/json"}
_SUCCESS_FIELDS = (
    "verified",
    "layer",
    "results",
    "attempt_id",
    "plot_id",
    "spec_id",
    "formula_hash",
    "spec_hash",
    "plotted_table_hash",
    "matplotlib_script_hash",
    "matplotlib_script",
)
_FORMULA_ROLES = {
    "canonical_spec",
    "formula_source",
    "plotted_table",
    "verdict",
    "matplotlib_script",
    "vcert_payload",
    "tool_versions",
}
_F02_HASHES = (
    "sha256:52d3251ec5400841d5d15e2713b78afe3a3797f5b6157bae64e0246f8a05112b",
    "sha256:bdd49020bdc67a7b90d6f692c237d705771b1ce92b1604600cfb326aebdf878c",
    "sha256:6f91870059e56d4734ba7edf4a899e8029e30549af081906fbcee5e600be4b38",
    "sha256:8861069e6a140ecd4bca9c8d85873477f9d50408f9f0c13ad350a7e640be7cd9",
)
_F06_HASHES = (
    "sha256:18d3d190c5cba54253a3ac479e6776f0336e7b97d5459fb052daab713349864d",
    "sha256:11191ef90c7c4ad3a2d73ac55f0402bc42e178620de046c873afef18be382945",
    "sha256:d9a420de65fcbbbbdc944b0c9f94730723dd229f49cf040563ed22c88d536865",
    "sha256:03c7cd2d5406c068eecd8f6e3658cc9b99a09772c4425c5e3e897c8e15a77974",
)


def _settings(tmp_path: Path, **changes: object) -> Settings:
    # Parametrized rows pass a per-case subdirectory of tmp_path, which pytest never created.
    # Identity requires the state directory's PARENT to already be a no-follow directory, so
    # create it here rather than at every call site.
    tmp_path.mkdir(parents=True, exist_ok=True)
    constructor = cast("Any", Settings)
    return cast(
        "Settings",
        constructor(data_dir=_ROOT / "data", state_dir=tmp_path / "state", **changes),
    )


def _raw_formula_post(
    tmp_path: Path, raw: bytes, **settings_changes: object
) -> tuple[Settings, Litestar, Response]:
    settings = _settings(tmp_path, **settings_changes)
    app = create_app(settings)
    with TestClient(app=app) as client:
        response = client.post("/verify-formula", content=raw, headers=_JSON)
    return settings, app, response


def _formula_post(
    tmp_path: Path, filename: str = "f02_linear.json"
) -> tuple[Settings, Litestar, bytes, Response]:
    raw = (_FORMULA_GOOD / filename).read_bytes()
    settings, app, response = _raw_formula_post(tmp_path, raw)
    return settings, app, raw, response


def _capture_attempt_drafts(monkeypatch: pytest.MonkeyPatch) -> list[AttemptDraft]:
    drafts: list[AttemptDraft] = []
    original = Archive.record_attempt

    def observed(
        archive: Archive,
        draft: AttemptDraft,
        signer: Signer,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> AttemptBundle:
        drafts.append(draft)
        return original(archive, draft, signer, limits=limits)

    monkeypatch.setattr(Archive, "record_attempt", observed)
    return drafts


def _success(response: Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    payload = cast("dict[str, Any]", response.json())
    assert tuple(payload) == _SUCCESS_FIELDS
    assert payload["verified"] is True
    assert payload["layer"] == "verify"
    return payload


type _RejectedRun = tuple[Settings, Litestar, bytes, Response, list[AttemptDraft]]


def _assert_rejected_attempt(
    run: _RejectedRun,
    *,
    layer: str,
    check: str,
    message: str | None = None,
) -> dict[str, Any]:
    settings, app, raw, response, drafts = run
    assert response.status_code == 200, response.text
    payload = cast("dict[str, Any]", response.json())
    assert tuple(payload) == ("verified", "layer", "results", "attempt_id")
    assert payload["verified"] is False
    assert payload["layer"] == layer
    results = cast("list[dict[str, Any]]", payload["results"])
    final = results[-1]
    assert final["check"] == check
    assert final["status"] == "fail"
    assert final["severity"] == "blocking"
    if message is not None:
        assert final["message"] == message
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.route is AttemptRoute.VERIFY_FORMULA
    assert draft.outcome is AttemptOutcome.REJECTED
    assert draft.http_status == 200
    assert draft.plot is None
    assert draft.artifacts.raw_spec == raw
    assert draft.artifacts.raw_csv is None
    assert draft.artifacts.raw_manifest is None
    assert draft.artifacts.model_request is None
    assert draft.artifacts.model_response is None
    assert draft.artifacts.model_reply is None
    attempt = _archive(app).read_attempt(
        cast("str", payload["attempt_id"]),
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    assert attempt.manifest.outcome is AttemptOutcome.REJECTED
    assert attempt.plot is None
    return payload


def _archive(app: Litestar) -> Archive:
    return cast("Archive", app.state["archive"])


def _formula_plot(
    archive: Archive, settings: Settings, payload: dict[str, Any]
) -> FormulaPlotBundle:
    plot = archive.read_plot(
        cast("str", payload["plot_id"]),
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    assert type(plot) is FormulaPlotBundle
    return plot


def _verified_formula_certificate(
    archive: Archive, settings: Settings, plot: FormulaPlotBundle
) -> tuple[bytes, vcert.VCertV03]:
    envelope = archive.read_certificate(
        plot.plot_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    public_key_bytes = archive.read_key(plot.keyid, max_bytes=32)
    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    verified = attestation.verify_vcert_v03(
        envelope,
        {plot.keyid: public_key},
        limits=settings.limits,
        require_canonical_envelope=True,
        expected_keyid_hint=plot.keyid,
    )
    return envelope, verified.certificate


def _assert_authenticated_hashes(
    payload: dict[str, Any], certificate: vcert.VCertV03, expected: tuple[str, str, str, str]
) -> None:
    assert type(certificate.source) is vcert.FormulaSourceCert
    assert type(certificate.artifact) is vcert.MatplotlibScriptArtifactCert
    source = certificate.source
    artifact = certificate.artifact
    actual = (
        cast("str", payload["formula_hash"]),
        cast("str", payload["spec_hash"]),
        cast("str", payload["plotted_table_hash"]),
        cast("str", payload["matplotlib_script_hash"]),
    )
    assert actual == expected
    assert actual == (
        source.formula_hash,
        certificate.spec_hash,
        certificate.plotted_table_hash,
        artifact.matplotlib_script_hash,
    )
    assert tuple(name for name in payload if name.endswith("_hash")) == (
        "formula_hash",
        "spec_hash",
        "plotted_table_hash",
        "matplotlib_script_hash",
    )


def test_v01_line_success_has_exact_shape_and_golden_script(tmp_path: Path) -> None:
    _settings, _app, _raw, response = _formula_post(tmp_path)
    payload = _success(response)

    script = cast("str", payload["matplotlib_script"]).encode()
    assert len(script) == 483
    assert payload["matplotlib_script_hash"] == _F02_HASHES[-1]


def test_v02_scatter_success_has_exact_shape_and_golden_script(tmp_path: Path) -> None:
    _settings, _app, _raw, response = _formula_post(tmp_path, "f06_quadratic.json")
    payload = _success(response)

    script = cast("str", payload["matplotlib_script"]).encode()
    assert len(script) == 438
    assert payload["matplotlib_script_hash"] == _F06_HASHES[-1]


def test_v03_f02_hashes_are_the_authenticated_v03_bindings(tmp_path: Path) -> None:
    settings, app, _raw, response = _formula_post(tmp_path)
    payload = _success(response)
    archive = _archive(app)
    plot = _formula_plot(archive, settings, payload)
    _envelope, certificate = _verified_formula_certificate(archive, settings, plot)

    _assert_authenticated_hashes(payload, certificate, _F02_HASHES)


def test_v04_f06_hashes_are_the_authenticated_v03_bindings(tmp_path: Path) -> None:
    settings, app, _raw, response = _formula_post(tmp_path, "f06_quadratic.json")
    payload = _success(response)
    archive = _archive(app)
    plot = _formula_plot(archive, settings, payload)
    _envelope, certificate = _verified_formula_certificate(archive, settings, plot)

    _assert_authenticated_hashes(payload, certificate, _F06_HASHES)


def test_v05_addresses_bind_exact_bytes_and_commit_precedes_model_construction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(data_dir=_ROOT / "data", state_dir=tmp_path / "state")
    app = create_app(settings)
    archive = _archive(app)
    model: object = pipeline_module.__dict__.get("FormulaScriptVerdict")
    assert callable(model), "FormulaScriptVerdict is absent from the formula pipeline"
    constructor = cast("Callable[..., object]", model)
    construction_calls = 0

    def observed_constructor(**kwargs: object) -> object:
        nonlocal construction_calls
        construction_calls += 1
        attempt_id = cast("str", kwargs["attempt_id"])
        archive.read_attempt(
            attempt_id,
            max_bytes=settings.max_archive_bytes,
            limits=settings.limits,
        )
        return constructor(**kwargs)

    monkeypatch.setattr(pipeline_module, "FormulaScriptVerdict", observed_constructor)
    raw = (_FORMULA_GOOD / "f02_linear.json").read_bytes()
    with TestClient(app=app) as client:
        response = client.post("/verify-formula", content=raw, headers=_JSON)
    payload = _success(response)
    plot = _formula_plot(archive, settings, payload)
    envelope, _certificate = _verified_formula_certificate(archive, settings, plot)
    attempt = archive.read_attempt(
        cast("str", payload["attempt_id"]),
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )

    assert construction_calls == 1
    assert payload["plot_id"] == hashlib.sha256(envelope).hexdigest()
    assert payload["spec_id"] == cast("str", payload["spec_hash"]).removeprefix("sha256:")
    assert payload["attempt_id"] == hashlib.sha256(attempt.attempt_envelope).hexdigest()
    assert cast("str", payload["matplotlib_script"]).encode() == plot.matplotlib_script


def test_v06_formula_plot_restarts_with_exact_reference_topology(tmp_path: Path) -> None:
    settings, app, _raw, response = _formula_post(tmp_path)
    payload = _success(response)
    first = _formula_plot(_archive(app), settings, payload)
    restarted = _formula_plot(open_archive(settings), settings, payload)
    with sqlite3.connect(settings.state_dir / "archive.sqlite3") as connection:
        rows = connection.execute(
            "SELECT role FROM plot_references WHERE plot_id = ? ORDER BY role",
            (first.plot_id,),
        ).fetchall()

    assert restarted == first
    assert len(rows) == 7
    assert {cast("str", row[0]) for row in rows} == _FORMULA_ROLES
    assert not hasattr(restarted, "raw_csv")
    assert not hasattr(restarted, "raw_manifest")
    assert not hasattr(restarted, "vega_lite")
    assert not hasattr(restarted, "svg")


def test_v07_formula_certificate_restarts_and_authenticates(tmp_path: Path) -> None:
    settings, _app, _raw, response = _formula_post(tmp_path)
    payload = _success(response)
    archive = open_archive(settings)
    plot = _formula_plot(archive, settings, payload)
    envelope, certificate = _verified_formula_certificate(archive, settings, plot)

    assert envelope == plot.vcert_envelope
    assert hashlib.sha256(envelope).hexdigest() == plot.plot_id
    _assert_authenticated_hashes(payload, certificate, _F02_HASHES)


def test_v08_nested_verified_attempt_restarts_without_dataset_bytes(tmp_path: Path) -> None:
    settings, _app, raw, response = _formula_post(tmp_path)
    payload = _success(response)
    archive = open_archive(settings)
    attempt = archive.read_attempt(
        cast("str", payload["attempt_id"]),
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    plot = _formula_plot(archive, settings, payload)

    assert attempt.manifest.route is AttemptRoute.VERIFY_FORMULA
    assert attempt.manifest.outcome is AttemptOutcome.VERIFIED
    assert attempt.manifest.http_status == 200
    assert type(attempt.plot) is FormulaPlotBundle
    assert attempt.plot == plot
    assert attempt.artifacts.raw_spec == raw
    assert attempt.artifacts.raw_csv is None
    assert attempt.artifacts.raw_manifest is None
    assert attempt.artifacts.verdict is not None


def test_v09_service_outcomes_are_a_closed_concrete_union(tmp_path: Path) -> None:
    dataset_type: object = pipeline_module.__dict__.get("DatasetOutcome")
    formula_type: object = pipeline_module.__dict__.get("FormulaOutcome")
    outcome_alias: object = pipeline_module.__dict__.get("Outcome")
    assert isinstance(dataset_type, type), "DatasetOutcome is absent"
    assert isinstance(formula_type, type), "FormulaOutcome is absent"
    assert outcome_alias is not None
    alias_value = getattr(outcome_alias, "__value__", outcome_alias)

    assert get_args(alias_value) == (dataset_type, formula_type)
    expected_fields = ("verdict", "spec", "trace", "evidence", "formal_trace", "prepared")
    assert tuple(item.name for item in fields(dataset_type)) == expected_fields
    assert tuple(item.name for item in fields(formula_type)) == expected_fields
    raw = (_ROOT / "examples" / "good_specs" / "g01_total_revenue_by_month.json").read_bytes()
    dataset = pipeline_module.verify_only(raw, _settings(tmp_path))
    assert type(dataset) is dataset_type
    assert not isinstance(outcome_alias, type)


def test_v10_malformed_json_commits_one_decode_rejection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = b"{"
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(tmp_path, raw)

    payload = _assert_rejected_attempt(
        (settings, app, raw, response, drafts),
        layer="decode",
        check="spec.decode",
        message="Input data was truncated",
    )
    result = cast("list[dict[str, Any]]", payload["results"])[0]
    assert result["method"] == "schema_validation"


def test_v11_wrong_version_commits_one_decode_rejection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = (
        (_FORMULA_GOOD / "f02_linear.json")
        .read_bytes()
        .replace(b'"vplot-formula-0.1"', b'"vplot-formula-9.9"', 1)
    )
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(tmp_path, raw)

    _assert_rejected_attempt(
        (settings, app, raw, response, drafts),
        layer="decode",
        check="spec.decode",
        message="Invalid enum value 'vplot-formula-9.9' - at `$.version`",
    )


def test_v12_unknown_field_commits_one_decode_rejection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = cast("dict[str, Any]", json.loads((_FORMULA_GOOD / "f02_linear.json").read_bytes()))
    source["unexpected"] = 0
    raw = msgspec.json.encode(source)
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(tmp_path, raw)

    _assert_rejected_attempt(
        (settings, app, raw, response, drafts),
        layer="decode",
        check="spec.decode",
        message="Object contains unknown field `unexpected`",
    )


def test_v13_duplicate_key_reaches_the_raw_formula_decoder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = (
        (_FORMULA_GOOD / "f02_linear.json")
        .read_bytes()
        .replace(b'"mark":"line"', b'"mark":"line","mark":"scatter"', 1)
    )
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(tmp_path, raw)

    _assert_rejected_attempt(
        (settings, app, raw, response, drafts),
        layer="decode",
        check="spec.decode",
        message="duplicate object key: 'mark'",
    )


def test_v14_invalid_utf8_is_wrapped_by_the_public_formula_decoder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = (
        (_FORMULA_GOOD / "f02_linear.json")
        .read_bytes()
        .replace(b'"formula":"2*x + 1"', b'"formula":"2*x + \xff"', 1)
    )
    with pytest.raises(msgspec.DecodeError) as caught:
        decode_formula_spec(raw)
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(tmp_path, raw)

    _assert_rejected_attempt(
        (settings, app, raw, response, drafts),
        layer="decode",
        check="spec.decode",
        message="spec input is not valid UTF-8",
    )


def test_v15_dataset_spec_is_a_formula_decode_rejection_without_dataset_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = (_ROOT / "examples" / "good_specs" / "g01_total_revenue_by_month.json").read_bytes()
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(tmp_path, raw)

    _assert_rejected_attempt(
        (settings, app, raw, response, drafts),
        layer="decode",
        check="spec.decode",
        message="Invalid enum value 'vplot-0.1' - at `$.version`",
    )


def test_v16_core_semantic_failure_commits_no_formula_plot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = (_ROOT / "examples" / "formula_bad_specs" / "fb17_reversed_domain.json").read_bytes()
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(tmp_path, raw)

    payload = _assert_rejected_attempt(
        (settings, app, raw, response, drafts),
        layer="verify",
        check="formula.domain_ordered",
    )
    assert "matplotlib_script" not in payload


# Each stage is patched on the module that OWNS it. pipeline re-exports only prepare_formula and
# materialize_formula_plot_bundle; it reaches the other four through their modules, so patching
# pipeline for those would silently observe nothing. Patching the owner also counts a call made
# from anywhere, which is the stronger reading of these rows.
_PIPELINE_STAGE_OWNERS: tuple[tuple[str, ModuleType], ...] = (
    ("verify_formula_run", checks),
    ("prepare_formula", pipeline_module),
    ("emit_matplotlib_script", matplotlib_script),
    ("build_formula_certificate", vcert),
    ("sign_vcert_v03", attestation),
    ("materialize_formula_plot_bundle", pipeline_module),
)
_PIPELINE_STAGE_NAMES = tuple(name for name, _ in _PIPELINE_STAGE_OWNERS)
_STORE_METHOD_NAMES = ("put_chart", "chart")


def _formula_raw(*, formula: str | None = None, domain_stop: str | None = None) -> bytes:
    source = cast("dict[str, Any]", json.loads((_FORMULA_GOOD / "f02_linear.json").read_bytes()))
    if formula is not None:
        source["formula"] = formula
    if domain_stop is not None:
        domain = cast("dict[str, Any]", source["domain"])
        domain["stop"] = domain_stop
    return msgspec.json.encode(source)


def _observe_formula_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, int], dict[str, list[Any]], dict[str, int]]:
    calls = dict.fromkeys(_PIPELINE_STAGE_NAMES, 0)
    returned: dict[str, list[Any]] = {name: [] for name in _PIPELINE_STAGE_NAMES}
    for name, owner in _PIPELINE_STAGE_OWNERS:
        value: object = owner.__dict__.get(name)
        assert callable(value), f"formula stage {name} is absent from {owner.__name__}"
        original = cast("Callable[..., Any]", value)

        def observed(
            *args: Any,
            _name: str = name,
            _original: Callable[..., Any] = original,
            **kwargs: Any,
        ) -> Any:
            calls[_name] += 1
            result = _original(*args, **kwargs)
            returned[_name].append(result)
            return result

        monkeypatch.setattr(owner, name, observed)

    store_calls = dict.fromkeys(_STORE_METHOD_NAMES, 0)
    for name in _STORE_METHOD_NAMES:
        value = ArtifactStore.__dict__.get(name)
        assert callable(value)
        original = cast("Callable[..., Any]", value)

        def observed_store(
            *args: Any,
            _name: str = name,
            _original: Callable[..., Any] = original,
            **kwargs: Any,
        ) -> Any:
            store_calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(ArtifactStore, name, observed_store)
    return calls, returned, store_calls


def _formula_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw: bytes,
    expectation: tuple[str, str],
    settings_changes: dict[str, object] | None = None,
) -> tuple[dict[str, Any], dict[str, int], dict[str, list[Any]]]:
    check, method = expectation
    calls, returned, store_calls = _observe_formula_stages(monkeypatch)
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(
        tmp_path, raw, **({} if settings_changes is None else settings_changes)
    )
    payload = _assert_rejected_attempt(
        (settings, app, raw, response, drafts), layer="verify", check=check
    )
    result = cast("list[dict[str, Any]]", payload["results"])[-1]
    assert result["method"] == method
    assert "matplotlib_script" not in payload
    assert store_calls == {"put_chart": 0, "chart": 0}
    return payload, calls, returned


def test_v17_solver_unknown_preserves_trace_but_no_prepared_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(formal, "_check_solver", lambda _solver: "unknown")
    _payload, calls, returned = _formula_failure(
        monkeypatch,
        tmp_path,
        (_FORMULA_GOOD / "f02_linear.json").read_bytes(),
        ("formal.solver_completed", "z3_smt"),
    )

    assert calls["verify_formula_run"] == 1
    assert calls["prepare_formula"] == 1
    preparation = returned["prepare_formula"][0]
    assert preparation.prepared is None
    assert preparation.formal_trace[-1].result_class == "unknown"
    assert calls["emit_matplotlib_script"] == 0
    assert calls["build_formula_certificate"] == 0
    assert calls["sign_vcert_v03"] == 0
    assert calls["materialize_formula_plot_bundle"] == 0


def test_v18_float64_fidelity_failure_has_no_emitted_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _payload, calls, returned = _formula_failure(
        monkeypatch,
        tmp_path,
        _formula_raw(formula="9007199254740993"),
        ("render.float64_fidelity", "deterministic_recompute"),
    )

    assert calls["verify_formula_run"] == 1
    assert calls["prepare_formula"] == 1
    assert calls["emit_matplotlib_script"] == 1
    emission = returned["emit_matplotlib_script"][0]
    assert emission.artifact is None
    assert calls["build_formula_certificate"] == 0
    assert calls["sign_vcert_v03"] == 0
    assert calls["materialize_formula_plot_bundle"] == 0


@pytest.mark.parametrize(
    "row",
    (
        ("v19", "x  ", "max_formula_bytes", 2, "resource.formula_bytes"),
        ("v20", "-x**-2", "max_formula_tokens", 4, "resource.formula_tokens"),
        ("v21", "---x", "max_formula_ast_nodes", 3, "resource.formula_ast_nodes"),
        ("v22", "---x", "max_formula_ast_depth", 3, "resource.formula_ast_depth"),
    ),
)
def test_v19_v22_parser_resource_refusals_stop_before_formula_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    row: tuple[str, str, str, int, str],
) -> None:
    case, formula, setting, limit, check = row
    _payload, calls, _returned = _formula_failure(
        monkeypatch,
        tmp_path / case,
        _formula_raw(formula=formula),
        (check, "resource_policy"),
        {setting: limit},
    )

    assert calls["verify_formula_run"] == 1
    assert calls["prepare_formula"] == 0
    assert calls["emit_matplotlib_script"] == 0
    assert calls["build_formula_certificate"] == 0
    assert calls["sign_vcert_v03"] == 0
    assert calls["materialize_formula_plot_bundle"] == 0


def _observe_callable(
    monkeypatch: pytest.MonkeyPatch, owner: object, name: str
) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    value: object = getattr(owner, name, None)
    assert callable(value), f"callable {name} is absent"
    original = cast("Callable[..., Any]", value)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def observed(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, observed)
    return calls


@pytest.mark.parametrize(
    "row",
    (
        (
            "v23",
            "(((x)))",
            None,
            "max_formula_paren_depth",
            2,
            "resource.formula_paren_depth",
        ),
        ("v24", "999", None, "max_formula_digits", 2, "resource.formula_digits"),
        (
            "v25",
            "xx",
            None,
            "max_formula_identifier_bytes",
            1,
            "resource.formula_identifier_bytes",
        ),
        (
            "v26",
            None,
            None,
            "max_formula_samples",
            10,
            "resource.formula_samples",
        ),
        (
            "v27",
            None,
            None,
            "max_formula_work_units",
            1,
            "resource.formula_work",
        ),
        (
            "v28",
            "x",
            "8",
            "max_formula_intermediate_bits",
            3,
            "resource.formula_intermediate_bits",
        ),
    ),
)
def test_v23_v28_formula_resource_refusals_stop_before_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    row: tuple[str, str | None, str | None, str, int, str],
) -> None:
    case, formula, domain_stop, setting, limit, check = row
    parse_calls = _observe_callable(monkeypatch, eval_module, "parse_expr")
    _payload, calls, _returned = _formula_failure(
        monkeypatch,
        tmp_path / case,
        _formula_raw(formula=formula, domain_stop=domain_stop),
        (check, "resource_policy"),
        {setting: limit},
    )

    # v26 and v28 refuse before the parser runs: eval admits the domain endpoints as exact
    # fractions BEFORE it parses the formula, so a domain-side refusal never reaches parse_expr.
    assert len(parse_calls) == (0 if case in {"v26", "v28"} else 1)
    assert calls["verify_formula_run"] == 1
    assert calls["prepare_formula"] == 0
    assert calls["emit_matplotlib_script"] == 0
    assert calls["build_formula_certificate"] == 0
    assert calls["sign_vcert_v03"] == 0
    assert calls["materialize_formula_plot_bundle"] == 0


def _observe_returns(monkeypatch: pytest.MonkeyPatch, owner: object, name: str) -> list[Any]:
    value: object = getattr(owner, name, None)
    assert callable(value), f"callable {name} is absent"
    original = cast("Callable[..., Any]", value)
    returned: list[Any] = []

    def observed(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        returned.append(result)
        return result

    monkeypatch.setattr(owner, name, observed)
    return returned


@pytest.mark.parametrize(
    "row",
    (
        (
            "v29",
            "x**2",
            "max_formula_exponent",
            1,
            "formula.exponents_bounded",
            "schema_validation",
            0,
            0,
        ),
        (
            "v30",
            None,
            "max_plotted_cells",
            1,
            "resource.plotted_cells",
            "resource_policy",
            0,
            0,
        ),
        (
            "v31",
            None,
            "max_render_rows",
            10,
            "resource.render_rows",
            "resource_policy",
            1,
            0,
        ),
        (
            "v32",
            None,
            "max_smt_terms",
            1,
            "resource.smt_terms",
            "resource_policy",
            1,
            0,
        ),
        (
            "v33",
            None,
            "max_matplotlib_script_bytes",
            482,
            "resource.matplotlib_script_bytes",
            "resource_policy",
            1,
            1,
        ),
    ),
)
def test_v29_v33_late_formula_refusals_preserve_exact_stage_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    row: tuple[str, str | None, str, int, str, str, int, int],
) -> None:
    case, formula, setting, limit, check, method, prepare_calls, emit_calls = row
    rendered = _observe_returns(monkeypatch, matplotlib_script, "_render_script")
    solver_calls = _observe_callable(monkeypatch, formal, "_new_solver")
    _payload, calls, _returned = _formula_failure(
        monkeypatch,
        tmp_path / case,
        _formula_raw(formula=formula),
        (check, method),
        {setting: limit},
    )

    assert calls["verify_formula_run"] == 1
    assert calls["prepare_formula"] == prepare_calls
    assert calls["emit_matplotlib_script"] == emit_calls
    assert calls["build_formula_certificate"] == 0
    assert calls["sign_vcert_v03"] == 0
    assert calls["materialize_formula_plot_bundle"] == 0
    if case == "v32":
        assert solver_calls == []
    if case == "v33":
        assert len(rendered) == 1
        assert type(rendered[0]) is bytes
        assert len(rendered[0]) == 483


def _install_v03_signature_counter(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Record every v0.3 DSSE envelope the service actually produces.

    Substituting a duck-typed private key does NOT work here: _sign_dsse type-guards the key with
    a TypeError before it reaches the byte ceiling, so a stub key masks the ceiling refusal under
    a 500. Wrap the signing seam instead, and append only on SUCCESSFUL return, so a refused
    signature leaves the list empty and the emptiness means what the row claims it means.
    """
    signed_v03: list[bytes] = []
    # The byte ceiling lives below the public wrapper, so this is the only seam that sees it.
    original = attestation._sign_dsse

    def observed(payload: bytes, private_key: Any, *, keyid: str, profile: Any) -> bytes:
        envelope = original(payload, private_key, keyid=keyid, profile=profile)
        if profile.payload_type == attestation.VCERT_V03_PAYLOAD_TYPE:
            signed_v03.append(envelope)
        return envelope

    monkeypatch.setattr(attestation, "_sign_dsse", observed)
    return signed_v03


def _assert_problem(response: Response, status: int, detail: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    payload = cast("dict[str, Any]", response.json())
    assert payload["status"] == status
    assert payload["detail"] == detail
    assert "matplotlib_script" not in payload
    return payload


def test_v34_attestation_ceiling_stages_formula_refusal_and_low_cap_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = (_FORMULA_GOOD / "f02_linear.json").read_bytes()
    with monkeypatch.context() as cap_patch:
        calls, _returned, store_calls = _observe_formula_stages(cap_patch)
        drafts = _capture_attempt_drafts(cap_patch)
        settings = _settings(tmp_path / "cap-1801", max_attestation_bytes=1801)
        app = create_app(settings)
        private_v03_signs = _install_v03_signature_counter(cap_patch)
        with TestClient(app=app) as client:
            response = client.post("/verify-formula", content=raw, headers=_JSON)
        payload = _assert_rejected_attempt(
            (settings, app, raw, response, drafts),
            layer="verify",
            check="resource.attestation_bytes",
        )
        result = cast("list[dict[str, Any]]", payload["results"])[-1]
        assert result["method"] == "resource_policy"
        assert calls["build_formula_certificate"] == 1
        assert calls["sign_vcert_v03"] == 1
        assert private_v03_signs == []
        assert calls["materialize_formula_plot_bundle"] == 0
        assert store_calls == {"put_chart": 0, "chart": 0}

    with monkeypatch.context() as low_patch:
        calls, _returned, store_calls = _observe_formula_stages(low_patch)
        settings = _settings(tmp_path / "cap-100", max_attestation_bytes=100)
        app = create_app(settings)
        with TestClient(app=app) as client:
            response = client.post("/verify-formula", content=raw, headers=_JSON)
        problem = _assert_problem(response, 500, "the verifier encountered an internal error")
        assert "attempt_id" not in problem
        assert calls["build_formula_certificate"] == 1
        assert calls["sign_vcert_v03"] == 1
        assert calls["materialize_formula_plot_bundle"] == 0
        stats = _archive(app).stats()
        assert stats.attempts == 0
        assert stats.plots == 0
        assert store_calls == {"put_chart": 0, "chart": 0}

    dataset_settings = _settings(tmp_path / "dataset-cap-100", max_attestation_bytes=100)
    dataset_app = create_app(dataset_settings)
    dataset_raw = (
        _ROOT / "examples" / "good_specs" / "g01_total_revenue_by_month.json"
    ).read_bytes()
    with TestClient(app=dataset_app) as client:
        response = client.post("/verify-and-render", content=dataset_raw, headers=_JSON)
    problem = _assert_problem(response, 500, "the verifier encountered an internal error")
    assert "attempt_id" not in problem
    assert _archive(dataset_app).stats().attempts == 0


@pytest.mark.parametrize(
    "row",
    (
        (
            "core",
            (_ROOT / "examples/formula_bad_specs/fb17_reversed_domain.json").read_bytes(),
            {},
            False,
            0,
            0,
            0,
            0,
        ),
        (
            "script",
            (_FORMULA_GOOD / "f02_linear.json").read_bytes(),
            {"max_matplotlib_script_bytes": 482},
            False,
            0,
            0,
            0,
            0,
        ),
        (
            "attestation",
            (_FORMULA_GOOD / "f02_linear.json").read_bytes(),
            {"max_attestation_bytes": 1801},
            False,
            1,
            1,
            0,
            0,
        ),
        (
            "success",
            (_FORMULA_GOOD / "f02_linear.json").read_bytes(),
            {},
            True,
            1,
            1,
            1,
            1,
        ),
    ),
)
def test_v35_failure_family_matrix_and_success_nested_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    row: tuple[str, bytes, dict[str, object], bool, int, int, int, int],
) -> None:
    case, raw, changes, verified, build, sign, materialize, nested = row
    calls, _returned, store_calls = _observe_formula_stages(monkeypatch)
    nested_calls = _observe_callable(monkeypatch, archive_module, "_plot_bundle_batch")
    drafts = _capture_attempt_drafts(monkeypatch)
    settings, app, response = _raw_formula_post(tmp_path / case, raw, **changes)
    assert response.status_code == 200, response.text
    payload = cast("dict[str, Any]", response.json())
    assert payload["verified"] is verified
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.outcome is (AttemptOutcome.VERIFIED if verified else AttemptOutcome.REJECTED)
    assert (type(draft.plot) is FormulaPlotBundle) is verified
    assert calls["build_formula_certificate"] == build
    assert calls["sign_vcert_v03"] == sign
    assert calls["materialize_formula_plot_bundle"] == materialize
    assert len(nested_calls) == nested
    assert store_calls == {"put_chart": 0, "chart": 0}
    attempt = _archive(app).read_attempt(
        cast("str", payload["attempt_id"]),
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    assert (type(attempt.plot) is FormulaPlotBundle) is verified


def test_v36_only_verified_200_archives_or_returns_a_formula_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = (_FORMULA_GOOD / "f02_linear.json").read_bytes()
    with monkeypatch.context() as failure_patch:
        calls, _returned, _store_calls = _observe_formula_stages(failure_patch)
        drafts = _capture_attempt_drafts(failure_patch)
        settings, app, response = _raw_formula_post(
            tmp_path / "verdict", raw, max_matplotlib_script_bytes=482
        )
        payload = _assert_rejected_attempt(
            (settings, app, raw, response, drafts),
            layer="verify",
            check="resource.matplotlib_script_bytes",
        )
        assert calls["sign_vcert_v03"] == 0
        assert "matplotlib_script" not in payload
        assert _archive(app).stats().plots == 0

    with monkeypatch.context() as quota_patch:
        calls, _returned, store_calls = _observe_formula_stages(quota_patch)
        drafts = _capture_attempt_drafts(quota_patch)
        settings = _settings(tmp_path / "quota", max_archive_bytes=1)
        app = create_app(settings)
        with TestClient(app=app) as client:
            response = client.post("/verify-formula", content=raw, headers=_JSON)
        problem = _assert_problem(
            response,
            507,
            "the provenance archive has insufficient logical storage capacity",
        )
        assert "attempt_id" not in problem
        assert calls["sign_vcert_v03"] == 1
        assert len(drafts) == 1
        assert drafts[0].outcome is AttemptOutcome.VERIFIED
        assert type(drafts[0].plot) is FormulaPlotBundle
        stats = _archive(app).stats()
        assert stats.attempts == 0 and stats.plots == 0
        assert store_calls == {"put_chart": 0, "chart": 0}

    def fail_commit() -> None:
        message = "injected pre-commit fault"
        raise RuntimeError(message)

    with monkeypatch.context() as fault_patch:
        _calls, _returned, store_calls = _observe_formula_stages(fault_patch)
        fault_patch.setattr(archive_module, "_before_archive_commit", fail_commit)
        settings = _settings(tmp_path / "fault")
        app = create_app(settings)
        with TestClient(app=app) as client:
            response = client.post("/verify-formula", content=raw, headers=_JSON)
        problem = _assert_problem(response, 500, "the verifier encountered an internal error")
        assert "attempt_id" not in problem
        stats = _archive(app).stats()
        assert stats.attempts == 0 and stats.plots == 0
        assert store_calls == {"put_chart": 0, "chart": 0}


def test_v37_formula_context_has_no_store_and_success_never_calls_chart_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context_type: object = pipeline_module.__dict__.get("FormulaContext")
    assert isinstance(context_type, type), "FormulaContext is absent"
    assert "store" not in {item.name for item in fields(context_type)}
    calls, _returned, store_calls = _observe_formula_stages(monkeypatch)
    drafts = _capture_attempt_drafts(monkeypatch)
    raw = (_FORMULA_GOOD / "f02_linear.json").read_bytes()
    settings, app, response = _raw_formula_post(tmp_path, raw)
    payload = _success(response)

    assert calls["materialize_formula_plot_bundle"] == 1
    assert len(drafts) == 1
    assert drafts[0].outcome is AttemptOutcome.VERIFIED
    assert type(drafts[0].plot) is FormulaPlotBundle
    assert store_calls == {"put_chart": 0, "chart": 0}
    assert _formula_plot(_archive(app), settings, payload) == drafts[0].plot


def _transport_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[
    Litestar,
    dict[str, int],
    list[AttemptDraft],
    dict[str, int],
    list[tuple[tuple[Any, ...], dict[str, Any]]],
]:
    calls, _returned, store_calls = _observe_formula_stages(monkeypatch)
    drafts = _capture_attempt_drafts(monkeypatch)
    app = create_app(_settings(tmp_path, max_body_bytes=64))
    admission_calls = _observe_callable(monkeypatch, type(app.state["admission"]), "try_acquire")
    return app, calls, drafts, store_calls, admission_calls


def _assert_transport_did_no_work(
    calls: dict[str, int],
    drafts: list[AttemptDraft],
    store_calls: dict[str, int],
    admission_calls: list[tuple[tuple[Any, ...], dict[str, Any]]],
) -> None:
    assert all(calls[name] == 0 for name in _PIPELINE_STAGE_NAMES)
    assert admission_calls == []
    assert drafts == []
    assert store_calls == {"put_chart": 0, "chart": 0}


def test_v38_wrong_content_type_refuses_before_body_admission_or_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app, calls, drafts, store_calls, admission_calls = _transport_probe(monkeypatch, tmp_path)
    with TestClient(app=app) as client:
        response = client.post(
            "/verify-formula", content=b"not read", headers={"content-type": "text/plain"}
        )
    payload = _assert_problem(
        response,
        415,
        "Content-Type must be application/json, got 'text/plain'",
    )
    assert "attempt_id" not in payload
    _assert_transport_did_no_work(calls, drafts, store_calls, admission_calls)


def test_v39_content_length_body_cap_refuses_before_formula_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app, calls, drafts, store_calls, admission_calls = _transport_probe(monkeypatch, tmp_path)
    with TestClient(app=app) as client:
        response = client.post(
            "/verify-formula",
            content=b"x" * 65,
            headers={**_JSON, "content-length": "65"},
        )
    payload = _assert_problem(response, 413, cast("str", response.json()["detail"]))
    assert "attempt_id" not in payload
    _assert_transport_did_no_work(calls, drafts, store_calls, admission_calls)


def test_v40_chunked_body_cap_matches_content_length_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app, calls, drafts, store_calls, admission_calls = _transport_probe(monkeypatch, tmp_path)

    def chunks() -> Iterator[bytes]:
        yield b"x" * 32
        yield b"x" * 33

    with TestClient(app=app) as client:
        chunked = client.post("/verify-formula", content=chunks(), headers=_JSON)
        fixed = client.post(
            "/verify-formula",
            content=b"x" * 65,
            headers={**_JSON, "content-length": "65"},
        )
    _assert_problem(chunked, 413, cast("str", fixed.json()["detail"]))
    assert chunked.content == fixed.content
    _assert_transport_did_no_work(calls, drafts, store_calls, admission_calls)
