# rev-m9-1 — formula contract + expression engine + evaluator

STATUS: IN-PROGRESS
FLUSHED: 3/3

## Unit verdicts

Fill one row per batch. verdict = CLEAN | FINDINGS. findings = comma-separated F-ids or `none`.

| unit | verdict | findings |
|---|---|---|
| M9.1 | FINDINGS | F1,F4,F7 |
| M9.2 | FINDINGS | F2,F3 |
| M9.3 | FINDINGS | F5,F6 |

## Findings

One block per finding. Header: `### F<n> | sev=HIGH|MED|LOW | <unit> | <file>:<line>`.
Required bullets: `divergence:` `impact:` `acceptance-check:` `red-test:`.
Zero findings overall ⇒ write the literal token NO-FINDINGS on its own line here.

### F1 | sev=HIGH | M9.1 | src/verifier/schema.py:82

- divergence: `FormulaXChannel`, `FormulaYChannel`, and `FormulaPlotSpec` have no runtime guards for their `Literal`/enum fields. Direct constructors and `msgspec.structs.replace` admit dunder-shaped near misses for `field`, `type`, `version`, `numeric_profile`, and `mark`; msgspec annotations bind decode only.
- impact: `verify_formula_run` returns an all-pass report for directly built specs with an invalid version, profile, or mark. An invalid profile is copied into `FormulaSource` while evaluation remains rational HALF_EVEN, so a typed caller can mint provenance that names an unimplemented numeric profile.
- acceptance-check: Add `__post_init__` guards for every formula literal/enum field; all seven near-miss cases must refuse, while valid decode and canonical-hash vectors remain byte-stable.
- red-test: `tests/test_review_m9_formula_contract.py`

### F2 | sev=HIGH | M9.2 | src/verifier/expr.py:115

- divergence: `Binary` has no runtime guard for its closed `BinaryOp`, and `print_expr` ends in an unconditional Binary-shaped catch-all. A dunder-shaped operator and an unrelated `op/left/right` object are admitted; `isinstance` also accepts undeclared subclasses of every AST variant.
- impact: The provenance-critical printer emits identical text for unequal objects: for example, `Number(1)` and an undeclared `Number` subclass both print `1`. Structural near misses and later variants can therefore collide with declared AST provenance.
- acceptance-check: Guard `Binary.op` against the exact four literals; dispatch on the exact six node classes; reject every other runtime type; preserve admitted printer vectors and valid-AST injectivity properties.
- red-test: `tests/test_review_m9_expr_closure.py`

### F3 | sev=LOW | M9.2 | src/verifier/expr.py:72

- divergence: `Number` documents a non-negative decimal-literal node, but `Number.__post_init__` admits `Fraction(-1)`. The archived claim that direct-construction guards admit exactly parser-admitted nodes is therefore false.
- impact: `print_expr(Number(value=Fraction(-1)))` emits `-1`, while parsing `-1` produces `(neg 1)`. A typed caller can bypass the parser-owned unary representation and create a noncanonical AST form, although the shipped formula pipeline never hand-builds this node.
- acceptance-check: Reject negative `Number.value` at direct construction; retain the signed magnitude ceiling and every parser-produced numeric boundary.
- red-test: `tests/test_review_m9_expr_closure.py`

### F4 | sev=MED | M9.1 | src/verifier/schema.py:156

- divergence: `FormulaDomain` has no runtime guard for the `Meta`-bounded integer fields. Direct construction admits `samples` outside 2..100000, `x_scale`/`y_scale` outside 0..12, and bool-as-int near misses.
- impact: The public typed evaluator leaks `ZeroDivisionError` for `samples=1` and `IndexError` for `samples=0`; `y_scale=-1` and scale 13 evaluate successfully. The strict byte decoder remains safe, but a directly built typed value bypasses the declared shape and evaluator totality.
- acceptance-check: Add exact-int range guards for all three fields; all nine boundary/type near misses must refuse, while decode boundaries 2/100000 and 0/12 remain admitted.
- red-test: `tests/test_review_m9_formula_contract.py`

### F7 | sev=HIGH | M9.1 | src/verifier/schema.py:82

- divergence: All five concrete formula structs admit undeclared subclasses. msgspec's deterministic encoder serializes subclass-only fields even though the strict formula decoder rejects those same fields as undeclared.
- impact: A `FormulaPlotSpec` subclass carrying `marker="__near__"` reaches an all-pass formula verification, and `spec_bytes` hashes bytes that `decode_formula_spec` refuses. The typed path can therefore certify a spec outside the closed formula schema and create an archive/replay self-inconsistency.
- acceptance-check: Reject undeclared subclasses for every concrete formula struct before construction or use; all five subclass near misses must refuse, while exact decoded classes keep identical canonical bytes.
- red-test: `tests/test_review_m9_formula_contract.py`

### F5 | sev=HIGH | M9.3 | src/verifier/eval.py:282

- divergence: `_admit_formula_sample_points` checks interior strictness while walking toward the stop endpoint. For `start=0`, `stop=0.04`, `samples=5`, `x_scale=0`, production refuses the index-1 collision before checking the inexact stop, while the oracle and declared `schedule/bounds/strictness` order select `formula.domain_bounded`.
- impact: Production returns `formula.sample_points_strictly_increasing` at work 12 while the oracle returns `formula.domain_bounded`. This falsifies check-ID parity on a valid joint-failure input and leaves the deterministic first-failure claim dependent on sample count.
- acceptance-check: Make endpoint boundedness globally precede strictness for the five-sample witness; pin the resulting work count as a hand-stated literal under the authoritative charge order, and retain the existing start/stop/collision single-failure literals.
- red-test: `tests/test_review_m9_eval_contract.py`

### F6 | sev=HIGH | M9.3 | src/verifier/expr.py:797

- divergence: `_interpret_expr` sends every unrecognized runtime node to `_interpret_binary`, and `_apply_binary` treats every operator other than add/sub/mul as division. Undeclared subclasses of all six AST variants also pass the `isinstance` dispatch.
- impact: Structural near misses evaluate as admitted ASTs, and a dunder-shaped operator evaluates as division. The closed-interpreter guarantee is false on the public runtime AST surface, and future variants can silently inherit existing semantics.
- acceptance-check: Dispatch on the exact six node classes, enumerate `div` explicitly, and reject every other node type/operator before evaluation; all structural, subclass-per-variant, and dunder-op reds must refuse without consuming work.
- red-test: `tests/test_review_m9_eval_contract.py`

## Notes

- M9.1 red proof: `pytest -q -p no:cacheprovider --no-cov tests/test_review_m9_formula_contract.py` → 21 failed, rc=1; ruff format/check + targeted mypy rc=0.
- M9.1 forged-path probes: invalid `version`/profile/mark each reached seven pass results; `samples=1/0` leaked `ZeroDivisionError`/`IndexError`; `y_scale=-1/13` completed. A `FormulaPlotSpec` subclass verified all-pass, encoded an undeclared `marker`, hashed successfully, then failed strict re-decode; probes rc=0.
- M9.2 red proof: `pytest -q -p no:cacheprovider --no-cov tests/test_review_m9_expr_closure.py` → 9 failed, rc=1; ruff format/check + targeted mypy rc=0.
- M9.2 policy probe: 32-term flat sum → depth=32/nodes=63/tokens=63; term 33 → `resource.formula_ast_depth`; `sqrt(4)`, `sqrt(2)`, sin/cos/tan/exp/log and dunder function near miss → `formula.functions_allowed`; pi/e and dunder name near miss → `formula.names_allowed`; rc=0.
- M9.3 red proof: `pytest -q -p no:cacheprovider --no-cov tests/test_review_m9_eval_contract.py` → 9 failed, rc=1; ruff format/check + targeted mypy rc=0.
- M9.3 tariff probe over 11 samples: `x=66`, `1=66`, `x+x=88`, `x*x+x=110`, all literal expectations matched; rc=0. Endpoint/collision probe: production=`formula.sample_points_strictly_increasing`/12, oracle=`formula.domain_bounded`; rc=0.
- Existing primary surfaces excluding reviewer reds: schema/canon/examples/expr/property/eval/oracle → 607 passed, rc=0.
- Committed-state baseline excluding the three reviewer-red files: 2900 passed, 6801 statements + 1406 branches at 100.00%, 8 existing `ResourceWarning`s, rc=0.
- Exact requested gate with reds: ruff format/check + mypy rc=0; pytest=39 failed reviewer reds + 2900 passed, 100.00% coverage, 8 warnings, rc=1.
- Reviewer red commit: `70af87f`.
