# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.6 aggregation: admission, projection, the reduction engine, `barh`, and the certificate.

Contract: `.agent/archive/contracts/m13u6.md` predicate groups A, R, B, plus G11/G9r and K1-K3. Each
docstring carries its predicate's acceptance check; the check is the test's specification and the
contract's wording wins wherever a body would assert more.

The reduction engine reproduces what the EXECUTED program plots, not what is arithmetically
nicest. pandas reduces a float64 group with ordered binary64 Kahan compensation in file-row order,
measured: naive left-to-right differs on 2,761/4,000 admitted-profile CSV groups (worst 8,192 ulp),
`math.fsum` on 1,483 (worst 5,252 ulp), Kahan on 0/16,062. A more precise engine is a less faithful
one, exactly as in M13.5's `expr.py` ruling.
"""

import hashlib
import math
import struct
from dataclasses import replace
from pathlib import Path
from typing import get_args

import pytest

from verifier.pysrc import Refused, Verified, spec, verify_python_source
from verifier.pysrc import csvread as csvread_module
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.certificate import _AXIS_LETTERS, certify
from verifier.pysrc.errors import PysrcCallerError, PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits
from verifier.pysrc.project import project
from verifier.pysrc.table import PlottedTable

_ROOT = Path(__file__).resolve().parent.parent

_DATASET_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"


def _dataset_source(body: str, *, path: str = "sales.csv") -> str:
    return _DATASET_PRELUDE + f'df = pd.read_csv("{path}")\n' + body


# A `DatasetMark` names the SPEC member, not the matplotlib call: `line` is drawn by `plt.plot`.
_MARK_CALLS = {"line": "plot", "scatter": "scatter", "bar": "bar", "barh": "barh"}


def _aggregate_source(
    reduction: str,
    *,
    mark: str = "bar",
    x: str = "g.index",
    y: str = "g.values",
) -> str:
    call = _MARK_CALLS[mark]
    return _dataset_source(
        f'g = df.groupby("region")["revenue"].{reduction}()\nplt.{call}({x}, {y})\nplt.show()\n'
    )


def _aggregate_verdict(
    content: bytes,
    reduction: str,
    *,
    mark: str = "bar",
    limits: PysrcLimits = DEFAULT_LIMITS,
) -> object:
    return verify_python_source(
        _aggregate_source(reduction, mark=mark),
        declared_target=spec.DatasetTarget(path="sales.csv", content=content),
        limits=limits,
    )


def _admission_code(source: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    return str(caught.value.code)


def _projection_code(source: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        project(parse_admitted(source))
    return str(caught.value.code)


# --- A: `groupby` admission and projection -----------------------------------


def test_a1_reduction_vocabulary_and_group_field_are_closed() -> None:
    """A1: `get_args(Reduction.__value__)` equals the hand-stated literal tuple
    `("sum", "mean", "min", "max")`, and `DatasetPlot.__dataclass_fields__` is pinned as an exact
    set including `group: Reduction | None = None`. Hand-stated, never read from production."""
    assert get_args(spec.Reduction.__value__) == ("sum", "mean", "min", "max")
    fields = spec.DatasetPlot.__dataclass_fields__
    assert set(fields) == {"mark", "source", "x", "y", "group", "labels"}
    assert fields["group"].default is None


def test_a2_admitted_chain_shape_projects() -> None:
    """A2: `<frame>.groupby('<key>')['<col>'].<reduction>()` bound by assignment projects, with the
    group key as x and the reduced column as y.

    "Bound by assignment to a name" carries P9's rule into the name space this unit adds: rebinding
    an aggregate name refuses `name_rebound`, so one name still denotes one thing. The rebind guard
    is a chain of `or` conjuncts, and branch coverage reads the chain as ONE jump — an unpinned
    conjunct is invisible to the gate and visible only to its own mutant."""
    for reduction in ("sum", "mean", "min", "max"):
        projected = project(parse_admitted(_aggregate_source(reduction)))
        assert isinstance(projected, spec.DatasetPlot), reduction
        assert projected.x == spec.Column("region"), reduction
        assert projected.y == spec.Column("revenue"), reduction
        assert projected.group == reduction, reduction

    rebound = _dataset_source(
        'g = df.groupby("region")["revenue"].sum()\n'
        'g = df.groupby("region")["orders"].sum()\n'
        "plt.bar(g.index, g.values)\nplt.show()\n"
    )
    assert _projection_code(rebound) == "name_rebound"


def test_a2_chain_deviations_each_refuse() -> None:
    """A2: one refusal witness per deviation — non-literal key, non-literal column, tuple column
    selection `['revenue', 'orders']` (the design set writes it once), unknown reduction
    `.median()`, a reduction carrying an argument, a chain on an unbound name.

    Each deviation names the code its OWN fault carries. A uniform `attribute_not_admitted` would
    assert more than A2 does, and it would hide that a non-literal subscript is caught by the
    string-literal rule rather than by the chain shape."""
    deviations = {
        "non-literal-key": (
            _dataset_source('key = "region"\ng = df.groupby(key)["revenue"].sum()\n'),
            "column_not_literal",
        ),
        "non-literal-column": (
            _dataset_source('column = "revenue"\ng = df.groupby("region")[column].sum()\n'),
            "column_not_literal",
        ),
        "column-list": (
            _dataset_source('g = df.groupby("region")[["revenue", "orders"]].sum()\n'),
            "column_not_literal",
        ),
        "unknown-reduction": (
            _dataset_source('g = df.groupby("region")["revenue"].median()\n'),
            "attribute_not_admitted",
        ),
        "reduction-argument": (
            _dataset_source('g = df.groupby("region")["revenue"].sum(1)\n'),
            "keyword_not_admitted",
        ),
        "no-column-selection": (
            _dataset_source('g = df.groupby("region").sum()\n'),
            "attribute_not_admitted",
        ),
        "groupby-without-a-key": (
            _dataset_source("g = df.groupby()\n"),
            "column_not_literal",
        ),
        "groupby-with-two-keys": (
            _dataset_source('g = df.groupby("region", "city")\n'),
            "column_not_literal",
        ),
        "groupby-key-by-keyword": (
            _dataset_source('g = df.groupby(by="region")\n'),
            "column_not_literal",
        ),
        "trailing-call-with-an-argument": (
            _dataset_source('g = df.groupby("region")["revenue"].sum().reset_index(drop=True)\n'),
            "attribute_not_admitted",
        ),
    }
    for name, (source, expected) in deviations.items():
        assert _admission_code(source) == expected, name

    unbound = _DATASET_PRELUDE + 'g = missing.groupby("region")["revenue"].sum()\n'
    assert _admission_code(unbound) == "name_not_bound"

    # The frame must be the ONE bound `read_csv` frame. A chain rooted in some other bound name
    # passes admission -- the name IS bound -- and projection is where it stops.
    wrong_frame = _dataset_source(
        'other = df["region"]\n'
        'g = other.groupby("region")["revenue"].sum()\n'
        "plt.bar(g.index, g.values)\nplt.show()\n"
    )
    assert _projection_code(wrong_frame) == "column_not_from_source"


def test_a3_reset_index_projects_as_the_series_spelling() -> None:
    """A3: `df.groupby('r')['o'].max().reset_index()` projects, EQUAL to the series spelling.

    M13.8 moved this boundary. The reset re-spells one reduced series as a two-column frame, so it
    computes the same numbers and must yield the same spec; the trailing call it rides on stays
    refused for every other attribute name, which `tests/test_pysrc_accessor.py` pins as a set."""
    reset = project(
        parse_admitted(
            _dataset_source(
                'g = df.groupby("region")["revenue"].max().reset_index()\n'
                'plt.bar(g["region"], g["revenue"])\n'
                "plt.show()\n"
            )
        )
    )
    series = project(parse_admitted(_aggregate_source("max")))
    assert isinstance(reset, spec.DatasetPlot)
    assert reset == series


def test_a4_aggregate_channels_project() -> None:
    """A4: `plt.bar(g.index, g.values)` and `plt.bar(g.index, g)` both project."""
    explicit_values = project(parse_admitted(_aggregate_source("sum")))
    bare_aggregate = project(parse_admitted(_aggregate_source("sum", y="g")))
    assert isinstance(explicit_values, spec.DatasetPlot)
    assert isinstance(bare_aggregate, spec.DatasetPlot)
    assert explicit_values == bare_aggregate


def test_a4_mixing_aggregate_and_raw_channels_refuses() -> None:
    """A4: `plt.bar(df['region'], g.values)` and `plt.bar(g.index, df['revenue'])` each refuse
    `column_not_from_source` — one mark reads one projection."""
    raw_x = _aggregate_source("sum", x='df["region"]')
    raw_y = _aggregate_source("sum", y='df["revenue"]')
    assert _projection_code(raw_x) == "column_not_from_source"
    assert _projection_code(raw_y) == "column_not_from_source"


def test_a5_frame_values_admits_then_refuses_at_projection() -> None:
    """A5: `df.values` is ADMITTED (admission has no types) and refused `column_not_from_source` at
    projection. Pinned at BOTH stages separately — one end-to-end assertion cannot say which caught
    it. `g.shape` and `df.loc` refuse `attribute_not_admitted` at admission.

    `df.index` carries the same shape on the OTHER attribute: the x channel spells the aggregate
    idiom exactly, and projection refuses it because `df` names a frame rather than a reduction."""
    frame_values = _dataset_source('plt.bar(df.values, df["revenue"])\nplt.show()\n')
    tree = parse_admitted(frame_values)
    with pytest.raises(PysrcRefusalError) as caught:
        project(tree)
    assert caught.value.code == "column_not_from_source"

    frame_index = _dataset_source(
        'g = df.groupby("region")["revenue"].sum()\nplt.bar(df.index, g.values)\nplt.show()\n'
    )
    assert _projection_code(frame_index) == "column_not_from_source"

    aggregate_shape = _dataset_source(
        'g = df.groupby("region")["revenue"].sum()\nshape = g.shape\n'
    )
    frame_loc = _dataset_source("location = df.loc\n")
    assert _admission_code(aggregate_shape) == "attribute_not_admitted"
    assert _admission_code(frame_loc) == "attribute_not_admitted"


def test_a6_unplotted_aggregation_refuses() -> None:
    """A6: a bound aggregation no mark references refuses `statement_not_projected`, exactly as an
    unused grid does. The design set writes a bare `data.groupby('city')` once.

    An UNBOUND chain refuses the same way and by a different route: a bare chain statement never
    reaches the unused sweep, because nothing was bound for the sweep to find. It is refused where
    every other admitted call with no drawing effect is."""
    source = _dataset_source(
        'unused = df.groupby("region")["revenue"].sum()\n'
        'plt.scatter(df["region"], df["revenue"])\n'
        "plt.show()\n"
    )
    assert _projection_code(source) == "statement_not_projected"

    statement = _dataset_source(
        'df.groupby("region")["revenue"].sum()\n'
        'plt.scatter(df["region"], df["revenue"])\n'
        "plt.show()\n"
    )
    assert _projection_code(statement) == "statement_not_projected"


def test_a7_local_fault_precedes_global_count() -> None:
    """A7: a program with a faulty aggregation AND two marks refuses the aggregation fault. Per
    `pysrc.md` the witness must be a SECOND faulty statement in a program admission ADMITS —
    at a first faulty statement the two orders are equivalent."""
    source = _dataset_source(
        'g = df.groupby("region")["revenue"].sum()\n'
        "plt.bar(g.index, g.values)\n"
        'plt.scatter(df["region"], g.values)\n'
        "plt.show()\n"
    )
    assert _projection_code(source) == "column_not_from_source"


def test_a8_atomic_chain_admission_keeps_the_depth_bound() -> None:
    """A8: `np.random.rand(3)` still refuses `attribute_not_admitted` — the atomic aggregation rule
    did not relax `_dotted`'s depth-1 bound. A mutant widening `_admit_aggregation` to accept any
    trailing attribute goes red on `df.groupby('r')['c'].cumsum()`.

    Admitting the chain atomically admits it in EVERY expression slot, the formula arm's included.
    The formula arm has no projection that can hold a reduced column, so a chain inside a formula
    `y` refuses `expression_not_projected` — the arm's own code for a value it cannot state."""
    random_call = "import numpy as np\nimport matplotlib.pyplot as plt\nx = np.random.rand(3)\n"
    cumsum = _dataset_source('g = df.groupby("region")["revenue"].cumsum()\n')
    assert _admission_code(random_call) == "attribute_not_admitted"
    assert _admission_code(cumsum) == "attribute_not_admitted"

    formula_arm = (
        "import numpy as np\nimport matplotlib.pyplot as plt\n"
        "x = np.linspace(0, 10, 11)\n"
        'plt.plot(x, x.groupby("a")["b"].sum())\n'
        "plt.show()\n"
    )
    assert _projection_code(formula_arm) == "expression_not_projected"


# --- R: the reduction engine, measured against pandas ------------------------


def test_r1_float_sum_is_kahan_not_naive_or_fsum() -> None:
    """R1: differential against pandas over the committed reduction corpus, bit patterns, zero
    disagreements. The naive-sum mutant and the `fsum` mutant must BOTH go red; they are what price
    this predicate."""
    values = (1_000_000_000.0, 0.000001, 0.000001, -1_000_000_000.0)
    content = b"region,revenue\none,1000000000.0\none,0.000001\none,0.000001\none,-1000000000.0\n"
    result = _aggregate_verdict(content, "sum")
    assert isinstance(result, Verified)
    observed = result.table.y[0]
    naive = 0.0
    for value in values:
        naive += value
    assert observed.hex() == "0x1.1000000000000p-19"
    assert naive.hex() == "0x1.0000000000000p-19"
    assert math.fsum(values).hex() == "0x1.0c6f7a0b5ed8dp-19"
    assert len({observed.hex(), naive.hex(), math.fsum(values).hex()}) == 3


def test_r2_float_mean_is_kahan_sum_over_count() -> None:
    """R2: bit-pattern differential, plus a witness where sum-then-divide and a running mean differ
    in the last bit."""
    content = b"region,revenue\none,1000000000.0\none,0.000001\none,0.000001\none,-1000000000.0\n"
    result = _aggregate_verdict(content, "mean")
    assert isinstance(result, Verified)
    assert result.table.y[0].hex() == "0x1.1000000000000p-21"

    running = 0.0
    for count, value in enumerate((1_000_000_000.0, 0.000001, 0.000001, -1_000_000_000.0), 1):
        running += (value - running) / count
    assert running.hex() == "0x1.0000000000000p-21"


def test_r3_int_mean_casts_before_summing(monkeypatch: pytest.MonkeyPatch) -> None:
    """R3: MEASURED witness `[2**53, 1, 0]` — pandas `mean` is `0x1.5555555555555p+51`, exact-then-
    divide is `0x1.5555555555556p+51`. Both pinned as hex-float literals; the implementation returns
    pandas'. A mutant computing the exact integer mean goes red here alone. Int64 `sum` stays int64
    and exact.

    The `sum` half is pinned INSIDE the profile, where the claim is true: C10 bounds each cell to
    int32 and `max_table_rows` bounds the count, so every admitted integer sum stays under 2**48 and
    float64 carries it exactly. `PlottedTable.y` is `tuple[float, ...]`, so "stays int64" is a claim
    about the retained DTYPE that B3 and B4 read, not about the table's storage type."""

    def unprofiled_float(text: str) -> float:
        """C10's cell bound withdrawn, and nothing else. `column_dtype` reads TEXT, so the dtype
        the reduction sees is unchanged."""
        return float(text)

    content = b"region,revenue\none,9007199254740992\none,1\none,0\n"
    with monkeypatch.context() as patch:
        patch.setattr(csvread_module, "_numeric_value", unprofiled_float)
        mean = _aggregate_verdict(content, "mean", mark="line")

    assert isinstance(mean, Verified)
    assert mean.table.y[0].hex() == "0x1.5555555555555p+51"
    assert float((2**53 + 1) / 3).hex() == "0x1.5555555555556p+51"

    total = _aggregate_verdict(b"region,revenue\none,2147483647\none,1\n", "sum", mark="line")
    assert isinstance(total, Verified)
    assert total.table.y[0] == 2147483648.0
    assert total.table.y[0].hex() == "0x1.0000000000000p+31"


def test_r4_extrema_keep_the_first_tied_value_bits(monkeypatch: pytest.MonkeyPatch) -> None:
    """R4: `[-0.0, +0.0]` gives `-0.0` for both `min` and `max`; reversed gives `+0.0`. Compared as
    bit patterns, since `-0.0 == +0.0`. Unreachable under C10 today and pinned anyway, because the
    profile is what makes it unreachable and the profile is what a later unit widens."""

    def unprofiled_float(text: str) -> float:
        return float(text)

    witnesses = (
        (b"region,revenue\none,-0.0\none,0.0\n", b"\x80\x00\x00\x00\x00\x00\x00\x00"),
        (b"region,revenue\none,0.0\none,-0.0\n", b"\x00\x00\x00\x00\x00\x00\x00\x00"),
    )
    with monkeypatch.context() as patch:
        patch.setattr(csvread_module, "_numeric_value", unprofiled_float)
        for content, expected_bits in witnesses:
            for reduction in ("min", "max"):
                result = _aggregate_verdict(content, reduction, mark="line")
                assert isinstance(result, Verified), (content, reduction)
                assert struct.pack(">d", result.table.y[0]) == expected_bits, (content, reduction)


def test_r5_int_sum_overflow_is_unreachable_under_the_profile() -> None:
    """R5: computes the worst-case magnitude from C10's range and `max_table_rows` and asserts it
    below 2**63. A mutant raising `max_table_rows` past that point makes this go red. pandas WRAPS
    on overflow (`[2**63-1, 1]` -> `-2**63`); the implementation asserts the bound instead."""
    largest_positive_sum = (2**31 - 1) * DEFAULT_LIMITS.max_table_rows
    largest_negative_magnitude = 2**31 * DEFAULT_LIMITS.max_table_rows
    assert max(largest_positive_sum, largest_negative_magnitude) < 2**63


# Hand-stated, never read from `csvread.NA_SPELLINGS`: cases derived from the production allowlist
# delete themselves with the member they were meant to pin, so removing a spelling would leave R6
# green over a set that no longer covers it. The equality assertion below is the widening half.
_NA_SPELLINGS = (
    "",
    "#N/A",
    "#N/A N/A",
    "#NA",
    "-1.#IND",
    "-1.#QNAN",
    "-NaN",
    "-nan",
    "1.#IND",
    "1.#QNAN",
    "<NA>",
    "N/A",
    "NA",
    "NULL",
    "NaN",
    "None",
    "n/a",
    "nan",
    "null",
)


def test_r6_nan_never_reaches_a_reduction(monkeypatch: pytest.MonkeyPatch) -> None:
    """R6: every NA spelling refuses `value_not_in_profile` ahead of the reduction, with a
    call-counting bomb on the reduction proving it never runs. So pandas' NaN-skipping arm and its
    compensation reset are both unreachable and neither is implemented — an unreachable branch would
    fail the 100% branch gate. A profile widening that admits NaN must add both arms.

    The 19 spellings are hand-stated here and the production set is asserted EQUAL to them, so a
    deletion and an addition both go red; iterating `csvread.NA_SPELLINGS` would pin neither."""
    assert frozenset(_NA_SPELLINGS) == csvread_module.NA_SPELLINGS
    calls = 0

    def reduction_input_bomb(_text: str) -> float:
        nonlocal calls
        calls += 1
        message = "an NA cell reached numeric conversion before reduction"
        raise AssertionError(message)

    with monkeypatch.context() as patch:
        patch.setattr(csvread_module, "_numeric_value", reduction_input_bomb)
        for spelling in _NA_SPELLINGS:
            for cell in (spelling, f'"{spelling}"'):
                content = f"region,revenue\none,{cell}\n".encode()
                result = _aggregate_verdict(content, "sum")
                assert isinstance(result, Refused), (spelling, cell)
                assert result.code == "value_not_in_profile", (spelling, cell)
    assert calls == 0


def test_r7_group_keys_sort_by_code_point() -> None:
    """R7: sorted-order differential against pandas over a key corpus separating the candidates —
    mixed case, digits vs letters, embedded spaces, non-ASCII, strings differing only past a common
    prefix. A locale-collator mutant and a file-order mutant each go red. MEASURED identical under
    C, C.utf8 and en_US.utf8, with an en_US collation control ordering differently."""
    keys = ("é", "a b", "2", "prefixい", "A", "ä", "a  a", "10", "z", "prefixあ", "a")
    content = "region,revenue\n" + "".join(f"{key},1\n" for key in keys)
    result = _aggregate_verdict(content.encode(), "sum")
    assert isinstance(result, Verified)
    assert result.table.x == (
        "10",
        "2",
        "A",
        "a",
        "a  a",
        "a b",
        "prefixあ",
        "prefixい",
        "z",
        "ä",
        "é",
    )


def test_r8_key_dtype_decides_before_key_order() -> None:
    """R8: witness pair — a key column of numeric-looking strings orders differently from one whose
    cells are all numeric. `['2', 'a', '10', '2']` groups to `['10', '2', 'a']`."""
    numeric = _aggregate_verdict(b"region,revenue\n2,1\n10,1\n2,1\n", "sum")
    textual = _aggregate_verdict(b"region,revenue\n2,1\na,1\n10,1\n2,1\n", "sum")
    assert isinstance(numeric, Verified)
    assert isinstance(textual, Verified)
    assert numeric.table.x == (2.0, 10.0)
    assert textual.table.x == ("10", "2", "a")


def test_r9_rows_keep_file_order_inside_a_group() -> None:
    """R9: a CSV whose rows for one key are not in value order sums in file order; a mutant sorting
    within the group goes red. This is what makes R1's ordered Kahan well defined."""
    content = b"region,revenue\none,1000000000.0\none,-1000000000.0\none,0.000001\none,0.000002\n"
    result = _aggregate_verdict(content, "sum")
    assert isinstance(result, Verified)
    assert result.table.y[0].hex() == "0x1.92a737110e454p-19"
    sorted_within_group = (-1_000_000_000.0, 0.000001, 0.000002, 1_000_000_000.0)
    total = compensation = 0.0
    for value in sorted_within_group:
        corrected = value - compensation
        next_total = total + corrected
        compensation = (next_total - total) - corrected
        total = next_total
    assert total.hex() == "0x1.9000000000000p-19"


def test_r10_group_count_is_bounded_and_charged() -> None:
    """R10: boundary witnesses at `max_groups` and `max_groups + 1`, the second refusing
    `work_budget_exceeded`; a budget bomb asserts the per-row and per-group charge happens."""
    two_groups = b"region,revenue\na,1\nb,2\na,3\n"
    at_boundary = _aggregate_verdict(
        two_groups,
        "sum",
        limits=replace(DEFAULT_LIMITS, max_groups=2, max_work=17),
    )
    one_charge_short = _aggregate_verdict(
        two_groups,
        "sum",
        limits=replace(DEFAULT_LIMITS, max_groups=2, max_work=16),
    )
    assert isinstance(at_boundary, Verified)
    assert isinstance(one_charge_short, Refused)
    assert one_charge_short.code == "work_budget_exceeded"

    too_many = _aggregate_verdict(
        b"region,revenue\na,1\nb,2\nc,3\n",
        "sum",
        limits=replace(DEFAULT_LIMITS, max_groups=2),
    )
    assert isinstance(too_many, Refused)
    assert too_many.code == "work_budget_exceeded"


# --- B: `barh` and the aggregate profile bound -------------------------------


def test_b1_barh_joins_the_mark_vocabulary_with_bar_argument_order() -> None:
    """B1: `get_args(DatasetMark.__value__)` pinned as the exact literal tuple
    `("line", "scatter", "bar", "barh")`; `plt.barh(g.index, g.values)` puts the key in x and the
    reduced column in y, the same as `bar`."""
    assert get_args(spec.DatasetMark.__value__) == ("line", "scatter", "bar", "barh")
    horizontal = project(parse_admitted(_aggregate_source("sum", mark="barh")))
    vertical = project(parse_admitted(_aggregate_source("sum", mark="bar")))
    assert isinstance(horizontal, spec.DatasetPlot)
    assert isinstance(vertical, spec.DatasetPlot)
    assert horizontal.mark == "barh"
    assert (horizontal.x, horizontal.y, horizontal.group) == (
        vertical.x,
        vertical.y,
        vertical.group,
    )


def test_b2_barh_carries_bar_integrity_rules() -> None:
    """B2: a duplicate-category `barh` refuses `category_not_unique`. The `match` in
    `_dataset_integrity` is closed over the widened vocabulary, so a missing arm fails
    `mypy --strict` rather than passing silently."""
    source = _dataset_source('plt.barh(df["region"], df["revenue"])\nplt.show()\n')
    result = verify_python_source(
        source,
        declared_target=spec.DatasetTarget(path="sales.csv", content=b"region,revenue\na,1\na,2\n"),
    )
    assert isinstance(result, Refused)
    assert result.code == "category_not_unique"


def test_b3_integer_aggregate_is_bounded_after_aggregation() -> None:
    """B3: two cells at `2147483647` summing to `4294967294` refuse `value_not_in_profile` under
    `bar` and under `barh`; the identical sum under `scatter` or `line` verifies; the negative bound
    carries its own witness at `-4294967296`. A mutant bounding only cells goes red on the first.
    MEASURED: both Pyodide builds raise `OverflowError: Python int too large to convert to C long`
    for bar and barh, while in-int32 controls render."""
    for content in (
        b"region,revenue\n1,2147483647\n1,2147483647\n",
        b"region,revenue\n1,-2147483648\n1,-2147483648\n",
    ):
        for mark in ("bar", "barh"):
            result = _aggregate_verdict(content, "sum", mark=mark)
            assert isinstance(result, Refused), (content, mark)
            assert result.code == "value_not_in_profile", (content, mark)
        for mark in ("scatter", "line"):
            result = _aggregate_verdict(content, "sum", mark=mark)
            assert isinstance(result, Verified), (content, mark)


def test_b4_reductions_retain_dtype(monkeypatch: pytest.MonkeyPatch) -> None:
    """B4: witness matrix over (int, float) x (sum, mean, min, max) asserting which combinations B3
    binds. The int-`mean` cell distinguishes dtype retention from a blanket bound — it is float64 by
    R3 and never reaches the renderer's integer branch, so a mutant bounding every aggregate goes
    red there.

    The patch withdraws C10's cell bound so an out-of-int32 magnitude reaches the reduction at all.
    It returns `float` for every cell, matching `_numeric_value`'s own type: the dtype under test
    comes from `column_dtype`, which reads the raw TEXT."""

    def unprofiled_float(text: str) -> float:
        return float(text)

    with monkeypatch.context() as patch:
        patch.setattr(csvread_module, "_numeric_value", unprofiled_float)
        for dtype, content in (
            ("int", b"region,revenue\n1,2147483648\n"),
            ("float", b"region,revenue\n1,2147483648.0\n"),
        ):
            for reduction in ("sum", "mean", "min", "max"):
                result = _aggregate_verdict(content, reduction)
                bounded = dtype == "int" and reduction != "mean"
                if bounded:
                    assert isinstance(result, Refused), (dtype, reduction)
                    assert result.code == "value_not_in_profile", (dtype, reduction)
                else:
                    assert isinstance(result, Verified), (dtype, reduction)


# --- G + K: integrity and the published sentence -----------------------------


def test_g11_per_group_counts_are_published() -> None:
    """G11: certificate byte-pin for one aggregate of each reduction, carrying the group count and
    each group's member count. A mutant dropping the counts goes red.

    The member counts are published as `CoreCertificate.group_counts`, aligned with `table.x`; the
    sentence carries the group count and the row count. The split is what keeps the one string a
    clinician reads readable: `max_groups` admits 1,000 groups, and a sentence that grows with the
    group count is no longer a one-glance sentence. An ungrouped plot publishes `None` rather than
    an empty tuple — "this figure draws no groups" and "this figure draws zero groups" differ."""
    content = b"region,revenue\nwest,1\neast,2\nwest,3\n"
    for reduction in ("sum", "mean", "min", "max"):
        result = _aggregate_verdict(content, reduction)
        assert isinstance(result, Verified), reduction
        assert result.table.x == ("east", "west"), reduction
        assert result.certificate.group_counts == (1, 2), reduction
        assert "The chart draws 2 groups from 3 rows." in result.certificate.interpretation

    pair = verify_python_source(
        _dataset_source('plt.bar(df["region"], df["revenue"])\nplt.show()\n'),
        declared_target=spec.DatasetTarget(
            path="sales.csv", content=b"region,revenue\nwest,1\neast,2\n"
        ),
    )
    assert isinstance(pair, Verified)
    assert pair.certificate.group_counts is None


def test_g78r_group_counts_sum_to_the_data_row_count() -> None:
    """G78r: for every aggregate, the summed per-group counts equal the CSV's data-row count. A
    `groupby` drops no row — every row joins exactly one group — which is what keeps G7's range
    claim and G8's ROW COVERAGE unconditional while aggregation is admitted. Coverage, not
    point-count equality: these 6 rows draw 3 points."""
    content = b"region,revenue\na,1\nc,2\na,3\nb,4\nc,5\nc,6\n"
    expected_counts = (2, 1, 3)
    assert sum(expected_counts) == 6
    for reduction in ("sum", "mean", "min", "max"):
        result = _aggregate_verdict(content, reduction)
        assert isinstance(result, Verified), reduction
        counts = result.certificate.group_counts
        assert counts is not None, reduction
        assert counts == expected_counts, reduction
        assert sum(counts) == 6, reduction
        assert len(counts) == len(result.table.x), reduction
        assert "The chart draws 3 groups from 6 rows." in result.certificate.interpretation


def test_g9r_line_over_a_group_key_verifies_in_sorted_order() -> None:
    """G9r: a line over a group key verifies, and its table rows are in sorted key order. A
    column-pair line still plots in FILE order — the pin that stops the restatement leaking into the
    non-aggregate path."""
    content = b"region,revenue\nb,1\na,2\nc,3\n"
    aggregate = _aggregate_verdict(content, "sum", mark="line")
    raw_source = _dataset_source('plt.plot(df["region"], df["revenue"])\nplt.show()\n')
    raw = verify_python_source(
        raw_source,
        declared_target=spec.DatasetTarget(path="sales.csv", content=content),
    )
    assert isinstance(aggregate, Verified)
    assert isinstance(raw, Verified)
    assert aggregate.table.x == ("a", "b", "c")
    assert raw.table.x == ("b", "a", "c")


def test_k1_aggregate_interpretation_is_byte_pinned() -> None:
    """K1: the aggregate interpretation, byte-pinned per reduction and hand-stated here.

    The contract's K1 row prints `sum of revenue grouped by region · 2 groups · 6 rows` as its
    example. That fragment is superseded by M13.5's K6 ruling, which fixes this field's sentence
    sequence and binds it to ASD-STE100: `interpretation` is the one core string a clinician reads,
    and `·`-joined notation is the agent register K1's own human-facing clause excludes. Every fact
    K1 names is present — the reduction, the aggregated column, the group key, the group count and
    the row count. The reduction words are hand-stated, since `min` reads as `minimum`."""
    content = b"region,revenue\nwest,1\neast,2\nwest,3\neast,4\nwest,5\neast,6\n"
    words = {"sum": "sum", "mean": "mean", "min": "minimum", "max": "maximum"}
    for reduction, word in words.items():
        result = _aggregate_verdict(content, reduction)
        assert isinstance(result, Verified), reduction
        assert result.certificate.interpretation == (
            'Chart type: bar. The data comes from the file "sales.csv". '
            'X shows the groups of the column "region". '
            f'Y shows the {word} of the column "revenue" in each group. '
            "The chart draws 2 groups from 6 rows. "
            "Numbers follow the profile binary64-libm-v1."
        ), reduction


def test_k2_column_pair_interpretation_is_unchanged() -> None:
    """K2: sha256 pin on the M13.4 column-pair certificate text. `assurance.md` requires
    byte-pinning the unchanged mode whenever a shared message splits by mode."""
    source = _dataset_source('plt.bar(df["region"], df["revenue"])\nplt.show()\n')
    result = verify_python_source(
        source,
        declared_target=spec.DatasetTarget(
            path="sales.csv",
            content=b"region,revenue\nnorth,1\nsouth,2\neast,3\nwest,4\n",
        ),
    )
    assert isinstance(result, Verified)
    digest = hashlib.sha256(result.certificate.interpretation.encode()).hexdigest()
    assert digest == "66491b269ccf2f9db232b6fe020e1b140c8ea20b352dbdcd279cf2d7c5345255"


def test_k3_cosmetic_fields_stay_out_of_the_sentence() -> None:
    """K3: two programs differing only in `figsize` have byte-identical interpretations and UNEQUAL
    specs. A figure size is not something the figure says about its data."""
    body = 'g = df.groupby("region")["revenue"].sum()\nplt.bar(g.index, g.values)\nplt.show()\n'
    plain_source = _dataset_source(body)
    sized_source = _dataset_source("plt.figure(figsize=(10, 6))\n" + body)
    target = spec.DatasetTarget(
        path="sales.csv", content=b"region,revenue\nwest,1\neast,2\nwest,3\n"
    )
    plain = verify_python_source(plain_source, declared_target=target)
    sized = verify_python_source(sized_source, declared_target=target)
    assert isinstance(plain, Verified)
    assert isinstance(sized, Verified)
    assert plain.spec != sized.spec
    assert plain.certificate.interpretation == sized.certificate.interpretation


def test_k1r_barh_interpretation_names_the_rendered_axes() -> None:
    """K1, re-pinned by the closing review: the sentence names the axis a reader is looking at.

    `plt.barh(y, width)` puts its first positional on the VERTICAL axis, so a `barh` certificate
    that says `X shows the groups` describes a chart nobody drew. The axis letters are a closed map
    on `DatasetMark`, hand-stated here so a fifth mark cannot inherit a default. Acceptance: the
    four marks' letter pairs are exactly as listed, and a live `barh` certificate reads `Y shows
    the groups` with the magnitude on X."""
    assert _AXIS_LETTERS == {
        "line": ("X", "Y"),
        "scatter": ("X", "Y"),
        "bar": ("X", "Y"),
        "barh": ("Y", "X"),
    }
    assert set(_AXIS_LETTERS) == set(get_args(spec.DatasetMark.__value__))
    target = spec.DatasetTarget(
        path="sales.csv", content=b"region,revenue\nwest,1\neast,2\nwest,3\n"
    )
    body = 'g = df.groupby("region")["revenue"].sum()\n'
    horizontal = verify_python_source(
        _dataset_source(body + "plt.barh(g.index, g.values)\nplt.show()\n"), declared_target=target
    )
    assert isinstance(horizontal, Verified)
    assert horizontal.certificate.interpretation == (
        'Chart type: barh. The data comes from the file "sales.csv". '
        'Y shows the groups of the column "region". '
        'X shows the sum of the column "revenue" in each group. '
        "The chart draws 2 groups from 3 rows. "
        "Numbers follow the profile binary64-libm-v1."
    )
    # The ungrouped sentence swaps too, and it needs unique categories: a repeated bar category
    # overplots, which is what G8 refuses as `category_not_unique`.
    flat = verify_python_source(
        _dataset_source('plt.barh(df["region"], df["revenue"])\nplt.show()\n'),
        declared_target=spec.DatasetTarget(
            path="sales.csv", content=b"region,revenue\nwest,1\neast,2\nnorth,3\n"
        ),
    )
    assert isinstance(flat, Verified)
    assert flat.certificate.interpretation == (
        'Chart type: barh. The data comes from the file "sales.csv". '
        'Y shows the column "region". X shows the column "revenue". '
        "The chart draws 3 rows. Numbers follow the profile binary64-libm-v1."
    )


def test_g11r_certify_refuses_a_grouped_spec_without_its_counts() -> None:
    """G11, re-pinned by the closing review: the counts are REQUIRED, not merely accepted.

    `certify`'s grouped branch once read `spec.group is None or group_counts is None`, so a grouped
    spec whose counts were absent fell through to the ungrouped sentence and shipped a certificate
    with `group_counts=None` for an aggregate figure. That is the catch-all-over-a-variant-space
    class, and it turns G11's guarantee into a convention the callers happen to keep. Both
    directions of the disagreement are a CALLER fault, so both raise `PysrcCallerError` rather than
    refusing. Acceptance: grouped-without-counts raises, ungrouped-with-counts raises, and both
    agreeing shapes still certify."""
    table = PlottedTable(x=("east", "west"), y=(2.0, 4.0))
    grouped = spec.DatasetPlot(
        mark="bar",
        source=spec.DatasetRef("sales.csv"),
        x=spec.Column("region"),
        y=spec.Column("revenue"),
        labels=spec.Labels(),
        group="sum",
    )
    ungrouped = replace(grouped, group=None)
    target = spec.DatasetTarget(path="sales.csv", content=b"region,revenue\nwest,1\neast,2\n")
    with pytest.raises(PysrcCallerError):
        certify(grouped, table, b"", target, None)
    with pytest.raises(PysrcCallerError):
        certify(ungrouped, table, b"", target, (1, 1))
    assert certify(grouped, table, b"", target, (1, 1)).group_counts == (1, 1)
    assert certify(ungrouped, table, b"", target, None).group_counts is None


# --- D + S: the committed demo dataset (M13.7b) ------------------------------


def test_d1_the_committed_sales_csv_verifies_grouped() -> None:
    """D1: a grouped program over the COMMITTED `data/sales.csv` bytes verifies, with
    `table.x == ("EU", "NAM")` and `group_counts == (3, 3)`. This is M13.7b's whole point: the
    region code was `NA`, one of the 19 pandas NA spellings, so the exactly-admitted groupby
    program refused `value_not_in_profile` and six held-out simple rows were unreachable. It reads
    the real committed bytes rather than a fixture, so it goes red again the moment an NA spelling
    reappears in a column this program SELECTS -- `region` or `revenue`. `read_columns` profiles the
    selected indices alone, so an NA cell in `month` or `orders` cannot reach the figure and does
    not refuse; the scope is the mark's own columns, which is the scope that decides the chart."""
    content = (_ROOT / "data" / "sales.csv").read_bytes()
    result = _aggregate_verdict(content, "sum")
    assert isinstance(result, Verified)
    assert result.table.x == ("EU", "NAM")
    assert result.certificate.group_counts == (3, 3)


def test_s2_an_na_group_key_refuses_value_not_in_profile() -> None:
    """S2: `verify_python_source` over a grouped program whose KEY column holds `NA` refuses
    `value_not_in_profile`. R6 sweeps all 19 spellings through the VALUE column; the key column is
    a separate path and it is the one `data/sales.csv` used to exercise. Banked here because the
    corpus gave the case up: it goes red if the profile ever stops refusing a key-column NA."""
    result = _aggregate_verdict(b"region,revenue\nNA,1\nEU,2\nNA,3\n", "sum")
    assert isinstance(result, Refused)
    assert result.code == "value_not_in_profile"
