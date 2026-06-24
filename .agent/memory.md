# Memory — figure-verification

Cross-session live context + lessons. Trajectory: `roadmap.md` + git. Process: `AGENTS.md`, `CLAUDE.md`. Earn each entry; delete when obsolete.

## State
- Planning done for M1. Outline relocated verbatim to `.agent/outline.md` (scope-seed, on-demand); `roadmap.md` adapted to the routine (ledger + active-milestone detail). M1 (trusted verifier core, 6 gate-free units) is IN-PROGRESS; M2–M6 UNPLANNED, planned when active. No project code yet — next session = M1.1 WORK-UNIT (scaffold). User manually steers these early sessions; slash commands left as-is by request.

## Conventions
- License id: `Apache-2.0 WITH LLVM-exception`. Source files carry header `SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception` (language-appropriate comment). `LICENSE` = project-neutral Apache 2.0 body + LLVM exception only (LLVM banner / NCSA / third-party sections stripped).
- Do-not-read enforcement lives in `.claude/settings.json` `permissions.deny` `Read()` (committed; needed because Read/Bash bypass `.gitignore`). Holds `LICENSE` + `uv.lock` (lands M1.1). Keep synced as files land. Serena's parallel = `.serena/project.yml` `ignored_paths` (non-gitignored entries only); now holds `LICENSE`.
- Git identity from global gitconfig (`Emir Turkes <eturkes@bu.edu>`); user drives remote.

## Stack (M1 trusted core) — researched SOTA, deliberately overriding the outline's human-popular defaults
- Runtime: Python ≥3.13; `uv` src-layout single pkg `verifier` (+`py.typed`, `uv_build`), committed `uv.lock`. FastAPI/service deferred to M2.
- Schema: **msgspec** (NOT Pydantic) — strict/fail-closed, `forbid_unknown_fields` on every `Struct`, transform ops = tagged union (`tag_field="op"`), `Literal` enums, module-level `Decoder`, `json.schema` export golden-snapshotted.
- Evaluator: **hand-rolled pure-Python** (NOT pandas/polars) — the trusted core; total control of row/col order, nulls, float accumulation.
- Hashing — all SHA-256 over **text** canonical forms, NEVER Parquet/Arrow bytes (version-coupled): table = typed-NDJSON (header `name:type`, fixed col order, total-sort rows, fixed per-type formatters, one null sentinel); spec = msgspec deterministic re-encode of the validated struct; dataset = raw CSV bytes.
- Oracle (dev/test only): **DuckDB** `threads=1` must reproduce byte-identical canonical tables on goldens (dual-engine determinism check).
- Renderer: **vl-convert-python** (pinned `vl_version`) → static **SVG** as the canonical/hashed artifact; hand-built Vega-Lite (NOT Altair), inline ONLY evaluator `data.values`, reject `url`/`datasets`/`transform`/`params`/`expr`; badge composed in trusted Python; optional non-canonical interactive HTML (`bundle=True, actions=False`, offline), off the hash chain. Vendor + register a font for SVG reproducibility.
- Lint/format: **ruff** (incl. S/T20/DTZ). Types: **mypy --strict** (hermetic, pure-Python; NOT `ty` — its silent unimplemented-check gaps are unsafe for a soundness core; `ty`/pyright editor-only). Tests: **pytest** + **Hypothesis** (property: 3-hash permutation-invariance + cross-run stability, aggregate-vs-recompute; CI `derandomize=True`, `deadline=None`) + **syrupy** goldens (assert-only in CI).

## Determinism invariants (M1 implementation MUST hold; migrate into tests at M1, prune at M1 review)
- Parse CSV cells as text → coerce by declared schema; decimals → `Decimal`/scaled-int, never float at ingest.
- Float sums: compensated (Kahan/Neumaier) or `Decimal` — never plain `sum` (non-associativity drifts hashes).
- Close every transform with an explicit TOTAL sort over all columns (declared `sort` first, fixed tiebreak); NaN never a sort key; one canonical null token.
- Validate spec against schema BEFORE recompute, so only allowlisted ops reach the evaluator (upholds `security.no_arbitrary_code`). No `eval`/`exec`/dynamic import anywhere.
- Renderer pins `vl_version` + a bundled font for byte-stable SVG; one spec per render (Vega element-id counter is process-global).

## Deferred
- M1.1 work-session: add `python` to `.serena/project.yml` `languages` once `.py` files exist (let Serena index real symbols then, not over an empty tree).
