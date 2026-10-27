# reviewer-5 — mutation-credit rulings, nodes 10 + 11

Target revision = `66c3fe9e054fb3c3abc5424dc62120efc290bfcf`; examined implementation/test files unchanged from that revision. Root = `/home/eturkes/Projects/figure-verification`.

**1,909/1,909 rows adjudicated. 11 specified: six have an existing-test kill; five need additional coverage. 1,898 open.** These findings concern mutation credit, not defects in the unmutated implementation. Severity = **minor** for each specified row.

## Fixed contracts

Fixed before survivor adjudication; node-level, not entire-product correctness:

- **10 / R309.** An otherwise admissible figure whose values need its sole attached CSV must return `Blocked("csv_too_large", <drawing site>)` when that file's byte length exceeds `DEFAULT_LIMITS.max_csv_bytes`; length decides before decoding/parsing. The strict boundary is included: a file at the byte limit is not oversized. An oversized file's contents do not change this refusal. Sources: `tests/test_figure_values.py:136-143` (docstring + assertion); `.agent/review.md:210` (R309 inventory gap + end-to-end witness); `src/verifier/pysrc/csvread.py:108-158` (`_read_csv`); `src/verifier/figure/sources.py:74-85` (`read_table`); `src/verifier/figure/judge.py:116-184` (`judge`, `_values`); `src/verifier/figure/explain.py:1039-1079` (unreadable-file reason propagation). Other resource limits/integrity rules have their own contracts. The sole-file/value-needs-CSV qualifications matter: the judge does not reject every unused attachment unconditionally.
- **11 / R285 `[elif]`.** Once parsed, the marks listing for a plotting statement inside an `elif` body keeps the whole plotting statement and its enclosing `if`/`elif` headers, without adding unrelated sibling/body statements. This control owns continuation-header widening, not recorded-row selection, parse/work budgets, failure-site handling or preparation tracing. `else`/`finally` fault variants are separate parametrized cases. Sources: `tests/test_paste_in_excerpts.py:465-484` (all five inputs, expected sets, docstring); `.agent/review.md:186` (R285 acceptance/fix); `webui/paste_in/excerpts.py:276-373` (`_span`, `_blocks`, `_statements`, `_shown`, `_Program.widen`) + `457-473` (`excerpts`). Multiline statements/headers and multiple plotted statements are domain variants, not a contract restricted to the five-line fixture.

## Verdict table

| check × target | verdict | rows | specified | open | never-executed survivor class |
|---|---|---:|---:|---:|---|
| R309 byte refusal × node 10 | finding C1–C5 | 978 | 5 (2 existing kills, 3 uncovered) | 973 | **open**, 4,931: code outside this node's executed path; not evidence of global equivalence |
| R285 elif widening × node 11 | finding E1–E6 | 931 | 6 (4 existing kills, 2 uncovered) | 925 | **open**, 6,443: code outside this control's executed path; other branch/failure/preparation behavior belongs to other contracts |

Never-executed counts = `git show -s --format=%B 7b61aa2`: node 10, 5,909 survived − 978 executed-line survivors; node 11, 7,374 − 931. As requested, these receive one scope ruling per node, not individual mutant review. A non-executed-line class is not a claim that those mutations preserve behavior on other inputs.

## Checked bulk predicates

Classifier = `.scratch/agents/q4/reviewer-5-src/evidence/rule.py`; input/output = `.scratch/agents/q4/reviewer-5.tsv`. It uses exact file paths, line ranges and complete mutated text, preserves `(key, operator, node, mutated)` and ordering, and asserts 1,909 data rows. Duplicate location keys with different mutations remain separate rows. Explicit specified predicates match the eleven details below before any bulk `open` predicate.

Module-domain predicates were checked against the actual module headers, top-level AST symbol inventory and mutation loci; this was a contract-scope adjudication, not a second whole-codebase defect review. Their `open` ruling means **outside this node's contract**, not globally harmless:

| exact path predicate (`src/verifier/` prefix below unless stated) | checked code domain / why open for these contracts |
|---|---|
| `__init__.py:1-8` | Package version metadata; neither byte refusal nor header widening. |
| `figure/anchoring.py`, `figure/columns.py` | Lexical naming and drawn-column/label checks; module headers + symbols, notably `columns.py:1-135`. No attachment-length or AST-header decision. |
| `figure/axes_rules.py` | `value_on_x:48-50`, `_check_scales:82-92`, `_check_zero:95-103`, `key_axes:106-120`, `_check_ticks:123-127`, `_check_clipping:130-153`, `check_axes:170-176`: independent figure-integrity predicates. |
| `figure/mark_rules.py` | `_record_values:49-54`, `_clear:61-62`, `_no_ink:105-118`, `_check_drawn:121-143`, bar/width/order checks `158-214`, dispatch `295-324`: mark integrity, not either target contract. |
| `figure/parts.py`, `figure/shapes.py`, `figure/series.py`, `figure/keys.py`, `figure/legends.py` | Artist-family/panel classification, geometry/series/key extraction and legend association. Sources checked by module header + named function ranges in the AST inventory (`parts.py:49-311`, `shapes.py:31-169`, `series.py:34-172`, `keys.py:21-69`, `legends.py:31-196`). These produce the already-described/otherwise-admissible chart on which the target behaviors operate. |
| `figure/reader.py`, `figure/description.py` | Renderer/hooks/recorded-site production and closed description decoding, respectively. Mutation-locus inventory covers reader hooks and run/render functions (`reader.py:100-1157`), schema records and decoders (`description.py:235-801`). These own facts/schema, not the later byte-count or source-statement widening rule. No broad reader-equivalence claim. |
| `figure/ticks.py`, `figure/request.py` | Numeric/date tick semantics (`51-169`) and typed-number/range parsing (`48-107`). Independent contracts. |
| `figure/computed.py`, `pysrc/aggregate.py` | Admitted computations and pandas-compatible reductions; module-level vocabulary/operators plus `aggregate.py::kahan_sum:91-107`. Refused CSV bytes produce no numeric table. |
| `figure/inert.py`, `figure/interpret.py` | Display escaping and passed-figure prose. Neither target contract asserts their text. |
| `pysrc/table.py` | Cell type declaration only. |
| `webui/paste_in/checks.py`, `webui/paste_in/reasons.py` | Check registry/text/HTML metadata and failure display text. Excerpt widening consumes the `Check` annotation, not these display constants. |

Target-adjacent predicates checked more narrowly:

- `pysrc/csvread.py`: every table row before line 108 is an export/type declaration or cell-profile constant; `_read_csv:109-110` decides oversized length before profile/decode work. All node-10 survivors on those two guard lines are specified (C1–C3). Node 11 owns no CSV behavior.
- `pysrc/limits.py:12`: node-10 default-byte-cap ±1 are specified (C4–C5). Other defaults and dataclass constructor/storage options (`8-22`) belong to other resource/API contracts; node 11 owns none.
- `pysrc/budget.py:14-57`: exports, storage and work-meter validation, not byte length; an oversized file is refused before CSV parsing charges. `pysrc/errors.py:11-24` + `figure/reasons.py:11-79`: taxonomy, dataclass/exception representation or default site; the exercised refusal carries explicit `.code` and drawing site.
- `figure/sources.py:26-51`: source-record storage and readable-table `rows` property. `read_table:79` changes the string argument of `typing.cast`; `cast` returns the refusal code unchanged. These survivors do not change length refusal.
- `figure/judge.py`: integrity checks/record construction (`29-97`), computed-value retry (`112-139`) or other value-stage state (`152-163`). `csv_too_large` is not one of the retry reasons. `figure/explain.py`: candidate/key/arithmetic machinery is outside this sole-unreadable-file behavior; at `1073`, `and` versus `or` agrees when outcome=`value_not_found` and an unreadable file is present; at `1074`, first versus last unreadable file agrees for the sole-file precondition.
- `webui/paste_in/excerpts.py:21`: annotation-only `Lines` alias. `24,449,467`: parse bound/fallback, separate from widening after a parse. `28,174-263,344-349,375-445,470-472`: preparation trace/budget; its result only joins values/columns. `48-73`: axis/tick call selection. `76-113`: recorded-row selection/aggregation upstream of widening. `266`: dataclass storage/mutability.
- Excerpts `_blocks`: `287` discovers `except`, `290` discovers `finally`, `294` updates the end used by a following `finally` (an `elif` has no following block); `295` handles `match`. `_statements:318` reads decorators; `324` reads an explicit first `case` header (an `if` first block has `None`); `329,334` track scope/ancestors for preparation; `333` indexes direct failure sites in header text. These are outside this control. `340` changes whole-vs-header mode for a **recorded compound statement**; an ordinary plotting statement in the body has `own == whole`. `462,464` handle absent descriptions/failing rows; the control has a description and no failing row. All other excerpt survivors in the table hit explicit specified predicates.

## Evidence / replay

Source-copy provenance printed and checked:

`/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-5-src/verifier/__init__.py`

For existing excerpt tests, `webui.paste_in.excerpts.__file__` was also printed under that copy. The helper loads this copied module into its qualified import slot; other dependencies resolve through the copied `verifier` and original `webui` package. Every mutant applies to a copy; each mutated line is checked; a `finally` restores exact original bytes. No tracked target edits, no venv sync, no mutation tool/full gate.

Retained evidence directory:

`/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-5-src/evidence/`

- `probe.py`, `run-probes.py`, `probes.log`: 11 baseline rc 0 → 11 distinct assertion rc 1 witnesses.
- `existing.py`, `run-existing.py`, `existing.log`: eight baseline-green candidate checks; six existing-test kills; E1 candidate remains green; all five R285 cases remain green under E3.
- `rule.py`: exact bulk predicates and specified-row lookup.

Commands (drivers apply the named mutant before invoking the test and restore it afterwards):

```sh
cd /home/eturkes/Projects/figure-verification
export UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy
uv run --no-sync --locked python /home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-5-src/evidence/run-probes.py
uv run --no-sync --locked python /home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-5-src/evidence/run-existing.py
```

The focused witness command within the first driver = copied-environment `python -B …/evidence/probe.py <case>`; within the second = `python -B …/evidence/existing.py '<pytest node>'`, which runs `pytest --no-cov -p no:cacheprovider -q -x <node>`. Original runs used identical helpers under `/tmp/reviewer-5-*`; retained versions differ only in helper path references.

## Specified details

### C1 — `src/verifier/pysrc/csvread.py:109:7` node 10 — minor

- Mutated: `if len(content) <= limits.max_csv_bytes:`.
- Contract: oversized length refuses before content parsing. Fixture's 2,000,001 rows hide the inverted byte guard behind the independent row ceiling.
- **Existing kill:** `tests/test_pysrc_csv.py::test_each_ceiling_refuses_before_the_work_it_bounds[bytes]`; baseline rc 0 → mutant rc 1: `Failed: DID NOT RAISE PysrcRefusalError` at `tests/test_pysrc_csv.py:224`.
- Focused input (`oversize-malformed`): `read_table('big.csv', b'\x00' * 8_000_008)`. Baseline `Unreadable(..., 'csv_too_large')`; mutant `Unreadable(..., 'csv_not_parsable')`; rc 1, `AssertionError: expected length refusal`.

### C2 — `src/verifier/pysrc/csvread.py:109:7` node 10 — minor

- Mutated: `if len(content) >= limits.max_csv_bytes:`.
- Contract: the exact byte limit is not oversized.
- **Uncovered.** Focused input (`at-limit`): valid CSV bytes `b'k,v\n' + (b'a' * 497 + b',1\n') * 15999 + b'b' * 493 + b',1\n'`, exactly 8,000,000 bytes; other row/cell/work limits hold. Call `read_table('big.csv', content)`.
- Baseline `Table`; mutant `Unreadable:csv_too_large`; rc 1, `AssertionError: expected Table at exact byte limit, got Unreadable:csv_too_large`.
- Cheap additional coverage for this operator can use `_read_csv` with a small injected byte limit and a CSV of exactly that length; the retained probe also covers the default boundary.

### C3 — `src/verifier/pysrc/csvread.py:110:8` node 10 — minor

- Mutated: `None` (drops `_refuse("csv_too_large")`).
- Contract/masking mechanism: C1.
- **Existing kill:** same `[bytes]` node as C1; baseline rc 0 → mutant rc 1, `Failed: DID NOT RAISE PysrcRefusalError`.
- Focused input (`oversize-malformed`): same 8,000,008 NUL bytes. Baseline `csv_too_large`; mutant `csv_not_parsable`; rc 1, `AssertionError: expected length refusal`.

### C4 — `src/verifier/pysrc/limits.py:12:25` node 10 — minor

- Mutated: `max_csv_bytes: int = 7999999`.
- Contract: the fixed 8,000,000-byte default admits its exact boundary; a lower cap changes that boundary.
- **Uncovered.** Input/observable = C2's exact-8,000,000 valid CSV (`at-limit`). Baseline `Table`; mutant `Unreadable:csv_too_large`; rc 1 with the same exact-limit assertion failure.

### C5 — `src/verifier/pysrc/limits.py:12:25` node 10 — minor

- Mutated: `max_csv_bytes: int = 8000001`.
- Contract: the first byte beyond 8,000,000 refuses before parsing.
- **Uncovered.** Focused input (`first-oversize`): `read_table('big.csv', b'\x00' * 8_000_001)`.
- Baseline `Unreadable(..., 'csv_too_large')`; mutant `Unreadable(..., 'csv_not_parsable')`; rc 1, `AssertionError: expected length refusal`.

### E1 — `webui/paste_in/excerpts.py:277:40` node 11 — minor

- Mutated: `return range(first, max(first, body[-1].lineno - 1) + 1)`.
- Contract: an enclosing header stops before the **first** body statement, not the last. A body with an unrelated statement before its plot exposes the extra line.
- **Uncovered.** Focused input (`span-last`), direct `_Program(ast.parse(program)).widen({5})`:

```text
if False:
    pass
elif True:
    x = 0
    plt.plot([1, 2])
```

- Baseline `[1, 3, 5]`; mutant `[1, 3, 4, 5]`; rc 1: `AssertionError: header/statement widening: got [1, 3, 4, 5], expected [1, 3, 5]`.
- Existing candidate `tests/test_paste_in_excerpts.py::test_e3_values_list_the_statements_that_prepare_the_drawn_data[def-whole]` remains green (baseline/mutant rc 0). It already expects the full def, so it does not expose this unwanted body inclusion.

### E2 — `webui/paste_in/excerpts.py:277:52` node 11 — minor

- Mutated: `return range(first, max(first, body[0].lineno - 2) + 1)`.
- Contract: include every line of the enclosing header, including the closing `):`.
- **Existing kill:** `tests/test_paste_in_excerpts.py::test_r1_f3_a_failure_in_an_except_header_widens_to_that_header`; baseline rc 0 → mutant rc 1, `{'run': (1, 3, 4)} != {'run': (1, 3, 4, 5)}` at test line 331.
- Focused elif input (`span-short`): `if False:\n    pass\nelif (\n    True\n):\n    plt.plot([1, 2])\n`, widen `{6}`. Baseline `[1, 3, 4, 5, 6]`; mutant `[1, 3, 4, 6]`; rc 1 with that exact set mismatch.

### E3 — `webui/paste_in/excerpts.py:286:17` node 11 — minor

- Mutated: `end = (body[-0].end_lineno or node.lineno) if body else node.lineno`.
- Contract: the next continuation header starts after the **last** prior-arm statement. Using the first pulls skipped prior-arm statements into the listing.
- **Uncovered.** Focused input (`end-first`), widen `{5}`:

```text
if False:
    x = 0
    y = 0
elif True:
    plt.plot([1, 2])
```

- Baseline `[1, 4, 5]`; mutant `[1, 3, 4, 5]`; rc 1 with that exact mismatch.
- All five existing `test_cr_r285_a_statement_shows_the_else_or_finally_header_it_sits_under` cases remain green under this mutant (rc 0, `5 passed`): their prior arms each hold one statement.

### E4 — `webui/paste_in/excerpts.py:293:39` node 11 — minor

- Mutated: `blocks.append((_span(end + 2, block), block))`.
- Contract: continuation context starts immediately after the preceding body; `+2` can pull the next body statement into an `elif` header and drop an `else` header.
- **Existing kill:** `tests/test_paste_in_excerpts.py::test_cr_r285_a_statement_shows_the_else_or_finally_header_it_sits_under[if-else]`; baseline rc 0 → mutant rc 1, `frozenset({2, 5}) != {2, 4, 5}` at test line 484.
- Focused elif input (`span-plus-two`) = E1; widen `{5}`. Baseline `[1, 3, 5]`; mutant `[1, 3, 4, 5]`; rc 1 with that exact mismatch.

### E5 — `webui/paste_in/excerpts.py:320:34` node 11 — minor

- Mutated: `whole = range(start, (node.end_lineno and node.lineno) + 1)`.
- Contract: retain a plotting statement's complete multiline span, not just its first line.
- **Existing kill:** `tests/test_paste_in_excerpts.py::test_e2_a_line_widens_to_its_statement_and_the_blocks_around_it`; baseline rc 0 → mutant rc 1, `(4,) != (4, 5, 6, 7)` at test line 103.
- Focused input (`whole-first`): `if False:\n    pass\nelif True:\n    plt.plot(\n        [1, 2]\n    )\n`, widen `{4}`. Baseline `[1, 3, 4, 5, 6]`; mutant `[1, 3, 4]`; rc 1 with that mismatch.

### E6 — `webui/paste_in/excerpts.py:371:16` node 11 — minor

- Mutated: `shown = set().union(*(_shown(self.statements[i]) for i in held))`.
- Contract: widening accumulates each plotted statement and its headers; a later recorded line does not replace an earlier statement.
- **Existing kill:** `tests/test_paste_in_excerpts.py::test_e1_each_row_lists_the_parts_its_check_reads`; baseline rc 0 → mutant rc 1, including `{'marks': (7,)} != {'marks': (3, 7, 9, 10)}` at test line 54.
- Focused input (`widen-replace`): `if False:\n    pass\nelif True:\n    plt.plot([1, 2])\n    plt.plot([2, 3])\n`, widen `{4, 5}`. Baseline `[1, 3, 4, 5]`; mutant `[1, 3, 5]`; rc 1 with that mismatch. No ordering claim about arbitrary sets is needed: replacement loses one of the two distinct statements whichever executes last.

## Register / limits

- R309's repeated-row fixture masks byte-guard deletion/inversion behind `max_csv_rows`; C1/C3 are already killed by the independent `[bytes]` node. Additional end-to-end assertion value is boundary/content independence, not another huge repeated-row fixture.
- **Unconfirmed full-suite absence** for C2/C4/C5/E1/E3: searched `tests/**/*.py` for `max_csv_bytes`/`csv_too_large`, read the CSV ceiling cases, OWUI capped-file witness and complete excerpt suite. Ran the named existing candidates above; did not mutate-run the entire suite. `uncovered` means no existing kill established here, with a confirmed baseline-green/new-red witness supplied.
- Historical record lists 80 abnormal node-10 trials + 154 abnormal node-11 trials; outside the supplied survivor rows and this assignment. No renewed mutation-credit/full-suite claim.
- Non-executed-line survivors were ruled as requested classes, not individually inspected. Module-scope open rulings are bounded to the fixed node contracts.
- One initial lookup assumed filenames `test_pysrc_csvread.py`/`test_pysrc_limits.py`; command rc 2 (files absent). Replaced with a repository-wide named-path search; actual file = `tests/test_pysrc_csv.py`. No absence conclusion used the failed lookup.
- Other tracked working-tree edits were already present while reviewing; they are outside target/write ownership. No target file was edited. Scratch witness copies and logs are retained for harvest.

## Validation

`python3 /home/eturkes/Projects/figure-verification/.scratch/agents/q4/seed.py check reviewer-5 10,11` → rc 0, `reviewer-5: 1909 rows, 0 problems`, rerun with D2's full-mutant-multiset validator. An independent ordered comparison also matched all 1,909 `(key, operator, node, mutated)` identities. Ruling unknown count = 0; every specified reason follows D1; marker verified. Both retained replay commands passed (11 baseline greens/11 focused reds; six existing kills, two surviving candidate checks). All 33 examined source/test paths byte-match revision `66c3fe9`; copied sources restored; seven `/tmp/reviewer-5-*` helpers/logs removed after retention; copied bytecode caches removed.

reviewer-5-DONE-1
