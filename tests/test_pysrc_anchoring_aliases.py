# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q43: an admin-declared alias is another name of its column wherever a header name counts.

User ruling (session 7): contract `.agent/archive/contracts/q43.md` approved as drafted. V3: an
alias names its column through exact naming, the one-edit tier, Q38 stop/negation, Q41/Q42 short
words and G10 labels, under both anchoring rules; an alias of a column the header lacks is ignored;
an alias two columns share, or equal to another column's name, is a tie; a column with an
anchoring-length alias becomes nameable under strict.
"""

import pytest

from anchoring_support import verdict
from verifier.figure.anchoring import Anchoring
from verifier.figure.judge import Sources

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_WEATHER = b"date,city,temp_c,precip_mm\n2024-01-01,Sapporo,1.5,0.5\n2024-01-02,Naha,2.5,1.5\n"
# `spec.Aliases`, spelled locally so each case reports its own red on a verifier without it.
type _Pairs = tuple[tuple[str, str], ...]
_ALIASES: _Pairs = (("temp_c", "temperature"), ("precip_mm", "rainfall"))


def _bar(key: str, value: str, decoration: str = "") -> str:
    return (
        _PRELUDE
        + 'df = pd.read_csv("data.csv")\n'
        + f'g = df.groupby("{key}")["{value}"].mean()\nplt.bar(g.index, g.values)\n'
        + decoration
        + "plt.show()\n"
    )


def _verdict(
    program: str,
    request: str | None,
    aliases: _Pairs = (),
    content: bytes = _WEATHER,
    anchoring: Anchoring = "strict",
) -> str:
    return verdict(program, request, content, anchoring=anchoring, aliases=aliases)


def test_q43_v3_an_alias_names_its_column_under_strict() -> None:
    """Accept: without the alias, `temperature` never names `temp_c` (A1 strict EN)."""
    program, ask = _bar("city", "temp_c"), "average temperature for each city"
    assert _verdict(program, ask) == "column_not_named"
    assert _verdict(program, ask, _ALIASES) == "VERIFIED"


def test_q43_v3_an_alias_matches_by_folded_column_and_alias() -> None:
    aliases = (("Temp_C", "ＴＥＭＰＥＲＡＴＵＲＥ"),)  # noqa: RUF001 - the full-width witness
    assert _verdict(_bar("city", "temp_c"), "temperature by city", aliases) == "VERIFIED"


def test_q43_v3_an_alias_counts_for_the_substitution_check_under_both_rules() -> None:
    """`temperature by city` drawn as rainfall: `temp_c` named + undrawn, `precip_mm` unnamed."""
    program, ask = _bar("city", "precip_mm"), "temperature by city"
    assert _verdict(program, ask, anchoring="substitution") == "VERIFIED"
    for anchoring in ("strict", "substitution"):
        verdict = _verdict(program, ask, _ALIASES, anchoring=anchoring)
        assert verdict == "column_not_requested"


def test_q43_v3_a_five_character_alias_takes_the_one_edit_tier() -> None:
    assert _verdict(_bar("city", "temp_c"), "temperatur by city", _ALIASES) == "VERIFIED"


def test_q43_v3_a_negated_alias_excludes_its_column() -> None:
    """`not temperature` consumes the alias: `temp_c` drawn and unnamed beside named rainfall."""
    ask = "rainfall by city, not temperature"
    assert _verdict(_bar("city", "temp_c"), ask, _ALIASES) == "column_not_requested"


def test_q43_v3_a_stop_phrase_alias_stays_a_name() -> None:
    """Q38 keeps a stop phrase that is a header's whole name; an alias name counts the same."""
    aliases = (("date", "in order"),)
    ask = "temperature in order"
    program = (
        _PRELUDE + 'df = pd.read_csv("data.csv")\nplt.plot(df["date"], df["temp_c"])\nplt.show()\n'
    )
    assert _verdict(program, ask, (*_ALIASES, *aliases)) == "VERIFIED"
    assert _verdict(program, ask, _ALIASES) == "column_not_named"


def test_q43_v3_a_japanese_alias_takes_the_short_word_tiers() -> None:
    """`日別` names `date` through its alias `日付` (Q41 + Q42), `気温` names `temp_c`."""
    ask = "日別の気温の平均を棒グラフにしてください。"
    program = _bar("date", "temp_c")
    aliases: _Pairs = (("temp_c", "気温"), ("date", "日付"))
    assert _verdict(program, ask, aliases) == "VERIFIED"
    assert _verdict(program, ask, aliases[:1]) == "column_not_named"
    assert _verdict(program, ask, aliases, anchoring="substitution") == "VERIFIED"


def test_q43_v3_an_alias_two_columns_share_is_a_tie() -> None:
    aliases = (("temp_c", "reading"), ("precip_mm", "reading"))
    assert _verdict(_bar("city", "temp_c"), "reading by city", aliases) == "column_not_requested"


def test_q43_v3_an_alias_equal_to_another_column_name_is_a_tie() -> None:
    aliases = (("temp_c", "city"),)
    assert _verdict(_bar("city", "temp_c"), "temp_c by city", aliases) == "column_not_requested"


def test_q43_v3_an_alias_of_its_own_column_name_is_no_tie() -> None:
    aliases = (("temp_c", "Temp C"), ("temp_c", "temp_c"))
    assert _verdict(_bar("city", "temp_c"), "temp c by city", aliases) == "VERIFIED"


def test_q43_v3_an_alias_of_an_absent_column_is_ignored() -> None:
    program, ask = _bar("city", "temp_c"), "humidity by city"
    aliases = (("humidity", "temp c"), ("humidity", "city"))
    assert _verdict(program, ask, aliases) == _verdict(program, ask) == "column_not_named"
    assert _verdict(program, "temp_c by city", aliases) == "VERIFIED"


def test_q43_v3_an_alias_makes_a_short_column_nameable_under_strict() -> None:
    """`t` alone is under the anchor minimum, so a request naming `city` leaves it exempt."""
    content = b"t,city\n1.5,Sapporo\n2.5,Naha\n"
    program, ask = _bar("city", "t"), "by city"
    assert _verdict(program, ask, content=content) == "VERIFIED"
    assert _verdict(program, ask, (("t", "temperature"),), content) == "column_not_named"
    assert _verdict(program, ask, (("t", "x"),), content) == "VERIFIED"


@pytest.mark.parametrize("anchoring", ["strict", "substitution"])
def test_q43_v3_a_label_naming_an_undrawn_columns_alias_refuses(anchoring: Anchoring) -> None:
    """G10 reads aliases under both rules; with no request, anchoring never runs."""
    program = _bar("city", "temp_c", 'plt.ylabel("Rainfall")\n')
    assert _verdict(program, None, anchoring=anchoring) == "VERIFIED"
    assert _verdict(program, None, _ALIASES, anchoring=anchoring) == "label_not_consistent"


def test_q43_v3_a_summary_word_an_alias_uses_names_its_column() -> None:
    """`Total` over a mean refuses as a summary word, unless an alias makes it a column name."""
    content = b"city,amount\nSapporo,1\nSapporo,3\nNaha,2\nNaha,6\n"
    program = _bar("city", "amount", 'plt.ylabel("Total")\n')
    assert _verdict(program, None, content=content) == "label_not_consistent"
    assert _verdict(program, None, (("amount", "total"),), content) == "VERIFIED"


def test_q43_v3_no_alias_is_the_default() -> None:
    assert Sources().aliases == ()
    assert Sources((("data.csv", _WEATHER),)) == Sources((("data.csv", _WEATHER),), aliases=())


@pytest.mark.parametrize("anchoring", ["strict", "substitution"])
def test_q43_v3_names_of_one_column_at_one_place_are_no_tie(anchoring: Anchoring) -> None:
    """`colur` is one edit from `color` and its alias `colour`: one column, so it names it."""
    content = b"city,color\nSapporo,1\nNaha,2\n"
    program, aliases = _bar("city", "color"), (("color", "colour"),)
    assert _verdict(program, "colur by city", (), content, anchoring) == "VERIFIED"
    assert _verdict(program, "colur by city", aliases, content, anchoring) == "VERIFIED"


def test_q43_v3_an_alias_never_hides_a_label_naming_an_undrawn_column() -> None:
    """G10 ignores ties; a header name and its own alias near one label word are no tie."""
    content = b"city,color,temp_c\nSapporo,1,1.5\nNaha,2,2.5\n"
    program = _bar("city", "temp_c", 'plt.ylabel("Colur")\n')
    for aliases in ((), (("color", "colour"),)):
        assert _verdict(program, None, aliases, content) == "label_not_consistent"


def test_q43_v3_short_words_fitting_names_of_one_column_name_it() -> None:
    """`月` fits both admin aliases `年月` and `月度` of `period`: one column, so it names it."""
    content = b"period,temp_c\n2024-01,1.5\n2024-02,2.5\n"
    program, ask = _bar("period", "temp_c"), "月ごとの気温の平均を棒グラフにしてください。"
    for aliases in ((("period", "年月"),), (("period", "年月"), ("period", "月度"))):
        assert _verdict(program, ask, (*aliases, ("temp_c", "気温")), content) == "VERIFIED"
