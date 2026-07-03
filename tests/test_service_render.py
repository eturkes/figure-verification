# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M2.3 POST /verify-and-render + retrieval GETs — verified renders through the transport.

The good corpus renders through the service byte-for-byte as a direct render.render (the SVG,
the four cert-verbatim hashes, and the content-addressed plot_id/spec_id); a repeat POST is
idempotent (same plot_id). The stored artifacts round-trip: GET /certificate serves the
canonical VCert bytes verbatim, GET /spec the canonical spec bytes. The never-a-chart pin
holds at byte level over ALL 18 bad specs — the raw response carries no "svg"/"html" key. The
store is bounded (an evicted render 404s on both its cert and spec GET); a malformed or absent
id 404s alike (no validity leak); and a render that returns None for a verified spec is a
broken invariant answered as a generic 500. X-Content-Type-Options: nosniff rides every
response, success and problem alike.
"""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from verifier import canon, render
from verifier.schema import decode_spec
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


# --- the render-None invariant break -> generic 500 --------------------------
def test_render_none_after_verified_is_500(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A verified spec whose render returns None cannot happen (render re-runs the same gates
    # verify_only just passed) -> a broken invariant answered as a generic 500 problem+json.
    def _render_none(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(render, "render", _render_none)
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == _NOSNIFF
    body: dict[str, Any] = response.json()
    assert body["status"] == 500
    assert "internal" in body["detail"].lower()  # generic, no internal cause leaked
