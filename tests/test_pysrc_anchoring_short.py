# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q41: under strict anchoring, a Japanese short word names its 2-4 character column.

User ruling (session 6): production users are primarily Japanese; `月ごと` must name `年月` and
`日ごと` must name `日付`. Strict anchoring alone reads the short word (T1); the demo's rule and the
G10 labels keep the shared matcher (T2). Contract `.agent/archive/contracts/q41.md`.
"""

import pytest

from verifier.pysrc.spec import Anchoring, DatasetTarget
from verifier.pysrc.verify import Verified, verify_python_source

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_SALES = "年月,地域,売上,注文数\n2024-01,東,1,5\n2024-02,西,2,6\n".encode()
_WEATHER = "日付,都市,気温,降水量\n2024-01-01,札幌,1.5,2\n2024-01-02,那覇,2.5,3\n".encode()


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
        (_SALES, "年月", "売上", "月ごとの売上を折れ線グラフにしてください。"),
        (_WEATHER, "日付", "降水量", "日ごとの降水量の合計を棒グラフで示してください。"),
        (_WEATHER, "日付", "降水量", "日付ごとの降水の合計を棒グラフで示してください。"),
    ],
    ids=["drop-first", "drop-last", "three-char-name"],
)
def test_q41_t1_a_short_word_names_its_column_under_strict(
    content: bytes, key: str, value: str, ask: str
) -> None:
    """Accept: Q37's strict rule refused each of these as `column_not_named`."""
    assert _verdict(_bar(key, value), ask, content) == "VERIFIED"


def test_q41_t1_a_short_word_counts_as_named_for_the_substitution_check() -> None:
    """`月ごとの売上` drawn over `地域`: `年月` named and undrawn, `地域` drawn and unnamed."""
    ask = "月ごとの売上を棒グラフにしてください。"
    assert _verdict(_bar("地域", "売上"), ask) == "column_not_requested"


def test_q41_t2_the_demo_rule_reads_no_short_word() -> None:
    """The demo keeps the shared matcher: `月` names nothing, so no substitution is seen."""
    ask = "月ごとの売上を棒グラフにしてください。"
    assert _verdict(_bar("地域", "売上"), ask, anchoring="substitution") == "VERIFIED"


def test_q41_t1_a_run_fitting_two_names_names_neither() -> None:
    content = "年月,年齢,売上\n2024-01,30,1\n2024-02,40,2\n".encode()
    assert _verdict(_bar("年月", "売上"), "年ごとの売上の合計", content) == "column_not_named"


def test_q41_t1_a_whole_run_must_match_not_a_part_of_it() -> None:
    """`月例` is one run; dropping one end of `年月` gives `月`, never `月例`."""
    assert _verdict(_bar("年月", "売上"), "月例の売上の合計") == "column_not_named"


def test_q41_t1_reads_four_characters_and_the_one_edit_tier_reads_five() -> None:
    """T1 stops at 4 characters: dropping one end of a 5+-character name is one edit, which the
    shared one-edit tier already reads in both modes."""
    content = "日付,在院日数\n1,3\n2,4\n".encode()
    assert _verdict(_bar("日付", "在院日数"), "日付ごとの院日数の合計", content) == "VERIFIED"
    content = "日付,収縮期血圧\n1,120\n2,130\n".encode()
    program = _bar("日付", "収縮期血圧")
    for anchoring in ("strict", "substitution"):
        ask = "日付ごとの収縮期血の合計"
        assert _verdict(program, ask, content, anchoring) == "VERIFIED"


def test_q41_t1_a_run_is_whole_in_the_request_before_names_are_consumed() -> None:
    """`診療科別` is one run; consuming the exact name `診療科` never leaves `別` to name `性別`."""
    content = "診療科,性別,患者数\n内科,男,3\n外科,女,4\n".encode()
    ask = "診療科別の患者数の合計"
    assert _verdict(_bar("性別", "患者数"), ask, content) == "column_not_requested"


def test_q41_t1_a_run_an_exact_name_covers_names_only_that_name() -> None:
    """`売上` is a header itself, so the run names `売上`, never `売上高` by dropping its end."""
    content = "地域,売上,売上高\n東,1,10\n西,2,20\n".encode()
    ask = "地域ごとの売上の合計"
    assert _verdict(_bar("地域", "売上高"), ask, content) == "column_not_requested"


def test_q41_t1_a_short_word_before_a_negation_cue_names_nothing() -> None:
    """As N3 reads an exact name: `月ではなく` excludes the month column, so drawing it refuses."""
    assert _verdict(_bar("年月", "売上"), "月ではなく、売上の合計") == "column_not_named"


def test_q41_t1_a_column_two_headers_fold_to_reads_no_short_word() -> None:
    content = "年月,年月 ,売上\n2024-01,1,1\n2024-02,2,2\n".encode()
    assert _verdict(_bar("年月", "売上"), "月ごとの売上の合計", content) == "column_not_named"


@pytest.mark.parametrize(
    ("header", "key", "ask", "expected"),
    [
        ("年月,売上", "年月", "月\U00020bb7ごとの売上の合計", "column_not_named"),
        ("\U00020bb7田,売上", "\U00020bb7田", "\U00020bb7ごとの売上の合計", "VERIFIED"),
        ("年月,売上", "年月", "月﨑ごとの売上の合計", "column_not_named"),
        ("﨑田,売上", "﨑田", "﨑ごとの売上の合計", "VERIFIED"),
    ],
    ids=["ext-b-in-run", "ext-b-short-word", "compat-in-run", "compat-short-word"],
)
def test_q41_t1_a_run_spans_every_nfkc_stable_ideograph(
    header: str, key: str, ask: str, expected: str
) -> None:
    """`𠮷` (Ext B) + `﨑` (an NFKC-stable compatibility ideograph) are kanji: `月𠮷` is one
    whole run that fits no name, and `𠮷` alone names `𠮷田`."""
    content = f"{header}\n1,1\n2,2\n".encode()
    assert _verdict(_bar(key, "売上"), ask, content) == expected


def test_q41_t1_a_fold_twin_name_still_ties_a_run_it_fits() -> None:
    """`年` fits `年月` and `年齢` (two headers fold to it): a tie, so `年月` stays unnamed."""
    content = "年月,年齢,年齢 ,売上\n2024-01,30,31,1\n2024-02,40,41,2\n".encode()
    assert _verdict(_bar("年月", "売上"), "年ごとの売上の合計", content) == "column_not_named"
