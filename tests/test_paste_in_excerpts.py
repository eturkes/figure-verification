# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M20.2 E1-E3: each "Show checks" row's program lines (`.agent/archive/contracts/m20u2.md`).

Every program runs through the host reader; each row's lines are hand-stated from the program.
"""

from __future__ import annotations

import pytest

from verifier.figure.description import parse_description
from verifier.figure.reader import run
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
