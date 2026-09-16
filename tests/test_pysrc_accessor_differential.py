# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.8 differential: independent accessor/reset oracle against production."""

import ast
import importlib
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path
from types import ModuleType
from typing import Final, cast

import pytest

import oracle_accessor as oracle_module
from oracle_accessor import (
    ACCESSOR_KEYWORDS,
    ACCESSOR_KIND_MAP,
    RESET_UNWRAPS,
    OracleProjection,
    OracleRefusal,
)
from oracle_accessor import (
    decide as oracle_decide,
)
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.project import project as production_project
from verifier.pysrc.spec import DatasetPlot

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"


@dataclass(frozen=True, slots=True)
class _Case:
    name: str
    source: str


def _source(body: str, *, path: str = "sales.csv") -> str:
    return _PRELUDE + f'df = pd.read_csv("{path}")\n' + body


def _accessor(  # noqa: PLR0913 — orthogonal generated-source axes stay explicit
    args: str,
    *,
    reduction: str = "sum",
    receiver: str = "g",
    path: str = "sales.csv",
    key: str = "region",
    value: str = "revenue",
) -> str:
    return _source(
        f'g = df.groupby("{key}")["{value}"].{reduction}()\n{receiver}.plot({args})\nplt.show()\n',
        path=path,
    )


def _series(*, reduction: str = "sum", mark: str = "bar") -> str:
    return _source(
        f'g = df.groupby("region")["revenue"].{reduction}()\n'
        f"plt.{mark}(g.index, g.values)\n"
        "plt.show()\n"
    )


def _reset(
    x: str = 'g["region"]',
    y: str = 'g["revenue"]',
    *,
    trailing: str = "reset_index",
) -> str:
    return _source(
        f'g = df.groupby("region")["revenue"].max().{trailing}()\nplt.bar({x}, {y})\nplt.show()\n'
    )


def _p1_p3_corpus() -> tuple[_Case, ...]:
    return (
        _Case("p1-bar", _accessor('kind="bar"')),
        _Case("p2-barh", _accessor('kind="barh"')),
        _Case("p2-pie", _accessor('kind="pie"')),
        _Case("p2-hist", _accessor('kind="hist"')),
        _Case("p2-line", _accessor('kind="line"')),
        _Case(
            "p2-nonliteral",
            _source(
                'chart_kind = "bar"\n'
                'g = df.groupby("region")["revenue"].sum()\n'
                "g.plot(kind=chart_kind)\n"
                "plt.show()\n"
            ),
        ),
        _Case("p2-missing", _accessor("")),
        _Case("p3-figsize", _accessor('kind="bar", figsize=(8, 5)')),
        _Case("p3-positional", _accessor('"bar"')),
    )


def _p4_p6_corpus() -> tuple[_Case, ...]:
    accessor_mark = 'g.plot(kind="bar")'
    pyplot_mark = "plt.bar(g.index, g.values)"
    return (
        _Case(
            "p4-color-weather",
            _accessor(
                'kind="bar", color="skyblue"',
                path="weather.csv",
                key="city",
                value="temperature",
            ),
        ),
        _Case("p4-dynamic-color", _accessor('kind="bar", color=df["region"]')),
        _Case("p5-frame", _source('df.plot(kind="bar")\nplt.show()\n')),
        _Case("p5-raw-column", _source('df["revenue"].plot(kind="bar")\nplt.show()\n')),
        _Case(
            "p6-accessor-first",
            _source(
                'g = df.groupby("region")["revenue"].sum()\n'
                f"{accessor_mark}\n{pyplot_mark}\nplt.show()\n"
            ),
        ),
        _Case(
            "p6-pyplot-first",
            _source(
                'g = df.groupby("region")["revenue"].sum()\n'
                f"{pyplot_mark}\n{accessor_mark}\nplt.show()\n"
            ),
        ),
    )


def _p7_r2_corpus() -> tuple[_Case, ...]:
    return (
        _Case("p7-plt-plot-wrong", _source("plt.plot_wrong(1, 2)\nplt.show()\n")),
        _Case(
            "p7-np-plot",
            _source('import numpy as np\nnp.plot(kind="bar")\nplt.show()\n'),
        ),
        _Case("p7-pd-plot", _source('pd.plot(kind="bar")\nplt.show()\n')),
        _Case("p7-unbound", _source('nosuch.plot(kind="bar")\nplt.show()\n')),
        _Case("r1-reset", _reset()),
        _Case("r1-series-twin", _series(reduction="max")),
        _Case("r2-swapped", _reset('g["revenue"]', 'g["region"]')),
        _Case("r2-missing-column", _reset(y='g["price"]')),
        _Case("r2-key-twice", _reset(y='g["region"]')),
    )


def _r3_r4_corpus() -> tuple[_Case, ...]:
    rebound = (
        _PRELUDE
        + 'g = pd.read_csv("sales.csv")\n'
        + 'g = g.groupby("region")["revenue"].max().reset_index()\n'
        + 'plt.bar(g["region"], g["revenue"])\n'
        + "plt.show()\n"
    )
    return (
        _Case("r3-sort-values", _reset(trailing="sort_values")),
        _Case("r4-rebound", rebound),
        _Case(
            "r4-no-aggregate",
            _source('g = df\nplt.bar(g["region"], g["revenue"])\nplt.show()\n'),
        ),
    )


def _corpus() -> tuple[_Case, ...]:
    return _p1_p3_corpus() + _p4_p6_corpus() + _p7_r2_corpus() + _r3_r4_corpus()


type _Verdict = str | None


def _production_admit_module() -> ModuleType:
    return importlib.import_module("verifier.pysrc.admit")


def _production_project_module() -> ModuleType:
    return importlib.import_module("verifier.pysrc.project")


def _oracle_verdict(source: str) -> _Verdict:
    decision = oracle_decide(source)
    return decision.code if isinstance(decision, OracleRefusal) else None


def _production_verdict(source: str) -> _Verdict:
    try:
        tree = parse_admitted(source)
        production_project(tree)
    except PysrcRefusalError as error:
        return str(error.code)
    return None


def _admitted(verdicts: dict[str, _Verdict]) -> frozenset[str]:
    return frozenset(name for name, verdict in verdicts.items() if verdict is None)


def _refusal_codes(verdicts: dict[str, _Verdict]) -> frozenset[tuple[str, str]]:
    return frozenset((name, verdict) for name, verdict in verdicts.items() if verdict is not None)


# Production field -> oracle field, in the canonical ORDER. Class names and field names are form
# noise across two implementations of one contract, so the correspondence is written down EXPLICITLY
# and the totality check below RAISES on a field neither mapped nor excluded: a generic
# lowercase-or-strip rule would absorb a real future divergence into agreement.
_MEANING_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("mark", "mark"),
    ("source", "path"),
    ("x", "key"),
    ("y", "value"),
    ("group", "reduction"),
)
# `labels` has no oracle counterpart: the contract gives the oracle no title, axis or legend text to
# compute. Excluded BY NAME so that a field added to `DatasetPlot` later fails loudly rather than
# going silently uncompared.
_MEANING_EXCLUDED: Final[frozenset[str]] = frozenset({"labels"})
# One explicit unwrap per mapped production field. The oracle states every channel as a bare string,
# production wraps them in `DatasetRef`/`Column`, and reaching through those wrappers generically
# would be the same absorbing rule the map exists to refuse.
_MEANING_UNWRAP: Final[dict[str, Callable[[DatasetPlot], str | None]]] = {
    "mark": lambda plot: plot.mark,
    "source": lambda plot: plot.source.path,
    "x": lambda plot: plot.x.name,
    "y": lambda plot: plot.y.name,
    "group": lambda plot: plot.group,
}


def _assert_meaning_map_is_total() -> None:
    """Every field of BOTH dataclasses is mapped or excluded by name."""
    mapped_production = {production for production, _ in _MEANING_FIELDS}
    mapped_oracle = {oracle for _, oracle in _MEANING_FIELDS}
    production_fields = {field.name for field in fields(DatasetPlot)}
    oracle_fields = {field.name for field in fields(OracleProjection)}
    assert mapped_production | _MEANING_EXCLUDED == production_fields, (
        "translation map does not cover DatasetPlot: "
        f"{sorted(production_fields ^ (mapped_production | _MEANING_EXCLUDED))!r}"
    )
    assert mapped_oracle == oracle_fields, (
        "translation map does not cover OracleProjection: "
        f"{sorted(oracle_fields ^ mapped_oracle)!r}"
    )
    assert set(_MEANING_UNWRAP) == mapped_production, (
        f"unwrap table and field map disagree: {sorted(set(_MEANING_UNWRAP) ^ mapped_production)!r}"
    )


def _oracle_projection(source: str) -> OracleProjection | None:
    decision = oracle_decide(source)
    return None if isinstance(decision, OracleRefusal) else decision


def _production_projection(source: str) -> DatasetPlot | None:
    try:
        spec = production_project(parse_admitted(source))
    except PysrcRefusalError:
        return None
    assert isinstance(spec, DatasetPlot), f"dataset corpus projected {type(spec).__name__}"
    return spec


def _oracle_meaning(projection: OracleProjection) -> tuple[str | None, ...]:
    return tuple(getattr(projection, oracle) for _, oracle in _MEANING_FIELDS)


def _production_meaning(plot: DatasetPlot) -> tuple[str | None, ...]:
    return tuple(_MEANING_UNWRAP[production](plot) for production, _ in _MEANING_FIELDS)


def _contains_bound_accessor(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "plot":
            continue
        receiver = node.func.value
        if not isinstance(receiver, ast.Name) or receiver.id not in {"plt", "np", "pd"}:
            return True
    return False


def _contains_reset(source: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "reset_index"
        for node in ast.walk(ast.parse(source))
    )


def _assert_nonvacuous(
    corpus: tuple[_Case, ...],
    *,
    project_module: ModuleType | None = None,
    admit_module: ModuleType | None = None,
) -> None:
    """Reject path aliasing and a corpus that never reaches either new idiom."""
    if project_module is None:
        project_module = _production_project_module()
    if admit_module is None:
        admit_module = _production_admit_module()
    oracle_file = Path(oracle_module.__file__).resolve()
    project_file = Path(cast("str", project_module.__file__)).resolve()
    admit_file = Path(cast("str", admit_module.__file__)).resolve()
    worktree = Path(__file__).resolve().parents[1]
    assert oracle_file not in {project_file, admit_file}, (
        "VACUOUS DIFFERENTIAL: oracle and production resolve to the same __file__"
    )
    assert oracle_file == worktree / "tests" / "oracle_accessor.py", (
        "oracle must resolve from this worktree's tests/"
    )
    assert project_file == worktree / "src" / "verifier" / "pysrc" / "project.py", (
        "production project must resolve from this worktree's src/; set PYTHONPATH"
    )
    assert admit_file == worktree / "src" / "verifier" / "pysrc" / "admit.py", (
        "production admission must resolve from this worktree's src/; set PYTHONPATH"
    )
    assert getattr(project_module, "project", None) is production_project, (
        "VACUOUS DIFFERENTIAL: compared project function differs from the checked module"
    )
    assert getattr(admit_module, "parse_admitted", None) is parse_admitted, (
        "VACUOUS DIFFERENTIAL: compared admission function differs from the checked module"
    )
    assert production_project is not oracle_decide, (
        "VACUOUS DIFFERENTIAL: production exposes the oracle decision function"
    )
    names = tuple(case.name for case in corpus)
    assert len(set(names)) == len(names), (
        "VACUOUS DIFFERENTIAL: duplicate case names collapse the compared sets"
    )
    accessor_cases = tuple(case for case in corpus if _contains_bound_accessor(case.source))
    reset_cases = tuple(case for case in corpus if _contains_reset(case.source))
    assert accessor_cases, "VACUOUS DIFFERENTIAL: corpus has no ACCESSOR program"
    assert reset_cases, "VACUOUS DIFFERENTIAL: corpus has no RESET_INDEX program"
    assert any(_oracle_verdict(case.source) is None for case in accessor_cases), (
        "VACUOUS DIFFERENTIAL: ACCESSOR corpus has no oracle-admitted positive"
    )
    assert any(_oracle_verdict(case.source) is None for case in reset_cases), (
        "VACUOUS DIFFERENTIAL: RESET_INDEX corpus has no oracle-admitted positive"
    )
    assert any(_oracle_verdict(case.source) is not None for case in corpus), (
        "VACUOUS DIFFERENTIAL: corpus has no near-miss refusal"
    )


def test_p1_oracle_accessor_equals_series_spelling() -> None:
    """P1: the accessor and `plt.bar` spelling independently project to one value."""
    assert oracle_decide(_accessor('kind="bar"')) == oracle_decide(_series())


def test_p2_oracle_kind_dispatch_is_closed() -> None:
    """P2: the hand-stated map carries exactly bar and barh; near misses refuse."""
    assert ACCESSOR_KIND_MAP == {"bar": "bar", "barh": "barh"}
    assert isinstance(oracle_decide(_accessor('kind="barh"')), OracleProjection)
    for kind in ("pie", "hist", "line"):
        assert oracle_decide(_accessor(f"kind={kind!r}")) == OracleRefusal(
            "call_target_not_admitted"
        )
    assert oracle_decide(_accessor("")) == OracleRefusal("call_target_not_admitted")


def test_p3_oracle_keyword_dispatch_is_closed() -> None:
    """P3: only kind and color exist; positional and added keywords share one refusal."""
    assert {"kind", "color"} == ACCESSOR_KEYWORDS
    assert oracle_decide(_accessor('kind="bar", figsize=(8, 5)')) == OracleRefusal(
        "keyword_not_admitted"
    )
    assert oracle_decide(_accessor('"bar"')) == OracleRefusal("keyword_not_admitted")


def test_p4_oracle_color_is_literal_only_and_discarded() -> None:
    """P4: one literal color is cosmetic; a column-valued color is refused."""
    plain = oracle_decide(_accessor('kind="bar"'))
    colored = oracle_decide(_accessor('kind="bar", color="skyblue"'))
    assert plain == colored
    assert oracle_decide(_accessor('kind="bar", color=df["region"]')) == OracleRefusal(
        "label_not_literal"
    )


def test_p5_oracle_receiver_is_a_reduced_series_only() -> None:
    """P5: a frame and a raw column both fail the same aggregate-receiver rule."""
    assert oracle_decide(_source('df.plot(kind="bar")\nplt.show()\n')) == OracleRefusal(
        "column_not_from_source"
    )
    assert oracle_decide(_source('df["revenue"].plot(kind="bar")\nplt.show()\n')) == OracleRefusal(
        "column_not_from_source"
    )


def test_p6_oracle_accessor_enters_shared_mark_counting() -> None:
    """P6: either ordering of accessor plus pyplot bar is two marks."""
    accessor_mark = 'g.plot(kind="bar")'
    pyplot_mark = "plt.bar(g.index, g.values)"
    setup = 'g = df.groupby("region")["revenue"].sum()\n'
    for marks in ((accessor_mark, pyplot_mark), (pyplot_mark, accessor_mark)):
        source = _source(setup + "\n".join(marks) + "\nplt.show()\n")
        assert oracle_decide(source) == OracleRefusal("multiple_marks")


def test_p7_oracle_alias_dispatch_stays_closed() -> None:
    """P7: aliases never become accessor receivers; one unbound receiver has its own code."""
    assert oracle_decide(_source("plt.plot_wrong(1, 2)\nplt.show()\n")) == OracleRefusal(
        "call_target_not_admitted"
    )
    np_source = _source('import numpy as np\nnp.plot(kind="bar")\nplt.show()\n')
    pd_source = _source('pd.plot(kind="bar")\nplt.show()\n')
    for source in (np_source, pd_source):
        assert oracle_decide(source) == OracleRefusal("call_target_not_admitted")
    assert oracle_decide(_source('nosuch.plot(kind="bar")\nplt.show()\n')) == OracleRefusal(
        "name_not_bound"
    )


def test_r1_oracle_reset_frame_equals_series_spelling() -> None:
    """R1: named reset-frame subscripts and series channels project to one value."""
    assert oracle_decide(_reset()) == oracle_decide(_series(reduction="max"))


def test_r2_oracle_reset_channels_are_key_then_value() -> None:
    """R2: swapped, missing, and key-twice channels all fail the same source rule."""
    sources = (
        _reset('g["revenue"]', 'g["region"]'),
        _reset(y='g["price"]'),
        _reset(y='g["region"]'),
    )
    assert all(
        oracle_decide(source) == OracleRefusal("column_not_from_source") for source in sources
    )


def test_r3_oracle_unwrap_dispatch_is_reset_index_only() -> None:
    """R3: the exact unwrap set is reset_index; sort_values remains unprojected."""
    assert {"reset_index"} == RESET_UNWRAPS
    assert oracle_decide(_reset(trailing="sort_values")) == OracleRefusal(
        "aggregation_not_projected"
    )


def test_r4_oracle_reset_name_does_not_enter_raw_columns() -> None:
    """R4: rebinding and a non-aggregate frame alias retain separate closed refusals."""
    cases = {case.name: case.source for case in _r3_r4_corpus()}
    assert oracle_decide(cases["r4-rebound"]) == OracleRefusal("name_rebound")
    assert oracle_decide(cases["r4-no-aggregate"]) == OracleRefusal("column_not_from_source")


def test_differential_guard_is_loud_and_has_positive_controls() -> None:
    """Path aliasing and either missing idiom make the differential fail before comparison."""
    corpus = _corpus()
    _assert_nonvacuous(corpus)

    same_file = ModuleType("same_file")
    same_file.__file__ = oracle_module.__file__
    same_file.__dict__["project"] = oracle_decide
    with pytest.raises(AssertionError, match="same __file__"):
        _assert_nonvacuous(corpus, project_module=same_file)

    without_accessor = tuple(case for case in corpus if not _contains_bound_accessor(case.source))
    with pytest.raises(AssertionError, match="ACCESSOR"):
        _assert_nonvacuous(without_accessor)

    without_reset = tuple(case for case in corpus if not _contains_reset(case.source))
    with pytest.raises(AssertionError, match="RESET_INDEX"):
        _assert_nonvacuous(without_reset)


def test_differential_p1_r4_admitted_sets_agree() -> None:
    """The generated P1-R4 corpus yields the same admitted case-name set on both sides."""
    corpus = _corpus()
    _assert_nonvacuous(corpus)
    oracle = {case.name: _oracle_verdict(case.source) for case in corpus}
    production = {case.name: _production_verdict(case.source) for case in corpus}
    oracle_admitted = _admitted(oracle)
    production_admitted = _admitted(production)
    assert oracle_admitted == production_admitted, (
        "admitted-set disagreement: "
        f"oracle_only={sorted(oracle_admitted - production_admitted)!r}, "
        f"production_only={sorted(production_admitted - oracle_admitted)!r}"
    )


def test_differential_p1_r4_refusal_codes_agree() -> None:
    """Common refusals retain contract codes; no source or projection text is compared."""
    corpus = _corpus()
    _assert_nonvacuous(corpus)
    oracle = {case.name: _oracle_verdict(case.source) for case in corpus}
    production = {case.name: _production_verdict(case.source) for case in corpus}
    oracle_refusals = _refusal_codes(oracle)
    production_refusals = _refusal_codes(production)
    assert oracle_refusals == production_refusals, (
        "refusal-code disagreement: "
        f"oracle_only={sorted(oracle_refusals - production_refusals)!r}, "
        f"production_only={sorted(production_refusals - oracle_refusals)!r}"
    )


def test_differential_p1_r4_projected_meaning_agrees() -> None:
    """Every case BOTH sides admit projects to ONE canonical meaning, field by mapped field.

    The two differentials above compare a decision and its code, so a projection drawing the wrong
    chart from the right refusal set passes them both: hardcoding the accessor's mark to `bar`
    leaves them green because `p2-barh` still refuses nothing. This is the comparison the
    projection law asks for -- one named map onto a canonical tuple in a fixed field order, raising
    on a field it does not cover -- and it is what makes the two implementations disagree about
    MEANING rather than about form. The distinct-meaning assert is its own vacuity guard: a
    production that returned one constant spec would agree with a constant oracle."""
    corpus = _corpus()
    _assert_nonvacuous(corpus)
    _assert_meaning_map_is_total()
    compared: dict[str, tuple[tuple[str | None, ...], tuple[str | None, ...]]] = {}
    for case in corpus:
        oracle = _oracle_projection(case.source)
        production = _production_projection(case.source)
        if oracle is None or production is None:
            continue
        compared[case.name] = (_oracle_meaning(oracle), _production_meaning(production))
    assert compared, "VACUOUS DIFFERENTIAL: no corpus case is admitted by both sides"
    assert len({meaning for meaning, _ in compared.values()}) > 1, (
        "VACUOUS DIFFERENTIAL: every compared case carries the same meaning"
    )
    disagreements = {
        name: {"oracle": oracle, "production": production}
        for name, (oracle, production) in compared.items()
        if oracle != production
    }
    assert not disagreements, f"projected-meaning disagreement: {disagreements!r}"
