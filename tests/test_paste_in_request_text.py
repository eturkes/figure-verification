# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q66: the request = every user message on the chat branch, as Open WebUI stored it.

Contract `.agent/archive/contracts/q66.md` (R1-R6). The store is `paste_in_support.fake_chats`,
strict to the 0.12.3 API; the effect cases run the real reader + judge over `data/sales.csv`.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine, Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from outlet_support import load
from paste_in_support import StoredChat, fake_chats, filter_request
from verifier.figure import reader
from verifier.figure.description import parse_description
from verifier.figure.judge import Passed, Sources, judge
from verifier.figure.reasons import Blocked

_SALES = Path(__file__).resolve().parents[1] / "data" / "sales.csv"
_OWNER = "user-1"
_CHAT = "chat-1"

# root u1 → a1 → u2 → a2 → u3, plus an edited sibling of u2 (u2b) on another branch.
_BRANCHES: dict[str, dict[str, object]] = {
    "u1": {"role": "user", "content": "Chart the total revenue of each region using bars."},
    "a1": {
        "role": "assistant",
        "parentId": "u1",
        "content": "Figure verification passed\n\nBars `orders` by `month`",
    },
    "u2": {"role": "user", "parentId": "a1", "content": [{"type": "text", "text": "month"}]},
    "u2b": {"role": "user", "parentId": "a1", "content": "Show the orders per month instead."},
    "a2": {"role": "assistant", "parentId": "u2", "content": "Figure verification passed"},
    "u3": {"role": "user", "parentId": "a2", "content": "Use orders instead of revenue."},
}
_THREAD = "Chart the total revenue of each region using bars.\n\nUse orders instead of revenue."
_LATEST = "Use orders instead of revenue."


def _metadata(message_id: object = "u3", chat_id: object = _CHAT) -> dict[str, object]:
    return {
        "chat_id": chat_id,
        "user_message_id": message_id,
        "user_message": {"id": message_id, "role": "user", "content": _LATEST},
    }


def _read(metadata: Mapping[str, object] | None, user_id: object = _OWNER) -> str | None:
    function = load("owui_files").request_text
    return asyncio.run(cast(Coroutine[Any, Any, str | None], function(metadata, user_id)))


@pytest.fixture
def store() -> Iterator[Any]:
    with fake_chats({_CHAT: StoredChat(_OWNER, _BRANCHES)}) as reads:
        yield reads


def test_q66_r1_r4_the_branch_user_texts_join_oldest_first(store: Any) -> None:
    """R1 + R4: u1 and u3 alone; a1/a2 (assistant, naming `orders` + `month`), u2 (block-list
    content) and the sibling branch u2b never enter."""
    assert _read(_metadata()) == _THREAD
    assert store.owner_checks == [(_CHAT, _OWNER)]
    assert store.map_reads == [_CHAT]


def test_q66_r1_a_first_message_is_its_own_thread(store: Any) -> None:
    metadata = {**_metadata("u1"), "user_message": {"content": _BRANCHES["u1"]["content"]}}
    assert _read(metadata) == _BRANCHES["u1"]["content"]
    assert store.map_reads == [_CHAT]


@pytest.mark.parametrize(
    ("metadata", "user_id"),
    [
        (_metadata(), None),
        (_metadata(), ""),
        (_metadata(), 7),
        (_metadata(chat_id=None), _OWNER),
        (_metadata(chat_id=""), _OWNER),
        (_metadata(message_id=None), _OWNER),
        (_metadata(message_id=""), _OWNER),
    ],
    ids=[
        "no-user",
        "empty-user",
        "int-user",
        "no-chat",
        "empty-chat",
        "no-message",
        "empty-message",
    ],
)
def test_q66_r2_missing_keys_read_the_latest_message_without_a_lookup(
    store: Any, metadata: dict[str, object], user_id: object
) -> None:
    assert _read(metadata, user_id) == _LATEST
    assert store.owner_checks == []
    assert store.map_reads == []


@pytest.mark.parametrize(
    "chat_id", ["local:temporary", "channel:team", "chat-2"], ids=["temporary", "channel", "other"]
)
def test_q66_r2_r3_a_chat_the_user_does_not_own_is_never_read(store: Any, chat_id: str) -> None:
    """R3: `chat-2` exists under another owner (Open WebUI lets an admin continue it)."""
    with fake_chats({"chat-2": StoredChat("user-2", _BRANCHES)}) as other:
        assert _read(_metadata(chat_id=chat_id)) == _LATEST
        assert other.owner_checks == [(chat_id, _OWNER)]
        assert other.map_reads == []
    assert store.map_reads == []
    assert _read(_metadata()) == _THREAD  # the outer store again, after the nested one


@pytest.mark.parametrize(
    ("messages", "message_id", "latest"),
    [
        ({}, "u3", _LATEST),
        (_BRANCHES, "u9", _LATEST),
        (_BRANCHES, "a2", _LATEST),
        (_BRANCHES, "a2", "Figure verification passed"),
        ({**_BRANCHES, "u3": {**_BRANCHES["u3"], "content": "edited elsewhere"}}, "u3", _LATEST),
    ],
    ids=["no-rows", "unknown-message", "ends-in-assistant", "assistant-same-text", "other-text"],
)
def test_q66_r2_a_branch_not_ending_in_the_current_message_reads_it_alone(
    messages: dict[str, dict[str, object]], message_id: str, latest: str
) -> None:
    metadata = {**_metadata(message_id), "user_message": {"content": latest}}
    with fake_chats({_CHAT: StoredChat(_OWNER, messages)}) as reads:
        assert _read(metadata) == latest
        assert reads.map_reads == [_CHAT]


@pytest.mark.usefixtures("store")
def test_q66_r2_a_latest_message_without_text_reads_none() -> None:
    metadata = {**_metadata(), "user_message": {"content": [{"type": "text", "text": "x"}]}}
    assert _read(metadata) is None
    assert _read(None) is None


@pytest.mark.parametrize("content", [None, "absent"], ids=["null", "absent"])
def test_q66_r2_no_text_reads_none_even_over_a_textless_stored_tail(content: object) -> None:
    """A stored current row with null or no content never admits the earlier messages."""
    tail: dict[str, object] = {"role": "user", "parentId": "a2"}
    if content is None:
        tail["content"] = None
    metadata = {**_metadata(), "user_message": {"id": "u3"}}
    with fake_chats({_CHAT: StoredChat(_OWNER, {**_BRANCHES, "u3": tail})}) as reads:
        assert _read(metadata) is None
        assert reads.owner_checks == []


class _StoreError(Exception):
    pass


@pytest.mark.usefixtures("store")
@pytest.mark.parametrize("seam", ["is_chat_owner", "get_messages_map_by_chat_id"])
def test_q66_r2_a_raising_store_reads_the_latest_message(seam: str) -> None:
    async def fail(*_args: object, **_kwargs: object) -> object:
        raise _StoreError

    chats = sys.modules["open_webui.models.chats"].__dict__["Chats"]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(chats, seam, fail)
        assert _read(_metadata()) == _LATEST


@pytest.mark.usefixtures("store")
@pytest.mark.parametrize("row", ["a row", None, 3], ids=["text", "none", "number"])
def test_q66_r2_a_malformed_row_reads_the_latest_message(row: object) -> None:
    misc = sys.modules["open_webui.utils.misc"]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(misc, "get_message_list", lambda _map, _id: [_BRANCHES["u1"], row])
        assert _read(_metadata()) == _LATEST


def test_q66_r2_open_webui_absent_reads_the_latest_message() -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "open_webui", None)
        patch.setitem(sys.modules, "open_webui.models.chats", None)
        assert _read(_metadata()) == _LATEST


@pytest.mark.usefixtures("store")
@pytest.mark.parametrize("seam", ["is_chat_owner", "get_messages_map_by_chat_id"])
def test_q66_r2_cancellation_propagates(seam: str) -> None:
    async def cancel(*_args: object, **_kwargs: object) -> object:
        raise asyncio.CancelledError

    chats = sys.modules["open_webui.models.chats"].__dict__["Chats"]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(chats, seam, cancel)
        with pytest.raises(asyncio.CancelledError):
            _read(_metadata())


@pytest.mark.usefixtures("store")
@pytest.mark.parametrize("demo", [False, True], ids=["production", "demo"])
@pytest.mark.parametrize(
    ("user", "expected"),
    [({"id": _OWNER}, _THREAD), ({"id": "user-2"}, _LATEST), (None, _LATEST)],
    ids=["owner", "other-user", "no-user"],
)
def test_q66_r5_the_receipt_carries_the_thread_under_the_requesting_user(
    user: dict[str, object] | None, expected: str, *, demo: bool
) -> None:
    module = load("demo_tool" if demo else "tool")
    request = filter_request()
    result = asyncio.run(
        cast(
            Coroutine[Any, Any, object],
            module.Tools().draw_figure(
                "program", __metadata__=_metadata(), __request__=request, __user__=user
            ),
        )
    )
    receipt = load("receipt").read_receipt(request)
    assert receipt == load("receipt").Receipt("program", (), expected, ())
    assert result == load("verdicts").CHART_SENT


_ORDERS_BY_REGION = f"""
import pandas as pd
import matplotlib.pyplot as plt
df = pd.read_csv({str(_SALES)!r})
totals = df.groupby('region')['orders'].sum()
plt.bar(totals.index, totals.values, color='red')
plt.title('Orders by region')
plt.show()
"""
_TYPED_BARS = """
import matplotlib.pyplot as plt
plt.bar(['A', 'B', 'C'], [3, 5, 9], color='red')
plt.show()
"""


def _verdict(program: str, request: str | None, files: tuple[tuple[str, bytes], ...]) -> object:
    described = parse_description(reader.run(program))
    assert described is not None
    return judge(described, Sources(files, request, "strict"))


@pytest.mark.usefixtures("store")
def test_q66_r6_a_follow_up_keeps_the_columns_an_earlier_message_named() -> None:
    """R6: strict anchoring over the thread passes the region x orders follow-up; the latest
    message alone names `orders` but not `region`."""
    files = (("sales.csv", _SALES.read_bytes()),)
    assert isinstance(_verdict(_ORDERS_BY_REGION, _read(_metadata()), files), Passed)
    latest = _verdict(_ORDERS_BY_REGION, _LATEST, files)
    assert isinstance(latest, Blocked)
    assert latest.reason == "column_not_named"


def test_q66_r6_a_follow_up_keeps_the_numbers_an_earlier_message_typed() -> None:
    """R6: typed values stay a data source on `make the bars red`; alone, it has none."""
    branch: dict[str, Mapping[str, object]] = {
        "t1": {"role": "user", "content": "Draw bars for A 3, B 5, C 9."},
        "t2": {"role": "assistant", "parentId": "t1", "content": "Figure verification passed"},
        "t3": {"role": "user", "parentId": "t2", "content": "Make the bars red."},
    }
    metadata = {
        "chat_id": _CHAT,
        "user_message_id": "t3",
        "user_message": {"content": "Make the bars red."},
    }
    with fake_chats({_CHAT: StoredChat(_OWNER, branch)}):
        thread = _read(metadata)
    assert thread == "Draw bars for A 3, B 5, C 9.\n\nMake the bars red."
    typed = _verdict(_TYPED_BARS, thread, ())
    alone = _verdict(_TYPED_BARS, "Make the bars red.", ())
    assert isinstance(typed, Passed)
    assert isinstance(alone, Passed)
    assert "typed in the request" in typed.interpretation
    assert "No data was attached or typed" in alone.interpretation
