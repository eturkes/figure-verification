# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""What was verified, in plain words, English and Japanese (tier 3: publication).

One sentence per drawn series names where its values come from: a CSV column, one reduction per
group with each group's row count (G11), a filter by its legend name (R6), the request's typed
numbers, one admitted computation of any of these (Q45: its operands in order), or none. A
drawn subset says N of M (R2). A figure with no data source says it was
checked for integrity alone (ruling 4). Text on the chart is listed, never judged (ruling 6).
Open WebUI renders the reply as markdown, so every name, cell, file name and chart text is one
inline code span (`inert.py`, M21.1 F1); only this module's own words stay prose.
"""

from typing import Final, cast

from verifier.figure.explain import Choice, Explanation
from verifier.figure.inert import code

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
# Q45: one computation of a source (`{base}` = its sentence part above, or the typed numbers).
_UNARY: Final = {
    "square": ("the square of {base}", "{base}の2乗"),
    "cumsum": ("the running total of {base}", "{base}の累計"),
    "diff": ("the change from the previous point of {base}", "{base}の前の点からの変化"),
    "share": ("the share of the total of {base}", "{base}の合計に対する割合"),
    "percent": ("the percent of the total of {base}", "{base}の合計に対する百分率"),
}
_BINARY: Final = {
    "ratio": ("{a} divided by {b}", "{a} 列を {b} 列で割った値"),
    "difference": ("{a} minus {b}", "{a} 列から {b} 列を引いた値"),
    "product": ("{a} times {b}", "{a} 列と {b} 列の積"),
    "total": ("{a} plus {b}", "{a} 列と {b} 列の和"),
}
_BINARY_SOURCES: Final = {
    "raw": ("{op} by {key} from {file}", "{file} の {op} ({key} 列ごと)"),
    "index": ("{op} in row order from {file}", "{file} の {op} (行の順)"),
    "sum": ("{op}, each summed per {key}, from {file}", "{file} の {key} 列ごとに合計した {op}"),
}
_OPERANDS: Final = (
    "the numbers typed in the request ({numbers})",
    "依頼文の数値 ({numbers}) ",
)
_OPERANDS_SHOWN: Final = 8
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


def _named(name: str | None) -> str:
    return "" if name is None else code(name)


def _groups(explanation: Explanation, *, japanese: bool) -> str:
    counts = explanation.counts or ()
    shown = [
        f"{code(str(key))} {count}" if not japanese else f"{code(str(key))} {count} 行"
        for (key, _value), count in zip(explanation.pairs, counts, strict=True)
    ][:_GROUPS_SHOWN]
    more = len(counts) > _GROUPS_SHOWN
    if japanese:
        return "各グループの行数: " + "、".join(shown) + ("、…" if more else "")
    return "rows per group: " + ", ".join(shown) + (", …" if more else "")


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() and abs(value) < 2**53 else repr(value)


def _operands(numbers: tuple[float, ...], *, japanese: bool) -> str:
    shown = [_number(value) for value in numbers[:_OPERANDS_SHOWN]]
    more = len(numbers) > _OPERANDS_SHOWN
    text = ("、" if japanese else ", ").join(shown) + (
        ("、…" if japanese else ", …") if more else ""
    )
    return _OPERANDS[1 if japanese else 0].format(numbers=text)


def _binary(explanation: Explanation, *, japanese: bool) -> str:
    language = 1 if japanese else 0
    transform = cast("str", explanation.transform)
    op = _BINARY[transform][language].format(
        a=_named(explanation.value), b=_named(explanation.other)
    )
    return _BINARY_SOURCES[explanation.family][language].format(
        op=op, key=_named(explanation.key), file=code(explanation.table)
    )


def _source(explanation: Explanation, *, japanese: bool) -> str:
    transform = explanation.transform
    if transform is not None and transform in _BINARY:
        text = _binary(explanation, japanese=japanese)
    else:
        text = _base(explanation, japanese=japanese)
        if transform is not None:
            text = _UNARY[transform][1 if japanese else 0].format(base=text)
    if explanation.where is not None:
        column, cell = explanation.where
        text += _WHERE[1 if japanese else 0].format(column=code(column), cell=code(cell))
    return text


def _base(explanation: Explanation, *, japanese: bool) -> str:
    family, language = explanation.family, 1 if japanese else 0
    if family in ("sum", "mean", "min", "max"):
        form = "reduced"
    elif family == "raw" and explanation.key == explanation.value:
        form = "self"
    else:
        form = family
    return _SOURCES[form][language].format(
        file=code(explanation.table),
        key=_named(explanation.key),
        value=_named(explanation.value),
        reduction=_REDUCTIONS[family][language] if form == "reduced" else "",
    )


def _reference(named: str, choice: Choice, *, japanese: bool) -> str:
    """A reference mark: the columns that alone hold its values, values several columns hold,
    and values that are zero or typed in the request."""
    language = 1 if japanese else 0
    parts = [
        _HELD[language].format(columns=_AND[language].join(map(code, columns)), file=code(file))
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
    named = f"{mark} {code(series.name)}" if series.name is not None else mark
    explanation = choice.explanation
    if explanation is None:
        if series.shape == "reference":
            return _reference(named, choice, japanese=japanese)
        if choice.typed is not None:
            operands = _operands(choice.operands, japanese=japanese)
            source = _UNARY[choice.typed][1 if japanese else 0].format(base=operands)
        else:
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
    if explanation.counts is not None and (
        explanation.family != "count" or explanation.transform is not None
    ):
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
        shown = ", ".join(code(text) for text in texts[:_TEXTS_SHOWN])
        more = len(texts) > _TEXTS_SHOWN
        if japanese:
            sentences.append(f"グラフ上の文字は確認していません: {shown}{'、…' if more else ''}。")
        else:
            sentences.append(f"Text on the chart was not checked: {shown}{', …' if more else ''}.")
    return "\n".join(sentences)
