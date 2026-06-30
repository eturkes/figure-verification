# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Verification spine — recompute the plotted data and emit a structured verdict.

The untrusted model proposes only a VPlotSpec. verify() resolves the bound CSV under a
trusted data directory, recomputes every plotted value from the declared transforms
(verifier.eval), and reports per-check pass/fail results; M1.6 renders a spec only when
report.passed. This is the M1.5 trust gate — meaning lives in VPlot_SEMANTICS.md.

Check provenance — four deliberately distinct classes:
- ACTIVE: computed here, one pass-or-fail result each — dataset.hash_matches_source (binding)
  plus the encoding/label stage (fields exist, axis types match, quantitative units present).
- SURFACED: any VerificationError evaluate() raises — eval's semantic checks and,
  transitively (eval calls ingest.load_table), ingest's data.* checks — is wrapped as a
  fail under its own .check name. Check-agnostic: no eval-pass is enumerated here.
- AFFIRMED: true by construction (the trust argument), emitted as constant passes —
  security.no_arbitrary_code, transform.ops_allowed, transform.filters_declared,
  transform.aggregates_match_recomputation.
- M1.6 renderer: enforced-by-construction at render time (bar baseline, legend domain),
  not in this module.

Control flow (short-circuit gates): pairing precondition (caller bug -> ValueError) ->
affirmations -> dataset-binding gate (fail -> return, no table) -> eval gate (raise ->
surface + return, no table) -> encoding/label stage over the recomputed table. An
encoding failure blocks report.passed but leaves plotted_table populated (eval succeeded),
so M1.6 reads it only when passed.
"""

from pathlib import Path
from typing import Literal

from verifier import canon, ingest
from verifier.errors import VerificationError
from verifier.eval import evaluate
from verifier.schema import Aggregate, ChannelType, VPlotSpec, _Base


# --- structured verdict ------------------------------------------------------
class CheckResult(_Base, frozen=True, kw_only=True):
    """One blocking check's verdict. `check` is the dotted name; `severity` is a single
    reserved value (advisory tiers are future work), so `passed` consults `status` only."""

    check: str
    status: Literal["pass", "fail"]
    severity: Literal["blocking"]
    message: str


class VerificationReport(_Base, frozen=True, kw_only=True):
    """The full verdict for one spec. `plotted_table` is the verifier-recomputed table on
    eval success, else None; M1.6 reads it only when `passed`."""

    results: tuple[CheckResult, ...]
    plotted_table: canon.Table | None

    @property
    def passed(self) -> bool:
        """Every check passed -> the spec may render. Blocking is the only severity."""
        return all(r.status == "pass" for r in self.results)


def _pass(check: str, message: str) -> CheckResult:
    return CheckResult(check=check, status="pass", severity="blocking", message=message)


def _fail(check: str, message: str) -> CheckResult:
    return CheckResult(check=check, status="fail", severity="blocking", message=message)


# --- affirmations (true by construction; the documented trust argument) ------
def _affirmations() -> list[CheckResult]:
    """Properties the architecture guarantees by construction, surfaced as passes so the
    report records the whole trust argument, not only the computed checks."""
    return [
        _pass(
            "security.no_arbitrary_code",
            "spec is pure data (frozen msgspec structs, no expr/script/url field), "
            "so it carries no executable path",
        ),
        _pass(
            "transform.ops_allowed",
            "transforms are a closed tagged union (select/filter/group_by/aggregate/sort); "
            "any other op is rejected at decode",
        ),
        _pass(
            "transform.filters_declared",
            "the verifier recomputes from the declared transform pipeline alone, "
            "so every applied filter is a declared filter op",
        ),
        _pass(
            "transform.aggregates_match_recomputation",
            "the model proposes no values; verify recomputes the table and returns it as "
            "plotted_table, so no model aggregate exists to diverge — M1.6 must inline this",
        ),
    ]


# --- dataset binding ---------------------------------------------------------
def _check_dataset_binding(spec: VPlotSpec, data_dir: Path) -> tuple[CheckResult, bytes | None]:
    """Resolve the spec's CSV under data_dir and verify its bytes hash to the declared
    dataset.hash. Returns (pass, source bytes) on success, (fail, None) otherwise.

    Path confinement (VPlot_SEMANTICS.md section 8): resolve() + is_relative_to(root) is
    the authoritative guard, rejecting any absolute, '..'-traversal, or symlink target that
    resolves outside data_dir regardless of how the spec was built (pathlib discards root on
    an absolute join). A decoded DatasetName also forbids '/' and CR/LF (defense in depth),
    so a model-proposed traversal name cannot even decode. data_dir is trusted operator
    config, so a concurrent resolve->read swap (TOCTOU) is out of scope; the read is on the
    already-resolved real path.
    """
    check = "dataset.hash_matches_source"
    name = spec.dataset.name
    root = data_dir.resolve()
    source = (root / name).resolve()
    if not source.is_relative_to(root):
        return _fail(check, f"dataset {name!r} resolves outside the data directory"), None
    try:
        raw = source.read_bytes()
    except OSError:
        return _fail(check, f"dataset {name!r} could not be read under the data directory"), None
    actual = canon.hash_dataset(raw)
    if actual != spec.dataset.hash:
        return _fail(check, f"declared {spec.dataset.hash} != source {actual}"), None
    return _pass(check, f"source bytes hash to the declared {spec.dataset.hash}"), raw


# --- encoding / label checks -------------------------------------------------
# VPlot_SEMANTICS.md section 7: the plotted-column kinds each channel type admits.
_CHANNEL_COLUMN_COMPAT: dict[ChannelType, frozenset[str]] = {
    "quantitative": frozenset({"numeric"}),
    "temporal": frozenset({"temporal"}),
    "ordinal": frozenset({"numeric", "string"}),
    "nominal": frozenset({"string", "numeric"}),
}


def unit_source(name: str, aggregates: tuple[Aggregate, ...]) -> str | None:
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
                return unit_source(measure.field, aggregates[:i])
    return name


def _encoding_checks(
    spec: VPlotSpec, plotted_table: canon.Table, manifest: ingest.Manifest
) -> list[CheckResult]:
    """The encoding/label stage over the recomputed plotted table — three checks in a
    narrowing chain so each catches exactly its own failure (a field absent from the table is
    excluded from the later type and unit checks). One pass-or-fail each.

    1. encoding.fields_exist_in_plotted_table — every channel field is a plotted column.
    2. encoding.axis_types_match_fields — over existing fields, the column kind admits the
       channel type (section 7).
    3. label.quantitative_units_present — over quantitative channels on a numeric column, the
       lineage source carries a manifest unit; a count-derived column is exempt (section 7).
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
        else _pass(check, "every present channel field's type matches its plotted-column kind")
    )

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
        source = unit_source(ch.field, aggregates)
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

    return results


# --- entry point -------------------------------------------------------------
def verify(spec: VPlotSpec, manifest: ingest.Manifest, *, data_dir: Path) -> VerificationReport:
    """Verify a decoded spec against its trusted manifest and data directory.

    `spec` is untrusted (model-proposed); `manifest` is caller-resolved trusted config;
    `data_dir` roots the CSV resolution. The manifest must pair with the spec's dataset —
    a mismatch is a caller bug (ValueError), not a verification outcome.

    Pipeline: affirmations + binding gate + eval gate + encoding/label stage. On eval
    success the recomputed table is returned as plotted_table regardless of the encoding
    verdict; an encoding/label failure blocks report.passed but leaves the table populated.
    """
    if manifest.dataset != spec.dataset.name:
        msg = f"manifest binds {manifest.dataset!r} but spec binds {spec.dataset.name!r}"
        raise ValueError(msg)
    results = _affirmations()
    binding, raw = _check_dataset_binding(spec, data_dir)
    results.append(binding)
    if raw is None:  # raw is None exactly when binding failed -> block, no table
        return VerificationReport(results=tuple(results), plotted_table=None)
    try:
        plotted = evaluate(spec, manifest, raw)
    except VerificationError as exc:  # eval semantic or (transitively) ingest data.* failure
        results.append(_fail(exc.check, str(exc)))
        return VerificationReport(results=tuple(results), plotted_table=None)
    results.extend(_encoding_checks(spec, plotted, manifest))
    return VerificationReport(results=tuple(results), plotted_table=plotted)
