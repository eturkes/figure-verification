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
from typing import Literal, assert_never

from verifier.pysrc.numeric import NUMERIC_PROFILE
from verifier.pysrc.spec import (
    Bin,
    Const,
    CorePlotSpec,
    DatasetPlot,
    DatasetTarget,
    DeclaredTarget,
    Expr,
    Fn,
    FormulaPlot,
    FormulaTarget,
    Grid,
    Labels,
    Neg,
    Num,
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
_UNUSED_DATA_FILE = "The supplied data file was not read by this chart."
_SPEC_DOMAIN = b"pysrc-spec-0.1\n"


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


def _labels_value(labels: Labels) -> dict[str, object]:
    return {
        "grid": labels.grid,
        "legend": labels.legend,
        "series": labels.series,
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
        return (
            isinstance(target, FormulaTarget)
            and target.y == spec.y
            and (target.grid is None or target.grid == spec.grid)
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


def _interpretation(spec: CorePlotSpec, table: PlottedTable) -> str:
    if isinstance(spec, FormulaPlot):
        text = (
            f"Chart type: {spec.mark}. The data comes from the submitted program. "
            f"Y computes {_expr_text(spec.y)}. X runs from {_expr_text(spec.grid.start)} to "
            f"{_expr_text(spec.grid.stop)} in {spec.grid.samples} samples. Numbers follow the "
            f"profile {NUMERIC_PROFILE}."
        )
        return _append_labels(text, spec.labels)
    if isinstance(spec, DatasetPlot):
        text = (
            f"Chart type: {spec.mark}. The data comes from the file {_quote(spec.source.path)}. "
            f"X shows the column {_quote(spec.x.name)}. Y shows the column {_quote(spec.y.name)}. "
            f"The chart draws {len(table.x)} rows. Numbers follow the profile {NUMERIC_PROFILE}."
        )
        return _append_labels(text, spec.labels)
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def certify(
    spec: CorePlotSpec,
    table: PlottedTable,
    source: bytes,
    target: DeclaredTarget | None,
) -> CoreCertificate:
    """Bind the submitted bytes, projected spec and recomputed table into one statement."""
    consumed = _target_consumed(spec, target)
    provenance: Provenance = "artifact" if consumed else "internal"
    declared_open = [_ARTIFACT_GAP]
    if isinstance(spec, FormulaPlot):
        declared_open.append(_NO_ARTIFACT)
        if not isinstance(target, FormulaTarget):
            declared_open.append(_INTENT_GAP)
        if isinstance(target, DatasetTarget):
            declared_open.append(_UNUSED_DATA_FILE)
    return CoreCertificate(
        version=CERTIFICATE_VERSION,
        source_sha256=_digest(source),
        spec_sha256=_digest(canonical_spec_bytes(spec)),
        table_sha256=_digest(table.canonical_bytes()),
        provenance=provenance,
        artifact_sha256=None,
        numeric_profile=NUMERIC_PROFILE,
        checks=_CHECKS,
        declared_open=tuple(declared_open),
        interpretation=_interpretation(spec, table),
    )
