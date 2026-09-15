# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.6 presentation: the data-effect-free cosmetic cluster, and the G-rows this width re-pins.

Contract: `.agent/archive/contracts/m13u6.md` predicate group W, plus G2r and G78r. Each
docstring carries its predicate's acceptance check; the contract's wording wins wherever a body
would assert more.

These calls are admitted WITHOUT amending the law that nothing is silently ignored: each is carried
into `Labels`, so each still contributes to the spec, and the certificate may publish or omit it.
`plt.figure` is the one member that is not purely cosmetic — a second call starts a new figure and
would discard an already-resolved mark, which is a real data effect and W3's whole subject.

A by-construction G-row is only as durable as the refusal under it, so G2r and G78r pin their rules
against the constructs that would break them rather than against the current mark count.
"""

from fractions import Fraction

import pytest

from verifier.pysrc import Verified, spec, verify_python_source
from verifier.pysrc import admit as admit_module
from verifier.pysrc.admit import ADMITTED_CALL_TARGETS, parse_admitted
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.project import project

_DATASET_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"


def _dataset_source(body: str) -> str:
    return _DATASET_PRELUDE + 'df = pd.read_csv("sales.csv")\n' + body


def _admission_code(source: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    return str(caught.value.code)


def _projection_code(source: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        project(parse_admitted(source))
    return str(caught.value.code)


# --- W: the data-effect-free cluster -----------------------------------------


def test_w1_labels_gains_exactly_three_presentation_fields() -> None:
    """W1: `Labels.__dataclass_fields__` pinned as an exact set adding `figsize`, `tick_rotation`
    and `tight_layout` and nothing else. Two programs differing only in `figsize` project to UNEQUAL
    specs — the fields are carried, not discarded.

    Each of the three carries its own unequal-spec witness. One witness over one field pins the
    assembler's `figsize=` argument alone, and a mutant dropping either of the other two survives
    it: three fields reaching the same constructor are three predicates, not one."""
    fields = spec.Labels.__dataclass_fields__
    assert set(fields) == {
        "title",
        "xlabel",
        "ylabel",
        "series",
        "legend",
        "grid",
        "figsize",
        "tick_rotation",
        "tight_layout",
    }
    assert fields["figsize"].default is None
    assert fields["tick_rotation"].default is None
    assert fields["tight_layout"].default is False

    mark = 'plt.bar(df["region"], df["revenue"])\n'
    plain = project(parse_admitted(_dataset_source(mark + "plt.show()\n")))
    assert isinstance(plain, spec.DatasetPlot)
    assert plain.labels.figsize is None
    assert plain.labels.tick_rotation is None
    assert plain.labels.tight_layout is False

    sized = project(
        parse_admitted(_dataset_source("plt.figure(figsize=(10, 6))\n" + mark + "plt.show()\n"))
    )
    rotated = project(
        parse_admitted(_dataset_source(mark + "plt.xticks(rotation=45)\nplt.show()\n"))
    )
    tightened = project(parse_admitted(_dataset_source(mark + "plt.tight_layout()\nplt.show()\n")))
    assert isinstance(sized, spec.DatasetPlot)
    assert isinstance(rotated, spec.DatasetPlot)
    assert isinstance(tightened, spec.DatasetPlot)
    assert sized.labels.figsize == (Fraction(10), Fraction(6))
    assert rotated.labels.tick_rotation == Fraction(45)
    assert tightened.labels.tight_layout is True
    assert len({plain, sized, rotated, tightened}) == 4


def test_w2_figure_admits_only_a_literal_two_tuple_figsize() -> None:
    """W2: `plt.figure()` and `plt.figure(figsize=(10, 6))` admit. `plt.figure(1)`,
    `plt.figure(dpi=200)`, `plt.figure(figsize=(w, 6))` for a bound `w`,
    `plt.figure(figsize=(10, 6, 2))`, `plt.figure(figsize='big')` and `plt.figure(figsize=[10, 6])`
    each refuse.

    A fractional size admits too, and it projects as the `Fraction` of the float64 that executes —
    `10.5` is exactly representable, so the pin is exact rather than approximate."""
    mark = 'plt.bar(df["region"], df["revenue"])\nplt.show()\n'
    for figure in ("plt.figure()\n", "plt.figure(figsize=(10, 6))\n"):
        projected = project(parse_admitted(_dataset_source(figure + mark)))
        assert isinstance(projected, spec.DatasetPlot), figure

    fractional = project(
        parse_admitted(_dataset_source("plt.figure(figsize=(10.5, 6.25))\n" + mark))
    )
    assert isinstance(fractional, spec.DatasetPlot)
    assert fractional.labels.figsize == (Fraction(21, 2), Fraction(25, 4))

    refusals = {
        "positional": ("plt.figure(1)\n", "keyword_not_admitted"),
        "other-keyword": ("plt.figure(dpi=200)\n", "keyword_not_admitted"),
        "bound-element": ("w = 10\nplt.figure(figsize=(w, 6))\n", "literal_not_admitted"),
        "wrong-arity": ("plt.figure(figsize=(10, 6, 2))\n", "literal_not_admitted"),
        "string": ("plt.figure(figsize='big')\n", "literal_not_admitted"),
        "list": ("plt.figure(figsize=[10, 6])\n", "literal_not_admitted"),
    }
    for name, (figure, code) in refusals.items():
        assert _admission_code(_dataset_source(figure + mark)) == code, name


def test_w2_no_other_call_or_keyword_gained_tuple_admission() -> None:
    """W2: `figsize` is the ONLY admitted tuple in the language. A tuple in any other keyword or
    argument slot still refuses `expression_not_admitted` — the near-miss pin that keeps
    `ADMITTED_TUPLE_KEYWORDS` from being a general display rule."""
    assert admit_module.ADMITTED_TUPLE_KEYWORDS == {("plt.figure", "figsize"): 2}
    near_misses = (
        _dataset_source('plt.bar(df["region"], df["revenue"], label=("a", "b"))\n'),
        _dataset_source('plt.title(("a", "b"))\n'),
        "pair = (1, 2)\n",
    )
    for source in near_misses:
        assert _admission_code(source) == "expression_not_admitted", source


def test_w3_figure_after_a_mark_refuses_figure_orphans_mark() -> None:
    """W3: `plt.bar(...)` then `plt.figure()` refuses `figure_orphans_mark`, NOT
    `statement_not_projected`. Two `plt.figure()` calls refuse the same. `plt.figure()` then
    `plt.bar(...)` verifies. A mutant deleting the ordering check goes red on the first witness."""
    mark = 'plt.bar(df["region"], df["revenue"])\n'
    witnesses = (
        _dataset_source(mark + "plt.figure()\nplt.show()\n"),
        _dataset_source('plt.title("orphaned")\nplt.figure()\n' + mark + "plt.show()\n"),
        _dataset_source("plt.figure()\nplt.figure()\n" + mark + "plt.show()\n"),
    )
    for source in witnesses:
        assert _projection_code(source) == "figure_orphans_mark"

    valid_source = _dataset_source("plt.figure()\n" + mark + "plt.show()\n")
    result = verify_python_source(
        valid_source,
        declared_target=spec.DatasetTarget(path="sales.csv", content=b"region,revenue\na,1\nb,2\n"),
    )
    assert isinstance(result, Verified)


def test_w4_tight_layout_admits_bare_and_once() -> None:
    """W4: `plt.tight_layout()` admits and sets the field; `plt.tight_layout(pad=2)` refuses; twice
    refuses `statement_not_projected`, like every other decoration.

    `pad=2` refuses one stage EARLIER than W4's wording expects: the per-target keyword allowlist is
    empty for `plt.tight_layout`, so admission answers `keyword_not_admitted` before projection ever
    reads the call. A bare positional (`plt.tight_layout(1)`) does reach projection."""
    mark = 'plt.bar(df["region"], df["revenue"])\n'
    once = project(parse_admitted(_dataset_source(mark + "plt.tight_layout()\nplt.show()\n")))
    assert isinstance(once, spec.DatasetPlot)
    assert once.labels.tight_layout is True
    assert (
        _projection_code(_dataset_source(mark + "plt.tight_layout(pad=2)\nplt.show()\n"))
        == "keyword_not_admitted"
    )
    assert (
        _projection_code(_dataset_source(mark + "plt.tight_layout(1)\nplt.show()\n"))
        == "statement_not_projected"
    )
    assert (
        _projection_code(
            _dataset_source(mark + "plt.tight_layout()\nplt.tight_layout()\nplt.show()\n")
        )
        == "statement_not_projected"
    )


def test_w5_xticks_admits_rotation_only_and_no_positional() -> None:
    """W5: `plt.xticks(rotation=45)` admits. `plt.xticks([1, 2, 3])` and `plt.xticks(df['month'])`
    refuse — a positional argument sets tick locations or labels, which changes what the figure
    asserts about x. `plt.xticks(rotation='vertical')` refuses `label_not_literal`.

    The two positional witnesses refuse at DIFFERENT stages, and each names the stage that caught
    it: a list display is not an admitted expression at all, so `[1, 2, 3]` never reaches
    projection, while `df['region']` is an admitted expression that projection then refuses."""
    mark = 'plt.bar(df["region"], df["revenue"])\n'
    rotated = project(
        parse_admitted(_dataset_source(mark + "plt.xticks(rotation=45)\nplt.show()\n"))
    )
    assert isinstance(rotated, spec.DatasetPlot)
    assert rotated.labels.tick_rotation == Fraction(45)
    fractional = project(
        parse_admitted(_dataset_source(mark + "plt.xticks(rotation=22.5)\nplt.show()\n"))
    )
    assert isinstance(fractional, spec.DatasetPlot)
    assert fractional.labels.tick_rotation == Fraction(45, 2)
    positional = {
        "plt.xticks([1, 2, 3])": "expression_not_admitted",
        'plt.xticks(df["region"])': "statement_not_projected",
    }
    for call, expected in positional.items():
        assert _projection_code(_dataset_source(mark + f"{call}\nplt.show()\n")) == expected, call
    assert (
        _projection_code(_dataset_source(mark + "plt.xticks(rotation='vertical')\nplt.show()\n"))
        == "label_not_literal"
    )


def test_w6_marks_admit_three_literal_only_keywords() -> None:
    """W6: `color=`, `marker=`, `linestyle=` admit a string literal, per target and matching
    matplotlib's own signature. `color=df['city']` refuses `label_not_literal` — that is the
    colour-by-category channel in disguise and the witness that matters."""
    allowed = {
        "plot": {"color": "steelblue", "marker": "o", "linestyle": "--"},
        "scatter": {"color": "steelblue", "marker": "o"},
        "bar": {"color": "steelblue"},
        "barh": {"color": "steelblue"},
    }
    for target, styles in allowed.items():
        plain = project(
            parse_admitted(
                _dataset_source(f'plt.{target}(df["region"], df["revenue"])\nplt.show()\n')
            )
        )
        for keyword, value in styles.items():
            styled = project(
                parse_admitted(
                    _dataset_source(
                        f'plt.{target}(df["region"], df["revenue"], {keyword}={value!r})\n'
                        "plt.show()\n"
                    )
                )
            )
            assert styled == plain, (target, keyword)

    for target, keyword in (("scatter", "linestyle"), ("bar", "marker"), ("barh", "marker")):
        source = _dataset_source(f'plt.{target}(df["region"], df["revenue"], {keyword}="x")\n')
        assert _admission_code(source) == "keyword_not_admitted", (target, keyword)

    non_literal = _dataset_source('plt.bar(df["region"], df["revenue"], color=df["region"])\n')
    assert _projection_code(non_literal) == "label_not_literal"

    both = project(
        parse_admitted(
            _dataset_source(
                'plt.bar(df["region"], df["revenue"], label="Revenue", color="steelblue")\n'
                "plt.show()\n"
            )
        )
    )
    color_only = project(
        parse_admitted(
            _dataset_source('plt.bar(df["region"], df["revenue"], color="steelblue")\nplt.show()\n')
        )
    )
    assert isinstance(both, spec.DatasetPlot)
    assert isinstance(color_only, spec.DatasetPlot)
    assert both.labels.series == "Revenue"
    assert color_only.labels.series is None


def test_w7_data_bearing_keywords_stay_refused() -> None:
    """W7: `c=`, `cmap=`, `edgecolors=`, `s=` and `alpha=` each refuse `keyword_not_admitted`.
    `c=`/`cmap=` are the colour-by-category channel the user ruled out and `s=` is G6's
    area-encoding channel; none may enter by the W6 door. This is the near-miss pin `assurance.md`
    requires beside W6's allowlist."""
    for keyword, value in (
        ("c", '"region"'),
        ("cmap", '"viridis"'),
        ("edgecolors", '"black"'),
        ("s", "10"),
        ("alpha", "0.5"),
    ):
        source = _dataset_source(f'plt.scatter(df["region"], df["revenue"], {keyword}={value})\n')
        assert _admission_code(source) == "keyword_not_admitted", keyword


# --- G2r + G78r: the by-construction rows, re-pinned -------------------------


def test_g2r_dual_axis_constructs_each_refuse() -> None:
    """G2r: `plt.twinx`, `plt.twiny`, `ax.secondary_yaxis` and `plt.subplots` each refuse. G2 stays
    true BY CONSTRUCTION and is pinned against these rather than against mark count, so a later
    widening cannot delete G2 silently."""
    targets = {"plt.twinx", "plt.twiny", "ax.secondary_yaxis", "plt.subplots"}
    assert not (targets & ADMITTED_CALL_TARGETS)
    calls = (
        "plt.twinx()",
        "plt.twiny()",
        'ax = 1\nax.secondary_yaxis("right")',
        "plt.subplots()",
    )
    for call in calls:
        source = _dataset_source('plt.bar(df["region"], df["revenue"])\n' + call + "\nplt.show()\n")
        assert _admission_code(source) == "call_target_not_admitted", call


def test_g78r_row_selection_idioms_each_refuse() -> None:
    """G78r: `df[df['c'] == 'x']`, `df.head(3)`, `df.dropna()` and `df.iloc[:3]` each refuse. With
    no filter admitted the plotted column is still the whole column, which is what keeps G7 and G8
    unconditional rather than moving them to a published `Filter`."""
    blocked = {
        'selected = df[df["region"] == "west"]\n': "column_not_literal",
        "selected = df.head(3)\n": "call_target_not_admitted",
        "selected = df.dropna()\n": "call_target_not_admitted",
        "selected = df.iloc[:3]\n": "expression_not_admitted",
    }
    tail = 'plt.bar(df["region"], df["revenue"])\nplt.show()\n'
    for statement, code in blocked.items():
        assert _admission_code(_dataset_source(statement + tail)) == code, statement
