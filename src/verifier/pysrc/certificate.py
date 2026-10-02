# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The core certificate: what was verified, in hashes and in plain words.

Stdlib-only, so this is NOT `verifier.vcert` -- that one is msgspec and belongs to the shipped
service. Where reuse conflicts with the paste-in's isolation, isolation wins.

Two disciplines the shape enforces. `checks` is all-pass BY CONSTRUCTION, mirroring v0.3's
`Literal["pass"]`: anything the verifier did not establish goes in `declared_open` and never into
`checks` as a failure. `interpretation` publishes the tier-3 gap in plain words; fidelity to what
the user meant is never claimed.
"""

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, assert_never, cast

from verifier.pysrc.errors import PysrcCallerError
from verifier.pysrc.numeric import NUMERIC_PROFILE
from verifier.pysrc.project import same_bound
from verifier.pysrc.spec import (
    Bin,
    Const,
    CorePlotSpec,
    DatasetMark,
    DatasetPlot,
    DatasetTarget,
    DeclaredTarget,
    Expr,
    Fn,
    FormulaPlot,
    FormulaTarget,
    Grid,
    Interval,
    Labels,
    Neg,
    Num,
    Reduction,
    Var,
)
from verifier.pysrc.table import PlottedTable

__all__ = ["CERTIFICATE_VERSION", "CertifiedCheck", "CoreCertificate", "certify"]

CERTIFICATE_VERSION = "pysrc-cert-0.1"

type Provenance = Literal["artifact", "internal"]


@dataclass(frozen=True, slots=True)
class CertifiedCheck:
    """One established property. `status` has one admitted value on purpose."""

    id: str
    status: Literal["pass"]


@dataclass(frozen=True, slots=True)
class CoreCertificate:
    """Field set is exact and pinned. A new field is a claim, so it moves the pin deliberately."""

    version: str
    source_sha256: str
    spec_sha256: str
    table_sha256: str
    # G11: one member count per plotted group, aligned with the table's x, and `None` when the plot
    # is not an aggregate. The interpretation sentence carries the two TOTALS a human reads at a
    # glance; the per-group detail lives here, where a machine consumer can check it row by row.
    group_counts: tuple[int, ...] | None
    provenance: Provenance
    artifact_sha256: str | None
    numeric_profile: str
    checks: tuple[CertifiedCheck, ...]
    declared_open: tuple[str, ...]
    interpretation: str


_CHECKS = tuple(
    CertifiedCheck(check, "pass")
    for check in (
        "prescan",
        "admission",
        "projection",
        "target_binding",
        "recomputation",
        "integrity",
    )
)
_ARTIFACT_GAP = "The emitted image is not compared against this table."
_INTENT_GAP = (
    "The plotted values are the submitted program's own expression, not a target the user stated."
)
_NO_ARTIFACT = (
    "No user artifact was consumed. The plotted values come from the submitted program alone."
)
_SAMPLES_GAP = "The request states no sample count. The submitted program sets it."
_INTERVAL_GAP = (
    "The request states no x interval. "
    "The submitted program sets the interval and the sample count."
)
_SPEC_DOMAIN = b"pysrc-spec-0.1\n"
# Reduction -> the word a person reads. `min`/`max` are abbreviations a reader has to expand;
# `sum` and `mean` are already the English words for what they do.
_REDUCTION_WORDS: dict[Reduction, str] = {
    "sum": "sum",
    "mean": "mean",
    "min": "minimum",
    "max": "maximum",
}

# (first channel's axis, second channel's axis) as RENDERED, per mark.
_AXIS_LETTERS: dict[DatasetMark, tuple[str, str]] = {
    "line": ("X", "Y"),
    "scatter": ("X", "Y"),
    "bar": ("X", "Y"),
    "barh": ("Y", "X"),
}


def _expr_value(expr: Expr) -> list[object]:
    if isinstance(expr, Num):
        return ["num", expr.value.numerator, expr.value.denominator]
    if isinstance(expr, Var):
        return ["var"]
    if isinstance(expr, Const):
        return ["const", expr.name]
    if isinstance(expr, Neg):
        return ["neg", _expr_value(expr.operand)]
    if isinstance(expr, Fn):
        return ["fn", expr.name, _expr_value(expr.arg)]
    if isinstance(expr, Bin):
        return ["bin", expr.op, _expr_value(expr.left), _expr_value(expr.right)]
    assert_never(expr)  # pragma: no cover - `Expr` is a closed union


def _grid_value(grid: Grid) -> dict[str, object]:
    return {
        "samples": grid.samples,
        "start": _expr_value(grid.start),
        "stop": _expr_value(grid.stop),
    }


def _fraction_value(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def _labels_value(labels: Labels) -> dict[str, object]:
    # The cosmetic fields are hashed like every other one. A figure size changes no plotted number,
    # but a spec digest that ignores a projected field is not a binding on that field, and the one
    # thing this digest exists to say is "the spec you read is the spec that was verified".
    figsize = labels.figsize
    return {
        "figsize": None if figsize is None else [_fraction_value(part) for part in figsize],
        "grid": labels.grid,
        "legend": labels.legend,
        "series": labels.series,
        "tick_rotation": (
            None if labels.tick_rotation is None else _fraction_value(labels.tick_rotation)
        ),
        "tight_layout": labels.tight_layout,
        "title": labels.title,
        "xlabel": labels.xlabel,
        "ylabel": labels.ylabel,
    }


def _spec_value(spec: CorePlotSpec) -> dict[str, object]:
    if isinstance(spec, FormulaPlot):
        return {
            "grid": _grid_value(spec.grid),
            "labels": _labels_value(spec.labels),
            "mark": spec.mark,
            "y": _expr_value(spec.y),
        }
    if isinstance(spec, DatasetPlot):
        return {
            "group": spec.group,
            "labels": _labels_value(spec.labels),
            "mark": spec.mark,
            "path": spec.source.path,
            "x": spec.x.name,
            "y": spec.y.name,
        }
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def _json_bytes(value: object) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return encoded.encode("utf-8") + b"\n"


def canonical_spec_bytes(spec: CorePlotSpec) -> bytes:
    """One byte encoding per projected spec, domain- and arm-tagged, stdlib-only."""
    if isinstance(spec, FormulaPlot):
        arm = b"formula\n"
    elif isinstance(spec, DatasetPlot):
        arm = b"dataset\n"
    else:
        assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union
    return _SPEC_DOMAIN + arm + _json_bytes(_spec_value(spec))


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _target_consumed(spec: CorePlotSpec, target: DeclaredTarget | None) -> bool:
    if isinstance(spec, DatasetPlot):
        return isinstance(target, DatasetTarget) and target.path == spec.source.path
    if isinstance(spec, FormulaPlot):
        if not isinstance(target, FormulaTarget) or target.y != spec.y:
            return False
        if target.grid is None:
            return True
        if isinstance(target.grid, Grid) and target.grid.samples != spec.grid.samples:
            return False
        return same_bound(spec.grid.start, target.grid.start) and same_bound(
            spec.grid.stop, target.grid.stop
        )
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _number_text(number: Num) -> str:
    if number.value.denominator == 1:
        return str(number.value.numerator)
    # Projection creates non-integral fractions only from finite source float64 values.
    return repr(float(number.value))


def _expr_text(expr: Expr) -> str:
    if isinstance(expr, Num):
        return _number_text(expr)
    if isinstance(expr, Var):
        return "x"
    if isinstance(expr, Const):
        return expr.name
    if isinstance(expr, Neg):
        return f"-({_expr_text(expr.operand)})"
    if isinstance(expr, Fn):
        return f"{expr.name}({_expr_text(expr.arg)})"
    if isinstance(expr, Bin):
        operators = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "**"}
        return f"({_expr_text(expr.left)} {operators[expr.op]} {_expr_text(expr.right)})"
    assert_never(expr)  # pragma: no cover - `Expr` is a closed union


def _append_labels(text: str, labels: Labels) -> str:
    sentences: list[str] = []
    if labels.xlabel is not None:
        sentences.append(f"X label: {_quote(labels.xlabel)}.")
    if labels.ylabel is not None:
        sentences.append(f"Y label: {_quote(labels.ylabel)}.")
    if labels.title is not None:
        sentences.append(f"Title: {_quote(labels.title)}.")
    return " ".join((text, *sentences))


def _dataset_text(
    spec: DatasetPlot, table: PlottedTable, group_counts: tuple[int, ...] | None
) -> str:
    # `plt.barh` draws its first positional on the VERTICAL axis and its second on the horizontal
    # one, so the axis letters swap with the mark. The sentence is a tier-3 claim about the figure
    # a person is looking at, and naming the wrong axis misdescribes exactly the mark this width
    # added. Closed on `DatasetMark`, never a default, so a fifth mark fails at the lookup.
    first, second = _AXIS_LETTERS[spec.mark]
    source = f"Chart type: {spec.mark}. The data comes from the file {_quote(spec.source.path)}."
    if spec.group is None:
        return (
            f"{source} {first} shows the column {_quote(spec.x.name)}. "
            f"{second} shows the column {_quote(spec.y.name)}. "
            f"The chart draws {len(table.x)} rows. Numbers follow the profile {NUMERIC_PROFILE}."
        )
    # G11's human half: the group count and the row count behind it, in the sentence a person
    # actually reads. Two numbers that disagree are what tells a reader rows went missing.
    # `certify` has already refused a grouped spec whose counts are absent, so the cast is that
    # guard's postcondition rather than a hope.
    counts = cast("tuple[int, ...]", group_counts)
    return (
        f"{source} {first} shows the groups of the column {_quote(spec.x.name)}. "
        f"{second} shows the {_REDUCTION_WORDS[spec.group]} of the column "
        f"{_quote(spec.y.name)} in each group. "
        f"The chart draws {len(table.x)} groups from {sum(counts)} rows. "
        f"Numbers follow the profile {NUMERIC_PROFILE}."
    )


def _interpretation(
    spec: CorePlotSpec,
    table: PlottedTable,
    group_counts: tuple[int, ...] | None,
    target: DeclaredTarget | None,
) -> str:
    if isinstance(spec, FormulaPlot):
        bound = ""
        if isinstance(target, FormulaTarget):
            if isinstance(target.grid, Grid):
                bound = "The formula, the x interval and the sample count match the request. "
            elif isinstance(target.grid, Interval):
                bound = "The formula and the x interval match the request. "
            else:
                bound = "The formula matches the request. "
        text = (
            f"Chart type: {spec.mark}. The data comes from the submitted program. "
            f"{bound}Y computes {_expr_text(spec.y)}. X runs from {_expr_text(spec.grid.start)} to "
            f"{_expr_text(spec.grid.stop)} in {spec.grid.samples} samples. Numbers follow the "
            f"profile {NUMERIC_PROFILE}."
        )
        return _append_labels(text, spec.labels)
    if isinstance(spec, DatasetPlot):
        return _append_labels(_dataset_text(spec, table, group_counts), spec.labels)
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def certify(
    spec: CorePlotSpec,
    table: PlottedTable,
    source: bytes,
    target: DeclaredTarget | None,
    group_counts: tuple[int, ...] | None,
) -> CoreCertificate:
    """Bind the submitted bytes, projected spec and recomputed table into one statement.

    `group_counts` is REQUIRED to agree with the spec: G11 publishes per-group counts beside every
    aggregate, and a branch that reads a grouped spec with absent counts as ungrouped would ship a
    G11-less certificate for an aggregate figure instead of failing. That is a caller defect, not
    an input fault, so it raises rather than refusing.
    """
    grouped = isinstance(spec, DatasetPlot) and spec.group is not None
    if grouped is not (group_counts is not None):
        message = (
            f"group counts disagree with the spec: grouped={grouped}, "
            f"counts={'absent' if group_counts is None else 'present'}"
        )
        raise PysrcCallerError(message)
    consumed = _target_consumed(spec, target)
    provenance: Provenance = "artifact" if consumed else "internal"
    declared_open = [_ARTIFACT_GAP]
    if isinstance(spec, FormulaPlot):
        if not isinstance(target, FormulaTarget):
            declared_open.extend((_INTENT_GAP, _NO_ARTIFACT))
        elif isinstance(target.grid, Interval):
            declared_open.append(_SAMPLES_GAP)
        elif target.grid is None:
            declared_open.append(_INTERVAL_GAP)
    return CoreCertificate(
        version=CERTIFICATE_VERSION,
        source_sha256=_digest(source),
        spec_sha256=_digest(canonical_spec_bytes(spec)),
        table_sha256=_digest(table.canonical_bytes()),
        group_counts=group_counts,
        provenance=provenance,
        artifact_sha256=None,
        numeric_profile=NUMERIC_PROFILE,
        checks=_CHECKS,
        declared_open=tuple(declared_open),
        interpretation=_interpretation(spec, table, group_counts, target),
    )
