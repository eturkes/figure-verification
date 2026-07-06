# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M2.4 tests: the hand-authored OpenAPI 3.1 document and its /schema/openapi.json route.

The document is assembled from three sources (VPlot defs + introspectable response models +
hand-derived RenderVerdict), so these tests pin the seams that could silently drift: the
committed golden byte-for-byte, the version/info surface (servers deliberately omitted), an
operationId + summary on every op (Open WebUI M4 reads them), the documented operations against
the app's live routes,
every internal pointer resolving to a present component (which also proves the discriminator
mapping was rebased, not just the $ref values), each component as a valid Draft 2020-12 schema,
and RenderVerdict tracking its struct (with the const NOT bleeding into Verdict's own schema).
The golden is a drift detector (a uv.lock bump shifting a generated schema, or a route/model
change), NOT a cross-environment byte promise.
"""

import json
import re
from pathlib import Path
from typing import Any

import msgspec
import msgspec.structs
import pytest
from jsonschema import Draft202012Validator
from litestar.routes import HTTPRoute
from litestar.testing import TestClient

from verifier import __version__
from verifier.checks import CheckResult
from verifier.render import VCert
from verifier.schema import json_schema
from verifier.service.app import create_app
from verifier.service.models import (
    Problem,
    ProposeRequest,
    ProposeResult,
    RenderVerdict,
    Verdict,
)
from verifier.service.openapi import openapi_document, openapi_document_text
from verifier.service.settings import Settings

_DOC = openapi_document()
_GOLDEN = Path(__file__).parents[1] / "schema" / "openapi.json"
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})
_NOSNIFF = "nosniff"


def _operations() -> list[tuple[str, str, dict[str, Any]]]:
    """Every (path, method, operation) documented in the paths object."""
    return [
        (path, method, operation)
        for path, item in _DOC["paths"].items()
        for method, operation in item.items()
        if method in _HTTP_METHODS
    ]


def _collect_pointers(node: Any) -> list[str]:
    """Every `#/`-prefixed JSON pointer anywhere in node — $ref values AND the Transform
    union's discriminator.mapping values (both are plain strings)."""
    if isinstance(node, dict):
        return [pointer for value in node.values() for pointer in _collect_pointers(value)]
    if isinstance(node, list):
        return [pointer for value in node for pointer in _collect_pointers(value)]
    if isinstance(node, str) and node.startswith("#/"):
        return [node]
    return []


def test_golden_matches_document() -> None:
    # The committed golden must equal the freshly assembled document, byte for byte.
    assert _GOLDEN.read_bytes() == openapi_document_text().encode("utf-8")


def test_openapi_version_is_3_1() -> None:
    assert re.fullmatch(r"3\.1\.\d+", _DOC["openapi"]) is not None


def test_info_exact_and_servers_omitted() -> None:
    assert _DOC["info"] == {"title": "verifier", "version": __version__}
    # No `servers` block: the doc is served by the running instance, so OpenAPI 3.1's
    # origin-relative default names the right server under any VERIFIER_HOST/PORT bind (a
    # hardcoded URL would misdescribe a reconfigured deploy).
    assert "servers" not in _DOC


def test_every_operation_has_operation_id_and_summary() -> None:
    for path, method, operation in _operations():
        assert operation["operationId"], f"{method} {path} missing operationId"
        assert operation["summary"], f"{method} {path} missing summary"


def test_operation_ids_unique() -> None:
    ids = [operation["operationId"] for _, _, operation in _operations()]
    assert len(ids) == len(set(ids))


def test_documented_operations_match_live_routes(tmp_path: Path) -> None:
    # The paths object must track the app's real HTTP routes: strip Litestar's `:type` param
    # suffix to OpenAPI form, drop the framework's OPTIONS/HEAD, and drop the self-describing
    # /schema/openapi.json route (documented nowhere — it would reference itself).
    app = create_app(Settings(data_dir=tmp_path))
    live: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, HTTPRoute):
            continue
        path = re.sub(r":\w+}", "}", route.path)
        if path == "/schema/openapi.json":
            continue
        live |= {(method, path) for method in route.methods if method not in {"OPTIONS", "HEAD"}}
    documented = {(method.upper(), path) for path, method, _ in _operations()}
    assert documented == live


def test_internal_pointers_resolve() -> None:
    components = _DOC["components"]["schemas"]
    pointers = _collect_pointers(_DOC)
    assert pointers, "expected internal $ref/discriminator pointers"
    for pointer in pointers:
        assert pointer.startswith("#/components/schemas/"), pointer
        assert pointer.removeprefix("#/components/schemas/") in components, pointer


def test_component_namespaces_disjoint() -> None:
    # _components() layers VPlot $defs, then the generated response models, then RenderVerdict,
    # trusting the three name spaces not to collide — a collision would silently overwrite one
    # (insertion is last-writer-wins), leaving a request/response ref bound to the wrong schema.
    # Nothing in the assembly guards it, so pin disjointness: a future colliding name fails the
    # gate instead of corrupting the document.
    vplot = set(json_schema()["$defs"])
    _, generated = msgspec.json.schema_components(
        [Verdict, Problem, CheckResult, VCert, ProposeRequest],
        ref_template="#/components/schemas/{name}",
    )
    response_names = set(generated) | {"RenderVerdict", "ProposeResult"}
    assert vplot.isdisjoint(response_names), vplot & response_names


@pytest.mark.parametrize("name", sorted(_DOC["components"]["schemas"]))
def test_component_schema_is_valid_draft_2020_12(name: str) -> None:
    Draft202012Validator.check_schema(_DOC["components"]["schemas"][name])


def test_render_verdict_tracks_struct() -> None:
    fields = msgspec.structs.fields(RenderVerdict)
    schema = _DOC["components"]["schemas"]["RenderVerdict"]
    assert list(schema["properties"]) == [f.encode_name for f in fields]
    assert schema["required"] == [f.encode_name for f in fields if f.required]
    assert schema["properties"]["verified"] == {"const": True}
    # The deepcopy must NOT have bled the const override into Verdict's own schema.
    assert _DOC["components"]["schemas"]["Verdict"]["properties"]["verified"] == {"type": "boolean"}


def test_post_bodies_reference_vplotspec() -> None:
    for path in ("/verify-only", "/verify-and-render"):
        body = _DOC["paths"][path]["post"]["requestBody"]
        assert body["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/VPlotSpec"
        }


def _payload(instance: msgspec.Struct) -> Any:
    """A response struct as its decoded-JSON form — the exact shape the service encodes."""
    return json.loads(msgspec.json.encode(instance))


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    """A validator for `schema` with the document's components mounted at the schema root, so
    every #/components/schemas/X pointer resolves inside the same document."""
    return Draft202012Validator({**schema, "components": _DOC["components"]})


def test_documented_response_schemas_accept_real_payloads() -> None:
    # The M1 external-contract lesson: prove the service's REAL encoded structs satisfy the
    # schemas the document advertises, not merely that those schemas are well-formed. It pins
    # anyOf over oneOf (a render payload validates against BOTH RenderVerdict and Verdict, so
    # oneOf would reject it) and guards the overlap the anyOf relies on — the
    # verify_200.is_valid(render_verdict) check below is what fails if Verdict gains
    # forbid_unknown_fields (additionalProperties:false). Validating the render payload against
    # the anyOf-200 alone would NOT catch that: its RenderVerdict branch would still pass.
    fail_verdict = _payload(
        Verdict(
            verified=False,
            layer="decode",
            results=(
                CheckResult(check="spec.decode", status="fail", severity="blocking", message="bad"),
            ),
        )
    )
    render_verdict = _payload(
        RenderVerdict(
            verified=True,
            layer="verify",
            results=(),
            plot_id="a" * 64,
            spec_id="b" * 64,
            dataset_hash="sha256:" + "c" * 64,
            spec_hash="sha256:" + "d" * 64,
            plotted_table_hash="sha256:" + "e" * 64,
            manifest_hash="sha256:" + "f" * 64,
            svg="<svg/>",
        )
    )
    paths = _DOC["paths"]
    render_200 = _validator(
        paths["/verify-and-render"]["post"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
    )
    assert render_200.is_valid(render_verdict)
    assert render_200.is_valid(fail_verdict)
    verify_200 = _validator(
        paths["/verify-only"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    assert verify_200.is_valid(fail_verdict)
    # A render payload ALSO satisfies the bare Verdict schema — the overlap the anyOf relies on,
    # and precisely what breaks if Verdict gains forbid_unknown_fields (additionalProperties:false).
    assert verify_200.is_valid(render_verdict)
    render_ref = _validator({"$ref": "#/components/schemas/RenderVerdict"})
    assert render_ref.is_valid(render_verdict)
    assert not render_ref.is_valid(fail_verdict)
    # The hand-written /health 200 schema (the one response schema not msgspec-generated) must
    # accept the real health body; test_health pins that body to the live route.
    health_schema = _DOC["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert Draft202012Validator(health_schema).is_valid({"status": "ok", "version": __version__})


def test_propose_payloads_match_schemas() -> None:
    # The /propose-spec contract: a real ProposeRequest validates against its request-body schema,
    # and a real ProposeResult with EITHER verdict arm — a plain Verdict and a RenderVerdict —
    # validates against the ProposeResult 200 schema (the anyOf(RenderVerdict, Verdict) union the
    # hand-derived schema declares, since msgspec cannot introspect the Literal[True] arm).
    fail_verdict = Verdict(
        verified=False,
        layer="decode",
        results=(
            CheckResult(check="spec.decode", status="fail", severity="blocking", message="bad"),
        ),
    )
    render_verdict = RenderVerdict(
        verified=True,
        layer="verify",
        results=(),
        plot_id="a" * 64,
        spec_id="b" * 64,
        dataset_hash="sha256:" + "c" * 64,
        spec_hash="sha256:" + "d" * 64,
        plotted_table_hash="sha256:" + "e" * 64,
        manifest_hash="sha256:" + "f" * 64,
        svg="<svg/>",
    )
    post = _DOC["paths"]["/propose-spec"]["post"]
    result_200 = _validator(post["responses"]["200"]["content"]["application/json"]["schema"])
    assert result_200.is_valid(_payload(ProposeResult(model_reply="{}", verdict=fail_verdict)))
    assert result_200.is_valid(_payload(ProposeResult(model_reply="{}", verdict=render_verdict)))
    request_schema = _validator(post["requestBody"]["content"]["application/json"]["schema"])
    assert request_schema.is_valid(
        _payload(ProposeRequest(user_request="plot it", dataset_name="sales.csv"))
    )


def test_invalid_include_html_returns_documented_400(tmp_path: Path) -> None:
    # /verify-and-render documents 400 (the only route with a typed query param); a non-boolean
    # include_html trips Litestar's coercion. Prove the live response matches the documented
    # status + Problem schema — a real error-body external-contract check.
    problem_ref = {"$ref": "#/components/schemas/Problem"}
    responses = _DOC["paths"]["/verify-and-render"]["post"]["responses"]
    assert responses["400"]["content"]["application/problem+json"]["schema"] == problem_ref
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post(
            "/verify-and-render?include_html=maybe",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert _validator(problem_ref).is_valid(response.json())


def test_served_via_test_client(tmp_path: Path) -> None:
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as client:
        response = client.get("/schema/openapi.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == _NOSNIFF
    assert response.content == openapi_document_text().encode("utf-8")
