# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M2.2 POST /verify-only tests — the golden corpus through the HTTP transport.

Mirrors test_examples.py's corpus iteration, but asserts the verdict the running service
returns rather than the decode outcome alone: 10 good specs verify (200, layer "verify",
every result passing); the 18 bad specs split on `decodes` — decode-layer ones answer a
lone spec.decode fail at layer "decode", semantic ones answer verified:false with the
index-declared check among the failed results. Transport misuse (wrong/missing
content-type -> 415, oversize -> 413 over both the content-length and chunked paths, wrong
method -> 405) answers RFC 9457 application/problem+json, as does a broken trusted manifest
(-> 500). The fail-closed pin: a duplicate-key body decodes-fails through the raw-bytes
path, proving the framework never pre-parsed the JSON (a parse would last-wins-collapse the
duplicate and the spec would verify).
"""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from litestar import Litestar
from litestar.testing import TestClient

from verifier import checks
from verifier.service import pipeline
from verifier.service.app import create_app
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "good_specs"
_BAD_DIR = _EXAMPLES / "bad_specs"
_DATA = _ROOT / "data"

_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["good_specs"]
_BAD: list[dict[str, Any]] = _INDEX["bad_specs"]
_BAD_DECODE: list[dict[str, Any]] = [b for b in _BAD if not b["decodes"]]
_BAD_SEMANTIC: list[dict[str, Any]] = [b for b in _BAD if b["decodes"]]

_JSON = {"content-type": "application/json"}
_PROBLEM_JSON = "application/problem+json"
# A sales-bound good spec, so an ad-hoc data_dir need only supply schemas/sales.json.
_SALES_GOOD = "g01_total_revenue_by_month.json"


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(e["file"]).stem for e in entries]


@pytest.fixture
def client() -> Iterator[TestClient[Litestar]]:
    """A client over the real data_dir (the golden corpus binds to it)."""
    with TestClient(app=create_app(Settings(data_dir=_DATA))) as test_client:
        yield test_client


# --- good specs: verified through the service --------------------------------
@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_good_spec_verifies(client: TestClient[Litestar], entry: dict[str, Any]) -> None:
    raw = (_GOOD_DIR / entry["file"]).read_bytes()
    response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 200
    for internal_name in (b'"trace"', b'"evidence"', b'"source_bytes"', b'"manifest_bytes"'):
        assert internal_name not in response.content
    body: dict[str, Any] = response.json()
    assert body["verified"] is True
    assert body["layer"] == "verify"
    assert body["results"]  # non-empty: the real check set passed through, not a vacuous all([])
    assert all(result["status"] == "pass" for result in body["results"])


def test_outcome_carries_incremental_trace_and_passed_evidence() -> None:
    settings = Settings(data_dir=_DATA)
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    manifest_bytes = (_DATA / "schemas" / "sales.json").read_bytes()
    source_bytes = (_DATA / "sales.csv").read_bytes()

    passed = pipeline.verify_only(raw, settings)
    assert passed.trace.manifest_bytes == manifest_bytes
    assert passed.trace.source_bytes == source_bytes
    assert passed.trace.eval_work_units > 0
    assert passed.evidence is not None
    assert passed.evidence.manifest_bytes == manifest_bytes
    assert passed.evidence.source_bytes == source_bytes

    hash_failure = pipeline.verify_only(
        (_BAD_DIR / "b08_dataset_hash_mismatch.json").read_bytes(), settings
    )
    assert hash_failure.trace.manifest_bytes == manifest_bytes
    assert hash_failure.trace.source_bytes == source_bytes
    assert hash_failure.trace.eval_work_units == 0
    assert hash_failure.evidence is None

    decode_failure = pipeline.verify_only(b"not JSON", settings)
    assert decode_failure.trace == checks.VerificationTrace(manifest_bytes=None, source_bytes=None)
    assert decode_failure.evidence is None


# --- bad specs, decode layer: a lone spec.decode fail ------------------------
@pytest.mark.parametrize("entry", _BAD_DECODE, ids=_ids(_BAD_DECODE))
def test_bad_spec_decode_layer(client: TestClient[Litestar], entry: dict[str, Any]) -> None:
    raw = (_BAD_DIR / entry["file"]).read_bytes()
    response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "decode"
    assert [result["check"] for result in body["results"]] == ["spec.decode"]
    assert body["results"][0]["status"] == "fail"


# --- bad specs, semantic layer: index check among the failures ---------------
@pytest.mark.parametrize("entry", _BAD_SEMANTIC, ids=_ids(_BAD_SEMANTIC))
def test_bad_spec_semantic_layer(client: TestClient[Litestar], entry: dict[str, Any]) -> None:
    raw = (_BAD_DIR / entry["file"]).read_bytes()
    response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "verify"
    failed = {result["check"] for result in body["results"] if result["status"] == "fail"}
    assert entry["check"] in failed


# --- the fail-closed pin: a duplicate-key body must decode-fail --------------
def test_duplicate_key_body_fails_closed(client: TestClient[Litestar]) -> None:
    # Prepend a duplicate top-level key to an otherwise-valid good spec: the JSON stays
    # well-formed, msgspec silently last-wins-collapses the repeat, but decode_spec's rescan
    # rejects it. Had the framework pre-parsed the body, the duplicate would collapse before
    # decode_spec saw it and the spec would verify — so a decode fail proves the raw path.
    base = (_GOOD_DIR / _SALES_GOOD).read_text(encoding="utf-8")
    assert base.startswith("{")
    dup_body = ('{"version": "vplot-0.1",' + base[1:]).encode("utf-8")
    response = client.post("/verify-only", content=dup_body, headers=_JSON)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "decode"
    assert [result["check"] for result in body["results"]] == ["spec.decode"]
    assert "duplicate" in body["results"][0]["message"].lower()


# --- transport misuse -> RFC 9457 problem+json -------------------------------
@pytest.mark.parametrize("content_type", ["text/plain", "application/xml"])
def test_wrong_content_type_415(client: TestClient[Litestar], content_type: str) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post("/verify-only", content=raw, headers={"content-type": content_type})
    assert response.status_code == 415
    assert response.headers["content-type"] == _PROBLEM_JSON
    body: dict[str, Any] = response.json()
    assert body["status"] == 415
    assert body["title"] and body["detail"]


def test_missing_content_type_415(client: TestClient[Litestar]) -> None:
    # A raw-bytes body carries no JSON content-type (unlike json=/data=), so omitting the
    # header leaves the essence empty -> 415, not a silent accept.
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post("/verify-only", content=raw)
    assert response.status_code == 415
    assert response.headers["content-type"] == _PROBLEM_JSON


def test_oversize_body_413_content_length() -> None:
    # A declared content-length over the cap bails before the body is read.
    app = create_app(Settings(data_dir=_DATA, max_body_bytes=16))
    with TestClient(app=app) as client:
        response = client.post("/verify-only", content=b"x" * 256, headers=_JSON)
    assert response.status_code == 413
    assert response.headers["content-type"] == _PROBLEM_JSON


def test_oversize_body_413_chunked() -> None:
    # A generator body sends no content-length (chunked), so the cap enforces on the
    # streamed byte total instead — the raw-body read still catches it before any decode.
    def _chunks() -> Iterator[bytes]:
        for _ in range(16):
            yield b"x" * 8  # 128 bytes total, over the 16-byte cap

    app = create_app(Settings(data_dir=_DATA, max_body_bytes=16))
    with TestClient(app=app) as client:
        response = client.post("/verify-only", content=_chunks(), headers=_JSON)
    assert response.status_code == 413
    assert response.headers["content-type"] == _PROBLEM_JSON


def test_wrong_method_405(client: TestClient[Litestar]) -> None:
    response = client.get("/verify-only")
    assert response.status_code == 405
    assert response.headers["content-type"] == _PROBLEM_JSON
    body: dict[str, Any] = response.json()
    assert body["status"] == 405


# --- manifest availability vs. corruption (200 verdict vs. 500 problem) ------
def test_manifest_unavailable_is_verdict_fail(tmp_path: Path) -> None:
    # A decodable spec naming a dataset with no trusted manifest fails closed as a 200
    # verdict (the model cannot force a 500 by naming a missing dataset), not a raise.
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app=app) as client:
        raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
        response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "verify"
    assert [result["check"] for result in body["results"]] == ["dataset.manifest_available"]


def test_oversized_manifest_is_resource_verdict(tmp_path: Path) -> None:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "sales.json").write_bytes(b"xxxx")
    # A tiny operator override proves the service threads Settings.limits instead of silently
    # consulting the process-global core defaults.
    app = create_app(Settings(data_dir=tmp_path, max_manifest_bytes=3))
    with TestClient(app=app) as client:
        raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
        response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "verify"
    assert [result["check"] for result in body["results"]] == ["resource.file_bytes"]
    assert "evidence" not in body
    assert "trace" not in body


def test_broken_manifest_is_500_problem(tmp_path: Path) -> None:
    # A malformed trusted manifest is operator misconfiguration: load_manifest raises,
    # the app answers a generic 500 problem+json (the cause withheld from the caller).
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "sales.json").write_bytes(b"{ not valid json")
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app=app) as client:
        raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
        response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON
    body: dict[str, Any] = response.json()
    assert body["status"] == 500
    assert "internal" in body["detail"].lower()  # generic, no internal detail leaked


class _ListHandler(logging.Handler):
    """Collect emitted records. caplog installs its handler on the root logger, but Litestar
    replaces root's handlers with its own queue handler at startup, so a root-level capture
    misses everything after the app boots — attach this to the named logger directly instead."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_500_logs_the_withheld_cause(tmp_path: Path) -> None:
    # The cause is withheld from the caller but MUST reach the server log: Litestar does not
    # log an exception a custom handler catches, so the handler logs it itself. Without that,
    # an operator debugging a broken-manifest 500 would have no diagnostic anywhere.
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "sales.json").write_bytes(b"{ not valid json")
    app = create_app(Settings(data_dir=tmp_path))
    handler = _ListHandler()
    logger = logging.getLogger("verifier.service.app")
    with TestClient(app=app) as client:
        logger.addHandler(handler)  # after Litestar's startup logging config has run
        try:
            raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
            response = client.post("/verify-only", content=raw, headers=_JSON)
        finally:
            logger.removeHandler(handler)
    assert response.status_code == 500
    assert "not valid json" not in response.text  # the cause never rides the response
    assert handler.records, "the 500 cause was not logged"
    assert handler.records[0].levelno == logging.ERROR
    assert handler.records[0].exc_info is not None  # the traceback (the withheld cause) attached


def test_mispaired_manifest_is_500_problem(tmp_path: Path) -> None:
    # A well-formed manifest whose declared dataset != the spec's is a caller-config bug:
    # checks.verify raises ValueError, surfacing as the same generic 500 problem+json.
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    real: dict[str, Any] = json.loads((_DATA / "schemas" / "sales.json").read_text("utf-8"))
    real["dataset"] = "weather.csv"  # mispair: file is schemas/sales.json, declares weather
    (schemas / "sales.json").write_text(json.dumps(real), encoding="utf-8")
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app=app) as client:
        raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
        response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON


def test_manifest_path_not_a_file_is_500_problem(tmp_path: Path) -> None:
    # A manifest PATH that is a directory (not a regular file) is broken operator config,
    # not an absent manifest: read_bytes raises IsADirectoryError, which propagates uncaught
    # to the generic 500 — only a genuine FileNotFoundError absence answers a 200 verdict.
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "sales.json").mkdir()  # a directory where the manifest file is expected
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app=app) as client:
        raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
        response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON
    body: dict[str, Any] = response.json()
    assert body["status"] == 500


def test_source_path_not_a_file_is_500_problem(tmp_path: Path) -> None:
    # Same trusted-file split at the CSV boundary: a present directory collision propagates as
    # operator misconfiguration; only genuine absence becomes dataset.hash_matches_source.
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "sales.json").write_bytes((_DATA / "schemas" / "sales.json").read_bytes())
    (tmp_path / "sales.csv").mkdir()
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app=app) as client:
        raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
        response = client.post("/verify-only", content=raw, headers=_JSON)
    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON
    body: dict[str, Any] = response.json()
    assert body["status"] == 500
