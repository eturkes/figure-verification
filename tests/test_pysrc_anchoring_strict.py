# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q37: strict request anchoring, production's rule.

User ruling (session 6): production = strict -- a request that names or negates a header column
must name every drawn column a request can name, else `column_not_named`; the demo keeps Q8's
substitution rule. Contract `.agent/archive/contracts/q37.md`.
"""

import pytest

from verifier.pysrc.spec import Anchoring, DatasetTarget
from verifier.pysrc.verify import Verified, verify_python_source

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_SALES = b"region,month,revenue,orders\nwest,2024-01,1,5\neast,2024-02,2,6\n"


def _bar(key: str, value: str = "revenue") -> str:
    return (
        _PRELUDE
        + 'df = pd.read_csv("data.csv")\n'
        + f'g = df.groupby("{key}")["{value}"].sum()\nplt.bar(g.index, g.values)\nplt.show()\n'
    )


def _verdict(
    program: str,
    request: str | None,
    anchoring: Anchoring = "strict",
    content: bytes = _SALES,
) -> str:
    target = DatasetTarget("data.csv", content, request, anchoring)
    verdict = verify_python_source(program, declared_target=target)
    return "VERIFIED" if isinstance(verdict, Verified) else verdict.code


def test_q37_s2_an_unnamed_drawn_column_refuses_under_strict_alone() -> None:
    """Accept: `chart revenue` drawn over `month` passes the demo's rule and refuses strict."""
    assert _verdict(_bar("month"), "Chart total revenue", "substitution") == "VERIFIED"
    assert _verdict(_bar("month"), "Chart total revenue") == "column_not_named"
    assert _verdict(_bar("month"), "Chart total revenue by month") == "VERIFIED"


def test_q37_s1_the_default_rule_is_strict() -> None:
    """Production first: a target built without a rule reads the request strictly."""
    target = DatasetTarget("data.csv", _SALES, "Chart total revenue")
    assert target.anchoring == "strict"
    verdict = verify_python_source(_bar("month"), declared_target=target)
    assert not isinstance(verdict, Verified)
    assert verdict.code == "column_not_named"


def test_q37_s2_a_request_naming_no_column_anchors_nothing() -> None:
    assert _verdict(_bar("month"), "Make a bar chart.") == "VERIFIED"
    assert _verdict(_bar("month"), None) == "VERIFIED"


def test_q37_s2_a_negated_column_triggers_strict() -> None:
    """A request that only excludes a column still states which columns it is about."""
    assert _verdict(_bar("month"), "Anything except orders", "substitution") == "VERIFIED"
    assert _verdict(_bar("month"), "Anything except orders") == "column_not_named"
    assert _verdict(_bar("month"), "Revenue by month, not orders") == "VERIFIED"


def test_q37_s2_a_drawn_negated_column_refuses_under_strict_alone() -> None:
    """User note: production refuses a chart drawing the column the request excludes."""
    request = "Total revenue, not month"
    assert _verdict(_bar("month"), request, "substitution") == "VERIFIED"
    assert _verdict(_bar("month"), request) == "column_not_named"


@pytest.mark.parametrize(
    ("content", "key", "value", "ask"),
    [
        (b"id,revenue\na,1\nb,2\n", "id", "revenue", "Chart total revenue"),
        ("月,売上\n1,1\n2,2\n".encode(), "月", "売上", "売上の合計"),
    ],
    ids=["two-char-ascii", "one-char-japanese"],
)
def test_q37_s2_a_column_no_request_can_name_is_not_required(
    content: bytes, key: str, value: str, ask: str
) -> None:
    assert _verdict(_bar(key, value), ask, content=content) == "VERIFIED"


def test_q37_s2_a_substitution_keeps_its_own_code_under_strict() -> None:
    """Strict extends the demo's rule: a swapped named column still reads as the swap."""
    assert _verdict(_bar("month"), "Total revenue by region") == "column_not_requested"
    content = b"id,region,revenue\na,west,1\nb,east,2\n"
    assert _verdict(_bar("id"), "Total revenue by region", content=content) == (
        "column_not_requested"
    )


def test_q37_s2_a_tie_refuses_under_strict() -> None:
    content = b"batch,patch,value\na,b,1\nc,d,2\n"
    assert _verdict(_bar("batch", "value"), "value by match", content=content) == (
        "column_not_requested"
    )


def test_q37_s2_a_column_two_headers_fold_to_cannot_be_named() -> None:
    """`Revenue` and `revenue` fold to one name: naming it ties, leaving it unnamed refuses."""
    content = b"month,Revenue,revenue\n2024-01,1,2\n2024-02,3,4\n"
    assert _verdict(_bar("month", "revenue"), "by month", content=content) == "column_not_named"


def test_q37_s2_a_japanese_negation_triggers_strict() -> None:
    content = "年月,売上,注文数\n2024-01,1,5\n2024-02,2,6\n".encode()
    program = _bar("年月", "売上")
    assert _verdict(program, "注文数ではなく", "substitution", content) == "VERIFIED"
    assert _verdict(program, "注文数ではなく", content=content) == "column_not_named"
