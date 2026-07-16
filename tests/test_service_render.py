# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M2.3 POST /verify-and-render + retrieval GETs + GET /chart (M4.1c) — renders through the wire.

The good corpus renders through the service byte-for-byte as a direct render.render (the SVG,
the five cert-verbatim hashes, and the content-addressed plot_id/spec_id); a repeat POST is
idempotent (same plot_id). The stored artifacts round-trip: GET /certificate serves the
canonical VCert bytes verbatim, GET /spec the canonical spec bytes. The never-a-chart pin
holds at byte level over ALL 18 bad specs — the raw response carries no "svg"/"html" key. The
store is bounded (an evicted render 404s on both its cert and spec GET); a malformed or absent
id 404s alike (no validity leak); and a render resource refusal returns a failed verdict before
storage. X-Content-Type-Options: nosniff rides every response, success and problem alike.

GET /chart/{plot_id} serves the offline HTML page built + stored on EVERY verified render, so it
resolves even when the JSON body omitted the inline copy (include_html=false), as text/html under
a Content-Security-Policy: sandbox allow-scripts. Its chart LRU (html_cap) evicts independently of
the render LRU (store_cap) — a certificate can outlive its chart page — and an absent or malformed
plot_id 404s as problem+json carrying neither the CSP nor text/html (only the app-default nosniff).
"""

import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, NoReturn, cast
from unittest.mock import AsyncMock

import httpx
import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from verifier import canon, checks, limits, render
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import VPlotSpec, decode_spec
from verifier.service import app as service_app
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

_JSON = {"content-type": "application/json"}
_PROBLEM_JSON = "application/problem+json"
_NOSNIFF = "nosniff"
_SALES_GOOD = "g01_total_revenue_by_month.json"


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(e["file"]).stem for e in entries]


def _manifest_bytes(dataset_name: str) -> bytes:
    return (_DATA / "schemas" / f"{Path(dataset_name).stem}.json").read_bytes()


def _direct_render(raw: bytes, *, include_html: bool = False) -> render.RenderResult:
    """render.render on the raw spec, off the transport — the byte-identity oracle."""
    spec = decode_spec(raw)
    result = render.render(
        spec, _manifest_bytes(spec.dataset.name), data_dir=_DATA, include_html=include_html
    )
    assert result is not None
    return result


def _copy_sales_dataset(data_dir: Path) -> tuple[Path, Path]:
    source = data_dir / "sales.csv"
    manifest = data_dir / "schemas" / "sales.json"
    manifest.parent.mkdir()
    source.write_bytes((_DATA / "sales.csv").read_bytes())
    manifest.write_bytes((_DATA / "schemas" / "sales.json").read_bytes())
    return source, manifest


def _post_render_route(
    client: TestClient[Litestar], raw: bytes, route: Literal["direct", "propose"]
) -> httpx.Response:
    if route == "direct":
        return client.post("/verify-and-render", content=raw, headers=_JSON)
    spec = decode_spec(raw)
    body = msgspec.json.encode(
        {"user_request": "Plot total revenue by month", "dataset_name": spec.dataset.name}
    )
    return client.post("/propose-spec", content=body, headers=_JSON)


def _render_verdict(
    response: httpx.Response, route: Literal["direct", "propose"]
) -> dict[str, Any]:
    if route == "direct":
        return cast("dict[str, Any]", response.json())
    payload = cast("list[Any]", response.json())
    result = cast("dict[str, Any]", payload[0])
    return cast("dict[str, Any]", result["verdict"])


@pytest.fixture
def client() -> Iterator[TestClient[Litestar]]:
    """A client over the real data_dir (the golden corpus binds to it)."""
    with TestClient(app=create_app(Settings(data_dir=_DATA))) as test_client:
        yield test_client


# --- good specs: verified renders match a direct render byte-for-byte --------
@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_good_spec_renders_and_matches_direct(
    client: TestClient[Litestar], entry: dict[str, Any]
) -> None:
    raw = (_GOOD_DIR / entry["file"]).read_bytes()
    response = client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    body: dict[str, Any] = response.json()
    assert body["verified"] is True
    assert body["layer"] == "verify"
    assert "html" not in body  # default omits the offline view (omit_defaults on None)

    direct = _direct_render(raw)
    cert = direct.certificate
    assert body["svg"] == direct.svg  # determinism THROUGH the service
    assert body["plot_id"] == hashlib.sha256(render.vcert_bytes(cert)).hexdigest()
    assert body["spec_id"] == cert.spec_hash.removeprefix("sha256:")
    assert body["dataset_hash"] == cert.dataset_hash
    assert body["spec_hash"] == cert.spec_hash
    assert body["plotted_table_hash"] == cert.plotted_table_hash
    assert body["manifest_hash"] == cert.manifest_hash
    assert body["vega_lite_hash"] == cert.vega_lite_hash
    assert [(item.id, item.method, item.status) for item in cert.checks] == [
        (item["check"], item["method"], item["status"])
        for item in body["results"]
        if item["status"] == "pass"
    ]


@pytest.mark.parametrize("route", ["direct", "propose"])
def test_render_routes_read_each_verification_input_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: Literal["direct", "propose"],
) -> None:
    source, manifest = _copy_sales_dataset(tmp_path)
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    # Stub the upstream proposal so this counts the proposer route's verification/render leg;
    # model prompt context has its own reads and is bounded separately in M5.1g.
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=raw))
    reads: Counter[Path] = Counter()

    def counted_read(path: Path, max_bytes: int) -> bytes:
        reads[path.resolve()] += 1
        return limits.read_bounded(path, max_bytes)

    monkeypatch.setattr(pipeline, "read_bounded", counted_read)
    monkeypatch.setattr(checks, "read_bounded", counted_read)
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as client:
        response = _post_render_route(client, raw, route)
    assert response.status_code == 200
    assert _render_verdict(response, route)["verified"] is True
    assert reads == Counter({source.resolve(): 1, manifest.resolve(): 1})
    for internal_name in (b'"trace"', b'"evidence"', b'"source_bytes"', b'"manifest_bytes"'):
        assert internal_name not in response.content


@pytest.mark.parametrize("route", ["direct", "propose"])
def test_render_routes_ignore_source_mutation_after_evidence_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: Literal["direct", "propose"],
) -> None:
    source, manifest = _copy_sales_dataset(tmp_path)
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    spec = decode_spec(raw)
    expected = render.render(spec, manifest.read_bytes(), data_dir=tmp_path)
    assert expected is not None
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=raw))
    original_verify_run = checks.verify_run
    calls = 0
    replacement = b"month,region,revenue,orders\n2099-01,NA,1.00,1\n"

    def capture_then_mutate(
        captured_spec: VPlotSpec,
        manifest_bytes: bytes,
        *,
        data_dir: Path,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> checks.VerificationRun:
        nonlocal calls
        run = original_verify_run(captured_spec, manifest_bytes, data_dir=data_dir, limits=limits)
        calls += 1
        source.write_bytes(replacement)
        return run

    monkeypatch.setattr(checks, "verify_run", capture_then_mutate)
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as client:
        response = _post_render_route(client, raw, route)
    assert response.status_code == 200
    verdict = _render_verdict(response, route)
    assert verdict["verified"] is True
    assert verdict["svg"] == expected.svg
    assert verdict["dataset_hash"] == expected.certificate.dataset_hash
    assert calls == 1
    assert source.read_bytes() == replacement


def test_proposer_formal_gate_blocks_built_bar_zero_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A builder-scale defect becomes a 200 failed verdict, with no native render or store."""
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    original_build = render.build_vega_lite

    def corrupt_zero(*args: Any, **kwargs: Any) -> dict[str, Any]:
        built = original_build(*args, **kwargs)
        built["encoding"]["y"]["scale"]["zero"] = False
        return built

    def forbidden_native(_: str) -> str:
        msg = "native render reached after a formal bar-zero failure"
        raise AssertionError(msg)

    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=raw))
    monkeypatch.setattr(render, "build_vega_lite", corrupt_zero)
    monkeypatch.setattr(render, "render_svg", forbidden_native)
    request = msgspec.json.encode(
        {"user_request": "Plot total revenue by month", "dataset_name": "sales.csv"}
    )
    with TestClient(app=create_app(Settings(data_dir=_DATA))) as client:
        response = client.post("/propose-spec", content=request, headers=_JSON)
        assert response.status_code == 200
        body = cast("dict[str, Any]", response.json())
        verdict = cast("dict[str, Any]", body["verdict"])
        assert verdict["verified"] is False
        assert b'"svg"' not in response.content
        assert b'"html"' not in response.content
        failed = [item for item in verdict["results"] if item["status"] == "fail"]
        assert [(item["check"], item["method"]) for item in failed] == [
            ("scale.bar_zero", "z3_smt")
        ]
        spec_id = canon.hash_spec(decode_spec(raw)).removeprefix("sha256:")
        assert client.get(f"/spec/{spec_id}").status_code == 404


# --- the never-a-chart pin: no svg/html key over the whole bad corpus --------
@pytest.mark.parametrize("entry", _BAD, ids=_ids(_BAD))
def test_bad_spec_never_renders(client: TestClient[Litestar], entry: dict[str, Any]) -> None:
    raw = (_BAD_DIR / entry["file"]).read_bytes()
    response = client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    # Byte level: neither the svg nor the html key appears in the raw response (a failing
    # verify-and-render answers a plain Verdict, which structurally has no such fields).
    assert b'"svg"' not in response.content
    assert b'"html"' not in response.content
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert "svg" not in body
    assert "html" not in body


# --- idempotent: a repeat POST content-addresses to the same plot -----------
def test_repeat_post_is_idempotent(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    first: dict[str, Any] = client.post("/verify-and-render", content=raw, headers=_JSON).json()
    second: dict[str, Any] = client.post("/verify-and-render", content=raw, headers=_JSON).json()
    assert first["plot_id"] == second["plot_id"]
    assert first["spec_id"] == second["spec_id"]
    assert first["svg"] == second["svg"]


# --- retrieval GETs serve the stored canonical bytes verbatim ---------------
def test_certificate_get_round_trips(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    posted: dict[str, Any] = client.post("/verify-and-render", content=raw, headers=_JSON).json()
    response = client.get(f"/certificate/{posted['plot_id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == _NOSNIFF
    direct = _direct_render(raw)
    assert response.content == render.vcert_bytes(direct.certificate)  # verbatim canonical bytes
    assert msgspec.json.decode(response.content, type=render.VCert) == direct.certificate


def test_spec_get_serves_canonical_bytes(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    posted: dict[str, Any] = client.post("/verify-and-render", content=raw, headers=_JSON).json()
    response = client.get(f"/spec/{posted['spec_id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.content == canon.spec_bytes(decode_spec(raw))  # canonical, not the raw file
    assert decode_spec(response.content) == decode_spec(raw)  # yet decodes to the same spec


# --- the offline HTML view: attached on request, omitted by default ---------
def test_include_html_attaches_view(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post(
        "/verify-and-render", content=raw, headers=_JSON, params={"include_html": "true"}
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    direct = _direct_render(raw, include_html=True)
    assert body["html"] == direct.html
    assert body["svg"] == direct.svg


# --- GET /chart serves the page built on every verified render (even include_html=false) -----
def test_chart_get_serves_page_without_inline_copy(client: TestClient[Litestar]) -> None:
    # The offline page is built + stored on every verified render, so GET /chart resolves even
    # when the JSON body omitted the inline copy (include_html=false). The served bytes are a
    # direct render's HTML verbatim, as text/html under the sandbox CSP (+ the app nosniff).
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    posted: dict[str, Any] = client.post(
        "/verify-and-render", content=raw, headers=_JSON, params={"include_html": "false"}
    ).json()
    assert "html" not in posted  # the JSON body still omits the inline view
    response = client.get(f"/chart/{posted['plot_id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == "sandbox allow-scripts"
    assert response.headers["x-content-type-options"] == _NOSNIFF
    direct = _direct_render(raw, include_html=True)
    assert direct.html is not None
    assert response.content == direct.html.encode("utf-8")  # the page bytes verbatim


# --- the chart LRU (html_cap) evicts independently of the render LRU (store_cap) -------------
def test_chart_lru_evicts_independently_of_certificate() -> None:
    # store_cap=2, html_cap=1: two renders both keep their certificate, but only the newest keeps
    # its chart page — the reachable mixed state (a certificate outlives its chart page), pinning
    # that the two LRUs evict on their OWN recency, through the transport.
    app = create_app(Settings(data_dir=_DATA, store_cap=2, html_cap=1))
    with TestClient(app=app) as client:
        a: dict[str, Any] = client.post(
            "/verify-and-render", content=(_GOOD_DIR / _GOOD[0]["file"]).read_bytes(), headers=_JSON
        ).json()
        b: dict[str, Any] = client.post(
            "/verify-and-render", content=(_GOOD_DIR / _GOOD[1]["file"]).read_bytes(), headers=_JSON
        ).json()
        assert a["plot_id"] != b["plot_id"]
        # Both renders sit within store_cap=2 -> both certificates live.
        assert client.get(f"/certificate/{a['plot_id']}").status_code == 200
        assert client.get(f"/certificate/{b['plot_id']}").status_code == 200
        # But html_cap=1: A's chart page evicted when B's landed, while B's chart page lives.
        assert client.get(f"/chart/{a['plot_id']}").status_code == 404
        assert client.get(f"/chart/{b['plot_id']}").status_code == 200


# --- an absent or malformed chart id 404s without the CSP (uniform with the other GETs) ------
def test_chart_absent_or_malformed_404_without_csp(client: TestClient[Litestar]) -> None:
    # A never-stored valid-shape id and a malformed id both 404 as problem+json — the same uniform
    # answer the other retrieval GETs give — carrying NEITHER the chart CSP nor a text/html
    # content-type; only the app-default nosniff rides the problem response.
    for bad_id in ("0" * 64, "abc", "g" * 64):
        response = client.get(f"/chart/{bad_id}")
        assert response.status_code == 404
        assert response.headers["content-type"] == _PROBLEM_JSON
        assert "content-security-policy" not in response.headers
        assert response.headers["x-content-type-options"] == _NOSNIFF


# --- the store is bounded: the oldest render evicts, cert AND spec together --
def test_store_eviction_drops_cert_and_spec() -> None:
    app = create_app(Settings(data_dir=_DATA, store_cap=1))
    with TestClient(app=app) as client:
        a: dict[str, Any] = client.post(
            "/verify-and-render", content=(_GOOD_DIR / _GOOD[0]["file"]).read_bytes(), headers=_JSON
        ).json()
        b: dict[str, Any] = client.post(
            "/verify-and-render", content=(_GOOD_DIR / _GOOD[1]["file"]).read_bytes(), headers=_JSON
        ).json()
        assert a["plot_id"] != b["plot_id"]
        # A is the oldest render at cap 1 -> evicted, and its spec mapping drops with it.
        assert client.get(f"/certificate/{a['plot_id']}").status_code == 404
        assert client.get(f"/spec/{a['spec_id']}").status_code == 404
        # B, the surviving render, still resolves on both GETs.
        assert client.get(f"/certificate/{b['plot_id']}").status_code == 200
        assert client.get(f"/spec/{b['spec_id']}").status_code == 200


# --- id discipline: malformed and absent ids 404 alike (no validity leak) ----
@pytest.mark.parametrize(
    "bad_id",
    [
        "A" * 64,  # uppercase hex
        "abc",  # too short
        "0" * 63,  # one short of 64
        "0" * 65,  # one past 64
        "g" * 64,  # right length, non-hex
        "." * 64,  # right length, traversal-flavoured chars
    ],
)
def test_malformed_id_404_problem(client: TestClient[Litestar], bad_id: str) -> None:
    for path in (f"/certificate/{bad_id}", f"/spec/{bad_id}"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["content-type"] == _PROBLEM_JSON
        assert response.headers["x-content-type-options"] == _NOSNIFF


def test_well_formed_but_absent_id_404_problem(client: TestClient[Litestar]) -> None:
    # A valid-shape id that was never stored: the store-miss branch, same 404 as a malformed id.
    assert client.get("/certificate/" + "0" * 64).status_code == 404
    response = client.get("/spec/" + "f" * 64)
    assert response.status_code == 404
    assert response.headers["content-type"] == _PROBLEM_JSON


# --- transport misuse on the new route -> problem+json ----------------------
def test_verify_and_render_wrong_content_type_415(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post(
        "/verify-and-render", content=raw, headers={"content-type": "text/plain"}
    )
    assert response.status_code == 415
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == _NOSNIFF


# --- a decodable spec for an unprovisioned dataset -> 200 Verdict, no chart --
def test_verify_and_render_manifest_unavailable_is_verdict(tmp_path: Path) -> None:
    # A decodable good spec whose dataset has no trusted manifest under data_dir fails closed as
    # a 200 Verdict — never a chart — through verify-and-render's early return on an unverified
    # outcome (a real data-domain path that 100% branch coverage does not otherwise pin here).
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app=app) as no_manifest_client:
        raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
        response = no_manifest_client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    assert b'"svg"' not in response.content
    assert b'"html"' not in response.content
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "verify"
    assert [result["check"] for result in body["results"]] == ["dataset.manifest_available"]


# --- render policy refusals stay verification outcomes and never store -------
@pytest.mark.parametrize("stage", ["prepare_render", "render_prepared"])
def test_render_resource_failure_is_verdict_without_store(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    def refused(*_args: object, **_kwargs: object) -> NoReturn:
        message = "artifact exceeds test limit"
        raise VerificationError(message, check="resource.vega_bytes")

    monkeypatch.setattr(render, stage, refused)
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    assert b'"svg"' not in response.content
    assert b'"html"' not in response.content
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "verify"
    assert body["results"][-1] == {
        "check": "resource.vega_bytes",
        "method": "resource_policy",
        "status": "fail",
        "severity": "blocking",
        "message": "artifact exceeds test limit",
    }
    spec_id = canon.hash_spec(decode_spec(raw)).removeprefix("sha256:")
    assert client.get(f"/spec/{spec_id}").status_code == 404


def test_render_uses_operator_resource_limits_without_store() -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    settings = Settings(data_dir=_DATA, max_render_rows=1)
    with TestClient(app=create_app(settings)) as scoped:
        response = scoped.post("/verify-and-render", content=raw, headers=_JSON)
        body: dict[str, Any] = response.json()
        assert response.status_code == 200
        assert body["verified"] is False
        assert body["results"][-1]["check"] == "resource.render_rows"
        spec_id = canon.hash_spec(decode_spec(raw)).removeprefix("sha256:")
        assert scoped.get(f"/spec/{spec_id}").status_code == 404
