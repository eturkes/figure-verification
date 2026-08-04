# figure-verification — roadmap

Local "verified-plot" PoC. A weak local LLM only PROPOSES a restricted JSON chart spec (VPlot); a separate trusted verifier deterministically recomputes the plotted data from the source CSV, runs structured checks, blocks charts whose spec, encoding, policy, or dataset binding fail those checks, and renders only verified charts with a provenance certificate (dataset hash, spec hash, plotted-table hash, passed checks).

- **Scope-seed**: 16 verbatim seed steps "Milestone 0..15" at `git show 9d09ecb:.agent/outline.md`. The ledger below maps each routine-milestone `M<m>` to those steps; steps 0-15 are consumed by M1-M6, so read one only when a later milestone reopens its ground.
- **Stack**: `.agent/memory.md` (Stack + Lessons) — researched SOTA, deliberately overriding the outline's human-popular defaults. Determinism/trust invariants live in `VPlot_SEMANTICS.md` + `POC_SCOPE.md` + module docstrings, locked by the suites.
- **Data-flow (trust spine)**: the untrusted model proposes ONLY a VPlot spec (transforms + encoding + declared `dataset.hash`) — never plotted values. The verifier recomputes ALL plotted data; the renderer inlines only that. So lies needing model-supplied data (the seed's "plots a value ≠ recomputation") are impossible by construction, not checks; checks target spec/encoding/policy/dataset-binding consistency. (The seed's `aggregates_match_recomputation` example carries a model-supplied value — a seed inconsistency, resolved here.)
- **Modest claim** (hold the line): verified = {validated spec, the independently recomputed plotted table, the emitted Vega-Lite inlining only that table, the provenance badge} are mutually consistent and the checks passed. Trusted, NOT verified (TCB): `vl-convert`/Vega, SVG rasterization, browser, pixels — trusted to render verified data faithfully, not proven to.
- **Quality gate** (M1.1 wires it; every WORK-UNIT runs it — implementing teammate, then MAIN's independent rerun — all green, touched scripts exit clean): `ruff format --check .` · `ruff check .` · `mypy` · `pytest` — all via `uv run --locked` (the lockfile, not a newer floor-satisfying release, pins the gate).

## Milestone ledger

| M | Title | Seed steps | Gate | Status |
|---|-------|-----------|------|--------|
| M1 | Trusted verifier core (headless) | 0,1·scaffold,2,3,4,5,6 | none — toolchain confirmed | REVIEWED |
| M2 | Verifier API service (Litestar) | 1·api,8 | none | REVIEWED |
| M3 | Local model proposer + failure eval | 1·model,7,8·propose,12 | local OpenAI-compat backend — OpenVINO (confirmed M3.1a; was "Ollama") | REVIEWED |
| M4 | Open WebUI integration | 1·webui,9,10,11 | Open WebUI running — CONFIRMED at plan | REVIEWED |
| M5 | Formal + provenance hardening | 13,14 | none — toolchain probe confirmed | REVIEWED |
| M6 | End-to-end demo | 15 | full stack (M3+M4) — CONFIRMED live at plan | REVIEWED |
| M7 | Interactive local-model browser instance | — (user request) | live stack (verifier+model+OWUI) — CONFIRMED at plan | REVIEWED |
| M8 | Reliable real-model figures (schema-guided decoding) | — (user request) | live NPU stack + OV structured output — CONFIRMED at plan | REVIEWED |
| M9 | Verified formula-plot mode (headless) | — (user request) | none (headless verifier core) | IN-PROGRESS |
| M10 | Formula plot in OWUI sandbox + demo | — (user request) | browser-live OWUI `execute:python` — source-confirmed; live proof at M10 plan | UNPLANNED |
| M11 | Derived/computed columns (dataset mode) | — (user request) | none (headless; reuses M9 expr engine) | UNPLANNED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6/M7/M10 are gated — confirm preconditions functionally at their planning turn; bring generated/heavy inputs into scope only when the gate needs them.

---

## M9 — Verified formula-plot mode (headless)   (IN-PROGRESS)

**User pivot.** The OWUI demo should: (1) render a PASSING plot as real inline Python in OWUI's own sandbox, not the verifier-served HTML iframe; (2) show a BLOCKED case as a real verifier rejection, not a confused-model passthrough; (3) use self-contained FORMULA prompts, not dataset (`sales.csv`) references. User's two calls: the sandbox runs the VERIFIER's canonical script (model authors intent, verifier authors the executed bytes → guarantee intact); KEEP both formula + dataset modes first-class. M9 = headless verified-formula pipeline; M10 = OWUI sandbox execution + demo (gated).

**Thesis (formula mode — same discipline, sharpened).** Untrusted model proposes ONLY `{formula, domain, encoding}` — no point values, no Python. Verifier PARSES the formula into a closed verifier-owned AST, EVALUATES exact (`Fraction`) over the declared domain, quantizes once (HALF_EVEN) into the plotted table, verifies, and EMITS its own fixed-template matplotlib SCRIPT inlining only the recomputed point literals. "Model lies about plotted values" → impossible (verifier owns every point). "Model smuggles code" → impossible (formula parsed, never Python-executed; emitted script is verifier-authored positive-allowlist). Claim: *at every declared sampled x the closed evaluator produced the certified y under the declared numeric + rounding profile* — NOT finiteness/continuity/monotonicity BETWEEN samples, NOT formula-vs-NL-intent. TCB unmoved: matplotlib/Pyodide/browser/pixels stay trusted display (verifier emits script BYTES, never runs them); the executed script is verifier-authored, so pixels are trusted-not-proven exactly like today's SVG.

**Gate: none (headless verifier core).** M1–M8 REVIEWED, gate green; the formula core (schema/parser/eval/checks/cert/archive/replay/service) is hardware-free + pytest-gated like M1–M5. No new verifier runtime dep — matplotlib/sympy/mpmath stay OUT (verifier emits script bytes; the sandbox owns matplotlib). M10's OWUI execution is gated on browser-live `execute:python` (source-confirmed feasible; live proof = M10's first unit).

**Key decisions (do not re-derive):**
- **Contract** — new strict `FormulaPlotSpec` (NOT nullable dataset fields on `VPlotSpec`: mixed/empty states forbidden); internal source union `DatasetPlotSpec | FormulaPlotSpec`; dataset decoder byte-unchanged; formula endpoint own strict decoder. v0.1 shape `{version:"vplot-formula-0.1", formula, domain:{start,stop (decimal-str), samples>=2, x_scale, y_scale (int)}, numeric_profile:"rational-half-even-v1", mark:"line"|"scatter", encoding: x/y quantitative fixed to fields "x"/"y"}`; decimals as bounded strings (never JSON float); no color/facet/label/url/style; model supplies no points.
- **Parser** — HAND-ROLLED bounded recursive-descent (Pratt) + immutable AST; NEVER Python `eval`/`ast.compile`/sympy (sympy `sympify`/`parse_expr` call `eval`; `ast.parse` admits the whole Python surface + C-stack risk). Grammar (exact-rational-first): `sum := product (("+"|"-") product)* ; product := unary (("*"|"/") unary)* ; unary := ("+"|"-") unary | power ; power := primary ("**" SIGNED_INT)? ; primary := NUMBER | VAR | "abs" "(" expr ")" | "(" expr ")"`. Variables = a caller-supplied identifier allowlist (VAR), NOT hardcoded — formula binds `{x}`, the M11 `derive` transform binds column names; power binds tighter than unary (`-x**2` = `-(x**2)`); integer exponent literal only; no implicit mult; consume whole input; AST-depth check BEFORE each recursion (stack-safety). Limits: bytes/tokens/nodes/depth/paren-depth/digits/exponent/identifier-len/work.
- **Shared expression engine (multi-variable, reusable — realized by M9.2+M9.3)** — the parser + exact evaluator are a REUSABLE subsystem, NOT formula-only: `parse_expr(text, allowed_vars) → AST` (allowlisted identifier set as a parameter) + `eval_expr(ast, binding {var → exact Decimal/Fraction}, limits) → exact value`. TWO consumers: (a) formula mode (M9) binds `{x}` over a sampled domain; (b) a `derive` transform (M11, dataset mode) binds column names per row → computed columns (`profit = revenue - cost`). Domain sampling + matplotlib emission are a formula-ONLY wrapper over the engine — keep them OUT of the engine core so M11 reuses it unchanged. Same exactness/quantize/allowlist for both consumers; the cumulative work budget (`max_formula_work_units`) is the EVALUATOR's alone — the parser is bounded structurally by bytes/tokens/nodes/depth/paren/digits and carries no work meter (M9.2, settled).
- **Numeric (exact-rational-first)** — internal exact `Fraction` (reuse `eval.py` machinery) for literals/domain/positions/`+ - * /`/int-power/abs; div0 reject; bound numerator/denominator bits + intermediate magnitude; charge work before each op; never touch ambient decimal context. Sampling: `q_i = start + i*(stop-start)/(n-1)` → quantize x to `x_scale` HALF_EVEN → canonicalize `-0` → require first/last = canonical domain endpoints + all x STRICTLY increasing (quantization collision = fail) → evaluate at the canonical x (not a hidden unrounded x) → quantize y once to `y_scale` HALF_EVEN → fail-closed on undefined/OOB/unquantizable. **TRANSCENDENTALS (sin/cos/tan/exp/log/non-perfect-square sqrt/pi/e) REJECTED in v0.1** — irrational, not Decimal-exact; deferred to a later separately-versioned interval-certified profile (directed lower/upper bounds, quantize both, accept only on agreement else raise precision within budget or fail; two-precision agreement is not a correct-rounding proof). USER NOTE: "basic math plot" = polynomial/rational (covered); trig deferred — surfaced to user; a trig profile is a later unit/milestone if prioritized.
- **Script emitter** — new `matplotlib_script.py` (NOT in `render.py`): fixed-template positive-allowlist — fixed imports + noninteractive backend + ONLY verifier x/y literals + one fixed line/scatter call + fixed styling + fixed LINEAR scales + explicit x domain + fixed labels + canonical UTF-8/whitespace/quoting/trailing newline; NO model bytes/formula-source/comments/paths/urls/`eval`/`exec`/`compile`/`open`/`import`/network/subprocess. Pre-emit `render.float64_fidelity`: every intended float64 finite + round-trips to the declared-scale Decimal + x stays strictly increasing + endpoints pass the declared-scale check; emit the shortest round-tripping repr. Claim = "display projection preserves each certified point at the declared Decimal scale" (NOT exact binary64 equality, NOT pixels). Bytes → `matplotlib_script_hash`.
- **Provenance** — 4 bindings: `formula_hash` (domain-separated over canonical RESOLVED formula-source bytes = grammar version + canonical AST + domain + resolved sample schedule + numeric profile + scales + rounding; NOT raw Python), `spec_hash` (full formula spec incl mark/encoding), `plotted_table_hash` (reuse typed-NDJSON canon), `matplotlib_script_hash` (exact emitted bytes). **VCert v0.3** source/artifact-aware: `source: DatasetSourceCert | FormulaSourceCert`, `artifact: VegaArtifactCert | MatplotlibScriptArtifactCert`, source-aware TCB; new MIME `application/vnd.figure-verification.vcert.v0.3+json`; datasets KEEP v0.2 (+ its verify/replay). TCB adds grammar/evaluator/script-template versions; matplotlib+Pyodide NOT in the verifier TCB. (Execution provenance if ever wanted = a SEPARATE signed execution receipt `{runtime versions, output-image hash}`, never folded into the formula cert.)
- **Archive v4** (v3→v4 migration) — source-tagged `DatasetPlotBundle | FormulaPlotBundle`; formula roles = `{canonical_spec, formula_source, plotted_table, verdict, matplotlib_script, vcert_payload, vcert_envelope, tool_versions, public_key}` — NO fabricated csv/manifest/vega/svg roles; mode-specific required-role validation; quota/accounting preserved.
- **Replay** — formula replay REPARSES/RE-EVALUATES/RE-EMITS from the archived canonical formula spec (NOT the stored table/script → comparison targets only); compares formula/spec/table/script hashes + exact cert payload + TCB; v0.2 dataset replay byte-unchanged; AST purity (no service import) preserved.
- **Checks** — TRANSFER `{resource.plotted_cells/render_rows/smt_terms/attestation_bytes, sort.canonical_order (ascending x), formal.solver_completed, encoding.fields_exist_in_plotted_table + axis_types_match_fields, method registry, evidence only after all-pass}`. NEW: schema/parser `{formula.grammar_allowed/names_allowed/functions_allowed/exponents_bounded/domain_ordered/domain_bounded}`; resource `{formula_bytes/tokens/ast_nodes/depth/samples/work/intermediate_bits, matplotlib_script_bytes}`; deterministic `{formula.hash_matches_source/sample_points_strictly_increasing/values_defined/values_bounded/rounding_unambiguous/points_match_recomputation, render.float64_fidelity}`; construction `{security.no_arbitrary_code, formula.points_from_recomputation, render.axes_linear/x_domain_exact/points_match_evidence/matplotlib_script_allowlisted}`. REWRITE the `checks.py` construction affirmation ("spec is pure data … no expr/script field" — FALSE once a formula string exists) → "formula text parsed to a closed verifier-owned AST + interpreted directly; never Python `eval`/`exec`/`compile`/import/attribute/dynamic-call." Bar-zero/legend-domain obligations inapplicable to one-series line/scatter.

**Reuse map (module → treatment):** `schema.py` reuse `_Base`/strict-decode/tuple-bounds/dup-key-reject + add `FormulaPlotSpec`/union · `canon.py` reuse `Table`/fixed-scale-Decimal/table-hash/deterministic-encode + add formula-hash domain · `ingest.py` BYPASSED (formula reads no CSV/manifest) · `eval.py` KEEP `evaluate_run`, ADD `evaluate_formula_run` (reuse `_WorkBudget`/`Fraction`/HALF_EVEN/canonical-sort) · `checks.py` add `DatasetEvidence`/`FormulaEvidence`, keep registry/report/trace/resource-map · `render.py` KEEP dataset Vega, formula script → new module (reuse prepare/build/formal split + immutable prepared artifact) · `limits.py` extend `VerificationLimits` (formula/parser/sampling/script) · `attestation.py` reuse `sign`/`verify_dsse`, add v0.3 wrappers, keep v0.2 · `formal.py` reuse solver orchestration + `sort.canonical_order` · `service/pipeline.py` tagged `Outcome` union, dispatch dataset/formula · `service/app.py` add `/verify-formula` + `/propose-formula` (dataset routes + pin unchanged) · `service/model_client.py` factor common bounded exchange, add formula prompt (forbid Python/points/Vega/script) · `service/settings.py` mirror new limits · `service/archive.py` v4 + `FormulaPlotBundle` · `service/replay.py` + `replay.py` add formula path · `service/models.py` source-specific request/result types.

**Sizing:** historical impl peaks ~122–137K; units target ≤~140K (≤~58% of 240K), fine per-module granularity per the M1 right-sizing rule (over-large units overflowed M1/M4; M5 ran 20 fine units at 45–80% cleanly). 13 headless units.

### Units (M9.4 next; M9.1–M9.3 DONE, rest OPEN, gate-independent)
- **M9.1 — formula contract + limits + hashes. DONE** (`main=55%`, `impl=77%`). `FormulaPlotSpec`/`FormulaDomain`/`FormulaEncoding` + `_decode[T]` shared mechanics + `decode_formula_spec`; `DatasetPlotSpec` alias + `PlotSpec` union (VPlotSpec NOT renamed → zero ripple); 12 formula limits (auto-exposed as `VERIFIER_*` via `settings.py`'s `__struct_fields__` splat); canon `FormulaSource` + 9-line `formula_source_bytes` + `formula`/`matplotlib-script` domains; corpus f01–f06 + fb01–fb20 (14 decode / 6 deferred). 1879 tests, 100% branch.
  - Decode is SHAPE-ONLY by design — ordering, endpoint representability, grammar, names/functions/exponents, sample distinctness all decode fine and are M9.2–M9.4's to reject (fb15–fb20 encode exactly that).
  - `DecimalText` carries NO `max_length`: its grammar self-bounds at 29 chars, so a cap could never bind. Pattern-unbounded aliases (`FieldName`/`DatasetName`) still need theirs.
  - **Check ORDER is a corpus obligation**: `formula.domain_ordered` MUST be evaluated before `formula.sample_points_strictly_increasing` — a reversed domain always also yields a descending schedule, so no fixture can isolate them (fb17 + `examples/README.md` record this).
  - Deferred deliberately: `schema/vplot-formula-0.1.schema.json` export → M9.12 (proposer guidance); `POC_SCOPE`/`VPlot_SEMANTICS` formula claims → M9.13. VCert keeps 4 slots until v0.3 (M9.6) — canon hashing them ≠ certifying them.
- **M9.2 — bounded lexer/parser + immutable AST. DONE** (`main=44%`, `impl=100%` — impl crossed the 240K boundary during fix pass 2, peak 239K; size M9.3 smaller or split it). `expr.py` (617→~640 lines): hand-rolled recursive-descent `sum → product → unary → power → primary`, frozen/kw_only AST (`Number`/`Variable`/`Neg`/`Abs`/`Pow`/`Binary`, PEP 695 recursive `Expr` alias), `parse_expr(text, *, allowed_vars, limits) → ParsedExpr(ast, tokens, nodes, depth, paren_depth)`, `print_expr` canonical prefix form, `GRAMMAR_VERSION = "expr-0.1"`, `FUNCTION_NAMES = {"abs"}`. Imports only `fractions`/`typing`/`msgspec`/`verifier.errors`/`verifier.limits` — no `eval`/`exec`/`compile`/`ast`/sympy reachable (purity test parses the module's own source and asserts disjointness from the forbidden-name set). 2008 tests, 100% branch (`expr.py` 369 stmts / 124 branches).
  - **Parser-owned ABSOLUTE ceilings** (`_MAX_FORMULA_AST_DEPTH=64`, `_MAX_FORMULA_PAREN_DEPTH=64`, `_MAX_FORMULA_DIGITS=512`), validated by `_validate_limits` as the FIRST statement of `parse_expr` — before allowlist, byte, and lexer work. Operator policy above a ceiling is trusted-caller misuse ⇒ native `ValueError` naming the field, NEVER a silent clamp. Reason: the 12 `VerificationLimits` formula fields are operator-settable up to the generic signed-64 bound, so depth/paren policy alone could admit ≤1024-char `FormulaText` that escaped as `RecursionError`, and digit policy could admit literals that escaped as ambient int↔str `ValueError`. 512 digits stays under CPython's MINIMUM legal `sys.int_info.str_digits_check_threshold` (640) ⇒ conversion-safe at every legal interpreter setting, verified in a child process with `PYTHONINTMAXSTRDIGITS=640`. Bytes/tokens/nodes/exponent get no ceiling (reasoned, commented): they drive neither recursion nor conversion — `max_formula_exponent` is a *value* bound checked after the 512-digit admission, so `int()` never sees more than 512 digits.
  - **Stack headroom, measured on the JOINT `(depth, paren_depth)` composition** (the true worst shape — single-axis shapes understate it): **267** active calls at the 32/32 defaults, **523** at the 64/64 ceilings, printer **65**, against CPython's default 1000-frame limit. MAIN's independent recursion-limit bisection agreed (526 limit for the compound worst; reviewer profiled 523 active over 448 full-budget wrapper compositions). Basis assumes the default limit; a process lowering it below ~527 invalidates it. Earlier "≤201 frames / near 400" figures were measured on non-joint shapes and are superseded.
  - **Direct-construction guards.** `Variable.__post_init__` enforces the ASCII-identifier invariant ⇒ `Variable(name="(add x 1)")` cannot exist, so `print_expr` injectivity holds over the typed public algebra with no caller precondition. `Number.__post_init__` (numerator + denominator) and `Pow.__post_init__` (exponent) reject magnitude ≥ `10**512` by INTEGER comparison against a precomputed constant — never `str()`/`len(str(...))`, since measuring digits by conversion would raise the very error being guarded. Guards admit exactly what the parser admits (512-digit integer, `0.` + 511 digits, 512-digit exponent all still parse). Deliberately NO validating walk in `print_expr` and no signature change: a hand-built AST deeper than the ceiling is trusted misuse, documented as a precondition, and no production path builds one (M9.3 evaluates, M9.4/M9.6 hash parser output, M9.9 reparses archived source, M11 parses `derive` text).
  - **Effective expression envelope** (M9.3/M9.4/M11 sizing + corpus authoring): `max_formula_tokens=256` binds long flat sums first, and because a left-associative chain's AST height equals its term count, `max_formula_ast_depth=32` caps a flat sum at ~31 terms. Ample for polynomial/rational plots; operator-tunable up to 64.
  - **Canonical normalization is exactly** whitespace, redundant grouping, decimal-literal spelling (lowest-terms `Fraction`), unary plus, and integer-exponent sign/leading-zero spelling — no constant folding or algebraic rewrite. That list is a provenance claim: `canon.FormulaSource.ast` hashes this text, so printer injectivity + determinism are provenance-critical. Goldens re-verified unchanged after both fix passes (`-x**2 + 3*x - 2` → `(sub (add (neg (pow x 2)) (mul 3 x)) 2)`, `007.500` → `15/2`).
  - **Review: two rounds, both blockers closed.** Pass 1 raised elevated-policy `RecursionError` + native conversion `ValueError` (blocking), printer overflow on a legal deep AST, injectivity precondition, incomplete normalization list — all fixed above. Pass 2 confirmed the closures and added: direct-construction bypass (fixed structurally for conversion, documented for depth), plus two mutation-proven TEST gaps — a defect firing only at joint `(64,64)` and moving `_validate_limits` after `_lex` each left all 108 parser tests green. Both now pinned (three joint-boundary witnesses asserting `(depth, paren_depth) == (64, 64)`; a `_lex` spy proving zero untrusted-text work under over-ceiling policy). Lesson worth carrying: **a boundary test suite can be 100%-branch-green and still miss the compound maximum of two independent bounds** — pin the joint corner explicitly, and mutation-test the ORDERING of a fail-fast guard, not just its presence.
  - **REJECTED (do not revisit): a parser work meter on `max_formula_work_units`.** Parse cost is bounded by admitted source bytes + tokens/nodes + the fixed 512-digit ceiling (trusted allowlist validation is separate and caller-fixed), so a second accounting authority adds no guarantee and would collide with M9.3's cumulative evaluator budget. The reviewer independently agreed after attacking it. **The M9.2 unit line's "work limits" phrase was the defective artifact** — `limits.py` (M9.1, reviewed) already assigns `max_formula_work_units` to M9.3; wording reconciled here and in the scope line above.
  - Clean negatives held under both rounds: no execution/reflection surface reachable; default-policy hostile text always structured (incl. lone surrogate `"\ud800"` → `formula.grammar_allowed`); declared grammar/precedence correct (power binds tighter than unary minus, `**` non-associative + integer-only, binaries left-associative, implicit multiplication rejected); canonical form locale/Decimal-context-free; the Hypothesis round-trip oracle is a test-side infix printer sharing no production code; corpus assertions driven from `examples/index.json` (fb15/fb16/fb19 parser-layer, fb17/fb18/fb20 clean-parser controls deferred to M9.3/M9.4).
- **M9.3 — exact sampler + rational evaluator. DONE** (`main=100%` 241K/240K, `impl=53%` 128K/240K — 4 sessions, 3 died mid-unit; high-water basis). `work.py` (27 stmts) = consumer-neutral run-local atomic `WorkBudget` + structured `WorkBudgetExceededError`; `expr.py` = exact `Fraction` interpreter `eval_expr(node, binding, limits, *, budget=None) → Fraction` (`ExactValue = Decimal | Fraction`, `ExpressionEvaluationError` carrying `work_units`); `eval.py` = `evaluate_formula_run → FormulaEvaluationRun{table, parsed, formula_source, work_units}` + exact-integer HALF_EVEN `_quantize_fraction`, with `_WorkBudget` reduced to a thin adapter preserving dataset error bytes. 2223 tests, 100% branch (5650 stmts / 1240 branches).
  - **Work tariff (authoritative; ONE cumulative budget spans a whole run).** Preflight = 0 (domain ordering, sample-count, endpoint bits, parsing, schedule-span). Charged 1 each: sample-position construction · x quantization · x admission · `Number` · `Variable` · `Neg`/`Abs` · every binary node · y quantization · row admission; `Pow` = `1 + abs(exponent)`. ⇒ successful sample = `5 + AST tariff`; formula `x` = `6 * samples`. **Charge always precedes the operation's guards** (a refused atomic charge consumes nothing and reports the prior cumulative; an admitted-but-failing operation retains its full charge). Tests pin literal integers, never a production cost helper.
  - **Check order** (pinned by the oracle's precedence parity): `formula.domain_ordered` → `resource.formula_samples` → domain-endpoint bit admission → `parse_expr` → schedule construction/admission (`formula.domain_bounded`, `formula.sample_points_strictly_increasing`) → per-row exact evaluation → y quantization → row admission.
  - **Quantization is total** over the admitted domain: exact integer `divmod` + tie-to-even on `2*remainder` vs denominator, source sign restored — no `Decimal.quantize`, precision search, float, or NaN/inf branch. `_scaled_int_to_decimal` takes digits from `Decimal(abs(scaled)).as_tuple().digits`, never `str(int)` ⇒ CPython's integer-string ceiling (`PYTHONINTMAXSTRDIGITS`) cannot reach it; hostile ambient `decimal` precision/traps produce identical tables and work counts.
  - **Oracle independence + claim boundary.** `tests/formula_oracle.py` = iterative postorder machine with its own HALF_EVEN integer parity; imports no `verifier.eval`/`verifier.work`, no production quantizer, no `round`/`Decimal.quantize` (statically asserted); shares only the pinned AST + contract types. 64,480-point cross-product over limits × formulas/domains/scales/sample counts → **zero unexpected divergences**; 11,513 points were expected production-only `resource.formula_work` refusals. Agreement is an END-TO-END public-evaluator outcome comparison — it evidences no individual internal admission site and never compares `work_units`.
  - **Mutation review** (two independent lenses: correctness/claims + mutation/determinism) ran **109 behavior-valid mutants → 79 killed, 30 survived**; 29 were committed-TEST gaps (now closed) and 1 was equivalent — a provably behavior-neutral dead negative-exponent numerator/denominator swap, deleted from `expr.py`. **No survivor was a production defect.** Survivor classes worth re-probing on any future metered evaluator: charge-ordering (charge moved after the guarded body), per-stage bound deletion (only the FINAL result still checked), power-preflight comparison/allocation, and process-determinism (hidden `str(bigint)`, ambient `Decimal` rounding on ties, `hash()`/global sequence in error text). Each new test proved non-vacuous by re-applying the exact mutant, confirming red, then byte-restoring the recorded SHA-256.
  - **Witness-impossibility class (reusable).** For the span/domain-start/domain-stop intermediate-bit sites, a "single over-limit quantity while every later-checked quantity fits" witness is IMPOSSIBLE — offset at `i=n−1` equals the span, position at `i=0` equals the start, position at `i=n−1` equals the stop. Discriminate such sites by stage-identifying exact-work/no-start witnesses instead: restored code fails at work 0, and deleting each guard shifts the same failure to work 3/1/3.
- **M9.4 — formula verification spine.** formula checks + `FormulaEvidence` + source-tagged evidence union + encoding restrictions + resource traces + canonical row-order obligation (reuse formal); no script from failed evidence. Accept: method-aware results; evidence only after all-pass; good/bad corpus; gate green.
  - **SPLIT FIRST (scout-pinned sizing; as worded this unit exceeds one window).** **M9.4a** = evidence/trace + registry foundation: `RecomputedEvidence` → `DatasetEvidence` (identical fields; keep an alias for zero ripple) + `FormulaEvidence{formula_source, formula_source_bytes, formula_hash, spec_hash, plotted_table, plotted_table_hash, results}` + `Evidence` union, exact method/resource registry inventory, dataset-side type narrowing, no behavior drift. **M9.4b** = formula verify + formal gate: evaluator result/error mapping, encoding/resource/construction checks, ascending-x facts + orchestration, good/bad corpus, evidence/prepared-artifact all-pass gates. Evaluator API changes needed for failure traces ⇒ a small PRE-unit, never hidden inside M9.4b.
  - Entry point is a SEPARATE decoded-spec `verify_formula_run` — `verify_run`'s manifest/`data_dir`/dataset args are mandatory and must not become nullable. Service dispatch stays out (M9.10); archive bundle shape stays out (M9.7).
  - **`formal.py` imports `checks.make_result` ⇒ `checks.py` must never import formal** — put ascending-x orchestration in a separate preparation seam. Solver needs no change: `RowOrderFacts(rows=((RankedCell(False, Fraction(x)),), …), directions=("ascending",))`; equality is not an inversion there ⇒ it proves NONDECREASING x, so `formula.sample_points_strictly_increasing` remains the strictness authority. `bar_zero`/`legend_domain` = `None` (formula marks are line/scatter, encoding is x/y only).
  - **Registry**: the shorthand above omits three REAL parser failure IDs that must also be registered — `resource.formula_digits`, `resource.formula_identifier_bytes`, `resource.formula_paren_depth` (unregistered ⇒ `make_result` fails closed as drift).
  - **Honesty gate**: `formula.values_bounded`, `formula.rounding_unambiguous`, `formula.points_match_recomputation` have NO active witnesses under the current run/error shape (success returns table + `ParsedExpr` + source + total work; failure carries only check/message/work — no unquantized rationals, rounding decisions, bit high-water, or second point set). Either extend the evaluator trace or classify them honestly as successful-evaluator/construction affirmations; calling them independent comparisons would overclaim. `formula.hash_matches_source` has no model-declared expected hash ⇒ its meaningful form is evidence-internal binding of `formula_source_bytes` to the stored `formula_hash`.
  - Construction affirmation at `checks.py:212-214` ("spec is pure data … carries no executable path") is already FALSE for `FormulaPlotSpec.formula` ⇒ split it by mode. Dispatch dataset/formula affirmations separately to hold dataset Verdict/attempt byte identity (VCert stores only `{id, method, status}`, so message edits leave v0.2 cert bytes unchanged).
- **M9.5 — matplotlib script emitter.** `matplotlib_script.py` fixed-template positive builder + `render.float64_fidelity` gate + exact x domain + line/scatter allowlist + script byte-limit/hash; golden scripts + static negative tests. Accept: byte-golden scripts inline only verified points; fidelity gate blocks non-round-tripping; no forbidden op emittable; gate green.
- **M9.6 — VCert v0.3 + DSSE routing.** source/artifact-aware cert + formula TCB + new MIME + generic signing wrappers + v0.2 back-compat; canonical payload/envelope vectors + tamper corpus. Accept: formula cert binds 4 hashes + methods + TCB; v0.2 verify/replay intact; one-byte mutations move plot identity; gate green.
- **M9.7 — archive v4 schema + role model.** v3→v4 migration + source-tagged bundles + formula roles + mode-specific required-role validation + quota/accounting preserved + old-archive migration tests. Accept: formula bundle stores only real roles; v3 archives migrate; dedup/quota/FK/immutable intact; gate green.
- **M9.8 — formula materialization + signed attempts.** build `FormulaPlotBundle` from one evidence/script/cert chain; formula routes/outcomes into signed attempt manifests + retrieval; atomic publish + failure capture. Accept: verified/rejected formula attempts round-trip + audit-diagnose across restart; injected rollback leaves zero rows; gate green.
- **M9.9 — pure formula replay.** authenticate v0.3 formula snapshots, independently reparse/recompute/re-emit, compare formula/spec/table/script/cert/TCB; v0.2 dataset replay unchanged; AST purity (no service import). Accept: exact replay from the archived formula spec; stored table/script cannot steer; wrong-key/mutation/version-drift caught at the right layer; gate green.
- **M9.10 — service formula verify pipeline.** source-aware `Outcome`/prepared-artifact union; formula verify/sign/archive path; formula result models; settings threading; admission; `POST /verify-formula`; never a script on failure. Accept: /verify-formula 200-verdict contract (decode failure = 200) + resource/formal fail paths + OpenAPI; dataset routes byte-unchanged; gate green.
- **M9.11 — archive replay adapter + HTTP retrieval.** thin `service.replay` formula adapter (lowest signed verified attempt) + script/spec/table/certificate GETs + replay verdict (no execution). Accept: verify→restart→replay reproduces table+script+cert (no chart yet); admission shared; unknown/corrupt fail closed; gate green.
- **M9.12 — formula proposer.** factor common bounded model transport; formula-only prompt + `POST /propose-formula` (forbid points/Python/Vega output); lossless traces; dataset pin behavior unchanged. Accept: mock matrix + (live-NPU MAIN check) a formula prompt → schema-representable `FormulaPlotSpec` → verifies; dataset proposer unchanged; gate green.
- **M9.13 — no-execution capstone + M9 close.** full direct + model-proposed formula flow through archive/replay from empty state; corruption/resource corpus; `demo/` formula walkthrough (script downloadable + authenticated, NOT yet OWUI-run); doc drift (POC_SCOPE/VPlot_SEMANTICS formula claim + boundary; root/bench READMEs; memory M9). MAIN closes M9. Accept: capstone green from empty state; docs state the formula claim + the "script not yet executed in OWUI" boundary; gate green; M9 IMPLEMENTED.

**M10 (deferred — browser-live OWUI; planned when M9 REVIEWED): OWUI sandbox execution + formula demo.** Source-CONFIRMED mechanism: a trusted async OUTLET Function filter reads the verifier tool-result from backend-owned state → verifies script sha256/signature → calls `execute:python` RPC DIRECTLY (bypassing `sanitize_code`) with the verifier's canonical script → Pyodide (sandbox iframe `allow-scripts`, no `allow-same-origin`) runs it, patched `plt.show()` → base64 PNG → emits an inline message file → else falls through to the unverified-chart block. Keep `ENABLE_CODE_INTERPRETER`/`ENABLE_CODE_EXECUTION` OFF (the internal RPC is not gated by them; model-driven exec stays off); `ENABLE_PYODIDE_FILE_PERSISTENCE` off; `ENABLE_WEBSOCKET_SUPPORT` on; bound `WEBSOCKET_EVENT_CALLER_TIMEOUT`. `execute:python` NEEDS a live browser socket → the headless harness (`webui/client.py`, random session_id, no socket) returns "Client session disconnected" → sandbox render = OPERATOR/browser step (like today's chart render; agent-container GL blocked per M6.3/M7); headless tests cover the gate logic/provenance/rewrite only. `enforcement_filter.py` reworked into verify-authentic-result → execute → publish → replace-content, else block (it currently treats matplotlib as an unverified signal — the user-reported bug). 3 units: (1) live OWUI feasibility gate; (2) conditional execution integration + browser E2E; (3) live demo + banner/blocked-visibility + close.

**M11 (deferred — dataset-mode derived columns; planned when M9 REVIEWED, sequence adjustable): computed columns via a `derive` transform.** New requirement (user): dataset mode must express per-row cross-column arithmetic (`profit = revenue - cost`) — the v0.1 transform grammar (select/filter/group_by/aggregate/sort) has NONE (aggregation is per-group, not per-row). Design: add a `Derive` op to the `schema.py` Transform union `{output: FieldName (distinct), expr: formula-source, out_scale}`; evaluate per row by binding the referenced columns into the SHARED M9 expression engine (exact `Fraction`, HALF_EVEN quantize to `out_scale`) → append one exact column; NO reinvention. Provenance: `expr` canonicalized folds into `spec_hash` (like `formula_hash`); derived values ride `plotted_table_hash`; replay reparses + recomputes per row; reuses M9 checks/cert/archive/replay. OPEN for M11 planning: per-row fail-closed policy (one undefined/div0/null row → reject the plot vs. drop the row; likely reject, total-or-nothing); pipeline placement + interaction with group_by/aggregate (a per-row map, so allowed broadly but aggregated-column rules needed); null-cell semantics; derived output type (quantitative) + encoding eligibility + name-distinctness; whether the dataset proposer emits derive ops. Transcendentals gated as in formula mode (exact-rational-first; interval profile later). No hardware gate (headless, pytest-gated).

---

## M8 — Reliable real-model figures (schema-guided decoding)   (REVIEWED — closed)

Delivered per-request schema-guided decoding so the real weak NPU model reliably emits
schema-representable VPlot, turning the browser banner's outcome from tier-driven into prompt-driven.
Claim boundary UNMOVED: guidance is structure-only and adds no trust — the verifier still decodes
strictly, recomputes Decimal-exact, and re-binds the CSV by SHA-256. Pieces:
`model_backend/schema_guidance.py` derives the guidance schema at load from
`schema/vplot-0.1.schema.json` with `pattern` + `format` recursively stripped (OV's xgrammar backend
rejects VPlot's negative-lookahead patterns) and fails closed; `Engine.generate(…, guided)` applies
`StructuredOutputConfig` per request, so plain `/v1/chat/completions` chat stays unconstrained while
the verifier's `propose_spec` sends `guided_json: true`; `webui/launch.sh` offers two pinned prompts;
`enforcement_filter.py` reads OWUI's persisted `output[].content[].text`.

Durable facts (detail: memory M8, `bench/README.md`):
- Two DISTINCT blocked paths, never to be conflated: the banner's blocked prompt is caught by the
  bypassable `Verified Plot Guard` outlet (`BLOCKED_NOTICE`) when the model skips proposeSpec and
  emits raw matplotlib; a schema-valid-but-semantically-wrong spec is rejected by the verifier
  (`encoding.fields_exist_in_plotted_table`), shown backend-direct on `/propose-spec`.
- Live NPU bench, constrained default vs M3's unconstrained baseline: `verified_render` 0/100 ->
  26/100; reply shape fenced 97->0 and bare_object 2->100; de-fenced/JSON-valid 24->83; buckets
  schema=0.51 / semantic=0.23 / policy=0.00; faults 0. The guarantee is unchanged — 18/18 bad
  blocked, 10/10 good accepted. The historical 0->26 comparison spans the M5.1h generation-path fix
  and the M5-M7 verifier evolution, so attribution rests on the M8-review same-commit A/B (only
  `MODEL_BACKEND_STRUCTURED_OUTPUT` flips): RAW 0/100 -> GUIDED 26/100, `json_validity` 0.01->0.83,
  fenced 52->0, buckets schema 1.00->0.51 — guidance-attributable end-to-end, with the guarantee
  identical in both arms.
- Guidance forces STRUCTURE, never SEMANTICS: a spec can verify and still not answer the request;
  intent alignment stays outside the verifier.

Deferred, still open (each surfaced to the user, none in M8 scope): OWUI output-item-type robustness
(`webui/client.py` + `enforcement_filter.py` read single-`content`-item shapes positionally — inert
today, MEDIUM once a reasoning-capable model lands; fix by selecting `type="message"` /
`type="output_text"` by type, not position); operator-schema hardening (load-time meta-validation +
non-finite/duplicate-key strictness — safety-independent, since strict decode already prevents false
verification); bench-provenance overhaul + a paired current-commit raw-vs-guided A/B +
`tool_call_rate` rename.

Four units (M8.1, M8.2a, M8.2b, M8.3) landed at `impl=` 39-62%. Gate at close: ruff format 94 / ruff
check / mypy 94 / pytest 1,605 @ 100% branch. Unit trail, per-unit context, review pass:
`git log --grep "(M8[. ]"`.

---

## M7 — Interactive local-model browser instance   (REVIEWED — closed)

Delivered `webui/launch.sh`, a repo-root bash orchestrator that stands the whole PoC up with one
command: optional `--fresh` wipe of `.webui-data`; verifier (`uv run --locked python -m
verifier.service`, raised work-rate) -> `/health`; model tier — REAL `model_backend` (accel env +
OpenVINO `PYTHONPATH`, then `.venv-model/bin/python -m model_backend` DIRECTLY, because `uv run`
strips `PYTHONPATH`; device default NPU) XOR `--stub` (hardware-free), sharing `:8001` -> `/v1/models`;
`webui serve` -> `/ready`; `webui bootstrap`; a banner with browser URL + admin credentials; and a
SIGINT/EXIT trap that tears every child down and frees :8000/:8001/:8080. Every host path, device,
credential, port, and timeout is an env override with a confirmed default. Adds no verifier trust and
moves no claim boundary: Open WebUI, its function runner, the iframe/browser, and pixels stay trusted
display/orchestration per POC_SCOPE.

Durable facts (detail: memory M7):
- Child endpoints are DERIVED from `HEALTH_HOST` + the port vars and exported
  (`WEBUI_PROVISION_VERIFIER_URL`, `WEBUI_PROVISION_MODEL_BACKEND_URL`, `VERIFIER_MODEL_BASE_URL`,
  `VERIFIER_PORT`); hardcoding them broke port remapping in three places at once — provisioning, the
  chart `Location`, and the verifier's own model client.
- A `/dev/tcp` `port_in_use()` preflight refuses to start against an already-bound port, and it runs
  BEFORE the cleanup trap installs, so a colliding second launcher can never `fuser -k` a running
  stack.
- A `&`-backgrounded launcher inherits SIGINT=`SIG_IGN`, so its INT trap is inert; only SIGTERM/EXIT
  teardown is proven on that path (an operator Ctrl-C under a real PTY exercises the INT path).
- Open WebUI attaches no tool on its own: the browser frontend pre-selects the model's `meta.toolIds`
  and the chat backend honors only request `tool_ids`, so `bootstrap` converges the workspace model's
  `meta.toolIds` to `server:verifier` (create-or-merge, idempotent, fail-closed readback) — without
  it a browser chat silently ignores the verifier and answers with raw matplotlib.

Open follow-up (deferred through M8): whether a REAL inner-service crash always propagates to the
tracked `setsid` leader that `wait -n`/`kill -0` observe. Post-READY the final `wait -n` carries no
wall-clock timeout, so a leader outliving a crashed descendant HANGS rather than exits; the
exit-0-false-clean hazard itself is closed. Fix shape: confirm the leader dies with the child,
validate every tracked PID immediately before the READY banner, and switch the final wait to explicit
tracked-leader operands (`wait -n -p VAR pid…`).

The launcher unit landed at `impl=` 36%; M7.2 added only the MAIN-executed live walkthrough + operator
docs. `webui/` is bash plus coverage-excluded Python, so the gate held at ruff/mypy/pytest 1,564 @
100% branch (1,590 after the default-tool auto-attach fix). Unit trail, live evidence, review +
follow-ups: `git log --grep "(M7[. ]"`.

---

## M6 — End-to-end demo   (REVIEWED — closed)

Delivered `demo/e2e.py` + `python -m demo.e2e`: a hardware-free driver that spawns a REAL-socket
verifier against a tmp state dir and proves the three seed cases from a clean checkout — g01 ->
verified chart, five certificate hashes, `/chart`, restart, `/replay` exact; b07 -> blocked with
`field 'profit' does not exist in the table`; b13 -> a blocked policy verdict plus a crafted
`scale.zero:false` variant proving the misleading-baseline vector is UNREPRESENTABLE (decode-refused
unknown field), while `scale.bar_zero` rides every verified certificate as a `z3_smt` pass. Two
opt-in live legs extend it: `--with-webui` drives the persisted-chat leg through Open WebUI,
`--with-model` meters three seed prompts on the live NPU; both default OFF and are mutually
exclusive because stub and NPU backend share `:8001`. `WebUIClient.run_persisted_chat` + `python -m
webui chat --prompt …` landed here with the wire shape live-probed, not guessed: create `POST
/api/v1/chats/new` -> completion `POST /api/chat/completions` (background task) -> poll `GET
/api/v1/chats/{chat_id}` until `done`, final text at `output[0].content[0].text`, chart at
`embeds[0]`. Root `README.md` gained the PoC-acceptance sweep, quoting POC_SCOPE's modest claim
verbatim instead of restating it.

The layering is honest by construction: the deterministic layer proves the cases, and the live-NPU
layer records OBSERVATIONS, never bounds — the real weak model verified 0/100 here (M8.3's guided
default later reached 26/100, still a minority), so "model proposes -> chart renders" is not
reliably reachable model-first, and the demo says so.

Durable facts (detail: memory M6): live NPU greedy decode overruns the 20 s hardware-free hang guard,
so the model leg alone uses 180 s; `chromiumfish` capture is blocked in this container (software-GL
SwANGLE/Vulkan EGL init failure hangs even `--print-to-pdf`, rc=124), so browser rendering stays the
operator's step and DOM/CSP evidence is gathered textually.

Four units landed at `impl=` 49-69%. Gate at close: ruff/mypy 93 files, pytest 1,563 @ 100% branch,
`python -m demo` 13/13, `python -m demo.e2e` 3/3. Unit trail, live evidence, review pass:
`git log --grep "(M6[. ]"`.

---

## M5 — Formal + provenance hardening   (REVIEWED — closed)

Delivered the hardening spine over M1-M4: bounded resources, an SMT gate, signed certificates, a
durable provenance archive, and replay. Pieces: `limits.py` (frozen `VerificationLimits` +
`read_bounded`, threaded through ingest/checks/render/service/proposer) -> `checks.verify_run`
returning `VerificationTrace` + `RecomputedEvidence` -> an evidence-driven `prepare_render`/render
split that builds Vega exactly once -> `formal.py` (z3 4.16 behind the sole lint-enforced production
import) proving three obligations before render: final row order matches the active declared sort +
canonical tail, every quantitative positional channel on a bar carries a zero baseline, and a
discrete color legend's explicit domain equals the plotted categories -> VCert v0.2 (method-bearing
`CheckResult` over the closed vocabulary `schema_validation`/`resource_policy`/
`deterministic_recompute`/`construction`/`z3_smt`, plus a fifth hash binding the authoritative Vega
bytes) -> `attestation.py` (DSSE v1.0.2 PAE + PyCA Ed25519, exactly one signature) ->
`service/identity.py` (0700 state dir; one raw 0600 key created atomically, no-follow;
`keyid=sha256(public key)`) -> `service/archive.py` (STRICT SQLite, `journal_mode=DELETE` +
`synchronous=FULL`, one `BEGIN IMMEDIATE` per bundle, content-addressed blobs, trigger-maintained
logical quota) -> signed attempt bundles for every classified outcome -> `verifier.replay` (pure,
imports no service module) + `service/replay.py` + `GET /replay/{plot_id}` -> the operator `audit`
CLI -> `tests/test_e2e_hardening.py` + the hardware-free `demo/` walkthrough.

Claim discipline (full boundary: POC_SCOPE.md; mechanics: module docstrings):
- SMT is a second bounded checker over the concrete recomputed table, not a proof of evaluator or
  renderer correctness. Z3 joins the TCB; `sat` yields a readable counterexample; `unknown`,
  timeout, and exception fail closed. Aggregation stays exact deterministic recomputation —
  encoding it in SMT would add a less transparent duplicate implementation, not assurance.
- Authenticity means "the holder of the private key matching this independently pinned public key
  produced these bytes" — no operator identity, PKI, timestamp authority, append-only/completeness,
  or transparency-log claim. `keyid` is a lookup hint, never a trust decision; an archived key
  proves storage self-consistency only, so trust resolves from the current signer plus explicitly
  pinned historical keyids.
- Every resource bound is LOGICAL: `VERIFIER_MAX_ARCHIVE_BYTES` (1 GiB default) counts typed payload
  bytes and explicitly not SQLite pages, journals, or filesystem overhead; a full quota refuses with
  507 and never evicts audit history.
- Replay re-executes from archived bytes through the current verifier. `exact` requires all five
  artifact hashes plus byte-exact VCert payload with no TCB drift; version drift alone is `drift`;
  native SVG equality is diagnostic only; the weak model is never re-run.
- WAL stays unused deliberately: rollback-journal `DELETE` commits are documented atomic, while the
  multi-connection WAL-reset bug reaches SQLite 3.51.2.

Twenty units (M5.1a-M5.5e) held cross-layer work to one module each; the six carrying records landed
at `impl=` 45-80%. Gate at close: ruff format/check 0 (90 files), mypy 0, pytest 1,545 @ 100% branch
(1,044 branches, 0 missing), `python -m demo` 13/13. Unit trail, per-unit context, review ledger +
post-close hardening: `git log --grep "(M5[. ]"`.

---

## M4 — Open WebUI integration   (REVIEWED — closed)

Delivered the Open WebUI 0.10.2 integration without moving the verifier claim boundary: Open
WebUI, its function runner, iframe/browser, Vega runtime, and pixels are trusted display /
orchestration; only the verifier's validated spec, recomputed table, emitted Vega-Lite, and
certificate are mutually checked. Pieces:

- verifier chart surface: every verified render builds an offline page with the Open WebUI
  `iframe:height` reporter; an independent `html_cap` LRU serves it at
  `GET /chart/{plot_id}` under `Content-Security-Policy: sandbox allow-scripts`; a clean
  `public_base_url` drives the absolute chart Location;
- `POST /propose-spec` verified success = Open WebUI's Location-variant
  `[ProposeResult, summary]` JSON body under `Content-Disposition: inline`; failures remain
  bare structured results with no embed; the hand-authored OpenAPI description + response union
  are golden- and consumer-validated;
- repo-root `webui/` harness: separate Python-3.12 Open WebUI executable, hermetic canonical
  child env, global backend-called OpenAPI server exposing only `proposeSpec`, legacy headless
  function calling, signup-or-signin provisioning, exact-source active/global filter convergence,
  deterministic hardware-free model stub, CLI, and operator recipe;
- `Verified Plot Guard`: a stdlib-only heuristic outlet classifier for common direct-chart forms.
  It is explicitly bypassable and false-positive-prone - a usability guardrail, never authority or
  evidence of verification.

Live evidence (durable observations, not reliability bounds): clean provisioning + idempotent
rerun found the model and `server:verifier`; the NPU model selected `proposeSpec` on 5/10 fixed
prompts and verified 0/10 (four fenced undecodable specs, one missing argument). The scripted
non-model fixture then proved the successful selector → tool → verifier → lean-context chain,
persisted chart Location, CSP + height reporter, and Chromium-rendered sandboxed chart (no
`allow-same-origin`). The real NPU reply also proved the filter-on blocked / filter-off
byte-preserved differential. Exact standup = `webui/README.md`; external-contract facts =
memory M4.

Milestone review read all 39 trace-keyed M4 commits + final state and accepted four hardening
findings: canonical URL/host validation now rejects ambiguous/misjoined endpoints; the load-bearing
`ENABLE_API_OUTLET_FILTERS=true` setting is explicit; auth/readback/function transport + malformed
UTF-8 responses stay inside `WebUIProvisionError`; POC_SCOPE now states the independent
certificate/spec and chart LRUs. Post-fix live rerun against installed 0.10.2: clean bootstrap
twice, exact outlet env observed in the child, block/pass differential, successful legacy-FC
tool/verifier chain; services/state cleaned, ports free. Full locked gate: 858 tests, 100% verifier
branch coverage. Unit/planning/review-follow-up trail: `git log --grep "(M4[. ]"`.

---

## M3 — Local model proposer + failure eval   (REVIEWED — closed)

Delivered the UNTRUSTED weak proposer in front of the M1/M2 verifier — claim boundary UNCHANGED
(the model supplies NO data values; verify recomputes the whole plotted table + rebinds the CSV
by hash; POC_SCOPE "## Model proposer" holds the contract). Pieces: `model_backend/` (repo-root
Litestar+uvicorn OpenAI-`/v1` wrapper over the installed `openvino_genai.LLMPipeline`, NPU-served
local INT4_SYM Qwen2-0.5B re-export — the NPU switch landed mid-milestone as a direct task;
hardware-gated, coverage-excluded, unshipped) → `service/model_client.py` (async `propose_spec` →
typed proposal with raw reply bytes, never VPlot-decoded client-side) → `POST /propose-spec`
(typed body → reply → `decode_stage` → dataset-name PIN at decode time → `verify_decoded` → `render_outcome`; the
pipeline split into those reusable seams) → repo-root `bench/` (100-prompt failure eval + the
deterministic two-corpus guarantee; classifiers/digests/exit-code locked by
`tests/test_bench_harness.py`). Error split: every extracted reply rides a 200 verdict (decode
failure = the metered model failure); 404 unknown dataset / 503 unreachable / 502 unusable reply
OR off-request pin / 400/415/405 transport misuse = problem+json; a broken trusted manifest = the
500 the model cannot provoke. Backend pick (OpenVINO over the seed's "Ollama", user-confirmed),
device/model/run facts + rejected-finding rationale: memory M3 + `bench/README.md`.
680 tests / 100% branch. Unit trail, per-unit context, review pass:
`git log --grep "(M3[. ]"` (+ `babe6da`/`f53bd0c`/`5936cad`, the NPU switch). Units landed at
45–81% of 200K.

**Eval evidence (live NPU: the M3.4b run + the M3-review re-run that validated the good-corpus
leg).** Served `Qwen2-0.5B-Instruct-int4-sym-ov` (NPU, greedy temp=0, 100 fixed ordered prompts;
recipe `bench/README.md`; reports/ gitignored — these numbers are the durable record; exit 0
both runs). **GUARANTEE CONFIRMED**: bad corpus 18/18 blocked (`false_accept=0`) AND good corpus
10/10 accepted (`false_reject=0`; leg added at M3 review — without it a reject-everything
verifier would satisfy the bad bound vacuously), 0 transport errors, both corpora
size+identity-digest pinned. **Observations** (n=100 HTTP-200 verdicts; NOT a bound):
`tool_call=0 json_validity=0 verified_render=0`; buckets `schema=1.0 semantic=0 policy=0`;
faults `off_request=0 upstream_fault=0 harness_error=0`; top failing check `spec.decode` (100).
Reply shape isolates WHY: `fenced=97 bare_object=2 other=1 empty=0`, de-fenced only 24/100 parse
as JSON — the weak proposer is 100% unreliable at strict VPlot JSON, the dominant failure
SYNTACTIC (markdown fence). The review re-run's summary reported an exact repeat of every
model-side number (independent server processes, same device+config — consistent with the
per-(device,config) determinism design; session-logged only, like all eval numbers here). So the
untrusted model EXERCISES the pipeline without weakening it — the deterministic verifier bound
is untouched by a fully-failing proposer. **(M8.3 supersession note):** this raw `0/100` is the
honest UNCONSTRAINED baseline; M8 ships schema-guided decoding as the DEFAULT and re-measured
`verified_render=26/100` on the same live NPU (fence failures `97→0`), with the guarantee unchanged
(18/18 blocked, 10/10 accepted) — see the M8 section for the full raw-vs-constrained record.

---

## M2 — Verifier API service   (REVIEWED — closed)

Delivered `verifier.service` — the M1 library wrapped in a local Litestar + uvicorn HTTP
transport (one worker, 127.0.0.1 by default), adding no verification trust of its own (one-way dep:
the core never imports the service). Pieces: `settings.py` (frozen operator config from
`VERIFIER_*` env, fail-closed bound guards) → `app.py` (factory + 6 routes, raw-body-first
POSTs so `decode_spec` stays authoritative, nosniff app default, two problem+json exception
handlers) → `pipeline.py` (decode → resolve manifest → load → `checks.verify`, reused by
render) → `models.py` (Verdict / RenderVerdict with `verified: Literal[True]` / RFC-9457 Problem)
→ `store.py` (bounded LRU over chart renders) → `openapi.py`
(hand-authored OpenAPI 3.1 doc, served at `/schema/openapi.json`, golden-pinned). Error split
(POC_SCOPE "## Service boundary"): every verification outcome incl. decode failure = 200
verdict; only transport misuse / operator-config fault = problem+json 4xx/5xx (its cause
logged by the handler, withheld from the caller). Claim boundary UNCHANGED — transport around
the verifier; POC_SCOPE holds the modest claim + TCB line verbatim, VPlot_SEMANTICS untouched.
616 tests / 100% branch, incl. a live-socket smoke over real TCP from a foreign cwd. Reusable
transport recipe (for M4's added endpoints) + probed Litestar facts live in `.agent/memory.md`
Stack; unit trail + per-unit context-usage + the review pass: `git log --grep "(M2[. ]"`.
Units landed at 46–87% of 200K.

---

## M1 — Trusted verifier core   (REVIEWED — closed)

Delivered the headless library `verifier`, gate-free, exercised entirely by pytest: schema decode gate (`schema.py` + exported JSON Schema golden) → canonical forms + 4 provenance hashes (`canon.py`) → typed ingest (`ingest.py`/`errors.py`) → Decimal-exact evaluator (`eval.py`) → verification spine + encoding/label checks (`checks.py`) → Vega-Lite positive-allowlist builder + SVG + VCert v0.1 badge + `render()` gate + optional offline HTML (`render.py`). 480 tests / 100% branch, dual-engine DuckDB oracle parity, golden corpus (10 good / 18 bad). Unit trail, per-unit context-usage, and the review pass: `git log --grep "(M1[. ]"`.

**Right-sizing rule (M1 evidence; binds M2+ unit sizing AND planning turns)**: size a unit at ~one module + its tests; an independent oracle or a property/fuzz layer is its OWN unit, never bundled. A unit whose DESIGN alone projects well past the ~200K aim is mis-sized → split it. A unit that runs well past the aim in IMPLEMENTATION despite a complete recipe is OVER-deriving, not under-specified → pre-derive a gate-validated transcription recipe (`.agent/*_design.md`), TRANSCRIBE not re-derive, reach the gate early, and salvage-continue (an overshoot ≠ bad work — a completed unit's gate-green output stands; recipes deleted once consumed). Isolate native-dep probes to scratch sessions — probing in the implementing window overflowed twice. M1 units landed at 39–88% of 200K under this rule. Sizing reads `impl=` alone; a unit chained into the previous unit's MAIN window records a cumulative `main=` and carries the tag `chained`. Measurement basis: `impl=` through M9.1 = each teammate's FINAL-turn reading (peak across teammates), which under-reads a teammate whose occupancy was reset by compaction or a stripped trail (M9.2 noted its 239K peak by hand); M9.3+ reads the HIGH-WATER turn via `.agent/context-gauge.sh <name>` → new records sit at or above the historical band for identical work, so compare basis-aware.
