# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Public entry, verdict, plotted table, work + limits — E, T, W of `.agent/contracts/m13u5.md`.

`verify_python_source` is the only public entry and the only thing M10 consumes. It is PURE: the
CSV arrives as bytes on `declared_target`, and the core never opens a path, reads a clock or draws
a random number.

Skeleton: each body is `pytest.skip` and its docstring carries the predicate's acceptance check.
"""

import pytest

# --- E: entry and verdict ---------------------------------------------------------------------


def test_e1_single_public_entry() -> None:
    """`verify_python_source(source, *, declared_target=None, limits=DEFAULT_LIMITS) -> Verdict`.

    Accept: importable from `verifier.pysrc` alone; `Verdict = Verified | Refused`; `__all__`
    pinned as an exact hand-stated set.
    """
    pytest.skip("M13.5 skeleton")


def test_e2_refusal_returned_caller_error_raised() -> None:
    """A refusal is a VALUE; a misconfiguration is an exception.

    Accept: an admitted-but-unprojectable program returns `Refused` with a closed code; a
    `PysrcLimits` carrying a zero field raises `PysrcCallerError` out of the entry.
    """
    pytest.skip("M13.5 skeleton")


def test_e3_stage_order() -> None:
    """prescan -> admit -> project -> bind -> recompute -> integrity -> certify, and no stage
    runs after an earlier one refuses.

    Accept: call-counting bombs on the downstream work, one per refusal reason, per
    `assurance.md` ORDERING law -- never outcome assertions.
    """
    pytest.skip("M13.5 skeleton")


def test_e4_verified_carries_no_source_bytes() -> None:
    """`Verified` holds `spec`, `table`, `certificate` and no model-authored byte beyond the
    certificate's `source_sha256`.

    Accept: `__dataclass_fields__` pinned as an exact set; a recursive scan of a verified result
    for a distinctive submitted identifier finds no occurrence.
    """
    pytest.skip("M13.5 skeleton")


def test_e5_entry_is_pure() -> None:
    """No filesystem, network, clock, RNG or environment read anywhere in the core.

    Accept: the closed-import pin of `test_pysrc_project.py::test_p12_projection_is_pure` extends
    to every new module; with `open`, `socket` and `time` monkeypatched to raise, every predicate
    in this file still passes.
    """
    pytest.skip("M13.5 skeleton")


def test_e6_entry_is_total() -> None:
    """Every admitted program verifies or refuses with a closed code -- never raises, never
    returns a half-populated `Verified`.

    Accept: Hypothesis over generated admitted programs, plus a catch-all `except Exception` bomb
    asserting it never fires.
    """
    pytest.skip("M13.5 skeleton")


# --- T: the plotted table ---------------------------------------------------------------------


def test_t1_table_shape_invariant() -> None:
    """`PlottedTable(x: tuple[CellValue, ...], y: tuple[float, ...])`, `len(x) == len(y)`.

    Accept: unequal lengths raise `PysrcCallerError` from `__post_init__`; `CellValue = float | str`
    pinned as an exact union.
    """
    pytest.skip("M13.5 skeleton")


def test_t2_table_contents_per_arm() -> None:
    """Formula: grid and evaluated y in grid order. Dataset: the two selected columns in FILE
    order.

    Accept: round-trip witnesses in both arms, values compared as bit patterns.
    """
    pytest.skip("M13.5 skeleton")


def test_t3_canonical_encoding() -> None:
    """One canonical byte encoding: `%a` hex-float, length-prefixed UTF-8 strings, no locale, no
    `repr`. `table_sha256` digests exactly those bytes.

    Accept: two structurally equal tables built by different code paths encode identically; a
    one-ulp change in any cell changes the digest.
    """
    pytest.skip("M13.5 skeleton")


def test_t4_table_bounded_before_it_is_built() -> None:
    """`max_table_rows` is checked BEFORE materialization, not after.

    Accept: a grid at `max_grid_samples + 1` refuses at projection; a CSV exceeding
    `max_table_rows` refuses `csv_too_large` before any cell is converted -- proven by a bomb on
    the cell converter.
    """
    pytest.skip("M13.5 skeleton")


# --- W: work and limits -----------------------------------------------------------------------


def test_w1_meter_lives_in_the_core() -> None:
    """One meter, in `verifier.pysrc.budget`; the legacy JSON mode imports it from there.

    Accept: `verifier/work.py` absent; `verifier.expr` and `verifier.eval` import from the core;
    the core's closed-import pin still passes.
    """
    pytest.skip("M13.5 skeleton")


def test_w2_tariff() -> None:
    """1 per expression node per sample, 1 per CSV cell read, 1 per emitted table cell. No
    exponent-magnitude surcharge -- it priced unbounded exact integer powers, which binary64
    `pow` is not.

    Accept: hand-computed charge for one small program asserted EXACTLY; a mutant dropping any of
    the three charges goes red.
    """
    pytest.skip("M13.5 skeleton")


def test_w3_atomic_pre_charge_survives_the_move() -> None:
    """A refused charge leaves consumption unchanged; consumption before it is retained.

    Accept: the existing meter tests move with the module and stay green.
    """
    pytest.skip("M13.5 skeleton")


def test_w4_limits_field_set() -> None:
    """`PysrcLimits` has exactly 14 fields, each validated `>= 1`.

    Accept: the field set is a hand-stated LITERAL; each of the seven new caps has its own
    over-limit witness and its own refusal code.
    """
    pytest.skip("M13.5 skeleton")


def test_w5_max_work_default_is_measured() -> None:
    """`max_work`'s default comes from a measured evaluation rate, not a guess.

    Accept: a benchmark committed under `tools/`; the measured rate and the chosen default both
    appear in the contract's verdict table.
    """
    pytest.skip("M13.5 skeleton")
