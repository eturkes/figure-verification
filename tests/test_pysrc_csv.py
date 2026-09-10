# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Target binding + the safe CSV profile — C1-C11 of `.agent/contracts/m13u5.md`.

The sandbox parses the user's file with `pandas.read_csv`; the verifier may not depend on pandas
and parses with stdlib `csv` + `float`. Everything the two would read differently is REFUSED, so
the profile is deliberately narrow: refusing is cheap, and plotting a number the verifier parsed
differently from the renderer is the failure this project exists to prevent.

Skeleton: each body is `pytest.skip` and its docstring carries the predicate's acceptance check.
"""

import pytest


def test_c1_declared_target_union() -> None:
    """`DeclaredTarget = DatasetTarget(path, content) | FormulaTarget(y, grid)`.

    Accept: exact-set pin on the union; a total map over it carries a missing-arm mutant.
    `FormulaTarget` holds a parsed `spec.Expr` tree, so the core needs no expression parser.
    """
    pytest.skip("M13.5 skeleton")


def test_c2_dataset_arm_without_bytes_refuses() -> None:
    """No `DatasetTarget` -> `source_not_supplied`, including when a `FormulaTarget` is supplied
    instead -- it carries no bytes.

    Accept: both witnesses; the `FormulaTarget` case must NOT reach `target_mismatch`.
    """
    pytest.skip("M13.5 skeleton")


def test_c3_path_binding_is_byte_exact() -> None:
    """`DatasetPlot.source.path` equals `DatasetTarget.path` byte-for-byte -- no normalization,
    no `Path` resolution, no case folding.

    Accept: near-miss witnesses each refusing `target_mismatch` -- trailing slash, `./` prefix,
    differing case, and a Unicode-equivalent but non-identical spelling.
    """
    pytest.skip("M13.5 skeleton")


def test_c4_formula_target_compares_structurally() -> None:
    """With a `FormulaTarget`, the projected `y` must equal `target.y` structurally, and the grid
    must equal `target.grid` when that is given.

    Accept: structural-equality witness pairs, including two spellings of one grid that M13.3
    makes equal; a mismatch refuses `target_mismatch`.
    """
    pytest.skip("M13.5 skeleton")


def test_c5_formula_arm_never_silently_consumes_a_target() -> None:
    """Formula arm with a `DatasetTarget`, or with none, verifies at `provenance = "internal"`
    and SAYS the user artifact was not consumed.

    Accept: the certificate string byte-pinned for all three formula/target combinations.
    """
    pytest.skip("M13.5 skeleton")


def test_c6_strict_structural_profile() -> None:
    """UTF-8 without BOM, `csv.reader(strict=True)`, exactly one header row, every data row the
    header's width, no post-quote junk. Outside -> `csv_not_parsable`.

    Accept: one witness per divergence class measured by `spike-m13u5b` T4 -- BOM, short row, long
    row, post-quote junk -- each refusing.
    """
    pytest.skip("M13.5 skeleton")


def test_c7_columns_present_and_unambiguous() -> None:
    """Both named columns present in the header, matched byte-for-byte; a duplicate header name
    refuses.

    Accept: present, absent and duplicate witnesses; absent -> `column_not_present`.
    """
    pytest.skip("M13.5 skeleton")


def test_c8_numeric_where_a_number_is_required() -> None:
    """`y` numeric always; `x` numeric for `line` and `scatter`, numeric or categorical for `bar`.

    Accept: the per-mark witness matrix; a categorical x under `plt.plot` refuses
    `column_not_numeric`.
    """
    pytest.skip("M13.5 skeleton")


def test_c9_no_null_survives() -> None:
    """An empty cell or any pandas default NA spelling in either selected column refuses
    `value_not_in_profile`. This refusal is what makes G8 hold by construction.

    Accept: the NA spelling list is a hand-stated LITERAL sourced from the measured build, not
    read from production.
    """
    pytest.skip("M13.5 skeleton")


def test_c10_cell_text_inside_the_zero_disagreement_region() -> None:
    """Every numeric cell text lies inside the measured 0-disagreement region for stdlib `float`
    vs the sandbox's `pandas.read_csv`; outside refuses `value_not_in_profile`.

    Accept: a differential over >=1,000,000 in-profile cells at zero BIT disagreements, plus a
    refusal witness just outside each boundary.

    PENDING the contract's § Open ruling -- the region itself is not yet chosen.
    """
    pytest.skip("M13.5 skeleton; region pending the contract's Open ruling")


def test_c11_source_order_is_preserved() -> None:
    """Row order is file order. The verifier never sorts, and the legacy total-sort closure is
    not reused.

    Accept: a CSV whose rows are not sorted by x plots in file order; a sort-injecting mutant goes
    red.
    """
    pytest.skip("M13.5 skeleton")
