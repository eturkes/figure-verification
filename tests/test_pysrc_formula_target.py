# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.4 core target widening.

Contract: `.agent/contracts/m10u4.md` predicate group C. Each docstring carries its
predicate's acceptance check; the check is the test's specification and the contract's wording
wins wherever a body would assert more.

Skeleton: each body is `pytest.skip`, retired at M10.4's close together with this line.
"""

import pytest


def test_c1_spec_interval_start_expr_stop_expr() -> None:
    """C1: `spec.Interval(start: Expr, stop: Expr)` = frozen slotted dataclass, `stop` INCLUSIVE;
    `FormulaTarget.grid: Grid | Interval | None = None`.

    Accept: Field sets hand-pinned: `Interval` = {start, stop}; `FormulaTarget` = {y, grid}
    (unchanged).
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_c2_formula_program_formulatarget_verified_requires_spec() -> None:
    """C2: Formula program + `FormulaTarget`: Verified requires `spec.y == target.y` AND, by
    `target.grid` form: `Grid` → `spec.grid == target.grid`; `Interval` → `spec.grid.start ==
    target.grid.start` and `spec.grid.stop == target.grid.stop`; `None` → no domain check. Any
    failing conjunct → `target_mismatch`. STRUCTURAL: no folding, so `Neg(Num(5)) != Num(-5)`.

    Accept: One witness per conjunct failing alone (y; start; stop; samples under `Grid`); samples
    differing under `Interval` still Verified.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_c3_formula_program_datasettarget_refused_target_mismatch() -> None:
    """C3: Formula program + `DatasetTarget` → Refused `target_mismatch` (was Verified, internal
    provenance). Dataset program + `FormulaTarget` stays `source_not_supplied`; formula program +
    `None` stays Verified internal.

    Accept: Full arm-by-target matrix pinned.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_c4_every_verified_with_a_non_none() -> None:
    """C4: Every Verified with a non-`None` target has `certificate.provenance == "artifact"`.

    Accept: Property over the matrix + Hypothesis-drawn formula programs/targets.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_c5_declared_open_exact_set_per_case() -> None:
    """C5: `declared_open` = exact set per case: dataset bound → {ARTIFACT_GAP}; formula + `None` →
    {ARTIFACT_GAP, INTENT_GAP, NO_ARTIFACT} (bytes unchanged); formula + `Grid` target →
    {ARTIFACT_GAP}; + `Interval` → {ARTIFACT_GAP, SAMPLES_GAP}; + no-domain target → {ARTIFACT_GAP,
    INTERVAL_GAP}. `_UNUSED_DATA_FILE` deleted (unreachable after C3).

    Accept: Hand-stated sets. SAMPLES_GAP = `The request states no sample count. The submitted
    program sets it.` INTERVAL_GAP = `The request states no x interval. The submitted program sets
    the interval and the sample count.`
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_c6_interpretation_formula_none_bytes_unchanged_bound() -> None:
    """C6: Interpretation: formula + `None` → bytes unchanged. Bound formula target → one sentence
    inserted right after `The data comes from the submitted program.`: `Grid` → `The formula, the x
    interval and the sample count match the request.`; `Interval` → `The formula and the x interval
    match the request.`; no domain → `The formula matches the request.`

    Accept: Byte-pinned witness per case.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_c7_certificate_version_the_certificate_field_set() -> None:
    """C7: `CERTIFICATE_VERSION`, the certificate field set (K1) and the 52-member refusal set are
    unchanged.

    Accept: `get_args(RefusalCode.__value__)` size 52; K1 green.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")
