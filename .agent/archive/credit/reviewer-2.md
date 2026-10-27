# reviewer-2 — R293 survivor rulings

Status = all 4,270 rows adjudicated; canonical-group counterexample incorporated; full-multiset validator rc 0. Targets = nodes 1, 2, 3 of `.agent/credit/cr-twins-survivors.tsv`; check set fixed before row adjudication = mutant effect versus the per-node R293 contract below; non-contract behavior → open/register. Tracked tree read-only; deliverable/TSV = validator inputs.

## Contracts (fixed)

- Node 1 (`rows-in-order`): a raw scatter's colour and size each belong to the SAME CSV row as its (key,value) point, even when multiple rows share (key,value). Correct paired channels in CSV order pass; colour/size spliced across such rows must not obtain a valid joint explanation. Sources: `tests/test_figure_values.py:730-757` (four parametrized cases + docstring); `.agent/review.md:194` (R293); `src/verifier/figure/series.py:34-39,125-141`; `src/verifier/figure/explain.py:913-976` (`_bound`, `_explain_channel`).
- Node 2 (`rows-reversed`): the same raw-row binding contract, with correctly paired rows drawn in reverse CSV order still passing. Sources = node 1; the `rows-reversed` parameter is the positive permutation control.
- Node 3 (`grouped_channels_bind_to_one_group`): a grouped scatter's main value, colour, and size bind to the SAME group; a channel retains earlier channels' group-specific partners. Correct sums pass with three `sum` explanations; swapping one channel across groups must not acquire a joint explanation. Sources: `tests/test_figure_values.py:760-780`; `.agent/review.md:194`; `src/verifier/figure/explain.py:821-897,913-976`.

Scope boundary: R293 owns row/group alignment of encoded scatter channels, including enumeration/routing necessary to enforce that alignment. It does not own other artist families, plotting-integrity rules, CSV profile/limits, lexical anchoring, display formatting, source transport, unrelated Q45 computations, or every other explanation acceptance rule. Those behaviors remain open for these nodes, not globally untested.

## Verdict table

`pass` = ruling completeness, not mutation-run credit. Every specified mutant has an existing red witness; no new in-contract test is required by this ruling.

| check × node | verdict | rows | specified | open | never-executed class ruling |
|---|---|---:|---:|---:|---|
| R293 survivor adjudication × 1 | pass | 1436 | 21 | 1415 | open — 3894 |
| R293 survivor adjudication × 2 | pass | 1436 | 21 | 1415 | open — 3894 |
| R293 survivor adjudication × 3 | pass | 1398 | 6 | 1392 | open — 3851 |

Totals = 4,270 rows; 48 specified (22 distinct mutants), 4,222 open; specified-uncovered = 0. This is not a finding that production code is defective: the red outcomes below occur only after intentionally applying a mutant to a copy.

### Never-executed class (one ruling per node)

- Nodes 1 and 2: **open**, 3,894 each (= 5,330 total survivors − 1,436 executed-line survivors). The raw duplicate-(key,value) partner-construction, partner comparison, channel enumeration, and values routing all execute; the omitted slice concerns other mark families, grouped/index/computed source variants, request-only/failure reporting, and unrelated module contracts, not this raw joint-row control.
- Node 3: **open**, 3,851 (= 5,249 − 1,398). This node's grouped main/channel/partner paths execute; raw duplicate-row alignment, index/computed variants, other marks, and independent failure/reporting features remain outside its grouped-sum control.
- Class-level ruling, as requested, not a fresh enumeration of the omitted mutant identities. Counts = `git show -s --format=%B 7b61aa2`; the never-executed inventories were not rerun. Equivalence of every omitted mutant across the whole verifier is **unconfirmed**; this ruling says only that these nodes do not own those other contracts.

## Predicate audit + limits

- Read all 1,512 distinct executed-line mutation variants (27 source files), their original source lines, and the relevant enclosing code. Row multiplicity is preserved: 189 additional variants share coordinates with another mutant; identity = `(key, operator, node, mutated)`, not `(key,node)` alone.
- `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-rule.py` applied the explicit source-module/function classes below; exact channel/matching exceptions were held unresolved, probed, then ruled individually. Every open row names its actual enclosing function (AST range) and why that function's changed behavior is outside R293, or states a checked equivalence.
- Annotation-only `TypeAlias`/`Literal` changes and `typing.cast` type-string changes → open/equivalent for this runtime path: matching reads literal runtime families, not alias members; cast returns its second argument unchanged. Dataclass slots/frozen/constructor-policy changes → open/outside contract (not a claim that mutability is globally equivalent).
- `series.py:68,130,134,152` selecting scatter artist `-1` instead of `0` → open/equivalent: `parts.py::_marks` constructs a scatter Mark with exactly one artist. `Point.partner`'s default → open: `_channels` explicitly sets each channel's tuple.
- `explain.py:919,923,968` → open where the mutation affects unused index/computed-row/absent-partner variants or only returns an equivalent copied explanation. `_bound`'s `partners=None` and `_explain_channel`'s `bound=None` are **specified for every node**. Initial grouped-equivalence inference was rejected by new evidence: distinct text groups `1` and `1.0` share canonical numeric key 1, recreating ambiguous (key,value) pairs. GROUP-ALIAS passes pristine and goes red under each mutant (spliced chart returns Passed). The simpler a/b/c group-swap probe still blocks under both; that narrow control does not prove equivalence.
- Exploratory decoder identity / legend recognition failures were set aside as **register entries**, not expanded into R293. This follows the fixed scope's exclusion of other plotting-integrity rules; `enumeration/routing` here means checked-channel omission and the values/explanation path, not universal correctness of every prerequisite.

| source region read (repo-relative) | open predicate / owner outside R293 |
|---|---|
| `src/verifier/__init__.py:1-8` | version metadata |
| `figure/anchoring.py:1-354` | lexical names, aliases, negation, summaries |
| `figure/axes_rules.py:1-176` | scale, inversion, zero, clipping, ticks, orientation of other marks |
| `figure/columns.py:1-135` | lexical anchoring + G10 labels |
| `figure/computed.py:1-168` | Q45 transform vocabulary and numerical algorithms |
| `figure/description.py:1-801` | schema/geometry decoding, call metadata, colorbar/legend identity |
| `figure/explain.py:42-312,325-736,748-910,919-930,974-1079` | non-R293 vocabulary/canonicalization, source/filter/tie/preference policy, request fallback, resource accounting, formatting; exact exceptions below |
| `figure/inert.py:1-67`, `figure/interpret.py:1-226` | presentation, never channel matching |
| `figure/judge.py:1-184` | other integrity stages, sources/default policy, Q45 retry and display fields; exact values-bypass/failure exceptions below |
| `figure/keys.py:1-69` | axis-key decoding and slot bands |
| `figure/legends.py:1-196` | legend naming/proxies/visibility/encoding admission; not joint-row matching |
| `figure/mark_rules.py:1-324` | visibility, geometry, zero/overlap, counts, varying-marker key requirements |
| `figure/parts.py:1-311` | closed artist set, axes/legend ownership, size-key/outline census |
| `figure/reader.py:1-1157` | hooks, display sites, other geometry, limits, fonts, transport; exact colour-array omission exceptions below |
| `figure/reasons.py:1-79`, `figure/request.py:1-107` | reason metadata, typed-number grammar/ranges |
| `figure/series.py:1-172` | other mark families/names/site/default metadata; exact channel omission exceptions below |
| `figure/shapes.py:1-174`, `figure/sources.py:1-85`, `figure/ticks.py:1-169` | geometry/legend appearance, CSV column/profile interpretation, ticks |
| `pysrc/aggregate.py:1-214`, `pysrc/csvread.py:1-221` | reduction arithmetic/group ordering and CSV admission/profile (candidates supplied to alignment) |
| `pysrc/budget.py:1-57`, `pysrc/limits.py:1-25`, `pysrc/errors.py:1-24`, `pysrc/table.py:1-10` | resource ceilings/metering, refusal/type/export metadata |

`figure/` and `pysrc/` in that table are under `src/verifier/`. Exact source code, not a filename heuristic alone, decides the exclusions; each TSV row retains the mutated bytes and its function-specific reason.

## Runtime evidence

Target code = `66c3fe9e054fb3c3abc5424dc62120efc290bfcf`; source copy = `.scratch/agents/q4/reviewer-2-src/verifier/`. Every mutation is regenerated by the installed poodle operator, matched by coordinate + operator + resulting bytes, spliced at UTF-8 AST offsets, syntax-checked, and applied to the copy alone. Each child prints and asserts `CANARY …/.scratch/agents/q4/reviewer-2-src/verifier/__init__.py`. Each trial restores and byte-compares the touched source to the tracked source.

- Initial controls: five existing R293/R8 nodes passed (rc 0); `colour-key-honest` corpus passed (rc 0); eight supplemental scratch witnesses passed (rc 0).
- 28 distinct candidate mutants tested on the five-node selection (`-x`): 21 killed (rc 1), seven survived that selection (rc 0). Of those seven, the nonnumeric-column mutant is killed by existing `colour-key-honest`; six concern out-of-contract decoder/legend handling and are registered below. The decoder colour-property mutant also dies on `colour-key-honest`.
- Six grouped-path mutant probes: `explain.py:388,707,1072` and `judge.py:167` change GROUP-SPLICE; `explain.py:931,955` change GROUP-ALIAS. The latter two leave GROUP-SPLICE blocked but admit wrongly spliced channels under canonical-equivalent group keys. GROUP-ALIAS baseline: 1 passed, rc 0; each mutant: 1 failed, rc 1.
- Not run: full gate; full mutation-credit tool; every existing test; CPython 3.11; sandbox/live hosts. Original credit-run rc 2 is not repaired by these spot probes. An existing killer means the named test actually failed on that mutant, not that a whole credit run on that node has completed.
- One setup attempt failed before comparison-mutator trials (`AttributeError: 'NoneType' object has no attribute 'mutator_opts'`); supplying the operator's empty default option namespace fixed the probe harness. Completed records below supersede that incomplete attempt.

### Witness inputs + commands

- **RAW-SPLICE** = existing R293 `[sizes-swapped]`: CSV `key,value,colour,size\n1,2,3,11\n1,2,4,17\n`; draw x `[1,1]`, y `[2,2]`, colours `[3,4]`, sizes `[17,11]`, one colourbar + sizes legend; request `value by key with colour and size`. Expected `Blocked("value_not_found", 2)`.
- **R8-COLOUR** = existing `[colour]`: CSV `key,amount,encoded\n10,101,6\n10,102,7\n20,103,8\n`; honest colours `[6,7,8]` must pass; `[7,6,8]` must produce `Blocked("value_not_found", 5)`.
- **CORPUS-COLOUR** = existing `colour-key-honest`: `data/sales.csv`; draw orders/revenue with colours=orders + `legend_elements()`; request `Revenue against orders, coloured by orders`; must pass even with the CSV's other text columns.
- **GROUP-SPLICE** = supplemental `test_group_size_stays_with_its_group`: CSV `k,v,c,s\na,1,3,10\na,2,4,20\nb,5,6,70\nc,11,19,130\n`; `groupby('k').sum()` gives v `[3,5,11]`, c `[7,6,19]`, s `[30,70,130]`; draw sizes `[70,30,130]` instead; expected `Blocked("value_not_found", 5)`.
- **GROUP-ALIAS** = `reviewer-2-src/evidence/reviewer-2-group-alias.py::test_distinct_group_keys_with_one_numeric_reading_keep_joint_channels`: CSV `key,v,c,s\n1,1,1,5\n1,1,2,6\n1.0,1,2,8\n1.0,1,2,9\nx,3,3,10\nx,4,5,13\n`; group sums v `[2,2,7]`, c `[3,4,8]`, s `[11,17,23]`. Honest chart passes with three sum explanations; sizes `[17,11,23]` must block `value_not_found` at 5. The two numeric-looking keys are text because the key column also holds x. Exact executed commands + output: `evidence/reviewer-2-group-alias-{10,11}.{json,log}`.
- Trial command **P(i)** (retained replay path; original completed runs used the identical `/tmp/reviewer-2-*` scripts): `cd /home/eturkes/Projects/figure-verification && UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python /home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probe.py i`. The script invokes pytest with `--no-cov -p no:cacheprovider -x --tb=short` and the five named tests, behind the copy canary. `P(9)`'s five-node selection survives; its decisive follow-up command is the existing `colour-key-honest` node on the same mutant (`/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-corpus-09.json`).
- Supplemental command **G(i)**: same environment, `python /home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-extra.py i`; for i ∈ {5,6,10,11,13,17}, pytest selects only `test_group_size_stays_with_its_group`. Logs + scripts are retained under the source-copy `evidence/`; the close footer records the preserved-path replay.

## Specified row details

Each subsection is a non-author mutation-credit ruling, not a production finding. `killed by` = observed pytest rc 1 on the existing node. Raw nodes 1/2 share their negative witness; node 3 additionally has GROUP-SPLICE evidence for its own grouped contract.

### src/verifier/figure/explain.py:319:11 node 1 [Compare; probe 4]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _fits accepts value OR partners instead of both; cross-row colour/size combination obtains a complete explanation.
- Mutated bytes: `return _value_ok(point, explanation.pairs[position][1]) or (partners is None or partners[position] == point.partner)`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(4); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/04.log`.

### src/verifier/figure/explain.py:319:11 node 2 [Compare; probe 4]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _fits accepts value OR partners instead of both; cross-row colour/size combination obtains a complete explanation.
- Mutated bytes: `return _value_ok(point, explanation.pairs[position][1]) or (partners is None or partners[position] == point.partner)`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(4); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/04.log`.

### src/verifier/figure/explain.py:388:7 node 3 [Compare; probe 5]

- Contract: same-group channel binding + a blocked result for mismatches.
- Effect: _coverage routes keyed group channels to a value multiset; exchanging sizes across group keys becomes acceptable.
- Mutated bytes: `if series.shape != 'values':`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(5); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Blocked(reaso...sted', site=2) == Blocked(reaso...ound', site=2)`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/05.log`.
- Own grouped witness: GROUP-SPLICE; G(5) rc 1; `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-extra/05.log`.

### src/verifier/figure/explain.py:707:13 node 1 [Compare; probe 6]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _explain_series admits a partial candidate whenever ANY point matches; other channel points need no matching row/group or typed fallback.
- Mutated bytes: `elif any(matched) or all((m or r for m, r in zip(matched, by_request, strict=True))):`
- Existing killer: `tests/test_figure_values.py::test_r8_a_channel_stays_with_its_own_point[colour]`; command P(6); rc 1; input = R8-COLOUR (swapped arm).
- Output: `E   assert Passed(judged=Judged(figure=Figure(site=5, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...rpretation_ja='散布点: `t.csv` の `amount` 列 (`key` 列ごと)。\n点の色: `t.csv` の `encoded` 列 (`key` 列ごと)。3 件中 1 件を描画。依頼文の数値 2 件。') == Blocked(reason=… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/06.log`.

### src/verifier/figure/explain.py:707:13 node 2 [Compare; probe 6]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _explain_series admits a partial candidate whenever ANY point matches; other channel points need no matching row/group or typed fallback.
- Mutated bytes: `elif any(matched) or all((m or r for m, r in zip(matched, by_request, strict=True))):`
- Existing killer: `tests/test_figure_values.py::test_r8_a_channel_stays_with_its_own_point[colour]`; command P(6); rc 1; input = R8-COLOUR (swapped arm).
- Output: `E   assert Passed(judged=Judged(figure=Figure(site=5, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...rpretation_ja='散布点: `t.csv` の `amount` 列 (`key` 列ごと)。\n点の色: `t.csv` の `encoded` 列 (`key` 列ごと)。3 件中 1 件を描画。依頼文の数値 2 件。') == Blocked(reason=… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/06.log`.

### src/verifier/figure/explain.py:707:13 node 3 [Compare; probe 6]

- Contract: same-group channel binding + a blocked result for mismatches.
- Effect: _explain_series admits a partial candidate whenever ANY point matches; other channel points need no matching row/group or typed fallback.
- Mutated bytes: `elif any(matched) or all((m or r for m, r in zip(matched, by_request, strict=True))):`
- Existing killer: `tests/test_figure_values.py::test_r8_a_channel_stays_with_its_own_point[colour]`; command P(6); rc 1; input = R8-COLOUR (swapped arm).
- Output: `E   assert Passed(judged=Judged(figure=Figure(site=5, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...rpretation_ja='散布点: `t.csv` の `amount` 列 (`key` 列ごと)。\n点の色: `t.csv` の `encoded` 列 (`key` 列ごと)。3 件中 1 件を描画。依頼文の数値 2 件。') == Blocked(reason=… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/06.log`.
- Own grouped witness: GROUP-SPLICE; G(6) rc 1; `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-extra/06.log`.

### src/verifier/figure/explain.py:762:15 node 1 [FuncCall; probe 7]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _row_channels drops candidate partners, so channels no longer bind to their main point or earlier channels.
- Mutated bytes: `partners = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(7); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/07.log`.

### src/verifier/figure/explain.py:762:15 node 2 [FuncCall; probe 7]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _row_channels drops candidate partners, so channels no longer bind to their main point or earlier channels.
- Mutated bytes: `partners = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(7); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/07.log`.

### src/verifier/figure/explain.py:765:11 node 1 [Compare; probe 8]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _row_channels skips numeric columns; honest row-bound channels can no longer be explained (unit-key twins happen to find a Q45 fallback).
- Mutated bytes: `if numbers is not None:`
- Existing killer: `tests/test_figure_values.py::test_r8_a_channel_stays_with_its_own_point[colour]`; command P(8); rc 1; input = R8-COLOUR (honest arm).
- Output: `E   assert False`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/08.log`.

### src/verifier/figure/explain.py:765:11 node 2 [Compare; probe 8]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _row_channels skips numeric columns; honest row-bound channels can no longer be explained (unit-key twins happen to find a Q45 fallback).
- Mutated bytes: `if numbers is not None:`
- Existing killer: `tests/test_figure_values.py::test_r8_a_channel_stays_with_its_own_point[colour]`; command P(8); rc 1; input = R8-COLOUR (honest arm).
- Output: `E   assert False`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/08.log`.

### src/verifier/figure/explain.py:765:22 node 1 [Keyword; probe 9]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _row_channels fails to skip nonnumeric columns; an unrelated text column causes a None subscription while explaining honest channels.
- Mutated bytes: `if numbers is ' ':`
- Existing killer: `tests/test_figure_corpus.py::test_corpus_case[colour-key-honest]`; command P(9) + corpus follow-up; rc 1; input = CORPUS-COLOUR.
- Output: `E   TypeError: 'NoneType' object is not subscriptable`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-corpus-09.log`.

### src/verifier/figure/explain.py:765:22 node 2 [Keyword; probe 9]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _row_channels fails to skip nonnumeric columns; an unrelated text column causes a None subscription while explaining honest channels.
- Mutated bytes: `if numbers is ' ':`
- Existing killer: `tests/test_figure_corpus.py::test_corpus_case[colour-key-honest]`; command P(9) + corpus follow-up; rc 1; input = CORPUS-COLOUR.
- Output: `E   TypeError: 'NoneType' object is not subscriptable`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-corpus-09.log`.

### src/verifier/figure/explain.py:931:15 node 1 [FuncCall; probe 10]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _bound discards earlier-channel partner tuples, admitting spliced raw-row colour/size combinations.
- Mutated bytes: `partners = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(10); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/10.log`.

### src/verifier/figure/explain.py:931:15 node 2 [FuncCall; probe 10]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _bound discards earlier-channel partner tuples, admitting spliced raw-row colour/size combinations.
- Mutated bytes: `partners = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(10); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/10.log`.

### src/verifier/figure/explain.py:955:16 node 1 [FuncCall; probe 11]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _explain_channel discards prior channels; separate raw-row colour and size matches substitute for one joint row.
- Mutated bytes: `bound = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(11); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/11.log`.

### src/verifier/figure/explain.py:955:16 node 2 [FuncCall; probe 11]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _explain_channel discards prior channels; separate raw-row colour and size matches substitute for one joint row.
- Mutated bytes: `bound = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(11); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/11.log`.

### src/verifier/figure/explain.py:1052:15 node 1 [Compare; probe 12]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: explain routes every non-reference series through scalar-reference matching, eliminating scatter row/partner binding.
- Mutated bytes: `if series.shape != 'reference':`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(12); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...t sizes: numbers typed in the request.', interpretation_ja='散布点: 依頼文に入力された数値。\n点の色: 依頼文に入力された数値。\n点の大きさ: 依頼文に入力された数値。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/12.log`.

### src/verifier/figure/explain.py:1052:15 node 2 [Compare; probe 12]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: explain routes every non-reference series through scalar-reference matching, eliminating scatter row/partner binding.
- Mutated bytes: `if series.shape != 'reference':`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(12); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...t sizes: numbers typed in the request.', interpretation_ja='散布点: 依頼文に入力された数値。\n点の色: 依頼文に入力された数値。\n点の大きさ: 依頼文に入力された数値。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/12.log`.

### src/verifier/figure/explain.py:1072:15 node 1 [FuncCall; probe 13]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: explain fails to return an Unexplained result; mismatched channels reach publication as an invalid Choice and raise instead of blocking.
- Mutated bytes: `if None:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(13); rc 1; input = RAW-SPLICE.
- Output: `E   AttributeError: 'Unexplained' object has no attribute 'columns'`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/13.log`.

### src/verifier/figure/explain.py:1072:15 node 2 [FuncCall; probe 13]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: explain fails to return an Unexplained result; mismatched channels reach publication as an invalid Choice and raise instead of blocking.
- Mutated bytes: `if None:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(13); rc 1; input = RAW-SPLICE.
- Output: `E   AttributeError: 'Unexplained' object has no attribute 'columns'`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/13.log`.

### src/verifier/figure/explain.py:1072:15 node 3 [FuncCall; probe 13]

- Contract: same-group channel binding + a blocked result for mismatches.
- Effect: explain fails to return an Unexplained result; mismatched channels reach publication as an invalid Choice and raise instead of blocking.
- Mutated bytes: `if None:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(13); rc 1; input = RAW-SPLICE.
- Output: `E   AttributeError: 'Unexplained' object has no attribute 'columns'`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/13.log`.
- Own grouped witness: GROUP-SPLICE; G(13) rc 1; `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-extra/13.log`.

### src/verifier/figure/judge.py:152:21 node 1 [Compare; probe 14]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _values declares a CSV chart integrity-only whenever the request contains no numbers; mismatched channels bypass all value checks.
- Mutated bytes: `integrity_only = not sources.files or not context.request.numbers`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(14); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...ssed the integrity checks alone.', interpretation_ja='データが添付されておらず、依頼文にも数値がないため、値はデータと照合していません。グラフは完全性のチェックだけに合格しました。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/14.log`.

### src/verifier/figure/judge.py:152:21 node 2 [Compare; probe 14]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _values declares a CSV chart integrity-only whenever the request contains no numbers; mismatched channels bypass all value checks.
- Mutated bytes: `integrity_only = not sources.files or not context.request.numbers`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(14); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...ssed the integrity checks alone.', interpretation_ja='データが添付されておらず、依頼文にも数値がないため、値はデータと照合していません。グラフは完全性のチェックだけに合格しました。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/14.log`.

### src/verifier/figure/judge.py:152:21 node 1 [UnaryOp; probe 15]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _values treats attached files as the integrity-only condition; mismatched CSV channels bypass all value checks.
- Mutated bytes: `integrity_only = sources.files and not context.request.numbers`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(15); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...ssed the integrity checks alone.', interpretation_ja='データが添付されておらず、依頼文にも数値がないため、値はデータと照合していません。グラフは完全性のチェックだけに合格しました。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/15.log`.

### src/verifier/figure/judge.py:152:21 node 2 [UnaryOp; probe 15]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _values treats attached files as the integrity-only condition; mismatched CSV channels bypass all value checks.
- Mutated bytes: `integrity_only = sources.files and not context.request.numbers`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(15); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...ssed the integrity checks alone.', interpretation_ja='データが添付されておらず、依頼文にも数値がないため、値はデータと照合していません。グラフは完全性のチェックだけに合格しました。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/15.log`.

### src/verifier/figure/judge.py:165:11 node 1 [UnaryOp; probe 16]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _values inverts the decision to compare data; normal CSV charts skip every channel binding check.
- Mutated bytes: `if integrity_only:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(16); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...}, encodings=frozenset({(0, 0, 'sizes')}))), choices=(), integrity_only=False, interpretation='', interpretation_ja='') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/16.log`.

### src/verifier/figure/judge.py:165:11 node 2 [UnaryOp; probe 16]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _values inverts the decision to compare data; normal CSV charts skip every channel binding check.
- Mutated bytes: `if integrity_only:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(16); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...}, encodings=frozenset({(0, 0, 'sizes')}))), choices=(), integrity_only=False, interpretation='', interpretation_ja='') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/16.log`.

### src/verifier/figure/judge.py:167:15 node 1 [FuncCall; probe 17]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _values fails to convert Unexplained into a block; mismatched channels reach column handling as a non-iterable result.
- Mutated bytes: `if None:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(17); rc 1; input = RAW-SPLICE.
- Output: `E   TypeError: 'Unexplained' object is not iterable`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/17.log`.

### src/verifier/figure/judge.py:167:15 node 2 [FuncCall; probe 17]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: _values fails to convert Unexplained into a block; mismatched channels reach column handling as a non-iterable result.
- Mutated bytes: `if None:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(17); rc 1; input = RAW-SPLICE.
- Output: `E   TypeError: 'Unexplained' object is not iterable`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/17.log`.

### src/verifier/figure/judge.py:167:15 node 3 [FuncCall; probe 17]

- Contract: same-group channel binding + a blocked result for mismatches.
- Effect: _values fails to convert Unexplained into a block; mismatched channels reach column handling as a non-iterable result.
- Mutated bytes: `if None:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(17); rc 1; input = RAW-SPLICE.
- Output: `E   TypeError: 'Unexplained' object is not iterable`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/17.log`.
- Own grouped witness: GROUP-SPLICE; G(17) rc 1; `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-extra/17.log`.

### src/verifier/figure/reader.py:223:4 node 1 [Return; probe 20]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: reader._floats returns None for the scatter colour array; the values stage silently omits colour, so a cross-row colour/size chart passes.
- Mutated bytes: `return None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(20); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/20.log`.

### src/verifier/figure/reader.py:223:4 node 2 [Return; probe 20]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: reader._floats returns None for the scatter colour array; the values stage silently omits colour, so a cross-row colour/size chart passes.
- Mutated bytes: `return None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(20); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/20.log`.

### src/verifier/figure/reader.py:656:12 node 1 [FuncCall; probe 21]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: reader._scatter discards get_array(); colour is omitted from the checked channels and spliced raw-row pairs pass.
- Mutated bytes: `array = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(21); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/21.log`.

### src/verifier/figure/reader.py:656:12 node 2 [FuncCall; probe 21]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: reader._scatter discards get_array(); colour is omitted from the checked channels and spliced raw-row pairs pass.
- Mutated bytes: `array = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(21); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/21.log`.

### src/verifier/figure/series.py:133:29 node 1 [String; probe 22]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series._channels renames colors to an unshown token; colour is omitted and spliced raw-row pairs pass.
- Mutated bytes: `for channel, values in (('XXcolorsXX', geometry.array), ("sizes", geometry.sizes)):`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(22); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/22.log`.

### src/verifier/figure/series.py:133:29 node 2 [String; probe 22]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series._channels renames colors to an unshown token; colour is omitted and spliced raw-row pairs pass.
- Mutated bytes: `for channel, values in (('XXcolorsXX', geometry.array), ("sizes", geometry.sizes)):`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(22); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の大きさ: `t.csv` の `size` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/22.log`.

### src/verifier/figure/series.py:133:57 node 1 [String; probe 23]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series._channels renames sizes to an unshown token; size is omitted and spliced raw-row pairs pass.
- Mutated bytes: `for channel, values in (("colors", geometry.array), ('XXsizesXX', geometry.sizes)):`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(23); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/23.log`.

### src/verifier/figure/series.py:133:57 node 2 [String; probe 23]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series._channels renames sizes to an unshown token; size is omitted and spliced raw-row pairs pass.
- Mutated bytes: `for channel, values in (("colors", geometry.array), ('XXsizesXX', geometry.sizes)):`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(23); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。\n点の色: `t.csv` の `colour` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/23.log`.

### src/verifier/figure/series.py:134:36 node 1 [DictArray; probe 24]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series._channels tests the channel key with artist=None; both channels disappear and spliced raw-row pairs pass.
- Mutated bytes: `if values and (panel.index, None, channel) in shown:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(24); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...se, interpretation='Points: `value` by `key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/24.log`.

### src/verifier/figure/series.py:134:36 node 2 [DictArray; probe 24]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series._channels tests the channel key with artist=None; both channels disappear and spliced raw-row pairs pass.
- Mutated bytes: `if values and (panel.index, None, channel) in shown:`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(24); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...se, interpretation='Points: `value` by `key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/24.log`.

### src/verifier/figure/series.py:139:12 node 1 [FuncCall; probe 25]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series._channels omits appending its channels; spliced raw-row pairs pass with the scatter main alone.
- Mutated bytes: `None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(25); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...se, interpretation='Points: `value` by `key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/25.log`.

### src/verifier/figure/series.py:139:12 node 2 [FuncCall; probe 25]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series._channels omits appending its channels; spliced raw-row pairs pass with the scatter main alone.
- Mutated bytes: `None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(25); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...se, interpretation='Points: `value` by `key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/25.log`.

### src/verifier/figure/series.py:167:15 node 1 [Compare; probe 26]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series inverts its scatter routing guard; scatter channels disappear and spliced raw-row pairs pass.
- Mutated bytes: `if mark.family != 'scatter':`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(26); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...se, interpretation='Points: `value` by `key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/26.log`.

### src/verifier/figure/series.py:167:15 node 2 [Compare; probe 26]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series inverts its scatter routing guard; scatter channels disappear and spliced raw-row pairs pass.
- Mutated bytes: `if mark.family != 'scatter':`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(26); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...se, interpretation='Points: `value` by `key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/26.log`.

### src/verifier/figure/series.py:167:30 node 1 [String; probe 27]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series never recognizes the scatter family; scatter channels disappear and spliced raw-row pairs pass.
- Mutated bytes: `if mark.family == 'XXscatterXX':`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(27); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...se, interpretation='Points: `value` by `key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/27.log`.

### src/verifier/figure/series.py:167:30 node 2 [String; probe 27]

- Contract: same-raw-row channel binding; paired honest channels pass, spliced rows block.
- Effect: series never recognizes the scatter family; scatter channels disappear and spliced raw-row pairs pass.
- Mutated bytes: `if mark.family == 'XXscatterXX':`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(27); rc 1; input = RAW-SPLICE.
- Output: `E   AssertionError: assert Passed(judged=Judged(figure=Figure(site=2, titles=(None, None, None), texts=(), legends=(), others=(), axes=(Axes(cls=...se, interpretation='Points: `value` by `key` from `t.csv`.', interpretation_ja='散布点: `t.csv` の `value` 列 (`key` 列ごと)。') ==… [log retains full line]`; full evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probes/27.log`.

### src/verifier/figure/explain.py:931:15 node 3 [FuncCall; probe 10]

- Contract: colour + size bind to one group, including distinct group labels with the same canonical numeric reading.
- Mutated bytes: `partners = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(10); rc 1.
- Own grouped witness: GROUP-ALIAS; pristine 1 passed (rc 0), mutant 1 failed (rc 1). Mutant output: `E   AssertionError: Passed(...)` where `Blocked(reason='value_not_found', site=5)` is required.
- Evidence: `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-group-alias-10.log`; exact argv + mutant identity: sibling `.json`. This evidence reverses the earlier open/equivalent ruling.

### src/verifier/figure/explain.py:955:16 node 3 [FuncCall; probe 11]

- Contract: colour + size bind to one group, including distinct group labels with the same canonical numeric reading.
- Mutated bytes: `bound = None`
- Existing killer: `tests/test_figure_values.py::test_cr_r293_a_point_s_colour_and_size_come_from_one_row[sizes-swapped]`; command P(11); rc 1.
- Own grouped witness: GROUP-ALIAS; pristine 1 passed (rc 0), mutant 1 failed (rc 1). Mutant output: `E   AssertionError: Passed(...)` where `Blocked(reason='value_not_found', site=5)` is required.
- Evidence: `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-group-alias-11.log`; exact argv + mutant identity: sibling `.json`. This evidence reverses the earlier open/equivalent ruling.

## Register (outside R293; mutant effects, not defects in current production)

- **REG-DESC-PROP** — `description.py:26:44` excludes the admitted `colors` legend property. Existing `tests/test_figure_corpus.py::test_corpus_case[colour-key-honest]` kills it (rc 1); no new witness needed. Evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-corpus-00.log`.
- **REG-DESC-INDEX** — `description.py:698:22` (two variants) + `:698:38` duplicate one member of `(axes,artist)`. An honest paired scatter preceded by `plt.text(1,2,'note')` has a nonzero artist index and blocks as `axes_not_judged` under each mutant; scratch `test_correct_channels_with_nonzero_artist_index[raw]` red, baseline green. Evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-extra/{01,02,03}.log`. Existing-suite coverage **unconfirmed**: searched figure tests and corpus candidates; no whole-suite mutant run.
- **REG-LEGEND-BREAK** — `legends.py:155:12` (`continue` → `break`) reads the first encoding alone. A valid combined colour+size key legend then blocks `marker_size_varies`; scratch `test_correct_channels_with_both_legend_keys[raw]` red, baseline green. Evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-extra/18.log`. Existing-suite coverage **unconfirmed** beyond the named five-node selection + bounded source search.
- **REG-LEGEND-UNION** — `legends.py:186:8` (`encodings |= keys` → `encodings = keys`) forgets earlier panels' size keys. Two otherwise valid panels then block `marker_size_varies` in the first; scratch `test_later_panel_preserves_first_panel_channels[raw]` red, baseline green. Evidence `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-extra/19.log`. Existing-suite coverage **unconfirmed** beyond the named selection + source search.
- Original commit `7b61aa2` records rc 2 mutation runs. The changed abnormal/invalid/timeout semantics and any full reruns belong to MAIN; this report does not claim credit-run completion.

## Close checks

- Full-multiset validator: `python3 /home/eturkes/Projects/figure-verification/.scratch/agents/q4/seed.py check reviewer-2 1,2,3` → rc 0, `4270 rows, 0 problems`.
- Validator positive control: one ruling temporarily `unknown` → rc 1 (`line 2: ruling 'unknown'`); restored byte-for-byte → rc 0. Logs: `reviewer-2-src/evidence/reviewer-2-validator-{red,green}.log`.
- Reviewed nodes 1/2/3 on restored copy: 3 passed, rc 0; canary confirmed copied verifier import. Log: `reviewer-2-src/evidence/reviewer-2-target-controls.log`.
- Retained replay `uv run --no-sync --locked python .scratch/agents/q4/reviewer-2-src/evidence/reviewer-2-probe.py 4` → existing R293 sizes-swapped node red (pytest rc 1, 1 failed); source restored after the run. Probe driver rc 0 means evidence collected, not that the mutated test passed.
- All copied verifier `.py` bytes match the tracked source after restoration. Tracked files untouched; no git writes; no environment sync. Rulings + evidence left unstaged for MAIN.
- Evidence root: `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-2-src/evidence/`. Original temporary `reviewer-2-*` paths removed after preserving them. Replays use the retained scripts/candidate manifest; old JSON command records retain the exact original executed argv.

reviewer-2-DONE-1
