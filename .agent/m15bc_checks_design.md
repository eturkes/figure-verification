# M1.5b + M1.5c — encoding/label checks: transcription recipe

TRANSCRIBE, do NOT re-derive. The `_encoding_checks` / `_unit_source` algorithm overflowed a
200K window in DESIGN alone, then again with M1.5b bundled whole → split into **M1.5b**
(structural: fields-exist + axis-types) + **M1.5c** (label-unit + count-exempt lineage), each a
coverage-safe commit. The code below is believed-correct (analyzed, symbol-checked vs `schema.py`
/ `ingest.py`) but was reverted BEFORE any gate run → reach the gate EARLY, verify incrementally,
salvage-continue on surprises (overflow ≠ bad work — the M1.4d lesson). Delete this doc at M1 review.

Baseline: `src/verifier/checks.py` is at M1.5a (`660ea05`). Confirmed symbols (no re-grep needed):
`schema.ChannelType` = `Literal["quantitative","temporal","ordinal","nominal"]`; `schema.Aggregate`
(`.measures: tuple[Measure,...]`); `schema.Measure`(`.field`,`.fn`,`.output`); `schema.Channel`
(`.field`,`.kind`); `schema.Encoding`(`.x`,`.y`,`.color: Channel|None`); `ingest.NumericColumnSpec`
(`.name`,`.unit: str|None`); `ingest.Manifest.columns`; `canon.Table.columns` each `.name`/`.kind`
∈ {numeric,temporal,string}. Corpus: b11→axis_types (M1.5b), b12→fields_exist (M1.5b), b13→units
(M1.5c; `aqi` is unit-less on purpose). No good spec uses `count` (count is dimensionless → would
trip the unit check), so count-exemption is exercised by DEDICATED `test_checks.py` specs over the
existing CSVs — do NOT add a corpus count golden (it would ripple into M1.4e/M1.4f "10 good specs").

---

## M1.5b — structural encoding checks (fields_exist + axis_types)

ACTIVE checks added: `encoding.fields_exist_in_plotted_table`, `encoding.axis_types_match_fields`.
NARROWING: a field absent from the plotted table is excluded from the axis-type check (and, at
M1.5c, the unit check) → each bad spec fails exactly its own check. Encoding failures run AFTER the
eval gate, so eval SUCCEEDED → `plotted_table` is POPULATED; only `report.passed` is False (the table
reflects the recomputation, M1.6 reads it only when passed). This differs from binding/eval-surface
failures, which return with `plotted_table=None` — the test split must separate the two.

### src deltas (`checks.py`)

1. Import — add `ChannelType`:
   `from verifier.schema import VPlotSpec, _Base` → `from verifier.schema import ChannelType, VPlotSpec, _Base`

2. Module docstring — ACTIVE bullet + control-flow tail. Replace:
   ```
   - ACTIVE: computed here, one pass-or-fail result each. M1.5a: dataset.hash_matches_source.
     (Encoding/label checks join in M1.5b.)
   ```
   with:
   ```
   - ACTIVE: computed here, one pass-or-fail result each — dataset.hash_matches_source (binding)
     plus the structural encoding stage (fields exist, axis types match). The quantitative-unit
     check joins in M1.5c.
   ```
   and replace the control-flow tail:
   ```
   surface + return, no table) -> report carrying the recomputed plotted table. The M1.5b
   encoding stage slots in after the eval gate; until then an encoding-invalid spec may
   still report passed (the documented M1.5a partial state).
   ```
   with:
   ```
   surface + return, no table) -> structural encoding stage over the recomputed table. An
   encoding failure blocks report.passed but leaves plotted_table populated (eval succeeded),
   so M1.6 reads it only when passed. The quantitative-unit check joins this stage in M1.5c;
   until then a unit-missing spec may still report passed (the documented M1.5b partial state).
   ```

3. Add the compat table + `_encoding_checks` immediately BEFORE `# --- entry point`:
   ```python
   # --- encoding / label checks -------------------------------------------------
   # VPlot_SEMANTICS.md section 7: the plotted-column kinds each channel type admits.
   _CHANNEL_COLUMN_COMPAT: dict[ChannelType, frozenset[str]] = {
       "quantitative": frozenset({"numeric"}),
       "temporal": frozenset({"temporal"}),
       "ordinal": frozenset({"numeric", "string"}),
       "nominal": frozenset({"string", "numeric"}),
   }


   def _encoding_checks(spec: VPlotSpec, plotted_table: canon.Table) -> list[CheckResult]:
       """The structural encoding stage over the recomputed plotted table — two checks in a
       narrowing chain so each catches exactly its own failure (a field absent from the table is
       excluded from the later type check, and from the M1.5c unit check). One pass-or-fail each.

       1. encoding.fields_exist_in_plotted_table — every channel field is a plotted column.
       2. encoding.axis_types_match_fields — over existing fields, the column kind admits the
          channel type (section 7).
       """
       channels = [spec.encoding.x, spec.encoding.y]
       if spec.encoding.color is not None:
           channels.append(spec.encoding.color)
       columns = {c.name: c for c in plotted_table.columns}
       results: list[CheckResult] = []

       check = "encoding.fields_exist_in_plotted_table"
       missing = [ch.field for ch in channels if ch.field not in columns]
       results.append(
           _fail(check, f"channel field(s) {missing} absent from plotted columns {sorted(columns)}")
           if missing
           else _pass(check, "every channel field exists in the plotted table")
       )

       check = "encoding.axis_types_match_fields"
       mismatched = [
           f"{ch.field} ({ch.kind} over {columns[ch.field].kind})"
           for ch in channels
           if ch.field in columns and columns[ch.field].kind not in _CHANNEL_COLUMN_COMPAT[ch.kind]
       ]
       results.append(
           _fail(check, f"channel type does not match the plotted-column kind: {mismatched}")
           if mismatched
           else _pass(check, "every channel type matches its plotted-column kind")
       )

       return results
   ```
   (M1.5c re-introduces the `manifest` parameter + the third check — keep the signature
   manifest-free here so M1.5b carries no unused argument.)

4. `verify` — wire the stage. Replace the placeholder line:
   `    # M1.5b: _encoding_checks(spec, plotted, manifest) results extend here.`
   with:
   `    results.extend(_encoding_checks(spec, plotted))`

5. `verify` docstring — replace the M1.5a partial-state paragraph:
   ```
   M1.5a spine: affirmations + binding + eval-surface, returning the recomputed table on
   eval success. Encoding/label checks (M1.5b) are not yet applied, so an
   encoding-invalid spec may still report passed here — closed in M1.5b.
   ```
   with:
   ```
   Pipeline: affirmations + binding gate + eval gate + structural encoding stage. On eval
   success the recomputed table is returned as plotted_table regardless of the encoding
   verdict; a structural encoding failure blocks report.passed but leaves the table populated.
   The quantitative-unit check (M1.5c) is not yet applied, so a unit-missing spec may still
   report passed here — closed in M1.5c.
   ```

### tests (`test_checks.py`) — reframe the corpus split
The M1.5a split is `_BAD_DECODE` | `_A_BAD` (all a-handled bad specs assert `plotted_table is None`).
b11/b12 break that assert (eval succeeds → table populated). Reframe:
- Rename the deferred set: `_ENCODING_CHECKS` → keep only the still-deferred unit check:
  `_DEFERRED_CHECKS = frozenset({"label.quantitative_units_present"})` (b13 only).
- `_PRE_TABLE_BAD = [b for b in _BAD if b["decodes"] and b["check"] not in {"encoding.fields_exist_in_plotted_table","encoding.axis_types_match_fields","label.quantitative_units_present"}]`
  — binding + eval-surface; these assert `plotted_table is None`.
- `_ENCODING_BAD = [b for b in _BAD if b["check"] in {"encoding.fields_exist_in_plotted_table","encoding.axis_types_match_fields"}]`
  — b11/b12; assert `failing == {entry["check"]}`, `not passed`, and `plotted_table is NOT None`.
- Rename `test_a_handled_bad_spec_fails_its_check` → keep it for `_PRE_TABLE_BAD` (table-None assert intact);
  add `test_encoding_bad_spec_fails_its_check` over `_ENCODING_BAD` (table-populated assert).
- `test_no_false_accepts_over_a_handled_bad_specs` → broaden to `_PRE_TABLE_BAD + _ENCODING_BAD`
  (still EXCLUDE b13 — units not checked yet; rename to `_no_false_accepts_excluding_units`).
- `test_a_handled_covers_binding_and_eval_surface` guard → update counts: `_PRE_TABLE_BAD` ≥7,
  `_ENCODING_BAD` == 2 (b11,b12), `_BAD_DECODE` non-empty.
- Good-spec / property / binding / pairing tests are UNCHANGED (the property spec passes checks 1&2:
  x=k nominal-over-string ✓, y=total quantitative-over-numeric ✓, both fields exist ✓; the unit check
  that would fail it does not run until M1.5c).

Coverage (100% branch on `verifier`):
- check1: fail via b12, pass via good specs. check2: fail via b11, pass via good specs.
- color arm: at least one good spec HAS `color` and one does NOT → both `if spec.encoding.color is not None`
  arms hit. (Confirm in `examples/index.json`; if all-or-none, add a tiny constructed-spec test.)
- A NARROWING test (recommended): a single spec whose channel field is absent AND, were it present,
  would also type-mismatch → asserts ONLY fields_exist fails (the absent field is excluded from check2),
  proving the chain. b12 already exercises this if its missing field is the only defect.

### accept (M1.5b)
b11 fails exactly `encoding.axis_types_match_fields`, b12 exactly `encoding.fields_exist_in_plotted_table`,
each with `plotted_table` populated and `not passed`; pre-table bad specs still assert `plotted_table is None`;
good specs pass; false-accept count == 0 over all bad specs EXCEPT b13 (units deferred); gate green at 100% branch.

---

## M1.5c — label-unit check + count-exempt position-aware lineage

ACTIVE check added: `label.quantitative_units_present`. Over quantitative channels on a numeric plotted
column, the lineage source must carry a manifest unit; a count-derived column is exempt (count =
dimensionless). Resolves the VPlot_SEMANTICS.md Open-questions count item.

COUNT-EXEMPTION + lineage rationale (why one-hop and global-scan are both WRONG):
eval admits `count→sum` / `sum→sum` aggregate chains, so the immediate measure's `field` may itself be
a derived column absent from the manifest → the reverse walk must RECURSE. It must also be
POSITION-AWARE: §5 enforces aggregate output-uniqueness PER-AGGREGATE only, and each aggregate REBUILDS
the schema, so an output name MAY recur across separate aggregate ops. A global last-wins scan is then
NON-TERMINATING (`count(x) as v` then `sum(v) as v` cycles v→v) AND UNSOUND (a reused intermediate
mis-resolves to its LATEST producer → false-accept). Keying on (name, POSITION) fixes both: walk
aggregates LATEST-first; the latest aggregate carrying `output==name` is name's surviving producer;
count there → exempt; else recurse on `measure.field` against STRICTLY EARLIER aggregates (the input
references the pre-aggregate schema); no measure matches anywhere → name is a manifest column (select /
group_by key / passthrough). Terminates: the aggregate prefix strictly shrinks (depth ≤ #aggregates ≤ 64).
Direct `numeric_units[source]` (no membership guard) is SAFE: check3 calls `_unit_source` only for a
numeric plotted channel, count short-circuits before any recursion, so every recursion's `name` stays
numeric → a returned manifest column is numeric → in `numeric_units`. (This avoids a dead/uncovered branch.)

### src deltas (`checks.py`)

1. Import — add `Aggregate`:
   `from verifier.schema import ChannelType, VPlotSpec, _Base` → `from verifier.schema import Aggregate, ChannelType, VPlotSpec, _Base`

2. Add `_unit_source` immediately AFTER `_CHANNEL_COLUMN_COMPAT` (before `_encoding_checks`):
   ```python
   def _unit_source(name: str, aggregates: tuple[Aggregate, ...]) -> str | None:
       """The manifest column whose unit a quantitative channel on plotted column `name` requires,
       or None when `name` traces back to a count (dimensionless -> unit-exempt).

       Position-aware reverse lineage over the spec's aggregate ops in pipeline order
       (VPlot_SEMANTICS.md sections 5 + 7). Walk the LATEST aggregate first: the latest one carrying
       a measure with output == name is `name`'s surviving producer, since each aggregate REBUILDS
       the schema (output-uniqueness is per-aggregate, so an output name may recur across aggregates).
       A count producer is dimensionless -> None. Any other producer's value derives from its input
       field, so recurse on that field against STRICTLY EARLIER aggregates (the input references the
       pre-aggregate schema). No measure matches anywhere -> `name` is a manifest column (a select /
       group_by key / passthrough), returned as the unit source.

       Terminates: the aggregate prefix strictly shrinks on each recursion (depth <= number of
       aggregates <= 64). Sound on reused names: a global last-wins scan would mis-resolve a reused
       output to its latest producer (false-accept) or cycle (non-terminating); keying on
       (name, position) resolves each input against the schema that actually produced it. Because the
       caller invokes this only for a numeric plotted channel, and count short-circuits before any
       recursion, every recursion's `name` stays numeric, so a returned manifest column is numeric.
       """
       for i in range(len(aggregates) - 1, -1, -1):
           for measure in aggregates[i].measures:
               if measure.output == name:
                   if measure.fn == "count":
                       return None
                   return _unit_source(measure.field, aggregates[:i])
       return name
   ```

3. `_encoding_checks` — restore the `manifest` parameter + append the third check. Signature:
   `def _encoding_checks(spec: VPlotSpec, plotted_table: canon.Table, manifest: ingest.Manifest) -> list[CheckResult]:`
   Docstring: change "two checks" → "three checks", and add the bullet:
   ```
       3. label.quantitative_units_present — over quantitative channels on a numeric column, the
          lineage source carries a manifest unit; a count-derived column is exempt (section 7).
   ```
   Append BEFORE `return results`:
   ```python
       check = "label.quantitative_units_present"
       aggregates = tuple(t for t in spec.transform if isinstance(t, Aggregate))
       numeric_units = {
           c.name: c.unit for c in manifest.columns if isinstance(c, ingest.NumericColumnSpec)
       }
       unit_failure: str | None = None
       for ch in channels:
           if ch.kind != "quantitative":
               continue
           if ch.field not in columns:
               continue
           if columns[ch.field].kind != "numeric":
               continue
           source = _unit_source(ch.field, aggregates)
           if source is None:
               continue  # count-derived -> dimensionless, unit-exempt
           if numeric_units[source] is None:
               unit_failure = (
                   f"quantitative channel {ch.field!r} traces to manifest column "
                   f"{source!r}, which declares no unit"
               )
               break
       results.append(
           _fail(check, unit_failure)
           if unit_failure is not None
           else _pass(check, "every quantitative channel resolves to a unit or a count")
       )
   ```

4. `verify` — call-site gains `manifest`: `results.extend(_encoding_checks(spec, plotted))` →
   `results.extend(_encoding_checks(spec, plotted, manifest))`.

5. Docstrings — finalize "structural encoding stage" → "encoding/label stage" and drop the
   M1.5b/M1.5c partial-state qualifiers in BOTH the module docstring (ACTIVE bullet: append
   "quantitative units present"; control-flow tail: drop "joins this stage in M1.5c") and the
   `verify` docstring ("+ encoding/label stage"; drop the "unit check (M1.5c) is not yet applied"
   sentence).

### VPlot_SEMANTICS.md ratification
§5 + §7 already carry per-aggregate output-uniqueness + the position-aware lineage (the design fix).
M1.5c removes the "pending" qualifiers and ratifies count-exemption:
- §1 + §7: drop "count-derived carve-out is pending — see Open"; state plainly that a quantitative
  channel tracing to `count` is dimensionless → unit-exempt; all other quantitative channels resolve
  (via position-aware reverse lineage) to a manifest numeric column that MUST declare a `unit`.
- Open: mark the count carve-out item RESOLVED (cite M1.5c).

### tests (`test_checks.py`)
- Remove the `_DEFERRED_CHECKS` exclusion: b13 now caught → `_ENCODING_BAD` includes b13 (assert
  `failing == {"label.quantitative_units_present"}`, `plotted_table` populated). False-accept test →
  full suite, rename to `test_no_false_accepts_over_full_bad_suite`, assert 0.
- Fix `_PROP_MANIFEST`: add `"unit": "units"` to the `v` numeric column — else the property's `total`
  channel (sum of v) traces to unit-less v and check3 fails it. (At M1.5b check3 is off, so this is a
  M1.5c-only fix.)
- `_unit_source` ARM tests (one per branch, all eval-valid — confirm via the pipeline; build specs with
  `decode_spec` over constructed JSON, run `verify` or call `_unit_source` directly):
  1. count-found (return None): `count region as region_count` over sales → unit check PASSES via
     exemption over a UNITLESS source (region is string, no unit; a source-unit-inherit bug would FAIL).
  2. manifest-terminus WITH unit (return name, unit present): g01 `sum revenue as ...` → PASSES.
  3. manifest-terminus WITHOUT unit (return name, unit None): `max aqi as max_aqi` over weather → FAILS.
  4. count-at-depth (recurse then count): chain `count(date) as c` then `sum(c) as cc`, quant on cc →
     EXEMPT via backward lineage (guards one-hop logic).
  5. surviving-producer / FA-guard: `sum(aqi) as v` then `{min(v) as w, count(v) as v}`, quant on w →
     FAILS via w→v(sum)→aqi (unitless); a global last-wins scan false-accepts by binding v to the later count.
  6. NT loop-guard: `count(date) as v` then `sum(v) as v`, quant on v → TERMINATES + EXEMPT (global
     last-wins loops v→v).
  7. group-key passthrough (match at i<last): `group_by[city]→sum(temp_c) as t`, then
     `group_by[t]→count(city) as n`, quant on t → PASSES via t's producing aggregate at an EARLIER index
     (t survives as a group key, not a measure).
  8. multi-measure inner loop: an aggregate with ≥2 measures where the match is the 2nd → exercises the
     inner `for measure` advance.
  9. b13 (aqi direct, non-count, no unit) — the failing control already in `_ENCODING_BAD`.
- Coverage (100% branch): the check3 `continue` guards each need a hit — non-quantitative channel
  (any good spec's x), quantitative-but-field-absent (covered if a narrowing case has a missing quant
  field; else add one), quantitative-but-non-numeric column (a quantitative channel over a string/temporal
  plotted column that EXISTS — but check2 would flag the type; construct a case or confirm the guard is
  reachable, else justify), source-None exempt (case 1/4/6), unit-None fail (case 3/5 + b13), pass-else
  (good specs). Confirm `weather`/`sales` manifest column names (`aqi`,`region`,`temp_c`,`city`,`revenue`,
  `date`) before writing.

### accept (M1.5c)
b13 fails exactly `label.quantitative_units_present` (table populated); a count-derived quant channel
passes over a UNITLESS source AND through a `count→sum` chain; `_unit_source` terminates + stays sound on
the NT and FA adversarial specs; false-accept count == 0 on the FULL bad suite; VPlot_SEMANTICS.md §1/§7/Open
ratify count-exemption; tests cover every encoding failure + each `_unit_source` arm; gate green at 100% branch.
