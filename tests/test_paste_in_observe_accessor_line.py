# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.10 observation: the positional reading of a pandas line accessor over string keys.

Contract: `.agent/contracts/m10u10.md` predicate group B. Each docstring carries its predicate's
acceptance check; the contract's wording wins wherever a body would assert more.

Skeleton: each body is `pytest.skip` until M10.10's implementation lands. The close deletes every
skip, this line, and nothing else.

Measured on the installed bundle (Pyodide 0.28.3, pandas 2.3.1, matplotlib 3.8.4): string keys draw
at x = 0..n-1 with `units` None and pandas labelling each integral tick `index[int(p)]` -- negative
ticks WRAP to tail keys, in-range integral positions may be absent (n=2 labels 0 alone).
"""

import pytest


def test_b1_committed_accessor_line_fixtures_release() -> None:
    """B1: fixtures `synthetic-accessor-line-{str,num,dec,wide}` + `design-simple-05` +
    `design-simple-06`, regenerated on the installed bundle, each release against their
    `Verified`. Accept: `observation_matches` is True for each."""
    pytest.skip("M10.10 skeleton: the positional reading is unwritten.")


def test_b2_positional_reading_ignores_out_of_range_and_fractional_ticks() -> None:
    """B2: string keys + `units is None` + one line at x = 0..n-1 bit-exact + y = `table.y`
    bit-exact + non-empty in-range integral ticks each labelled `keys[int(p)]` releases, while
    ticks outside `[0, n)` (incl. a wrapped negative label) and non-integral ticks are ignored.
    Accept: a hand-built observation with a wrapped `-1` tick and `""` fractional ticks releases."""
    pytest.skip("M10.10 skeleton: the positional reading is unwritten.")


@pytest.mark.parametrize(
    "perturbation",
    [
        "labels-swapped",
        "label-altered",
        "x-shifted",
        "x-half-step",
        "y-one-ulp",
        "point-appended",
        "point-dropped",
        "units-present",
        "in-range-ticks-removed",
        "second-line",
        "collection-added",
    ],
)
def test_b3_one_perturbation_withholds(perturbation: str) -> None:
    """B3: each ONE perturbation of a B1-released observation withholds. Accept: False."""
    pytest.skip(f"M10.10 skeleton: the positional reading is unwritten ({perturbation}).")


def test_b4_numeric_keys_never_read_positionally() -> None:
    """B4: an integer-key accessor-line observation re-shaped to positions 0..n-1 with tick text
    equal to each key's text withholds; the B1 `num`/`dec` fixtures release. Accept: False +
    True."""
    pytest.skip("M10.10 skeleton: the positional reading is unwritten.")


def test_b6_fixture_set_is_38_dataset_and_20_formula() -> None:
    """B6: `tests/fixtures/observe/` holds 38 dataset + 20 formula fixtures. Accept: exact
    counts."""
    pytest.skip("M10.10 skeleton: the positional reading is unwritten.")
