# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.10 line-accessor width; `.agent/archive/contracts/m10u10.md` predicates A1-A8.

The accessor is another spelling of `plt.plot(g.index, g.values)`. Closed maps, receiver rules,
mark cardinality, recomputed values and certificate interpretation remain independently pinned.
"""

from pathlib import Path
from typing import get_args

import pytest

from verifier.pysrc import Refused, Verified, verify_python_source
from verifier.pysrc.admit import (
    ADMITTED_ACCESSOR_KEYWORDS,
    ADMITTED_ACCESSOR_KINDS,
    parse_admitted,
)
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.project import project
from verifier.pysrc.spec import CorePlotSpec, DatasetPlot, DatasetTarget
from webui.paste_in import observe

_ROOT = Path(__file__).resolve().parents[1]
_PRELUDE = 'import pandas as pd\nimport matplotlib.pyplot as plt\ndf = pd.read_csv("sales.csv")\n'


def _source(marks: str, *, key: str = "region", reduction: str = "sum") -> str:
    return (
        _PRELUDE + f'g = df.groupby("{key}")["revenue"].{reduction}()\n' + marks + "\nplt.show()\n"
    )


def _code(source: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        project(parse_admitted(source))
    return str(caught.value.code)


def _verify(source: str) -> Verified | Refused:
    return verify_python_source(
        source,
        declared_target=DatasetTarget("sales.csv", (_ROOT / "data/sales.csv").read_bytes()),
    )


@pytest.mark.parametrize("key", ("month", "orders"))
@pytest.mark.parametrize("reduction", ("sum", "mean", "min", "max"))
def test_a1_line_accessor_projects_equal_to_the_plt_plot_spelling(key: str, reduction: str) -> None:
    """A1: all eight reduction/key pairs have equal specs, tables and interpretation bytes."""
    direct = _source("plt.plot(g.index, g.values)", key=key, reduction=reduction)
    accessor = _source('g.plot(kind="line")', key=key, reduction=reduction)
    expected = project(parse_admitted(direct))
    assert isinstance(expected, DatasetPlot)
    assert project(parse_admitted(accessor)) == expected
    direct_verdict = _verify(direct)
    accessor_verdict = _verify(accessor)
    assert isinstance(direct_verdict, Verified), direct_verdict
    assert isinstance(accessor_verdict, Verified), accessor_verdict
    assert accessor_verdict.table == direct_verdict.table
    assert accessor_verdict.certificate.interpretation.encode("utf-8") == (
        direct_verdict.certificate.interpretation.encode("utf-8")
    )


def test_a2_the_admitted_kind_map_is_bar_barh_and_line() -> None:
    """A2: the hand-stated three-entry map and the projected line mark are exact."""
    assert ADMITTED_ACCESSOR_KINDS == {"bar": "plt.bar", "barh": "plt.barh", "line": "plt.plot"}
    projected = project(parse_admitted(_source('g.plot(kind="line")')))
    assert isinstance(projected, DatasetPlot)
    assert projected.mark == "line"


@pytest.mark.parametrize(
    "arguments",
    (
        'kind="area"',
        'kind="scatter"',
        'kind="hist"',
        'kind="pie"',
        'kind="Line"',
        'kind="line "',
        "kind=chart_kind",
        "",
    ),
)
def test_a3_near_miss_kinds_refuse_call_target_not_admitted(arguments: str) -> None:
    """A3: the six near-miss literals, a bound nonliteral and missing kind remain refused."""
    source = _source(f'chart_kind = "line"\ng.plot({arguments})')
    assert _code(source) == "call_target_not_admitted"


@pytest.mark.parametrize(
    ("arguments", "expected"),
    (
        ('kind="line", marker="o"', "keyword_not_admitted"),
        ('kind="line", linestyle="--"', "keyword_not_admitted"),
        ('kind="line", label="x"', "keyword_not_admitted"),
        ('kind="line", figsize=(8, 5)', "keyword_not_admitted"),
        ('"line"', "keyword_not_admitted"),
        ('kind="line", color="red"', None),
        ('color="red", kind="line"', None),
    ),
)
def test_a4_the_accessor_keyword_set_is_unchanged(arguments: str, expected: str | None) -> None:
    """A4: exact keyword set; five refusals; a literal color verifies in either keyword order."""
    assert {"kind", "color"} == ADMITTED_ACCESSOR_KEYWORDS
    source = _source(f"g.plot({arguments})")
    if expected is None:
        assert isinstance(_verify(source), Verified)
    else:
        assert _code(source) == expected


@pytest.mark.parametrize(
    ("line", "bar", "expected"),
    (
        (
            'df["revenue"].plot(kind="line")',
            'df["revenue"].plot(kind="bar")',
            "column_not_from_source",
        ),
        ('g["US"].plot(kind="line")', 'g["US"].plot(kind="bar")', "column_not_from_source"),
        (
            'r = df.groupby("region")["revenue"].sum().reset_index()\nr.plot(kind="line")',
            'r = df.groupby("region")["revenue"].sum().reset_index()\nr.plot(kind="bar")',
            "column_not_from_source",
        ),
        ('df.plot(kind="line")', 'df.plot(kind="bar")', "column_not_from_source"),
        ("g.plot.line()", "g.plot.bar()", "attribute_not_admitted"),
    ),
    ids=("raw-column", "subscripted-reduction", "reset-frame", "frame", "attribute-chain"),
)
def test_a5_receiver_rules_match_the_bar_twin(line: str, bar: str, expected: str) -> None:
    """A5: four non-series receivers and the attribute-chain form match their bar-twin codes."""
    assert _code(_source(bar)) == expected
    assert _code(_source(line)) == expected


@pytest.mark.parametrize(
    "marks",
    (
        'g.plot(kind="line")\nplt.bar(g.index, g.values)',
        'g.plot(kind="line")\ng.plot(kind="bar")',
        'plt.plot(g.index, g.values)\ng.plot(kind="line")',
    ),
    ids=("accessor-direct-bar", "accessor-accessor-bar", "direct-line-accessor"),
)
def test_a6_a_line_accessor_is_one_mark(marks: str) -> None:
    """A6: all three mixed spellings refuse multiple_marks, independently of their order."""
    assert _code(_source(marks)) == "multiple_marks"


@pytest.mark.parametrize("kind", ("line", "bar"))
def test_a7_the_int32_renderer_bound_binds_bars_alone(kind: str) -> None:
    """A7: in-profile integer cells sum beyond int32; line verifies, bar refuses the profile."""
    content = b"key,value\na,2147483647\na,2147483647\nb,-2147483648\nb,-2147483648\n"
    source = (
        'import pandas as pd\nimport matplotlib.pyplot as plt\ndf = pd.read_csv("wide.csv")\n'
        'g = df.groupby("key")["value"].sum()\n'
        f'g.plot(kind="{kind}")\nplt.show()\n'
    )
    verdict = verify_python_source(source, declared_target=DatasetTarget("wide.csv", content))
    if kind == "line":
        assert isinstance(verdict, Verified), verdict
        assert verdict.table.y == (4294967294.0, -4294967296.0)
    else:
        assert isinstance(verdict, Refused), verdict
        assert verdict.code == "value_not_in_profile"


def test_a8_the_width_invariants_hold() -> None:
    """A8: 55 refusal codes, two spec members and four reader keys, all hand-stated."""
    assert len(get_args(RefusalCode)) == 55
    assert len(get_args(CorePlotSpec.__value__)) == 2
    assert set(observe.READERS) == {"line", "scatter", "bar", "barh"}
