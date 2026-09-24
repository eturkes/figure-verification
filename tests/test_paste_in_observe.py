# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.2 the observation gate withholds a PNG the sandbox did not draw from the verified table.

Contract: `.agent/contracts/m10u2.md`. Each docstring carries its predicate's acceptance check; the
check is the test's specification and the contract's wording wins wherever a body would assert
more.

Skeleton: each body is `pytest.skip`, retired at M10.2's close together with this line.
"""

import pytest


def test_o1_the_wrapper_s_show_hook_reads() -> None:
    """O1: The wrapper's show hook reads the ONE axes BEFORE saving/clearing and prints exactly one
    tagged JSON observation line: every line's `get_xydata()`, every collection's `get_offsets()`,
    every `BarContainer`'s patches as `(x, width, height, y)`, the axis `units._mapping` of each
    categorical axis, and the tick positions + tick label texts of both axes. Values travel as
    float64 bit patterns or exact decimal strings, never rounded text.

    Accept: Node run over the installed bundle (measurement harness) emits one observation per case;
    a static gate test pins the tag + field set; a second show call, a second axes or a missing line
    ⇒ the filter withholds.
    """
    pytest.skip("owned by **M10.2** (`.agent/spec.md` Deferred)")


def test_o2_the_comparator_a_closed_map_keyed() -> None:
    """O2: The comparator = a CLOSED map keyed on the projected mark (`line`, `scatter`, `bar`,
    `barh`) with no default arm; each entry reads exactly one artist of its own type and demands no
    other plotted artist.

    Accept: An unmapped mark, a mark whose artist is absent, an extra artist, or a wrong artist type
    ⇒ withhold; the map's key set is pinned equal to the projected mark vocabulary.
    """
    pytest.skip("owned by **M10.2** (`.agent/spec.md` Deferred)")


def test_o3_dataset_arm_table_y_equals_the() -> None:
    """O3: Dataset arm: `table.y` equals the observed magnitudes bit for bit (line/scatter y; bar
    height; barh width); numeric `table.x` equals observed positions bit for bit; a string `table.x`
    binds through the axis `units._mapping` (direct marks) or through tick identity (accessor:
    position of the tick = the patch's forward position, tick text = the key; a numeric accessor
    key's text parses to a finite float whose bits equal the key); point count + order equal.

    Accept: The 32 dataset spike cases replayed from committed observation fixtures ⇒ 32/32 release;
    each conjunct perturbed alone ⇒ withhold (count, order, one y bit, one category text, one tick
    label).
    """
    pytest.skip("owned by **M10.2** (`.agent/spec.md` Deferred)")


def test_o4_bar_geometry_is_forward_never_inverted() -> None:
    """O4: Bar geometry is FORWARD, never inverted: `patch.get_x() == position - span/2` and
    `patch.get_y() == 0` (barh: the same on the swapped axes), where `span` = matplotlib's converted
    width from the FIRST direct numeric position (nominal 0.8), 0.8 for direct categorical, 0.5 for
    the pandas accessor.

    Accept: The decimal witnesses (x = 0.000001, keys 1e-06/2e-06) release; a center-equality
    comparator on the same fixtures withholds (the documented false block).
    """
    pytest.skip("owned by **M10.2** (`.agent/spec.md` Deferred)")


def test_o5_formula_arm_observed_x_equals_table() -> None:
    """O5: Formula arm: observed x equals `table.x` bit for bit; observed y lies inside the host
    interval of the projected expression at that x — each `sin cos tan exp log` + `**` call widened
    ±1 ulp, each `+ - * /` endpoint rounded outward 1 ulp, `sqrt` (correctly rounded) + `abs` +
    negation kept as points; a non-singleton argument to a transcendental or `**`, a pole, a
    zero-crossing divisor or a non-finite endpoint ⇒ withhold.

    Accept: The 20 formula spike cases ⇒ 820/820 inside; the cancellation witness (`sin(x) - cos(x)`
    near π/4) releases; a y moved outside by one ulp beyond the interval ⇒ withhold.
    """
    pytest.skip("owned by **M10.2** (`.agent/spec.md` Deferred)")


def test_o6_withhold_only_the_observation_can_turn() -> None:
    """O6: WITHHOLD-ONLY: the observation can turn M10.1's PASS into FAIL and nothing else. A
    `Refused` verdict issues no RPC, so no observation is read; a missing, unparseable, duplicated
    or oversized observation ⇒ FAIL; a matching observation never changes a FAIL.

    Accept: Decision-table test over every (verdict, observation outcome) pair; orc's differential
    agrees on every row.
    """
    pytest.skip("owned by **M10.2** (`.agent/spec.md` Deferred)")


def test_o7_planted_projection_defect_with_the_projector() -> None:
    """O7: Planted projection defect: with the projector mutated host-side (bar/barh x bound to
    `value` instead of `key`; formula `sin(x)` scaled by `1+2⁻⁴⁰`), `verify_python_source` still
    returns `Verified` with a consistent certificate, and the observation gate — alone — withholds.

    Accept: `unittest.mock` projector mutants over committed observation fixtures of the ORIGINAL
    programs: verdict `Verified` (asserted) + gate withhold (asserted); unmutated ⇒ release.
    """
    pytest.skip("owned by **M10.2** (`.agent/spec.md` Deferred)")
