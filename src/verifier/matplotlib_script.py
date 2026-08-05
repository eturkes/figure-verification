# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Canonical fixed-template matplotlib source from formally prepared formula evidence.

The verifier projects only certified x/y Decimals and resolved x-domain endpoints to binary64.
Each finite projection must HALF_EVEN-round back to its certified Decimal at the declared scale;
projected x must remain strictly increasing. Admitted values use Python's shortest round-tripping
float representation with signed zero canonicalized positive.

Emission is a closed construction: fixed imports select the noninteractive backend before pyplot,
one fixed line/scatter call consumes only projected evidence lists, both axes are explicitly linear,
and fixed x limits consume only admitted endpoint projections. The verifier hashes exact UTF-8
bytes but neither imports matplotlib nor executes the source. Matplotlib, browser execution, and
pixels remain trusted downstream display components.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import cast

from verifier import canon, checks
from verifier.errors import VerificationError
from verifier.formula_prepare import PreparedFormula
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import FormulaMark, FormulaPlotSpec

__all__ = [
    "SCRIPT_TEMPLATE_VERSION",
    "MatplotlibScriptArtifact",
    "MatplotlibScriptRun",
    "emit_matplotlib_script",
]

SCRIPT_TEMPLATE_VERSION = "matplotlib-script-0.1"

_MARK_CALLS: Mapping[FormulaMark, str] = MappingProxyType(
    {
        "line": 'ax.plot(x, y, color="#2563eb", linewidth=2.0)',
        "scatter": 'ax.scatter(x, y, color="#2563eb", s=24.0)',
    }
)
_TEMPLATE = """import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

x = [{x_values}]
y = [{y_values}]
fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
{mark_call}
ax.set_xscale("linear")
ax.set_yscale("linear")
ax.set_xlim({x_start}, {x_stop})
ax.set_xlabel("x")
ax.set_ylabel("y")
ax.grid(True, color="#d1d5db", linewidth=0.8)
fig.tight_layout()
plt.show()
"""


@dataclass(frozen=True, slots=True)
class MatplotlibScriptArtifact:
    """One admitted script bound to its exact formula evidence, results, and digest."""

    spec: FormulaPlotSpec = field(repr=False)
    evidence: checks.FormulaEvidence = field(repr=False)
    results: tuple[checks.CheckResult, ...] = field(repr=False)
    matplotlib_script: bytes = field(repr=False)
    matplotlib_script_hash: str


@dataclass(frozen=True, slots=True)
class MatplotlibScriptRun:
    """Merged report plus an artifact only when every semantic emission check passes."""

    report: checks.VerificationReport
    artifact: MatplotlibScriptArtifact | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Projection:
    x_literals: tuple[str, ...]
    y_literals: tuple[str, ...]
    x_start: str
    x_stop: str


class _Float64FidelityError(ValueError):
    """Internal fail-fast carrier converted to one blocking report result at the public seam."""


def _float_literal(value: Decimal, scale: int, label: str) -> tuple[float, str]:
    projected = float(value)
    if not math.isfinite(projected):
        message = f"{label} projects to non-finite float64"
        raise _Float64FidelityError(message)
    if round(Fraction.from_float(projected), scale) != Fraction(value):
        message = f"{label} does not survive float64 projection at declared scale {scale}"
        raise _Float64FidelityError(message)
    if projected == 0.0:
        projected = 0.0
    return projected, repr(projected)


def _project(prepared: PreparedFormula) -> _Projection:
    source = prepared.evidence.formula_source
    rows = prepared.evidence.plotted_table.rows
    x_literals: list[str] = []
    x_values: list[float] = []
    for index, row in enumerate(rows):
        x = cast("Decimal", row[0])
        projected_x, x_literal = _float_literal(x, source.x_scale, f"row {index} x")
        if x_values and projected_x <= x_values[-1]:
            message = (
                "projected float64 x values are not strictly increasing "
                f"between rows {index - 1} and {index}"
            )
            raise _Float64FidelityError(message)
        x_values.append(projected_x)
        x_literals.append(x_literal)

    start, start_literal = _float_literal(source.start, source.x_scale, "domain start")
    stop, stop_literal = _float_literal(source.stop, source.x_scale, "domain stop")
    if start != x_values[0]:
        message = "projected domain start does not match projected first x value"
        raise _Float64FidelityError(message)
    if stop != x_values[-1]:
        message = "projected domain stop does not match projected last x value"
        raise _Float64FidelityError(message)

    y_literals = tuple(
        _float_literal(cast("Decimal", row[1]), source.y_scale, f"row {index} y")[1]
        for index, row in enumerate(rows)
    )
    return _Projection(
        x_literals=tuple(x_literals),
        y_literals=y_literals,
        x_start=start_literal,
        x_stop=stop_literal,
    )


def _render_script(projection: _Projection, mark: FormulaMark) -> bytes:
    mark_call = _MARK_CALLS[mark]
    return _TEMPLATE.format(
        x_values=", ".join(projection.x_literals),
        y_values=", ".join(projection.y_literals),
        x_start=projection.x_start,
        x_stop=projection.x_stop,
        mark_call=mark_call,
    ).encode("utf-8")


def _success_checks() -> tuple[checks.CheckResult, ...]:
    return (
        checks.make_result(
            "render.float64_fidelity",
            status="pass",
            message=(
                "every plotted value and domain endpoint survives float64 projection at its "
                "declared Decimal scale; projected x remains strictly increasing"
            ),
        ),
        checks.make_result(
            "render.axes_linear",
            status="pass",
            message="the fixed template sets both axes to linear scales",
        ),
        checks.make_result(
            "render.x_domain_exact",
            status="pass",
            message=(
                "the fixed template sets x limits to the float64 projections of the certified "
                "domain endpoints"
            ),
        ),
        checks.make_result(
            "render.points_match_evidence",
            status="pass",
            message=(
                "the fixed template inlines only the validated float64 projections of this "
                "evidence table's x/y points"
            ),
        ),
        checks.make_result(
            "render.matplotlib_script_allowlisted",
            status="pass",
            message=(
                "closed line/scatter dispatch selects a fixed script template; only "
                "verifier-derived finite x/y and domain numeric literals vary"
            ),
        ),
    )


def emit_matplotlib_script(
    prepared: PreparedFormula,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> MatplotlibScriptRun:
    """Project, admit, hash, and bind one canonical matplotlib script without executing it."""
    try:
        projection = _project(prepared)
    except _Float64FidelityError as exc:
        failure = checks.make_result(
            "render.float64_fidelity",
            status="fail",
            message=str(exc),
        )
        report = checks.VerificationReport(results=(*prepared.results, failure))
        return MatplotlibScriptRun(report=report, artifact=None)

    script = _render_script(projection, prepared.spec.mark)
    size = len(script)
    if size > limits.max_matplotlib_script_bytes:
        message = (
            f"matplotlib script has {size} bytes; limit is {limits.max_matplotlib_script_bytes}"
        )
        raise VerificationError(message, check="resource.matplotlib_script_bytes")

    script_hash = canon.hash_matplotlib_script(script)
    results = (*prepared.results, *_success_checks())
    report = checks.VerificationReport(results=results)
    artifact = MatplotlibScriptArtifact(
        spec=prepared.spec,
        evidence=prepared.evidence,
        results=results,
        matplotlib_script=script,
        matplotlib_script_hash=script_hash,
    )
    return MatplotlibScriptRun(report=report, artifact=artifact)
