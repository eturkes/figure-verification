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
| G7 | all | plotted x-range = data range unless a `Filter` is projected AND published | to implement |
| G8 | all | plotted point count = non-null row count unless a drop is projected AND published | to implement |
| G9 | line | x ordered and uniformly spaced — a connecting line asserts interpolation | to implement |
| G10 | all | label/legend text consistent with the projected computation | `label=` admitted, unchecked |
| G11 | aggregate | per-group counts published beside every aggregate | tier 3 |

A by-construction rule is only as durable as the refusal under it ⇒ **every G-row pinned by a test
that fails when the allowlist widens**. Admitting `plt.ylim` later must break G1's test, not silently
delete G1. This is the closed-dispatch defect class applied to the claim surface.

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
4. exact recomputation (the `expr.py` evaluator ported: its parser and Decimal/Fraction arithmetic
   are pure stdlib, and only its `msgspec.Struct` node types need swapping for frozen dataclasses)

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
- A differential between two implementations of this contract compares MEANING: one named
  translation maps both sides onto a canonical tuple through an EXPLICIT node-name and field-name
  map, in a fixed field order. Class names and field order are form noise (`Number`/`Num`,
  `expression`/`y`) and produced 23 of 25 false disagreements on first run. The map raises on a name
  it does not cover — a generic lowercase-or-strip rule would absorb a real future divergence.
  A semantic disagreement is ESCALATED to the lead, never absorbed into the map; both of M13.3's
  were, and both resolved in production's favour.
- **Refusal precedence: LOCAL before GLOBAL.** A fault local to one statement refuses before a fault
  global to the program — `plt.plot(...)` then `plt.bar(...)` refuses `mark_not_valid_for_arm`, not
  `multiple_marks`. In the formula arm this is structural rather than ordering-dependent: `plt.bar`
  is in `_WRONG_ARM_MARKS` and never in `_MARKS`, so it cannot become a second mark. Keep it
  structural as the dataset arm widens `_MARKS`.

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
writes. `tools/mutants/project.toml` = 23 mutants over the projection predicates, with the two
EQUIVALENT mutants documented in the file rather than listed.

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
