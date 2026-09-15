---
paths:
  - "**/src/verifier/pysrc/**"
  - "**/tests/test_pysrc*.py"
  - "**/corpus/python/**"
  - "**/.agent/contracts/m13*.md"
---

# `pysrc-0.1` — model-authored Python verification (M13 law)

## Verification model (user ruling; supersedes the math-function-only re-scope)

BOTH arms ship. Dataset arm (`read_csv` over the user's uploaded file) = the clinical spine; formula
arm (`f(x)` over a stated interval) = the high-resolution special case, the one where the request
sentence IS the specification. One core, one allowlist, two projections.

Three tiers, ordered by what each needs to know about the user:

1. **Provenance** — every plotted number recomputed from the user's artifact by an independent
   engine. Needs NO intent. Kills hallucinated values. Total within the admitted subset.
2. **Integrity** — the figure satisfies the closed per-mark rule set below. Needs NO intent. Kills
   misrepresenting encodings. Total over the rule set.
3. **Interpretation** — the certificate publishes in plain words exactly what was verified (`sum of
   sales grouped by quarter · 4 groups · 1 null row dropped · y from 0`). It PUBLISHES the residual
   intent gap instead of closing it; a human reads it in one glance.

Fidelity to INTENT is never claimed: intent lives in a person's head, and a chat sentence is not a
specification. Tier 3 makes that gap visible; nothing hides it. Coverage grows by adding a mark —
projection + its integrity rules — and adding a mark costs NO new trust.

Both failure profiles are covered, which is why the model tier does not move the design: a weak
proposer hallucinates values (tier 1 catches it), a strong one truncates an axis or drops outliers
to flatter the story (tier 2 catches it).

## Integrity rule set — decidable, per mark, and MOSTLY ALREADY TRUE

`admit.py` admits no `ylim`, `xlim`, `yscale`, `twinx` or `subplots`, so several rules hold BY
CONSTRUCTION today and are unclaimed. Reading that narrowness as "small subset" understates it: it
is graphical integrity, enforced by refusal.

| id | scope | predicate | today |
|---|---|---|---|
| G1 | bar | length encodes magnitude ⇒ baseline at zero, axis limits unset | by construction |
| G2 | all | one Axes, one y-scale — no dual or secondary axis | by construction |
| G3 | all | linear scale only | by construction |
| G4 | all | ticks monotonic + evenly spaced under a linear claim | by construction |
| G5 | formula | sampled functions are line/scatter, never bar (`FormulaMark`) | shipped, unclaimed |
| G6 | scatter | marker size encodes value by AREA, never radius | with the `s=` keyword |
| G7 | all | plotted x-range = data range unless a `Filter` is projected AND published | by construction (M13.5) |
| G8 | all | every non-null row is covered by a plotted point — one point per row for a column pair, one group point per row set for an aggregate — unless a drop is projected AND published | by construction (M13.5) |
| G9 | line | x numeric NON-DECREASING, or categorical with UNIQUE categories in file order | M13.5 |
| G10 | all | label/legend text consistent with the projected computation | `label=` admitted, unchecked |
| G11 | aggregate | per-group counts published beside every aggregate | tier 3 |

A by-construction rule is only as durable as the refusal under it ⇒ **every G-row pinned by a test
that fails when the allowlist widens**. Admitting `plt.ylim` later must break G1's test, not silently
delete G1. This is the closed-dispatch defect class applied to the claim surface.

G7/G8/G9 became decidable only once M13.5's recomputation materialized the plotted table, and each
resolved differently:

- **G7 + G8 = by construction (user).** The admitted subset has no filter, slice, mask or
  `head`/`tail`/`dropna` idiom, so the plotted column IS the whole column; and the CSV profile
  refuses every empty cell and every pandas NA spelling, so no null can survive to be dropped. Two
  backing refusals, each pinned against allowlist widening exactly as G1/G2/G3 are. G8 needs one
  added check to stay true: `bar` over a categorical x requires UNIQUE categories, else
  `category_not_unique` — duplicates overplot, so the figure would show fewer bars than rows.
  **G8 is ROW COVERAGE, never point-count equality** — the equality holds for a column pair alone.
  An aggregate collapses its rows into one point per group, so a 3-row file over 2 groups verifies
  with 2 plotted points and drops no row; G11's per-group counts, which SUM to the data-row count,
  are what publish that collapse. Read G8 as "no row goes missing", and G11 as the ledger proving
  where each row went.
- **G9 drops "uniformly spaced" and admits UNIQUE categorical x (user).** Ordering survives, uniform
  spacing does not: irregular spacing is LEGIBLE in the rendered figure, so it misrepresents nothing,
  while real clinical series are irregularly sampled and a uniformity requirement would refuse most
  of them. Non-monotonic x is the actual fault — it draws a path that reads as a function when it is
  not. A categorical x is admitted for `line` when every category appears EXACTLY ONCE, in file
  order: with unique keys the path is a genuine sequence of distinct points, which is what a
  categorical line chart means, and it is the shape a `groupby` key always has. A repeated category
  refuses, because the line would double back over itself. `scatter` still requires numeric x.

## Comparison surfaces — what the verifier can compare AT ALL

Every check is `claimed` vs `independent`, and is worth exactly as much as side B's independence
from the model.

| class | compares | catches | cannot catch |
|---|---|---|---|
| **I** admission | submitted AST vs closed allowlist | overreach: scipy/sklearn, `subplots(2,2)`, loops, themes, `cmap=` | anything wrong but admissible |
| **II** recomputation vs out-of-model truth | plotted values vs values derived from an artifact the USER supplied (uploaded CSV, or a target stated in the `expr-0.1` grammar) | the figure misrepresents the thing of record | nothing, within its scope |
| **III** internal consistency | projection vs projection | numeric-literal arrays (= model-supplied data), label/computation mismatch, grid/value length skew, `np.random` | a model that coherently plots the wrong function |
| **IV** integrity | projection vs the G-rules | truncated baselines, dual axes, silent row drops, radius-encoded area, interpolation asserted over unordered x | a well-formed figure of the wrong quantity |

**Class II's truth source is the user's own artifact** — the uploaded CSV (dataset arm) or the
formula stated in the request (formula arm). Both are bytes the user supplied; neither is derivable
from the model. Rejected as class-II sources, each for a different reason: committed per-prompt
expected answers move the boundary out of the verifier (ruling 5); a second model has no
independence; back-translation self-consistency is the SAME model, consistently wrong.

**The residual no class catches: task infidelity** — every number real and correctly computed, but
of a different quantity than the request meant (grouped by `month` where the user said quarter;
summed where they meant averaged). It is not mechanically decidable without a specification of
intent, so tier 3 PUBLISHES the interpretation rather than pretending to check it. A verdict never
implies the figure answers the question asked.

## Forks

- **(a) Declared target — RESOLVED.** The truth source is the user's artifact: the uploaded CSV in
  the dataset arm, the formula in the request sentence in the formula arm. `verify_python_source(src,
  declared_target=None)` keeps the parameter optional for headless callers; the demo supplies it from
  the arm in play.
- **(b) Observed-execution confirmation — RESOLVED: ADOPTED (user).** The sandbox reports the arrays
  matplotlib actually received (`gcf().axes[*].lines[*].get_xydata()`), the outlet filter returns
  them, and the PNG is withheld until they match the verifier's own recomputation. This closes the
  projection gap EMPIRICALLY instead of by construction and costs no new trust: OWUI already
  rewrites `plt.show()` to `savefig(BytesIO)`, so an environment layer around the model's bytes
  already exists and is accepted, and admitted code provably cannot tamper with the observer because
  the allowlist admits no idiom that could. The environment/observation layer reads as OUTSIDE
  ruling 1 (verifier-(re)authored scripts REJECTED): the EXECUTED bytes stay the model's, and the
  epilogue observes rather than re-authors. Observation may only WITHHOLD, never admit — a
  comparison it cannot perform blocks. M10 owns the implementation.

The verdict is decided statically either way — it must precede release — so the core is built on
projection + exact recomputation and observation is additive.

## Deployment facts that bind the design

- Initial deployment = Japan, clinical. Production proposer = latest Kimi; the demo keeps
  `Qwen2.5-Coder-0.5B-Instruct` on the host of record. The design must not depend on proposer
  strength: tier 1 carries the weak arm, tier 2 the strong one.
- Request language and CSV header language may differ arbitrarily ⇒ **lexical term anchoring is NOT
  load-bearing**. It is a deferred refinement over tiers 1-3, never a prerequisite for a verdict.
- Text normalization that is SAFE because the model gets no vote in it: `unicodedata.normalize
  ("NFKC", …)` + full/half-width folding + bounded edit distance against the file's REAL header, a
  unique match required and ties refused. The target set comes from the user's bytes, so a typo fix
  cannot invent a column.
- Japanese has no whitespace word boundaries ⇒ every request-side match is SUBSTRING containment,
  never tokenization. This makes anchoring more robust in Japanese than in English, which needs
  plural and possessive handling.
- A model-produced translation of the request may never become the anchor: the model would then
  control both sides of the comparison and class II would be deleted, not weakened. A translation
  reaches the user through tier 3 publication only.

## Layering (ruling 7: embeddability is a DESIGN INPUT, not an M14 retrofit)

Portable core, `src/verifier/pysrc/`, **stdlib-only** — no msgspec, litestar, archive or service
imports, inlinable into one pasted file:

1. byte cap + nesting pre-scan AHEAD of `ast.parse`
2. AST allowlist by idiom class
3. projection to a formula plot spec
4. recomputation. **`expr.py` is NOT ported, in whole or in part (M13.5 ruling).** Two independent
   reasons, and the second is the deciding one. First, coverage: its union is `Number | Variable |
   Neg | Abs | Pow | Binary`, no function node, while the formula arm evaluates
   `sin cos tan exp log sqrt abs`. Second, FAITHFULNESS: `expr.py` is exact over `Fraction`, but the
   executed program is numpy float64 and rounds at EVERY operator, so an exact engine that rounds
   once at the end computes a number the program never computes. The more precise engine is the less
   faithful one. Recomputation is therefore binary64, operator by operator, in the projected tree's
   own shape — a small evaluator written for the job, not a port. `expr.py`'s lexer and parser are
   dead weight here regardless: `project.py` already returns a `pysrc.spec.Expr` tree from the AST.

   The numeric profile is NAMED `binary64-libm-v1` and splits every admitted operator in two.
   **Standard-exact**, agreement guaranteed by IEEE-754: `add sub mul div`, unary minus, `abs`,
   `sqrt`, decimal-literal conversion, `pi`, `e`, and both grid constructors. **libm-dependent**,
   agreement a MEASURED band on a named environment pair rather than a proof: `sin cos tan exp log`
   and `pow`. Measured host-of-record vs Pyodide-wasm numpy 2.2.5, 1,000,000 stratified inputs per
   function: 56,929/6,000,000 disagreements, EVERY ONE exactly 1 ulp (`sin` 17,792 · `cos` 17,872 ·
   `tan` 20,876 · `exp` 389 · `log` 0 · `sqrt` 0); `pow` measured separately over 1,000,000
   stratified (base, exponent) pairs at 238 disagreements, every one exactly 1 ulp, IDENTICAL on
   Pyodide 0.28.0 and 0.28.1; grids agree at 0 ulp over 3.5M values. So bit-exact y comparison is off
   the table and the 1-ulp band is forced by the ENVIRONMENT PAIR, not by verifier precision — which
   is also the resolution limit M10's fork-(b) observation inherits.

   Domain and overflow faults are never raised: the evaluator reproduces numpy's IEEE results
   (`x/0` → `±inf`, `log(0)` → `-inf`, `sqrt(x<0)` → `nan`, …) and a single refusal,
   `value_not_finite`, rejects any non-finite that reaches the table. `pow` is the operator where
   that reproduction takes real logic, and the ONE place a stdlib spelling must be chosen rather than
   assumed. CPython's `**` is unusable: over the same corpus it returned a COMPLEX on 135,034 pairs
   and raised `ZeroDivisionError` on 49,764 more. `math.pow` never leaves `float`, and wherever it
   SUCCEEDS it is bit-identical to numpy (639,275/639,275, 0 disagreements) — but its exceptions are
   ambiguous, `ValueError` alone covering `+inf` (45,528), `-inf` (4,236) and `nan` (176,382). A
   blanket `exception → nan` therefore disagrees with numpy on 184,343/1,000,000. C99 resolves the
   ambiguity from the operands, and that explicit rule measured 0/1,000,000: `OverflowError` →
   `±inf`, negative only for a negative base under an odd-integer exponent; `ValueError` with a zero
   base → the pole `±inf`, negative only for `-0.0` under an odd-integer exponent; every remaining
   `ValueError` → `nan`. Category structure (`finite`/`±inf`/`nan`) never split across the
   environment pair — 0 splits in 1,000,000 — so the REFUSAL decision is environment-independent and
   only a finite value's last bit can differ.

   The DATASET arm's parse is a separate and harder problem: the sandbox calls plain
   `pd.read_csv`, whose DEFAULT float parser is not correctly rounded. Measured against stdlib
   `float` over 1,000,000 adversarial cells: 326,834 disagree (314,781 at 1 ulp, 12,053 at
   2–7,262 ulp); only `float_precision="round_trip"` agrees fully; and NO significant-digit cap
   repairs it — even `1e-23` disagrees. **RULED: restrict, not reimplement.** The admitted cell text
   is canonical fixed point, `-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?`, ≤15 significant digits, finite,
   in `[-2147483648, 2147483647]`, and not a sign-bearing zero — measured at 0/4,000,000 bit
   mismatches against target Pyodide across plain and quoted fields. Two of those clauses are about
   the RENDERER, not the parser: Pyodide's `plt.bar` keeps integer heights as `int32` and RAISES
   outside signed 32 bits, and matplotlib bar erases the sign of `-0.0` (99/1,024 heights). Line and
   scatter altered nothing (0/40,000 each). A categorical bar maps unique labels to float64 centers
   in first-occurrence order, which is exactly why a duplicate category overplots and G8 refuses it.
   Full profile + its closed refusal complement = `.agent/archive/contracts/m13u5.md` § The C10 ruling.

Demo-side wrappers, outside the core: certificate kinds · archive (`PlotSourceKind` + `PlotRole`
widening, 5 totality sites) · `AttemptRoute.VERIFY_PYTHON` + `PROPOSE_PYTHON` at all NINE route
surfaces · replay · `POST /verify-python` + `/propose-python`. Surfaces enumerated in the archived
roadmap § M13 scope sketch.

Where "reuse the shipped evaluator" conflicts with core isolation, **embeddability wins** (user
word): extract into the core rather than import the service stack. `formal.py` stays demo-side —
z3 cannot be inlined.

## Projection law (formula arm)

- **Grid identity is STRUCTURAL, never lexical.** One `Grid` shape `(start, stop, samples)`, `stop`
  INCLUSIVE, no `kind` and no `step` field ⇒ `np.arange(0, 5)` and `np.linspace(0, 4, 5)` project
  EQUAL. Any reference to a grid structurally equal to the mark's x grid IS the grid variable,
  whether spelled as the bound name or as a repeated call; a structurally unequal grid refuses
  `y_not_over_grid`. `Var` carries no name, so renaming a bound grid cannot change a spec. This
  supersedes "an inline grid binds no name, so a free name in y refuses": that program draws the
  curve the projection states, and refusing it is a false refusal with no verification value.
- **`np.arange` admits INTEGER bounds only** (`denominator == 1`, `|numerator| <= 2**52`), and it is
  a faithfulness bound. numpy sizes `arange` as `ceil((stop - start) / step)` in float64 and
  accumulates samples in float64, so a non-integer step makes the EXECUTED array disagree with the
  exact-rational grid by a whole step. Measured, 5 of 15 non-integer cases disagree:
  `arange(0, 3, 0.3)` draws 10 points ending 2.6999999999999997 where the exact grid says 11 ending
  3; `arange(0.1, 0.4, 0.1)` draws 4 where the grid says 3; `arange(1, 2, 0.1)` ends
  1.9000000000000008, not 1.9. Integer bounds: 115/115 cases faithful, integral-float spellings
  (`0.0, 10.0, 1.0`) included. numpy's own reference calls non-integer steps inconsistent and points
  at `linspace`, whose residual is a per-sample rounding rather than a different SAMPLE COUNT — the
  comparison layer's business (M13.5), not a structural gap.
- A source float projects as `Fraction(<the float64>)`: `0.1` → `Fraction(3602879701896397,
  36028797018963968)`, never `Fraction(1, 10)`. Projection is faithful to EXECUTION; which spelling
  a check compares against is M13.5's ruling.
- `CorePlotSpec` is a ONE-MEMBER alias for `FormulaPlot`; `DatasetPlot` is declared by M13.4, not
  before. A placeholder written ahead of the admitted dataset idioms would be written wrong and then
  inherited as law, and the alias makes the widening a visible edit at the union.
- **Dataset-arm width, M13.4 (user ruling): COLUMN PAIRS ONLY** — `read_csv` → column selection →
  bar/line/scatter over two columns. No `groupby`/`sum`/`mean` in that unit, so G11 stays dormant
  and aggregation is its own later unit. The width caps the FIRST release, never the ceiling:
  coverage grows one mark at a time at no new trust, and the same core ships in the M14 paste-in, so
  whatever M13.4 admits is what the production artifact admits on day one.
- **Dataset-arm width, M13.6 (user ruling): aimed by MEASURED proposer output, not by idiom
  coverage.** An idiom-coverage ceiling over the held-out manifest says the column-pair subset
  reaches 2/20 = 10%. That number is a CEILING and it is not the bottleneck. Measured over all 50
  committed design captures against the shipped verifier: 0/25 simple verify; 17/25 refuse
  `name_not_bound` because the proposer writes `pd.read_csv` with no `import pandas as pd`; repair
  that hypothetically and it is STILL 0/25, blocked by constructs carrying NO data effect —
  `plt.figure(figsize=)` in 16/25 prompts, `plt.tight_layout()` 6, `plt.xticks(rotation=)` 6,
  literal `color=`/`marker=`/`linestyle=` ~20 uses — against `groupby` in 7. M13.6 therefore admits
  the data-effect-free cosmetic cluster, `groupby` aggregation, and `plt.barh`. The missing import
  is a PROPOSER defect, not a width defect, and its lever is the capture prompt (M13.7).
- **What the M13.7 lever exposed, and it re-aims the NEXT width.** Naming pandas in the capture
  prompt took `name_not_bound` from 17/25 to 0/25 over the simple design rows and left simple verify
  at 0/25, so the M13.6 census is now stale and the blocker layer under it is a different shape
  (`.agent/measurements/w1_width.py`, run against `m13-design`; per-row counts in `.agent/spec.md`).
  Two width gaps carry real rows and NEITHER is cosmetic: 4 rows call the pandas plotting ACCESSOR,
  `series.plot(kind="bar")`, instead of `plt.bar`; 2 append `.reset_index()` to the reduction, which
  re-spells the channels and is exactly what `aggregation_not_projected` names. The remaining simple
  rows are proposer defects the verifier is right to refuse; widening for them would move the
  pass/fail boundary out of the verifier. The largest such bucket is `category_not_unique` at 6 —
  the proposer plots raw rows where the task said a total or an each-group figure.
- **A DEMO DATASET MAY NEVER SPELL A GROUP KEY WITH A PANDAS NA SPELLING (M13.7b, closed).** The
  third M13.7 blocker was not the verifier at all: `data/sales.csv` spelled North America `NA`, one
  of the 19 default pandas NA spellings the CSV profile refuses, so every `groupby("region")`
  program over it refused `value_not_in_profile` — 3 of the 25 simple design rows, and 6 of the 20
  held-out simple rows, which capped the acceptance ceiling at 10/20 = 50% under `Intent`'s
  required 70%. The refusal is CORRECT: pandas reads those cells as missing, `groupby` drops all 3
  rows, and the drawn figure really would lose a bar. So the DATA carried the defect. The region
  code is now `NAM` and every spelling in that column must stay outside `csvread.NA_SPELLINGS`;
  measured over the same captures, simple VERIFIED went 0/25 → 2/25 and `value_not_in_profile`
  3/25 → 0/25, with `column_not_numeric` 2 → 3 as one row's true fault stopped being masked. The
  adversarial NA case is banked on fixtures that are NOT `data/sales.csv`, three ways:
  `tests/test_pysrc_aggregate.py`'s 19 hand-stated spellings through the VALUE column, its
  key-column end-to-end refusal (S2), and `data/deliberately_dirty.csv`, which keeps its literal
  `NA` for JSON mode's "only an empty cell is null" claim. The digest of `data/sales.csv` is cited
  in 25 tracked files, so a data edit is replayed by `uv run --locked python
  tools/rederive_dataset_hashes.py` — idempotent, recomputing each citation from the CSV — and
  `tests/test_dataset_digests.py` fails on any stale one.
- **The SECOND mark is CANCELLED (user ruling), and `CorePlotSpec` keeps ONE mark.** It converts
  zero held-out prompts. It existed for heldout simple 06/14 ("separate city lines"), but
  `weather.csv` is LONG — 8 rows = 4 dates x 2 cities — so two marks over two columns cannot draw
  two city lines; those prompts need ROW SELECTION, and the design capture for that idiom writes
  `for city in set(...): df[df['city'] == city]`, a loop plus a boolean mask. Consequences, all
  binding: the seven `assert_never(spec)` sites do NOT move, `PlottedTable` stays one series,
  `certificate.canonical_bytes` keeps its framing, G2 stays true BY CONSTRUCTION and is re-pinned
  against `twinx`/`twiny`/`secondary_yaxis`/`subplots` rather than against mark count, and G7/G8
  stay UNCONDITIONAL rather than moving to "a `Filter` projected AND published" — with no filter
  admitted, the plotted column is still the whole column. Heldout 06/14 (multi-series) and 08/16
  (colour-by-category) stay refused, for a ceiling of 16/20 = 80% with ten points of headroom. G11
  (per-group counts published beside every aggregate) goes live in M13.6.
- **Aggregation recomputation is Kahan, and this is measured, not chosen.** pandas reduces a
  float64 group with ordered binary64 Kahan compensation in file-row order. Naive left-to-right
  differs on 2,761 of 4,000 admitted-profile CSV groups, worst 8,192 ulp; `math.fsum` differs on
  1,483, worst 5,252 ulp; Kahan matches on 0/16,062. `mean` is that Kahan sum over the non-NaN
  count; an INT64 `mean` is per-value float cast then Kahan then divide, NOT the exact integer mean
  (witness `[2**53, 1, 0]`, a 1-ulp split). `min`/`max` update on strict `<`/`>`, keeping the first
  tied value's bits. Group key order IS the plotted x-order and is pandas' `sort=True` default:
  ascending, by Unicode CODE POINT for strings and numerically for numbers, measured
  locale-independent across `C`, `C.utf8` and `en_US.utf8` with an `en_US` collation control
  ordering differently. `bottleneck` and `numexpr` change nothing (0 changed sections, present or
  absent, enabled or disabled). Host vs BOTH Pyodide builds: 0 differences over 96,372 reduction
  rows — so unlike the libm functions, the reduction carries NO measured ulp band.
- **An integer aggregate needs the renderer bound re-asserted AFTER aggregation.** C10 bounds each
  CELL to int32 because Pyodide's `plt.bar` integer path raises outside it; a SUM of in-profile
  cells can leave the range. Measured: both Pyodide 0.28.0 and 0.28.1 raise `OverflowError: Python
  int too large to convert to C long` on `bar` AND `barh` of int64 sums `[4294967294, -4294967296]`,
  while in-int32 controls render and `plot`/`scatter` preserve their float64 bits. Reductions
  therefore retain dtype, and the bound binds integer `sum`/`min`/`max` under `bar`/`barh` alone —
  an integer `mean` is float64 and never reaches that branch.
- A differential between two implementations of this contract compares MEANING: one named
  translation maps both sides onto a canonical tuple through an EXPLICIT node-name and field-name
  map, in a fixed field order. Class names and field order are form noise (`Number`/`Num`,
  `expression`/`y`) and produced 23 of 25 false disagreements on first run. The map raises on a name
  it does not cover — a generic lowercase-or-strip rule would absorb a real future divergence.
  A semantic disagreement is ESCALATED to the lead, never absorbed into the map. Both of M13.3's
  resolved in production's favour; M13.4's ONE resolved in the ORACLE's, and it was a real defect
  no red suite had reached. So the prior is NOT "production is usually right" — escalate on the
  disagreement, rule on the law, and expect the oracle to win often enough to be worth its cost.
  An oracle also earns its keep by being based on the SAME tip as production: M13.4's was seeded
  from the skeleton commit, so its first full run was 20 loud skips against an absent type and
  proved nothing. Land the implementation before, or re-base the oracle onto, the code it grades.
- **Refusal precedence: LOCAL before GLOBAL.** A fault local to one statement refuses before a fault
  global to the program — `plt.plot(...)` then `plt.bar(...)` refuses `mark_not_valid_for_arm`, not
  `multiple_marks`. In the formula arm this is structural rather than ordering-dependent: `plt.bar`
  is in `_WRONG_ARM_MARKS` and never in `_MARKS`, so it cannot become a second mark. Keep it
  structural as the dataset arm widens `_MARKS`.
- **A statement is validated on its OWN terms before any program-wide count, INCLUDING the statement
  that trips the count.** The mark therefore resolves arity, keywords and channels AT ITS OWN
  STATEMENT; only the decorations, which may legally follow it, wait for assembly. Holding an
  unresolved `(target, node)` and assembling at the end silently inverted this: a FIRST mark naming
  a bad column refused `multiple_marks` on the second mark's existence, because assembly never ran.
  Both faults refuse either way, so no figure escaped — what was wrong is which fault the author was
  told to fix. Found by the M13.4 differential oracle, not by the red suite, whose local-fault
  witness (`df[c]`) is caught at ADMISSION and so never exercises projection-stage precedence: a
  precedence witness must be a program admission ADMITS. The distinguishing mutant is the ORDER of
  resolve-vs-count at a SECOND faulty mark; at a first faulty mark the two orders are equivalent.

## Binding rules

- The archived AND executed artifact is the EXACT submitted bytes, hashed under a new domain tag.
  No canonical re-emission: canonicalizing would make the executed bytes no longer the model's.
- Projection gap ruled PER CONSTRUCT — closed by construction, or declared TRUSTED. Never unstated.
- Claims: recomputation strong · admission BY ALLOWLIST · containment TRUSTED (the Pyodide iframe
  and its bundled matplotlib/pandas/numpy join the TCB).
- `ast.parse` over untrusted bytes is a TCB addition for this module ALONE — it runs the CPython
  parser on adversarial input, so the byte cap and nesting pre-scan must precede it. `expr.py` keeps
  its no-`ast` property.
- Subset designed by IDIOM CLASS on the design set alone; held-out untouched until the config is
  frozen. A ≥70% figure taken on the design set is not evidence.
- No prompt text, prompt hash, sample-specific field list or raw model reply may appear in
  production code — one committed search test. Admission is justified by AST idiom class.

## Mutation evidence (the allowlist is kernel tier; coverage alone credits nothing)

Driver = **`tools/mutate.py`**, committed, catalogues under `tools/mutants/<module>.toml`. Run
`uv run --locked python tools/mutate.py tools/mutants/project.toml`. Each `[[mutant]]` names the ONE
test that must go red and only that test runs under it, so attribution cannot drift to whichever
red came first; the baseline runs unmutated and must be green, ANCHOR-MISS is reported apart from
SURVIVED, and the target restores under sha256 verification with `__pycache__` cleared on both
writes. `tools/mutants/project.toml` = 46 mutants over the projection predicates (23 at M13.3, +13
at M13.4, +10 at M13.6), with the two EQUIVALENT mutants documented in the file rather than listed.
`tools/mutants/aggregate.toml` = 14 over the grouped reduction engine, and it documents THREE
deliberately unmutated predicates: R5 and R6 are absence claims the CSV profile refuses upstream, so
there is no branch left to neuter, and each witness takes the shape its own absence earns — R6 a
call-counting bomb on `_numeric_value`, R5 an arithmetic bound under 2**63 that a `max_table_rows`
widening reddens; and
`_reduce_int`'s `float(sum(values))` is profile-equivalent, because C10's int32 cell bound times
`max_table_rows` = 100,000 keeps every admitted integer sum under 2**48, and float64 carries every
integer exactly to 2**53. `tools/mutants/csvread.toml` = 1, G11's PUBLICATION seam: the counts are
computed in `aggregate.py` but carried forward from `read_columns`, and one module per catalogue is
what splits them. Run all three — a claim credited in one catalogue can sit unmutated in another.

A widening INVALIDATES anchors silently until the driver runs: M13.6 edited four lines that M13.3
and M13.4 mutants anchored on (`p4-y-over-inline-grid`, `d1-grid-selector-is-deep`,
`d2-rebind-dataset-names`, `d10-dataset-statement-coverage`), and the driver reported ANCHOR-MISS
rather than a kill. Rerun EVERY catalogue of a module a unit touches, not just the new one.

`admit.py` = 13/13 killed. Driver was `.scratch/mutate_admit.py` (gitignored ⇒ port its 13 mutants
into `tools/mutants/admit.toml`; queued in `.agent/deferred.md`, superseding the driver half of
p3/p4/p43/p44). Each
mutant neuters a PREDICATE: call-target set opened · exact-type literal check degraded to
`isinstance` · call-alias bound check dropped · constant-attribute alias bound check dropped ·
assignment binding moved ahead of its right-hand side · `**kwargs` conjunct dropped ·
private-attribute check dropped · expression tail turned catch-all · import alias conjunct dropped ·
statement tail turned catch-all · chained-assignment check dropped · attribute depth bound removed ·
constant-attribute allowlist opened.

`name_not_bound` guards TWO functions ⇒ its anchor carries a successor line to name the enclosing
one; a whole-file anchor matches both and applies to neither, and the driver reports that as
ANCHOR-MISS rather than as a kill.

`isinstance` vs exact type over the literal tuple is an EQUIVALENT mutant while `bool` is listed:
`bool` subclasses `int`, so the two spellings diverge only once the set is narrowed. Its pin
withdraws `bool` by `monkeypatch` and demands `True` refuse — the general shape for any allowlist
whose membership test could be subclass-closed.
