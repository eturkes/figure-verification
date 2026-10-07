# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q8: lexical request anchoring refuses a column substitution and nothing else.

User ruling: refuse substitutions only, as `column_not_requested`; NFKC + width folding; edit
distance 1 for terms of 5+ characters; a tie refuses. A substitution = the program drops a column
the request names AND plots one the request never names. Contract `.agent/archive/contracts/q8.md`.
"""

from typing import SupportsIndex

import pytest

from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits
from verifier.pysrc.spec import DatasetTarget
from verifier.pysrc.verify import Verified, _unnamed_places, verify_python_source
from webui.paste_in import selection
from webui.paste_in.owui_files import UploadedFile

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_SALES = b"region,month,revenue,orders\nwest,2024-01,1,5\neast,2024-02,2,6\n"
_WEATHER = b"date,city,temp_c,precip_mm\n2024-01-01,a,1.5,2\n2024-01-02,b,2.5,3\n"
_BY_REGION = "Make a bar chart of total revenue for each region."


def _bar(key: str, value: str = "revenue", *, path: str = "data.csv") -> str:
    return (
        _PRELUDE
        + f'df = pd.read_csv("{path}")\n'
        + f'g = df.groupby("{key}")["{value}"].sum()\nplt.bar(g.index, g.values)\nplt.show()\n'
    )


def _verdict(
    program: str,
    request: str | None,
    content: bytes = _SALES,
    limits: PysrcLimits = DEFAULT_LIMITS,
) -> str:
    verdict = verify_python_source(
        program,
        declared_target=DatasetTarget("data.csv", content, request),
        limits=limits,
    )
    return "VERIFIED" if isinstance(verdict, Verified) else verdict.code


def test_q8_substitution_witness_refuses() -> None:
    """Accept: the request names `region`, the program draws `month` in its place."""
    assert _verdict(_bar("month"), _BY_REGION) == "column_not_requested"
    assert _verdict(_bar("region"), _BY_REGION) == "VERIFIED"
    assert _verdict(_bar("month"), None) == "VERIFIED"


def test_q8_an_unnamed_plotted_column_alone_passes() -> None:
    """The request names the measure only; the program picks its own x column."""
    assert _verdict(_bar("month"), "chart revenue") == "VERIFIED"


def test_q8_an_unplotted_named_column_alone_passes() -> None:
    """Three named columns, two drawn: nothing the request never named takes a slot."""
    assert _verdict(_bar("region"), "revenue and orders by region") == "VERIFIED"


def test_q8_a_request_naming_no_column_passes() -> None:
    assert _verdict(_bar("month"), "Make a bar chart.") == "VERIFIED"


def test_q8_a_word_within_one_edit_of_two_headers_is_a_tie() -> None:
    """`match` is one edit from `batch` and from `patch`: the request does not say which."""
    content = b"batch,patch,value\na,b,1\nc,d,2\n"
    assert _verdict(_bar("batch", "value"), "value by match", content) == "column_not_requested"
    assert _verdict(_bar("batch", "value"), "value by batch", content) == "VERIFIED"


def test_q8_a_tie_beside_an_exact_name_still_refuses() -> None:
    """Kernel review K1: `batch` named exactly elsewhere leaves `match` tied all the same."""
    content = b"batch,patch,value\na,b,1\nc,d,2\n"
    program = _bar("batch", "value")
    assert _verdict(program, "value by batch and match", content) == "column_not_requested"


def test_q8_two_headers_folding_to_one_name_tie() -> None:
    """`revenue` names `revenue` and `REVENUE` alike: no unique match."""
    content = b"region,revenue,REVENUE\nwest,1,2\neast,3,4\n"
    assert _verdict(_bar("region"), "Revenue by region", content) == "column_not_requested"
    assert _verdict(_bar("region"), "Chart it by region", content) == "VERIFIED"


def test_q8_a_longer_name_consumes_the_shorter_one_inside_it() -> None:
    """`unit price` names `unit_price` alone, never also `price`, whatever the header order."""
    content = b"price,unit_price,region\n1,2,west\n3,4,east\n"
    program = _bar("region", "unit_price")
    assert _verdict(program, "average unit price", content) == "VERIFIED"
    assert _verdict(program, "average price", content) == "column_not_requested"


def test_q8_a_longer_japanese_name_consumes_the_shorter_one_inside_it() -> None:
    content = "日付,収縮期血圧,収縮期血圧値\n1,2,3\n2,3,4\n".encode()
    program = _bar("日付", "収縮期血圧値")
    assert _verdict(program, "収縮期血圧値の平均", content) == "VERIFIED"


def test_q8_overlapping_near_matches_are_one_place() -> None:
    """`収縮期血庄変動`: one stretch fits `収縮期血圧` and an overlapping one fits `期血圧変動`:
    one place, two names, a tie, though no single stretch fits both."""
    content = "日付,収縮期血圧,期血圧変動\n1,120,3\n2,130,4\n".encode()
    program = _bar("日付", "収縮期血圧")
    assert _verdict(program, "日付ごとの収縮期血庄変動", content) == "column_not_requested"


def test_q8_a_name_twice_in_a_row_is_consumed_both_times() -> None:
    """Kernel review: adjacent occurrences share a space; one replace pass skipped the second."""
    content = b"price,unit_price,region\n1,2,west\n3,4,east\n"
    program = _bar("region", "unit_price")
    assert _verdict(program, "average unit price (unit_price)", content) == "VERIFIED"


def test_q8_one_edit_names_a_long_japanese_header() -> None:
    """Kernel review K2: the ruling's one edit at 5+ characters binds Japanese names too."""
    content = "日付,収縮期血圧,拡張期血圧\n1,120,80\n2,130,85\n".encode()
    request = "日付ごとの収宿期血圧の平均"
    assert _verdict(_bar("日付", "拡張期血圧"), request, content) == "column_not_requested"
    assert _verdict(_bar("日付", "収縮期血圧"), request, content) == "VERIFIED"
    assert _verdict(_bar("日付", "収縮期血圧"), "日付ごとの収張期血圧", content) == (
        "column_not_requested"
    )


def test_q8_an_exact_word_never_names_its_near_neighbour() -> None:
    """`batch` names `batch` alone, so a program drawing `patch` substitutes it."""
    content = b"batch,patch,value\na,b,1\nc,d,2\n"
    assert _verdict(_bar("patch", "value"), "value by batch", content) == "column_not_requested"


@pytest.mark.parametrize(
    "request_text",
    ["revenue by regon", "revenue by regions", "revenue by regiom", "revenue by rigion"],
    ids=["deletion", "insertion", "end-substitution", "inner-substitution"],
)
def test_q8_one_edit_names_a_long_header(request_text: str) -> None:
    """Deletion, insertion, and substitution at the end and inside the word."""
    assert _verdict(_bar("month"), request_text) == "column_not_requested"


def test_q8_two_edits_name_nothing() -> None:
    """`monthly` is two edits from `month`: not named, so `region` takes no named slot."""
    assert _verdict(_bar("region"), "monthly revenue") == "VERIFIED"


def test_q8_fuzzy_matching_needs_five_characters() -> None:
    """`citi` is one edit from the 4-letter `city`, which matches exactly or not at all."""
    program = _bar("date", "temp_c")
    assert _verdict(program, "total temp_c per citi", _WEATHER) == "VERIFIED"
    assert _verdict(program, "total temp_c per city", _WEATHER) == "column_not_requested"


def test_q8_ascii_headers_shorter_than_three_never_anchor() -> None:
    content = b"id,group,value\n1,a,5\n2,b,6\n"
    assert _verdict(_bar("group", "value"), "value by id", content) == "VERIFIED"


def test_q8_underscore_reads_as_a_space() -> None:
    """`temp c` names `temp_c`; the program draws `precip_mm` in its place."""
    program = _bar("city", "precip_mm")
    assert _verdict(program, "total temp c by city", _WEATHER) == "column_not_requested"
    assert _verdict(program, "total precip mm by city", _WEATHER) == "VERIFIED"


def test_q8_width_folds_before_matching() -> None:
    request = "ｒｅｖｅｎｕｅ ｂｙ ｒｅｇｉｏｎ"  # noqa: RUF001 - the full-width witness itself
    assert _verdict(_bar("month"), request) == "column_not_requested"


def test_q8_case_folds_before_matching() -> None:
    """Upper case alone: no word sits within one edit of a header unfolded."""
    assert _verdict(_bar("month"), "TOTAL REVENUE BY REGION") == "column_not_requested"


def test_q8_words_split_where_ascii_meets_japanese() -> None:
    request = "regionごとのrevenueの合計を棒グラフにしてください。"
    assert _verdict(_bar("month"), request) == "column_not_requested"
    assert _verdict(_bar("region"), request) == "VERIFIED"


def test_q8_japanese_headers_anchor_inside_the_request() -> None:
    content = "年月,地域,売上\n2024-01,東,1\n2024-02,西,2\n".encode()
    request = "地域ごとの売上の合計を棒グラフにしてください。"
    assert _verdict(_bar("年月", "売上"), request, content) == "column_not_requested"
    assert _verdict(_bar("地域", "売上"), request, content) == "VERIFIED"


def test_q8_one_character_japanese_headers_never_anchor() -> None:
    """`月` sits inside too many words (`月曜`, `今月`) to name a column."""
    content = "月,地域,売上\n1,東,1\n2,西,2\n".encode()
    assert _verdict(_bar("地域", "売上"), "月ごとの売上を棒グラフに", content) == "VERIFIED"


_UNREADABLE_HEADER = {
    "bom": b"\xef\xbb\xbf" + _SALES,
    "nul": _SALES + b"north,2024-03,\x003,7\n",
    "cr-endings": _SALES.replace(b"\n", b"\r"),
    "not-utf8": _SALES + b"\xff,2024-03,3,7\n",
    "empty": b"",
    "header-quote": b'"region"x,month,revenue,orders\nwest,2024-01,1,5\n',
}


@pytest.mark.parametrize("content", _UNREADABLE_HEADER.values(), ids=_UNREADABLE_HEADER)
def test_q8_an_unreadable_header_leaves_recompute_refusal(content: bytes) -> None:
    """A header `read_columns` refuses to read anchors nothing: its own refusal names the fault."""
    alone = _verdict(_bar("month"), None, content)
    assert alone not in {"VERIFIED", "column_not_requested"}
    assert _verdict(_bar("month"), _BY_REGION, content) == alone


def test_q8_an_oversize_file_leaves_recompute_refusal() -> None:
    limits = PysrcLimits(max_csv_bytes=len(_SALES) - 1)
    assert _verdict(_bar("month"), _BY_REGION, limits=limits) == "csv_too_large"


_REFUSED_HEADER = {
    "duplicate-name": (b"region,month,revenue,region\nwest,2024-01,1,a\neast,2024-02,2,b\n", None),
    "empty-name": (b"region,month,revenue,\nwest,2024-01,1,a\neast,2024-02,2,b\n", None),
    "too-many-columns": (_SALES, PysrcLimits(max_csv_columns=3)),
    "oversize-name": (_SALES, PysrcLimits(max_csv_cell_bytes=6)),
    "header-work": (_SALES, PysrcLimits(max_work=3)),
}


@pytest.mark.parametrize(("content", "limits"), _REFUSED_HEADER.values(), ids=_REFUSED_HEADER)
def test_q8_a_header_read_columns_refuses_leaves_recompute_refusal(
    content: bytes, limits: PysrcLimits | None
) -> None:
    """Each header-record check `read_columns` applies, mirrored: the refusal stays its own."""
    chosen = limits or DEFAULT_LIMITS
    alone = _verdict(_bar("month"), None, content, chosen)
    assert alone not in {"VERIFIED", "column_not_requested"}
    assert _verdict(_bar("month"), _BY_REGION, content, chosen) == alone


def test_q8_a_plotted_column_absent_from_the_header_leaves_recompute_refusal() -> None:
    assert _verdict(_bar("regoin"), _BY_REGION) == "column_not_present"


def test_q8_binding_precedes_recompute() -> None:
    """A substitution whose y is also categorical reports the substitution first."""
    program = (
        _PRELUDE + 'df = pd.read_csv("data.csv")\nplt.scatter(df["orders"], df["region"])\n'
        "plt.show()\n"
    )
    request = "Draw orders against revenue as a scatter plot."
    assert _verdict(program, None) == "column_not_numeric"
    assert _verdict(program, request) == "column_not_requested"


def test_q8_selection_threads_the_request_into_every_dataset_target() -> None:
    upload = UploadedFile("file", "/mnt/uploads/sales.csv", _SALES)
    program = _bar("month", path="/mnt/uploads/sales.csv")
    refused, consumed = selection.first_verdict(program, (upload,), _BY_REGION)
    assert consumed is upload
    assert not isinstance(refused, Verified) and refused is not None
    assert refused.code == "column_not_requested"
    verified, _ = selection.first_verdict(program, (upload,), None)
    assert isinstance(verified, Verified)


# Q38: stop phrases + negation. Contract `.agent/archive/contracts/q38.md`.
_PHRASES = [
    "chronological order",
    "alphabetical order",
    "descending order",
    "ascending order",
    "numerical order",
    "reverse order",
    "sorted order",
    "sort order",
    "in order",
]


@pytest.mark.parametrize("phrase", _PHRASES)
def test_q38_n1_a_stop_phrase_names_no_header(phrase: str) -> None:
    """`order` is one edit from `orders`: the phrase alone made `orders` a named, undrawn column."""
    assert _verdict(_bar("month"), f"Chart total revenue in {phrase}") == "VERIFIED"


def test_q38_n1_a_header_spelled_as_a_stop_phrase_is_still_named() -> None:
    content = b"sort_order,month,revenue\n1,2024-01,5\n2,2024-02,6\n"
    request = "Chart revenue by sort order"
    assert _verdict(_bar("month"), request, content) == "column_not_requested"
    assert _verdict(_bar("sort_order"), request, content) == "VERIFIED"


def test_q38_n1_a_header_beside_a_stop_phrase_is_named_by_its_own_word() -> None:
    content = b"order,month,revenue\n1,2024-01,5\n2,2024-02,6\n"
    request = "Chart revenue by order, in chronological order"
    assert _verdict(_bar("month"), request, content) == "column_not_requested"


@pytest.mark.parametrize(
    "cue",
    [
        "not",
        "no",
        "without",
        "except",
        "excluding",
        "rather than",
        "instead of",
        "not the",
        "no any",
    ],
)
def test_q38_n2_an_english_cue_unnames_the_header_after_it(cue: str) -> None:
    """`orders` follows the cue: excluded, so drawing `month` substitutes nothing."""
    assert _verdict(_bar("month"), f"Chart total revenue, {cue} orders") == "VERIFIED"


def test_q38_n2_a_negated_name_within_one_edit_is_unnamed() -> None:
    assert _verdict(_bar("month"), "Chart total revenue, not ordrs") == "VERIFIED"


def test_q38_n2_a_negated_multiword_name_is_unnamed_whole() -> None:
    content = b"price,unit_price,region\n1,2,west\n3,4,east\n"
    program = _bar("region", "price")
    assert _verdict(program, "average by region, not unit price", content) == "VERIFIED"


@pytest.mark.parametrize(
    "cue",
    ["ではなく", "じゃなく", "でなく", "以外", "を除いて"],
    ids=["dewanaku", "janaku", "denaku", "igai", "wo-nozoite"],
)
def test_q38_n3_a_japanese_cue_unnames_the_header_before_it(cue: str) -> None:
    content = "年月,地域,売上,注文数\n2024-01,東,1,5\n2024-02,西,2,6\n".encode()
    program = _bar("年月", "売上")
    assert _verdict(program, f"注文数{cue}、売上の合計を表示", content) == "VERIFIED"


def test_q38_n3_a_japanese_cue_unnames_an_ascii_header_before_it() -> None:
    assert _verdict(_bar("month"), "ordersではなくrevenueの合計") == "VERIFIED"


def test_q38_n4_a_cue_before_a_non_name_negates_nothing() -> None:
    """`not only revenue but orders` names both: `orders` undrawn, `month` drawn unnamed."""
    program = _bar("month")
    assert _verdict(program, "Chart not only revenue but orders") == "column_not_requested"


def test_q38_n4_a_name_negated_once_and_named_elsewhere_stays_named() -> None:
    program = _bar("month")
    assert _verdict(program, "Chart revenue, not orders. Well, orders too") == (
        "column_not_requested"
    )


def test_q38_n4_a_negated_place_joins_no_tie() -> None:
    """`match` is one edit from `batch` and from `patch`; negated, it asks for neither."""
    content = b"batch,patch,value\na,b,1\nc,d,2\n"
    assert _verdict(_bar("batch", "value"), "value, not match", content) == "VERIFIED"


@pytest.mark.parametrize(
    "cue",
    ["ではなく", "じゃなく", "でなく", "以外", "を除いて"],
    ids=["dewanaku", "janaku", "denaku", "igai", "wo-nozoite"],
)
def test_q38_n3_a_mixed_script_header_ending_in_ascii_is_unnamed(cue: str) -> None:
    """Kernel review: `気温_C` folds to `気温 c`; `_words` splits it from the cue after it."""
    content = "年月,売上,気温_C\n2024-01,1,5\n2024-02,2,6\n".encode()
    program = _bar("年月", "売上")
    assert _verdict(program, f"気温_C{cue}売上の合計", content) == "VERIFIED"


@pytest.mark.parametrize(
    ("column", "request_text"),
    [
        ("any", "Chart revenue, not 'any'."),
        ("the", "Chart revenue, not 'the'."),
        ("any_adverse_event", "Chart revenue, not any adverse event"),
        ("the_count", "Chart revenue, without the count"),
    ],
)
def test_q38_n2_a_header_opening_with_a_filler_word_is_negated(
    column: str, request_text: str
) -> None:
    """Kernel review: the cue's own successor is tried as a name before `the`/`any` is a filler."""
    content = f"{column},month,revenue\n0,2024-01,1\n1,2024-02,2\n".encode()
    assert _verdict(_bar("month"), request_text, content) == "VERIFIED"


def test_q38_k8_a_cue_scan_copies_text_linear_in_the_request() -> None:
    """Kernel review: each cue once copied the whole rest of the request (quadratic in cues)."""

    class Counted(str):
        copied = 0

        def __getitem__(self, key: SupportsIndex | slice) -> str:
            result = super().__getitem__(key)
            if isinstance(key, slice):
                Counted.copied += len(result)
            return result

    def copied(count: int) -> int:
        Counted.copied = 0
        text = Counted(" " + "not only " * count)
        assert _unnamed_places(text, ["month", "revenue", "orders"]) == text
        return Counted.copied

    small, large = copied(128), copied(256)
    assert large <= 3 * small, (small, large)


def test_q38_n3_negation_matches_by_containment_like_naming() -> None:
    """Kernel re-review: `SBP値` names `BP値` by containment, so `SBP値ではなく` negates it."""
    content = "年月,売上,BP値\n2024-01,1,5\n2024-02,2,6\n".encode()
    assert _verdict(_bar("年月", "売上"), "SBP値ではなく売上の合計", content) == "VERIFIED"


def test_q38_a_cue_inside_a_negated_name_is_not_a_second_cue() -> None:
    """`not no show month`: `no show` is the negated name, so its `no` cues nothing and `month`
    stays named -- read as a cue, it would swallow `show month` and hide `month`."""
    content = b"no_show,show_month,month,revenue\na,b,2024-01,1\nc,d,2024-02,2\n"
    program = _bar("show_month")
    assert _verdict(program, "Total revenue, not no show month", content) == "column_not_requested"
