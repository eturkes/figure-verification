# Closed-milestone records — M1–M8

Range · shipped surface · gauge band (unit peaks, each at its original denominator + basis per the roadmap's sizing rule). Status → the roadmap's milestone ledger. `git log --grep "(M<m>[. ]"` indexes each unit trail but matches BODIES too ⇒ the ranges here are the authoritative spans.

- **M1** `609c25d^..c6ae99b` — headless `verifier` lib: `schema` → `canon` → `ingest` → `eval` → `checks` → `render`, exported JSON-Schema golden, Vega-Lite positive-allowlist builder, VCert v0.1 badge. impl 39–88%/200K.
- **M2** `e187211^..9e9f29e` — `verifier.service`: Litestar + uvicorn transport, `settings`/`app` (6 routes, raw-body-first)/`pipeline`/`models`/`store`/hand-authored `openapi`. impl 46–87%/200K.
- **M3** `baa4639^..0007354` — untrusted proposer: `model_backend/` OpenVINO NPU `/v1` wrapper, `service/model_client.py`, `POST /propose-spec`, `bench/` 100-prompt failure eval. impl 45–81%/200K.
- **M4** `70c8935^..f77da0d` — Open WebUI 0.10.2 integration: `GET /chart/{plot_id}` + `html_cap`, Location-variant propose reply, `webui/` harness, `Verified Plot Guard` outlet filter. impl 59–77%/200K (partial record).
- **M5** `e805acf^..d6f698b` — hardening spine: `limits.py`, `formal.py` (z3, three obligations), VCert v0.2 + `attestation.py` DSSE/Ed25519 + `service/identity.py`, SQLite provenance archive + replay. impl 45–80%/200K (6 of 20 units recorded).
- **M6** `d7329dc^..8dcde56` — `demo/e2e.py` hardware-free three-seed-case driver, opt-in `--with-webui`/`--with-model` legs, `WebUIClient.run_persisted_chat`. impl 49–69%/200K.
- **M7** `de04f66^..81b8a23` — `webui/launch.sh` one-command stack: verifier → model tier (REAL XOR `--stub`) → OWUI serve/bootstrap → banner → SIGINT/EXIT teardown. impl 36%/200K (one unit).
- **M8** `26635bb^..ec89cd6` — schema-guided decoding: `model_backend/schema_guidance.py`, per-request `StructuredOutputConfig`, `guided_json` on `propose_spec`, two pinned launcher prompts. impl 39–62%/200K.
