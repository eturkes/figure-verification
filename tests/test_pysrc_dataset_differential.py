# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent M13.4 dataset projection anchors and differential."""

import ast
import importlib
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

import oracle_dataset as oracle_module
from oracle_dataset import (
    ChartLabels,
    CsvFile,
    DatasetChart,
    Field,
    OracleDatasetProjectionError,
    OraclePlotSpec,
)
from oracle_dataset import project as oracle_project
from oracle_project import FormulaPlot
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.errors import PysrcRefusalError

_DATASET_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_FORMULA_PRELUDE = "import numpy as np\nimport matplotlib.pyplot as plt\n"
_BAR = (
    _DATASET_PRELUDE
    + 'df = pd.read_csv("sales.csv")\n'
    + 'plt.bar(df["region"], df["revenue"])\n'
    + "plt.show()\n"
)
_PATHS = ("sales.csv", "clinical.csv", "患者データ.csv")
_COLUMNS = ("region", "revenue", "quarter", "患者数")
_FRAME_NAMES = ("df", "data", "table")
_MARK_CALLS = ("plot", "scatter", "bar")
_DECORATIONS = ("title", "xlabel", "ylabel", "legend")


@dataclass(frozen=True, slots=True)
class _RefusalCase:
    predicate: str
    source: str
    code: str


def _valid_source(  # noqa: PLR0913 — independent generated-program axes stay explicit
    *,
    path: str,
    frame: str,
    x_column: str,
    y_column: str,
    mark: str,
    binding_mode: str,
    label: str | None,
    decorations: frozenset[str],
    grid_decoration: str,
) -> str:
    lines = [f"{frame} = pd.read_csv({path!r})"]
    x_expression = f"{frame}[{x_column!r}]"
    y_expression = f"{frame}[{y_column!r}]"
    if binding_mode in {"both", "x"}:
        lines.append(f"x = {x_expression}")
        x_expression = "x"
    if binding_mode in {"both", "y"}:
        lines.append(f"y = {y_expression}")
        y_expression = "y"
    label_arg = "" if label is None else f", label={label!r}"
    lines.append(f"plt.{mark}({x_expression}, {y_expression}{label_arg})")
    if "title" in decorations:
        lines.append("plt.title('title')")
    if "xlabel" in decorations:
        lines.append("plt.xlabel('x axis')")
    if "ylabel" in decorations:
        lines.append("plt.ylabel('y axis')")
    if "legend" in decorations:
        lines.append("plt.legend()")
    if grid_decoration != "omit":
        argument = "" if grid_decoration == "toggle" else grid_decoration.title()
        lines.append(f"plt.grid({argument})")
    lines.append("plt.show()")
    return _DATASET_PRELUDE + "\n".join(lines) + "\n"


@st.composite
def _valid_sources(draw: DrawFn) -> str:
    decorations = draw(
        st.frozensets(st.sampled_from(_DECORATIONS), min_size=0, max_size=len(_DECORATIONS))
    )
    return _valid_source(
        path=draw(st.sampled_from(_PATHS)),
        frame=draw(st.sampled_from(_FRAME_NAMES)),
        x_column=draw(st.sampled_from(_COLUMNS)),
        y_column=draw(st.sampled_from(_COLUMNS)),
        mark=draw(st.sampled_from(_MARK_CALLS)),
        binding_mode=draw(st.sampled_from(["inline", "both", "x", "y"])),
        label=draw(st.sampled_from([None, "series", "系列"])),
        decorations=decorations,
        grid_decoration=draw(st.sampled_from(["omit", "toggle", "true", "false"])),
    )


_VALID_SOURCES: SearchStrategy[str] = _valid_sources()


@st.composite
def _projection_refusals(  # noqa: PLR0911 — closed D1-D10 witness dispatch
    draw: DrawFn,
) -> _RefusalCase:
    predicate = draw(st.sampled_from([1, 2, 3, 4, 5, 7, 8, 9, 10]))
    frame = draw(st.sampled_from(_FRAME_NAMES))
    path = draw(st.sampled_from(_PATHS))
    if predicate == 1:
        source = (
            _DATASET_PRELUDE
            + "import numpy as np\n"
            + f"{frame} = pd.read_csv({path!r})\n"
            + "grid = np.arange(3)\n"
            + f"plt.plot({frame}['region'], {frame}['revenue'])\n"
            + "plt.show()\n"
        )
        return _RefusalCase("D1-generated", source, "arm_ambiguous")
    if predicate == 2:
        other_path = draw(st.sampled_from(_PATHS))
        source = (
            _DATASET_PRELUDE
            + f"{frame} = pd.read_csv({path!r})\n"
            + f"other = pd.read_csv({other_path!r})\n"
            + f"plt.plot({frame}['region'], {frame}['revenue'])\n"
            + "plt.show()\n"
        )
        return _RefusalCase("D2-generated", source, "multiple_sources")
    if predicate == 3:
        source = (
            _DATASET_PRELUDE
            + f"path = {path!r}\n"
            + f"{frame} = pd.read_csv(path)\n"
            + f"plt.plot({frame}['region'], {frame}['revenue'])\n"
            + "plt.show()\n"
        )
        return _RefusalCase("D3-generated", source, "source_not_literal")
    if predicate == 4:
        if draw(st.booleans()):
            source = (
                _DATASET_PRELUDE
                + f"{frame} = pd.read_csv({path!r})\n"
                + "column = 'region'\n"
                + f"plt.plot({frame}[column], {frame}['revenue'])\n"
                + "plt.show()\n"
            )
            return _RefusalCase("D4-generated-literal", source, "column_not_literal")
        source = (
            _DATASET_PRELUDE
            + f"{frame} = pd.read_csv({path!r})\n"
            + f"other = {frame}\n"
            + f"plt.plot(other['region'], {frame}['revenue'])\n"
            + "plt.show()\n"
        )
        return _RefusalCase("D4-generated-source", source, "column_not_from_source")
    if predicate == 5:
        source = (
            _DATASET_PRELUDE
            + f"{frame} = pd.read_csv({path!r})\n"
            + f"x = {frame}['region']\n"
            + f"other = {frame}\n"
            + "y = other['revenue']\n"
            + "plt.scatter(x, y)\n"
            + "plt.show()\n"
        )
        return _RefusalCase("D5-generated", source, "column_not_from_source")
    if predicate == 7:
        second = draw(st.sampled_from(_MARK_CALLS))
        source = (
            _DATASET_PRELUDE
            + f"{frame} = pd.read_csv({path!r})\n"
            + f"plt.plot({frame}['region'], {frame}['revenue'])\n"
            + f"plt.{second}({frame}['region'], {frame}['revenue'])\n"
            + "plt.show()\n"
        )
        return _RefusalCase("D7-generated", source, "multiple_marks")
    if predicate == 8:
        target = draw(st.sampled_from(["title", "xlabel", "ylabel"]))
        source = (
            _DATASET_PRELUDE
            + f"{frame} = pd.read_csv({path!r})\n"
            + "label = 'not literal here'\n"
            + f"plt.plot({frame}['region'], {frame}['revenue'])\n"
            + f"plt.{target}(label)\n"
            + "plt.show()\n"
        )
        return _RefusalCase("D8-generated", source, "label_not_literal")
    if predicate == 9:
        tail = draw(st.sampled_from(["", "plt.show()\nplt.show()\n", "plt.show()\nplt.grid()\n"]))
        code = "no_terminal" if not tail else "statement_after_terminal"
        source = (
            _DATASET_PRELUDE
            + f"{frame} = pd.read_csv({path!r})\n"
            + f"plt.plot({frame}['region'], {frame}['revenue'])\n"
            + tail
        )
        return _RefusalCase("D9-generated", source, code)
    unused_column = draw(st.sampled_from(_COLUMNS))
    source = (
        _DATASET_PRELUDE
        + f"{frame} = pd.read_csv({path!r})\n"
        + f"unused = {frame}[{unused_column!r}]\n"
        + f"plt.plot({frame}['region'], {frame}['revenue'])\n"
        + "plt.show()\n"
    )
    return _RefusalCase("D10-generated", source, "statement_not_projected")


_PROJECTION_REFUSALS: SearchStrategy[_RefusalCase] = _projection_refusals()


class _Project(Protocol):
    def __call__(self, tree: ast.Module) -> object: ...


class _TypeAlias(Protocol):
    __value__: object


class _ProductionSpec(Protocol):
    CorePlotSpec: _TypeAlias
    FormulaPlot: type[object]
    DatasetPlot: type[object]


def _production_module() -> ModuleType:
    return importlib.import_module("verifier.pysrc.project")


def _production_project(module: ModuleType) -> _Project:
    candidate = getattr(module, "project", None)
    if not callable(candidate):
        message = "verifier.pysrc.project.project is absent or not callable"
        raise TypeError(message)
    return cast("_Project", candidate)


def _require_dataset_symbol() -> None:
    spec = importlib.import_module("verifier.pysrc.spec")
    if getattr(spec, "DatasetPlot", None) is None:
        pytest.skip("LOUD M13.4 DIFFERENTIAL SKIP: verifier.pysrc.spec.DatasetPlot is absent")


def _assert_nonvacuous(module: ModuleType) -> None:
    oracle_file = Path(oracle_module.__file__).resolve()
    production_file = Path(cast("str", module.__file__)).resolve()
    assert oracle_file != production_file, (
        "VACUOUS DIFFERENTIAL: oracle and production resolve to the same __file__"
    )
    worktree = Path(__file__).resolve().parents[1]
    assert oracle_file == worktree / "tests" / "oracle_dataset.py", (
        "oracle must resolve from this worktree's tests/"
    )
    assert production_file == worktree / "src" / "verifier" / "pysrc" / "project.py", (
        "production must resolve from this worktree's src/; set PYTHONPATH to the worktree src"
    )
    assert _production_project(module) is not oracle_project, (
        "VACUOUS DIFFERENTIAL: both module paths expose the same project function"
    )


def _oracle_code(source: str) -> str:
    with pytest.raises(OracleDatasetProjectionError) as caught:
        oracle_project(ast.parse(source))
    return str(caught.value.code)


def _contains_ast(value: object, seen: set[int] | None = None) -> bool:
    if isinstance(value, ast.AST):
        return True
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return False
    seen.add(identity)
    if is_dataclass(value) and not isinstance(value, type):
        return any(_contains_ast(getattr(value, field.name), seen) for field in fields(value))
    if isinstance(value, dict):
        return any(_contains_ast(item, seen) for pair in value.items() for item in pair)
    if isinstance(value, (tuple, list, set, frozenset)):
        return any(_contains_ast(item, seen) for item in value)
    return False


def _assert_agreement(source: str, *, expected_code: str | None = None) -> None:
    _require_dataset_symbol()
    module = _production_module()
    _assert_nonvacuous(module)
    production = _production_project(module)
    oracle_tree = ast.parse(source)
    try:
        production_tree = parse_admitted(source)
    except PysrcRefusalError as admission_error:
        try:
            oracle_project(oracle_tree)
        except OracleDatasetProjectionError as oracle_error:
            oracle_code = str(oracle_error.code)
            production_code = str(admission_error.code)
            assert oracle_code == production_code
            if expected_code is not None:
                assert oracle_code == expected_code
            return
        message = "oracle admitted but production admission refused"
        raise AssertionError(message) from admission_error

    try:
        expected = oracle_project(oracle_tree)
    except OracleDatasetProjectionError as oracle_error:
        try:
            production(production_tree)
        except PysrcRefusalError as production_error:
            oracle_code = str(oracle_error.code)
            production_code = str(production_error.code)
            assert oracle_code == production_code
            if expected_code is not None:
                assert oracle_code == expected_code
            return
        message = "oracle refused but production admitted"
        raise AssertionError(message) from oracle_error

    try:
        observed = production(production_tree)
    except PysrcRefusalError as production_error:
        message = "oracle admitted but production refused"
        raise AssertionError(message) from production_error
    assert expected_code is None
    assert oracle_module.normalize(expected) == oracle_module.normalize(observed)


def test_oracle_first_dataset_bar_is_complete() -> None:
    """Checkpoint: one bar reaches a complete immutable, hand-stated oracle value."""
    assert oracle_project(ast.parse(_BAR)) == DatasetChart(
        kind="bar",
        csv=CsvFile("sales.csv"),
        horizontal=Field("region"),
        vertical=Field("revenue"),
        annotations=ChartLabels(),
    )


def test_d1_oracle_arm_selection_is_closed() -> None:
    """D1: pandas and a grid conflict; neither arm retains formula refusal behavior."""
    ambiguous = (
        _DATASET_PRELUDE
        + "import numpy as np\n"
        + 'df = pd.read_csv("sales.csv")\n'
        + "x = np.linspace(0, 1)\n"
        + 'plt.plot(df["a"], df["b"])\n'
        + "plt.show()\n"
    )
    assert _oracle_code(ambiguous) == "arm_ambiguous"
    assert _oracle_code("") == "no_mark"
    literal_mark = _FORMULA_PRELUDE + "plt.plot(1, 2)\nplt.show()\n"
    assert _oracle_code(literal_mark) == "x_not_a_grid"


def test_d1_differential_arm_selection_is_closed() -> None:
    """D1: the structural ambiguity witness agrees with production."""
    source = (
        _DATASET_PRELUDE
        + "import numpy as np\n"
        + 'df = pd.read_csv("sales.csv")\n'
        + "x = np.linspace(0, 1)\n"
        + 'plt.plot(df["a"], df["b"])\n'
        + "plt.show()\n"
    )
    _assert_agreement(source, expected_code="arm_ambiguous")


_D2_REFUSALS = (
    _RefusalCase("D2-no-mark-or-source", _DATASET_PRELUDE + "plt.show()\n", "no_mark"),
    _RefusalCase(
        "D2-mark-without-source",
        _DATASET_PRELUDE + "plt.plot(1, 2)\nplt.show()\n",
        "no_source",
    ),
    _RefusalCase(
        "D2-multiple-sources",
        _DATASET_PRELUDE
        + 'left = pd.read_csv("a.csv")\n'
        + 'right = pd.read_csv("b.csv")\n'
        + 'plt.plot(left["x"], left["y"])\n'
        + "plt.show()\n",
        "multiple_sources",
    ),
)


@pytest.mark.parametrize("case", _D2_REFUSALS, ids=lambda case: case.predicate)
def test_d2_oracle_source_cardinality(case: _RefusalCase) -> None:
    """D2: no mark, no source, and a second source each retain one code."""
    assert _oracle_code(case.source) == case.code


@pytest.mark.parametrize("case", _D2_REFUSALS, ids=lambda case: case.predicate)
def test_d2_differential_source_cardinality(case: _RefusalCase) -> None:
    """D2: production and oracle agree on all source-cardinality precedence cases."""
    _assert_agreement(case.source, expected_code=case.code)


_D3_PROJECTION_REFUSALS = (
    _RefusalCase(
        "D3-name",
        _DATASET_PRELUDE
        + 'path = "a.csv"\n'
        + "df = pd.read_csv(path)\n"
        + 'plt.plot(df["x"], df["y"])\n'
        + "plt.show()\n",
        "source_not_literal",
    ),
    _RefusalCase(
        "D3-extra-positional",
        _DATASET_PRELUDE
        + 'df = pd.read_csv("a.csv", "extra")\n'
        + 'plt.plot(df["x"], df["y"])\n'
        + "plt.show()\n",
        "source_not_literal",
    ),
)


@pytest.mark.parametrize("case", _D3_PROJECTION_REFUSALS, ids=lambda case: case.predicate)
def test_d3_oracle_source_requires_one_literal(case: _RefusalCase) -> None:
    """D3: admitted non-single-literal source shapes refuse in projection."""
    assert _oracle_code(case.source) == case.code


@pytest.mark.parametrize("case", _D3_PROJECTION_REFUSALS, ids=lambda case: case.predicate)
def test_d3_differential_source_requires_one_literal(case: _RefusalCase) -> None:
    """D3: both admitted near misses agree on `source_not_literal`."""
    _assert_agreement(case.source, expected_code=case.code)


@pytest.mark.parametrize(
    "source,code",
    [
        (
            _DATASET_PRELUDE
            + 'df = pd.read_csv("a.csv", sep=";")\n'
            + 'plt.plot(df["x"], df["y"])\n'
            + "plt.show()\n",
            "keyword_not_admitted",
        ),
        (
            _DATASET_PRELUDE
            + "n = 1\n"
            + 'df = pd.read_csv(f"{n}.csv")\n'
            + 'plt.plot(df["x"], df["y"])\n'
            + "plt.show()\n",
            "expression_not_admitted",
        ),
    ],
    ids=["D3-keyword", "D3-f-string"],
)
def test_d3_production_admission_owned_forms(source: str, code: str) -> None:
    """D3: admission-owned source faults retain their stage-specific codes."""
    _require_dataset_symbol()
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    assert str(caught.value.code) == code


@pytest.mark.parametrize(
    "setup,x_expression,code",
    [
        ('column = "region"\n', "df[column]", "column_not_literal"),
        ("other = df\n", 'other["region"]', "column_not_from_source"),
    ],
    ids=["D4-nonliteral", "D4-other-frame"],
)
def test_d4_oracle_column_shape(setup: str, x_expression: str, code: str) -> None:
    """D4: the index and source-frame halves each have a distinct refusal."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + setup
        + f'plt.plot({x_expression}, df["revenue"])\n'
        + "plt.show()\n"
    )
    assert _oracle_code(source) == code


@pytest.mark.parametrize(
    "setup,x_expression,code",
    [
        ('column = "region"\n', "df[column]", "column_not_literal"),
        ("other = df\n", 'other["region"]', "column_not_from_source"),
    ],
    ids=["D4-nonliteral", "D4-other-frame"],
)
def test_d4_differential_column_shape(setup: str, x_expression: str, code: str) -> None:
    """D4: production and oracle agree on both closed column-reference halves."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + setup
        + f'plt.plot({x_expression}, df["revenue"])\n'
        + "plt.show()\n"
    )
    _assert_agreement(source, expected_code=code)


def test_d5_oracle_channels_share_the_bound_frame() -> None:
    """D5: a column alias cannot substitute another frame spelling."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'x = df["region"]\n'
        + "other = df\n"
        + 'y = other["revenue"]\n'
        + "plt.scatter(x, y)\n"
        + "plt.show()\n"
    )
    assert _oracle_code(source) == "column_not_from_source"


def test_d5_differential_channels_share_the_bound_frame() -> None:
    """D5: the mixed-frame bound-column witness agrees with production."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'x = df["region"]\n'
        + "other = df\n"
        + 'y = other["revenue"]\n'
        + "plt.scatter(x, y)\n"
        + "plt.show()\n"
    )
    _assert_agreement(source, expected_code="column_not_from_source")


@pytest.mark.parametrize(
    "call,kind",
    [("plot", "line"), ("scatter", "scatter"), ("bar", "bar")],
    ids=["D6-line", "D6-scatter", "D6-bar"],
)
def test_d6_oracle_dataset_mark_space(call: str, kind: str) -> None:
    """D6: line, scatter, and bar are the complete dataset mark vocabulary."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + f'plt.{call}(df["region"], df["revenue"])\n'
        + "plt.show()\n"
    )
    projected = oracle_project(ast.parse(source))
    assert isinstance(projected, DatasetChart)
    assert projected.kind == kind


@pytest.mark.parametrize(
    "call",
    ["plot", "scatter", "bar"],
    ids=["D6-line", "D6-scatter", "D6-bar"],
)
def test_d6_differential_dataset_mark_space(call: str) -> None:
    """D6: every dataset mark meaning agrees with production through the closed map."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + f'plt.{call}(df["region"], df["revenue"])\n'
        + "plt.show()\n"
    )
    _assert_agreement(source)


def test_g5_oracle_bar_is_arm_specific() -> None:
    """G5: identical bar targets admit for columns and refuse for sampled functions."""
    formula = _FORMULA_PRELUDE + "x = np.arange(3)\n" + "plt.bar(x, np.sin(x))\n" + "plt.show()\n"
    assert _oracle_code(formula) == "mark_not_valid_for_arm"
    dataset = oracle_project(ast.parse(_BAR))
    assert isinstance(dataset, DatasetChart)
    assert dataset.kind == "bar"


def test_g5_differential_bar_is_arm_specific() -> None:
    """G5: both arms independently agree on opposite verdicts for `plt.bar`."""
    formula = _FORMULA_PRELUDE + "x = np.arange(3)\n" + "plt.bar(x, np.sin(x))\n" + "plt.show()\n"
    _assert_agreement(formula, expected_code="mark_not_valid_for_arm")
    _assert_agreement(_BAR)


def test_d7_oracle_mark_cardinality_and_local_precedence() -> None:
    """D7: a second valid mark is global; a bad channel on either mark is local first."""
    two_valid = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + 'plt.scatter(df["region"], df["revenue"])\n'
        + "plt.show()\n"
    )
    assert _oracle_code(two_valid) == "multiple_marks"
    for first_x, second_x in [
        ('other["region"]', 'df["region"]'),
        ('df["region"]', 'other["region"]'),
    ]:
        local_fault = (
            _DATASET_PRELUDE
            + 'df = pd.read_csv("sales.csv")\n'
            + "other = df\n"
            + f'plt.plot({first_x}, df["revenue"])\n'
            + f'plt.scatter({second_x}, df["revenue"])\n'
            + "plt.show()\n"
        )
        assert _oracle_code(local_fault) == "column_not_from_source"


@pytest.mark.parametrize(
    "prefix,first_x,second_x,code",
    [
        ("", 'df["region"]', 'df["region"]', "multiple_marks"),
        (
            "other = df\n",
            'other["region"]',
            'df["region"]',
            "column_not_from_source",
        ),
        (
            "other = df\n",
            'df["region"]',
            'other["region"]',
            "column_not_from_source",
        ),
    ],
    ids=["D7-two-valid", "D7-first-local", "D7-counting-mark-local"],
)
def test_d7_differential_mark_cardinality(
    prefix: str, first_x: str, second_x: str, code: str
) -> None:
    """D7: production and oracle resolve either mark locally before cardinality."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + prefix
        + f'plt.plot({first_x}, df["revenue"])\n'
        + f'plt.scatter({second_x}, df["revenue"])\n'
        + "plt.show()\n"
    )
    _assert_agreement(source, expected_code=code)


def test_d8_oracle_decorations_project_to_shared_labels() -> None:
    """D8: mark label and all decoration calls reach one immutable label record."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'plt.scatter(df["region"], df["revenue"], label="series")\n'
        + 'plt.title("title")\n'
        + 'plt.xlabel("region axis")\n'
        + 'plt.ylabel("revenue axis")\n'
        + "plt.legend()\n"
        + "plt.grid(True)\n"
        + "plt.show()\n"
    )
    projected = oracle_project(ast.parse(source))
    assert isinstance(projected, DatasetChart)
    assert projected.annotations == ChartLabels(
        heading="title",
        horizontal="region axis",
        vertical="revenue axis",
        series_name="series",
        has_legend=True,
        has_grid=True,
    )


def test_d8_oracle_nonliteral_label_refuses() -> None:
    """D8: a bound string remains nonliteral at the label call site."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'title = "title"\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + "plt.title(title)\n"
        + "plt.show()\n"
    )
    assert _oracle_code(source) == "label_not_literal"


@pytest.mark.parametrize("case", ["valid", "nonliteral"], ids=["D8-valid", "D8-nonliteral"])
def test_d8_differential_decorations(case: str) -> None:
    """D8: complete labels and the nonliteral near miss each agree with production."""
    if case == "valid":
        source = (
            _DATASET_PRELUDE
            + 'df = pd.read_csv("sales.csv")\n'
            + 'plt.scatter(df["region"], df["revenue"], label="series")\n'
            + 'plt.title("title")\n'
            + 'plt.xlabel("region axis")\n'
            + 'plt.ylabel("revenue axis")\n'
            + "plt.legend()\n"
            + "plt.grid(True)\n"
            + "plt.show()\n"
        )
        _assert_agreement(source)
        return
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'title = "title"\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + "plt.title(title)\n"
        + "plt.show()\n"
    )
    _assert_agreement(source, expected_code="label_not_literal")


@pytest.mark.parametrize(
    "tail,code",
    [
        ("", "no_terminal"),
        ('plt.show()\nplt.title("late")\n', "statement_after_terminal"),
        ("plt.show()\nplt.show()\n", "statement_after_terminal"),
    ],
    ids=["D9-missing", "D9-nonfinal", "D9-multiple"],
)
def test_d9_oracle_terminal_is_single_and_final(tail: str, code: str) -> None:
    """D9: missing, nonfinal, and repeated terminal calls each refuse."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + tail
    )
    assert _oracle_code(source) == code


@pytest.mark.parametrize(
    "tail,code",
    [
        ("", "no_terminal"),
        ('plt.show()\nplt.title("late")\n', "statement_after_terminal"),
        ("plt.show()\nplt.show()\n", "statement_after_terminal"),
    ],
    ids=["D9-missing", "D9-nonfinal", "D9-multiple"],
)
def test_d9_differential_terminal_is_single_and_final(tail: str, code: str) -> None:
    """D9: all three terminal refusal shapes agree with production."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + tail
    )
    _assert_agreement(source, expected_code=code)


def test_d10_oracle_rejects_an_unused_column_assignment() -> None:
    """D10: admitted column work not represented in the spec refuses totality."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'unused = df["ignored"]\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + "plt.show()\n"
    )
    assert _oracle_code(source) == "statement_not_projected"


def test_d10_differential_rejects_an_unused_column_assignment() -> None:
    """D10: the unused admitted-column witness agrees with production."""
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'unused = df["ignored"]\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + "plt.show()\n"
    )
    _assert_agreement(source, expected_code="statement_not_projected")


def test_d11_oracle_projection_is_pure() -> None:
    """D11: equal parses yield equal AST-free values without mutating either tree."""
    tree = ast.parse(_BAR)
    before = ast.dump(tree, include_attributes=True)
    first = oracle_project(tree)
    second = oracle_project(tree)
    third = oracle_project(ast.parse(_BAR))
    assert ast.dump(tree, include_attributes=True) == before
    assert first == second == third
    assert not _contains_ast(first)
    assert _BAR not in repr(oracle_module.normalize(first))


def test_d11_differential_projection_is_pure() -> None:
    """D11: production independently has the same purity and value semantics."""
    _require_dataset_symbol()
    module = _production_module()
    _assert_nonvacuous(module)
    production = _production_project(module)
    tree = parse_admitted(_BAR)
    before = ast.dump(tree, include_attributes=True)
    first = production(tree)
    second = production(tree)
    third = production(parse_admitted(_BAR))
    assert ast.dump(tree, include_attributes=True) == before
    assert first == second == third
    assert not _contains_ast(first)
    assert _BAR not in repr(oracle_module.normalize(first))
    _assert_agreement(_BAR)


def test_d12_oracle_plot_union_is_exact() -> None:
    """D12: the independent plot union is exactly formula plus dataset."""
    assert get_args(OraclePlotSpec.__value__) == (FormulaPlot, DatasetChart)


def test_d12_production_plot_union_is_exact() -> None:
    """D12: production's PEP-695 alias has the hand-stated two-member tuple."""
    _require_dataset_symbol()
    spec = cast("_ProductionSpec", importlib.import_module("verifier.pysrc.spec"))
    assert get_args(spec.CorePlotSpec.__value__) == (spec.FormulaPlot, spec.DatasetPlot)


def test_g1_dataset_axis_limit_stays_unadmitted() -> None:
    """G1: dataset bars retain a zero baseline because axis limits cannot enter."""
    _require_dataset_symbol()
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'plt.bar(df["region"], df["revenue"])\n'
        + "plt.ylim(50, 100)\n"
        + "plt.show()\n"
    )
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    assert str(caught.value.code) == "call_target_not_admitted"


def test_g2_dataset_secondary_axis_stays_unadmitted() -> None:
    """G2: a dataset chart cannot construct a second or secondary axis."""
    _require_dataset_symbol()
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + "plt.twinx()\n"
        + "plt.show()\n"
    )
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    assert str(caught.value.code) == "call_target_not_admitted"


def test_g3_dataset_nonlinear_scale_stays_unadmitted() -> None:
    """G3: a dataset chart cannot replace the sole linear scale."""
    _require_dataset_symbol()
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'plt.plot(df["region"], df["revenue"])\n'
        + 'plt.yscale("log")\n'
        + "plt.show()\n"
    )
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    assert str(caught.value.code) == "call_target_not_admitted"


def test_g6_dataset_marker_size_stays_unadmitted() -> None:
    """G6: no unverified size encoding can enter a dataset scatter."""
    _require_dataset_symbol()
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'plt.scatter(df["region"], df["revenue"], s=4)\n'
        + "plt.show()\n"
    )
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    assert str(caught.value.code) == "keyword_not_admitted"


def test_g7_oracle_carries_range_inputs_without_claiming_a_range() -> None:
    """G7: M13.4 carries source and both columns; range equality remains open."""
    projected = oracle_project(ast.parse(_BAR))
    assert projected == DatasetChart(
        kind="bar",
        csv=CsvFile("sales.csv"),
        horizontal=Field("region"),
        vertical=Field("revenue"),
        annotations=ChartLabels(),
    )
    assert "range" not in repr(oracle_module.normalize(projected)).lower()


def test_g7_differential_carries_range_inputs_without_claiming_a_range() -> None:
    """G7: production agrees on the facts M13.5 will use, not a range verdict."""
    _assert_agreement(_BAR)


def test_g8_oracle_carries_count_inputs_without_claiming_a_count() -> None:
    """G8: two selected channels are explicit; eligible row count remains open."""
    projected = oracle_project(ast.parse(_BAR))
    assert isinstance(projected, DatasetChart)
    assert projected.csv == CsvFile("sales.csv")
    assert (projected.horizontal, projected.vertical) == (Field("region"), Field("revenue"))
    assert "count" not in repr(oracle_module.normalize(projected)).lower()


def test_g8_differential_carries_count_inputs_without_claiming_a_count() -> None:
    """G8: production agrees on selection facts, not the M13.5 row-count verdict."""
    _assert_agreement(_BAR)


def test_g11_dataset_aggregation_stays_dormant() -> None:
    """G11: the column-pair width refuses aggregation before projection."""
    _require_dataset_symbol()
    source = (
        _DATASET_PRELUDE
        + 'df = pd.read_csv("sales.csv")\n'
        + 'grouped = df.groupby("region")\n'
        + 'plt.bar(df["region"], df["revenue"])\n'
        + "plt.show()\n"
    )
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    assert str(caught.value.code) == "call_target_not_admitted"


@given(_VALID_SOURCES)
def test_oracle_generated_valid_dataset_programs(source: str) -> None:
    """Generated positives span paths, columns, binding, marks, labels, and decorations."""
    assert isinstance(oracle_project(ast.parse(source)), DatasetChart)


@given(_VALID_SOURCES)
def test_differential_generated_valid_dataset_programs(source: str) -> None:
    """Both independent implementations agree over the generated valid population."""
    _assert_agreement(source)


@given(_PROJECTION_REFUSALS)
def test_oracle_generated_dataset_refusals(case: _RefusalCase) -> None:
    """Generated one-boundary near misses yield their hand-stated refusal codes."""
    assert _oracle_code(case.source) == case.code


@given(_PROJECTION_REFUSALS)
def test_differential_generated_dataset_refusals(case: _RefusalCase) -> None:
    """Both implementations agree over generated D1-D10 projection near misses."""
    _assert_agreement(case.source, expected_code=case.code)


def test_differential_modules_are_distinct() -> None:
    """The editable-path vacuity guard is an explicit differential precondition."""
    _require_dataset_symbol()
    _assert_nonvacuous(_production_module())


def test_vacuity_guard_has_positive_controls() -> None:
    """Same-file and same-function fakes prove both independence guards can fire."""
    same_file = ModuleType("same_file")
    same_file.__file__ = oracle_module.__file__
    with pytest.raises(AssertionError, match="same __file__"):
        _assert_nonvacuous(same_file)

    same_function = ModuleType("same_function")
    worktree = Path(__file__).resolve().parents[1]
    same_function.__file__ = str(worktree / "src" / "verifier" / "pysrc" / "project.py")
    same_function.__dict__["project"] = oracle_project
    with pytest.raises(AssertionError, match="same project function"):
        _assert_nonvacuous(same_function)


def test_canonical_dataset_translation_is_explicit_and_ordered() -> None:
    """The one comparison boundary fixes every dataset node, field, and field position."""
    observed = oracle_module.normalize(
        DatasetChart(
            kind="bar",
            csv=CsvFile("sales.csv"),
            horizontal=Field("region"),
            vertical=Field("revenue"),
            annotations=ChartLabels(),
        )
    )
    assert observed == (
        "DatasetPlot",
        (
            ("mark", "bar"),
            ("source", ("DatasetRef", (("path", "sales.csv"),))),
            ("x", ("Column", (("name", "region"),))),
            ("y", ("Column", (("name", "revenue"),))),
            (
                "labels",
                (
                    "Labels",
                    (
                        ("title", None),
                        ("xlabel", None),
                        ("ylabel", None),
                        ("series", None),
                        ("legend", False),
                        ("grid", False),
                    ),
                ),
            ),
        ),
    )


def test_canonical_dataset_translation_rejects_unknown_shapes() -> None:
    """An unmapped dataset node or field fails loudly instead of erasing disagreement."""

    @dataclass(frozen=True)
    class UnknownDatasetNode:
        value: int

    @dataclass(frozen=True)
    class DatasetPlot:
        mark: str
        source: object
        x: object
        y: object
        labels: object
        extra: int

    with pytest.raises(TypeError, match="unmapped projection node"):
        oracle_module.normalize(UnknownDatasetNode(1))
    malformed = DatasetPlot("bar", object(), object(), object(), object(), 1)
    with pytest.raises(TypeError, match="unmapped DatasetPlot fields"):
        oracle_module.normalize(malformed)
