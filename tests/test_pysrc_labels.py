# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q16: G10 refuses a label naming what the chart does not show, as `label_not_consistent`.

Row acceptance: a committed check refuses a label naming a column or aggregation the projection
does not use, and a planted mismatch fires it. The verdict carries no free text (`errors.py`), so
"naming the label" is read as the plant sitting in the label: each label position fires alone.
Contract `.agent/archive/contracts/q16.md`.
"""

import pytest

from anchoring_support import verdict
from verifier.figure import reader
from verifier.figure.description import parse_description
from verifier.figure.judge import Passed, Sources, judge

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_SALES = b"region,month,revenue,orders\nwest,2024-01,1,5\neast,2024-02,2,6\n"
# Two rows per region: a group of one row is a raw value, so its reductions coincide and no
# summary word is read; here sum, mean, min + max differ in every group.
_GROUPED = (
    b"region,month,revenue,orders\n"
    b"west,2024-01,1,5\nwest,2024-02,3,6\neast,2024-01,2,7\neast,2024-02,6,8\n"
)


def _labelled(
    labels: dict[str, str],
    *,
    key: str = "region",
    value: str = "revenue",
    reduction: str = "sum",
) -> str:
    series = f', label="{labels["series"]}"' if "series" in labels else ""
    lines = [
        _PRELUDE + 'df = pd.read_csv("data.csv")',
        f'g = df.groupby("{key}")["{value}"].{reduction}()',
        f"plt.bar(g.index, g.values{series})",
        *(
            f'plt.{call}("{labels[call]}")'
            for call in ("title", "xlabel", "ylabel")
            if call in labels
        ),
        *(["plt.legend()"] if series else []),
        "plt.show()",
    ]
    return "\n".join(lines) + "\n"


def _verdict(program: str, content: bytes = _SALES) -> str:
    return verdict(program, None, content)


@pytest.mark.parametrize("position", ["title", "xlabel", "ylabel", "series"])
def test_q16_a_label_naming_an_undrawn_column_refuses(position: str) -> None:
    """Accept: the planted mismatch, in each label position alone."""
    assert _verdict(_labelled({position: "Revenue by month"})) == "label_not_consistent"
    assert _verdict(_labelled({position: "Revenue by region"})) == "VERIFIED"


def test_q16_a_one_edit_spelling_names_its_column() -> None:
    assert _verdict(_labelled({"xlabel": "Months"})) == "label_not_consistent"


@pytest.mark.parametrize(
    ("reduction", "consistent", "inconsistent"),
    [
        ("sum", "Total revenue", "Average revenue"),
        ("mean", "Average revenue", "Total revenue"),
    ],
)
def test_q16_a_summary_word_of_another_reduction_refuses(
    reduction: str, consistent: str, inconsistent: str
) -> None:
    program = _labelled({"title": inconsistent}, reduction=reduction)
    assert _verdict(program, _GROUPED) == "label_not_consistent"
    assert _verdict(_labelled({"title": consistent}, reduction=reduction), _GROUPED) == "VERIFIED"


@pytest.mark.parametrize(("reduction", "label"), [("min", "Max revenue"), ("max", "Min revenue")])
def test_q16_a_group_min_or_max_reads_as_raw_cells(reduction: str, label: str) -> None:
    """A group's min or max IS one of its cells, so the drawn values are a raw subset (R2) and
    the canonical explanation is raw: no reduction is drawn, so no summary word is read."""
    assert _verdict(_labelled({"title": label}, reduction=reduction), _GROUPED) == "VERIFIED"


def test_q16_a_summary_no_reduction_computes_refuses() -> None:
    assert _verdict(_labelled({"ylabel": "Median revenue"}), _GROUPED) == "label_not_consistent"


def test_q16_without_a_reduction_summary_words_go_unread() -> None:
    """A raw column may itself hold totals: `Total revenue` over raw rows claims nothing."""
    program = (
        _PRELUDE + 'df = pd.read_csv("data.csv")\nplt.scatter(df["orders"], df["revenue"])\n'
        'plt.ylabel("Total revenue")\nplt.show()\n'
    )
    assert _verdict(program) == "VERIFIED"


def test_q16_a_summary_word_inside_a_header_names_the_column() -> None:
    content = b"region,total_revenue\nwest,1\nwest,3\neast,2\neast,6\n"
    program = _labelled({"title": "Average total revenue"}, value="total_revenue", reduction="mean")
    assert _verdict(program, content) == "VERIFIED"


def test_q16_japanese_summary_words_match_inside_the_label() -> None:
    content = "地域,売上\n東,1\n東,3\n西,2\n西,6\n".encode()
    mean = {"key": "地域", "value": "売上", "reduction": "mean"}
    assert _verdict(_labelled({"title": "地域ごとの売上合計"}, **mean), content) == (
        "label_not_consistent"
    )
    assert _verdict(_labelled({"title": "地域ごとの売上平均"}, **mean), content) == "VERIFIED"


def test_q16_a_japanese_summary_word_inside_a_header_names_the_column() -> None:
    content = "地域,合計金額\n東,1\n東,3\n西,2\n西,6\n".encode()
    program = _labelled({"title": "合計金額の平均"}, key="地域", value="合計金額", reduction="mean")
    assert _verdict(program, content) == "VERIFIED"


def test_q16_a_japanese_label_naming_an_undrawn_column_refuses() -> None:
    content = "年月,地域,売上\n2024-01,東,1\n2024-02,西,2\n".encode()
    program = _labelled({"xlabel": "年月"}, key="地域", value="売上")
    assert _verdict(program, content) == "label_not_consistent"


def test_q16_a_tied_label_word_names_nothing() -> None:
    """A request tie refuses (Q8); a label tie is no positive mismatch."""
    content = b"batch,patch,value\na,b,1\nc,d,2\n"
    assert _verdict(_labelled({"xlabel": "match"}, key="batch", value="value"), content) == (
        "VERIFIED"
    )


def test_q16_a_tied_japanese_label_names_nothing_inside_it() -> None:
    """Kernel review G3: `収張期血圧` fits both pressures; no stretch inside it names one."""
    content = "日付,収縮期血圧,拡張期血圧\n1,120,80\n2,130,85\n".encode()
    program = _labelled({"ylabel": "収張期血圧"}, key="日付", value="収縮期血圧", reduction="mean")
    assert _verdict(program, content) == "VERIFIED"


def test_q16_a_name_repeated_in_one_label_names_its_column_alone() -> None:
    """Kernel review G3: `Unit price (unit_price)` names `unit_price` twice and `price` never."""
    content = b"region,unit_price,price\nwest,1,2\neast,3,4\n"
    program = _labelled({"ylabel": "Unit price (unit_price)"}, value="unit_price", reduction="mean")
    assert _verdict(program, content) == "VERIFIED"


def test_q16_a_label_naming_nothing_checkable_passes() -> None:
    assert _verdict(_labelled({"title": "Sales overview"})) == "VERIFIED"


def test_q16_mark_rules_refuse_before_labels() -> None:
    """A repeated category and a bad label: the drawn data's fault reports first (two bars on one
    category overlap, a mark rule, before the columns stage reads any label)."""
    program = (
        _PRELUDE + 'df = pd.read_csv("data.csv")\nplt.bar(df["region"], df["revenue"])\n'
        'plt.xlabel("Month")\nplt.show()\n'
    )
    content = b"region,month,revenue\nwest,2024-01,1\nwest,2024-02,2\n"
    assert _verdict(program, content) == "bars_overlap"


def test_q16_labels_without_a_file_meet_no_header() -> None:
    """A computed curve and no attached file: no header, so G10 reads nothing."""
    program = (
        "import numpy as np\nimport matplotlib.pyplot as plt\nx = np.linspace(0, 1, 3)\n"
        'plt.plot(x, np.sin(x))\nplt.xlabel("revenue total")\nplt.show()\n'
    )
    described = parse_description(reader.run(program))
    assert described is not None
    assert isinstance(judge(described, Sources()), Passed)


@pytest.mark.parametrize("label", ["Revenue (not orders)", "Revenue in chronological order"])
def test_q38_a_label_negating_or_ordering_names_no_column(label: str) -> None:
    """Q38 reaches G10 through the shared matcher: neither label names `orders`."""
    assert _verdict(_labelled({"title": label})) == "VERIFIED"


def test_q38_a_japanese_label_negating_a_column_names_no_column() -> None:
    content = "地域,売上,注文数\n東,1,5\n西,2,6\n".encode()
    program = _labelled({"title": "注文数ではなく売上"}, key="地域", value="売上")
    assert _verdict(program, content) == "VERIFIED"


def test_q38_a_cue_before_a_non_name_negates_nothing_in_a_label() -> None:
    """`only` is no column, so `orders` after it stays named: an undrawn column in the title."""
    assert _verdict(_labelled({"title": "Revenue, not only orders"})) == "label_not_consistent"


def test_q38_a_mixed_script_label_negating_a_column_names_no_column() -> None:
    content = "地域,売上,売上JPY\n東,1,5\n西,2,6\n".encode()
    program = _labelled({"title": "売上JPYではなく売上"}, key="地域", value="売上")
    assert _verdict(program, content) == "VERIFIED"
