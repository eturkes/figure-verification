# Memory — figure-verification

Cross-session live context + lessons. Trajectory: `roadmap.md` + git. Process: `AGENTS.md`, `CLAUDE.md`. Earn each entry; delete when obsolete.

## State
- Planning done for M1, then hardened per `/codex-review` (claims narrowed to the recompute/TCB boundary; data-flow trust spine pinned — model proposes spec only, never values; added `dataset.hash_matches_source` check, `data/schemas/` manifests, `VPlot_SEMANTICS.md`; renderer denylist → positive allowlist; singular Decimal numeric model; spec-canon rules). Outline relocated verbatim to `.agent/outline.md` (scope-seed, on-demand; note: its `aggregates_match_recomputation` example is internally inconsistent — model supplies no values — resolved in roadmap). `roadmap.md` adapted to the routine (ledger + active-milestone detail). M1 (trusted verifier core, 6 gate-free units) IN-PROGRESS; M2–M6 UNPLANNED, planned when active. **M1.1 DONE** — `uv`/`uv_build` src-layout pkg `verifier` scaffolded (committed `uv.lock` + `.python-version`), pyproject quality gate (ruff · mypy-strict · pytest + 100% branch-cov) green, `POC_SCOPE.md` written; next = M1.2 (VPlot v0.1 msgspec schema). User manually steers these early sessions; slash commands left as-is by request.

## Conventions
- License id: `Apache-2.0 WITH LLVM-exception`. Source files carry header `SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception` (language-appropriate comment). `LICENSE` = project-neutral Apache 2.0 body + LLVM exception only (LLVM banner / NCSA / third-party sections stripped).
- Do-not-read enforcement lives in `.claude/settings.json` `permissions.deny` `Read()` (committed; needed because Read/Bash bypass `.gitignore`). Holds `LICENSE` + `uv.lock`. Keep synced as files land. Serena's parallel = `.serena/project.yml` `ignored_paths` (non-gitignored entries only); now holds `LICENSE`.
- Git identity from global gitconfig (`Emir Turkes <eturkes@bu.edu>`); user drives remote.

## Stack (M1 trusted core) — researched SOTA, deliberately overriding the outline's human-popular defaults
- Runtime: Python ≥3.13; `uv` src-layout single pkg `verifier` (+`py.typed`, `uv_build`), committed `uv.lock`. Committed `.python-version` pins the dev/CI interpreter to 3.13 — uv otherwise floats to the newest satisfying `requires-python` (it grabbed 3.14), and Unicode/NFC data is bound to the Python minor, so one pinned minor keeps spec-hash canonicalization bit-identical across the host (`.venv-host`) and container (`.venv`) layers; `requires-python` stays the `>=3.13` floor (develop-on-floor). FastAPI/service deferred to M2.
- Schema: **msgspec** (NOT Pydantic) — strict/fail-closed, `forbid_unknown_fields` on every `Struct`, transform ops = tagged union (`tag_field="op"`), `Literal` enums, module-level `Decoder`, `json.schema` export golden-snapshotted.
- Evaluator: **hand-rolled pure-Python** (NOT pandas/polars) — the trusted core; total control of row/col order, nulls, float accumulation.
- Hashing — all SHA-256 over **text** canonical forms, NEVER Parquet/Arrow bytes (version-coupled): table = typed-NDJSON (header `name:type`, fixed col order, total-sort rows, fixed per-type formatters, one null sentinel); spec = msgspec re-encode of the validated struct (definition-order fields, pinned msgspec, NFC strings, floats forbidden in specs, `canon_version` tag — leaner than JCS/rfc8785, sufficient since we own the encoder); dataset = raw CSV bytes (byte-exact SOURCE identity, NOT permutation-invariant); + per-column manifest hash. Only the plotted-table hash is permutation-invariant (total-sort closure).
- Oracle (dev/test only): **DuckDB** `threads=1`, columns as matching `DECIMAL`, must reproduce byte-identical canonical tables on goldens; ops it cannot match bit-for-bit → logged tolerance cross-check (dual-engine determinism check).
- Renderer: **vl-convert-python** (pinned `vl_version`) → static **SVG** as the canonical/hashed artifact; hand-built Vega-Lite (NOT Altair) emitted via a POSITIVE allowlist schema (drop every key outside the generated subset — excludes `url`/`datasets`/`transform`/`params`/`expr`/`href`/`tooltip`/image-`url`/`loader`/`signals` by construction), inline ONLY evaluator `data.values`; VCert v0.1 badge composed in trusted Python; optional non-canonical interactive HTML (`bundle=True, actions=False`, offline), off the hash chain. Vendor + register a font for SVG reproducibility. Output-scan test: no `<script>`/external `href`/`src`/`url`, zero fetches.
- Lint/format: **ruff** (incl. S/T20/DTZ). Types: **mypy --strict** (hermetic, pure-Python; NOT `ty` — its silent unimplemented-check gaps are unsafe for a soundness core; `ty`/pyright editor-only). Tests: **pytest** + **Hypothesis** (property: 3-hash permutation-invariance + cross-run stability, aggregate-vs-recompute; CI `derandomize=True`, `deadline=None`) + **syrupy** goldens (assert-only in CI).

## Determinism invariants (M1 implementation MUST hold; migrate into tests at M1, prune at M1 review)
- Data-flow invariant: the model proposes ONLY the spec (transforms + encoding + declared `dataset.hash`); the verifier computes ALL plotted data and the renderer inlines only that — no model-supplied value ever reaches a chart. `dataset.hash_matches_source` binds the spec to the exact bytes (source path confined to `data/`).
- Parse CSV cells as text → coerce by the M1.3 manifest (the trusted schema; CSV alone has no types/units/labels).
- Numeric model is singular: `Decimal`/scaled-int with a declared per-measure scale + `ROUND_HALF_EVEN`; aggregation/division are exact-then-quantize (associative → hash-stable), so NO float math and NO Kahan. The DuckDB oracle must match this `DECIMAL` precision/rounding for hash equality.
- Close every transform with an explicit TOTAL sort over all columns (declared `sort` first, fixed tiebreak); NaN never a sort key; one canonical null token.
- Validate spec against schema BEFORE recompute, so only allowlisted ops reach the evaluator (upholds `security.no_arbitrary_code`). No `eval`/`exec`/dynamic import anywhere.
- Renderer pins `vl_version` + a bundled font for byte-stable SVG; one spec per render (Vega element-id counter is process-global).

## Ops (dev loop)
- venv is per-layer (uv bakes abs paths): container `.venv`, host `.venv-host`, both git-ignored. In non-interactive shells `export UV_PROJECT_ENVIRONMENT=.venv` (+ `UV_LINK_MODE=copy` to silence the cross-fs hardlink warning) before `uv` calls.
- Coverage gate = 100% branch (pyproject `fail_under=100`, `--cov` in `addopts`); a partial run (`uv run pytest tests/x.py`) trips it — add `--no-cov` for subsets.
- Hypothesis profiles live in `tests/conftest.py` (not pyproject): default `ci` (derandomize, no deadline) for reproducibility, `HYPOTHESIS_PROFILE=dev` for randomized exploration.

## Deferred
- M1.4: when `verifier/eval.py` imports duckdb (oracle) it ships no `py.typed` — add a mypy per-module override (`ignore_missing_imports`) or a stubs pkg so `mypy --strict` stays clean; same check for vl-convert-python at M1.6.
