# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M3.3a POST /propose-spec tests: propose -> verify_and_render end to end, error split.

Drives the whole app through TestClient, injecting the model backend by patching
model_client._build_async_client with an httpx.AsyncClient over a MockTransport (the
test_service_model_client pattern), so no socket binds and the reply is deterministic. The
client runs over the real data_dir (data/), so a proposed good spec verifies, renders, and is
stored, while a proposed malformed or check-failing spec rides a 200 verdict — the metered
model-failure mode, carried alongside the model's raw reply. The proposer error split maps to
problem+json: an unknown dataset -> 404 (the name never echoed), an unreachable backend -> 503,
an unusable reply -> 502, a malformed request body -> 400, a wrong content-type -> 415, a wrong
method -> 405. A proposal that decodes but names a DIFFERENT dataset than requested is refused
502 by the M3.3b dataset-name pin, right after decode — before any verify or render, so even a
broken off-request manifest is a uniform 502, never a 500 or a store — no off-request chart.
"""

import json
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from verifier import canon
from verifier.schema import decode_spec
from verifier.service import model_client
from verifier.service.app import create_app
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD_DIR = _ROOT / "examples" / "good_specs"
_JSON = {"content-type": "application/json"}
_PROBLEM_JSON = "application/problem+json"
_NOSNIFF = "nosniff"
# A good sales spec, used verbatim as the model's reply for the verified path.
_SALES_GOOD = "g01_total_revenue_by_month.json"


def _install_handler(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Point model_client._build_async_client at a MockTransport-backed client running handler,
    so the proposer's HTTP call is served in-process with no socket."""

    def build(settings: Settings) -> httpx.AsyncClient:
        # Mirror the real factory's timeout wiring (harmless under MockTransport).
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=settings.model_timeout
        )

    monkeypatch.setattr(model_client, "_build_async_client", build)


def _install_reply(monkeypatch: pytest.MonkeyPatch, content: bytes) -> None:
    """Install a backend that answers 200 with a chat-completion envelope carrying `content` as
    the sole choice's message content."""

    def handler(_request: httpx.Request) -> httpx.Response:
        envelope = {"choices": [{"message": {"content": content.decode("utf-8")}}]}
        return httpx.Response(200, json=envelope)

    _install_handler(monkeypatch, handler)


def _spec_text(name: str) -> bytes:
    """A good-spec fixture's raw bytes, used as a canned model reply."""
    return (_GOOD_DIR / name).read_bytes()


@pytest.fixture
def client() -> Iterator[TestClient[Litestar]]:
    """A client over the real data_dir (the golden corpus binds to it)."""
    with TestClient(app=create_app(Settings(data_dir=_DATA))) as test_client:
        yield test_client


def _propose(client: TestClient[Litestar], user_request: str, dataset_name: str) -> httpx.Response:
    """POST a well-formed propose request."""
    body = msgspec.json.encode({"user_request": user_request, "dataset_name": dataset_name})
    return client.post("/propose-spec", content=body, headers=_JSON)


# --- the verification outcomes: every proposal rides a 200 verdict -----------
def test_propose_verified_spec_renders_and_stores(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A proposed good spec verifies and renders: a 200 RenderVerdict carrying the certified
    # chart, the raw reply echoed verbatim, and the artifacts stored (cert + spec round-trip).
    _install_reply(monkeypatch, _spec_text(_SALES_GOOD))
    response = _propose(client, "Plot total revenue by month", "sales.csv")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    body: dict[str, Any] = response.json()
    assert body["model_reply"] == _spec_text(_SALES_GOOD).decode("utf-8")
    verdict = body["verdict"]
    assert verdict["verified"] is True
    assert "svg" in verdict
    assert client.get(f"/certificate/{verdict['plot_id']}").status_code == 200
    assert client.get(f"/spec/{verdict['spec_id']}").status_code == 200


def test_propose_malformed_spec_is_decode_verdict(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A reply that parses as JSON but is not a valid VPlot spec (the weak model's placeholder
    # echo) fails decode -> a 200 layer="decode" verdict, never a chart, the raw reply carried.
    reply = b'{"version": "vplot-0.1", "mark": "bar|line"}'
    _install_reply(monkeypatch, reply)
    response = _propose(client, "anything", "sales.csv")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["model_reply"] == reply.decode("utf-8")
    verdict = body["verdict"]
    assert verdict["verified"] is False
    assert verdict["layer"] == "decode"
    assert "svg" not in verdict


def test_propose_failing_check_is_verify_verdict(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A reply that decodes cleanly but declares a wrong dataset hash fails the binding check ->
    # a 200 layer="verify" verdict, never a chart (a decoded-but-failed outcome, not a decode
    # failure). The name still matches the requested dataset, so no M3.3b pin is involved.
    spec = json.loads(_spec_text(_SALES_GOOD))
    spec["dataset"]["hash"] = "sha256:" + "0" * 64  # valid shape, wrong value
    reply = json.dumps(spec).encode("utf-8")
    _install_reply(monkeypatch, reply)
    response = _propose(client, "anything", "sales.csv")
    assert response.status_code == 200
    verdict = response.json()["verdict"]
    assert verdict["verified"] is False
    assert verdict["layer"] == "verify"
    assert "svg" not in verdict


# --- the M3.3b dataset-name pin: an off-request proposal is refused, not verified ---
def test_propose_dataset_mismatch_is_502(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The model proposes a spec for weather.csv (a valid, provisioned dataset whose own name +
    # hash verify honestly) though sales.csv was requested. checks._check_dataset_binding hashes
    # the file NAMED IN THE SPEC, so absent the pin this would verify, render, and store an
    # off-request chart; the pin refuses it 502 after verify_only, before render/store — never a
    # 200. The other dataset's name never enters the response.
    reply = _spec_text("g06_max_temp_by_city.json")  # names weather.csv, would verify + render
    _install_reply(monkeypatch, reply)
    response = _propose(client, "Plot max temperature by city", "sales.csv")
    assert response.status_code == 502
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == _NOSNIFF
    body: dict[str, Any] = response.json()
    assert body["status"] == 502
    assert "weather" not in json.dumps(body)  # the off-request name never leaks
    # The pin fires BEFORE render/store: the spec the reply WOULD have hashed to (spec_id =
    # cert.spec_hash = canon.hash_spec(spec)) was never stored -> a 404 at the spec GET, so this
    # locks pin-before-store, not merely the status.
    spec_id = canon.hash_spec(decode_spec(reply)).removeprefix("sha256:")
    assert client.get(f"/spec/{spec_id}").status_code == 404


def test_propose_offrequest_broken_manifest_is_502(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The requested sales.csv is validly provisioned (so the model runs), but the model proposes a
    # spec for a DIFFERENT dataset whose trusted manifest is PRESENT but malformed. The pin refuses
    # the off-request name 502 right after decode — before verify_decoded loads that manifest — so
    # a broken off-request manifest is a uniform 502, never the operator-config 500 it would raise
    # were verification to run on it (nor a present/broken/absent status oracle over the data dir).
    shutil.copy(_DATA / "sales.csv", tmp_path / "sales.csv")
    (tmp_path / "schemas").mkdir()
    shutil.copy(_DATA / "schemas" / "sales.json", tmp_path / "schemas" / "sales.json")
    (tmp_path / "schemas" / "trap.json").write_bytes(b"{ not valid json")
    spec = json.loads(_spec_text(_SALES_GOOD))
    spec["dataset"]["name"] = "trap.csv"  # a decodable spec naming the broken-manifest dataset
    _install_reply(monkeypatch, json.dumps(spec).encode("utf-8"))
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as scoped:
        response = _propose(scoped, "anything", "sales.csv")
    assert response.status_code == 502
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == _NOSNIFF
    body: dict[str, Any] = response.json()
    assert body["status"] == 502
    assert "trap" not in json.dumps(body)  # the off-request name never leaks


# --- the model as an upstream dependency: faults answer problem+json ---------
def test_propose_unknown_dataset_is_404(client: TestClient[Litestar]) -> None:
    # An unprovisioned (but path-safe) name resolves to nothing under data_dir -> 404 before any
    # HTTP call (no transport installed). The name is never echoed back to the caller.
    response = _propose(client, "anything", "nonexistent.csv")
    assert response.status_code == 404
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == _NOSNIFF
    body: dict[str, Any] = response.json()
    assert body["status"] == 404
    assert "nonexistent" not in json.dumps(body)


def test_propose_backend_unreachable_is_503(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        msg = "connection refused"
        raise httpx.ConnectError(msg)

    _install_handler(monkeypatch, handler)
    response = _propose(client, "anything", "sales.csv")
    assert response.status_code == 503
    assert response.headers["content-type"] == _PROBLEM_JSON
    body: dict[str, Any] = response.json()
    assert body["status"] == 503
    assert "refused" not in json.dumps(body)  # the cause is logged, never leaked


def test_propose_backend_unusable_reply_is_502(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_handler(monkeypatch, lambda _request: httpx.Response(500, json={"error": "boom"}))
    response = _propose(client, "anything", "sales.csv")
    assert response.status_code == 502
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json()["status"] == 502


def test_propose_invalid_utf8_reply_is_502(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A 200 body whose JSON string content carries invalid UTF-8 is not a usable chat completion:
    # msgspec raises the builtin UnicodeDecodeError (not its own DecodeError), which
    # _extract_content maps to a 502 upstream fault — never the operator-config 500 the model
    # must not be able to provoke.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"choices":[{"message":{"content":"\xed\xa0\x80"}}]}')

    _install_handler(monkeypatch, handler)
    response = _propose(client, "anything", "sales.csv")
    assert response.status_code == 502
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json()["status"] == 502


# --- transport misuse on the new route ---------------------------------------
@pytest.mark.parametrize(
    "body",
    [
        b'{"dataset_name": "sales.csv"}',
        b'{"user_request": "x"}',
        b'{"user_request": "x", "dataset_name": "sales.csv", "extra": 1}',
        b'{"user_request": "x", "dataset_name": "../sales.csv"}',
        b'{"user_request": "x", "dataset_name": "sales.txt"}',
    ],
    ids=["missing-request", "missing-dataset", "unknown-field", "traversal-name", "non-csv-name"],
)
def test_propose_malformed_body_is_400(client: TestClient[Litestar], body: bytes) -> None:
    # A missing field, an unknown field, or a name that fails the path-safe DatasetName pattern
    # (a traversal or non-.csv name cannot decode) is transport misuse, not a spec proposal.
    response = client.post("/propose-spec", content=body, headers=_JSON)
    assert response.status_code == 400
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json()["status"] == 400


def test_propose_non_json_body_is_400(client: TestClient[Litestar]) -> None:
    response = client.post("/propose-spec", content=b"not json {", headers=_JSON)
    assert response.status_code == 400
    assert response.json()["status"] == 400


def test_propose_wrong_content_type_is_415(client: TestClient[Litestar]) -> None:
    body = msgspec.json.encode({"user_request": "x", "dataset_name": "sales.csv"})
    response = client.post("/propose-spec", content=body, headers={"content-type": "text/plain"})
    assert response.status_code == 415
    assert response.headers["content-type"] == _PROBLEM_JSON


def test_propose_wrong_method_is_405(client: TestClient[Litestar]) -> None:
    response = client.get("/propose-spec")
    assert response.status_code == 405
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json()["status"] == 405


# --- dataset resolution: a genuine absence (404) vs. a broken manifest (500) --
# The proposer reads the CSV + trusted manifest to build its prompt. Absence is a caller-facing
# 404 (the dataset simply is not provisioned); a manifest PATH that is present-but-wrong-shape
# (a directory) is operator misconfiguration, so it propagates to the generic 500 exactly as the
# verify pipeline does — the model, naming only the dataset, cannot provoke that 500.
def test_propose_csv_without_manifest_is_404(tmp_path: Path) -> None:
    # A half-provisioned dataset (CSV present, trusted manifest genuinely absent) stays a 404:
    # the manifest FileNotFoundError is not-provisioned, distinct from a shape fault's 500. This
    # locks the split CSV/manifest reads — the absence case must not become a 500.
    (tmp_path / "sales.csv").write_bytes(b"date,revenue\n2021-01,100\n")
    (tmp_path / "schemas").mkdir()
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as scoped:
        response = _propose(scoped, "anything", "sales.csv")
    assert response.status_code == 404
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json()["status"] == 404


def test_propose_manifest_is_directory_is_500(tmp_path: Path) -> None:
    # A provisioned CSV whose trusted manifest path is a DIRECTORY is broken operator config:
    # _load_dataset_context lets the IsADirectoryError propagate (mirroring the verify pipeline)
    # -> a generic 500 problem+json, not the caller-facing 404. The model never runs (no
    # transport installed); the fault fires while the proposer reads the manifest.
    (tmp_path / "sales.csv").write_bytes(b"date,revenue\n2021-01,100\n")
    (tmp_path / "schemas" / "sales.json").mkdir(parents=True)
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as scoped:
        response = _propose(scoped, "anything", "sales.csv")
    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json()["status"] == 500
