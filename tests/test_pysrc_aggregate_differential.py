# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.6 differential: the independent aggregation oracle against production.

Contract: `.agent/archive/contracts/m13u6.md` sections A, R, B, W and G11.
`tests/oracle_aggregate.py` and the widened `tests/oracle_dataset.py` are the independent side;
this module owns the single translation between the two vocabularies and escalates a semantic
disagreement to the lead instead of absorbing it into the map.

Two standing requirements from `.claude/rules/assurance.md`, both load-bearing here:
a differential that sets no `PYTHONPATH` can compare a tree against ITSELF through the editable
`.pth`, so every differential ships a LOUD vacuity guard; and the map raises on a name it does not
cover, because a generic lowercase-or-strip rule would absorb a real future divergence.

pandas is absent from the gate venv. The pandas-facing comparison is therefore frozen measurement
under `.agent/measurements/`, and every R predicate here is graded against the contract's
hand-stated MEASURED witnesses, compared as BIT PATTERNS rather than by `==`.

"""

import ast
import importlib
import math
import struct
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

import oracle_aggregate as aggregate_oracle_module
import oracle_dataset as projection_oracle_module
from oracle_aggregate import OracleReduction, aggregate, reduce_float64, reduce_int64
from oracle_dataset import (
    ChartLabels,
    CsvFile,
    DatasetChart,
    Field,
    OracleDatasetProjectionError,
)
from oracle_dataset import project as oracle_project
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.spec import DatasetTarget
from verifier.pysrc.verify import Verified, verify_python_source

_DATASET_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"


class _AggregateResult(Protocol):
    @property
    def values(self) -> tuple[float, ...]: ...

    @property
    def dtype(self) -> str: ...


class _AggregateSeries(Protocol):
    def __call__(  # noqa: PLR0913 - mirrors the six-input production seam exactly
        self,
        keys: tuple[float | str, ...],
        value_texts: tuple[str, ...],
        values: tuple[float, ...],
        reduction: OracleReduction,
        *,
        budget: WorkBudget,
        max_groups: int,
    ) -> _AggregateResult: ...


class _Project(Protocol):
    def __call__(self, tree: ast.Module) -> object: ...


def _production_aggregate_module() -> ModuleType:
    return importlib.import_module("verifier.pysrc.aggregate")


def _production_aggregate_series(module: ModuleType) -> _AggregateSeries:
    candidate = vars(module)["aggregate_series"]
    if not callable(candidate):
        message = "verifier.pysrc.aggregate.aggregate_series is not callable"
        raise TypeError(message)
    return cast("_AggregateSeries", candidate)


def _reduce_through_production(
    value_texts: tuple[str, ...],
    values: tuple[float, ...],
    reduction: OracleReduction,
) -> _AggregateResult:
    return _production_aggregate_series(_production_aggregate_module())(
        ("group",) * len(values),
        value_texts,
        values,
        reduction,
        budget=WorkBudget(len(values) + 1),
        max_groups=1,
    )


def _production_project_module() -> ModuleType:
    return importlib.import_module("verifier.pysrc.project")


def _production_project(module: ModuleType) -> _Project:
    candidate = getattr(module, "project", None)
    if not callable(candidate):
        message = "verifier.pysrc.project.project is absent or not callable"
        raise TypeError(message)
    return cast("_Project", candidate)


def _project_both(source: str) -> tuple[object, object]:
    expected = oracle_project(ast.parse(source))
    observed = _production_project(_production_project_module())(parse_admitted(source))
    assert projection_oracle_module.normalize(expected) == projection_oracle_module.normalize(
        observed
    )
    return expected, observed


def _assert_projection_agreement(source: str) -> None:
    oracle_tree = ast.parse(source)
    try:
        production_tree = parse_admitted(source)
    except PysrcRefusalError as production_admission:
        with pytest.raises(OracleDatasetProjectionError) as oracle_caught:
            oracle_project(oracle_tree)
        assert str(oracle_caught.value.code) == str(production_admission.code)
        return
    try:
        expected = oracle_project(oracle_tree)
    except OracleDatasetProjectionError as oracle_error:
        with pytest.raises(PysrcRefusalError) as production_caught:
            _production_project(_production_project_module())(production_tree)
        assert str(oracle_error.code) == str(production_caught.value.code)
        return
    observed = _production_project(_production_project_module())(production_tree)
    assert projection_oracle_module.normalize(expected) == projection_oracle_module.normalize(
        observed
    )


def _source(
    reduction: OracleReduction, *, mark: str = "bar", x: str = "g.index", y: str = "g.values"
) -> str:
    return (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("data.csv")\n'
        + f'g = df.groupby("key")["value"].{reduction}()\n'
        + f"plt.{mark}({x}, {y})\n"
        + "plt.show()\n"
    )


def _csv(key_cells: tuple[str, ...], value_cells: tuple[str, ...]) -> bytes:
    rows = (f"{key},{value}" for key, value in zip(key_cells, value_cells, strict=True))
    return ("key,value\n" + "\n".join(rows) + "\n").encode()


def _verified(
    key_cells: tuple[str, ...],
    value_cells: tuple[str, ...],
    reduction: OracleReduction,
    *,
    mark: str = "bar",
) -> Verified:
    verdict = verify_python_source(
        _source(reduction, mark=mark),
        declared_target=DatasetTarget("data.csv", _csv(key_cells, value_cells)),
    )
    if not isinstance(verdict, Verified):
        message = f"production refused an oracle-admitted aggregate: {verdict!r}"
        pytest.fail(message)
    return verdict


def _bits(value: float | int) -> bytes:
    return struct.pack(">d", float(value))


def _micro_cell(units: int) -> str:
    sign = "-" if units < 0 else ""
    return f"{sign}0.{abs(units):06d}".rstrip("0")


@st.composite
def _cancelling_float_cells(draw: DrawFn) -> tuple[str, ...]:
    magnitude = draw(st.integers(min_value=1, max_value=1_000_000_000))
    micros = draw(
        st.lists(
            st.one_of(
                st.integers(min_value=-999_999, max_value=-1),
                st.integers(min_value=1, max_value=999_999),
            ),
            min_size=1,
            max_size=8,
        )
    )
    return (f"{magnitude}.0", *(_micro_cell(units) for units in micros), f"-{magnitude}.0")


_CANCELLING_FLOAT_CELLS: SearchStrategy[tuple[str, ...]] = _cancelling_float_cells()

# --- the anchor and the vacuity guard ----------------------------------------


def test_aggregate_differential_is_not_vacuous() -> None:
    """Loud guard: oracle and production must resolve to DIFFERENT `__file__` paths, and
    production must resolve from this tree's `src/`. A differential comparing a tree against
    itself passes unconditionally and pins nothing."""
    module = _production_aggregate_module()
    oracle_file = Path(aggregate_oracle_module.__file__).resolve()
    production_file = Path(cast("str", module.__file__)).resolve()
    worktree = Path(__file__).resolve().parents[1]
    assert oracle_file != production_file, (
        "VACUOUS DIFFERENTIAL: oracle and production resolve to the same __file__"
    )
    assert oracle_file == worktree / "tests" / "oracle_aggregate.py"
    assert production_file == worktree / "src" / "verifier" / "pysrc" / "aggregate.py", (
        "production must resolve from this worktree's src/; set PYTHONPATH to the worktree src"
    )


def test_oracle_first_aggregate_bar_is_complete() -> None:
    """Anchor: the oracle projects `df.groupby('region')['revenue'].sum()` plotted as
    `plt.bar(g.index, g.values)` to a complete aggregate chart, with no field left unset. The
    anchor runs BEFORE any differential, so an oracle that refuses everything cannot read as
    agreement."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("data.csv")\n'
        + 'g = df.groupby("region")["revenue"].sum()\n'
        + "plt.bar(g.index, g.values)\n"
        + "plt.show()\n"
    )
    assert oracle_project(ast.parse(source)) == DatasetChart(
        kind="bar",
        csv=CsvFile("data.csv"),
        horizontal=Field("region"),
        vertical=Field("revenue"),
        annotations=ChartLabels(),
        reduction="sum",
    )


# --- R: the reduction engine -------------------------------------------------


@given(value_cells=_CANCELLING_FLOAT_CELLS)
def test_r1_differential_float_sum_agrees_bitwise(value_cells: tuple[str, ...]) -> None:
    """R1: over a generated float64 cohort inside C10's fixed-point profile, oracle and production
    sums agree on every bit pattern. Hypothesis-driven, with the cohort drawn so groups carry
    cancelling magnitudes — the shape that separates compensated from naive summation."""
    key_cells = ("group",) * len(value_cells)
    expected = aggregate(key_cells, value_cells, "sum")
    observed = _verified(key_cells, value_cells, "sum")
    assert _bits(observed.table.y[0]) == _bits(expected.reduced[0])


def test_r1_measured_witness_separates_kahan_from_naive_and_fsum() -> None:
    """R1: the four cells `[1000000000.0, 0.000001, 0.000001, -1000000000.0]` give Kahan
    `0x1.1000000000000p-19`, naive `0x1.0000000000000p-19` and `fsum`/Neumaier
    `0x1.0c6f7a0b5ed8dp-19` — three distinct values, hand-stated as hex-float literals. Both the
    oracle and production must return the Kahan value, and the test computes the other two locally
    so the separation is proven rather than asserted."""
    value_cells = ("1000000000.0", "0.000001", "0.000001", "-1000000000.0")
    values = tuple(float(cell) for cell in value_cells)
    expected = float.fromhex("0x1.1000000000000p-19")
    naive_expected = float.fromhex("0x1.0000000000000p-19")
    fsum_expected = float.fromhex("0x1.0c6f7a0b5ed8dp-19")
    naive = 0.0
    for value in values:
        naive += value
    assert _bits(naive) == _bits(naive_expected)
    assert _bits(math.fsum(values)) == _bits(fsum_expected)
    assert len({_bits(expected), _bits(naive), _bits(math.fsum(values))}) == 3
    assert _bits(reduce_float64(values, "sum")) == _bits(expected)
    observed = _verified(("group",) * len(values), value_cells, "sum")
    assert _bits(observed.table.y[0]) == _bits(expected)


def test_r2_differential_float_mean_agrees_bitwise() -> None:
    """R2: `mean` is the Kahan sum divided by the non-NaN count, in that order. Differential over
    the same cohort, bit patterns, plus a witness where sum-then-divide and a running mean differ
    in the last bit."""
    value_cells = ("1000000000.0", "1000000000.0", "-1000000000.0")
    values = tuple(float(cell) for cell in value_cells)
    expected = float.fromhex("0x1.3de4355555555p+28")
    running_expected = float.fromhex("0x1.3de4355555556p+28")
    running = 0.0
    for count, value in enumerate(values, start=1):
        running += (value - running) / count
    assert _bits(running) == _bits(running_expected)
    assert _bits(reduce_float64(values, "mean")) == _bits(expected)
    assert _bits(expected) != _bits(running)
    observed = _verified(("group",) * len(values), value_cells, "mean")
    assert _bits(observed.table.y[0]) == _bits(expected)


def test_r3_differential_int_mean_casts_before_summing() -> None:
    """R3: `[2**53, 1, 0]` — pandas `mean` is `0x1.5555555555555p+51`, exact-then-divide is
    `0x1.5555555555556p+51`. Hand-stated hex-float pins; both sides must return pandas'. The
    dtype-retaining reductions compare over C10-admitted integer cells, where their float table
    carrier remains exact."""
    values = (2**53, 1, 0)
    expected = float.fromhex("0x1.5555555555555p+51")
    exact_then_divide = float.fromhex("0x1.5555555555556p+51")
    oracle_mean = reduce_int64(values, "mean")
    production_mean = _reduce_through_production(
        tuple(str(value) for value in values), tuple(float(value) for value in values), "mean"
    )
    assert isinstance(oracle_mean, float)
    assert _bits(oracle_mean) == _bits(expected)
    assert _bits(sum(values) / len(values)) == _bits(exact_then_divide)
    assert production_mean.dtype == "float64"
    assert _bits(production_mean.values[0]) == _bits(expected)

    retaining_values = (2**31 - 1, 1, 0)
    retaining_texts = tuple(str(value) for value in retaining_values)
    retaining_floats = tuple(float(value) for value in retaining_values)
    for reduction, hand_expected in (("sum", 2**31), ("min", 0), ("max", 2**31 - 1)):
        typed_reduction = cast("OracleReduction", reduction)
        observed = _reduce_through_production(retaining_texts, retaining_floats, typed_reduction)
        assert reduce_int64(retaining_values, typed_reduction) == hand_expected
        assert observed.dtype == "int64"
        assert _bits(observed.values[0]) == _bits(hand_expected)


def test_r4_differential_extrema_keep_the_first_tied_bits() -> None:
    """R4: `[-0.0, +0.0]` reduces to `-0.0` for both `min` and `max`, and the reversed input to
    `+0.0`. Compared through `math.copysign`/`struct` bit patterns, since `-0.0 == +0.0` hides the
    whole predicate."""
    negative_first = (-0.0, 0.0)
    positive_first = (0.0, -0.0)
    for reduction in ("min", "max"):
        oracle_negative = reduce_float64(negative_first, reduction)
        oracle_positive = reduce_float64(positive_first, reduction)
        production_negative = _reduce_through_production(
            ("-0.0", "0.0"), negative_first, reduction
        ).values[0]
        production_positive = _reduce_through_production(
            ("0.0", "-0.0"), positive_first, reduction
        ).values[0]
        assert math.copysign(1.0, oracle_negative) == -1.0
        assert math.copysign(1.0, production_negative) == -1.0
        assert math.copysign(1.0, oracle_positive) == 1.0
        assert math.copysign(1.0, production_positive) == 1.0
        assert _bits(oracle_negative) == _bits(production_negative)
        assert _bits(oracle_positive) == _bits(production_positive)


def test_r7_differential_key_order_is_code_point_ascending() -> None:
    """R7: over a key corpus built to separate the candidates — mixed case, digits versus letters,
    embedded spaces, non-ASCII, and strings differing only past a common prefix — oracle and
    production emit the same key order, and it is code-point ascending rather than a locale
    collation or file order."""
    key_cells = ("患者", "a 2", "Z", "10", "a", "é", "A", "2", "a 10", "z")
    value_cells = ("1",) * len(key_cells)
    hand_order = ("10", "2", "A", "Z", "a", "a 10", "a 2", "z", "é", "患者")
    expected = aggregate(key_cells, value_cells, "sum")
    observed = _verified(key_cells, value_cells, "sum")
    assert expected.keys == hand_order
    assert expected.keys != key_cells
    assert observed.table.x == hand_order


def test_r8_differential_dtype_decides_before_order() -> None:
    """R8: the witness pair — `['2', 'a', '10', '2']` orders `['10', '2', 'a']` as strings, while
    an all-numeric key column orders numerically. Both sides agree on both columns."""
    text_keys = ("2", "a", "10", "2")
    text_values = ("1",) * len(text_keys)
    numeric_keys = ("2", "10", "2")
    numeric_values = ("1",) * len(numeric_keys)
    text_oracle = aggregate(text_keys, text_values, "sum")
    numeric_oracle = aggregate(numeric_keys, numeric_values, "sum")
    text_production = _verified(text_keys, text_values, "sum")
    numeric_production = _verified(numeric_keys, numeric_values, "sum")
    assert text_oracle.keys == ("10", "2", "a")
    assert numeric_oracle.keys == ("2", "10")
    assert text_production.table.x == ("10", "2", "a")
    assert numeric_production.table.x == (2.0, 10.0)


def test_r9_differential_members_keep_file_order() -> None:
    """R9: a CSV whose rows for one key are not in value order reduces in FILE order on both
    sides, which is what makes R1's ordered Kahan well defined."""
    key_cells = ("b", "a", "b", "b", "b")
    value_cells = ("1000000000.0", "5.0", "1000000000.0", "0.000001", "0.000002")
    expected_file_order = float.fromhex("0x1.dcd650000000dp+30")
    sorted_value_order = float.fromhex("0x1.dcd650000000cp+30")
    expected = aggregate(key_cells, value_cells, "sum")
    observed = _verified(key_cells, value_cells, "sum")
    assert expected.keys == ("a", "b")
    assert _bits(expected.reduced[1]) == _bits(expected_file_order)
    assert _bits(expected_file_order) != _bits(sorted_value_order)
    assert observed.table.x == ("a", "b")
    assert _bits(observed.table.y[1]) == _bits(expected_file_order)


# --- A, B, W: the widened projection ----------------------------------------


def test_a2_differential_chain_shape_admits_and_refuses_alike() -> None:
    """A2: over the admitted chain and one witness per structural deviation, the oracle and
    production reach the same verdict and the same refusal code. A disagreement is ESCALATED, never
    absorbed: M13.4's single disagreement resolved in the ORACLE's favour and was a real defect no
    red suite had reached."""
    valid = _source("sum")
    _project_both(valid)
    deviations = (
        'key = "key"\n' + valid.replace('groupby("key")', "groupby(key)"),
        'column = "value"\n' + valid.replace('["value"]', "[column]"),
        valid.replace('["value"]', '[["value", "other"]]'),
        valid.replace(".sum()", ".median()"),
        valid.replace(".sum()", ".sum(1)"),
        valid.replace("df.groupby", "other.groupby"),
    )
    for source in deviations:
        _assert_projection_agreement(source)


def test_a4_differential_aggregate_channels_project_alike() -> None:
    """A4: `plt.bar(g.index, g.values)`, `plt.bar(g.index, g)`, and the two mixed-channel refusals
    project or refuse identically on both sides."""
    _project_both(_source("sum"))
    _project_both(_source("sum", y="g"))
    for source in (
        _source("sum", x='df["key"]'),
        _source("sum", y='df["value"]'),
    ):
        _assert_projection_agreement(source)


def test_b1_differential_barh_shares_bar_argument_order() -> None:
    """B1: `plt.barh(g.index, g.values)` puts the key in x and the reduced column in y on both
    sides, differing from `bar` in the mark alone."""
    bar, _ = _project_both(_source("sum", mark="bar"))
    barh, _ = _project_both(_source("sum", mark="barh"))
    if not isinstance(bar, DatasetChart) or not isinstance(barh, DatasetChart):
        pytest.fail("dataset sources must project to DatasetChart")
    assert bar.kind == "bar"
    assert barh.kind == "barh"
    assert barh.horizontal == bar.horizontal == Field("key")
    assert barh.vertical == bar.vertical == Field("value")
    assert barh.reduction == bar.reduction == "sum"


def test_w1_differential_cosmetic_fields_are_carried_not_discarded() -> None:
    """W1 + W6b: programs differing only in `figsize`, `tick_rotation` or `tight_layout` project to
    UNEQUAL specs on both sides, and `label=` alone sets the series name while `color=` does not.
    Both differential suites normalize `Labels` explicitly, so this widening updates the field maps
    deliberately rather than letting an unmapped name pass."""
    plain_source = _source("sum")
    figure_source = plain_source.replace(
        "plt.bar(g.index, g.values)",
        "plt.figure(figsize=(10, 6))\nplt.bar(g.index, g.values)",
    )
    rotation_source = plain_source.replace("plt.show()", "plt.xticks(rotation=45)\nplt.show()")
    tight_source = plain_source.replace("plt.show()", "plt.tight_layout()\nplt.show()")
    labelled_source = plain_source.replace(
        "plt.bar(g.index, g.values)",
        "plt.bar(g.index, g.values, label='Revenue', color='steelblue')",
    )
    colour_source = plain_source.replace(
        "plt.bar(g.index, g.values)", "plt.bar(g.index, g.values, color='steelblue')"
    )
    projected = tuple(
        _project_both(source)[0]
        for source in (
            plain_source,
            figure_source,
            rotation_source,
            tight_source,
            labelled_source,
            colour_source,
        )
    )
    if not all(isinstance(plot, DatasetChart) for plot in projected):
        pytest.fail("dataset sources must project to DatasetChart")
    plain, figure, rotation, tight, labelled, colour = cast(
        "tuple[DatasetChart, DatasetChart, DatasetChart, DatasetChart, DatasetChart, DatasetChart]",
        projected,
    )
    assert figure != plain and figure.annotations.canvas_size == (Fraction(10), Fraction(6))
    assert rotation != plain and rotation.annotations.tick_angle == Fraction(45)
    assert tight != plain and tight.annotations.packed_layout is True
    assert labelled.annotations.series_name == "Revenue"
    assert colour.annotations.series_name is None


def test_g11_differential_group_counts_agree() -> None:
    """G11 + G78r: the per-group counts agree on both sides, and on both sides they sum to the
    CSV's data-row count for every aggregate — a `groupby` drops no row."""
    key_cells = ("b", "a", "b", "c", "a", "b")
    value_cells = ("1", "2", "3", "4", "5", "6")
    for reduction in ("sum", "mean", "min", "max"):
        expected = aggregate(key_cells, value_cells, reduction)
        observed = _verified(key_cells, value_cells, reduction)
        group_counts = observed.certificate.group_counts
        assert observed.table.x == expected.keys
        assert group_counts == expected.counts
        assert group_counts is not None
        assert sum(group_counts) == len(key_cells)
