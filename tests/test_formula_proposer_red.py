# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Diff-blind red suite for M9.12 steps 4-5: route vocabulary, occurrence identity, fault matrix.

Every test here is written against `.scratch/agents/contract-m9u12.md` and
`.scratch/agents/rulings-m9u12.md` ALONE, never against MAIN's implementation. A test that passes
before MAIN implements the step is a defective test: it pins something that already held.

IMPORT RULE, load-bearing: module-level imports may name ONLY symbols that exist at `main`.
Anything M9.12 adds (`AttemptRoute.PROPOSE_FORMULA`, `propose_formula`, `/propose-formula`,
`ProposeFormulaRequest`, ...) must be imported INSIDE the test body. A module-level import of an
unbuilt symbol turns the whole file into one collection ERROR and hides every other red test.

Replace each placeholder body with its real assertions. MAIN polls
`rg -c unwritten tests/test_formula_proposer_red.py`, which must fall from 29 to 0.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast, get_args
from unittest.mock import AsyncMock

import httpx
import msgspec
import pytest
from litestar.testing import TestClient

from verifier import replay, schema
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.service import app as service_app
from verifier.service import archive as archive_module
from verifier.service import model_client
from verifier.service import pipeline as pipeline_module
from verifier.service import replay as service_replay
from verifier.service.archive import (
    Archive,
    ArchiveIntegrityError,
    ArchiveNotFoundError,
    AttemptArtifacts,
    AttemptBundle,
    AttemptDraft,
    AttemptManifest,
    AttemptOutcome,
    AttemptRoute,
    FormulaPlotBundle,
    PlotSourceKind,
    open_archive,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.model_client import ModelProposal, ProposalFault, ProposalTrace
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_FORMULA_GOOD = _ROOT / "examples" / "formula_good_specs"
_FORMULA_BAD = _ROOT / "examples" / "formula_bad_specs"
_JSON = {"content-type": "application/json"}
_MODEL_REQUEST = b'{"messages":[{"role":"user","content":"private formula request"}]}'
_MODEL_FIELDS = ("model_request", "model_response", "model_reply")
_CHART_FIELDS = {"html", "svg", "vega_lite"}


@dataclass(frozen=True, slots=True, kw_only=True)
class _FormulaInput:
    proposal: ModelProposal | None = None
    error: Exception | None = None
    backend_handler: Callable[[httpx.Request], httpx.Response] | None = None
    user_request: str = "Plot a formula"
    settings_changes: dict[str, object] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class _FormulaRun:
    settings: Settings
    response: httpx.Response
    constructed: tuple[str, ...]
    chart_calls: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class _CellExpectation:
    status: int
    outcome: AttemptOutcome
    model_roles: frozenset[str]
    raw_spec: bytes | None
    model_reply: bytes | None
    plot: bool


def _settings(tmp_path: Path, **changes: object) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    constructor = cast("Any", Settings)
    return cast(
        "Settings",
        constructor(data_dir=_DATA, state_dir=tmp_path / "state", **changes),
    )


def _proposal(reply: bytes) -> ModelProposal:
    response = msgspec.json.encode({"choices": [{"message": {"content": reply.decode("utf-8")}}]})
    trace = ProposalTrace(
        request_body=_MODEL_REQUEST,
        response_body=response,
        reply_bytes=reply,
        fault=None,
    )
    return ModelProposal(reply, trace)


class _RawStream(httpx.AsyncByteStream):
    """Hand the client bytes exactly as given, so a declared encoding survives the transport."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._content


def _install_backend(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    class Stream(httpx.AsyncByteStream):
        def __init__(self, content: bytes) -> None:
            self._content = content

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield self._content

    def stream_handler(request: httpx.Request) -> httpx.Response:
        response = handler(request)
        if not response.is_stream_consumed:
            return response
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=Stream(response.content),
        )

    def build(settings: Settings) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(stream_handler),
            timeout=settings.model_timeout,
        )

    monkeypatch.setattr(model_client, "_build_async_client", build)


def _json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        return {
            *(key for key in mapping if isinstance(key, str)),
            *(key for child in mapping.values() for key in _json_keys(child)),
        }
    if isinstance(value, list):
        return {key for child in cast("list[object]", value) for key in _json_keys(child)}
    return set()


def _observe_commit_before_response(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> list[str]:
    committed: list[str] = []
    constructed: list[str] = []
    original_record = Archive.record_attempt

    def observed_record(
        archive: Archive,
        draft: AttemptDraft,
        signer: Signer,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> AttemptBundle:
        bundle = original_record(archive, draft, signer, limits=limits)
        committed.append(bundle.attempt_id)
        return bundle

    monkeypatch.setattr(Archive, "record_attempt", observed_record)

    def require_committed(attempt_id: str) -> None:
        assert attempt_id in committed
        open_archive(settings).read_attempt(
            attempt_id,
            max_bytes=settings.max_archive_bytes,
            limits=settings.limits,
        )

    original_problem = service_app._problem_response

    def observed_problem(
        status: int,
        detail: str,
        *,
        attempt_id: str | None = None,
    ) -> object:
        if attempt_id is not None:
            require_committed(attempt_id)
            constructed.append("problem")
        return original_problem(status, detail, attempt_id=attempt_id)

    monkeypatch.setattr(service_app, "_problem_response", observed_problem)
    result_type = service_app.__dict__.get("ProposeFormulaResult")
    if callable(result_type):
        constructor = cast("Callable[..., object]", result_type)

        def observed_result(*args: object, **kwargs: object) -> object:
            verdict = kwargs.get("verdict", args[1] if len(args) > 1 else None)
            attempt_id = getattr(verdict, "attempt_id", None)
            assert isinstance(attempt_id, str)
            require_committed(attempt_id)
            constructed.append("result")
            return constructor(*args, **kwargs)

        monkeypatch.setattr(service_app, "ProposeFormulaResult", observed_result)
    return constructed


def _run_formula_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: _FormulaInput | None = None,
) -> _FormulaRun:
    case = _FormulaInput() if case is None else case
    if case.proposal is not None:
        monkeypatch.setattr(
            service_app,
            "propose_formula",
            AsyncMock(return_value=case.proposal),
            raising=False,
        )
    if case.error is not None:
        monkeypatch.setattr(
            service_app,
            "propose_formula",
            AsyncMock(side_effect=case.error),
            raising=False,
        )
    if case.backend_handler is not None:
        _install_backend(monkeypatch, case.backend_handler)
    settings = _settings(
        tmp_path,
        **({} if case.settings_changes is None else case.settings_changes),
    )
    chart_calls: list[str] = []
    original_put_chart = ArtifactStore.put_chart

    def observed_put_chart(store: ArtifactStore, plot_id: str, chart: bytes) -> None:
        chart_calls.append(plot_id)
        original_put_chart(store, plot_id, chart)

    monkeypatch.setattr(ArtifactStore, "put_chart", observed_put_chart)
    app = service_app.create_app(settings)
    constructed = _observe_commit_before_response(monkeypatch, settings)
    body = msgspec.json.encode({"user_request": case.user_request})
    with TestClient(app=app) as client:
        response = client.post("/propose-formula", content=body, headers=_JSON)
    return _FormulaRun(
        settings=settings,
        response=response,
        constructed=tuple(constructed),
        chart_calls=tuple(chart_calls),
    )


def _assert_formula_cell(run: _FormulaRun, expected: _CellExpectation) -> AttemptBundle:
    response = run.response
    assert response.status_code == expected.status
    body = cast("dict[str, Any]", response.json())
    if expected.status == 200:
        assert set(body) == {"model_reply", "verdict"}
        assert body["model_reply"] == cast("bytes", expected.model_reply).decode("utf-8")
        verdict = cast("dict[str, Any]", body["verdict"])
        attempt_id = cast("str", verdict["attempt_id"])
        expected_constructor = "result"
    else:
        assert response.headers["content-type"] == "application/problem+json"
        assert "model_reply" not in body and "verdict" not in body
        attempt_id = cast("str", body["attempt_id"])
        expected_constructor = "problem"
    assert response.headers.get("location") is None
    assert _json_keys(body).isdisjoint(_CHART_FIELDS)
    assert run.chart_calls == ()
    assert run.constructed == (expected_constructor,)

    settings = run.settings
    bundle = open_archive(settings).read_attempt(
        attempt_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    assert (bundle.manifest.route.name, bundle.manifest.route.value) == (
        "PROPOSE_FORMULA",
        "/propose-formula",
    )
    assert bundle.manifest.http_status == expected.status
    assert bundle.manifest.outcome is expected.outcome
    artifacts = bundle.artifacts
    assert (
        frozenset(name for name in _MODEL_FIELDS if getattr(artifacts, name) is not None)
        == expected.model_roles
    )
    assert artifacts.raw_spec == expected.raw_spec
    assert artifacts.model_reply == expected.model_reply
    if expected.raw_spec is not None:
        assert artifacts.model_reply == artifacts.raw_spec == expected.raw_spec
    assert artifacts.raw_csv is None
    assert artifacts.raw_manifest is None
    assert {binding.role.value for binding in bundle.manifest.artifacts}.isdisjoint(
        {"raw_csv", "raw_manifest"}
    )
    assert (type(bundle.plot) is FormulaPlotBundle) is expected.plot
    return bundle


# --- S8 fault matrix: 13 cells, every column hand-stated, never derived from production ---


def test_f01_verified_signs_a_propose_formula_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = (_FORMULA_GOOD / "f02_linear.json").read_bytes()
    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(proposal=_proposal(reply)),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=200,
            outcome=AttemptOutcome.VERIFIED,
            model_roles=frozenset({"model_request", "model_response", "model_reply"}),
            raw_spec=reply,
            model_reply=reply,
            plot=True,
        ),
    )


def test_f02_decode_rejected_signs_a_propose_formula_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = b"{"
    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(proposal=_proposal(reply)),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=200,
            outcome=AttemptOutcome.REJECTED,
            model_roles=frozenset({"model_request", "model_response", "model_reply"}),
            raw_spec=reply,
            model_reply=reply,
            plot=False,
        ),
    )


def test_f03_semantic_rejected_signs_a_propose_formula_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = (_FORMULA_BAD / "fb17_reversed_domain.json").read_bytes()
    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(proposal=_proposal(reply)),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=200,
            outcome=AttemptOutcome.REJECTED,
            model_roles=frozenset({"model_request", "model_response", "model_reply"}),
            raw_spec=reply,
            model_reply=reply,
            plot=False,
        ),
    )


def test_f04_pre_call_user_policy_signs_a_traceless_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(
            user_request="xx",
            settings_changes={"max_user_request_bytes": 1},
        ),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=422,
            outcome=AttemptOutcome.PROPOSER_POLICY,
            model_roles=frozenset(),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )


def test_f05_pre_call_prompt_policy_signs_a_traceless_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(settings_changes={"max_prompt_bytes": 1}),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=422,
            outcome=AttemptOutcome.PROPOSER_POLICY,
            model_roles=frozenset(),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )


def test_f06_transport_fault_retains_the_request_role_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        message = "private connection failure"
        raise httpx.ConnectError(message)

    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(backend_handler=handler),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=503,
            outcome=AttemptOutcome.MODEL_TRANSPORT,
            model_roles=frozenset({"model_request"}),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )


def test_f07_content_encoding_fault_retains_the_request_role_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The encoded body must reach the client still encoded. Passing `content=` here would make
    # HTTPX decompress it inside the mock transport, so the run would fault as transport before
    # the client ever read the header this cell is about.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=_RawStream(b"private compressed bytes"),
        )

    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(backend_handler=handler),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=502,
            outcome=AttemptOutcome.MODEL_CONTENT_ENCODING,
            model_roles=frozenset({"model_request"}),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )


def test_f08_oversize_fault_retains_the_request_role_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"xx")

    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(
            backend_handler=handler,
            settings_changes={"max_model_response_bytes": 1},
        ),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=502,
            outcome=AttemptOutcome.MODEL_RESPONSE_TOO_LARGE,
            model_roles=frozenset({"model_request"}),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )


def test_f09_upstream_http_status_retains_request_and_response_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_body = b'{"error":"private upstream failure"}'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=response_body)

    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(backend_handler=handler),
    )

    bundle = _assert_formula_cell(
        run,
        _CellExpectation(
            status=502,
            outcome=AttemptOutcome.MODEL_HTTP_STATUS,
            model_roles=frozenset({"model_request", "model_response"}),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )
    assert bundle.artifacts.model_response == response_body


def test_f10_prompt_token_policy_retains_request_and_response_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_body = msgspec.json.encode(
        {
            "error": {
                "message": "prompt exceeds token ceiling",
                "type": "prompt_too_long",
            }
        }
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            content=response_body,
            headers={"content-type": "application/json"},
        )

    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(backend_handler=handler),
    )

    bundle = _assert_formula_cell(
        run,
        _CellExpectation(
            status=422,
            outcome=AttemptOutcome.MODEL_PROMPT_TOKENS,
            model_roles=frozenset({"model_request", "model_response"}),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )
    assert bundle.artifacts.model_response == response_body


def test_f11_invalid_envelope_retains_request_and_response_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_body = b"{}"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=response_body)

    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(backend_handler=handler),
    )

    bundle = _assert_formula_cell(
        run,
        _CellExpectation(
            status=502,
            outcome=AttemptOutcome.MODEL_INVALID_ENVELOPE,
            model_roles=frozenset({"model_request", "model_response"}),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )
    assert bundle.artifacts.model_response == response_body


def test_f12_no_choice_retains_request_and_response_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_body = msgspec.json.encode({"choices": []})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=response_body)

    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(backend_handler=handler),
    )

    bundle = _assert_formula_cell(
        run,
        _CellExpectation(
            status=502,
            outcome=AttemptOutcome.MODEL_NO_CHOICES,
            model_roles=frozenset({"model_request", "model_response"}),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )
    assert bundle.artifacts.model_response == response_body


def test_f13_empty_content_retains_request_and_response_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_body = msgspec.json.encode({"choices": [{"message": {"content": ""}}]})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=response_body)

    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(backend_handler=handler),
    )

    bundle = _assert_formula_cell(
        run,
        _CellExpectation(
            status=502,
            outcome=AttemptOutcome.MODEL_EMPTY_CONTENT,
            model_roles=frozenset({"model_request", "model_response"}),
            raw_spec=None,
            model_reply=None,
            plot=False,
        ),
    )
    assert bundle.artifacts.model_response == response_body


# --- S6 route totality: the 9 R6 sites, each an exact-set literal pin ---


def test_r6_attempt_route_enum_members_are_exactly_four() -> None:
    assert {(route.name, route.value) for route in AttemptRoute} == {
        ("VERIFY_AND_RENDER", "/verify-and-render"),
        ("PROPOSE_SPEC", "/propose-spec"),
        ("VERIFY_FORMULA", "/verify-formula"),
        ("PROPOSE_FORMULA", "/propose-formula"),
    }


def test_r6_route_plot_sources_is_total_and_formula_maps_to_formula_only() -> None:
    formula_route = AttemptRoute("/propose-formula")
    expected = {
        AttemptRoute.VERIFY_AND_RENDER: frozenset({PlotSourceKind.DATASET}),
        AttemptRoute.PROPOSE_SPEC: frozenset({PlotSourceKind.DATASET}),
        AttemptRoute.VERIFY_FORMULA: frozenset({PlotSourceKind.FORMULA}),
        formula_route: frozenset({PlotSourceKind.FORMULA}),
    }
    assert set(archive_module._ROUTE_PLOT_SOURCES) == {
        AttemptRoute.VERIFY_AND_RENDER,
        AttemptRoute.PROPOSE_SPEC,
        AttemptRoute.VERIFY_FORMULA,
        formula_route,
    }
    assert expected == archive_module._ROUTE_PLOT_SOURCES


def test_r6_route_reads_dataset_inputs_is_total_and_formula_is_false() -> None:
    formula_route = AttemptRoute("/propose-formula")
    expected = {
        AttemptRoute.VERIFY_AND_RENDER: True,
        AttemptRoute.PROPOSE_SPEC: True,
        AttemptRoute.VERIFY_FORMULA: False,
        formula_route: False,
    }
    assert set(archive_module._ROUTE_READS_DATASET_INPUTS) == {
        AttemptRoute.VERIFY_AND_RENDER,
        AttemptRoute.PROPOSE_SPEC,
        AttemptRoute.VERIFY_FORMULA,
        formula_route,
    }
    assert expected == archive_module._ROUTE_READS_DATASET_INPUTS


def _role_manifest(route: AttemptRoute, outcome: AttemptOutcome) -> AttemptManifest:
    """One shape-valid manifest carrying just the route and outcome a role selector reads."""
    return AttemptManifest(
        version="attempt-0.1",
        nonce="0" * 32,
        occurred_at="2026-08-23T00:00:00.000000Z",
        route=route,
        http_status=200,
        outcome=outcome,
        plot_id=None,
        artifacts=(),
        plot_artifacts=(),
        keyid="sha256:" + "1" * 64,
        verifier_version="test",
    )


def test_r6_route_model_roles_is_total_and_formula_narrows_the_proposer_selector() -> None:
    formula_route = AttemptRoute("/propose-formula")
    expected = {
        AttemptRoute.VERIFY_AND_RENDER: archive_module._render_route_model_roles,
        AttemptRoute.PROPOSE_SPEC: archive_module._proposer_route_model_roles,
        AttemptRoute.VERIFY_FORMULA: archive_module._formula_route_model_roles,
        formula_route: archive_module._formula_proposer_route_model_roles,
    }
    assert set(archive_module._ROUTE_MODEL_ROLES) == {
        AttemptRoute.VERIFY_AND_RENDER,
        AttemptRoute.PROPOSE_SPEC,
        AttemptRoute.VERIFY_FORMULA,
        formula_route,
    }
    assert expected == archive_module._ROUTE_MODEL_ROLES
    # The formula proposer does not reuse the dataset proposer's entry outright: reusing it is what
    # makes the dataset-only outcomes signable on a route that opens no dataset. It delegates for
    # the model-trace policy, so that policy still has exactly one implementation.
    narrowed = archive_module._ROUTE_MODEL_ROLES[formula_route]
    assert narrowed is not archive_module._ROUTE_MODEL_ROLES[AttemptRoute.PROPOSE_SPEC]
    for outcome in AttemptOutcome:
        if outcome in {AttemptOutcome.DATASET_NOT_FOUND, AttemptOutcome.DATASET_MISMATCH}:
            continue
        manifest = _role_manifest(formula_route, outcome)
        assert narrowed(manifest) == archive_module._proposer_route_model_roles(manifest)


@pytest.mark.parametrize(
    "outcome",
    [AttemptOutcome.DATASET_NOT_FOUND, AttemptOutcome.DATASET_MISMATCH],
    ids=["dataset-not-found", "dataset-mismatch"],
)
def test_s6_dataset_only_outcomes_are_unreachable_on_propose_formula(
    outcome: AttemptOutcome,
) -> None:
    formula_route = AttemptRoute("/propose-formula")
    selector = archive_module._ROUTE_MODEL_ROLES[formula_route]
    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^formula proposer attempts may not carry a dataset outcome$",
    ):
        selector(_role_manifest(formula_route, outcome))
    # The dataset proposer keeps reaching both: only the formula route's vocabulary narrows.
    dataset_selector = archive_module._ROUTE_MODEL_ROLES[AttemptRoute.PROPOSE_SPEC]
    assert dataset_selector(_role_manifest(AttemptRoute.PROPOSE_SPEC, outcome)) is not None


def test_r6_validate_attempt_outcome_binds_reply_identity_on_both_proposer_routes() -> None:
    formula_route = AttemptRoute("/propose-formula")
    proposer_routes = {AttemptRoute.PROPOSE_SPEC, formula_route}
    assert {(route.name, route.value) for route in proposer_routes} == {
        ("PROPOSE_SPEC", "/propose-spec"),
        ("PROPOSE_FORMULA", "/propose-formula"),
    }
    keyid = "sha256:" + "1" * 64
    artifacts = AttemptArtifacts(
        raw_spec=b"exact reply",
        verdict=b"{}",
        model_request=b"request",
        model_response=b"response",
        model_reply=b"different reply",
    )

    for route in proposer_routes:
        manifest = AttemptManifest(
            version="attempt-0.1",
            nonce="0" * 32,
            occurred_at="2026-08-23T00:00:00.000000Z",
            route=route,
            http_status=200,
            outcome=AttemptOutcome.REJECTED,
            plot_id=None,
            artifacts=(),
            plot_artifacts=(),
            keyid=keyid,
            verifier_version="test",
        )
        bundle = AttemptBundle(
            attempt_id="a" * 64,
            keyid=keyid,
            manifest=manifest,
            artifacts=artifacts,
            attempt_payload=b"{}",
            attempt_envelope=b"{}",
            public_key=b"k" * 32,
        )
        with pytest.raises(
            ArchiveIntegrityError,
            match="attempt model reply differs from the exact raw spec handed to decode",
        ):
            archive_module._validate_attempt_outcome(bundle)


def test_r6_replay_attempt_route_literal_is_exactly_four_values() -> None:
    assert set(cast("tuple[str, ...]", get_args(replay._AttemptRoute.__value__))) == {
        "/verify-and-render",
        "/propose-spec",
        "/verify-formula",
        "/propose-formula",
    }


def test_r6_replay_expected_model_roles_is_total_and_formula_expects_all_three() -> None:
    expected = {
        "/verify-and-render": frozenset(),
        "/propose-spec": frozenset({"model_request", "model_response", "model_reply"}),
        "/verify-formula": frozenset(),
        "/propose-formula": frozenset({"model_request", "model_response", "model_reply"}),
    }
    assert set(replay._EXPECTED_MODEL_ROLES) == {
        "/verify-and-render",
        "/propose-spec",
        "/verify-formula",
        "/propose-formula",
    }
    assert expected == replay._EXPECTED_MODEL_ROLES


def test_r6_replay_route_attaches_dataset_plot_is_total_and_formula_is_false() -> None:
    expected = {
        "/verify-and-render": True,
        "/propose-spec": True,
        "/verify-formula": False,
        "/propose-formula": False,
    }
    assert set(replay._ROUTE_ATTACHES_DATASET_PLOT) == {
        "/verify-and-render",
        "/propose-spec",
        "/verify-formula",
        "/propose-formula",
    }
    assert expected == replay._ROUTE_ATTACHES_DATASET_PLOT


def test_r6_replay_route_attaches_formula_plot_is_total_and_formula_is_true() -> None:
    expected = {
        "/verify-and-render": False,
        "/propose-spec": False,
        "/verify-formula": True,
        "/propose-formula": True,
    }
    assert set(replay._ROUTE_ATTACHES_FORMULA_PLOT) == {
        "/verify-and-render",
        "/propose-spec",
        "/verify-formula",
        "/propose-formula",
    }
    assert expected == replay._ROUTE_ATTACHES_FORMULA_PLOT


# --- S7 occurrence identity + S6 unreachable outcomes ---


def test_s7_propose_formula_binds_model_reply_to_the_exact_raw_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    writer = pipeline_module.AttemptWriter(
        settings=settings,
        archive=open_archive(settings),
        signer=load_identity(settings).signer,
    )
    raw_reply = b'{"version":"vplot-formula-0.1"}'
    trace = ProposalTrace(
        request_body=_MODEL_REQUEST,
        response_body=b'{"choices":[]}',
        reply_bytes=raw_reply,
        fault=None,
    )
    context = pipeline_module.FormulaContext(
        writer=writer,
        route=cast("AttemptRoute", "/propose-formula"),
        raw_spec=raw_reply,
        proposal_trace=trace,
    )
    verdict = pipeline_module._single("spec.decode", "rejected", layer="decode")
    captured: list[AttemptArtifacts] = []

    def capture(_context: object, artifacts: AttemptArtifacts, _plot: object) -> str:
        captured.append(artifacts)
        return "a" * 64

    monkeypatch.setattr(pipeline_module, "_record_attempt", capture)
    assert pipeline_module._record_formula_attempt(verdict, context, None) == "a" * 64
    assert len(captured) == 1
    artifacts = captured[0]
    assert artifacts.raw_spec == raw_reply
    assert artifacts.model_request == trace.request_body
    assert artifacts.model_response == trace.response_body
    assert artifacts.model_reply == artifacts.raw_spec == trace.reply_bytes
    assert artifacts.raw_csv is None
    assert artifacts.raw_manifest is None


def test_s7_direct_verify_formula_stays_trace_free(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(app=service_app.create_app(settings)) as client:
        response = client.post("/verify-formula", content=b"{", headers=_JSON)
    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    bundle = open_archive(settings).read_attempt(
        cast("str", body["attempt_id"]),
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    assert bundle.manifest.route is AttemptRoute.VERIFY_FORMULA
    assert bundle.artifacts.model_request is None
    assert bundle.artifacts.model_response is None
    assert bundle.artifacts.model_reply is None
    formula_proposer = AttemptRoute("/propose-formula")
    assert formula_proposer is not AttemptRoute.VERIFY_FORMULA
    assert {
        (route.name, route.value) for route in {AttemptRoute.VERIFY_FORMULA, formula_proposer}
    } == {
        ("VERIFY_FORMULA", "/verify-formula"),
        ("PROPOSE_FORMULA", "/propose-formula"),
    }


def test_s7_a_formula_proposer_fault_never_records_the_dataset_route(tmp_path: Path) -> None:
    signature = inspect.signature(pipeline_module.AttemptWriter.record_problem)
    assert "route" in signature.parameters
    settings = _settings(tmp_path)
    writer = pipeline_module.AttemptWriter(
        settings=settings,
        archive=open_archive(settings),
        signer=load_identity(settings).signer,
    )
    formula_route = AttemptRoute("/propose-formula")
    trace = ProposalTrace(
        request_body=_MODEL_REQUEST,
        response_body=None,
        reply_bytes=None,
        fault=ProposalFault.TRANSPORT,
    )
    record_problem = cast("Callable[..., str]", writer.record_problem)
    attempt_id = record_problem(
        route=formula_route,
        outcome=AttemptOutcome.MODEL_TRANSPORT,
        http_status=503,
        proposal_trace=trace,
    )
    bundle = open_archive(settings).read_attempt(
        attempt_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    assert bundle.manifest.route is formula_route
    assert bundle.manifest.route is not AttemptRoute.PROPOSE_SPEC
    assert bundle.artifacts.model_request == _MODEL_REQUEST
    assert bundle.artifacts.model_response is None
    assert bundle.artifacts.model_reply is None
    assert bundle.artifacts.raw_csv is None
    assert bundle.artifacts.raw_manifest is None


def test_s6_dataset_not_found_is_unreachable_on_propose_formula(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposer_object = model_client.__dict__.get("propose_formula")
    assert callable(proposer_object), "propose_formula is absent"
    assert tuple(inspect.signature(proposer_object).parameters) == (
        "user_request",
        "settings",
    )

    def dataset_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("formula proposer reached the dataset context loader")

    monkeypatch.setattr(model_client, "_load_dataset_context", dataset_bomb)
    reply = (_FORMULA_GOOD / "f02_linear.json").read_bytes()

    def handler(_request: httpx.Request) -> httpx.Response:
        envelope = {"choices": [{"message": {"content": reply.decode("utf-8")}}]}
        return httpx.Response(200, content=msgspec.json.encode(envelope))

    _install_backend(monkeypatch, handler)
    proposer = cast(
        "Callable[[str, Settings], Coroutine[Any, Any, ModelProposal]]",
        proposer_object,
    )
    proposal = asyncio.run(proposer("Plot a formula", _settings(tmp_path)))
    assert proposal.reply_bytes == reply
    assert proposal.trace.reply_bytes == reply
    assert proposal.trace.fault is None


def test_s6_dataset_mismatch_is_unreachable_on_propose_formula(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dataset_pin_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("formula proposal reached the dataset-name pin")

    monkeypatch.setattr(service_app, "_verify_render_pinned", dataset_pin_bomb)
    reply = (_FORMULA_GOOD / "f02_linear.json").read_bytes()
    run = _run_formula_case(
        tmp_path,
        monkeypatch,
        _FormulaInput(proposal=_proposal(reply)),
    )

    _assert_formula_cell(
        run,
        _CellExpectation(
            status=200,
            outcome=AttemptOutcome.VERIFIED,
            model_roles=frozenset({"model_request", "model_response", "model_reply"}),
            raw_spec=reply,
            model_reply=reply,
            plot=True,
        ),
    )


# --- S9: transport misuse is a 400 with no occurrence, because the model has not run yet ---


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b'{"user_request": 1}',
        b"{}",
        b'{"user_request": "Plot a formula", "dataset_name": "sales.csv"}',
    ],
    ids=["truncated", "wrong-type", "missing-field", "dataset-name"],
)
def test_s9_malformed_propose_formula_body_is_a_400_before_any_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    # The dataset-name case is the one that matters most: formula mode names no dataset, so the
    # field is unknown and REFUSED here rather than silently ignored by a lenient decode.
    def model_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("transport misuse reached the model backend")

    monkeypatch.setattr(service_app, "propose_formula", model_bomb, raising=False)
    settings = _settings(tmp_path)
    app = service_app.create_app(settings)
    with TestClient(app=app) as client:
        response = client.post("/propose-formula", content=body, headers=_JSON)

    assert response.status_code == 400
    assert response.headers.get("location") is None
    payload = cast("dict[str, Any]", response.json())
    # No model call means no classified outcome, so there is no occurrence to address.
    assert "attempt_id" not in payload


# --- R7: which stage refuses which malformation. The two are not interchangeable. ---


def _formula_body(formula: str) -> bytes:
    """One otherwise-valid formula spec carrying the given formula text."""
    raw = (_FORMULA_GOOD / "f02_linear.json").read_bytes()
    base = cast("dict[str, Any]", msgspec.json.decode(raw))
    return msgspec.json.encode({**base, "formula": formula})


@pytest.mark.parametrize(
    "formula",
    ["hello world", "lambda x", "import os", "vega"],
    ids=["prose", "lambda", "import", "vega"],
)
def test_r7_prose_formula_text_decodes_and_the_parser_is_what_refuses_it(
    tmp_path: Path, formula: str
) -> None:
    # FormulaText's alphabet admits letters, digits, underscore and space, so strict shape decode
    # CANNOT be the stage that refuses Python- or prose-shaped formula text: it decodes cleanly.
    # The closed expression parser owns that refusal. Claiming otherwise would credit schema
    # validation with a guarantee it does not provide.
    spec = schema.decode_formula_spec(_formula_body(formula))
    assert spec.formula == formula

    outcome = pipeline_module.verify_formula_decoded(spec, _settings(tmp_path))
    assert not outcome.verdict.verified
    assert [result.check for result in outcome.verdict.results if result.status == "fail"] == [
        "formula.names_allowed"
    ]


@pytest.mark.parametrize(
    "formula",
    ["lambda x: x", "{}", "x ^ 2", "a[0]", "x = 1"],
    ids=["colon", "braces", "caret", "brackets", "equals"],
)
def test_r7_out_of_alphabet_formula_text_never_reaches_the_parser(formula: str) -> None:
    # The bytes the alphabet excludes are the ones strict decode does own, so these die a stage
    # earlier and no verdict exists for them at all.
    with pytest.raises(msgspec.ValidationError):
        schema.decode_formula_spec(_formula_body(formula))


# --- K5: the replay mirror's soundness dependency, pinned so a relaxation cannot pass silently ---


def test_k5_replay_lowest_still_demands_a_verified_attempt_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert set(replay._EXPECTED_MODEL_ROLES) == {
        "/verify-and-render",
        "/propose-spec",
        "/verify-formula",
        "/propose-formula",
    }
    expected_roles = cast("dict[str, frozenset[str]]", replay._EXPECTED_MODEL_ROLES)
    assert expected_roles["/propose-formula"] == frozenset(
        {"model_request", "model_response", "model_reply"}
    )
    settings = _settings(tmp_path)
    archive = open_archive(settings)
    selected: list[str] = []

    def select(_archive: Archive, plot_id: str) -> None:
        selected.append(plot_id)

    def read_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("replay read an attempt without a verified-attempt selection")

    monkeypatch.setattr(Archive, "lowest_verified_attempt_id", select)
    monkeypatch.setattr(Archive, "read_attempt", read_bomb)
    plot_id = "0" * 64
    with pytest.raises(
        ArchiveNotFoundError,
        match="archive plot has no replayable signed verified attempt",
    ):
        service_replay._replay_lowest(
            archive,
            {},
            plot_id,
            settings.max_archive_bytes,
            settings.limits,
        )
    assert selected == [plot_id]


def test_k5_a_formula_replay_record_round_trips_through_the_widened_literal() -> None:
    digest = "sha256:" + "0" * 64
    payload = msgspec.json.encode(
        {
            "version": "attempt-0.1",
            "nonce": "0" * 32,
            "occurred_at": "2026-08-23T00:00:00.000000Z",
            "route": "/propose-formula",
            "http_status": 200,
            "outcome": "verified",
            "plot_id": "a" * 64,
            "artifacts": [
                {"role": "raw_spec", "digest": digest},
                {"role": "verdict", "digest": digest},
                {"role": "model_request", "digest": digest},
                {"role": "model_response", "digest": digest},
                {"role": "model_reply", "digest": digest},
            ],
            "plot_artifacts": [],
            "keyid": digest,
            "verifier_version": "test",
        }
    )

    decoded = cast("Any", replay._ATTEMPT_DECODER.decode(payload))
    assert decoded.route == "/propose-formula"
    assert {binding.role for binding in decoded.artifacts} == {
        "raw_spec",
        "verdict",
        "model_request",
        "model_response",
        "model_reply",
    }
    assert replay._ENCODER.encode(decoded) == payload
