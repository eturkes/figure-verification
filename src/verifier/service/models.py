# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Serialized response models for the verifier service (M2.2).

Three shapes cross the transport boundary. Verdict is the verification-outcome envelope,
answered HTTP 200 whether the spec verified, decoded but failed a check, or failed to
decode (a decode failure is an expected model failure mode M3 meters, not transport
misuse). RenderVerdict extends that envelope with the render artifacts POST
/verify-and-render adds on a PASSING verdict (the SVG, an optional HTML view, the
content-addressed ids, the durable attempt id, and the five cert-verbatim hashes); a FAILING
verify-and-render
answers a plain Verdict, so a chart never rides an unverified outcome. Problem is the RFC
9457 application/problem+json body the app's exception handlers emit for transport misuse,
process-local admission refusal, or a server-config fault (wrong content-type, oversize body,
work gate exhausted, a broken trusted manifest) —
never a verification outcome. CheckResult is reused verbatim from the trusted core
(verifier.checks) — the transport adds no result struct or status/severity/method of its own. It
does mint two fail-closed check tags the core never emits — `spec.decode` (the raw body
would not decode) and `dataset.manifest_available` (no trusted manifest for the named
dataset) — each a blocking pre-pipeline verdict (see pipeline.py) that can only fail closed,
never falsely verify.

ProposeRequest and ProposeResult (M3.3a) frame the /propose-spec endpoint that runs the
untrusted local model in front of this same pipeline: the request carries the user's ask plus
the dataset name to plot; the result pairs the model's raw reply with the verify-and-render
verdict on it. The model proposes only a spec, never plotted values, so the claim boundary is
unchanged — a malformed proposal simply rides a failing verdict like any other blocked spec.
"""

from typing import Annotated, Literal

import msgspec

from verifier.checks import CheckResult
from verifier.schema import DatasetName

__all__ = ["Problem", "ProposeRequest", "ProposeResult", "RenderVerdict", "Verdict"]

type AttemptId = Annotated[str, msgspec.Meta(pattern="^[0-9a-f]{64}$")]


class Verdict(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """The verification outcome (HTTP 200 regardless of the judgement).

    `layer` names the stage that produced it: "decode" when the raw body failed to decode
    (a lone synthetic spec.decode result), "verify" once decoding passed and the trusted
    pipeline ran (dataset binding, recomputation, encoding/label, exact builder + SMT).
    `verified` is true only when every final result passed. `attempt_id` is present only after an
    artifact-producing route durably commits the signed occurrence; stateless `/verify-only`
    leaves it absent. The archived canonical verdict omits it too because the signed attempt
    envelope - and therefore its content-derived id - does not exist until after those bytes are
    fixed.
    """

    verified: bool
    layer: Literal["decode", "verify"]
    results: tuple[CheckResult, ...]
    attempt_id: AttemptId | None = None


class RenderVerdict(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """A passing /verify-and-render outcome: the Verdict fields plus the render artifacts.

    Only ever answered when `verified` is true — the field is typed `Literal[True]`, a STATIC
    (mypy) pin: constructing a RenderVerdict with `verified=False` is a type error, though
    msgspec skips `Literal` checks at runtime (direct construction still builds one), so the
    runtime never-a-chart guarantee lives in the pipeline path (a failing verify-and-render
    returns a plain Verdict, structurally without svg/html) plus the bad-corpus tests, not this
    field alone. A DISTINCT struct rather than a Verdict subclass, so the handler's
    Verdict | RenderVerdict return stays a real union for mypy and the OpenAPI surface.
    `attempt_id` = SHA-256 hexdigest of the signed occurrence envelope committed atomically with
    the complete plot bundle, before either in-memory LRU mutates.
    `plot_id` = SHA-256 hexdigest of the deterministic signed DSSE envelope bytes;
    `spec_id` = `spec_hash` minus its
    `sha256:` prefix (bare 64-hex). plot_id <-> spec_id is 1:1 only under stable trusted config;
    changing the trusted manifest, verifier/formal TCB, emitted Vega bytes, or signing key keeps
    spec_id but changes plot_id, so several plot_ids can share a spec_id (store.py refcounts them).
    The five `*_hash` fields are the authenticated VCert payload's verbatim
    `sha256:`-prefixed digests.
    `html` (omitted when absent via omit_defaults) carries the offline view only under
    include_html=true.
    """

    verified: Literal[True]
    layer: Literal["decode", "verify"]
    results: tuple[CheckResult, ...]
    attempt_id: AttemptId
    plot_id: str
    spec_id: str
    dataset_hash: str
    spec_hash: str
    plotted_table_hash: str
    manifest_hash: str
    vega_lite_hash: str
    svg: str
    html: str | None = None


class Problem(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """RFC 9457 detail for a non-verification HTTP outcome.

    `type` defaults to the RFC's "about:blank" (omitted when default), `title` is the HTTP
    status reason phrase, `status` the code, `detail` the occurrence-specific message. Transport
    misuse, work/prompt-policy refusal, upstream failure, and server faults use this shape.
    `attempt_id` is present only for an admitted, classified proposer fault whose signed occurrence
    committed successfully; pre-admission refusals and archive/internal faults omit it. A
    verification outcome never travels as a Problem — it is always a 200 Verdict.
    """

    title: str
    status: int
    detail: str
    type: str = "about:blank"
    attempt_id: AttemptId | None = None


class ProposeRequest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """A /propose-spec request: the free-text ask plus the dataset to plot.

    `user_request` is admitted by its UTF-8 encoding (4 KiB by default, operator-configurable),
    not JSON Schema's code-point `maxLength`; an over-policy request receives 422 before any model
    call. The complete system + user message content has its own independent byte ceiling.

    `dataset_name` is the VPlot DatasetName — path-safe by construction (a traversal or a
    non-`.csv` name cannot decode), so the untrusted caller cannot escape the trusted data
    directory through it. forbid_unknown_fields rejects any extra key at decode (a 400), like
    every decoded request the service accepts.
    """

    user_request: str
    dataset_name: DatasetName


class ProposeResult(msgspec.Struct, frozen=True, kw_only=True):
    """A /propose-spec outcome: the model's raw reply plus the verifier's verdict on it.

    `model_reply` is the backend's reply content verbatim (the proposed spec text, decoded to a
    string but never re-encoded), carried so a caller sees exactly what the untrusted model
    produced — including a malformed proposal that decoded to a failing verdict. `verdict` is the
    same Verdict | RenderVerdict the verify-and-render pipeline returns: a RenderVerdict with the
    certified chart when the proposal verified, a plain Verdict otherwise (never a chart on an
    unverified outcome). Response-only, so no forbid_unknown_fields; it rides Litestar's encoder
    like RenderVerdict (the Literal[True] pin blocks decode/inspect, not encode), so openapi.py
    hand-derives its schema for the same reason.
    """

    model_reply: str
    verdict: Verdict | RenderVerdict
