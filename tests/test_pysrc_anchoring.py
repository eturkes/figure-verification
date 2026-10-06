# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q8: lexical request anchoring refuses a column substitution and nothing else.

User ruling: refuse substitutions only, as `column_not_requested`; NFKC + width folding; edit
distance 1 for terms of 5+ characters; a tie refuses. A substitution = the program drops a column
the request names AND plots one the request never names. Contract `.agent/archive/contracts/q8.md`.
"""

import pytest

from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits
from verifier.pysrc.spec import DatasetTarget
from verifier.pysrc.verify import Verified, verify_python_source
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
