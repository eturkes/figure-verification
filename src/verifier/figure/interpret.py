# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""What was verified, in plain words, English and Japanese (tier 3: publication).

One sentence per drawn series names where its values come from: a CSV column, one reduction per
group with each group's row count (G11), a filter by its legend name (R6), the request's typed
numbers, or none. A drawn subset says N of M (R2). A figure with no data source says it was
checked for integrity alone (ruling 4). Text on the chart is listed, never judged (ruling 6).
"""

from typing import Final

from verifier.figure.explain import Choice, Explanation

_MARKS: Final = {
    "line": ("Line", "折れ線"),
    "scatter": ("Points", "散布点"),
    "bar": ("Bars", "棒"),
    "hist": ("Histogram", "ヒストグラム"),
    "pie": ("Pie", "円グラフ"),
    "band": ("Area", "面"),
    "reference": ("Reference mark", "基準線"),
    "colors": ("Point colours", "点の色"),
    "sizes": ("Point sizes", "点の大きさ"),
}
_REDUCTIONS: Final = {
    "sum": ("sum", "合計"),
    "mean": ("mean", "平均"),
    "min": ("minimum", "最小値"),
    "max": ("maximum", "最大値"),
}
_SOURCES: Final = {
    "self": ("{value} from {file}", "{file} の {value} 列"),
    "raw": ("{value} by {key} from {file}", "{file} の {value} 列 ({key} 列ごと)"),
    "index": ("{value} in row order from {file}", "{file} の {value} 列 (行の順)"),
    "count": ("the number of rows per {key} from {file}", "{file} の {key} 列ごとの行数"),
    "reduced": (
        "the {reduction} of {value} per {key} from {file}",
        "{file} の {key} 列ごとの {value} 列の{reduction}",
    ),
}
_WHERE: Final = (", rows where {column} is {cell}", " ({column} 列が {cell} の行)")
# A reference mark's clauses.
_HELD: Final = ("a value of {columns} from {file}", "{file} の {columns} 列の値")
_AND: Final = (" and ", "、")
_SHARED: Final = ("{n} value(s) held by several columns", "複数の列にある値 {n} 件")
_TYPED: Final = ("zero or a number typed in the request", "ゼロまたは依頼文の数値")
_TYPED_COUNT: Final = ("{n} value(s) zero or typed in the request", "ゼロまたは依頼文の数値 {n} 件")
_JOIN: Final = ("; ", "。")
_STOP: Final = (".", "。")
_GROUPS_SHOWN: Final = 8
_TEXTS_SHOWN: Final = 8
_INTEGRITY_ONLY: Final = (
    "No data was attached or typed in the request, so the values were not compared with data."
    " The chart passed the integrity checks alone.",
    "データが添付されておらず、依頼文にも数値がないため、値はデータと照合していません。"
    "グラフは完全性のチェックだけに合格しました。",
)


def _quote(text: str) -> str:
    return f'"{text}"'


def _groups(explanation: Explanation, *, japanese: bool) -> str:
    counts = explanation.counts or ()
    shown = [
        f"{key} {count}" if not japanese else f"{key} {count} 行"
        for (key, _value), count in zip(explanation.pairs, counts, strict=True)
    ][:_GROUPS_SHOWN]
    more = len(counts) > _GROUPS_SHOWN
    if japanese:
        return "各グループの行数: " + "、".join(shown) + ("、…" if more else "")
    return "rows per group: " + ", ".join(shown) + (", …" if more else "")


def _source(explanation: Explanation, *, japanese: bool) -> str:
    family, language = explanation.family, 1 if japanese else 0
    if family in ("sum", "mean", "min", "max"):
        form = "reduced"
    elif family == "raw" and explanation.key == explanation.value:
        form = "self"
    else:
        form = family
    text = _SOURCES[form][language].format(
        file=explanation.table,
        key=explanation.key,
        value=explanation.value,
        reduction=_REDUCTIONS[family][language] if form == "reduced" else "",
    )
    if explanation.where is not None:
        column, cell = explanation.where
        text += _WHERE[language].format(column=column, cell=cell)
    return text


def _reference(named: str, choice: Choice, *, japanese: bool) -> str:
    """A reference mark: the columns that alone hold its values, values several columns hold,
    and values that are zero or typed in the request."""
    language = 1 if japanese else 0
    parts = [
        _HELD[language].format(columns=_AND[language].join(columns), file=file)
        for file, columns in ((file, sorted(c)) for file, c in choice.columns)
    ]
    if choice.shared:
        parts.append(_SHARED[language].format(n=choice.shared))
    if choice.from_request:
        typed = _TYPED[language]
        parts.append(typed if not parts else _TYPED_COUNT[language].format(n=choice.from_request))
    return f"{named}: " + _JOIN[language].join(parts) + _STOP[language]


def _sentence(choice: Choice, *, japanese: bool) -> str:
    series = choice.series
    mark = _MARKS[series.mark.family if series.channel == "value" else series.channel][
        1 if japanese else 0
    ]
    named = f"{mark} {_quote(series.name)}" if series.name is not None else mark
    explanation = choice.explanation
    if explanation is None:
        if series.shape == "reference":
            return _reference(named, choice, japanese=japanese)
        source = "依頼文に入力された数値" if japanese else "numbers typed in the request"
        return f"{named}: {source}。" if japanese else f"{named}: {source}."
    parts = [_source(explanation, japanese=japanese)]
    total = len(explanation.pairs)
    if choice.matched < total:
        parts.append(
            f"{total} 件中 {choice.matched} 件を描画"
            if japanese
            else f"{choice.matched} of {total} drawn"
        )
    if explanation.counts is not None and explanation.family != "count":
        parts.append(_groups(explanation, japanese=japanese))
    if choice.from_request:
        parts.append(
            f"依頼文の数値 {choice.from_request} 件"
            if japanese
            else f"{choice.from_request} value(s) typed in the request"
        )
    if japanese:
        return f"{named}: " + "。".join(parts) + "。"
    return f"{named}: " + "; ".join(parts) + "."


def interpretation(
    choices: tuple[Choice, ...], texts: tuple[str, ...], *, integrity_only: bool, japanese: bool
) -> str:
    """The plain-words record of what passed, in one language."""
    sentences = [_INTEGRITY_ONLY[1 if japanese else 0]] if integrity_only else []
    sentences += [_sentence(choice, japanese=japanese) for choice in choices]
    if texts:
        shown = ", ".join(_quote(text) for text in texts[:_TEXTS_SHOWN])
        more = len(texts) > _TEXTS_SHOWN
        if japanese:
            sentences.append(f"グラフ上の文字は確認していません: {shown}{'、…' if more else ''}。")
        else:
            sentences.append(f"Text on the chart was not checked: {shown}{', …' if more else ''}.")
    return "\n".join(sentences)
