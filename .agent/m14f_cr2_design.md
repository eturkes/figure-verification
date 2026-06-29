# M1.4f-cr round 2 — codex-review follow-up recipe (TRANSCRIBE; delete at M1 review)

Pre-derived so the next session TRANSCRIBES + gates, never re-runs codex / re-reads the
4 sources / re-probes DuckDB. Round-1 shipped (`a6e0fb1`); a 2nd `/codex-review` of `a6e0fb1`
raised 3 findings, ALL ACCEPTED (empirically verified this session via a DuckDB probe). The
in-progress edits were reverted because the INVESTIGATION overflowed the window, not the small
application (same failure mode as round-1 → `b958acc`).

Verdict: the oracle's loud-raise behavior is CORRECT for a DECIMAL(38) engine — the bug is
OVERSTATED docstring/ledger claims + one weak boundary test. **Fix = docs + tests only. The
oracle `_coerce_numeric` routing is RIGHT — change NO `tests/oracle.py` code, only its docstrings.**
Rejected codex's alt "make the oracle support eval's unbounded compare" — out of scope for a DuckDB
DECIMAL(38) oracle: a hybrid Python/bignum path is feasible but forfeits the engine independence that
makes this a real cross-check, at more complexity. The loud raise IS the correct guard.

## Verified DuckDB facts — do NOT re-probe (codex-review r2 independently re-derived all of these; the §"new boundary tests" below re-pin the two overflow SITES each gate run, at representative magnitudes — not the exact boundaries)

1. **Two-site aggregate overflow** (magnitude-dependent, both LOUD):
   - DuckDB `SUM` raises `duckdb.OutOfRangeException` when its HUGEINT/INT128 accumulator
     overflows — INT128 max ≈ 1.70e38, so `|sum| > ~1.7e38`.
   - The typed-table REINSERT (coerced result → typed `DECIMAL(38,scale)` table) raises
     `duckdb.ConversionException` when `DECIMAL(38,0)-max (=10**38-1 ≈ 9.99e37) < |sum| <= HUGEINT-max`.
   - So the band `(9.99e37, 1.70e38]` fails at REINSERT (ConversionException); `> 1.70e38` fails
     at SUM (OutOfRangeException). The round-1 ledger/docstrings claim ONLY the reinsert site — FALSE.
   - Sharper (the mean corollary): the oracle's mean = SQL `SUM`+`COUNT` then a PYTHON
     `eval.mean_at_scale` division. So a mean whose RESULT is in-domain STILL raises
     `OutOfRangeException` when its intermediate SUM overflows HUGEINT. (eval's mean never
     materializes the raw sum as a typed value → no divergence on eval's side.)

2. **Scale-38 filter-literal divergence** (LOUD, by the magnitude bound — `_coerce_numeric`):
   `DECIMAL(38,38)` holds only `|x| < 1` (38 fractional, 0 integer digits). `_coerce_numeric`'s
   magnitude bound is `value.is_zero() or value.adjusted() <= _MAX_PRECISION-1-scale` (= `37 - scale`).
   For scale 38 the bound is `adjusted() <= -1`, so even the literal `1` (`adjusted()==0`) raises
   `data.numeric_value` "exceeds DECIMAL(38, scale) magnitude". eval's filter compare is UNBOUNDED
   (`_coerce_filter_value`: int→`Decimal(value)`, str→`_decimal_at_scale`, neither magnitude-bounds),
   so eval keeps rows while the oracle raises. The oracle's filter domain is genuinely NARROWER
   than eval's — never a silent mis-bind. (Same shape on a scale-0 column for any literal with
   `adjusted() >= 38`, e.g. `10**38`.)

## The 3 findings (all ACCEPTED, all honesty/test-scope — no oracle logic bug)

- **F1r2** (MED): round-1 docstrings ("faithful RECOMPUTE for valid specs", "_filter_clause matches
  eval's filter coercion") overstate scope — fact 2 shows a narrower filter domain. Fix: narrow the
  claim in docstrings (oracle module + `_filter_clause`).
- **F2r2** (MED): the SUM-overflow SITE claim is false (fact 1) — both the oracle module docstring,
  the §10 reinsert-path docstring, AND `.agent/memory.md` say ONLY reinsert/ConversionException.
  Fix: state BOTH sites + the in-domain-mean/overflowing-SUM corollary.
- **F3r2** (LOW): the single boundary test `test_oracle_raises_loudly_on_over_domain_filter_literal`
  is weak — discards the eval result, asserts only `pytest.raises(VerificationError)` (any path
  passes), pins neither the site nor the eval-accepts side. Fix: replace with 3 sharper tests that
  pin eval-accepts + the exact oracle exception per site.

## Edits (transcription)

### A. `tests/oracle.py` — DOCSTRINGS ONLY (verify code unchanged: `git diff --stat tests/oracle.py` ⇒ docstring lines only)
Read the module docstring "Scope" paragraph + the `_filter_clause` docstring. Replace their false
single-site / full-match claims with prose conveying EXACTLY facts 1 & 2 above. Required content:
- Module "Scope" para: oracle = faithful RECOMPUTE for valid specs WHOSE VALUES STAY IN DuckDB's
  DECIMAL(38)/HUGEINT domain; it raises LOUDLY (never silently diverges) on two eval-accepted edges —
  (1) a filter literal outside the column's `DECIMAL(38,scale)` domain (a huge value, OR the literal
  `1` on a scale-38 column where `|x|<1` only), via the coercer's magnitude bound; (2) an aggregate
  whose total leaves the domain, at EITHER the DuckDB `SUM` (`OutOfRangeException`, HUGEINT overflow,
  `|sum|>~1.7e38`) OR the typed reinsert (`ConversionException`, `DECIMAL(38,0)<|sum|<=HUGEINT`) — and
  because mean is SQL `SUM`+`COUNT` then a Python division, an in-domain mean RESULT still raises when
  its intermediate SUM overflows.
- `_filter_clause` docstring: the numeric branch coerces via `_coerce_numeric` so it compares
  IDENTICALLY to eval's filter literal FOR IN-DOMAIN VALUES (eval's Decimal compare is unbounded;
  this oracle's is DECIMAL(38)-scoped); a literal outside the column's `DECIMAL(38,scale)` domain
  (huge, OR `1` on a scale-38 column) raises LOUDLY here via the coercer's magnitude bound — the
  oracle's filter domain is genuinely narrower than eval's, never a silent mis-bind (pinned by the
  new boundary tests).
- Also fix the §10 SUM-path docstring if it asserts the single reinsert site → both sites.

### B. `tests/test_oracle_parity.py` — replace the 1 weak boundary test with 3 sharp ones
Imports: add `from decimal import Decimal` (stdlib block, after `pathlib`) and `import duckdb`
(third-party block, before `msgspec`).

Module-level constants (place near the existing `_NUM2`; the scale-0 aggregate/filter cases reuse the
existing `_NUM` manifest):
```python
# scale-38 numeric: DECIMAL(38,38) holds only |x| < 1, so even the literal 1 is out of domain.
_S38 = b'{"dataset":"t.csv","columns":[{"name":"v","type":"numeric","scale":38,"label":"V"}]}'
# Over-domain aggregate fixtures (scale 0): sums that leave DuckDB's DECIMAL(38,0)/HUGEINT domain.
_SUM_OVER_HUGEINT = b"v\n" + b"9" * 38 + b"\n" + b"9" * 38 + b"\n"   # 2*(10**38-1) ~2e38 > HUGEINT
_SUM_OVER_DECIMAL38 = b"v\n" + (b"5" + b"0" * 37 + b"\n") * 3        # 1.5e38: fits HUGEINT, > DEC(38,0)
```
Build each spec with the file's EXISTING helpers: `_spec_manifest(manifest_json, csv, transform)`
(decodes spec + manifest; encoding is recompute-irrelevant) where `transform` =
`_flt(field, cmp, value)` for a filter or `_grp_agg(keys, measures)` for an aggregate (`measures` =
`[(field, fn, "as"), ...]`, `keys=[]` → whole-table). `evaluate` (`verifier.eval`), `recompute`
(`oracle`'s ONLY export), and `VerificationError` (`verifier.errors`) are ALREADY imported; the new
tests assert on `.rows` / `pytest.raises` and need NO serialization. Three tests:

1. `test_oracle_raises_loudly_on_over_domain_filter_literal` — `pytest.mark.parametrize` ids
   `huge_literal_scale0` / `small_literal_scale38`:
   - `huge_literal_scale0`: `_NUM` (scale-0) manifest + csv `b"v\n1\n2\n"`, transform
     `_flt("v", "lt", "1e38")`. The literal MUST be the STRING `"1e38"`, NOT int `10**38` — msgspec
     caps a JSON filter int at int64, so `{"value": 10**38}` fails at DECODE (`ValidationError`), never
     reaching the oracle bound. `Decimal("1e38").adjusted()==38 > 37` → the scale-0 magnitude bound
     raises; eval's str filter path is unbounded → keeps both rows. eval ACCEPTS:
     `assert len(evaluate(spec, manifest, csv).rows) == 2`. Oracle RAISES:
     `with pytest.raises(VerificationError, match="exceeds DECIMAL"): recompute(spec, manifest, csv)`.
   - `small_literal_scale38`: `_S38` manifest + csv `b"v\n0.5\n0.9\n"`, transform `_flt("v", "lt", 1)`
     (int `1` is fine — within int64). eval keeps both rows (`len(...rows) == 2`); oracle raises (same
     `match="exceeds DECIMAL"`).

2. `test_oracle_raises_loudly_on_over_domain_aggregate` — parametrize ids
   `over_hugeint_at_sum` / `over_decimal38_at_reinsert`, tuple `(csv, eval_sum, exc)`:
   - `(_SUM_OVER_HUGEINT, 2 * (10**38 - 1), duckdb.OutOfRangeException)`
   - `(_SUM_OVER_DECIMAL38, 3 * (5 * 10**37), duckdb.ConversionException)`
   Transform = `_grp_agg([], [("v", "sum", "s")])` (whole-table), `_NUM` (scale-0) manifest. eval ACCEPTS:
   `assert evaluate(spec, manifest, csv).rows == ((Decimal(eval_sum),),)`. Oracle RAISES at its site:
   `with pytest.raises(exc): recompute(spec, manifest, csv)`.

3. `test_oracle_mean_diverges_when_intermediate_sum_overflows` — `csv = _SUM_OVER_HUGEINT`, `_NUM`
   (scale-0) manifest, transform `_grp_agg([], [("v", "mean", "m")])`. eval's mean RESULT is in-domain:
   `assert evaluate(spec, manifest, csv).rows == ((Decimal(10**38 - 1),),)`. Oracle still raises on
   the intermediate SUM: `with pytest.raises(duckdb.OutOfRangeException): recompute(spec, manifest, csv)`.

E501 guard (line length 100): the named constants above keep the parametrize tuples short — do NOT
inline the long CSV expressions. Run `ruff format` (write) before the gate to settle wrapping.

### C. `.agent/memory.md` — correct the false SUM-site claim (M1.4f codex-review entry)
The entry says the §10 SUM-overflow raise fires ONLY at the typed-table REINSERT
(`ConversionException`), not at `SUM`. Replace with the TWO-SITE fact (fact 1): `SUM` raises
`OutOfRangeException` when HUGEINT overflows (`|sum|>~1.7e38`); the reinsert raises
`ConversionException` for `DEC(38,0)<|sum|<=HUGEINT`; a mean with an in-domain result still raises on
the intermediate SUM. (The float64-error-reporting note there is unrelated + CONFIRMED — leave it.)

NOTE: the roadmap's M1.4f-cr callout F3 line was ALREADY corrected to two-site in the re-plan commit
that created this recipe — do NOT re-edit it; only `memory.md` remains.

## Gate + close
```
export UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy
uv run --locked ruff format --check . && uv run --locked ruff check . \
  && uv run --locked mypy && uv run --locked pytest    # 100% branch; oracle.py outside coverage source
```
Then: record this unit's ctx; flip M1.4f-cr round-2 → DONE in the roadmap; `rm .agent/m14f_cr2_design.md`
deferred to M1 review (with the other design docs). Commit keeping the `(M1.4f)` key + a
`Codex-Review:` trailer naming the 3 accepted findings, e.g.:
```
oracle (M1.4f): codex-review r2 — two-site overflow + filter-domain honesty, sharper boundary tests

Codex-Review: F1r2 narrow filter-domain claim; F2r2 both overflow sites (SUM OutOfRange + reinsert Conversion) + mean corollary; F3r2 replace weak boundary test with 3 site-pinning tests
```
