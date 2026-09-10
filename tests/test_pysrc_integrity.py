# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Graphical-integrity tripwires for the G-rules that hold BY CONSTRUCTION.

Contract: `.agent/archive/contracts/m13u3.md`. Each test asserts BOTH halves — the target is
absent from the allowlist AND a program using it is refused — so widening `admit.py` breaks the
rule's test instead of silently deleting the rule. Rule text: `.claude/rules/pysrc.md` § Integrity
rule set.
"""

import pytest

from verifier.pysrc.admit import ADMITTED_CALL_TARGETS, ADMITTED_KEYWORDS, parse_admitted
from verifier.pysrc.errors import PysrcRefusalError

_PRELUDE = "import numpy as np\nimport matplotlib.pyplot as plt\n"
_PLOT = "x = np.arange(3)\ny = np.sin(x)\nplt.plot(x, y)\n"


def _admission_code(body: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(_PRELUDE + body)
    return str(caught.value.code)


def test_g1_bar_baseline_unreachable() -> None:
    """`plt.ylim` is absent; a limit after an otherwise-admitted bar refuses by target."""
    assert "plt.ylim" not in ADMITTED_CALL_TARGETS
    bar = "x = np.arange(3)\ny = np.sin(x)\nplt.bar(x, y)\n"
    parse_admitted(_PRELUDE + bar + "plt.show()\n")
    assert _admission_code(bar + "plt.ylim(50, 100)\nplt.show()\n") == "call_target_not_admitted"


def test_g2_single_axes() -> None:
    """Every named multi-Axes constructor is absent and refuses beside an admitted plot."""
    targets = {
        "plt.twinx",
        "plt.subplots",
        "plt.subplot",
        "plt.gca",
        "plt.figure",
    }
    assert not (targets & ADMITTED_CALL_TARGETS)
    parse_admitted(_PRELUDE + _PLOT + "plt.show()\n")
    assert {
        target: _admission_code(_PLOT + f"{target}()\nplt.show()\n") for target in targets
    } == dict.fromkeys(targets, "call_target_not_admitted")


def test_g3_linear_scale_only() -> None:
    """Scale-changing calls are absent and refuse beside an admitted linear plot."""
    calls = {
        "plt.yscale": 'plt.yscale("log")',
        "plt.xscale": 'plt.xscale("log")',
        "plt.semilogy": "plt.semilogy(x, y)",
        "plt.loglog": "plt.loglog(x, y)",
    }
    assert not (set(calls) & ADMITTED_CALL_TARGETS)
    parse_admitted(_PRELUDE + _PLOT + "plt.show()\n")
    assert {
        target: _admission_code(_PLOT + f"{call}\nplt.show()\n") for target, call in calls.items()
    } == dict.fromkeys(calls, "call_target_not_admitted")


def test_g6_scatter_size_keyword_unreachable() -> None:
    """Scatter admits only literal `label`; a bound `s=v` size refuses by keyword."""
    assert ADMITTED_KEYWORDS["plt.scatter"] == frozenset({"label"})
    body = "x = np.arange(3)\ny = np.sin(x)\nv = 3\n"
    parse_admitted(_PRELUDE + body + 'plt.scatter(x, y, label="series")\nplt.show()\n')
    assert _admission_code(body + "plt.scatter(x, y, s=v)\nplt.show()\n") == "keyword_not_admitted"


# --- M13.5: the three rules recomputation made decidable ---------------------------------------
# Contract: `.agent/archive/contracts/m13u5.md` § G.


def test_g7_plotted_range_is_the_data_range() -> None:
    """No filter, slice, mask or head/tail idiom exists, so the plotted column IS the column.

    Accept: a pin that goes RED if `admit.py` ever admits `.loc .iloc .query .head .tail .dropna
    .sample`, boolean masking or slicing -- the G1/G2/G3 both-halves shape.
    """
    blocked_targets = {
        "df.loc",
        "df.iloc",
        "df.query",
        "df.head",
        "df.tail",
        "df.dropna",
        "df.sample",
    }
    assert not (blocked_targets & ADMITTED_CALL_TARGETS)
    prelude = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("measurements.csv")\n'
    )
    tail = 'plt.bar(df["site"], df["value"])\nplt.show()\n'
    parse_admitted(prelude + tail)
    blocked = {
        'filtered = df.loc["west"]\n': "expression_not_admitted",
        "filtered = df.iloc[0]\n": "expression_not_admitted",
        'filtered = df.query("value > 0")\n': "call_target_not_admitted",
        "filtered = df.head(1)\n": "call_target_not_admitted",
        "filtered = df.tail(1)\n": "call_target_not_admitted",
        "filtered = df.dropna()\n": "call_target_not_admitted",
        "filtered = df.sample(1)\n": "call_target_not_admitted",
        'filtered = df["site"][0:1]\n': "expression_not_admitted",
        'filtered = df[df["value"] > 0]\n': "column_not_literal",
    }
    for filtering, expected in blocked.items():
        with pytest.raises(PysrcRefusalError) as caught:
            parse_admitted(prelude + filtering + tail)
        assert caught.value.code == expected, filtering


def test_g8_point_count_is_the_row_count() -> None:
    """No null survives (C9) and `bar` over a categorical x requires UNIQUE categories.

    Accept: the allowlist pin as in G7, plus a duplicate-category witness refusing
    `category_not_unique` -- duplicates overplot, so the figure would show fewer bars than rows.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415
    from verifier.pysrc.spec import DatasetTarget  # noqa: PLC0415

    blocked_targets = {"df.dropna", "df.query", "df.head", "df.tail"}
    assert not (blocked_targets & ADMITTED_CALL_TARGETS)
    prelude = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("measurements.csv")\n'
    )
    tail = 'plt.bar(df["site"], df["value"])\nplt.show()\n'
    for filtering, expected in (
        ("clean = df.dropna()\n", "call_target_not_admitted"),
        ('clean = df[df["value"] > 0]\n', "column_not_literal"),
    ):
        with pytest.raises(PysrcRefusalError) as caught:
            parse_admitted(prelude + filtering + tail)
        assert caught.value.code == expected

    duplicate = verify_python_source(
        prelude + tail,
        declared_target=DatasetTarget(path="measurements.csv", content=b"site,value\na,1\na,2\n"),
    )
    unique = verify_python_source(
        prelude + tail,
        declared_target=DatasetTarget(path="measurements.csv", content=b"site,value\na,1\nb,2\n"),
    )
    assert isinstance(duplicate, Refused)
    assert duplicate.code == "category_not_unique"
    assert isinstance(unique, Verified)


def test_g9_line_x_is_ordered() -> None:
    """`line` takes x numeric and NON-DECREASING, or categorical with UNIQUE categories in file
    order. Uniform spacing is NOT required; `scatter` still requires numeric x.

    Accept: ordered, unordered, duplicate-numeric-x-but-ordered, unique-categorical and
    repeated-categorical witnesses. The IRREGULARLY-SPACED-but-ordered case must VERIFY --
    irregular spacing is legible in the rendered figure, so it misrepresents nothing. The two
    refusals carry DIFFERENT codes and that split is the point: non-monotonic numeric x refuses
    `x_not_ordered`, while a repeated category refuses `category_not_unique`, the same code G8
    uses for `bar`. The fault there is the repetition itself -- the marks overplot -- and a line
    additionally doubles back over itself; ordering is not what is wrong with it.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415
    from verifier.pysrc.spec import DatasetTarget  # noqa: PLC0415

    source = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("measurements.csv")\n'
        'plt.plot(df["x"], df["y"])\n'
        "plt.show()\n"
    )

    def verdict(content: bytes) -> object:
        return verify_python_source(
            source,
            declared_target=DatasetTarget(path="measurements.csv", content=content),
        )

    ordered = verdict(b"x,y\n1,10\n2,20\n3,30\n")
    irregular = verdict(b"x,y\n1,10\n2,20\n10,30\n")
    duplicate_numeric = verdict(b"x,y\n1,10\n1,20\n2,30\n")
    unique_categorical = verdict(b"x,y\nfirst,10\nthird,20\nsecond,30\n")
    for result in (ordered, irregular, duplicate_numeric, unique_categorical):
        assert isinstance(result, Verified)

    for content, expected_code in (
        (b"x,y\n1,10\n3,30\n2,20\n", "x_not_ordered"),
        (b"x,y\nfirst,10\nsecond,20\nfirst,30\n", "category_not_unique"),
    ):
        result = verdict(content)
        assert isinstance(result, Refused), content
        assert result.code == expected_code, content

    scatter = source.replace("plt.plot", "plt.scatter")
    categorical_scatter = verify_python_source(
        scatter,
        declared_target=DatasetTarget(
            path="measurements.csv", content=b"x,y\nfirst,10\nsecond,20\n"
        ),
    )
    assert isinstance(categorical_scatter, Refused)
    assert categorical_scatter.code == "column_not_numeric"
