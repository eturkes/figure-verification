# POC_SCOPE — verified-plot PoC

A caller submits a restricted JSON plot spec; in DATASET MODE a weak local LLM can propose that
spec instead, and FORMULA MODE has no model front end. A separate trusted verifier independently
recomputes the plotted data — from the source CSV in dataset mode, by exact rational evaluation of
the submitted expression in formula mode — runs structured checks, blocks plots whose spec, data
binding, or encoding fail those checks, and releases only the rest under a provenance certificate:
a rendered chart in dataset mode, a verifier-authored matplotlib script the service never executes
in formula mode. This document fixes the boundary.

## What kinds of plots are allowed?

Dataset mode: `bar` · `line` · `scatter`. Formula mode: one closed-form expression sampled over an
explicit domain.

## What transformations are allowed?

Dataset mode only — formula mode declares no transforms, because the expression IS the computation.

- `select` — choose fields
- `filter` — keep rows by an explicit, declared predicate
- `group_by` — group by one or more keys
- `aggregate` — `sum` · `mean` · `count` · `min` · `max`
- `sort` — order rows by declared key(s) and direction

## What does verification mean for this PoC?

The verifier has TWO plot modes with DISJOINT carriers. DATASET MODE is the original: a source
CSV plus a trusted column manifest, emitted as Vega-Lite, certified by VCert v0.2. FORMULA MODE
plots a closed-form expression over an explicit domain: no CSV, no manifest, no Vega-Lite, no SVG,
and a verifier-authored matplotlib script the service NEVER executes, certified by VCert v0.3.
Every sentence below naming a CSV, manifest, Vega-Lite, SVG, renderer, or chart is a DATASET-MODE
sentence.

The untrusted model proposes ONLY a VPlot spec — transforms, encoding, and a declared
source-dataset hash — never plotted values. In dataset mode, "verified" means these four artifacts
are mutually consistent and every check passed:

1. the spec validated against the VPlot v0.1 DSL (unknown fields, ops, and marks are
   rejected before any computation runs);
2. the plotted table the verifier recomputed independently from the source CSV;
3. the emitted Vega-Lite, which inlines only that recomputed table;
4. the VCert v0.2 provenance record and badge representation: source-dataset, trusted-manifest,
   canonical-spec, recomputed-table, and exact emitted-Vega hashes; every passing check with its
   method; and the verifier, Z3, canonicalization, and display-tool versions in the trusted base.

Formula mode verifies its own four artifacts instead: the spec validated against the
`vplot-formula-0.1` DSL; the plotted table the verifier recomputed by EXACT rational evaluation of
the declared formula over the declared domain, never floating point; the canonical matplotlib
script the verifier itself authored from that table; and the VCert v0.3 provenance record binding
exactly four hashes — RESOLVED formula source, canonical spec, recomputed table, and emitted
script. The resolved formula source is the verifier's own canonical rendering of nine fixed fields
— grammar version, numeric profile, rounding mode, printed AST, resolved domain endpoints, sample
count, and both axis scales — never the submitted formula string verbatim, so two equivalent
respellings share one formula source hash while a changed domain or scale does not. Only that
hash is respelling-invariant: the canonical spec preserves the submitted text, so the spec hash,
the certificate payload, and the derived plot and spec ids still differ between two spellings of
the same function. There is no fifth. The same structured checks, resource ceilings, and Z3 second-checking apply, over
formula-mode obligations. matplotlib, the interpreter that would run the script, and the resulting
pixels are display trust, exactly as SVG rasterization is for dataset mode.

For a service render, the persistent Ed25519 signer wraps the exact VCert payload bytes and their
application-specific type in deterministic DSSE. `plot_id` is SHA-256 over the complete envelope
bytes; `/certificate/{plot_id}`, `/spec/{spec_id}`, and `/key/{keyid}` serve archive-validated exact
certificate, canonical-spec, and raw-public-key bytes durably across process restart. Each GET
rechecks its address and typed archive relation; certificate retrieval also verifies the canonical
DSSE signature/type under the digest-matching archived key as a self-consistency check.
Archive and key-endpoint presence are never trust. Authentication under an independently pinned public key means
only that the holder of the corresponding private key produced the envelope. The envelope's
`keyid` is an unauthenticated lookup hint - it does not establish operator identity, PKI
membership, time, completeness, or transparency log inclusion. Chart liveness remains process-local
and ephemeral. The chart page
visibly shows the VCert badge, signer hint, plot ID, and exact envelope link; display remains outside the proof.

Because the renderer only ever receives verifier-recomputed data, a chart cannot
display model-supplied numbers — that class of lie is impossible by construction, not a
check. Checks instead target spec, encoding, policy, and dataset-binding consistency:
fields exist in the plotted table, axis types match their fields, the exact built rows retain the
declared canonical order, every quantitative bar channel includes zero, an explicit discrete
legend domain exactly covers its plotted categories, a quantitative axis carries the unit the trusted
column manifest declares for its field, the declared dataset hash matches the source
bytes, and only allowlisted ops ever reach the evaluator.

The emitted Vega-Lite carries no model-supplied data transforms — no encoding-level
aggregate, bin, or impute, no model-supplied scale-domain override, no top-level `transform`.
The builder's `stack`/`sort`/`order` nulls switch Vega-Lite's implicit stacking/sorting off; its
only domain is the recomputed discrete-color domain checked before native rendering — so the marks
show the recomputed rows, nothing re-derived downstream.

What verification does NOT cover: representativeness or intent. A spec that filters to
an unflattering-but-real subset, or picks a valid-but-misleading encoding, still passes
every check — honest selection is the author's job. The certificate binds the separately
retrievable canonical spec by hash and discloses every applied filter and active sort, so a reader
can see which rows were chosen; the verifier guarantees the chart faithfully shows that selection,
not that the selection is fair.

## What is intentionally not supported?

arbitrary Python · arbitrary SQL · custom JavaScript · free-form Vega expressions ·
Vega-Lite's own data transforms (aggregate, bin, stack, impute, sort, scale-domain
override) · map charts · faceting · interaction · dashboards · multi-source joins.

## The line we hold (trusted computing base)

Z3 is a trusted second checker for three bounded, concrete obligations; it does not prove the
evaluator, builder, renderer, or whole verifier. `vl-convert` and the Vega runtime, SVG
rasterization, the browser, and the final pixels are likewise trusted, not formally verified -
trusted to render verified data faithfully, not proven to. In formula mode, matplotlib and the
Python interpreter that would execute the emitted script hold exactly that position; the verifier
authors those bytes and never runs them, so nothing downstream of the script is proven. The claim
is about the mutually bound data, spec, emitted artifact, and certificate layer, not what reaches
the screen.

One quantization inside that trusted zone is KNOWN, not merely unproven: the JS runtime
parses the inlined JSON numbers as IEEE-754 doubles, so a value beyond exact-double range
(integer part past 2^53, or more than ~16 significant digits — the DECIMAL(38) data model
admits both) can display rounded, even though the certificate hashes both the exact emitted
Vega-Lite bytes and the exact recomputed plotted table. Formula mode takes the opposite position on
the same hazard: the emitter REFUSES a spec whose exact rational values do not survive the float64
literals a matplotlib script must carry, blocking that outcome with a
`render.float64_fidelity` failure instead of certifying a script that would display rounded.

## Service boundary

`verifier.service` wraps this same verifier in a local HTTP transport - one uvicorn worker, bound
to `127.0.0.1` by default. Its persistent signer attests successful VCert payloads but adds no
verification check: a verify request runs the pipeline above unchanged and the service serializes
the result, mapping a decode failure or an unprovisioned manifest to its own fail-closed verdict
that can never falsely verify. The
metadata and artifact GETs are SOURCE-NEUTRAL: they serve exactly what a prior verified outcome of
either mode already produced, so the verification claim and the trusted-computing-base line both
hold verbatim. `data_dir` stays trusted operator config,
supplied through the environment before the process binds — never anything a caller sends. It is
read in dataset mode alone; formula mode reads no trusted file.

`POST /verify-formula` is formula mode's transport. A verified outcome answers the canonical
matplotlib script TEXT inline, next to the four VCert v0.3 hashes and the durable ids. ONLY A
VERIFIED 200 RETURNS OR ARCHIVES A SCRIPT ARTIFACT; EVERY FAILED VERDICT DOES NEITHER. The claim is
stated over VERDICTS, not over non-2xx responses, because emission, certification, and signing
necessarily precede the archive's transactional commit: a capacity 507 or an archive 500 can land
AFTER a script was built and signed in memory. Those answer a Problem, never a verdict and never a
script, and the atomic commit is what keeps the signed bytes from becoming durable or observable.
The service emits script bytes and never runs them, so formula mode writes no chart page and no
display cache on any path: `GET /chart/{plot_id}` never resolves a formula plot.

The transport reports two kinds of outcome and never confuses them:

- A **verification outcome** — verified, failed a semantic/resource check, or failed to decode at
  all — is a `200` carrying a structured verdict. A decode failure is an expected model
  failure mode, not a transport error, so it rides the verdict envelope like any other
  blocked spec; a chart is attached only when the verdict is verified, never otherwise.
- **A non-verification HTTP outcome** — a wrong `Content-Type` (415), an oversize
  body (413), a wrong method (405), an uncoercible query parameter like a non-boolean
  `include_html` (400), process-local work admission refusal (429), an unknown or malformed
  artifact id (404), a proposer input/token policy refusal before any model output or native
  generation exists (422), or a broken trusted manifest / implementation or native-render fault
  (500) — answers an RFC 9457
  `application/problem+json` document. Resource ceilings are verification outcomes, so they
  return a failed verdict before artifact storage once a spec entered verification; proposer
  context/token ceilings instead return 422 because no model content exists to verify. ONE ceiling
  escapes that rule in both modes: `VERIFIER_MAX_ATTESTATION_BYTES` bounds the signed OCCURRENCE as
  well as the certificate, so a value too small to sign even the rejection record replaces that
  verification outcome with a generic 500 carrying no attempt. Sizing it above the largest signable
  occurrence is operator configuration; the service enforces no minimum. A 500
  remains outside the verification contract; its cause stays in the server log, never in the
  caller's response.

Each application process owns one lock-safe token bucket and active-job gate shared by every
admitted POST route plus `GET /replay/{plot_id}`. The defaults admit a burst of 120 jobs, refill at
120 jobs/minute, and allow 2 active jobs. Bounded POST-body reads and transport-shape validation run
first, preserving their 400/413/415 outcomes; a malformed replay id likewise 404s before admission.
Then a caller either acquires both controls immediately or receives 429 before model, verifier,
replay, or native-render work. The permit spans async model wait and the full worker operation
through signed attempt commit and artifact storage. If the request is cancelled while its worker is
running, the worker retains the permit until it actually exits - Python cannot cancel that native
thread safely.

This admission is logical and process-local, not distributed resource accounting. The canonical
single-worker uvicorn process has one gate; running multiple service processes multiplies the
configured aggregate rate and active capacity. Operators tune the three controls with
`VERIFIER_WORK_RATE_PER_MINUTE`, `VERIFIER_WORK_BURST`, and `VERIFIER_MAX_ACTIVE_JOBS`.

Only offline chart pages occupy a bounded in-memory LRU; it is a process-local liveness cache.
Signed VCert envelopes and canonical specs are not render-cached: certificate, spec, and public-key
GETs resolve durably from the SQLite archive and revalidate their exact bytes. Only chart-LRU
eviction is endpoint-visible: `/chart/{plot_id}` may 404 after eviction or restart. A served chart
was verified when built and is immutable;
the certificate is provenance, not a chart-liveness gate. `VERIFIER_STATE_DIR` (default
`.verifier-state`, mode 0700) holds the 0600 raw Ed25519 signing key, content-addressed public keys,
and the owner-private SQLite provenance archive. Keep it off git and back it up as one private state
unit: losing it loses both signing identity and durable provenance/replay, so archived charts cannot
be replayed. Choosing a new `VERIFIER_SIGNING_KEY_FILE` rotates identity and changes plot IDs.
Preserved/publicly served keys gain no trust automatically; operators pin accepted historical key
IDs explicitly with `VERIFIER_TRUSTED_KEYIDS`.

The archive database rejects any inode with a link count other than one. It uses rollback-journal
`DELETE` with `synchronous=EXTRA`, an extra durability guarantee within the documented local
filesystem/VFS contract. The no-follow descriptor is validated before SQLite separately connects
through the open state-directory FD; replacement in that interval remains an accepted local
filesystem TOCTOU boundary. The pre-COMMIT fault hook proves explicit rollback only, not COMMIT
failure, hot-journal recovery, process termination, or power loss.

Every admitted, classified `/verify-and-render`, `/verify-formula`, or `/propose-spec` outcome
commits one signed
occurrence before response and before the chart LRU mutates. A successful occurrence atomically adds
the complete plot bundle too — the dataset bundle or the formula bundle, each holding only its own
mode's carriers; rejected verdicts and proposer faults bind only bytes actually
observed. A formula occurrence binds its raw spec and canonical verdict alone: no CSV, no manifest,
and no model trace exists on that route. The returned verdict or admitted-fault Problem carries the non-secret `attempt_id` derived
from that occurrence envelope. `/verify-only`, pre-admission transport/rate/capacity refusal,
disconnect before an outcome, process crash, unclassified operator/implementation fault, and
archive failure are intentionally outside this non-completeness claim. `VERIFIER_MAX_ARCHIVE_BYTES`
gates logical typed payload bytes transactionally without eviction; SQLite pages, indexes, rollback
journals, and filesystem overhead remain outside that accounting. Quota refusal replaces the
original outcome with 507; another archive fault replaces it with generic 500. Neither response
carries an attempt ID or leaks an unarchived artifact of either mode — no chart, and no script.

Owner-local audit is `python -m verifier.service audit ATTEMPT_ID [--reveal-sensitive]`. It
revalidates the complete signed graph reachable from the named attempt and authenticates under the
current signer's public verification key or an explicitly pinned historical public key. Default
ASCII JSON exposes hashes and metadata only; `--reveal-sensitive` additionally exposes
attempt-observation bytes as JSON-escaped UTF-8 or padded base64. Raw CSV, prompt, model, and request
bytes stay operator-local; no HTTP surface exposes them.

`GET /replay/{plot_id}` re-runs the trusted pipeline from archived raw CSV, manifest, and canonical
spec bytes under the operator's independent trust policy: the current signer plus explicitly pinned
historical key IDs. Archive key presence never grants trust. Its bounded `ReplayVerdict` reports
reproduction status, trusted keyid, per-artifact hash matches, version drift, and diagnostic-only SVG
equality - never raw source, prompt, snapshot, or rendered bytes. An exact reproduction repopulates
the ephemeral chart LRU from the authenticated archived inputs, so `GET /chart/{plot_id}` serves the
regenerated page. An unknown or malformed id returns 404, and so does any plot
with no signed verified attempt; an archived formula plot with such an attempt returns 501,
because this version replays dataset plots alone; process-local rate/active-job refusal returns 429;
a SQLite, schema, archive-read, or implementation fault becomes generic 500. A signed
attestation, blob, key, version, or recomputation mismatch instead returns a bounded 200 diagnostic
with no chart. Replay does not re-run the weak model; pixels and browser rendering remain trusted
display, not replay proof. Certificate, spec, and public-key retrieval remain durable and
archive-backed.

Endpoints, exercised with `curl` (defaults: loopback, port 8000):

```sh
# start the service (binds 127.0.0.1:8000)
VERIFIER_DATA_DIR=data python -m verifier.service

# liveness and running version
curl -sS http://127.0.0.1:8000/health

# verify a spec, get a structured verdict (never a chart)
curl -sS http://127.0.0.1:8000/verify-only \
  -H 'Content-Type: application/json' \
  --data-binary @examples/good_specs/g01_total_revenue_by_month.json

# verify and, only if verified, render the certified chart
# (add ?include_html=true for the offline HTML view)
curl -sS 'http://127.0.0.1:8000/verify-and-render?include_html=false' \
  -H 'Content-Type: application/json' \
  --data-binary @examples/good_specs/g01_total_revenue_by_month.json

# verify a formula spec and, only if verified, return the certified matplotlib script
# (the verifier authors that script and never runs it)
curl -sS http://127.0.0.1:8000/verify-formula \
  -H 'Content-Type: application/json' \
  --data-binary @examples/formula_good_specs/f02_linear.json

# fetch a stored signed DSSE certificate envelope / spec by the ids returned above
# (plot_id and spec_id come from that response; shown here as shell variables)
curl -sS "http://127.0.0.1:8000/certificate/${plot_id}"
curl -sS "http://127.0.0.1:8000/spec/${spec_id}"

# replay the archived inputs under current-or-explicitly-pinned trust;
# an exact result regenerates the ephemeral chart page
curl -sS "http://127.0.0.1:8000/replay/${plot_id}"

# fetch the independently bounded offline chart page Open WebUI embeds
curl -sS "http://127.0.0.1:8000/chart/${plot_id}"

# the hand-authored OpenAPI 3.1 document
curl -sS http://127.0.0.1:8000/schema/openapi.json
```

## Model proposer

`verifier.service` puts a weak local model in front of that same verifier through one more
endpoint, `POST /propose-spec`. The request is a small `{user_request, dataset_name}` object;
the service builds the VPlot proposer prompt, asks the local backend for a spec, and feeds
whatever it returns through `verify-and-render` above, pinned to the requested dataset: a
proposal that decodes but names a different dataset than the request is refused (`502`) right
after decode — before any of that dataset's trusted files are read, so it is never verified,
rendered, or stored, and an off-request chart cannot ride an honest hash. The claim boundary
does not move: the model proposes only a spec, never plotted values, and the verifier recomputes
the whole plotted table and re-binds the source CSV by hash exactly as before — so the model
earns no new trust, and a chart still rides only a verified, on-request outcome.

Schema-guided decoding is the shipped default for `/propose-spec` generation: the service asks the
untrusted backend for structure-constrained ("guided") output, steering the weak model toward
schema-representable structure instead of markdown-fenced prose. The guidance schema is derived from
the authoritative VPlot schema with the unsupported `pattern` and `format` constraints stripped;
ordinary chat and Open WebUI tool selection omit the flag and stay unconstrained. This constrains
output STRUCTURE ONLY — it does not establish semantic correctness, dataset binding, recomputation,
provenance, or acceptance — and is a generation convenience, not a trust grant or boundary change.
Guided bytes are still subject to the full strict VPlot decode and every semantic, resource, and SMT
check; the backend remains untrusted, the verifier strictly re-decodes every proposal and owns every
semantic and provenance check, and the modest claim and TCB line above are unchanged.

Prompt construction and later trusted verification read separate bounded filesystem snapshots.
A local change between them is an accepted TOCTOU boundary: the prompt may describe the earlier
snapshot, but only the later verification snapshot can satisfy binding checks and enter the signed
archive.

The error split extends the service boundary's rule to the model as an upstream dependency.
Before calling it, the service admits `user_request` by UTF-8 bytes (4 KiB default), reads the CSV
and manifest with the core's inclusive bounded-file policy, and incrementally admits the combined
system + user message content (32 KiB default). This is a byte/memory ceiling, not a token-count
claim; exact prompt-token admission belongs to the backend. Context breach returns a dedicated 422
before the backend call. The backend caps its own JSON request at 128 KiB before decode, applies
the chat template, tokenizes it without duplicate special tokens, and rejects a token count over
its configured inclusive ceiling before native generation. It forwards that exact admitted token
buffer to generation - never a string the runtime can re-template or retokenize. The verifier maps
only that backend's canonical HTTP-400 `prompt_too_long` JSON envelope to the same 422; every
lookalike stays 502. No 422 carries model output or a verification result. The backend response is
requested without content coding and streamed only through 128 KiB + one probe byte; an oversized
success or error body closes early as 502 before JSON decode and never becomes a stored/metered
model reply.

Once the backend returns a reply with extractable content, that content is a spec proposal —
however malformed — so it rides a `200` verdict just like a spec posted directly, including a
decode failure (whether a reply passes strict decode or fails at decode or a later check is an
observation of a particular model, device, and configuration, not part of this boundary; residual
failures include strict-decode misses and semantic blocks such as a selected field absent from the
recomputed plotted table). The verdict carries its committed
`attempt_id`. Only a fault outside that flow answers
problem+json: an unknown dataset name (`404`, the name never echoed back), an unreachable or
timed-out backend (`503`), a backend reply that is oversized or not a usable chat completion
(`502`, except the exact pre-generation token-policy 422 above), a decoded proposal naming a
different dataset than requested (`502`, the dataset-name
pin above),
or a malformed request body, wrong `Content-Type`, or wrong method (`400`/`415`/`405`). Admitted,
classified proposer faults carry a committed `attempt_id`; transport-shape and admission refusals
do not. The model
proposes the whole spec, but of the verifier's trusted inputs it names only the dataset — never
the trusted files at that path — so it cannot provoke the operator-config `500`.

```sh
# propose a spec with the local model, then verify and render it
curl -sS http://127.0.0.1:8000/propose-spec \
  -H 'Content-Type: application/json' \
  --data-binary '{"user_request": "total revenue by month", "dataset_name": "sales.csv"}'
```

## Open WebUI boundary

Open WebUI is a trusted display and orchestration layer, not a verifier and not an
extension of the verification claim. It asks the untrusted model what to do, executes
the allowlisted `proposeSpec` tool, and displays the result. Open WebUI, its function
runner, the browser, iframe handling, and the final pixels therefore join the trusted
computing base described above; only the verifier's validated spec, recomputed table,
emitted Vega-Lite, and certificate are mutually checked.

The verifier tool is global and executes in the Open WebUI backend. Open WebUI fetches
the verifier's OpenAPI document and posts tool requests server-to-server, so the
verifier intentionally exposes no browser CORS surface. A verified tool response names
an absolute chart `Location`; Open WebUI embeds that URL in a sandboxed iframe. The
chart response adds its own `Content-Security-Policy: sandbox allow-scripts`, while the
embedding sandbox grants no same-origin capability. This is defense in depth around a
trusted display path, not a proof of rendered pixels.

The deployment recipe assumes a bare-metal, single-user machine: browser, Open WebUI,
model backend, and verifier all resolve the same loopback interfaces. A container,
remote browser, or network-exposed deployment must replace those origins and undergo a
separate security review; the fixed PoC credentials and loopback URL assumptions are
not suitable there.

`Verified Plot Guard` is a global server-side outlet filter that replaces common
direct-chart reply forms with a notice routing the user through Figure Verifier. Its
classifier is intentionally heuristic: novel encodings can bypass it and ordinary text
can trigger false positives. It is a usability guardrail only - never a security
boundary, evidence that a reply was verified, or part of the verifier's correctness
claim. The deterministic verifier remains the sole authority that can attach a chart
and provenance certificate.
