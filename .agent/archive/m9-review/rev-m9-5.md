# rev-m9-5 — service formula pipeline + artifact routes + proposer

STATUS: DONE
FLUSHED: 4/4

## Unit verdicts

Fill one row per batch. verdict = CLEAN | FINDINGS. findings = comma-separated F-ids or `none`.

| unit | verdict | findings |
|---|---|---|
| M9.10 | CLEAN | none |
| M9.11 | CLEAN | none |
| M9.12a | FINDINGS | F1,F2 |
| M9.12b | FINDINGS | F3 |

## Findings

### F1 | sev=MED | M9.12a | model_backend/schema_guidance.py:113

- divergence: `_require_json_schema` accepts any non-empty object carrying one recognized keyword; it never checks the Draft 2020-12 meta-schema. Therefore `{"type":"not-a-json-schema-type"}`, `{"required":"not-an-array"}`, and `{"minimum":"not-a-number"}` all survive `load_guidance_schema`, contradicting `Engine.load`'s fail-closed invalid-schema claim. The portable backend tests replace `StructuredOutputConfig` with a string holder, so they cannot detect a schema-to-grammar converter that fails open.
- impact: A bad operator pin starts successfully and `/health` advertises its digest as the schema that actually guides the mode. The first guided request can fail late or run without effective structure. Strict verifier decode preserves the trust boundary, but backend availability and the shipped structure-guidance claim become false.
- acceptance-check: Validate each strict and stripped document as Draft 2020-12 before pipeline load. Add a hardware-free converter probe that compiles the stripped formula schema, accepts emitted JSON that passes the strict schema, and refuses at least an extra property, a missing required field, and a wrong enum. `/health` must become reachable only after both pins pass.
- red-test: tests/test_rev_m9_12a_guidance.py

### F2 | sev=LOW | M9.12a | bench/__main__.py:111

- divergence: `--timeout` uses bare `type=float`; it admits `0`, negative values, `inf`, and `nan`. `httpx.Client(timeout=...)` accepts all four at construction, unlike the finite-positive guards on the verifier and WebUI client paths.
- impact: The formula live-smoke/benchmark driver can time out immediately, use an undefined negative deadline, hang without a bound, or raise only when a request starts. A run can therefore fail or stall before producing the evidence that its configured timeout claims to bound.
- acceptance-check: Parse `--timeout` through one finite-positive validator. `0`, `-1`, `inf`, and `nan` must exit with argparse status 2 before client construction; a finite positive value must reach `httpx.Client` unchanged.
- red-test: tests/test_rev_m9_12a_timeout.py

### F3 | sev=MED | M9.12b | src/verifier/service/app.py:338

- divergence: `/propose-formula` correctly reads `await request.body()`, but its plain `msgspec.json.Decoder(ProposeFormulaRequest)` still accepts duplicate object members and silently keeps the last value. `{"user_request":"first","user_request":"second"}` reaches the model as `second` instead of becoming the route's documented malformed-body 400. The dataset proposer twin has the same decoder shape.
- impact: The raw-byte transport invariant does not prevent the collapse it was introduced to prevent. An ambiguous caller body is accepted under parser-dependent intent, and the signed occurrence retains the generated model request rather than the original duplicate-bearing HTTP body. Final formula verification still protects artifact correctness, but request semantics and auditability fail open.
- acceptance-check: Preflight both proposer request bodies with one duplicate-key rejecting decoder before typed decode. Any duplicate member must return RFC 9457 400 before admission, model execution, or attempt archival; ordinary, extra-field, and malformed-body behavior must stay unchanged.
- red-test: tests/test_rev_m9_12b_duplicate_keys.py

## Notes

- M9.10: CLEAN. Focused formula-route/contract/mutation suite = 48 passed. OpenAPI app/generator/golden summary triplicate exact; generated golden byte-identical (78096 B); 200 schema uses `anyOf`. Script-artifact negative claim occurs once at each mandated site after Markdown quote normalization and is text-identical. Success hashes are sourced from the authenticated VCert v0.3 bindings; raw request-body and failure/commit ordering are pinned by the focused suite.
- M9.11: CLEAN. Focused formula replay/artifact/OpenAPI suite = 103 passed. Attempt read precedes mode classification; classification precedes integrity-verdict construction. `/table` + `/script` remain role-addressed archive reads without a mode lookup, and claim text says typed-relation/digest-addressed but not certificate-graph authenticated. Certified-byte tests authenticate VCert v0.3 first and use `canon.hash_table_bytes` / `canon.hash_matplotlib_script`; the lone raw-SHA wording names the archive blob check and immediately distinguishes certified domain tags. `/replay` publishes `oneOf`; both concrete schemas set `additionalProperties:false`, real payload tests prove single-arm validity. App/generator/golden summaries agree. Affected artifact tests set explicit `state_dir`; `.verifier-state` search rc=1.
- M9.12a: FINDINGS F1,F2. Focused schema/backend/client/bench suite = 320 passed before reviewer reds. Formula golden = 3024 B, full SHA-256 `62d0a6b804c3fbddeec5918adcbdbc8eaa3be8d79d4adfc546636111a8eace55`; generated document equals disk and all 6 good formula specs pass jsonschema plus strict decode. Selector is one closed `guided_schema` key; production `guided_json` search rc=1; stale key is ignored; explicit null equals omission. Service timeout is finite-positive guarded. Reviewer reds: guidance meta-schema 3/3 failed pre-fix; bench timeout 4/4 failed pre-fix.
- M9.12b: FINDING F3. Focused proposer/attempt/replay/OpenAPI/admission suite = 281 passed before reviewer red. All nine route surfaces carry `/propose-formula`; nine independently applied omission/value mutants were killed by their dedicated hand-stated tests, and every source was SHA-restored with `src/**/__pycache__` cleared. Pre-sign identity has a signer call-count bomb and both replay engines re-hold it. `_ROUTE_ALLOWED_OUTCOMES` and `ReplayUnsupportedError` remain absent. App/generator/golden summary triplicate exact; generated golden byte-identical (78096 B); response set is 200/400/413/415/422/429/500/502/503/507 with no 404. Formula-gradient search found only explicit negative claims. Reviewer duplicate-key red = 1/1 failed pre-fix.

Free-form evidence pointers (log paths, commands run, rc). Keep dense.
