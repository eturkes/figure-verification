# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Verification spine — recompute plotted data, retain bounded evidence, emit a verdict.

The untrusted model proposes only a VPlotSpec. ``verify_run`` admits the exact trusted
manifest bytes, bounded-reads the bound CSV under ``data_dir``, recomputes every plotted
value from the declared transforms (verifier.eval), and returns three deliberately split
views: a public results-only ``VerificationReport``; an internal ``VerificationTrace`` of
successfully admitted raw inputs; and ``RecomputedEvidence`` only after every check passes.
``verify`` is the public report-only projection. This is the trust gate — meaning lives in
VPlot_SEMANTICS.md.

Check provenance — four deliberately distinct classes:
- ACTIVE: computed here, one pass-or-fail result each — dataset.hash_matches_source (binding)
  plus the encoding/label stage (fields exist, axis types match, quantitative units present).
- SURFACED: any VerificationError from manifest admission/evaluate plus the plotted-cell
  ceiling is wrapped as a fail under its own .check name. Check-agnostic: no eval-pass is
  enumerated here.
- AFFIRMED: true by construction (the trust argument), emitted as constant passes —
  security.no_arbitrary_code, transform.ops_allowed, transform.filters_declared,
  transform.aggregates_match_recomputation.
- M1.6 renderer: enforced-by-construction at render time (bar baseline, legend domain),
  not in this module.

Control flow (short-circuit gates): manifest byte/shape policy -> pairing precondition
(caller bug -> ValueError) -> affirmations -> dataset-binding/read gate -> eval gate ->
plotted-cell gate -> encoding/label stage. Every failure returns immediately with no
evidence; a successfully admitted input remains in the trace even when a later hash or
semantic gate fails. Hashes and recomputed data cross the renderer boundary only through
``RecomputedEvidence``.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, cast

from verifier import canon, ingest
from verifier.errors import VerificationError
from verifier.eval import EvaluationError, evaluate_run
from verifier.limits import DEFAULT_LIMITS, VerificationLimits, read_bounded
from verifier.schema import Aggregate, ChannelType, VPlotSpec, _Base

# --- structured verdict ------------------------------------------------------
CheckMethod = Literal[
    "schema_validation",
    "resource_policy",
    "deterministic_recompute",
    "construction",
    "z3_smt",
]


class CheckResult(_Base, frozen=True, kw_only=True):
    """One blocking check's verdict and the method that established it.

    ``method`` is closed and orthogonal to the dotted ``check`` family: evaluator failures named
    ``schema.*`` still arise from deterministic recomputation, while ``spec.decode`` is schema
    validation. ``severity`` has one reserved value (advisory tiers are future work), so
    :attr:`VerificationReport.passed` consults ``status`` only.
    """

    check: str
    method: CheckMethod
    status: Literal["pass", "fail"]
    severity: Literal["blocking"]
    message: str


# Exact registry = one internal source of method provenance. Dynamic VerificationError tags are
# admitted only through this table: a new check must make its method choice explicit before it can
# become a public result. ``z3_smt`` is already in CheckMethod for M5.2b, but has no result ID yet.
_CHECK_METHODS: dict[str, CheckMethod] = {
    # Service-only schema prerequisites.
    "spec.decode": "schema_validation",
    "dataset.manifest_available": "schema_validation",
    # Logical resource ceilings across core verification and rendering.
    "resource.file_bytes": "resource_policy",
    "resource.manifest_columns": "resource_policy",
    "resource.source_rows": "resource_policy",
    "resource.source_cells": "resource_policy",
    "resource.eval_work": "resource_policy",
    "resource.plotted_cells": "resource_policy",
    "resource.render_rows": "resource_policy",
    "resource.vega_bytes": "resource_policy",
    "resource.attestation_bytes": "resource_policy",
    "resource.svg_bytes": "resource_policy",
    "resource.html_bytes": "resource_policy",
    # Active binding, data-integrity, evaluator, encoding, and label checks.
    "dataset.hash_matches_source": "deterministic_recompute",
    "data.charset": "deterministic_recompute",
    "data.csv_syntax": "deterministic_recompute",
    "data.header": "deterministic_recompute",
    "data.row_width": "deterministic_recompute",
    "data.numeric_value": "deterministic_recompute",
    "data.temporal_value": "deterministic_recompute",
    "transform.group_by_placement": "deterministic_recompute",
    "group_by.keys_distinct": "deterministic_recompute",
    "select.fields_distinct": "deterministic_recompute",
    "schema.fields_exist": "deterministic_recompute",
    "filter.value_type": "deterministic_recompute",
    "sort.fields_distinct": "deterministic_recompute",
    "aggregate.output_unique": "deterministic_recompute",
    "schema.field_types_match": "deterministic_recompute",
    "sort.field_in_plotted_table": "deterministic_recompute",
    "encoding.fields_exist_in_plotted_table": "deterministic_recompute",
    "encoding.axis_types_match_fields": "deterministic_recompute",
    "label.quantitative_units_present": "deterministic_recompute",
    # Constant trust-spine affirmations whose truth follows from the architecture.
    "security.no_arbitrary_code": "construction",
    "transform.ops_allowed": "construction",
    "transform.filters_declared": "construction",
    "transform.aggregates_match_recomputation": "construction",
}


def make_result(check: str, *, status: Literal["pass", "fail"], message: str) -> CheckResult:
    """Build one internally emitted result from the exact check/method registry.

    Unknown IDs are implementation drift, not an extensibility hook: fail before serializing a
    result whose provenance method was never chosen.
    """
    try:
        method = _CHECK_METHODS[check]
    except KeyError:
        msg = f"check {check!r} has no registered verification method"
        raise ValueError(msg) from None
    return CheckResult(
        check=check,
        method=method,
        status=status,
        severity="blocking",
        message=message,
    )


class VerificationReport(_Base, frozen=True, kw_only=True):
    """Public verdict for one spec. Internal inputs/recomputation never serialize here."""

    results: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        """Every check passed -> the spec may render. Blocking is the only severity."""
        return all(r.status == "pass" for r in self.results)


@dataclass(frozen=True, slots=True)
class VerificationTrace:
    """Successfully admitted inputs/work, retained incrementally for local audit only.

    ``None`` means that input never crossed its byte/read gate. Raw bytes stay out of reprs
    because source/manifest content may be sensitive. ``eval_work_units`` is the cumulative
    deterministic admission charge before evaluator success/failure; the service never serializes
    this type.
    """

    manifest_bytes: bytes | None = field(repr=False)
    source_bytes: bytes | None = field(repr=False)
    eval_work_units: int = 0


@dataclass(frozen=True, slots=True)
class RecomputedEvidence:
    """A check-passed recomputation eligible for later builder/formal gates.

    This is evidence of core verification only: it is not a rendered or certified artifact.
    Exact bytes, their canonical hashes, the decoded manifest, table, and passed results travel
    together so downstream code cannot silently rebind one component to mutable live files.
    """

    manifest: ingest.Manifest = field(repr=False)
    manifest_bytes: bytes = field(repr=False)
    source_bytes: bytes = field(repr=False)
    dataset_hash: str
    manifest_hash: str
    spec_hash: str
    plotted_table: canon.Table = field(repr=False)
    plotted_table_hash: str
    results: tuple[CheckResult, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class VerificationRun:
    """Internal verification result: public report + incremental trace + optional evidence."""

    report: VerificationReport
    trace: VerificationTrace
    evidence: RecomputedEvidence | None = field(repr=False)


def _pass(check: str, message: str) -> CheckResult:
    return make_result(check, status="pass", message=message)


def _fail(check: str, message: str) -> CheckResult:
    return make_result(check, status="fail", message=message)


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
            "the model proposes no values; verify recomputes the table into internal evidence, "
            "so no model aggregate exists to diverge — the renderer must inline this evidence",
        ),
    ]


# --- dataset binding ---------------------------------------------------------
def _check_dataset_binding(
    spec: VPlotSpec, data_dir: Path, limits: VerificationLimits
) -> tuple[CheckResult, bytes | None, str | None]:
    """Resolve the spec's CSV under data_dir and verify its bytes hash to the declared
    dataset.hash. Returns the exact bounded source bytes after any successful read, including
    a hash mismatch, so the caller can retain them in ``VerificationTrace``. Confinement or
    genuine absence returns no bytes; an over-limit read surfaces its own ``resource.*`` tag;
    any other filesystem fault is broken trusted config and propagates.

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
        result = _fail(check, f"dataset {name!r} resolves outside the data directory")
        return result, None, None
    try:
        raw = read_bounded(source, limits.max_csv_bytes)
    except VerificationError as exc:
        return _fail(exc.check, str(exc)), None, None
    except FileNotFoundError:
        result = _fail(check, f"dataset {name!r} could not be read under the data directory")
        return result, None, None
    actual = canon.hash_dataset(raw)
    if actual != spec.dataset.hash:
        result = _fail(check, f"declared {spec.dataset.hash} != source {actual}")
        return result, raw, actual
    result = _pass(check, f"source bytes hash to the declared {spec.dataset.hash}")
    return result, raw, actual


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


# --- entry points ------------------------------------------------------------
def _failed_run(results: list[CheckResult], trace: VerificationTrace) -> VerificationRun:
    """Freeze one short-circuited failure; failed runs never carry recomputed evidence."""
    report = VerificationReport(results=tuple(results))
    return VerificationRun(report=report, trace=trace, evidence=None)


def _admit_manifest(
    manifest_bytes: bytes, limits: VerificationLimits
) -> ingest.Manifest | VerificationRun:
    """Byte-admit + decode a manifest, or return its structured resource failure."""
    empty_trace = VerificationTrace(manifest_bytes=None, source_bytes=None)
    if len(manifest_bytes) > limits.max_manifest_bytes:
        message = f"file exceeds byte limit of {limits.max_manifest_bytes}"
        return _failed_run([_fail("resource.file_bytes", message)], empty_trace)

    trace = VerificationTrace(manifest_bytes=manifest_bytes, source_bytes=None)
    try:
        return ingest.load_manifest(manifest_bytes, limits=limits)
    except VerificationError as exc:
        return _failed_run([_fail(exc.check, str(exc))], trace)


def verify_run(
    spec: VPlotSpec,
    manifest_bytes: bytes,
    *,
    data_dir: Path,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> VerificationRun:
    """Verify a decoded spec and retain bounded internal trace/evidence.

    ``manifest_bytes`` is the trusted caller's exact manifest snapshot. Its size is admitted
    before decode; filesystem callers use ``read_bounded`` before invoking this entry (the
    service adapter is wired in M5.1d). ``data_dir`` roots the independently bounded CSV read.
    A trusted manifest parse/mispair fault remains an exception; resource, binding, data, eval,
    plotted-size, and encoding failures become structured reports under their own check tags.

    Inputs enter ``VerificationTrace`` only after their byte/read gate succeeds; evaluator work is
    retained after its attempt, including a structured failure. Evidence is minted only after every
    gate passes and carries all four current canonical hashes alongside the exact snapshots and
    recomputation. It means eligible for later builder/formal checks, never already rendered or
    certified.
    """
    admitted = _admit_manifest(manifest_bytes, limits)
    if isinstance(admitted, VerificationRun):
        return admitted
    manifest = admitted
    trace = VerificationTrace(manifest_bytes=manifest_bytes, source_bytes=None)
    if manifest.dataset != spec.dataset.name:
        msg = f"manifest binds {manifest.dataset!r} but spec binds {spec.dataset.name!r}"
        raise ValueError(msg)

    results = _affirmations()
    binding, raw, dataset_hash = _check_dataset_binding(spec, data_dir, limits)
    results.append(binding)
    trace = VerificationTrace(manifest_bytes=manifest_bytes, source_bytes=raw)
    if binding.status == "fail":
        return _failed_run(results, trace)

    # A passing binding result is constructed only with admitted raw bytes + its exact hash.
    source_bytes = cast("bytes", raw)
    admitted_dataset_hash = cast("str", dataset_hash)
    try:
        evaluated = evaluate_run(spec, manifest, source_bytes, limits=limits)
    except EvaluationError as exc:
        trace = replace(trace, eval_work_units=exc.work_units)
        results.append(_fail(exc.check, str(exc)))
        return _failed_run(results, trace)
    plotted = evaluated.table
    trace = replace(trace, eval_work_units=evaluated.work_units)

    plotted_cells = len(plotted.columns) * len(plotted.rows)
    if plotted_cells > limits.max_plotted_cells:
        message = f"plotted table has {plotted_cells} cells; limit is {limits.max_plotted_cells}"
        results.append(_fail("resource.plotted_cells", message))
        return _failed_run(results, trace)

    results.extend(_encoding_checks(spec, plotted, manifest))
    report = VerificationReport(results=tuple(results))
    if not report.passed:
        return VerificationRun(report=report, trace=trace, evidence=None)

    evidence = RecomputedEvidence(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        source_bytes=source_bytes,
        dataset_hash=admitted_dataset_hash,
        manifest_hash=canon.hash_manifest(manifest_bytes),
        spec_hash=canon.hash_spec(spec),
        plotted_table=plotted,
        plotted_table_hash=canon.hash_table(plotted),
        results=report.results,
    )
    return VerificationRun(report=report, trace=trace, evidence=evidence)


def verify(
    spec: VPlotSpec,
    manifest_bytes: bytes,
    *,
    data_dir: Path,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> VerificationReport:
    """Public results-only projection of :func:`verify_run`; raw trace/evidence stay internal."""
    return verify_run(spec, manifest_bytes, data_dir=data_dir, limits=limits).report
