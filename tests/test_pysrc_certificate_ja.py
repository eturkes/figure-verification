# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M17.2 I1-I4: independent bilingual byte pins + interpretation invariants.

Contract: `.agent/archive/contracts/m17u2.md`. Expected text comes from its grammar, not a renderer.
"""

import importlib
import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from capture.harness import defence
from verifier.pysrc import Verified, spec, verify_python_source
from verifier.pysrc.certificate import CoreCertificate


@dataclass(frozen=True)
class _Witness:
    name: str
    source: str
    target: spec.DatasetTarget | spec.FormulaTarget | None
    japanese: str
    english: str


_PAIR_BYTES = b"time,value\n1,10\n2,20\n4,30\n"
_GROUP_BYTES = b"site,value\nwest,1\neast,2\nwest,3\neast,4\nwest,5\n"
_FORMULA = (
    "import numpy as np\nimport matplotlib.pyplot as plt\n"
    "grid_points = np.linspace(0, 1, num=3)\n"
    "curve_values = np.sin(grid_points)\n"
    "plt.plot(grid_points, curve_values)\nplt.show()\n"
)


def _pair(mark: str = "bar", labels: str = "") -> str:
    method = "plot" if mark == "line" else mark
    return (
        "import pandas as pd\nimport matplotlib.pyplot as plt\n"
        'frame = pd.read_csv("measurements.csv")\n'
        f'plt.{method}(frame["time"], frame["value"])\n{labels}plt.show()\n'
    )


def _aggregate(reduction: str, mark: str = "bar") -> str:
    return (
        "import pandas as pd\nimport matplotlib.pyplot as plt\n"
        'frame = pd.read_csv("measurements.csv")\n'
        f'reduced = frame.groupby("site")["value"].{reduction}()\n'
        f"plt.{mark}(reduced.index, reduced.values)\nplt.show()\n"
    )


def _target(domain: str) -> spec.FormulaTarget | None:
    if domain == "unbound":
        return None
    grid = spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(1)), 3)
    interval: spec.Grid | spec.Interval | None = (
        grid
        if domain == "grid"
        else spec.Interval(grid.start, grid.stop)
        if domain == "interval"
        else None
    )
    return spec.FormulaTarget(spec.Fn("sin", spec.Var()), interval)


_PAIR_TARGET = spec.DatasetTarget("measurements.csv", _PAIR_BYTES)
_GROUP_TARGET = spec.DatasetTarget("measurements.csv", _GROUP_BYTES)
_WITNESSES = (
    _Witness(
        "pair-bar",
        _pair(),
        _PAIR_TARGET,
        'グラフの種類: 棒グラフ。データはファイル "measurements.csv" から読み込みます。'
        'X 軸は列 "time" を表します。Y 軸は列 "value" を表します。'
        "描画する行は 3 行です。数値はプロファイル binary64-libm-v1 に従います。",
        'Chart type: bar. The data comes from the file "measurements.csv". '
        'X shows the column "time". Y shows the column "value". The chart draws 3 rows. '
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "pair-barh",
        _pair("barh"),
        _PAIR_TARGET,
        'グラフの種類: 横棒グラフ。データはファイル "measurements.csv" から読み込みます。'
        'Y 軸は列 "time" を表します。X 軸は列 "value" を表します。'
        "描画する行は 3 行です。数値はプロファイル binary64-libm-v1 に従います。",
        'Chart type: barh. The data comes from the file "measurements.csv". '
        'Y shows the column "time". X shows the column "value". The chart draws 3 rows. '
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "pair-line",
        _pair("line"),
        _PAIR_TARGET,
        'グラフの種類: 折れ線グラフ。データはファイル "measurements.csv" から読み込みます。'
        'X 軸は列 "time" を表します。Y 軸は列 "value" を表します。'
        "描画する行は 3 行です。数値はプロファイル binary64-libm-v1 に従います。",
        'Chart type: line. The data comes from the file "measurements.csv". '
        'X shows the column "time". Y shows the column "value". The chart draws 3 rows. '
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "pair-scatter",
        _pair("scatter"),
        _PAIR_TARGET,
        'グラフの種類: 散布図。データはファイル "measurements.csv" から読み込みます。'
        'X 軸は列 "time" を表します。Y 軸は列 "value" を表します。'
        "描画する行は 3 行です。数値はプロファイル binary64-libm-v1 に従います。",
        'Chart type: scatter. The data comes from the file "measurements.csv". '
        'X shows the column "time". Y shows the column "value". The chart draws 3 rows. '
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "aggregate-sum",
        _aggregate("sum"),
        _GROUP_TARGET,
        'グラフの種類: 棒グラフ。データはファイル "measurements.csv" から読み込みます。'
        'X 軸は列 "site" のグループを表します。Y 軸は各グループの列 "value" の合計を表します。'
        "5 行から 2 個のグループを描画します。数値はプロファイル binary64-libm-v1 に従います。",
        'Chart type: bar. The data comes from the file "measurements.csv". '
        'X shows the groups of the column "site". Y shows the sum of the column "value" '
        "in each group. The chart draws 2 groups from 5 rows. "
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "aggregate-mean",
        _aggregate("mean"),
        _GROUP_TARGET,
        'グラフの種類: 棒グラフ。データはファイル "measurements.csv" から読み込みます。'
        'X 軸は列 "site" のグループを表します。Y 軸は各グループの列 "value" の平均を表します。'
        "5 行から 2 個のグループを描画します。数値はプロファイル binary64-libm-v1 に従います。",
        'Chart type: bar. The data comes from the file "measurements.csv". '
        'X shows the groups of the column "site". Y shows the mean of the column "value" '
        "in each group. The chart draws 2 groups from 5 rows. "
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "aggregate-min-barh",
        _aggregate("min", "barh"),
        _GROUP_TARGET,
        'グラフの種類: 横棒グラフ。データはファイル "measurements.csv" から読み込みます。'
        'Y 軸は列 "site" のグループを表します。X 軸は各グループの列 "value" の最小値を表します。'
        "5 行から 2 個のグループを描画します。数値はプロファイル binary64-libm-v1 に従います。",
        'Chart type: barh. The data comes from the file "measurements.csv". '
        'Y shows the groups of the column "site". X shows the minimum of the column "value" '
        "in each group. The chart draws 2 groups from 5 rows. "
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "aggregate-max",
        _aggregate("max"),
        _GROUP_TARGET,
        'グラフの種類: 棒グラフ。データはファイル "measurements.csv" から読み込みます。'
        'X 軸は列 "site" のグループを表します。Y 軸は各グループの列 "value" の最大値を表します。'
        "5 行から 2 個のグループを描画します。数値はプロファイル binary64-libm-v1 に従います。",
        'Chart type: bar. The data comes from the file "measurements.csv". '
        'X shows the groups of the column "site". Y shows the maximum of the column "value" '
        "in each group. The chart draws 2 groups from 5 rows. "
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "formula-unbound",
        _FORMULA,
        None,
        "グラフの種類: 折れ線グラフ。データは送信されたプログラムから計算します。"
        "Y は sin(x) を計算します。X は 0 から 1 までの 3 点です。"
        "数値はプロファイル binary64-libm-v1 に従います。",
        "Chart type: line. The data comes from the submitted program. "
        "Y computes sin(x). X runs from 0 to 1 in 3 samples. "
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "formula-target-only",
        _FORMULA,
        _target("none"),
        "グラフの種類: 折れ線グラフ。データは送信されたプログラムから計算します。"
        "数式は依頼と一致します。Y は sin(x) を計算します。X は 0 から 1 までの 3 点です。"
        "数値はプロファイル binary64-libm-v1 に従います。",
        "Chart type: line. The data comes from the submitted program. "
        "The formula matches the request. Y computes sin(x). X runs from 0 to 1 in 3 samples. "
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "formula-interval",
        _FORMULA,
        _target("interval"),
        "グラフの種類: 折れ線グラフ。データは送信されたプログラムから計算します。"
        "数式と x の区間は依頼と一致します。Y は sin(x) を計算します。"
        "X は 0 から 1 までの 3 点です。数値はプロファイル binary64-libm-v1 に従います。",
        "Chart type: line. The data comes from the submitted program. "
        "The formula and the x interval match the request. "
        "Y computes sin(x). X runs from 0 to 1 in 3 samples. "
        "Numbers follow the profile binary64-libm-v1.",
    ),
    _Witness(
        "formula-grid",
        _FORMULA,
        _target("grid"),
        "グラフの種類: 折れ線グラフ。データは送信されたプログラムから計算します。"
        "数式、x の区間、サンプル数は依頼と一致します。Y は sin(x) を計算します。"
        "X は 0 から 1 までの 3 点です。数値はプロファイル binary64-libm-v1 に従います。",
        "Chart type: line. The data comes from the submitted program. "
        "The formula, the x interval and the sample count match the request. "
        "Y computes sin(x). X runs from 0 to 1 in 3 samples. "
        "Numbers follow the profile binary64-libm-v1.",
    ),
)
_LABELS = (
    ("x", 'plt.xlabel("時点")\n', 'X 軸ラベル: "時点"。', ' X label: "時点".'),
    ("y", 'plt.ylabel("測定値")\n', 'Y 軸ラベル: "測定値"。', ' Y label: "測定値".'),
    ("title", 'plt.title("結果")\n', 'タイトル: "結果"。', ' Title: "結果".'),
    (
        "all",
        'plt.title("結果")\nplt.ylabel("測定値")\nplt.xlabel("時点")\n',
        'X 軸ラベル: "時点"。Y 軸ラベル: "測定値"。タイトル: "結果"。',
        ' X label: "時点". Y label: "測定値". Title: "結果".',
    ),
    (
        "quoted",
        "plt.title('a\"b\\\\c\\n日本')\n",
        'タイトル: "a\\"b\\\\c\\n日本"。',
        ' Title: "a\\"b\\\\c\\n日本".',
    ),
    ("empty", 'plt.title("")\n', 'タイトル: ""。', ' Title: "".'),
)
_LABEL_WITNESSES = tuple(
    _Witness(
        base.name + "-label-" + name,
        base.source.replace("plt.show()\n", source + "plt.show()\n"),
        base.target,
        base.japanese + japanese,
        base.english + english,
    )
    for base in (_WITNESSES[0], _WITNESSES[8])
    for name, source, japanese, english in _LABELS
)


def _verified(witness: _Witness) -> Verified:
    verdict = verify_python_source(witness.source, declared_target=witness.target)
    assert isinstance(verdict, Verified), (witness.name, verdict)
    return verdict


def _japanese(certificate: CoreCertificate) -> str:
    text: object = getattr(certificate, "interpretation_ja")  # noqa: B009 - absent on red base
    assert isinstance(text, str)
    return text


def test_i1_field_set_gains_interpretation_ja_last() -> None:
    """I1: exact pre-unit ordered fields + one appended Japanese rendering."""
    assert tuple(CoreCertificate.__dataclass_fields__) == (
        "version",
        "source_sha256",
        "spec_sha256",
        "table_sha256",
        "group_counts",
        "provenance",
        "artifact_sha256",
        "numeric_profile",
        "checks",
        "declared_open",
        "interpretation",
        "interpretation_ja",
    )


@pytest.mark.parametrize("witness", _WITNESSES + _LABEL_WITNESSES, ids=lambda item: item.name)
def test_i2_japanese_bytes_per_branch(witness: _Witness) -> None:
    """I2: four marks, four reductions, four target shapes; both arms' quoted/ordered labels."""
    assert _japanese(_verified(witness).certificate) == witness.japanese


@pytest.mark.parametrize("witness", _WITNESSES + _LABEL_WITNESSES, ids=lambda item: item.name)
def test_i3_english_bytes_unchanged_per_branch(witness: _Witness) -> None:
    """I3: the exact same branch set, with independently hand-stated English bytes."""
    assert _verified(witness).certificate.interpretation == witness.english


@given(suffix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20))
@settings(max_examples=50)
def test_i4_japanese_text_is_model_free_and_total(suffix: str) -> None:
    """I4 property: alpha-renaming dataset/formula bindings changes neither rendering."""
    for witness in (_WITNESSES[0], _WITNESSES[4], _WITNESSES[8]):
        source = witness.source
        for identifier in ("frame", "reduced", "grid_points", "curve_values"):
            source = source.replace(identifier, "model_" + suffix + "_" + identifier)
        result = verify_python_source(source, declared_target=witness.target)
        assert isinstance(result, Verified), result
        text = _japanese(result.certificate)
        assert text == witness.japanese
        assert result.certificate.interpretation == witness.english
        assert text.startswith("グラフの種類: ")
        assert "model_" + suffix not in text


def test_i4_quoted_bound_names_remain_artifact_text() -> None:
    """I4: names disappear as bindings, never from a quoted path/header/label."""
    source = (
        "import pandas as pd\nimport matplotlib.pyplot as plt\n"
        'frame = pd.read_csv("frame")\n'
        'plt.bar(frame["frame"], frame["curve_values"])\n'
        'plt.xlabel("frame")\nplt.ylabel("curve_values")\nplt.title("grid_points")\nplt.show()\n'
    )
    result = verify_python_source(
        source, declared_target=spec.DatasetTarget("frame", b"frame,curve_values\n1,2\n3,4\n")
    )
    assert isinstance(result, Verified), result
    assert _japanese(result.certificate) == (
        'グラフの種類: 棒グラフ。データはファイル "frame" から読み込みます。'
        'X 軸は列 "frame" を表します。Y 軸は列 "curve_values" を表します。'
        "描画する行は 2 行です。数値はプロファイル binary64-libm-v1 に従います。"
        'X 軸ラベル: "frame"。Y 軸ラベル: "curve_values"。タイトル: "grid_points"。'
    )


@given(label=st.text(alphabet=st.characters(codec="utf-8"), max_size=80))
@settings(max_examples=60)
def test_i4_arbitrary_formula_labels_remain_json_quoted(label: str) -> None:
    """I4 property: opaque user labels stay verbatim inside JSON quotes, not semantics."""
    source = _FORMULA.replace("plt.show()", f"plt.title({label!r})\nplt.show()")
    result = verify_python_source(source)
    assert isinstance(result, Verified), result
    assert _japanese(result.certificate) == (
        _WITNESSES[8].japanese + "タイトル: " + json.dumps(label, ensure_ascii=False) + "。"
    )


@pytest.mark.parametrize("run", ["m10-design", "m10-heldout"])
def test_i4_every_verified_capture_carries_japanese(run: str) -> None:
    """I4 corpus sweep: every recorded source reaches the public verifier; every PASS has JA."""
    root = Path(__file__).resolve().parents[1]
    records = root / "corpus/python/captures" / run / "records.ndjson"
    verified: list[tuple[str, CoreCertificate]] = []
    for line in records.read_text().splitlines():
        record = json.loads(line)
        content = record["content"]
        if content is None:
            continue
        assert isinstance(content, str)
        dataset = record["dataset_name"]
        assert dataset in {"sales.csv", "weather.csv"}
        target = spec.DatasetTarget(
            "/mnt/uploads/" + dataset, (root / "data" / dataset).read_bytes()
        )
        _fenced, source = defence(content)
        result = verify_python_source(source, declared_target=target)
        if isinstance(result, Verified):
            verified.append((record["prompt_id"], result.certificate))
    assert verified, "corpus sweep needs at least one Verified control"
    for prompt_id, certificate in verified:
        assert _japanese(certificate).startswith("グラフの種類: "), prompt_id


def test_i4_japanese_maps_are_closed() -> None:
    """I4: mark/reduction vocabularies are literal exact maps; same-family near misses raise."""
    module = importlib.import_module("verifier.pysrc.certificate")
    marks = cast(dict[str, str], module._JA_MARK_WORDS)
    reductions = cast(dict[str, str], module._JA_REDUCTION_WORDS)
    assert marks == {
        "bar": "棒グラフ",
        "barh": "横棒グラフ",
        "line": "折れ線グラフ",
        "scatter": "散布図",
    }
    assert reductions == {"sum": "合計", "mean": "平均", "min": "最小値", "max": "最大値"}
    for key in ("hist", "bars", "Bar", "bar ", "plot"):
        with pytest.raises(KeyError):
            marks[key]
    for key in ("median", "count", "Mean", "mean "):
        with pytest.raises(KeyError):
            reductions[key]
