# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M17.2 I5-I6: the PASS reply language follows the metadata request.

Contract: `.agent/archive/contracts/m17u2.md`.
Public outlet + real certificate; only OWUI/RPC are faked.
"""

import logging
from pathlib import Path
from typing import Literal, cast

import pytest

from filter_checks_support import embed_event, normalized_events
from observe_support import stdout_for_verified
from oracle_filter import FileRow, ReceiptValue, RpcOutcome, Scenario, oracle_outlet
from paste_in_support import (
    StoredFile,
    assert_filter_text,
    fake_open_webui,
    filter_body,
    invoke_filter,
    load_filter_module,
    recorded_request,
    valid_png_uri,
)
from test_paste_in_filter_differential import _assert_agrees, _load_filter
from test_paste_in_filter_reasons import _assert_log, _files, _records, _status
from verifier.pysrc import DatasetTarget, Verified, verify_python_source
from verifier.pysrc.request import formula_target

_DATASET = (
    "import pandas as pd\nimport matplotlib.pyplot as plt\n"
    'frame = pd.read_csv("/mnt/uploads/chart.csv")\n'
    'plt.bar(frame["key"], frame["value"])\nplt.show()\n'
)
_FORMULA = (
    "import numpy as np\nimport matplotlib.pyplot as plt\n"
    "grid_points = np.linspace(0, 1, num=3)\n"
    "curve_values = np.sin(grid_points)\n"
    "plt.plot(grid_points, curve_values)\nplt.show()\n"
)
_REQUEST = "y = sin(x), x in [0, 1], n = 3"
_CONTENT = b"key,value\nwest,1.25\neast,2.5\n"
_ENGLISH = {
    "dataset": (
        'Chart type: bar. The data comes from the file "/mnt/uploads/chart.csv". '
        'X shows the column "key". Y shows the column "value". '
        "The chart draws 2 rows. Numbers follow the profile binary64-libm-v1."
    ),
    "formula": (
        "Chart type: line. The data comes from the submitted program. "
        "The formula, the x interval and the sample count match the request. "
        "Y computes sin(x). X runs from 0 to 1 in 3 samples. "
        "Numbers follow the profile binary64-libm-v1."
    ),
}
_JAPANESE = {
    "dataset": (
        'グラフの種類: 棒グラフ。データはファイル "/mnt/uploads/chart.csv" から読み込みます。'
        'X 軸は列 "key" を表します。Y 軸は列 "value" を表します。'
        "描画する行は 2 行です。数値はプロファイル binary64-libm-v1 に従います。"
    ),
    "formula": (
        "グラフの種類: 折れ線グラフ。データは送信されたプログラムから計算します。"
        "数式、x の区間、サンプル数は依頼と一致します。Y は sin(x) を計算します。"
        "X は 0 から 1 までの 3 点です。数値はプロファイル binary64-libm-v1 に従います。"
    ),
}
_LANGUAGE_CASES = (
    pytest.param({"user_message": {"content": "あ"}}, True, id="hiragana"),
    pytest.param({"user_message": {"content": "カ"}}, True, id="katakana"),
    pytest.param({"user_message": {"content": "ｶ"}}, True, id="halfwidth-katakana"),
    pytest.param({"user_message": {"content": "\U0001b001"}}, True, id="supplementary-kana"),
    pytest.param({"user_message": {"content": "Plot 漢字 あ"}}, True, id="mixed-kana"),
    pytest.param({"user_message": {"content": "漢字"}}, False, id="kanji-only"),
    pytest.param({"user_message": {"content": "English request"}}, False, id="ascii"),
    pytest.param({"user_message": {"content": ""}}, False, id="empty-content"),
    pytest.param({"user_message": {"content": "゙゚゛゜ゝゞ・ー･ｰﾞﾟ"}}, False, id="kana-nonletters"),
    pytest.param({}, False, id="missing-user-message"),
    pytest.param({"user_message": None}, False, id="null-user-message"),
    pytest.param({"user_message": "あ"}, False, id="string-user-message"),
    pytest.param({"user_message": [{"content": "あ"}]}, False, id="list-user-message"),
    pytest.param({"user_message": 1}, False, id="integer-user-message"),
    pytest.param({"user_message": {}}, False, id="missing-content"),
    pytest.param({"user_message": {"content": None}}, False, id="null-content"),
    pytest.param({"user_message": {"content": 1}}, False, id="integer-content"),
    pytest.param({"user_message": {"content": ["あ"]}}, False, id="list-content"),
    pytest.param({"user_message": {"content": {"text": "あ"}}}, False, id="dict-content"),
    pytest.param({"user_message": {"content": "あ".encode()}}, False, id="bytes-content"),
)


def _witness(arm: str) -> tuple[str, Verified, list[StoredFile], tuple[str, ...]]:
    if arm == "dataset":
        source = _DATASET
        target = DatasetTarget("/mnt/uploads/chart.csv", _CONTENT)
        verdict = verify_python_source(source, declared_target=target)
        stored = [StoredFile("upload", "owner", "chart.csv", _CONTENT)]
        files: tuple[str, ...] = ("upload",)
    else:
        source = _FORMULA
        formula = formula_target(_REQUEST)
        assert formula is not None
        verdict = verify_python_source(source, declared_target=formula)
        stored = []
        files = ()
    assert isinstance(verdict, Verified), verdict
    return source, verdict, stored, files


@pytest.mark.parametrize("arm", ["dataset", "formula"])
@pytest.mark.parametrize("language_fields,japanese", _LANGUAGE_CASES)
def test_i5_pass_reply_language_follows_the_request(
    arm: str,
    language_fields: dict[str, object],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    *,
    japanese: bool,
) -> None:
    """I5: both arms x kana/non-kana/malformed language fields, with a valid browser session."""
    caplog.set_level(logging.INFO, logger="webui.paste_in.filter")
    source, verified, stored, files = _witness(arm)
    metadata = {"session_id": "session", **language_fields}
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        return {"stdout": stdout_for_verified(verified, valid_png_uri()), "stderr": None}

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    body = filter_body("MODEL_REPLY_KANA_あ_IS_NOT_THE_LANGUAGE_CARRIER")
    # Opposite-language receipt text proves that metadata alone selects the rendering.
    request_text = _REQUEST + ("" if japanese else " あ")
    with fake_open_webui(stored, tmp_path):
        result = invoke_filter(
            load_filter_module(),
            body,
            request=recorded_request(source, files, request_text),
            user={"id": "owner"},
            metadata=metadata,
            event_call=rpc,
            event_emitter=emit,
        )
    assert result is body
    interpretation = _JAPANESE[arm] if japanese else _ENGLISH[arm]
    assert_filter_text(result, "Figure verification passed\n\n" + interpretation)
    assert len(calls) == 1
    assert normalized_events(events) == [_files(), embed_event(None, metadata)]
    assert _records(caplog) == []


@pytest.mark.parametrize("arm", ["dataset", "formula"])
@pytest.mark.parametrize(
    "metadata",
    [None, [], "あ", 1, {}, {"user_message": {"content": "あ"}}],
    ids=["null", "list", "string", "integer", "empty-dict", "kana-without-session"],
)
def test_i5_non_dict_or_sessionless_metadata_still_fails_no_browser(
    arm: str, metadata: object, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """I5: malformed browser context stays FAIL; language fallback never manufactures a PASS."""
    caplog.set_level(logging.INFO, logger="webui.paste_in.filter")
    source, _verified, stored, files = _witness(arm)
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        message = "no_browser must precede RPC"
        raise AssertionError(message)

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui(stored, tmp_path):
        result = invoke_filter(
            load_filter_module(),
            filter_body("MODEL_TEXT"),
            request=recorded_request(source, files, _REQUEST),
            user={"id": "owner"},
            metadata=cast(dict[str, object] | None, metadata),
            event_call=rpc,
            event_emitter=emit,
        )
    assert_filter_text(result, "Figure verification failed, no image produced")
    assert calls == []
    language: Literal[0, 1] = 1 if isinstance(metadata, dict) and "user_message" in metadata else 0
    assert normalized_events(events) == [
        _status("no_browser", language),
        embed_event("no_browser", metadata),
    ]
    _assert_log(caplog, "no_browser")


@pytest.mark.parametrize("arm", ["dataset", "formula"])
@pytest.mark.parametrize("language_fields,japanese", _LANGUAGE_CASES)
def test_i6_differential_expects_the_language_from_its_own_rule(
    arm: str,
    language_fields: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    *,
    japanese: bool,
) -> None:
    """I6: independent language oracle; both persisted surfaces equal the hand-stated rendering."""
    source, verified, stored, files = _witness(arm)
    scenario = Scenario(
        ReceiptValue(source, files, _REQUEST + ("" if japanese else " あ")),
        "owner",
        tuple(FileRow(row.file_id, row.user_id, row.filename, row.content) for row in stored),
        {"role": "assistant", "content": "MODEL_KANA_あ_NEVER_SELECTS_LANGUAGE"},
        {"session_id": "session", **language_fields},
        RpcOutcome(
            "returns", {"stdout": stdout_for_verified(verified, valid_png_uri()), "stderr": None}
        ),
    )
    module = _load_filter()

    def language_bomb(_metadata: object) -> bool:
        pytest.fail("oracle used the production language predicate")

    with monkeypatch.context() as scoped:
        scoped.setattr(module, "_japanese", language_bomb)
        expected = oracle_outlet(scenario)
    text = "Figure verification passed\n\n" + (_JAPANESE[arm] if japanese else _ENGLISH[arm])
    assert expected.content == text
    assert expected.output == (
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text}],
        },
    )
    assert expected.rpc.font is None, "request language alone must not trigger a font payload"
    _assert_agrees(scenario, module, monkeypatch)
