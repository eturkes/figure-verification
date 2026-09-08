---
paths:
  - "**/src/verifier/pysrc/**"
  - "**/tests/test_pysrc*.py"
  - "**/corpus/python/**"
  - "**/.agent/contracts/m13*.md"
---

# `pysrc-0.1` — model-authored Python verification (M13 law)

## Demo re-scope (user ruling; supersedes "simple arm = CSV bar/line/scatter")

Demo prompts plot MATH FUNCTIONS and import no data. A program that forgets an import is broken and
fails outright without the verifier — not the verifier's concern, and not a calibration lever, which
retires the unbound-`pd` problem (`archive/contracts/m12u7.md` § Derived: 24/50 design replies used
`pd` unbound, reading the simple arm at 33% under a bound-name predicate).

- Simple arm = `f(x)` over a stated interval.
- Complicated arm = tricky formulas, or math to perform and then plot, where the verifier can catch
  the RESULT being wrong.
- Motivation: under a clinician's complex specification even an intelligent model may plot something
  disingenuous to the data.
- Consequences: `corpus/python/` (88 prompts) and the 50-record `m12-design` capture are INVALIDATED
  and re-authored against math prompts; the projection targets the FORMULA plot spec, not the
  dataset one; OWUI `files`-payload plumbing is no longer needed; `capture_prompt_v1.txt` and its
  pinned sha256 need a v2 (the template names `/mnt/uploads/<dataset>`).

## Comparison surfaces — what the verifier can compare AT ALL

Every check is `claimed` vs `independent`, and is worth exactly as much as side B's independence
from the model.

| class | compares | catches | cannot catch |
|---|---|---|---|
| **I** admission | submitted AST vs closed allowlist | overreach: scipy/sklearn, `subplots(2,2)`, loops, themes, `cmap=` | anything wrong but admissible |
| **II** recomputation vs out-of-model truth | plotted values vs values derived from an artifact the USER supplied (uploaded CSV, or a target stated in the `expr-0.1` grammar) | the figure misrepresents the thing of record | nothing, within its scope |
| **III** internal consistency | projection vs projection | numeric-literal arrays (= model-supplied data), label/computation mismatch, grid/value length skew, `np.random` | a model that coherently plots the wrong function |
| **IV** invariants | projection vs law | NaN/Inf, non-monotonic grid, negative data on a log axis, sample explosion | any plausible wrong answer |

**Only class II catches coherent wrongness.** Removing the CSV removes source 1, so class II holds
only if the user states the quantity of record in machine-readable form. Rejected as a class-II
source: committed per-prompt expected answers — that moves the pass/fail boundary out of the
verifier, against ruling 5.

## Two forks left OPEN — they bind later, and the core is identical under all of them

- **(a) Declared target: absent | optional | mandatory.** `verify_python_source(src,
  declared_target=None)` carries all three; only the demo surface and the certificate's stated
  guarantee tier change.
- **(b) Observed-execution confirmation.** The sandbox reports the arrays matplotlib actually
  received (`gcf().axes[*].lines[*].get_xydata()`), the outlet filter returns them, and the PNG is
  withheld until they match the verifier's own recomputation. This closes the projection gap
  EMPIRICALLY instead of by construction and costs no new trust: OWUI already rewrites `plt.show()`
  to `savefig(BytesIO)`, so an environment layer around the model's bytes already exists and is
  accepted, and admitted code provably cannot tamper with the observer because the allowlist admits
  no idiom that could. It needs a user ruling, being the same category as ruling 1
  (verifier-(re)authored scripts REJECTED); read the environment/observation layer as OUTSIDE that
  ruling rather than inside it.

The verdict is decided statically either way — it must precede release — so the core is built on
projection + exact recomputation and observation is additive.

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
