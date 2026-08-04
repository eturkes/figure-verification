# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Evidence-bound formula preparation and the bounded nondecreasing-x formal gate.

``prepare_formula`` accepts only a decoded ``FormulaPlotSpec`` paired with passing
``FormulaEvidence`` from core verification. It rebinds the pair by canonical spec hash, applies the
render-row ceiling before fact construction, and delegates the SMT-term/context gate to
``formal.verify_formal``. Formula facts contain one exact ascending x rank per row; equality is not
an inversion, so SMT establishes nondecreasing order only. Evaluator-owned
``formula.sample_points_strictly_increasing`` remains the strict sampled-domain authority.

The merged report preserves core results before formal results. ``PreparedFormula`` exists only
when every result passes; later script emission must consume this concrete spec/evidence pair.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import cast

from verifier import canon, checks, formal
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import FormulaPlotSpec


@dataclass(frozen=True, slots=True)
class PreparedFormula:
    """Core- and formal-passed formula inputs for later deterministic script emission."""

    spec: FormulaPlotSpec = field(repr=False)
    evidence: checks.FormulaEvidence = field(repr=False)
    results: tuple[checks.CheckResult, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class FormulaPreparationRun:
    """Merged report, bounded solver trace, and optional all-pass prepared formula."""

    report: checks.VerificationReport
    formal_trace: tuple[formal.FormalTrace, ...]
    prepared: PreparedFormula | None = field(repr=False)


def formula_row_order_facts(evidence: checks.FormulaEvidence) -> formal.RowOrderFacts:
    """Project each evaluator-produced x value onto one exact ascending rank."""
    return formal.RowOrderFacts(
        rows=tuple(
            (
                formal.RankedCell(
                    is_null=False,
                    rank=Fraction(cast("Decimal", x)),
                ),
            )
            for x, _y in evidence.plotted_table.rows
        ),
        directions=("ascending",),
    )


def _formula_formal_result(result: checks.CheckResult) -> checks.CheckResult:
    """Translate the shared row-order result to this seam's exact x-only obligation."""
    if result.check != "sort.canonical_order":
        return result
    if result.status == "pass":
        message = "sampled x values are nondecreasing in ascending order"
    else:
        message = result.message.replace(
            "canonical row order is violated",
            "sampled x values descend",
            1,
        )
    return checks.make_result(result.check, status=result.status, message=message)


def prepare_formula(
    spec: FormulaPlotSpec,
    evidence: checks.FormulaEvidence,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> FormulaPreparationRun:
    """Bind, resource-admit, and formally prepare one passing formula recomputation."""
    spec_hash = canon.hash_spec(spec)
    if spec_hash != evidence.spec_hash:
        message = f"spec hash {spec_hash} does not match evidence {evidence.spec_hash}"
        raise ValueError(message)

    row_count = len(evidence.plotted_table.rows)
    if row_count > limits.max_render_rows:
        message = f"plotted table has {row_count} render rows; limit is {limits.max_render_rows}"
        raise VerificationError(message, check="resource.render_rows")

    formal_run = formal.verify_formal(
        formal.FormalFacts(
            row_order=formula_row_order_facts(evidence),
            bar_zero=None,
            legend_domain=None,
        ),
        limits=limits,
    )
    formal_results = tuple(_formula_formal_result(result) for result in formal_run.results)
    report = checks.VerificationReport(results=(*evidence.results, *formal_results))
    prepared = (
        PreparedFormula(spec=spec, evidence=evidence, results=report.results)
        if report.passed
        else None
    )
    return FormulaPreparationRun(
        report=report,
        formal_trace=formal_run.trace,
        prepared=prepared,
    )
