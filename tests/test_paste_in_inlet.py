# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.5 O7: last text user + last owned header; no-file guidance; immutable evidence."""

from __future__ import annotations

import asyncio
import copy
import csv
import io
from collections.abc import Coroutine
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from outlet_support import USER, load
from paste_in_support import StoredFile, fake_open_webui

_FILE = "FILE /mnt/uploads/{dataset}\nCOLUMNS {columns}\nTASK {task}"
_NO_FILE = "NO FILE\nTASK {task}"


def _inlet(
    body: dict[str, object], metadata: dict[str, object], *, demo: bool = False
) -> dict[str, object]:
    module = load("demo_filter" if demo else "filter")
    instance = module.Filter()
    instance._TEMPLATES = load("templates").Templates(_FILE, _NO_FILE)
    return cast(
        dict[str, object],
        asyncio.run(
            cast(
                Coroutine[Any, Any, object],
                instance.inlet(body, __user__=USER, __metadata__=metadata),
            )
        ),
    )


def _last(body: dict[str, object]) -> dict[str, object]:
    return next(
        message
        for message in reversed(cast(list[dict[str, object]], body["messages"]))
        if message.get("role") == "user"
    )


def _csv(header: tuple[str, ...]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerow("1" for _ in header)
    return buffer.getvalue().encode("utf-8")


@example(task="{task}\n日本語 {columns}", filename="表 {dataset}.csv", header=("月", "売上"))
@given(
    task=st.text(alphabet=st.characters(codec="utf-8"), max_size=100),
    filename=st.text(alphabet="abcé年 {}", min_size=1, max_size=20).map(lambda s: s + ".csv"),
    header=st.lists(
        st.text(alphabet="abcé年 {}", min_size=1, max_size=10).filter(lambda s: bool(s.strip())),
        min_size=1,
        max_size=5,
        unique=True,
    ).map(tuple),
)
@settings(max_examples=45, deadline=None)
def test_o7_template_parameters_preserve_generated_task_filename_and_header(
    task: str, filename: str, header: tuple[str, ...]
) -> None:
    message: dict[str, object] = {"role": "user", "content": task, "id": "fresh"}
    body: dict[str, object] = {"messages": [message]}
    metadata: dict[str, object] = {"files": [{"id": "owned"}], "user_message": message}
    original = copy.deepcopy(metadata)
    stored = StoredFile("owned", "outlet-owner", filename, _csv(header))
    with (
        TemporaryDirectory(prefix="m19-inlet-") as directory,
        fake_open_webui((stored,), Path(directory)) as lookups,
    ):
        result = _inlet(body, metadata)
    assert _last(result)["content"] == _FILE.format(
        dataset=filename, columns=", ".join(header), task=task
    )
    assert lookups == [("owned", "outlet-owner")]
    assert result is not body and _last(result) is not message
    assert message["content"] == task
    assert metadata == original and metadata["user_message"] is message


@pytest.mark.parametrize("demo", [False, True])
def test_o7_last_owned_file_and_last_user_win_without_mutation(
    tmp_path: Path, *, demo: bool
) -> None:
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": "older reply"},
        {"role": "user", "content": "fresh", "other": 1},
        {"role": "assistant", "content": "pending"},
    ]
    body: dict[str, object] = {"messages": messages, "other": [1]}
    metadata: dict[str, object] = {
        "user_message": messages[2],
        "files": [{"id": name} for name in ("first", "last", "foreign", "missing")],
    }
    snapshot = copy.deepcopy((body, metadata))
    stored = (
        StoredFile("first", "outlet-owner", "first.csv", b"old,value\n1,2\n"),
        StoredFile("last", "outlet-owner", "last.csv", b"new,amount\n1,2\n"),
        StoredFile("foreign", "other", "other.csv", b"wrong,data\n1,2\n"),
    )
    with fake_open_webui(stored, tmp_path) as lookups:
        result = _inlet(body, metadata, demo=demo)
    assert (body, metadata) == snapshot
    assert result is not body
    result_messages = cast(list[dict[str, object]], result["messages"])
    assert result_messages[0] is messages[0] and result_messages[1] is messages[1]
    assert result_messages[3] is messages[3]
    assert result_messages[2] == {
        "role": "user",
        "content": "FILE /mnt/uploads/last.csv\nCOLUMNS new, amount\nTASK fresh",
        "other": 1,
    }
    assert result_messages[2] is not messages[2]
    assert lookups == [(name, "outlet-owner") for name in ("first", "last", "foreign", "missing")]


@pytest.mark.parametrize("ids", [(), ("foreign",), ("bad",), ("good", "bad")])
def test_o7_missing_owned_or_refused_last_header_uses_no_file_template(
    tmp_path: Path, ids: tuple[str, ...]
) -> None:
    message: dict[str, object] = {"role": "user", "content": "request"}
    body: dict[str, object] = {"messages": [message]}
    metadata: dict[str, object] = {"user_message": message, "files": [{"id": name} for name in ids]}
    stored = (
        StoredFile("good", "outlet-owner", "good.csv", b"key,value\n1,2\n"),
        StoredFile("bad", "outlet-owner", "bad.csv", b"same,same\n1,2\n"),
        StoredFile("foreign", "other", "other.csv", b"key,value\n1,2\n"),
    )
    with fake_open_webui(stored, tmp_path):
        result = _inlet(body, metadata)
    assert result is not body and _last(result) is not message
    assert _last(result)["content"] == "NO FILE\nTASK request"
    assert message["content"] == "request"


@pytest.mark.parametrize("content", [None, 42, [], [{"type": "text", "text": "request"}], {}])
def test_o7_non_text_last_user_stays_unchanged(content: object) -> None:
    body: dict[str, object] = {
        "messages": [
            {"role": "user", "content": "earlier text"},
            {"role": "user", "content": content},
        ]
    }
    before = copy.deepcopy(body)
    assert _inlet(body, {}) == before
    assert body == before


def test_o7_no_user_message_stays_unchanged() -> None:
    body: dict[str, object] = {"messages": [{"role": "assistant", "content": "pending"}]}
    assert _inlet(body, {}) == body


def test_o7_production_and_demo_templates_share_rules_but_not_bare_source_format() -> None:
    templates = load("templates")
    production = templates.PRODUCTION_TEMPLATES
    demo = templates.DEMO_TEMPLATES
    assert templates.RULES and templates.FORMAT
    assert load("filter").Filter._TEMPLATES is production
    assert load("demo_filter").Filter._TEMPLATES is demo
    for name in ("file", "no_file"):
        plain = getattr(production, name)
        formatted = getattr(demo, name)
        assert "{task}" in plain and templates.RULES in plain
        assert templates.FORMAT not in plain and templates.TRANSPORT not in formatted
        assert plain.endswith(templates.TRANSPORT) and formatted.endswith(templates.FORMAT)
        assert formatted.removesuffix(templates.FORMAT) == plain.removesuffix(templates.TRANSPORT)
    assert "{dataset}" in production.file and "{columns}" in production.file
    assert "bare source" in templates.FORMAT and "Markdown fences" in templates.FORMAT
    assert "draw_figure" in templates.TRANSPORT and "program argument" in templates.TRANSPORT
