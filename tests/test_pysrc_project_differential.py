# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Generated and anchored differential corpus for M13.3 projection."""

import ast
import importlib
from dataclasses import dataclass, fields, is_dataclass
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

import oracle_project as oracle_module
from oracle_project import FormulaPlot, OracleProjectionError, normalize
from oracle_project import project as oracle_project
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.errors import PysrcRefusalError

_PRELUDE = "import numpy as np\nimport matplotlib.pyplot as plt\n"
_LINE = (
    _PRELUDE + "x = np.linspace(0, 1)\n" + "y = np.sin(x)\n" + "plt.plot(x, y)\n" + "plt.show()\n"
)
_INLINE_LINE = (
    _PRELUDE + "plt.plot(np.linspace(0, 1), np.sin(np.linspace(0, 1)))\n" + "plt.show()\n"
)
_ARANGE_LINE = _PRELUDE + "x = np.arange(0, 10)\n" + "plt.plot(x, np.cos(x))\n" + "plt.show()\n"
_DECORATED = (
    _PRELUDE
    + "x = np.linspace(0, 1, num=20)\n"
    + "y = np.sin(x)\n"
    + 'plt.scatter(x, y, label="series")\n'
    + 'plt.title("title")\n'
    + 'plt.xlabel("x axis")\n'
    + 'plt.ylabel("y axis")\n'
    + "plt.legend()\n"
    + "plt.grid(True)\n"
    + "plt.show()\n"
)

_EXPRESSION_TEMPLATES = (
    ("identity", "{x}"),
    ("sin", "np.sin({x})"),
    ("cos", "np.cos({x})"),
    ("tan", "np.tan({x})"),
    ("exp", "np.exp({x})"),
    ("log", "np.log({x})"),
    ("sqrt", "np.sqrt({x})"),
    ("abs", "np.abs({x})"),
    ("add", "{x} + 1"),
    ("sub", "{x} - 1"),
    ("mul", "2 * {x}"),
    ("div", "{x} / 2"),
    ("pow", "{x} ** 2"),
    ("neg", "-{x}"),
    ("pi", "{x} + np.pi"),
    ("e", "{x} * np.e"),
)
_GRID_EXPRESSIONS = (
    "np.linspace(0, 1)",
    "np.linspace(0, 1, 17)",
    "np.linspace(0, 2 * np.pi, num=32)",
    "np.arange(5)",
    "np.arange(0, 5)",
    "np.arange(0, 5, 2)",
    "np.arange(5, 0, -1)",
)


@dataclass(frozen=True, slots=True)
class _RefusalCase:
    predicate: str
    source: str
    code: str


_P1_P4_REFUSALS = (
    _RefusalCase("P1-empty", "", "no_mark"),
    _RefusalCase("P1-decoration", _PRELUDE + 'plt.title("t")\nplt.show()\n', "no_mark"),
    _RefusalCase(
        "P2-second-mark",
        _PRELUDE
        + "x = np.linspace(0, 1)\n"
        + "y = np.sin(x)\n"
        + "plt.plot(x, y)\n"
        + "plt.scatter(x, y)\n"
        + "plt.show()\n",
        "multiple_marks",
    ),
    _RefusalCase(
        "P3-literal-x",
        _PRELUDE + "y = np.sin(3)\nplt.plot(3, y)\nplt.show()\n",
        "x_not_a_grid",
    ),
    _RefusalCase(
        "P4-second-grid",
        _PRELUDE
        + "x = np.linspace(0, 1)\n"
        + "z = np.arange(0, 2)\n"
        + "plt.plot(x, z)\n"
        + "plt.show()\n",
        "y_not_over_grid",
    ),
)

_P5_P8_REFUSALS = (
    _RefusalCase(
        "P6-zero",
        _PRELUDE + "x = np.linspace(0, 1, num=0)\n" + "plt.plot(x, np.sin(x))\n" + "plt.show()\n",
        "grid_not_representable",
    ),
    _RefusalCase(
        "P6-float",
        _PRELUDE + "x = np.linspace(0, 1, num=2.5)\n" + "plt.plot(x, np.sin(x))\n" + "plt.show()\n",
        "grid_not_representable",
    ),
    _RefusalCase(
        "P6-name",
        _PRELUDE
        + "n = 20\n"
        + "x = np.linspace(0, 1, num=n)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.show()\n",
        "grid_not_representable",
    ),
    _RefusalCase(
        "P6-over-limit",
        _PRELUDE
        + "x = np.linspace(0, 1, num=100001)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.show()\n",
        "grid_not_representable",
    ),
    _RefusalCase(
        "P7-title-name",
        _PRELUDE
        + "x = np.linspace(0, 1)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.title(x)\n"
        + "plt.show()\n",
        "label_not_literal",
    ),
    _RefusalCase(
        "P8-no-terminal",
        _PRELUDE + "x = np.arange(3)\n" + "plt.plot(x, np.sin(x))\n",
        "no_terminal",
    ),
    _RefusalCase(
        "P8-non-final",
        _PRELUDE
        + "x = np.arange(3)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.show()\n"
        + 'plt.title("late")\n',
        "statement_after_terminal",
    ),
    _RefusalCase(
        "P8-second-terminal",
        _PRELUDE
        + "x = np.arange(3)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.show()\n"
        + "plt.show()\n",
        "statement_after_terminal",
    ),
)

_P9_P11_REFUSALS = (
    _RefusalCase(
        "P9-rebound",
        _PRELUDE
        + "x = np.linspace(0, 1)\n"
        + "x = np.arange(3)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.show()\n",
        "name_rebound",
    ),
    _RefusalCase(
        "P10-bar",
        _PRELUDE + "x = np.arange(3)\n" + "plt.bar(x, np.sin(x))\n" + "plt.show()\n",
        "mark_not_valid_for_arm",
    ),
    _RefusalCase(
        "P10-local-before-global",
        _PRELUDE
        + "x = np.arange(3)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.bar(x, np.cos(x))\n"
        + "plt.show()\n",
        "mark_not_valid_for_arm",
    ),
    _RefusalCase(
        "P11-unused-assignment",
        _PRELUDE
        + "spare = 7\n"
        + "x = np.arange(3)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.show()\n",
        "statement_not_projected",
    ),
    _RefusalCase(
        "P11-bare-pure-call",
        _PRELUDE
        + "x = np.arange(3)\n"
        + "np.sin(1)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.show()\n",
        "statement_not_projected",
    ),
)

_ALL_PROJECTION_REFUSALS = _P1_P4_REFUSALS + _P5_P8_REFUSALS + _P9_P11_REFUSALS


class _Project(Protocol):
    def __call__(self, tree: ast.Module) -> object: ...


def _production_module() -> ModuleType:
    return importlib.import_module("verifier.pysrc.project")


def _production_project(module: ModuleType) -> _Project:
    candidate = getattr(module, "project", None)
    if not callable(candidate):
        message = "verifier.pysrc.project.project is absent or not callable"
        raise TypeError(message)
    return cast("_Project", candidate)


def _assert_nonvacuous(module: ModuleType) -> None:
    """Fail before comparison when editable-path leakage resolves both sides to one module."""
    oracle_file = Path(oracle_module.__file__).resolve()
    production_file = Path(cast("str", module.__file__)).resolve()
    assert oracle_file != production_file, (
        "VACUOUS DIFFERENTIAL: oracle and production resolve to the same __file__"
    )
    worktree = Path(__file__).resolve().parents[1]
    assert oracle_file == worktree / "tests" / "oracle_project.py", (
        "oracle must resolve from this worktree's tests/"
    )
    assert production_file == worktree / "src" / "verifier" / "pysrc" / "project.py", (
        "production must resolve from this worktree's src/; set PYTHONPATH to the worktree src"
    )
    assert _production_project(module) is not oracle_project, (
        "VACUOUS DIFFERENTIAL: both module paths expose the same project function"
    )


def _oracle_code(source: str) -> str:
    with pytest.raises(OracleProjectionError) as caught:
        oracle_project(parse_admitted(source))
    return caught.value.code


def _valid_source(  # noqa: PLR0913 — orthogonal generated-program axes stay explicit
    *,
    grid_expression: str,
    expression_template: str,
    mark: str,
    bind_grid: bool,
    bind_y: bool,
    label: str | None,
    title: bool,
    xlabel: bool,
    ylabel: bool,
    legend: bool,
    grid_decoration: str,
) -> str:
    lines: list[str] = []
    if bind_grid:
        lines.append(f"x = {grid_expression}")
        x_expression = "x"
    else:
        x_expression = f"({grid_expression})"
    y_expression = expression_template.format(x=x_expression)
    if bind_y:
        lines.append(f"y = {y_expression}")
        y_expression = "y"
    label_arg = "" if label is None else f', label="{label}"'
    lines.append(f"plt.{mark}({x_expression}, {y_expression}{label_arg})")
    if title:
        lines.append('plt.title("title")')
    if xlabel:
        lines.append('plt.xlabel("x axis")')
    if ylabel:
        lines.append('plt.ylabel("y axis")')
    if legend:
        lines.append("plt.legend()")
    if grid_decoration != "omit":
        argument = "" if grid_decoration == "toggle" else grid_decoration.title()
        lines.append(f"plt.grid({argument})")
    lines.append("plt.show()")
    return _PRELUDE + "\n".join(lines) + "\n"


@st.composite
def _valid_sources(draw: DrawFn) -> str:
    return _valid_source(
        grid_expression=draw(st.sampled_from(_GRID_EXPRESSIONS)),
        expression_template=draw(
            st.sampled_from([template for _, template in _EXPRESSION_TEMPLATES])
        ),
        mark=draw(st.sampled_from(["plot", "scatter"])),
        bind_grid=draw(st.booleans()),
        bind_y=draw(st.booleans()),
        label=draw(st.sampled_from([None, "series"])),
        title=draw(st.booleans()),
        xlabel=draw(st.booleans()),
        ylabel=draw(st.booleans()),
        legend=draw(st.booleans()),
        grid_decoration=draw(st.sampled_from(["omit", "toggle", "true", "false"])),
    )


_VALID_SOURCES: SearchStrategy[str] = _valid_sources()


@st.composite
def _projection_refusals(  # noqa: PLR0911 — closed P1-P11 witness dispatch
    draw: DrawFn,
) -> _RefusalCase:
    predicate = draw(st.integers(min_value=1, max_value=11))
    if predicate == 1:
        decoration = draw(st.sampled_from(["title", "xlabel", "ylabel"]))
        return _RefusalCase(
            "P1-generated", _PRELUDE + f'plt.{decoration}("label")\nplt.show()\n', "no_mark"
        )
    if predicate == 2:
        second = draw(st.sampled_from(["plot", "scatter"]))
        source = (
            _PRELUDE
            + "x = np.arange(4)\n"
            + "plt.plot(x, np.sin(x))\n"
            + f"plt.{second}(x, np.cos(x))\n"
            + "plt.show()\n"
        )
        return _RefusalCase("P2-generated", source, "multiple_marks")
    if predicate == 3:
        literal = draw(st.sampled_from(["0", "1", "2.5"]))
        source = _PRELUDE + f"plt.plot({literal}, np.sin({literal}))\nplt.show()\n"
        return _RefusalCase("P3-generated", source, "x_not_a_grid")
    if predicate == 4:
        stop = draw(st.integers(min_value=3, max_value=20))
        source = (
            _PRELUDE
            + "x = np.arange(0, 2)\n"
            + f"z = np.arange(0, {stop})\n"
            + "plt.plot(x, z)\n"
            + "plt.show()\n"
        )
        return _RefusalCase("P4-generated", source, "y_not_over_grid")
    if predicate == 5:
        source = _PRELUDE + "x = np.arange()\nplt.plot(x, np.sin(x))\nplt.show()\n"
        return _RefusalCase("P5-generated", source, "grid_not_representable")
    if predicate == 6:
        count = draw(st.sampled_from(["0", "1", "-1", "2.5", "n", "100001"]))
        prefix = "n = 10\n" if count == "n" else ""
        source = (
            _PRELUDE
            + prefix
            + f"x = np.linspace(0, 1, num={count})\n"
            + "plt.plot(x, np.sin(x))\n"
            + "plt.show()\n"
        )
        return _RefusalCase("P6-generated", source, "grid_not_representable")
    if predicate == 7:
        target = draw(st.sampled_from(["title", "xlabel", "ylabel"]))
        source = (
            _PRELUDE
            + "x = np.arange(3)\n"
            + "plt.plot(x, np.sin(x))\n"
            + f"plt.{target}(x)\n"
            + "plt.show()\n"
        )
        return _RefusalCase("P7-generated", source, "label_not_literal")
    if predicate == 8:
        trailer = draw(st.sampled_from(['plt.title("late")', "plt.show()", "plt.grid(True)"]))
        source = (
            _PRELUDE
            + "x = np.arange(3)\n"
            + "plt.plot(x, np.sin(x))\n"
            + "plt.show()\n"
            + trailer
            + "\n"
        )
        return _RefusalCase("P8-generated", source, "statement_after_terminal")
    if predicate == 9:
        replacement = draw(st.sampled_from(["np.arange(3)", "np.linspace(0, 1)", "1"]))
        source = (
            _PRELUDE
            + "x = np.arange(3)\n"
            + f"x = {replacement}\n"
            + "plt.plot(x, np.sin(x))\n"
            + "plt.show()\n"
        )
        return _RefusalCase("P9-generated", source, "name_rebound")
    if predicate == 10:
        source = _PRELUDE + "x = np.arange(3)\nplt.bar(x, np.sin(x))\nplt.show()\n"
        return _RefusalCase("P10-generated", source, "mark_not_valid_for_arm")
    unused = draw(st.sampled_from(["spare = 1", "other = np.sin(1)", "np.cos(1)"]))
    source = (
        _PRELUDE
        + unused
        + "\n"
        + "x = np.arange(3)\n"
        + "plt.plot(x, np.sin(x))\n"
        + "plt.show()\n"
    )
    return _RefusalCase("P11-generated", source, "statement_not_projected")


_PROJECTION_REFUSALS: SearchStrategy[_RefusalCase] = _projection_refusals()


@st.composite
def _admission_refusals(draw: DrawFn) -> str:
    return draw(
        st.sampled_from(
            [
                "import numpy as onp\n",
                _PRELUDE + "plt.plott(1, 2)\n",
                _PRELUDE + "plt.plot(1, 2, color='r')\n",
                _PRELUDE + "x = [1, 2]\n",
                "x = 1 // 2\n",
            ]
        )
    )


_ADMISSION_REFUSALS: SearchStrategy[str] = _admission_refusals()


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
    module = _production_module()
    _assert_nonvacuous(module)
    production = _production_project(module)
    oracle_tree = parse_admitted(source)
    production_tree = parse_admitted(source)

    try:
        expected = oracle_project(oracle_tree)
    except OracleProjectionError as oracle_error:
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
    assert normalize(expected) == normalize(observed)


def test_oracle_projects_the_first_line_shape() -> None:
    """Checkpoint: one admitted line program reaches a complete immutable oracle spec."""
    projected = oracle_project(parse_admitted(_LINE))
    assert isinstance(projected, FormulaPlot)
    assert projected.mark == "line"
    assert projected.grid.count == 50


def test_first_line_shape_agrees_end_to_end() -> None:
    """The first valid shape agrees after the loud module-identity guard."""
    _assert_agreement(_LINE)


@pytest.mark.parametrize("case", _P1_P4_REFUSALS, ids=lambda case: case.predicate)
def test_oracle_p1_p4_refusal_anchors(case: _RefusalCase) -> None:
    """Concrete P1-P4 anchors fix each refusal boundary before generated widening."""
    assert _oracle_code(case.source) == case.code


@pytest.mark.parametrize("case", _P1_P4_REFUSALS, ids=lambda case: case.predicate)
def test_differential_p1_p4_refusal_anchors(case: _RefusalCase) -> None:
    """Production and oracle agree on every concrete P1-P4 refusal witness."""
    _assert_agreement(case.source, expected_code=case.code)


def test_oracle_p3_bound_and_inline_grids_are_equal() -> None:
    """P3 anchor: bound and inline spelling project to one structural value."""
    assert oracle_project(parse_admitted(_LINE)) == oracle_project(parse_admitted(_INLINE_LINE))


@pytest.mark.parametrize("source", [_LINE, _INLINE_LINE], ids=["bound", "inline"])
def test_differential_p3_grid_spelling(source: str) -> None:
    """Both P3 grid spellings agree independently with production."""
    _assert_agreement(source)


def test_differential_p4_cross_constructor_grid_identity() -> None:
    """Equal arange and linspace points denote one grid across distinct source spellings."""
    source = (
        _PRELUDE
        + "x = np.arange(0, 5)\n"
        + "y = np.sin(np.linspace(0, 4, 5))\n"
        + "plt.plot(x, y)\n"
        + "plt.show()\n"
    )
    assert isinstance(oracle_project(parse_admitted(source)), FormulaPlot)
    _assert_agreement(source)


@pytest.mark.parametrize("case", _P5_P8_REFUSALS, ids=lambda case: case.predicate)
def test_oracle_p5_p8_refusal_anchors(case: _RefusalCase) -> None:
    """Concrete P5-P8 anchors fix count, label, and terminal boundaries."""
    assert _oracle_code(case.source) == case.code


@pytest.mark.parametrize("case", _P5_P8_REFUSALS, ids=lambda case: case.predicate)
def test_differential_p5_p8_refusal_anchors(case: _RefusalCase) -> None:
    """Production and oracle agree on every concrete P5-P8 refusal witness."""
    _assert_agreement(case.source, expected_code=case.code)


def test_oracle_p5_grid_shapes_and_defaults() -> None:
    """P5: both constructors share `(start, inclusive stop, samples)`."""
    linspace = oracle_project(parse_admitted(_LINE))
    arange = oracle_project(parse_admitted(_ARANGE_LINE))
    equivalent = oracle_project(
        parse_admitted(_PRELUDE + "x = np.linspace(0, 9, 10)\nplt.plot(x, np.cos(x))\nplt.show()\n")
    )
    assert isinstance(linspace, FormulaPlot)
    assert isinstance(arange, FormulaPlot)
    assert type(linspace.grid) is type(arange.grid)
    assert linspace.grid.count == 50
    assert arange.grid == equivalent.grid
    assert arange.grid.count == 10
    assert arange.grid.stop == oracle_module.Number(Fraction(9))


def test_oracle_p5_integer_arange_and_float_fidelity() -> None:
    """P5: arange is integer-only; floats retain their executed float64 value."""
    descending_source = (
        _PRELUDE + "x = np.arange(5, 0, -1)\n" + "plt.plot(x, np.sin(x))\n" + "plt.show()\n"
    )
    descending = oracle_project(parse_admitted(descending_source))
    assert isinstance(descending, FormulaPlot)
    assert descending.grid == oracle_module.Grid(
        oracle_module.Number(Fraction(5)), oracle_module.Number(Fraction(1)), 5
    )

    noninteger_source = (
        _PRELUDE + "x = np.arange(0, 3, 0.3)\n" + "plt.plot(x, np.sin(x))\n" + "plt.show()\n"
    )
    assert _oracle_code(noninteger_source) == "grid_not_representable"

    float_source = (
        _PRELUDE + "x = np.linspace(0.1, 0.2, 2)\n" + "plt.plot(x, np.sin(x))\n" + "plt.show()\n"
    )
    float_grid = oracle_project(parse_admitted(float_source))
    assert isinstance(float_grid, FormulaPlot)
    assert float_grid.grid.start == oracle_module.Number(Fraction(0.1))
    assert float_grid.grid.start != oracle_module.Number(Fraction(1, 10))


def test_oracle_p6_count_boundaries() -> None:
    """P6: the inclusive hand-stated oracle range is 2..100,000."""
    for count in (2, 100_000):
        source = (
            _PRELUDE
            + f"x = np.linspace(0, 1, num={count})\n"
            + "plt.plot(x, np.sin(x))\n"
            + "plt.show()\n"
        )
        projected = oracle_project(parse_admitted(source))
        assert isinstance(projected, FormulaPlot)
        assert projected.grid.count == count


def test_oracle_p7_decorations_project_to_labels() -> None:
    """P7: literal labels and boolean decorations all reach one immutable record."""
    projected = oracle_project(parse_admitted(_DECORATED))
    assert isinstance(projected, FormulaPlot)
    assert projected.labels.title == "title"
    assert projected.labels.xlabel == "x axis"
    assert projected.labels.ylabel == "y axis"
    assert projected.labels.series == "series"
    assert projected.labels.legend is True
    assert projected.labels.grid is True


@pytest.mark.parametrize("source", [_ARANGE_LINE, _DECORATED], ids=["arange", "decorated"])
def test_differential_p5_p7_valid_shapes(source: str) -> None:
    """Constructor and decoration positives independently agree with production."""
    _assert_agreement(source)


@pytest.mark.parametrize("case", _P9_P11_REFUSALS, ids=lambda case: case.predicate)
def test_oracle_p9_p11_refusal_anchors(case: _RefusalCase) -> None:
    """Concrete P9-P11 anchors fix rebinding, mark-arm, and totality boundaries."""
    assert _oracle_code(case.source) == case.code


@pytest.mark.parametrize("case", _P9_P11_REFUSALS, ids=lambda case: case.predicate)
def test_differential_p9_p11_refusal_anchors(case: _RefusalCase) -> None:
    """Production and oracle agree on every concrete P9-P11 refusal witness."""
    _assert_agreement(case.source, expected_code=case.code)


@pytest.mark.parametrize("case", _ALL_PROJECTION_REFUSALS, ids=lambda case: case.predicate)
def test_every_projection_anchor_passes_admission(case: _RefusalCase) -> None:
    """Projection-refusal witnesses form a distinct population that reaches project()."""
    assert isinstance(parse_admitted(case.source), ast.Module)


@pytest.mark.parametrize("name,template", _EXPRESSION_TEMPLATES)
def test_oracle_all_expression_shapes(name: str, template: str) -> None:
    """Every admitted math/operator/constant expression shape reaches the oracle."""
    source = _valid_source(
        grid_expression="np.linspace(0, 2 * np.pi, num=32)",
        expression_template=template,
        mark="plot",
        bind_grid=True,
        bind_y=True,
        label=None,
        title=False,
        xlabel=False,
        ylabel=False,
        legend=False,
        grid_decoration="omit",
    )
    projected = oracle_project(parse_admitted(source))
    assert isinstance(projected, FormulaPlot), name


@pytest.mark.parametrize("_name,template", _EXPRESSION_TEMPLATES)
def test_differential_all_expression_shapes(_name: str, template: str) -> None:
    """Every admitted expression family independently agrees with production."""
    source = _valid_source(
        grid_expression="np.linspace(0, 2 * np.pi, num=32)",
        expression_template=template,
        mark="plot",
        bind_grid=True,
        bind_y=True,
        label=None,
        title=False,
        xlabel=False,
        ylabel=False,
        legend=False,
        grid_decoration="omit",
    )
    _assert_agreement(source)


def test_oracle_p12_projection_is_pure() -> None:
    """P12: one AST is stable across calls; equal parses yield AST-free equal values."""
    first_tree = parse_admitted(_DECORATED)
    before = ast.dump(first_tree, include_attributes=True)
    first = oracle_project(first_tree)
    second = oracle_project(first_tree)
    third = oracle_project(parse_admitted(_DECORATED))
    assert ast.dump(first_tree, include_attributes=True) == before
    assert first == second == third
    assert not _contains_ast(first)
    assert _DECORATED not in repr(normalize(first))


def test_differential_p12_projection_is_pure() -> None:
    """Production has the same P12 purity and value-equality properties as the oracle."""
    module = _production_module()
    _assert_nonvacuous(module)
    production = _production_project(module)
    tree = parse_admitted(_DECORATED)
    before = ast.dump(tree, include_attributes=True)
    first = production(tree)
    second = production(tree)
    third = production(parse_admitted(_DECORATED))
    assert ast.dump(tree, include_attributes=True) == before
    assert first == second == third
    assert not _contains_ast(first)
    assert _DECORATED not in repr(normalize(first))
    _assert_agreement(_DECORATED)


def test_differential_modules_are_distinct() -> None:
    """The vacuity guard is an explicit test as well as the first agreement step."""
    _assert_nonvacuous(_production_module())


def test_vacuity_guard_has_positive_controls() -> None:
    """Same-file and same-function fakes prove both independence checks can fire."""
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


def test_canonical_translation_rejects_unknown_shapes() -> None:
    """The comparison boundary refuses every unmapped node class and field."""

    @dataclass(frozen=True)
    class UnknownNode:
        value: int

    @dataclass(frozen=True)
    class Num:
        value: Fraction
        extra: int

    with pytest.raises(TypeError, match="unmapped projection node"):
        normalize(UnknownNode(1))
    with pytest.raises(TypeError, match="unmapped Num fields"):
        normalize(Num(Fraction(1), 0))


@given(_VALID_SOURCES)
def test_oracle_generated_valid_programs(source: str) -> None:
    """Generated valid programs span grids, expressions, marks, binding, and decoration."""
    assert isinstance(oracle_project(parse_admitted(source)), FormulaPlot)


@given(_VALID_SOURCES)
def test_differential_generated_valid_programs(source: str) -> None:
    """Both implementations agree over the generated valid-program population."""
    _assert_agreement(source)


@given(_PROJECTION_REFUSALS)
def test_oracle_generated_projection_refusals(case: _RefusalCase) -> None:
    """Generated one-boundary near misses reach projection and yield their fixed code."""
    assert isinstance(parse_admitted(case.source), ast.Module)
    assert _oracle_code(case.source) == case.code


@given(_PROJECTION_REFUSALS)
def test_differential_generated_projection_refusals(case: _RefusalCase) -> None:
    """Both implementations agree over generated projection-refusal near misses."""
    assert isinstance(parse_admitted(case.source), ast.Module)
    _assert_agreement(case.source, expected_code=case.code)


@given(_ADMISSION_REFUSALS)
def test_generated_admission_refusals_never_reach_projection(source: str) -> None:
    """The admission-refused population stays outside every differential comparison."""
    with pytest.raises(PysrcRefusalError):
        parse_admitted(source)
