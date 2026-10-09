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
   intent gap instead of closing it; a human reads it in one glance. Two renderings of ONE
   statement (`CoreCertificate.interpretation` + `interpretation_ja`, M17.2); the reader picks by
   request language, and both renderings are present whatever language it picks.

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
| G10 | dataset | no title, axis or legend label names a CSV column the chart does not draw, or, over a reduction, another reduction's summary word | Q16, lexical |
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
- **G10 = a label's POSITIVE mismatch, lexically (Q16).** `verify.py::_check_labels`, last in
  `_dataset_integrity`, matches `title`, `xlabel`, `ylabel` and the `label=` series text against
  the file's header + its admin aliases (Q43) with the request-anchoring matcher (ties name nothing here): naming a column
  other than x/y refuses `label_not_consistent`; over a reduction, so does a summary word of
  another reduction or `median` (`_SUMMARY_WORDS`, EN whole words + JA containment). Without a
  reduction summary words go unread (a raw column may hold totals), and a summary word inside any
  header word names that column (`total_revenue`). The formula arm meets no header, so G10 binds
  the dataset arm alone. A label naming nothing checkable passes; an x/y swap (`xlabel` naming the
  y column) is not a G10 fault. Measured, A2 (`.agent/measurements/a2_labels.py`): false refusals
  0/18 per form (EN · JA over a translated header · JA naming the English header); x-label plants
  caught 30/42 · 42/42 · 42/42 (EN misses `Temperature`, `Precipitation`, `Air quality index`: no lexical anchor);
  summary plants 45/45 each; `m10-design` captures: 0 FAITHFUL rows refused, design-simple-06/22
  (`xlabel` `Date` over x = `city`) now refuse.

## Comparison surfaces — what the verifier can compare AT ALL

Every check is `claimed` vs `independent`, and is worth exactly as much as side B's independence
from the model.

| class | compares | catches | cannot catch |
|---|---|---|---|
| **I** admission | submitted AST vs closed allowlist | overreach: scipy/sklearn, `subplots(2,2)`, loops, themes, `cmap=` | anything wrong but admissible |
| **II** recomputation vs out-of-model truth | plotted values vs values derived from an artifact the USER supplied (uploaded CSV, or a target stated in the `pyexpr-0.1` request grammar) | the figure misrepresents the thing of record | nothing, within its scope |
| **III** internal consistency | projection vs projection | numeric-literal arrays (= model-supplied data), grid/value length skew, `np.random`, a label naming an undrawn column or another reduction (G10, lexical; any wider label meaning stays tier-3 publication) | a model that coherently plots the wrong function |
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
- **(b) Observed-execution confirmation — RESOLVED: ADOPTED (user), SHIPPED (`webui/paste_in/observe.py`,
  `.agent/archive/contracts/m10u2.md`).** The wrapper's show hook prints ONE tagged JSON observation
  line of what matplotlib actually holds, then the PNG line; the outlet compares the observation with
  the verifier's own `Verified.table.{x,y}` and withholds the PNG unless they match. The reader =
  `READERS`, a CLOSED PER-MARK map keyed `line`/`scatter`/`bar`/`barh` with NO default arm, because
  matplotlib files each mark under a different artist: `plt.plot` → `line.get_xydata()`,
  `plt.scatter` → `collection.get_offsets()`, bars → `container.patches` bound through the FORWARD
  edge `patch.get_x() == position - span/2` + base 0 (barh on the swapped axes; span = matplotlib's
  converted width, 0.8 direct, 0.5 pandas accessor) — never a center equality, which false-blocks
  decimal positions. A categorical x binds through the axis `units._mapping` (direct marks) or tick
  identity (accessor bars). A string-keyed LINE with no category units -- pandas' line accessor -- binds POSITIONALLY (M10.10): x = 0..n-1 exactly, each in-range integral tick labelled with its key, at least one such tick present; negative ticks wrap to tail keys and are ignored. Formula arm (O5 + reading R4): each observed y inside the interval of the
  verified expression — per-call ±1-ulp libm, point `+ - * /` over two points exact, outward 1 ulp
  once an operand is an interval; a libm call or integer `**` over an interval argument encloses
  its result by its own rule (Q18): exp/log/tan monotone (tan withholds a pole the interval may
  hold), sin/cos endpoints + every extremum the interval may hold, an integer power per sign of
  its base (zero inside an even power ⇒ lower bound 0), 1 ulp outward per call — so
  `np.exp(-x**2)` and `np.sin(x)**2` release; anything else withholds. An unmapped mark, an
  extra artist, a second axes, a missing/duplicate/oversized/unparseable observation line ⇒ FAIL.
  This closes the projection gap EMPIRICALLY instead of by construction at no new trust: OWUI
  already wraps the model's bytes (`plt.show()` → `savefig`), admitted code provably cannot tamper
  with the observer because the allowlist admits no idiom that could, and the EXECUTED bytes stay
  the model's (outside ruling 1: the epilogue observes, never re-authors). Observation may only
  WITHHOLD, never admit — a comparison it cannot perform blocks.

The verdict is decided statically either way — it must precede release — so the core is built on
projection + exact recomputation and observation is additive.

## Deployment facts that bind the design

- Initial deployment = Japan, clinical. Production proposer = latest Kimi; the demo keeps
  `Qwen2.5-Coder-0.5B-Instruct` on the host of record. The design must not depend on proposer
  strength: tier 1 carries the weak arm, tier 2 the strong one.
- Request language and CSV header language may differ arbitrarily ⇒ **lexical term anchoring is NOT
  load-bearing**: a refinement over tiers 1-3, never a prerequisite — a request naming no header
  column anchors nothing.
- **Request anchoring, shipped (Q8, user ruling: substitutions only).** `verify.py::_check_anchoring`
  in the `binding` check, ahead of recompute: `DatasetTarget.request` (the user's message, threaded
  by `selection.py`) vs the program's x/y; refuse `column_not_requested` only on a SUBSTITUTION = a
  named column undrawn AND a drawn column unnamed. Either half alone passes: `chart revenue` leaves x
  to the program; three named columns let a two-column chart pick two. A tie refuses too. H1
  (Q39) re-grades the held-out capture with each prompt as the request: simple VERIFIED 14 → 13/20
  (`heldout-simple-13`, `monthly order totals` drawn as revenue, caught), complicated 20/20.
- **Strict anchoring = production's rule (Q37, user: strict for production, the demo functional;
  `.agent/archive/contracts/q37.md`).** `DatasetTarget.anchoring` = `strict` (default) |
  `substitution` (the demo's Q8 rule). Strict = the substitution check, then: a request that names
  OR negates ≥1 header column (`anchoring.py::anchors`) must name every drawn column a request can
  name (`anchoring.py::nameable`: folded name or an admin alias ≥ the anchor minimum), else `column_not_named`. A drawn
  negated column is unnamed ⇒ refuses; a column two headers fold to can never be named ⇒ drawn
  under an anchored request it refuses. Production pays the cost in request wording, not proposer
  strength. A1 strict leg: false refusals of faithful intents EN 5/18 · JA 0/18 (4/18 before Q41)
  · JA-mixed 1/18 (one-name requests: `average temperature for each city` never names `temp_c`),
  swaps caught 47 · 57 · 57
  of 57; `m10-design` captures VERIFIED 18 → 10, FAITHFUL 10 → 6; H1 held-out simple 14 → 7/20
  (MAIN's reading: `heldout-simple-02` + `-12` faithful refused, `-08` `-16` `-18` `-20` unfaithful
  caught). Mode lives in the generated
  artifact, never in the model's reach: `webui/paste_in/tool.py::Tools._ANCHORING` +
  `webui/paste_in/filter.py::Filter._ANCHORING` = `strict`, the demo subclasses
  (`webui/paste_in/demo_tool.py`, `webui/paste_in/demo_filter.py`) = `substitution`.
- **Japanese short words name short columns under strict alone (Q41,
  `.agent/archive/contracts/q41.md`).** `anchoring.py::_short_names`: a whole kanji run (`々` + every
  CJK ideograph block NFKC leaves in place: Ext A, the main block, compatibility `﨑`, Ext B+ `𠮷`)
  of the folded request, read before any name is consumed (`診療科別` stays one run where `診療科` is a header),
  equal to a 2-4 character Japanese name minus its first or last character names it (`月ごと` →
  `年月`, `日ごと` → `日付`) — unless a Japanese header name overlaps the run (the exact name takes
  it), the run fits names of two columns (names neither) or precedes a Japanese negation cue; a name two
  headers fold to never names this way, yet still ties a run it fits. A one-word 5+-character name
  is the one-edit tier's: dropping one end is one edit. The shared matcher is unchanged, so the
  demo's substitution rule + G10 labels never read short words. Trust limit: a short word names the
  one header it fits (`年ごと` over a header whose only fit is `年齢` names `年齢`). Q42
  (`.agent/archive/contracts/q42.md`): a run ending in one grouping suffix (`anchoring.py::_SUFFIXES` = `単位`
  `別` `毎` `次`, cut once, at the end) is read again without it (`月別` → `年月`); the run and its
  stem fitting different names = a tie. Risk: a word ending in a listed suffix by itself (`区別`,
  `目次`) can name a header its stem fits (`区` → `地区`).
  Measured: A1 strict JA 4/18 → 0/18, JA-mixed 1/18 stays (`日ごと` for the English `date` = a
  translation), swaps caught unchanged; A3 (`.agent/measurements/a3_short_names.py`): 0 false names
  (clinical leg adds 3, own headers 4, 88 noise pairs 6, 240 suffix pairs 24 — each a column the
  request's own chart draws: `年月`, once `日付`), clinical false refusals strict 0/20 (1/20 before
  Q42: `月別`), substitution 0/20.
- **Admin-declared column aliases (Q43, `.agent/archive/contracts/q43.md`).** `DatasetTarget.aliases`
  (`spec.Aliases` = (column, alias) pairs; `()` default = every verdict as before) — `anchoring.py::_keys`
  folds each alias onto every header column whose folded name equals the alias's column, so an alias
  is another name of its column wherever a header name counts: exact naming, the one-edit tier, Q38
  stop + negation, Q41/Q42 short words, G10 labels + the summary-word exemption, under both rules.
  An alias of a column the header lacks is ignored; one two columns share, or equal to another
  column's name, is a tie (names nothing; naming it refuses `column_not_requested`); `_nameable`
  reads aliases, so an anchoring-length alias makes a short column nameable under strict. Names of
  ONE column at one place (its name + an alias, or two aliases) name it in the one-edit + short-word
  tiers, never a tie. Trust: an
  alias is ADMIN configuration, never model-supplied — the production tool's
  `Valves.column_aliases` text (`webui/paste_in/aliases.py::parse_aliases`), recorded in the
  receipt (`/2`) and read by the filter from it alone (`.claude/rules/owui.md`); OWUI lets the
  tool's owner, an admin or a write-granted user edit Valves, so the admin guide makes an
  administrator the tool's owner and keeps write access to it away from chat users. The core stays
  stdlib; `pydantic` lives in the wrapper alone. Measured, A4 (`.agent/measurements/a4_aliases.py`,
  aliases `a4_aliases.txt` authored from column meanings before the run): strict false refusals EN
  0/18 · JA 0/18 · JA-mixed 0/18 (A1 strict 5 · 0 · 1), substitution 0/18 each, plants 0; strict
  swaps caught 56 · 57 · 57 of 57 (A1 strict 47 · 57 · 57); `m10-design` captures 0 FAITHFUL rows
  refused (design-simple-19's title `Monthly Order Count by Region` names `month` through `monthly`:
  `label_not_consistent`); A3 legs 0 false names; H1 with the same aliases (reported, not targeted)
  simple 10/20 VERIFIED under each rule, complicated 20/20, both sentinels.
- Matching is SAFE because the model gets no vote: the target set = the file's REAL header, so a
  typo fix cannot invent a column. NFKC + `casefold`; words split at every non-word char (`_`
  included) and where ASCII meets another script (`regionごとのrevenue`). Exact names first, longest
  first, each consuming its span (`unit price` never also names `price`): an ASCII header ≥3 chars =
  an exact word sequence, a non-ASCII header ≥2 chars = containment in the request's words (Japanese
  has no word spaces). Then a one-word name ≥5 chars also matches one span within Levenshtein 1 (a
  word; in Japanese, a stretch of near length). A span within 1 of names of TWO columns, or one name two headers
  fold to = tie. An unreadable header (`csvread.header_names` = None wherever `read_columns` refuses
  by the header) or a drawn column absent from it leaves the verdict to recompute. Lexical only:
  `temperature` never names `temp_c` unless an admin alias says so (Q43). Before naming, Q38 (`anchoring.py::_unnamed_places`,
  `.agent/archive/contracts/q38.md`) consumes the closed EN stop phrases (`chronological order` … `in
  order`, unless one is a header's whole name) + every negated name: the longest name, else one
  ASCII word within one edit of a 5+-char name, right after `not` `no` `without` `except`
  `excluding` `rather than` `instead of` (the cue's successor first, then past one `the`/`any`), or
  a name right before `ではなく` `じゃなく` `でなく` `以外` `を除` (a space between them where the
  name ends in ASCII, as `_words` splits there). The scan stays linear in the request. A consumed place names nothing + joins no tie; a cue before a
  non-name negates nothing; the same name elsewhere still names. Shared with G10 labels. Measured, A1 (`.agent/measurements/a1_anchor.py`): false refusals 0/18 per
  language (EN · JA over a translated header · JA naming the English header), swaps caught 37/57 ·
  48/57 · 54/57; plants (` in chronological order` · `, not <undrawn column>`) 0/18 each per
  language (the pre-Q38 matcher: EN 1 + 7, JA 0 + 4, JA-mixed 0 + 1); `m10-design` captures: 0
  VERIFIED rows refused; anchoring moves only refusal codes (06 + 22 `label_not_consistent`, 23
  `column_not_numeric` → `column_not_requested`).
- A model-produced translation of the request may never become the anchor: the model would then
  control both sides of the comparison and class II would be deleted, not weakened. A translation
  reaches the user through tier 3 publication only; an ADMIN alias (Q43) is the one translation that
  anchors, because neither the model nor the chat user writes it.

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
   only a finite value's last bit can differ. A NaN's SIGN is not stable across x86 hosts either:
   numpy's `log(-1)` is +NaN on the host of record and −NaN on the hosted CI runner. The evaluator
   is pure `math` and does not move, and `value_not_finite` refuses every NaN before a verdict, so
   a differential against numpy compares a NaN by category (`math.isnan` on both sides) and every
   other value by bits (M10.8, `.agent/archive/contracts/m10u8.md`).

   The DATASET arm's parse is a separate and harder problem: the sandbox calls plain
   `pd.read_csv`, whose DEFAULT float parser is not correctly rounded. Measured against stdlib
   `float` over 1,000,000 adversarial cells: 326,834 disagree (314,781 at 1 ulp, 12,053 at
   2–7,262 ulp); only `float_precision="round_trip"` agrees fully; and NO significant-digit cap
   repairs it — even `1e-23` disagrees. **RULED: restrict, not reimplement.** The admitted cell text
   is canonical fixed point, `-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?`, ≤15 significant digits, finite,
   in `[-2147483648, 2147483647]` IN AN INTEGER COLUMN (a column pandas infers float64 — any token
   with a decimal point — is bounded by the 15-digit cap alone, user ruling Q12: host↔Pyodide
   0/1,345,852 bit disagreements to ±2**53 on 0.28.0/0.28.1/0.28.3, `plt.bar` float heights 0/2,364
   changed, integer tokens in a float64 column 0/1,000,049; `.agent/measurements/` T8), and not a
   sign-bearing zero — measured at 0/4,000,000 bit
   mismatches against target Pyodide across plain and quoted fields. Two of those clauses are about
   the RENDERER, not the parser: Pyodide's `plt.bar` keeps integer heights as `int32` and RAISES
   outside signed 32 bits, and matplotlib bar erases the sign of `-0.0` (99/1,024 heights). Line and
   scatter altered nothing (0/40,000 each). A categorical bar maps unique labels to float64 centers
   in first-occurrence order, which is exactly why a duplicate category overplots and G8 refuses it.
   Full profile + its closed refusal complement = `.agent/archive/contracts/m13u5.md` § The C10 ruling.

Python mode ships in the Open WebUI paste-in alone; the :8000 service stays JSON-spec-only (user
ruling, `.agent/spec.md` Demo shape), so no python-mode certificate kind, archive widening,
`AttemptRoute` member, replay or `/verify-python` route exists. The archived roadmap § M13 scope
sketch that enumerated those wrappers is history, not a plan.

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
- **An `arange` bound folds exact arithmetic (user rulings Q9 + Q17)** — `project.py::fold_exact`:
  `+ - * /` over literals and negations, `**` only with a literal integer exponent `|e| <= 64`; a
  zero divisor, a wider power, a symbolic constant, a COMPUTED zero (`0 / -1` executes as -0.0, a
  sign a `Fraction` loses) or ANY node that is not exact in binary64 or exceeds `2**53` folds to
  None ⇒ `grid_not_representable`. The node guard is the faithfulness
  bound: there Python's exact ints, numpy's float64 and IEEE `+ - * /` agree with the exact value,
  so `np.arange(1/49*49, 5)` (exact start 1, executed 0.9999999999999999, 4 vs 5 samples) and
  `np.arange(0, 10000000000000000 - 9999999999999995)` (Python 5, binary64 4) refuse. A declared
  target compares its bounds by that folded value when BOTH sides fold (`project.py::same_bound`),
  else by tree: `x ∈ [-5, 5]` binds `np.arange(-5, 6)`; `y` stays tree-compared.
- A source float projects as `Fraction(<the float64>)`: `0.1` → `Fraction(3602879701896397,
  36028797018963968)`, never `Fraction(1, 10)`. Projection is faithful to EXECUTION; which spelling
  a check compares against is M13.5's ruling.
- `CorePlotSpec` = `FormulaPlot | DatasetPlot` (`src/verifier/pysrc/spec.py`). A new arm widens the
  union where every `assert_never(spec)` site sees it; declare it with its admitted idioms, never as
  a placeholder ahead of them.
- **Dataset-arm width, M13.4 (user ruling): COLUMN PAIRS ONLY** — `read_csv` → column selection →
  bar/line/scatter over two columns. No `groupby`/`sum`/`mean` in that unit, so G11 stays dormant
  and aggregation is its own later unit. The width caps the FIRST release, never the ceiling:
  coverage grows one mark at a time at no new trust, and the same core ships in the M14 paste-in, so
  whatever M13.4 admits is what the production artifact admits on day one.
- **Dataset-arm width, M13.6 (user ruling): aimed by MEASURED proposer output, not by idiom
  coverage.** An idiom-coverage ceiling over the held-out manifest says the column-pair subset
  reaches 2/20 = 10%. That number is a CEILING and it is not the bottleneck. Measured over all 50
  committed design captures against the shipped verifier (every n/25 in this file = 24 design rows
  PLUS the sentinel, the measurement's convention until the lever unit moved `w1_width.py` to
  design-only n/24 with the sentinels printed apart): 0/25 simple verify; 17/25 refuse
  `name_not_bound` because the proposer writes `pd.read_csv` with no `import pandas as pd`; repair
  that hypothetically and it is STILL 0/25, blocked by constructs carrying NO data effect —
  `plt.figure(figsize=)` in 16/25 prompts, `plt.tight_layout()` 6, `plt.xticks(rotation=)` 6,
  literal `color=`/`marker=`/`linestyle=` ~20 uses — against `groupby` in 7. M13.6 therefore admits
  the data-effect-free cosmetic cluster, `groupby` aggregation, and `plt.barh`. The missing import
  is a PROPOSER defect, not a width defect, and its lever is the capture prompt (M13.7).
- **What the M13.7 lever exposed, and it re-aims the NEXT width.** Naming pandas in the capture
  prompt took `name_not_bound` from 17/25 to 0/25 over the simple design rows and left simple verify
  at 0/25, so the M13.6 census is now stale and the blocker layer under it is a different shape
  (`.agent/measurements/w1_width.py`, run against `m13-design`, retired at `d1f1ecd`; its capture stays at `f4ebe2b`).
  Two width gaps carry real rows and NEITHER is cosmetic: 4 rows call the pandas plotting ACCESSOR,
  `series.plot(kind="bar")`, instead of `plt.bar`; 2 append `.reset_index()` to the reduction, which
  re-spells the channels and is exactly what `aggregation_not_projected` names. The remaining simple
  rows are proposer defects the verifier is right to refuse; widening for them would move the
  pass/fail boundary out of the verifier. The largest such bucket is `category_not_unique` at 6 —
  the proposer plots raw rows where the task said a total or an each-group figure.
- **Dataset-arm width, M13.8: the two idioms the M13.7 census left on the table.** The pandas
  plotting ACCESSOR, `<reduced series>.plot(kind="bar"|"barh")`, and a trailing `.reset_index()` on
  the reduction. Both are RE-SPELLINGS of what M13.6 already projects, so each lands on the same
  `DatasetPlot` as its `plt.bar` twin — structural equality, exactly as the formula arm's grid
  identity rule requires, or a cosmetic rewrite would publish a different figure. Three things carry
  that: `kind` is TARGET IDENTITY and maps onto `plt.bar`/`plt.barh` through a CLOSED map at
  admission, never a `.get(k, default)` at projection; the accessor enters the same mark-counting
  seam `plt.bar` enters, so `multiple_marks` still fires; and the `.reset_index()` unwrap is BY
  NAME, `ADMITTED_UNWRAPPED_ATTRS = {"reset_index"}`. That last one is load-bearing and not obvious:
  `_admit_aggregation` admits ONE trailing no-argument call as a CLASS, so `.sort_values()` arrives
  ALREADY ADMITTED and is refused only at projection with the SAME `aggregation_not_projected` code
  — an unwrap taking whatever trailing call it finds would therefore admit a REORDERING with nothing
  red, and both G8's row coverage and G9's ordering are read off group-key order. A reset frame
  binds its OWN name space rather than a flag on the aggregate: its `.index` is a fresh RangeIndex
  and not the group key, so the two spellings must not cross, and separate tables make that
  structural instead of a conjunct every later reader has to remember.
- **The accessor's receiver is a BARE NAME bound to a reduced series, and a SUBSCRIPT on it
  refuses `column_not_from_source` (M13.8).** `accessor_receiver` walks past one subscript on
  purpose, so that `df["revenue"].plot(kind="bar")` is routed by its ROOT name and priced on the
  channel it cannot state rather than landing `call_target_not_admitted` on a fault that is not its
  target. That routing erases the subscript, so projection has to price it back: `g["revenue"]`
  over a REDUCED `g` selects one element of the series BY GROUP KEY, never a column, so the
  executed receiver is a scalar and reading the root alone would verify `g` for a figure the
  program never draws. Admission prices the subscript's SLICE (`_admit_string_index`), projection
  prices its EFFECT (`accessor_is_subscripted`), and the guard is compound with one mutant per
  conjunct. This is the general shape wherever a router normalizes a receiver to reach a name: the
  normalization is a claim the consumer must re-price, or it silently widens what verifies.
- **The accessor's TICK PLACEMENT is a declared gap, ruled TRUSTED (M13.8).** Bars only: M10.10's line accessor draws numeric keys at their data positions. For a NUMERIC group
  key the two spellings place ticks differently: pandas draws the accessor CATEGORICALLY, at
  positions 0..n-1 with the key as the label, while `plt.bar` draws at the data positions. The gap
  lives inside the renderer, the recomputed table is identical either way, and no plotted VALUE
  differs — so it is trusted rather than closed, and it is STATED here because the rule above says a
  projection gap is closed by construction or declared TRUSTED, never left unstated.
- **The accessor's LINE kind, M10.10 (user phase-close ruling 1).** `kind="line"` maps onto
  `plt.plot` in the same closed map; the keywords stay `{kind, color}` and a missing `kind` -- pandas'
  default line -- still refuses. Aimed by design evidence alone: 5 simple `m10-design` rows wrote
  `<series>.plot(kind='line')`; `w1_width.py` moved 15/24 -> 20/24 VERIFIED, 7/24 -> 10/24 FAITHFUL,
  complicated 24/24 BLOCKED unchanged (Q16's G10 then refused design-simple-06/22, whose x label
  names `date` over x = `city`: 18/24 VERIFIED, FAITHFUL unchanged). The line carries NO tick-placement gap: numeric keys draw at
  their data positions, and string keys draw at 0..n-1 with pandas-set labels that the observation
  gate reads (fork (b)). design-simple-06/14 ask for per-city series and draw ONE collapsed line
  over `groupby('city')` -- 14 verifies, not faithful, the gap tier 3 publishes; 06's label refuses.
- **A DEMO DATASET MAY NEVER SPELL A GROUP KEY WITH A PANDAS NA SPELLING (M13.7b, closed).** The
  third M13.7 blocker was not the verifier at all: `data/sales.csv` spelled North America `NA`, one
  of the 19 default pandas NA spellings the CSV profile refuses, so every `groupby("region")`
  program over it refused `value_not_in_profile` — 3 of the 25 simple design rows, and 6 of the 20
  held-out simple rows, which capped the acceptance ceiling at 10/20 = 50% under `Intent`'s
  required 70%. The refusal is CORRECT: pandas reads those cells as missing, `groupby` drops all 3
  rows, and the drawn figure really would lose a bar. So the DATA carried the defect. The region
  code is now `US` and every spelling in that column must stay outside `csvread.NA_SPELLINGS`;
  measured over the same captures, simple VERIFIED went 0/25 → 2/25 and `value_not_in_profile`
  3/25 → 0/25, with `column_not_numeric` 2 → 3 as one row's true fault stopped being masked. The
  adversarial NA case is banked on fixtures that are NOT `data/sales.csv`, three ways:
  `tests/test_pysrc_aggregate.py`'s 19 hand-stated spellings through the VALUE column, its
  key-column end-to-end refusal (S2), and `data/deliberately_dirty.csv`, which keeps its literal
  `NA` for JSON mode's "only an empty cell is null" claim. The digest of `data/sales.csv` is cited
  in 24 tracked files (`tests/test_dataset_digests.py` `_SALES_CITATION_FLOOR`), so a data edit is replayed by `uv run --locked python
  tools/rederive_dataset_hashes.py` — idempotent, recomputing each citation from the CSV — and
  `tests/test_dataset_digests.py` states the same law independently. Read that law at its real
  strength: a `sha256:<64 lower-case hex>` token in a tracked file naming a tracked `data/*.csv`
  must equal that dataset's live digest, the owner being the last such name before the token or the
  first after it, swept over BYTES so a non-UTF-8 file is covered. It does NOT decide a citation
  whose nearest named CSV is not its owner, an upper-case token, a name outside `[A-Za-z0-9_-]+`,
  or a token split across literals. Three exemptions, all BY PATH and each pinned rather than
  trusted — the archive, the two deliberate-mismatch fixtures (pinned NON-LIVE, so a vector carrying
  some other wrong digest is not silently repaired into a passing one), and the two files that
  hand-state canonical-encoding digests.
- **The SECOND mark is CANCELLED (user ruling), and `CorePlotSpec` keeps ONE mark.** It converts
  zero held-out prompts. It existed for heldout simple 06/14 ("separate city lines"), but
  `weather.csv` is LONG — 8 rows = 4 dates x 2 cities — so two marks over two columns cannot draw
  two city lines; those prompts need ROW SELECTION, and the design capture for that idiom writes
  `for city in set(...): df[df['city'] == city]`, a loop plus a boolean mask. Consequences, all
  binding: the seven `assert_never(spec)` sites do NOT move, `PlottedTable` stays one series,
  `certificate.canonical_bytes` keeps its framing, G2 stays true BY CONSTRUCTION and is re-pinned
  against `twinx`/`twiny`/`secondary_yaxis`/`subplots` rather than against mark count, and G7/G8
  stay UNCONDITIONAL rather than moving to "a `Filter` projected AND published" — with no filter
  admitted, the plotted column is still the whole column. No admitted idiom draws heldout 06/14 (multi-series) or 08/16
  (colour-by-category) FAITHFULLY, for a faithful ceiling of 16/20 = 80%; since M10.10 a program that
  collapses the series into one line may still VERIFY (design-simple-14 does), so 16/20 bounds
  FAITHFUL, never VERIFIED. G11
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
  an integer `mean` is float64 and never reaches that branch. A float64 reduction under `bar`/`barh`
  stays within `2**53` (Q12): float64 cells sum past it, and the float bar path was measured
  bit-exact only up to it.
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

## Source positions (M18.1, `.agent/archive/contracts/m18u1.md`)

`position.py` = `Span` (ast convention: lines at `\r\n|\r|\n`, UTF-8 byte columns, exclusive end; a point = no character) + `Step(role, span)` + `Trace`. `Refused.at` = a GENUINE program location alone: the innermost instrumented node (admission + projection attach it in the recursing frame itself — a wrapper function doubled the frames per level and turned a 600-term chain into `RecursionError`, reviewer-1 F1), the pre-scan's character/token/line, or a role hint at exactly three codes (`source_not_supplied` + dataset `target_mismatch` → the `source` statement, `label_not_consistent` → the failing label's statement); every other post-projection refusal (file, data, request, limit) = `()`. `trace` = `project.statement_trace(tree)`, one closed role per top-level statement, set once projection returned. Both are `compare=False`: positions never enter verdict identity, and they are integers + roles, never source bytes. Tokenizer coordinates are converted (rows split at `\n` alone; its `unexpected EOF` column counts bytes ⇒ clamped into the row); a tokenizer `UnicodeDecodeError` (CPython 3.13, bare `\r` + non-ASCII) refuses `source_not_tokenizable`.

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
writes. `tools/mutants/project.toml` = 68 mutants over the projection predicates (23 at M13.3, +13
at M13.4, +10 at M13.6, +10 at Q9 -- the exact folder -- +1 at Q17, +2 at
Q34 -- the depth bound -- +9 at M13.8 against one REPLACED — `.reset_index()` now projects, so the
mutant asserting it never could was retired for the by-name-unwrap predicate the widening rests on),
with the two EQUIVALENT mutants documented in the file rather than listed. The accessor's receiver
guard is a COMPOUND one and carries one mutant per conjunct: `p5-accessor-receiver-unchecked` drops
the `_aggs` membership test, `p5-accessor-subscript-erased` drops the subscript test, and each
names a different red.
`tools/mutants/aggregate.toml` = 14 over the grouped reduction engine, and it documents THREE
deliberately unmutated predicates: R5 and R6 are absence claims the CSV profile refuses upstream, so
there is no branch left to neuter, and each witness takes the shape its own absence earns — R6 a
call-counting bomb on `_numeric_value`, R5 an arithmetic bound under 2**63 that a `max_table_rows`
widening reddens; and
`_reduce_int`'s `float(sum(values))` is profile-equivalent, because C10's int32 cell bound times
`max_table_rows` = 100,000 keeps every admitted integer sum under 2**48, and float64 carries every
integer exactly to 2**53. `tools/mutants/csvread.toml` = 15: G11's PUBLICATION seam + Q12's four range-split predicates +
Q8's ten header-read predicates. The counts are
computed in `aggregate.py` but carried forward from `read_columns`, and one module per catalogue is
what splits them. `tools/mutants/admit.toml` = 42: the accessor ROUTE (M13.8's five + M10.10's `line` entry), M13.2's
13 allowlist predicates (below), + 21 admission predicates, + Q26's two presentation-positional entries — the string-literal column subscript,
each `groupby(k)[c].reduce()` chain link, the cosmetic call-target set, the per-target style-keyword
map + `ADMITTED_TUPLE_KEYWORDS` arity. Every refusal ADMISSION lands is decided before projection
runs, so `project.toml` cannot reach it. Run
all four — a claim credited in one catalogue can sit unmutated in another.

A widening INVALIDATES anchors silently until the driver runs: M13.6 edited four lines that M13.3
and M13.4 mutants anchored on (`p4-y-over-inline-grid`, `d1-grid-selector-is-deep`,
`d2-rebind-dataset-names`, `d10-dataset-statement-coverage`), and the driver reported ANCHOR-MISS
rather than a kill. Rerun EVERY catalogue of a module a unit touches, not just the new one.

`admit.py`'s M13.2 allowlist = 13/13 killed, in `tools/mutants/admit.toml` (`M1`-`M13`). Each
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
