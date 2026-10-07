# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q42: under strict anchoring, a short word with a grouping suffix names its short column.

User ruling (session 7): contract `.agent/archive/contracts/q42.md` approved as drafted. A
whole kanji run = a short word + one suffix from the closed list `別` `毎` `次` `単位` names a
header when the short word alone would under Q41 (U1); a run a Japanese header overlaps stays
that header's, and the suffix is cut once, at the run's end (U2); the demo's rule + G10 never
read suffixes (U3).
"""

import pytest

from verifier.pysrc.spec import Anchoring, DatasetTarget
from verifier.pysrc.verify import Verified, verify_python_source

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_SALES = "年月,地域,売上\n2024-01,東,1\n2024-02,西,2\n".encode()
_WEATHER = "日付,都市,気温\n2024-01-01,札幌,1.5\n2024-01-02,那覇,2.5\n".encode()


def _bar(key: str, value: str) -> str:
    return (
        _PRELUDE
        + 'df = pd.read_csv("data.csv")\n'
        + f'g = df.groupby("{key}")["{value}"].sum()\nplt.bar(g.index, g.values)\nplt.show()\n'
    )


def _verdict(
    program: str, request: str, content: bytes = _SALES, anchoring: Anchoring = "strict"
) -> str:
    target = DatasetTarget("data.csv", content, request, anchoring)
    verdict = verify_python_source(program, declared_target=target)
    return "VERIFIED" if isinstance(verdict, Verified) else verdict.code


@pytest.mark.parametrize(
    ("content", "key", "value", "ask"),
    [
        (_SALES, "年月", "売上", "月別の売上の合計を棒グラフにしてください。"),
        (_SALES, "年月", "売上", "月毎の売上の合計を棒グラフにしてください。"),
        (_SALES, "年月", "売上", "月次の売上の合計を棒グラフにしてください。"),
        (_SALES, "年月", "売上", "月単位の売上の合計を棒グラフにしてください。"),
        (_WEATHER, "日付", "気温", "日別の気温の合計を棒グラフで示してください。"),
    ],
    ids=["betsu", "mai", "ji", "tani", "drop-last"],
)
def test_q42_u1_a_suffixed_short_word_names_its_column_under_strict(
    content: bytes, key: str, value: str, ask: str
) -> None:
    """Accept: Q41's strict rule refused each of these as `column_not_named`."""
    assert _verdict(_bar(key, value), ask, content) == "VERIFIED"


def test_q42_u1_a_suffixed_short_word_counts_for_the_substitution_check() -> None:
    """`月別の売上` drawn over `地域`: `年月` named and undrawn, `地域` drawn and unnamed."""
    assert _verdict(_bar("地域", "売上"), "月別の売上の合計") == "column_not_requested"


def test_q42_u3_the_demo_rule_reads_no_suffix() -> None:
    ask = "月別の売上の合計"
    assert _verdict(_bar("地域", "売上"), ask, anchoring="substitution") == "VERIFIED"


def test_q42_u2_the_suffix_is_cut_once() -> None:
    """`月次別` loses `別` alone; `月次` fits no name, so `年月` stays unnamed."""
    assert _verdict(_bar("年月", "売上"), "月次別の売上の合計") == "column_not_named"


def test_q42_u2_the_suffix_is_cut_at_the_end_only() -> None:
    assert _verdict(_bar("年月", "売上"), "別月の売上の合計") == "column_not_named"


def test_q42_u2_a_run_a_header_overlaps_stays_that_headers() -> None:
    """`月別` is itself a header: the run names `月別`, never `年月` through its stem."""
    content = "年月,月別,売上\n2024-01,1,1\n2024-02,2,2\n".encode()
    assert _verdict(_bar("年月", "売上"), "月別の売上の合計", content) == "column_not_requested"


def test_q42_u1_a_stem_fitting_two_names_names_neither() -> None:
    content = "年月,年齢,売上\n2024-01,30,1\n2024-02,40,2\n".encode()
    assert _verdict(_bar("年月", "売上"), "年別の売上の合計", content) == "column_not_named"


def test_q42_u1_a_run_and_its_stem_fitting_different_names_name_neither() -> None:
    """`月次` fits `月次表` whole and `年月` without `次`: a tie, so `年月` stays unnamed."""
    content = "年月,月次表,売上\n2024-01,1,1\n2024-02,2,2\n".encode()
    assert _verdict(_bar("年月", "売上"), "月次の売上の合計", content) == "column_not_named"


def test_q42_u1_a_suffixed_short_word_before_a_negation_cue_names_nothing() -> None:
    """`月別ではなく` excludes the month: the run names nothing, so `年月` drawn stays unnamed."""
    assert _verdict(_bar("年月", "売上"), "月別ではなく売上の合計") == "column_not_named"
