# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Diff-blind red suite for M13.4 dataset-arm projection.

Contract: `.agent/contracts/m13u4.md`. Each test names ONE predicate and its docstring carries that
predicate's acceptance check verbatim, so a red states which ruling it defends.
"""

import ast
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, cast, get_args

import pytest

from verifier.pysrc import spec
from verifier.pysrc.admit import ADMITTED_CALL_TARGETS, ADMITTED_KEYWORDS, parse_admitted
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.project import project


def test_d1_arm_selection_is_closed() -> None:
    """D1: a pandas import selects the dataset arm, a grid call the formula arm.

    Accept: a program importing pandas AND using `np.linspace` refuses `arm_ambiguous`; no `else:`
    tail picks an arm.
    """
    ambiguous = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("sales.csv")\n'
        "x = np.linspace(0, 1, num=5)\n"
        "y = np.sin(x)\n"
        "plt.plot(x, y)\n"
        "plt.show()\n"
    )
    with pytest.raises(PysrcRefusalError) as caught_ambiguous:
        project(parse_admitted(ambiguous))
    assert str(caught_ambiguous.value.code) == "arm_ambiguous"

    no_mark = "import matplotlib.pyplot as plt\nplt.show()\n"
    with pytest.raises(PysrcRefusalError) as caught_no_mark:
        project(parse_admitted(no_mark))
    assert str(caught_no_mark.value.code) == "no_mark"

    no_grid = "import matplotlib.pyplot as plt\nplt.plot(1, 2)\nplt.show()\n"
    with pytest.raises(PysrcRefusalError) as caught_no_grid:
        project(parse_admitted(no_grid))
    assert str(caught_no_grid.value.code) == "x_not_a_grid"


def test_d2_exactly_one_source() -> None:
    """D2: exactly one `read_csv`, bound to exactly one name.

    Accept: two `read_csv` assignments refuse `multiple_sources`; zero in the dataset arm, with a
    mark present, refuses `no_source`. A program with NEITHER refuses `no_mark` in both arms.
    Bound to exactly one name covers both bindings this arm adds: rebinding a frame OR a column
    name refuses `name_rebound`, which outranks the source count because it is statement-local.
    """
    multiple = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'first = pd.read_csv("first.csv")\n'
        'second = pd.read_csv("second.csv")\n'
        'plt.plot(first["x"], first["y"])\n'
        "plt.show()\n"
    )
    with pytest.raises(PysrcRefusalError) as caught_multiple:
        project(parse_admitted(multiple))
    assert str(caught_multiple.value.code) == "multiple_sources"

    missing = "import pandas as pd\nimport matplotlib.pyplot as plt\nplt.plot(1, 2)\nplt.show()\n"
    with pytest.raises(PysrcRefusalError) as caught_missing:
        project(parse_admitted(missing))
    assert str(caught_missing.value.code) == "no_source"

    # Neither mark nor source: one defect, one code, in both arms. Splitting the empty program's
    # answer on an unrelated import would report two codes for the same fault.
    nothing = "import pandas as pd\nimport matplotlib.pyplot as plt\nplt.show()\n"
    with pytest.raises(PysrcRefusalError) as caught_nothing:
        project(parse_admitted(nothing))
    assert str(caught_nothing.value.code) == "no_mark"

    rebound_frame = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("first.csv")\n'
        'df = pd.read_csv("second.csv")\n'
        'plt.plot(df["x"], df["y"])\n'
        "plt.show()\n"
    )
    assert _refusal_code(rebound_frame) == "name_rebound"

    rebound_column = _dataset_source('x = df["a"]\nx = df["b"]\nplt.plot(x, df["c"])\nplt.show()\n')
    assert _refusal_code(rebound_column) == "name_rebound"


def test_d3_source_argument_is_a_string_literal() -> None:
    """D3: the `read_csv` argument is a single positional string literal.

    Accept: a bound name and an extra positional argument refuse `source_not_literal`; a keyword
    form refuses `keyword_not_admitted`; an f-string refuses `expression_not_admitted`.
    """
    prelude = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
    tail = 'plt.plot(df["x"], df["y"])\nplt.show()\n'
    invalid_sources = (
        'p = "a.csv"\ndf = pd.read_csv(p)\n',
        "df = pd.read_csv()\n",
        'df = pd.read_csv("a.csv", ";")\n',
        # A literal of the wrong type: admitted as an expression, refused as a path.
        "df = pd.read_csv(1)\n",
    )
    for source in invalid_sources:
        with pytest.raises(PysrcRefusalError) as caught:
            project(parse_admitted(prelude + source + tail))
        assert str(caught.value.code) == "source_not_literal"

    with pytest.raises(PysrcRefusalError) as caught_keyword:
        project(parse_admitted(prelude + 'df = pd.read_csv("a.csv", sep=";")\n' + tail))
    assert str(caught_keyword.value.code) == "keyword_not_admitted"

    f_string = 'n = 1\ndf = pd.read_csv(f"{n}.csv")\n'
    with pytest.raises(PysrcRefusalError) as caught_f_string:
        project(parse_admitted(prelude + f_string + tail))
    assert str(caught_f_string.value.code) == "expression_not_admitted"

    for target in ("read_table", "read_excel"):
        with pytest.raises(PysrcRefusalError) as caught_target:
            parse_admitted(prelude + f'df = pd.{target}("a.csv")\n' + tail)
        assert str(caught_target.value.code) == "call_target_not_admitted"


def _dataset_source(body: str, path: str = "sales.csv") -> str:
    return (
        f'import pandas as pd\nimport matplotlib.pyplot as plt\ndf = pd.read_csv("{path}")\n{body}'
    )


def _refusal_code(source: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        project(parse_admitted(source))
    return str(caught.value.code)


def test_d4_column_reference_shape() -> None:
    """D4: a column is `<bound frame>["<string literal>"]`.

    Accept: `df[c]` refuses `column_not_literal`; `other["a"]` refuses `column_not_from_source`.
    """
    bound_index = _dataset_source('c = "x"\nplt.plot(df[c], df["y"])\nplt.show()\n')
    other_frame = _dataset_source('other = 0\nplt.plot(other["x"], df["y"])\nplt.show()\n')
    assert _refusal_code(bound_index) == "column_not_literal"
    assert _refusal_code(other_frame) == "column_not_from_source"

    unbound_base = _dataset_source('plt.plot(missing["x"], df["y"])\nplt.show()\n')
    assert _refusal_code(unbound_base) == "name_not_bound"

    # Neither a subscript nor a name bound to one: the channel names no column at all.
    literal_channel = _dataset_source('plt.plot(1, df["y"])\nplt.show()\n')
    assert _refusal_code(literal_channel) == "column_not_from_source"

    near_misses = (
        'plt.plot(df.loc["x"], df["y"])\nplt.show()\n',
        'plt.plot(df.iloc[0], df["y"])\nplt.show()\n',
        'plt.plot(df[0:1], df["y"])\nplt.show()\n',
        'plt.plot(df["x", "z"], df["y"])\nplt.show()\n',
        'plt.plot(df.x, df["y"])\nplt.show()\n',
    )
    for body in near_misses:
        with pytest.raises(PysrcRefusalError):
            project(parse_admitted(_dataset_source(body)))


def test_d5_both_channels_share_one_frame() -> None:
    """D5: both mark channels are columns of the SAME bound frame.

    Accept: `plt.scatter(df["a"], other["b"])` refuses `column_not_from_source`.
    """
    wrong_y = _dataset_source('other = 0\nplt.scatter(df["a"], other["b"])\nplt.show()\n')
    wrong_x = _dataset_source('other = 0\nplt.scatter(other["a"], df["b"])\nplt.show()\n')
    assert _refusal_code(wrong_y) == "column_not_from_source"
    assert _refusal_code(wrong_x) == "column_not_from_source"

    projected = project(
        parse_admitted(_dataset_source('plt.scatter(df["a"], df["b"])\nplt.show()\n'))
    )
    assert isinstance(projected, spec.DatasetPlot)


def test_d6_dataset_mark_admits_bar() -> None:
    """D6: `DatasetMark` is line | scatter | bar; bar is VALID in this arm.

    Accept: `plt.bar(df["region"], df["revenue"])` projects with `mark == "bar"`.
    """
    assert set(get_args(spec.DatasetMark.__value__)) == {"line", "scatter", "bar"}

    marks = {"plot": "line", "scatter": "scatter", "bar": "bar"}
    for target, expected in marks.items():
        source = _dataset_source(f'plt.{target}(df["region"], df["revenue"])\nplt.show()\n')
        projected = project(parse_admitted(source))
        assert isinstance(projected, spec.DatasetPlot)
        assert projected.mark == expected

    for target in ("step", "barh", "hist"):
        source = _dataset_source(f'plt.{target}(df["region"], df["revenue"])\nplt.show()\n')
        assert _refusal_code(source) == "call_target_not_admitted"


def test_d7_exactly_one_mark() -> None:
    """D7: exactly one mark call, refusal precedence LOCAL before GLOBAL.

    Accept: two marks refuse `multiple_marks`.
    """
    two_marks = _dataset_source(
        'plt.plot(df["a"], df["b"])\nplt.scatter(df["a"], df["b"])\nplt.show()\n'
    )
    assert _refusal_code(two_marks) == "multiple_marks"

    local_fault = _dataset_source(
        'c = "b"\nplt.plot(df["a"], df["b"])\nplt.scatter(df["a"], df[c])\nplt.show()\n'
    )
    assert _refusal_code(local_fault) == "column_not_literal"

    formula_local_fault = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "x = np.arange(3)\n"
        "y = np.sin(x)\n"
        "plt.plot(x, y)\n"
        "plt.bar(x, y)\n"
        "plt.show()\n"
    )
    assert _refusal_code(formula_local_fault) == "mark_not_valid_for_arm"


def test_d8_labels_match_the_formula_arm() -> None:
    """D8: decorations project to the same `Labels` record as the formula arm.

    Accept: a non-string-literal argument refuses `label_not_literal`.
    """
    decorations = (
        'plt.title("title")\n'
        'plt.xlabel("x label")\n'
        'plt.ylabel("y label")\n'
        "plt.legend()\n"
        "plt.grid(True)\n"
        "plt.show()\n"
    )
    dataset = project(
        parse_admitted(
            _dataset_source('plt.plot(df["x"], df["y"], label="series")\n' + decorations)
        )
    )
    formula = project(
        parse_admitted(
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "x = np.arange(3)\n"
            "y = np.sin(x)\n"
            'plt.plot(x, y, label="series")\n' + decorations
        )
    )
    assert isinstance(dataset, spec.DatasetPlot)
    assert isinstance(formula, spec.FormulaPlot)
    assert dataset.labels == formula.labels

    non_literal = _dataset_source('plt.plot(df["x"], df["y"])\nplt.title(df)\nplt.show()\n')
    assert _refusal_code(non_literal) == "label_not_literal"


def test_d9_terminal_show_is_last() -> None:
    """D9: exactly one `plt.show()`, and it is final.

    Accept: zero refuses `no_terminal`; a non-final one refuses `statement_after_terminal`.
    """
    mark = 'plt.plot(df["x"], df["y"])\n'
    valid = project(parse_admitted(_dataset_source(mark + "plt.show()\n")))
    assert isinstance(valid, spec.DatasetPlot)
    assert _refusal_code(_dataset_source(mark)) == "no_terminal"
    assert (
        _refusal_code(_dataset_source(mark + 'plt.show()\nplt.title("late")\n'))
        == "statement_after_terminal"
    )
    assert (
        _refusal_code(_dataset_source(mark + "plt.show()\nplt.show()\n"))
        == "statement_after_terminal"
    )


def test_d10_total_statement_coverage() -> None:
    """D10: every admitted statement contributes to the returned spec.

    Accept: an unused column assignment refuses `statement_not_projected`.
    """
    consumed = _dataset_source('x = df["region"]\ny = df["revenue"]\nplt.bar(x, y)\nplt.show()\n')
    assert isinstance(project(parse_admitted(consumed)), spec.DatasetPlot)

    unused = _dataset_source(
        'unused = df["margin"]\nx = df["region"]\ny = df["revenue"]\nplt.bar(x, y)\nplt.show()\n'
    )
    assert _refusal_code(unused) == "statement_not_projected"


def _walk_nodes(value: object) -> Iterator[object]:
    yield value
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(cast(Any, value)):
            yield from _walk_nodes(getattr(value, item.name))
    elif isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            yield from _walk_nodes(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_nodes(item)


def test_d11_projection_is_pure() -> None:
    """D11: projection is a pure function of the tree, holding no `ast` node or source text.

    Accept: equality over two parses of the same bytes; a search test over `spec.py` for `ast.`.
    """
    source = _dataset_source(
        'x = df["region"]\n'
        'y = df["revenue"]\n'
        'plt.bar(x, y, label="sales")\n'
        'plt.title("Revenue")\n'
        "plt.show()\n"
    )
    first_tree = parse_admitted(source)
    second_tree = parse_admitted(source)
    shifted_tree = parse_admitted("\n" + source)
    first = project(first_tree)

    assert first == project(first_tree) == project(second_tree) == project(shifted_tree)
    nodes = tuple(_walk_nodes(first))
    assert not any(isinstance(node, ast.AST) for node in nodes)
    assert source not in nodes
    assert not any(
        isinstance(node, str) and ("import pandas as pd" in node or "plt.show()" in node)
        for node in nodes
    )
    field_names = {
        item.name
        for node in nodes
        if is_dataclass(node) and not isinstance(node, type)
        for item in fields(cast(Any, node))
    }
    assert field_names.isdisjoint(
        {"lineno", "end_lineno", "col_offset", "end_col_offset", "line_number", "source_text"}
    )

    spec_path = Path(spec.__file__)
    assert "ast." not in spec_path.read_text(encoding="utf-8")


def test_d12_core_plot_spec_union_is_exact() -> None:
    """D12: `CorePlotSpec` is EXACTLY `FormulaPlot | DatasetPlot`.

    Accept: `get_args(CorePlotSpec.__value__)` equals the hand-stated two-member tuple. A PEP-695
    alias needs `__value__` -- `get_args()` on the alias itself returns `()`.
    """
    assert get_args(spec.CorePlotSpec.__value__) == (spec.FormulaPlot, spec.DatasetPlot)


def test_g1_dataset_bar_baseline_holds_by_construction() -> None:
    """G1: axis limits stay unadmitted, so a dataset bar's baseline is at zero by construction.

    Accept: `plt.ylim(50, 100)` after a dataset bar refuses `call_target_not_admitted`.
    """
    axis_limits = {"plt.ylim", "plt.xlim"}
    assert not (axis_limits & ADMITTED_CALL_TARGETS)

    mark = 'plt.bar(df["region"], df["revenue"])\n'
    valid = project(parse_admitted(_dataset_source(mark + "plt.show()\n")))
    assert isinstance(valid, spec.DatasetPlot)
    assert valid.mark == "bar"

    limits = ("plt.ylim(50, 100)", "plt.xlim(0, 10)")
    for limit in limits:
        assert (
            _refusal_code(_dataset_source(mark + f"{limit}\nplt.show()\n"))
            == "call_target_not_admitted"
        )


def test_g5_bar_is_arm_dependent() -> None:
    """G5: the same `plt.bar` call is refused in the formula arm and admitted in the dataset arm.

    Accept: BOTH halves asserted in one test -- this row is also the unit's probe seed, so admitting
    bar in the formula arm must turn it red.
    """
    same_mark = "plt.bar(x, y)\n"
    formula = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "x = np.arange(3)\n"
        "y = np.sin(x)\n"
        f"{same_mark}"
        "plt.show()\n"
    )
    assert _refusal_code(formula) == "mark_not_valid_for_arm"

    dataset = _dataset_source(f'x = df["region"]\ny = df["revenue"]\n{same_mark}plt.show()\n')
    projected = project(parse_admitted(dataset))
    assert isinstance(projected, spec.DatasetPlot)
    assert projected.mark == "bar"


def test_g2_g3_g6_survive_the_widening() -> None:
    """G2/G3/G6: re-asserted against a DATASET program so the widening cannot silently delete them.

    Accept: `plt.twinx`, `plt.yscale` refuse `call_target_not_admitted`; `s=` on `plt.scatter`
    refuses `keyword_not_admitted`.
    """
    blocked_targets = {"plt.twinx", "plt.yscale"}
    assert not (blocked_targets & ADMITTED_CALL_TARGETS)
    assert ADMITTED_KEYWORDS["plt.scatter"] == frozenset({"label"})

    mark = 'plt.scatter(df["x"], df["y"])\n'
    blocked_calls = ("plt.twinx()", 'plt.yscale("log")')
    for call in blocked_calls:
        assert (
            _refusal_code(_dataset_source(mark + f"{call}\nplt.show()\n"))
            == "call_target_not_admitted"
        )

    sized = _dataset_source('plt.scatter(df["x"], df["y"], s=df["size"])\nplt.show()\n')
    assert _refusal_code(sized) == "keyword_not_admitted"
