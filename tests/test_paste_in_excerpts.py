# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M20.2 E1-E3: each "Show checks" row's program lines (`.agent/archive/contracts/m20u2.md`).

Every program runs through the host reader; each row's lines are hand-stated from the program.
"""

from __future__ import annotations

import pytest

from verifier.figure.description import parse_description
from verifier.figure.judge import Sources, judge
from verifier.figure.reader import run
from verifier.figure.reasons import Blocked
from webui.paste_in import excerpts as excerpts_module
from webui.paste_in.excerpts import excerpts

_PLT = "import matplotlib.pyplot as plt\n"
_PD = "import pandas as pd\nimport matplotlib.pyplot as plt\n"


def _rows(
    program: str, failing: str | None = None, site: int | None = None, *, described: bool = True
) -> dict[str, tuple[int, ...]]:
    description = parse_description(run(program)) if described else None
    assert description is not None or not described
    found = excerpts(program, description, failing, site)  # type: ignore[arg-type]
    return {check: tuple(sorted(lines)) for check, lines in found}


# --- E1 recorded rows ------------------------------------------------------------------------

_PANELS = (
    _PLT  # 1
    + "fig, (left, right) = plt.subplots(1, 2)\n"  # 2
    + "left.bar(['a', 'b'], [1, 2], label='n')\n"  # 3
    + "left.set_ylim(0, 3)\n"  # 4
    + "left.set_title('T')\n"  # 5
    + "left.set_xlabel('X')\n"  # 6
    + "left.legend()\n"  # 7
    + "left.text(0, 2, 'note')\n"  # 8
    + "points = right.scatter([1, 2], [3, 4], c=[1, 2])\n"  # 9
    + "fig.colorbar(points, ax=right)\n"  # 10
    + "right.set_yscale('log')\n"  # 11
    + "right.set_ylabel('log Y')\n"  # 12
    + "right.set_xticks([1, 2])\n"  # 13
    + "fig.suptitle('S')\n"  # 14
    + "fig.text(0.5, 0, 'F')\n"  # 15
    + "plt.show()\n"  # 16
)


def test_e1_each_row_lists_the_parts_its_check_reads() -> None:
    assert _rows(_PANELS) == {
        "figure": (2, 5, 6, 7, 8, 12, 13, 14, 15),
        "parts": (2, 3, 5, 6, 7, 8, 9, 10, 12, 14, 15),
        "axes": (2, 4, 5, 6, 10, 11, 12, 13),
        "marks": (3, 7, 9, 10),
        "values": (3, 9, 10),
        "columns": (3, 5, 6, 7, 9, 10, 12, 14),
    }


def test_e1_a_figure_level_part_joins_parts() -> None:
    program = _PLT + "fig = plt.figure()\nplt.plot([1, 2])\nfig.figimage([[1, 2], [3, 4]])\n"
    assert _rows(program)["parts"] == (3, 4)


def test_e1_a_failing_site_joins_its_row() -> None:
    """The failure's own line joins the failing row; the other rows keep their recorded lines."""
    program = _PLT + "plt.bar(['a'], [1])\nwidth = 3\nplt.show()\n"
    rows = _rows(program, "marks", 3)
    assert rows["marks"] == (2, 3)
    assert rows["values"] == (2,)


# --- E2 widening -----------------------------------------------------------------------------

_SPLIT = (
    _PLT  # 1
    + "heights = [1,\n"  # 2
    + "           2]\n"  # 3
    + "plt.bar(\n"  # 4
    + "    ['a', 'b'],\n"  # 5
    + "    heights,\n"  # 6
    + ")\n"  # 7
    + "plt.show()\n"  # 8
)
_BLOCKS = (
    _PLT  # 1
    + "try:\n"  # 2
    + "    for k, v in [('a', 1), ('b', 2)]:\n"  # 3
    + "        if v:\n"  # 4
    + "            plt.bar(k, v)\n"  # 5
    + "except ValueError:\n"  # 6
    + "    pass\n"  # 7
    + "plt.show()\n"  # 8
)


def test_e2_a_line_widens_to_its_statement_and_the_blocks_around_it() -> None:
    split, blocks = _rows(_SPLIT), _rows(_BLOCKS)
    assert split["marks"] == (4, 5, 6, 7)
    assert split["values"] == (2, 3, 4, 5, 6, 7)
    assert blocks["marks"] == (2, 3, 4, 5)
    # The loop binds `k` + `v`; it encloses the drawing statement, so only its header shows.
    assert blocks["values"] == (2, 3, 4, 5)


def test_e2_a_handler_shows_its_own_header() -> None:
    program = "try:\n    x = 1 / 0\nexcept ZeroDivisionError:\n    raise ValueError(x)\n"
    assert _rows(program, "run", 4, described=False) == {"run": (1, 3, 4)}


def test_e2_a_one_line_block_is_one_line() -> None:
    program = _PLT + "for v in [1, 2]: plt.bar(str(v), v)\nplt.show()\n"
    assert _rows(program)["marks"] == (2,)


def _padded(length: int) -> str:
    """`_SPLIT` grown to exactly `length` characters by a trailing comment."""
    return _SPLIT + "#" * (length - len(_SPLIT))


@pytest.mark.parametrize(
    ("program", "widened"),
    [
        (_PLT + "plt.bar(\n    ['a'],\n    [1],\n)\nplt.show(\n", False),  # Python refuses it
        (_padded(65_536), True),  # the parse bound
        (_padded(65_537), False),
    ],
    ids=["unparsable", "at-bound", "past-bound"],
)
def test_e2_without_a_parse_the_recorded_lines_stay(program: str, *, widened: bool) -> None:
    assert _rows(program, "run", 2, described=False) == {"run": (2, 3) if widened else (2,)}
    if program.startswith(_SPLIT):
        rows = _rows(program)
        assert rows["marks"] == ((4, 5, 6, 7) if widened else (4,))


def test_e2_a_line_no_statement_holds_stays() -> None:
    program = _PLT + "# a comment\nplt.bar(['a'], [1])\n"
    assert _rows(program, "axes", 2, described=False) == {"axes": (2,)}


# --- E3 data preparation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("program", "values"),
    [
        pytest.param(
            _PD
            + "df = pd.DataFrame({'r': ['a', 'b', 'a'], 'v': [1, 2, 3]})\n"  # 3
            + "g = df.groupby('r')['v'].sum()\n"  # 4
            + "other = df.copy()\n"  # 5
            + "g.plot(kind='bar')\n",  # 6
            (3, 4, 6),
            id="pandas-chain",
        ),
        pytest.param(
            _PLT
            + "x = ['a', 'b']\n"  # 2
            + "fig, ax = plt.subplots()\n"  # 3: builds the chart, never data
            + "y = [9, 9]\n"  # 4: rebound below before any read
            + "y = [1, 2]\n"  # 5
            + "ax.bar(x, y)\n",  # 6
            (2, 5, 6),
            id="axes-receiver-rebinding",
        ),
        pytest.param(
            _PLT
            + "vals = [1, 2]\n"  # 2
            + "total = 0\n"  # 3
            + "for v in vals:\n"  # 4
            + "    total += v\n"  # 5
            + "unused = 7\n"  # 6
            + "plt.bar(['t'], [total])\n",  # 7
            (2, 3, 4, 5, 7),
            id="loop-accumulation",
        ),
        pytest.param(
            _PLT
            + "values = []\n"  # 2
            + "values.append(3)\n"  # 3
            + "values.sort()\n"  # 4
            + "others = []\n"  # 5
            + "others.append(1)\n"  # 6
            + "values.count(3)\n"  # 7: reads, changes nothing
            + "plt.bar(['a'], values)\n",  # 8
            (2, 3, 4, 8),
            id="in-place-calls",
        ),
        pytest.param(
            _PD
            + "df = pd.DataFrame({'r': ['b', 'a'], 'v': [1, 2], 'z': [0, 0]})\n"  # 3
            + "df.sort_values('v', inplace=True)\n"  # 4
            + "df.sort_values('r')\n"  # 5: returns a copy
            + "df['w'] = df['v'] * 1\n"  # 6
            + "del df['z']\n"  # 7
            + "df.plot(x='r', y='w', kind='bar')\n",  # 8
            (3, 4, 6, 7, 8),
            id="frame-changes",
        ),
        pytest.param(
            _PLT
            + "k = 9\n"  # 2: the def's own `k` shadows it
            + "scale = 2\n"  # 3
            + "def make():\n"  # 4
            + "    k = 3\n"  # 5
            + "    return [k * scale, 1]\n"  # 6
            + "y = make()\n"  # 7
            + "plt.bar(['a', 'b'], y)\n",  # 8
            (3, 4, 5, 6, 7, 8),
            id="def-whole",
        ),
        pytest.param(
            _PLT
            + "y = [1, 2]\n"  # 2
            + "def unrelated():\n"  # 3
            + "    y = [7, 7]\n"  # 4: binds its own local
            + "    return y\n"  # 5
            + "plt.bar(['a', 'b'], y)\n",  # 6
            (2, 6),
            id="other-scope",
        ),
        pytest.param(
            _PLT
            + "data = [5, 6]\n"  # 2: the caller's value, not followed
            + "def draw(ax, data):\n"  # 3
            + "    ax.bar(['a', 'b'], data)\n"  # 4
            + "draw(plt.gca(), data)\n",  # 5
            (3, 4),
            id="parameter",
        ),
        pytest.param(
            _PD
            + "df = pd.DataFrame({'r': ['a', 'b'], 'v': [1, 2]})\n"  # 3
            + "ax = df.plot(x='r', y='v', kind='bar')\n"  # 4: draws + builds the axes
            + "ax.axhline(df['v'].mean())\n",  # 5
            (3, 4, 5),
            id="builder-seed",
        ),
        pytest.param(
            _PLT
            + "v = 100\n"  # 2: a comprehension's own name
            + "xs = [1, 2]\n"  # 3
            + "print((total := sum(xs)))\n"  # 4
            + "ys: list[int] = [n * 2 for v in xs for n in [v]]\n"  # 5
            + "plt.bar(['a', 'b', 'c'], [*ys, total])\n",  # 6
            (3, 4, 5, 6),
            id="walrus-annotation-comprehension",
        ),
        pytest.param(
            _PD
            + "import contextlib\n"  # 3
            + "with contextlib.nullcontext([1, 2]) as values:\n"  # 4
            + "    pass\n"  # 5
            + "plt.bar(['a', 'b'], values)\n",  # 6
            (4, 6),
            id="with-imports",
        ),
    ],
)
def test_e3_values_list_the_statements_that_prepare_the_drawn_data(
    program: str, values: tuple[int, ...]
) -> None:
    rows = _rows(program)
    assert rows["values"] == values
    assert set(values) <= set(rows["columns"])


def test_e3_marks_and_axes_list_no_preparation() -> None:
    rows = _rows(_PD + "df = pd.DataFrame({'v': [1, 2]})\nplt.plot(df['v'])\n")
    assert (rows["marks"], rows["axes"], rows["values"]) == ((4,), (4,), (3, 4))


def test_m20_4_t5_tick_style_calls_join_the_figure_and_axes_rows() -> None:
    """A tick style can change the tick font, and with it the glyphs the figure check counts: the
    figure + axes rows list it (`.agent/archive/contracts/m20u4.md` T5, closing review R180)."""
    program = (
        _PLT  # 1
        + "plt.bar(['a', 'b'], [1, 2])\n"  # 2
        + "plt.xticks(rotation=45)\n"  # 3
        + "plt.gca().tick_params(axis='y', labelsize=8)\n"  # 4
        + "plt.gca().set_xticks([0, 1])\n"  # 5
    )
    rows = _rows(program)
    assert (rows["figure"], rows["axes"]) == ((2, 3, 4, 5), (2, 3, 4, 5))


def test_r180_a_tick_font_that_drops_a_glyph_shows_in_the_figure_row() -> None:
    program = _PLT + "plt.plot([-1, 2], [3, -4])\nplt.xticks(fontfamily='cmr10')\n"
    description = parse_description(run(program))
    assert description is not None
    assert judge(description, Sources()) == Blocked("glyph_missing", None)
    assert _rows(program, "figure")["figure"] == (2, 3)


# --- closing review (M20.3): reviewer-1 F1-F3, reviewer-3 F1-F2 -----------------------------


def test_r1_f1_a_colorbar_axes_made_on_its_own_line_joins_marks() -> None:
    program = (
        _PLT  # 1
        + "fig, ax = plt.subplots()\n"  # 2
        + "points = ax.scatter([1, 2], [3, 4], c=[1, 2])\n"  # 3
        + "cax = fig.add_axes([0.9, 0.1, 0.03, 0.8])\n"  # 4
        + "fig.colorbar(points, cax=cax)\n"  # 5
    )
    assert _rows(program)["marks"] == (3, 4, 5)


@pytest.mark.parametrize(
    "drawn",
    [
        "ys = [value for value in value]\n",  # the first iterable reads the outer name
        "ys = [(lambda value: value)(1), value[0]]\n",  # a lambda's parameter binds its body alone
    ],
    ids=["comprehension-iterable", "lambda-sibling"],
)
def test_r1_f2_an_inner_scope_binds_only_its_own_reads(drawn: str) -> None:
    program = _PLT + "value = [1, 2]\n" + drawn + "plt.plot(ys)\n"
    assert _rows(program)["values"] == (2, 3, 4)


def test_r1_f3_a_failure_in_an_except_header_widens_to_that_header() -> None:
    program = (
        "try:\n    raise ValueError('stop')\nexcept (\n    UndefinedException,\n):\n    pass\n"
    )
    assert _rows(program, "run", 4, described=False) == {"run": (1, 3, 4, 5)}


def test_r1_f3_a_case_header_widens_like_an_except_header() -> None:
    program = "match 1:\n    case 0:\n        pass\n    case (\n        1\n    ):\n        pass\n"
    assert _rows(program, "run", 5, described=False) == {"run": (1, 4, 5, 6)}
    assert _rows(program, "run", 3, described=False) == {"run": (1, 2, 3)}


@pytest.mark.parametrize(
    ("program", "values"),
    [
        pytest.param(
            _PD
            + "df = pd.DataFrame({'x': [1, 2], 'y': [3, 4]})\n"  # 3
            + "df.add(100)\n"  # 4: returns a new frame
            + "plt.plot(df['x'], df['y'])\n",  # 5
            (3, 5),
            id="discarded-result",
        ),
        pytest.param(
            _PLT
            + "values = [99, 99]\n"  # 2: rebound before the helper runs
            + "def draw_chart():\n"  # 3
            + "    plt.plot([1, 2], values)\n"  # 4
            + "values = [3, 4]\n"  # 5
            + "draw_chart()\n",  # 6
            (3, 4, 5),
            id="global-read-at-the-call",
        ),
        pytest.param(
            _PD
            + "df = pd.DataFrame({'y': [3, 4]})\n"  # 3
            + "try:\n"  # 4
            + "    values = df['y'].tolist()\n"  # 5: may run, so the arm below may too
            + "except KeyError:\n"  # 6
            + "    values = [99, 99]\n"  # 7
            + "plt.plot([1, 2], values)\n",  # 8
            (3, 4, 5, 6, 7, 8),
            id="every-arm-that-may-bind",
        ),
        pytest.param(
            _PLT
            + "values = [3, 4]\n"  # 2
            + "for values in []:\n"  # 3: a loop may run zero times
            + "    pass\n"  # 4
            + "plt.plot([1, 2], values)\n",  # 5
            (2, 3, 5),
            id="loop-that-may-not-run",
        ),
    ],
)
def test_r3_f1_every_binding_that_may_reach_the_drawing_line(
    program: str, values: tuple[int, ...]
) -> None:
    """A binding the drawing line's path may skip keeps the earlier one listed (the real data
    line was dropped); a call that returns a copy changes nothing; a helper's global is read
    where the helper is called."""
    assert _rows(program)["values"] == values


def test_r3_f2_the_trace_stops_at_its_work_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """One walk per drawing line over 13,000 statements took 72 s on the event loop; past the
    budget the trace stops, and the lines it found stand."""
    program = _PLT + "x = [1, 2]\n" + "a = 0\n" * 50 + "plt.plot(x)\n"
    assert _rows(program)["values"] == (2, 53)
    monkeypatch.setattr(excerpts_module, "_WORK", 10)
    assert _rows(program)["values"] == (53,)


_SCOPE_NAMES = (
    _PLT  # 1
    + "total = [1, 2]\n"  # 2: `global` keeps the def reading it
    + "math = 0\n"  # 3: shadowed by the def's own import
    + "e = 7\n"  # 4: shadowed by the def's `except ... as e`
    + "inner = 9\n"  # 5: shadowed by the def's own def
    + "scale = 3\n"  # 6: read by the class body
    + "class Box:\n"  # 7
    + "    size = scale\n"  # 8
    + "def make():\n"  # 9
    + "    global total\n"  # 10
    + "    import math\n"  # 11
    + "    total = list(total)\n"  # 12
    + "    try:\n"  # 13
    + "        pass\n"  # 14
    + "    except ValueError as e:\n"  # 15
    + "        return [e]\n"  # 16
    + "    def inner():\n"  # 17
    + "        return 1\n"  # 18
    + "    return [math.floor(t) * Box.size * inner() for t in total]\n"  # 19
    + "y = make()\n"  # 20
    + "plt.plot(y)\n"  # 21
)


def test_r1_f2_a_def_reads_every_name_it_does_not_bind_itself() -> None:
    """A def read whole reads the free names of its body: a `global` name, a class it uses; its
    own import, `except ... as` name and inner def shadow the outer ones."""
    assert _rows(_SCOPE_NAMES)["values"] == (2, 6, 7, 8, *range(9, 20), 20, 21)


@pytest.mark.parametrize(
    ("program", "values"),
    [
        pytest.param(
            _PLT + "v = [9]\nys = [(lambda v: v)(1), 2]\nplt.plot(ys)\n",
            (3, 4),
            id="lambda-own-parameter",
        ),
    ],
)
def test_r1_f2_a_lambda_parameter_shadows_the_outer_name(
    program: str, values: tuple[int, ...]
) -> None:
    assert _rows(program)["values"] == values


def test_r3_f2_finding_a_helper_s_caller_spends_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = (
        _PLT  # 1
        + "values = [1, 2]\n"  # 2
        + "def draw():\n"  # 3
        + "    plt.plot(values)\n"  # 4
        + "draw()\n"  # 5
        + "a = 0\n" * 50  # 6-55: the body the caller scan reads
    )
    assert _rows(program)["values"] == (2, 3, 4)
    monkeypatch.setattr(excerpts_module, "_WORK", 20)
    assert _rows(program)["values"] == (3, 4)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("if False:\n    pass\nelse:\n    plt.plot([1, 2])\n", {2, 4, 5}),
        ("try:\n    pass\nexcept ValueError:\n    pass\nelse:\n    plt.plot([1, 2])\n", {2, 6, 7}),
        ("try:\n    pass\nfinally:\n    plt.plot([1, 2])\n", {2, 4, 5}),
        ("for _ in ():\n    pass\nelse:\n    plt.plot([1, 2])\n", {2, 4, 5}),
        ("if False:\n    pass\nelif True:\n    plt.plot([1, 2])\n", {2, 4, 5}),
    ],
    ids=["if-else", "try-else", "try-finally", "for-else", "elif"],
)
def test_cr_r285_a_statement_shows_the_else_or_finally_header_it_sits_under(
    body: str, expected: set[int]
) -> None:
    """R285 (code review): an `else:` / `finally:` header carries no node of its own, so its block
    widened to the opening `if` / `try` alone and the listing read as the plot ran in the false
    arm; each continuation header now joins the lines shown."""
    program = "import matplotlib.pyplot as plt\n" + body
    described = parse_description(run(program))
    assert described is not None and described.error is None
    assert dict(excerpts(program, described, None, None))["marks"] == expected
