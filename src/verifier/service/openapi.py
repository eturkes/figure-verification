# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hand-authored OpenAPI 3.1 document for the verifier service (M2.4).

Litestar's OpenAPI auto-generation stays OFF (the app sets openapi_config=None): it
introspects response models via msgspec.inspect, and RenderVerdict.verified: Literal[True]
(the M2.3 never-a-chart type pin) makes msgspec.inspect.type_info() — like
msgspec.json.schema() and .decode() — raise TypeError ("Literal may only contain
None/integers/strings") at inspector build. Only encode + direct construction tolerate it,
and RenderVerdict is response-only, so the service just encodes it; weakening the pin to a
plain bool would trade a static (mypy) never-a-chart guarantee for tooling convenience. So
the document is hand-authored in the project's own-every-byte, positive-allowlist spirit,
reusing the schemas msgspec CAN introspect and hand-deriving only the one it cannot.

Components come from three sources, zero hand-drift beyond the transport-only response shapes:
  1. the VPlot request-body defs (schema.json_schema()["$defs"]), their internal pointers
     rebased #/$defs/X -> #/components/schemas/X by string VALUE (msgspec emits the pointer
     as $ref values AND as the Transform union's discriminator.mapping values — a key-only
     rewrite would leave the mapping dangling);
  2. the introspectable request/response models (Verdict, Problem, CheckResult, VCert, and the
     M3.3a ProposeRequest, plus CertifiedCheck/Disclosed*/Tcb nested transitively), via
     msgspec.json.schema_components;
  3. the two models msgspec cannot introspect (both hold a Literal[True] arm): RenderVerdict,
     hand-derived from Verdict's generated schema (a deepcopy of its properties, so the const
     override never bleeds into Verdict's own `verified`); and the M3.3a ProposeResult, whose
     `verdict` field is the Verdict | RenderVerdict union; plus the canonical DSSE envelope served
     as raw bytes (not decoded into a transport model).

openapi_json_bytes() serves the deterministic, newline-terminated text verbatim at
GET /schema/openapi.json; schema/openapi.json commits the same bytes as a drift detector
(a uv.lock bump that shifts a generated schema, or a route/model change — NOT a cross-env
byte promise).
"""

import copy
import functools
import inspect
import json
from typing import Any

import msgspec

from verifier import __version__
from verifier.attestation import VCERT_PAYLOAD_TYPE
from verifier.checks import CheckResult
from verifier.render import VCert
from verifier.schema import json_schema
from verifier.service.models import Problem, ProposeRequest, ProposeResult, RenderVerdict, Verdict

__all__ = ["openapi_document", "openapi_document_text", "openapi_json_bytes"]

_OPENAPI_VERSION = "3.1.0"
_COMPONENTS = "#/components/schemas"
# A 64-hex artifact id (the fullmatch app.py enforces on the path param, in OpenAPI form).
_ID_PATTERN = "^[0-9a-f]{64}$"
# RenderVerdict's ten render-only fields on top of the Verdict envelope; every one is a
# plain string, and all but the omit_defaults `html` are required.
_RENDER_STRING_FIELDS = (
    "attempt_id",
    "plot_id",
    "spec_id",
    "dataset_hash",
    "spec_hash",
    "plotted_table_hash",
    "manifest_hash",
    "vega_lite_hash",
    "svg",
    "html",
)


def _rebase_refs(node: Any) -> Any:
    """Rewrite every `#/$defs/X` pointer to `#/components/schemas/X` by string VALUE.

    msgspec emits the pointer both as `$ref` values and as the Transform union's
    discriminator.mapping values, so the walk recurses through dicts/lists and rewrites any
    string pointer (no non-pointer VPlot string carries the `#/$defs/` prefix) — a key-based
    rewrite would leave the mapping values dangling."""
    if isinstance(node, dict):
        return {key: _rebase_refs(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_rebase_refs(item) for item in node]
    if isinstance(node, str) and node.startswith("#/$defs/"):
        return f"{_COMPONENTS}/{node.removeprefix('#/$defs/')}"
    return node


def _render_verdict_schema(verdict_schema: dict[str, Any]) -> dict[str, Any]:
    """RenderVerdict's schema, hand-derived from Verdict's generated schema — the one response
    model msgspec cannot introspect (Literal[True]).

    Its `verified/layer/results` come from a DEEPCOPY of Verdict's properties (never an alias:
    an in-place override would rewrite Verdict's own `verified` and falsely document a plain
    failing Verdict as always-verified), with `verified` overridden to {"const": True} — the
    JSON-Schema meaning of Literal[True]. The ten render fields are plain strings; every field
    but the omit_defaults `html` is required. The title/description/type/properties/required key
    shape mirrors msgspec's generated siblings."""
    properties: dict[str, Any] = copy.deepcopy(verdict_schema["properties"])
    properties["verified"] = {"const": True}
    for name in _RENDER_STRING_FIELDS:
        properties[name] = {"type": "string"}
    properties["attempt_id"]["pattern"] = _ID_PATTERN
    return {
        "title": "RenderVerdict",
        "description": inspect.getdoc(RenderVerdict),
        "type": "object",
        "properties": properties,
        "required": [name for name in properties if name != "html"],
    }


def _propose_result_schema() -> dict[str, Any]:
    """ProposeResult's schema, hand-derived for the same reason as RenderVerdict — its `verdict`
    field is the Verdict | RenderVerdict union, and RenderVerdict cannot be introspected
    (Literal[True]). `model_reply` is the raw model reply string; `verdict` is anyOf
    RenderVerdict|Verdict (a RenderVerdict payload also satisfies Verdict — anyOf, not oneOf,
    the /verify-and-render 200 precedent). Both fields are required."""
    return {
        "title": "ProposeResult",
        "description": inspect.getdoc(ProposeResult),
        "type": "object",
        "properties": {
            "model_reply": {"type": "string"},
            "verdict": {
                "anyOf": [
                    {"$ref": f"{_COMPONENTS}/RenderVerdict"},
                    {"$ref": f"{_COMPONENTS}/Verdict"},
                ]
            },
        },
        "required": ["model_reply", "verdict"],
    }


def _dsse_schemas() -> dict[str, dict[str, Any]]:
    """Canonical one-signature service envelope; DSSE ``keyid`` remains only a lookup hint."""
    signature = {
        "title": "DSSESignature",
        "description": (
            "The service's single Ed25519 signature. keyid is an unauthenticated lookup hint; "
            "trust comes only from an independently pinned public key."
        ),
        "type": "object",
        "properties": {
            "keyid": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            "sig": {"type": "string", "contentEncoding": "base64"},
        },
        "required": ["keyid", "sig"],
    }
    envelope = {
        "title": "DSSEEnvelope",
        "description": (
            "A deterministic DSSE v1 envelope authenticating the exact base64-decoded VCert "
            "v0.2 payload bytes and application-specific payload type. Verify it against an "
            "independently pinned Ed25519 public key before parsing the payload."
        ),
        "type": "object",
        "properties": {
            "payload": {"type": "string", "contentEncoding": "base64"},
            "payloadType": {"const": VCERT_PAYLOAD_TYPE},
            "signatures": {
                "type": "array",
                "items": {"$ref": f"{_COMPONENTS}/DSSESignature"},
                "minItems": 1,
                "maxItems": 1,
            },
        },
        "required": ["payload", "payloadType", "signatures"],
    }
    return {"DSSEEnvelope": envelope, "DSSESignature": signature}


def _components() -> dict[str, Any]:
    """The components/schemas block: VPlot request-body defs (pointers rebased) + the
    introspectable response/request models (sorted, ProposeRequest among them) + hand-derived
    transport schemas. The three key spaces are disjoint, so insertion never collides."""
    schemas: dict[str, Any] = {
        name: _rebase_refs(schema) for name, schema in json_schema()["$defs"].items()
    }
    _, generated = msgspec.json.schema_components(
        [Verdict, Problem, CheckResult, VCert, ProposeRequest],
        ref_template=f"{_COMPONENTS}/{{name}}",
    )
    for name in sorted(generated):
        schemas[name] = generated[name]
    schemas.update(_dsse_schemas())
    schemas["RenderVerdict"] = _render_verdict_schema(generated["Verdict"])
    schemas["ProposeResult"] = _propose_result_schema()
    return schemas


def _json_response(description: str, schema: dict[str, Any]) -> dict[str, Any]:
    """An application/json response object with the given schema."""
    return {"description": description, "content": {"application/json": {"schema": schema}}}


def _problem_response(description: str) -> dict[str, Any]:
    """An RFC 9457 application/problem+json response referencing the Problem component."""
    return {
        "description": description,
        "content": {"application/problem+json": {"schema": {"$ref": f"{_COMPONENTS}/Problem"}}},
    }


def _html_response(description: str) -> dict[str, Any]:
    """A text/html response object — the chart page is an opaque HTML string (its inner structure
    is the trusted render's, not part of this contract)."""
    return {"description": description, "content": {"text/html": {"schema": {"type": "string"}}}}


def _spec_request_body() -> dict[str, Any]:
    """The required VPlot-spec JSON request body shared by both POST routes."""
    return {
        "required": True,
        "content": {"application/json": {"schema": {"$ref": f"{_COMPONENTS}/VPlotSpec"}}},
    }


def _id_parameter(name: str) -> dict[str, Any]:
    """A required 64-hex path parameter (a content-addressed artifact id)."""
    return {
        "name": name,
        "in": "path",
        "required": True,
        "schema": {"type": "string", "pattern": _ID_PATTERN},
    }


def _paths() -> dict[str, Any]:
    """The seven documented operations, each with an explicit operationId + summary (Open WebUI
    maps operationId -> tool name; the model reads description, else summary — proposeSpec, the
    model-invoked proposal tool, carries the description). Intentionally outside the per-operation
    contract: the self-describing GET /schema/openapi.json route (the route-drift test drops it)
    and framework method responses (405 for a wrong method, and OPTIONS/HEAD — a property of the
    path, not an operation); an operation-specific validation failure like the 400 below, tied to
    a documented parameter, IS listed."""
    problems_post = {
        "413": _problem_response("The request body exceeded the configured size cap."),
        "415": _problem_response("The Content-Type was not application/json."),
        "429": _problem_response(
            "The process-local rate or active-job admission gate refused the work before model, "
            "verification, or render execution. Each service process owns an independent gate."
        ),
        "500": _problem_response(
            "The verifier hit an internal operator-config, implementation, or archive fault."
        ),
    }
    archive_quota = {
        "507": _problem_response(
            "The signed attempt could not commit within the configured logical archive quota; "
            "the original endpoint outcome and any chart artifact were withheld."
        )
    }
    not_found = {"404": _problem_response("No stored artifact for that id, or a malformed id.")}
    return {
        "/health": {
            "get": {
                "operationId": "health",
                "summary": "Liveness and version probe",
                "responses": {
                    "200": _json_response(
                        "The service is live; reports the running package version.",
                        {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string"},
                                "version": {"type": "string"},
                            },
                            "required": ["status", "version"],
                        },
                    )
                },
            }
        },
        "/verify-only": {
            "post": {
                "operationId": "verifyOnly",
                "summary": "Verify a VPlot spec and return a structured verdict",
                "requestBody": _spec_request_body(),
                "responses": {
                    "200": _json_response(
                        "The verification verdict (verified, decoded-but-failed, or a decode "
                        "failure) — never a chart.",
                        {"$ref": f"{_COMPONENTS}/Verdict"},
                    ),
                    **problems_post,
                },
            }
        },
        "/verify-and-render": {
            "post": {
                "operationId": "verifyAndRender",
                "summary": "Verify a VPlot spec and, only if verified, render the certified chart",
                "parameters": [
                    {
                        "name": "include_html",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "boolean", "default": False},
                    }
                ],
                "requestBody": _spec_request_body(),
                "responses": {
                    "200": _json_response(
                        "A RenderVerdict with the certified chart on a passing verdict, or a "
                        "plain Verdict on a failing one — each carrying its durably committed "
                        "attempt_id, and never a chart on an unverified outcome.",
                        # anyOf, NOT oneOf: a RenderVerdict payload also satisfies Verdict
                        # (which carries no additionalProperties:false), so the two are not
                        # mutually exclusive.
                        {
                            "anyOf": [
                                {"$ref": f"{_COMPONENTS}/RenderVerdict"},
                                {"$ref": f"{_COMPONENTS}/Verdict"},
                            ]
                        },
                    ),
                    # 400 is this route's own — include_html is the only typed request param, so
                    # only /verify-and-render can fail Litestar's query coercion. /verify-only
                    # (raw body, no typed params) never emits it, so it stays out of problems_post.
                    "400": _problem_response(
                        "The include_html query parameter was not a valid boolean."
                    ),
                    **problems_post,
                    **archive_quota,
                },
            }
        },
        "/propose-spec": {
            "post": {
                "operationId": "proposeSpec",
                "summary": "Propose a VPlot spec with the local model, then verify and render it",
                # The model-visible tool text (Open WebUI reads description, else summary — the
                # 0.10.x rule). Names the two request fields and concrete provisioned datasets, so
                # the weak local model gets a grounded, example-led prompt.
                "description": (
                    "Draft and verify a chart for a provisioned dataset. Given a natural-language "
                    "chart request and a dataset name, the local model proposes a VPlot chart "
                    "specification, which the verifier independently checks and — only if it "
                    "passes every check — renders as a certified chart. Provide `user_request` "
                    '(what to plot, for example "monthly revenue by region") and `dataset_name`, '
                    "one of the provisioned CSV datasets (for example sales.csv or weather.csv). A "
                    "verified proposal returns the certified chart to display; an unverifiable one "
                    "returns the failing verdict instead."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": f"{_COMPONENTS}/ProposeRequest"}}
                    },
                },
                "responses": {
                    "200": _json_response(
                        "On a verified proposal, a [result, summary] array carrying the certified "
                        "chart as an Open WebUI embed; on any other outcome, the bare result — the "
                        "model's raw reply paired with the verify-and-render verdict (a plain "
                        "verdict when unverified). Every admitted classified outcome carries its "
                        "durably committed attempt_id.",
                        # anyOf: the bare ProposeResult object (every non-verified outcome), OR the
                        # verified-success embed body — a two-element [ProposeResult, summary]
                        # array (element0 that same ProposeResult, element1 a human summary
                        # string). The arms are type-disjoint (object vs array); anyOf follows the
                        # union-200 house style (the /verify-and-render precedent).
                        {
                            "anyOf": [
                                {"$ref": f"{_COMPONENTS}/ProposeResult"},
                                {
                                    "type": "array",
                                    "prefixItems": [
                                        {"$ref": f"{_COMPONENTS}/ProposeResult"},
                                        {"type": "string"},
                                    ],
                                    "minItems": 2,
                                    "maxItems": 2,
                                },
                            ]
                        },
                    ),
                    "400": _problem_response(
                        "The propose request body was malformed or failed validation."
                    ),
                    "404": _problem_response("No dataset with the requested name is provisioned."),
                    "422": _problem_response(
                        "The user request, bounded dataset context, assembled prompt, or exact "
                        "backend-tokenized prompt exceeded proposer resource policy. No native "
                        "model generation or verification occurred. UTF-8/file byte ceilings "
                        "and the backend token ceiling are independent and inclusive."
                    ),
                    **problems_post,
                    **archive_quota,
                    "502": _problem_response(
                        "The model backend replied, but not with a usable chat completion "
                        "(any other non-success status, an oversized or malformed body, or no "
                        "usable message content), or it proposed a specification for a different "
                        "dataset than requested."
                    ),
                    "503": _problem_response("The model backend was unreachable or timed out."),
                },
            }
        },
        "/certificate/{plot_id}": {
            "get": {
                "operationId": "getCertificate",
                "summary": "Fetch a stored verified-plot certificate by plot_id",
                "parameters": [_id_parameter("plot_id")],
                "responses": {
                    "200": _json_response(
                        "The stored deterministic DSSE envelope bytes. Its plot_id is the "
                        "SHA-256 digest of these exact bytes; the authenticated payload is VCert "
                        "v0.2.",
                        {"$ref": f"{_COMPONENTS}/DSSEEnvelope"},
                    ),
                    **not_found,
                },
            }
        },
        "/spec/{spec_id}": {
            "get": {
                "operationId": "getSpec",
                "summary": "Fetch a stored verified spec's canonical bytes by spec_id",
                "parameters": [_id_parameter("spec_id")],
                "responses": {
                    "200": _json_response(
                        "The stored verified spec's canonical bytes.",
                        {"$ref": f"{_COMPONENTS}/VPlotSpec"},
                    ),
                    **not_found,
                },
            }
        },
        "/chart/{plot_id}": {
            "get": {
                "operationId": "getChart",
                "summary": "Fetch a stored verified chart page by plot_id",
                "parameters": [_id_parameter("plot_id")],
                "responses": {
                    "200": _html_response(
                        "The stored offline chart HTML page (served text/html under a sandbox CSP)."
                    ),
                    **not_found,
                },
            }
        },
    }


def openapi_document() -> dict[str, Any]:
    """The full OpenAPI 3.1 document (see the module docstring for how components are assembled).
    Construction order is deterministic, so no sort_keys is needed at serialization."""
    return {
        "openapi": _OPENAPI_VERSION,
        "info": {"title": "verifier", "version": __version__},
        # No `servers`: the document is served by the running instance, so OpenAPI 3.1's
        # origin-relative default ("/") already names the correct server under any bind — a
        # hardcoded URL would misdescribe a VERIFIER_HOST/PORT-overridden deploy.
        "paths": _paths(),
        "components": {"schemas": _components()},
    }


def openapi_document_text() -> str:
    """openapi_document() as deterministic, newline-terminated UTF-8 JSON — the byte-exact form
    committed as schema/openapi.json (the json_schema_text pattern; no sort_keys, since the
    construction order and sorted(generated) already fix every key's position)."""
    return json.dumps(openapi_document(), indent=2, ensure_ascii=False) + "\n"


@functools.cache
def openapi_json_bytes() -> bytes:
    """The served document bytes (openapi_document_text encoded UTF-8), cached — the document is
    a pure function of the build, so it is assembled once and served verbatim by the route."""
    return openapi_document_text().encode("utf-8")
