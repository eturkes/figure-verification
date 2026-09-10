# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Diff-blind red suite for M13.3 projection. Contract: `.agent/archive/contracts/m13u3.md`.

Every test below carries its predicate's acceptance check in the docstring and is skipped until it
is written. A test that asserts more than the ratified predicate loses to the predicate.
"""

import ast
import sys
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import pytest

from verifier.pysrc import spec
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.project import project

_PRELUDE = "import numpy as np\nimport matplotlib.pyplot as plt\n"


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


def _only_node[T](root: object, node_type: type[T]) -> T:
    matches = [node for node in _walk_nodes(root) if isinstance(node, node_type)]
    assert len(matches) == 1
    return matches[0]


def _formula(body: str) -> ast.Module:
    return parse_admitted(_PRELUDE + body)


def _project_code(tree: ast.Module) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        project(tree)
    return str(caught.value.code)


def test_p1_no_mark_refuses() -> None:
    """Empty and admitted decoration-only programs refuse `no_mark`."""
    decoration_only = parse_admitted(
        'import matplotlib.pyplot as plt\nplt.title("decoration only")\nplt.show()\n'
    )
    assert _project_code(parse_admitted("")) == "no_mark"
    assert _project_code(decoration_only) == "no_mark"


def test_p2_exactly_one_mark() -> None:
    """Two `plt.plot` calls refuse `multiple_marks`; one projects to a spec."""
    one = _formula("x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n")
    two = _formula(
        "x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\nplt.plot(x, y)\nplt.show()\n"
    )
    assert isinstance(project(one), spec.FormulaPlot)
    assert _project_code(two) == "multiple_marks"


def test_p3_x_resolves_to_grid() -> None:
    """`plt.plot(3, y)` refuses; equivalent bound and fully inline grids project equally."""
    bound = _formula("x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n")
    inline = _formula(
        "plt.plot(np.linspace(0, 1, num=5), np.sin(np.linspace(0, 1, num=5)))\nplt.show()\n"
    )
    not_grid = _formula("x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(3, y)\nplt.show()\n")
    assert project(bound) == project(inline)
    assert _project_code(not_grid) == "x_not_a_grid"


def test_p4_y_over_grid_only() -> None:
    """Y is over THE grid by VALUE: an equal grid resolves, an unequal one refuses.

    Grid identity is structural, so the spelling of the reference is irrelevant and only the
    sample points decide. The two refusals cover both routes into y -- a bound name and a
    repeated call -- because a guard on either one alone survives a mutant that neuters it."""
    bound = _formula("x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n")
    second_grid = _formula(
        "x = np.linspace(0, 1, num=5)\nz = np.arange(5)\nplt.plot(x, z)\nplt.show()\n"
    )
    inline_x_bound_y = _formula(
        "x = np.linspace(0, 1, num=5)\ny = np.sin(x)\n"
        "plt.plot(np.linspace(0, 1, num=5), y)\nplt.show()\n"
    )
    unequal_inline_in_y = _formula(
        "plt.plot(np.linspace(0, 1, num=5), np.sin(np.linspace(0, 2, num=5)))\nplt.show()\n"
    )
    assert project(inline_x_bound_y) == project(bound)
    alias_as_value = _formula("x = np.linspace(0, 1, num=5)\nplt.plot(x, np)\nplt.show()\n")
    assert _project_code(second_grid) == "y_not_over_grid"
    assert _project_code(unequal_inline_in_y) == "y_not_over_grid"
    assert _project_code(alias_as_value) == "expression_not_projected"


def test_p5_grid_forms_agree() -> None:
    """Grid is `(start, inclusive stop, samples)` with exact normalization and literals."""

    def projected(grid_call: str) -> spec.CorePlotSpec:
        return project(_formula(f"x = {grid_call}\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n"))

    linspace = projected("np.linspace(0, 9, num=10)")
    arange = projected("np.arange(0, 10)")
    arange_grid = _only_node(arange, spec.Grid)
    assert linspace == arange
    assert (
        _only_node(arange_grid.start, Fraction),
        _only_node(arange_grid.stop, Fraction),
        arange_grid.samples,
    ) == (Fraction(0), Fraction(9), 10)

    linspace_default = projected("np.linspace(0, 49)")
    arange_default = projected("np.arange(0, 50)")
    assert linspace_default == projected("np.linspace(0, 49, num=50)")
    assert arange_default == projected("np.arange(0, 50, 1)")
    assert linspace_default == arange_default
    assert linspace_default != projected("np.linspace(0, 49, num=51)")
    assert arange_default != projected("np.arange(0, 50, 2)")

    symbolic_pi = projected("np.linspace(0, np.pi, num=10)")
    float_pi = projected("np.linspace(0, 3.141592653589793, num=10)")
    assert symbolic_pi != float_pi
    for grid_call in ("np.arange(0, np.pi)", "np.arange(0, 10, np.pi)"):
        assert (
            _project_code(_formula(f"x = {grid_call}\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n"))
            == "grid_not_representable"
        )

    # numpy sizes and accumulates `arange` in float64, so a non-integer step draws a different
    # NUMBER of samples than the exact grid says -- measured, `arange(0, 3, 0.3)` draws 10 ending
    # 2.6999999999999997 where the exact grid says 11 ending 3. Integers keep it faithful, and a
    # negated literal folds so a descending range stays reachable.
    for grid_call in ("np.arange(0, 3, 0.3)", "np.arange(0.1, 0.4, 0.1)", "np.arange(0, 1, 0.1)"):
        assert (
            _project_code(_formula(f"x = {grid_call}\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n"))
            == "grid_not_representable"
        )
    descending = _only_node(projected("np.arange(5, 0, -1)"), spec.Grid)
    assert (
        _only_node(descending.start, Fraction),
        _only_node(descending.stop, Fraction),
        descending.samples,
    ) == (Fraction(5), Fraction(1), 5)
    assert projected("np.arange(0.0, 10.0, 1.0)") == projected("np.arange(0, 10)")

    float_grid = _only_node(projected("np.linspace(0.1, 0.2, num=2)"), spec.Grid)
    projected_tenth = _only_node(float_grid.start, Fraction)
    assert projected_tenth == Fraction(0.1)
    assert projected_tenth != Fraction(1, 10)


def test_p6_sample_count_representable() -> None:
    """Samples are exact int literals in the hand-stated inclusive range 2..100_000."""

    def linspace(num: str) -> ast.Module:
        return _formula(
            f"x = np.linspace(0, 1, num={num})\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n"
        )

    for samples in (2, 100_000):
        grid = _only_node(project(linspace(str(samples))), spec.Grid)
        assert grid.samples == samples

    non_literal = _formula(
        "n = 2\nx = np.linspace(0, 1, num=n)\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n"
    )
    invalid = (
        linspace("0"),
        linspace("1"),
        linspace("2.5"),
        linspace("True"),
        non_literal,
        linspace("100_001"),
    )
    given_twice = _formula(
        "x = np.linspace(0, 1, 5, num=7)\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n"
    )
    assert [_project_code(tree) for tree in invalid] == ["grid_not_representable"] * 6
    assert _project_code(given_twice) == "grid_not_representable"


def test_p7_labels_are_literals() -> None:
    """Every decoration changes labels; literal text survives and a grid-valued title refuses."""
    body = "x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\n"
    plain = project(_formula(body + "plt.show()\n"))
    decorated = {
        "title": project(_formula(body + 'plt.title("title literal")\nplt.show()\n')),
        "xlabel": project(_formula(body + 'plt.xlabel("x literal")\nplt.show()\n')),
        "ylabel": project(_formula(body + 'plt.ylabel("y literal")\nplt.show()\n')),
        "legend": project(_formula(body + "plt.legend()\nplt.show()\n")),
        "grid": project(_formula(body + "plt.grid(True)\nplt.show()\n")),
    }
    assert all(projected != plain for projected in decorated.values())
    assert all(isinstance(projected, spec.FormulaPlot) for projected in decorated.values())
    assert decorated["title"].labels.title == "title literal"
    assert "x literal" in tuple(_walk_nodes(decorated["xlabel"].labels))
    assert "y literal" in tuple(_walk_nodes(decorated["ylabel"].labels))

    non_literal = _formula(body + "plt.title(x)\nplt.show()\n")
    repeated = _formula(body + 'plt.title("first")\nplt.title("second")\nplt.show()\n')
    assert _project_code(non_literal) == "label_not_literal"
    assert _project_code(repeated) == "statement_not_projected"


def test_p8_single_terminal_last() -> None:
    """One final `show` projects; zero or any statement after a `show` refuses."""
    body = "x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\n"
    valid = _formula(body + "plt.show()\n")
    no_terminal = _formula(body)
    statement_after = _formula(body + 'plt.show()\nplt.title("late")\n')
    two_terminals = _formula(body + "plt.show()\nplt.show()\n")

    assert isinstance(project(valid), spec.FormulaPlot)
    assert _project_code(no_terminal) == "no_terminal"
    assert _project_code(statement_after) == "statement_after_terminal"
    assert _project_code(two_terminals) == "statement_after_terminal"


def test_p9_no_rebinding() -> None:
    """Distinct bindings project; a second binding of `x` refuses `name_rebound`."""
    distinct = _formula("x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n")
    rebound = _formula(
        "x = np.linspace(0, 1, num=5)\nx = np.arange(5)\ny = np.sin(x)\n"
        "plt.plot(x, y)\nplt.show()\n"
    )
    assert isinstance(project(distinct), spec.FormulaPlot)
    assert _project_code(rebound) == "name_rebound"


def test_p10_bar_refused_in_formula_arm() -> None:
    """Scatter over a sampled function projects; bar over the same values refuses by arm."""
    body = "x = np.linspace(0, 1, num=5)\ny = np.sin(x)\n"
    scatter = _formula(body + "plt.scatter(x, y)\nplt.show()\n")
    bar = _formula(body + "plt.bar(x, y)\nplt.show()\n")
    assert isinstance(project(scatter), spec.FormulaPlot)
    assert _project_code(bar) == "mark_not_valid_for_arm"


def test_p11_total_statement_coverage() -> None:
    """A fully consumed program projects; an otherwise-unused assignment refuses."""
    body = "x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n"
    covered = _formula(body)
    unprojected = _formula("unused = 7\n" + body)
    discarded_call = _formula(
        "x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nnp.cos(x)\nplt.plot(x, y)\nplt.show()\n"
    )
    assert isinstance(project(covered), spec.FormulaPlot)
    assert _project_code(unprojected) == "statement_not_projected"
    assert _project_code(discarded_call) == "statement_not_projected"


def test_p12_projection_is_pure() -> None:
    """Equal trees give data-only specs; portable core source retains no forbidden coupling."""
    source = _PRELUDE + (
        "x = np.linspace(0, 1, num=5)\ny = np.sin(x)\nplt.plot(x, y)\nplt.show()\n"
    )
    first_tree = parse_admitted(source)
    second_tree = parse_admitted(source)
    first = project(first_tree)

    assert first == project(first_tree) == project(second_tree)
    nodes = tuple(_walk_nodes(first))
    assert not any(isinstance(node, ast.AST) for node in nodes)
    assert source not in nodes
    assert not any(
        isinstance(node, str) and ("import numpy as np" in node or "plt.show()" in node)
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
    package_sources = {
        path: path.read_text(encoding="utf-8") for path in sorted(spec_path.parent.glob("*.py"))
    }
    imported_roots: set[str] = set()
    for module_source in package_sources.values():
        for node in ast.walk(ast.parse(module_source)):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    imported_roots.add("__intra_package__")
                elif node.module is not None:
                    imported_roots.add(node.module.partition(".")[0])

    intra_package = {"__intra_package__", "verifier"}
    allowed_import_roots = {
        "__intra_package__",
        "ast",
        "collections",
        "dataclasses",
        "fractions",
        "io",
        "math",
        "tokenize",
        "typing",
        "verifier",
    }
    assert imported_roots <= allowed_import_roots
    assert allowed_import_roots - intra_package <= sys.stdlib_module_names

    package_text = "\n".join(package_sources.values())
    forbidden_payload = {"prompt_text", "prompt_hash", "sample_fields", "raw_model_reply"}
    assert not [term for term in forbidden_payload if term in package_text]


def test_p13_every_projection_refusal_path_is_reachable() -> None:
    """Each remaining projection guard refuses a concrete admitted program.

    A guard with no witness is indistinguishable from a guard that cannot fire, so every path the
    predicates above do not already reach gets one source here. Positives ride along where the
    same branch has an admitting side."""
    grid = "x = np.linspace(0, 1, num=5)\n"
    tail = "plt.show()\n"

    def code(body: str) -> str:
        return _project_code(_formula(body))

    # Expression paths: non-finite float, non-numeric literal, wrong call shape, arithmetic.
    assert code(grid + f"plt.plot(x, 1e999)\n{tail}") == "expression_not_projected"
    assert code(grid + f'plt.plot(x, "text")\n{tail}') == "expression_not_projected"
    assert code(grid + f"plt.plot(x, np.sin(x, x))\n{tail}") == "expression_not_projected"
    arithmetic = project(_formula(grid + f"plt.plot(x, 2 * x + np.pi)\n{tail}"))
    assert isinstance(arithmetic, spec.FormulaPlot)
    assert arithmetic.y == spec.Bin(
        "add", spec.Bin("mul", spec.Num(Fraction(2)), spec.Var()), spec.Const("pi")
    )

    # Grid call shapes.
    positional = _formula(f"x = np.linspace(0, 1, 5)\ny = np.sin(x)\nplt.plot(x, y)\n{tail}")
    assert _only_node(project(positional), spec.Grid).samples == 5
    assert code(f"x = np.linspace(0)\ny = np.sin(x)\nplt.plot(x, y)\n{tail}") == (
        "grid_not_representable"
    )
    assert (
        code(f"x = np.arange()\ny = np.sin(x)\nplt.plot(x, y)\n{tail}") == "grid_not_representable"
    )
    assert (
        code(f"x = np.arange(0, 5, 1, 2)\ny = np.sin(x)\nplt.plot(x, y)\n{tail}")
        == "grid_not_representable"
    )
    assert code(f"x = np.arange(0, 5, 0)\ny = np.sin(x)\nplt.plot(x, y)\n{tail}") == (
        "grid_not_representable"
    )
    assert code(f"x = np.arange(5, 0)\ny = np.sin(x)\nplt.plot(x, y)\n{tail}") == (
        "grid_not_representable"
    )

    # Decoration shapes.
    plot = grid + "y = np.sin(x)\nplt.plot(x, y)\n"
    assert code(plot + f'plt.title("a", "b")\n{tail}') == "label_not_literal"
    assert code(plot + f"plt.grid(True, False)\n{tail}") == "label_not_literal"
    assert code(plot + f'plt.grid("on")\n{tail}') == "label_not_literal"
    assert code(plot + f"plt.show(1)\n{tail}") == "statement_not_projected"

    # Mark arity and the series label.
    assert code(grid + f"y = np.sin(x)\nplt.plot(x)\n{tail}") == "mark_arity_not_projected"
    assert code(grid + f"y = np.sin(x)\nplt.plot(x, y, label=x)\n{tail}") == "label_not_literal"
    labelled = project(_formula(grid + f'y = np.sin(x)\nplt.plot(x, y, label="s")\n{tail}'))
    assert isinstance(labelled, spec.FormulaPlot)
    assert labelled.labels.series == "s"
