# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""X1-X3: the paste-in inlet carries one authored capture prompt without changing user evidence."""

from __future__ import annotations

import asyncio
import copy
import csv
import inspect
import io
from collections.abc import Coroutine
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import msgspec
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from capture.corpus import CORPUS_ROOT, DATA_ROOT, PromptSet, render_capture_prompt
from paste_in_support import (
    REPO_ROOT,
    StoredFile,
    copy_tracked_tree,
    fake_open_webui,
    filter_request,
    load_filter_module,
    run_generator,
)

_OWNER = "owner-1"
_TEMPLATE = CORPUS_ROOT / "capture_prompt_v1.txt"
_CHARS = st.characters(codec="utf-8", blacklist_characters="\x00\r\n\ufeff")
_HEADER = st.lists(
    st.text(alphabet=_CHARS, min_size=1, max_size=8), min_size=1, max_size=5, unique=True
).map(tuple)
_NAME = st.text(
    alphabet=st.characters(codec="utf-8", blacklist_characters="/\\\x00\r\n"),
    min_size=1,
    max_size=12,
).map(lambda name: name + ".csv")
_TASK = st.one_of(
    st.text(alphabet=st.characters(codec="utf-8"), max_size=80),
    st.sampled_from(("{task}", "{dataset} {columns}\n次の図", "{{double}}\n{task}")),
)


def _csv_bytes(header: tuple[str, ...]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerow("1" for _ in header)
    return buffer.getvalue().encode("utf-8")


def _messages(task: object) -> tuple[dict[str, object], dict[str, object]]:
    last = {"id": "target", "role": "user", "content": task, "trace": "keep"}
    return {"messages": [{"role": "assistant", "content": "earlier"}, last]}, last


def _metadata(last: dict[str, object], *file_ids: str) -> dict[str, object]:
    return {
        "user_message": last,
        "files": [{"id": file_id, "name": "untrusted-name.csv"} for file_id in file_ids],
    }


def _inlet(body: dict[str, object], metadata: dict[str, object]) -> dict[str, object]:
    operation = (
        load_filter_module().Filter().inlet(body, __user__={"id": _OWNER}, __metadata__=metadata)
    )
    assert inspect.isawaitable(operation)
    result = asyncio.run(cast(Coroutine[Any, Any, object], operation))
    assert isinstance(result, dict)
    return cast(dict[str, object], result)


def _last(result: dict[str, object], *, offset: int = -1) -> dict[str, object]:
    messages = cast(list[dict[str, object]], result["messages"])
    return messages[offset]


@example(
    task="{task}\n日本語 {columns} {{literal}}",
    filename="売上 {dataset}.csv",
    header=("月", "売上"),
)
@given(task=_TASK, filename=_NAME, header=_HEADER)
@settings(max_examples=64, deadline=None)
def test_x1_generated_prompt_matches_independent_template(
    task: str, filename: str, header: tuple[str, ...]
) -> None:
    """X1: generated task, owned name and accepted CSV header render the template verbatim."""
    stored = StoredFile("owned", _OWNER, filename, _csv_bytes(header))
    body, last = _messages(task)
    metadata = _metadata(last, stored.file_id)
    expected = _TEMPLATE.read_text(encoding="utf-8").format(
        task=task, dataset=filename, columns=", ".join(header)
    )
    with (
        TemporaryDirectory(prefix="inlet-x1-") as directory,
        fake_open_webui((stored,), Path(directory)) as lookups,
    ):
        returned = _inlet(body, metadata)
    assert _last(returned)["content"] == expected
    assert _last(returned)["role"] == "user"
    assert _last(returned) is not last
    assert lookups == [("owned", _OWNER)]


def test_x1_simple_sentinel_renders_exactly_the_corpus_prompt(tmp_path: Path) -> None:
    """X1: the public simple task over the real CSV matches capture.corpus byte for byte."""
    sentinels = msgspec.json.decode((CORPUS_ROOT / "sentinels.json").read_bytes(), type=PromptSet)
    sentinel = next(prompt for prompt in sentinels.prompts if prompt.id == "sentinel-simple")
    stored = StoredFile("sales", _OWNER, "sales.csv", (DATA_ROOT / "sales.csv").read_bytes())
    body, last = _messages(sentinel.prompt)
    metadata = _metadata(last, "sales")
    with fake_open_webui((stored,), tmp_path):
        returned = _inlet(body, metadata)
    expected = _TEMPLATE.read_text(encoding="utf-8").format(
        task=sentinel.prompt,
        dataset="sales.csv",
        columns="month, region, revenue, orders",
    )
    assert _last(returned)["content"] == expected
    assert _last(returned)["content"] == render_capture_prompt(sentinel)


def test_x1_last_owned_file_and_last_user_message_win(tmp_path: Path) -> None:
    """X1: the last owned file wins even before a foreign file; trailing assistant is preserved."""
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "fresh request"},
        {"role": "assistant", "content": "pending"},
    ]
    body: dict[str, object] = {"messages": messages}
    stored = (
        StoredFile("first", _OWNER, "first.csv", b"wrong,old\n1,2\n"),
        StoredFile("last", _OWNER, "last.csv", b"new,value\n1,2\n"),
        StoredFile("foreign", "other-user", "foreign.csv", b"other,value\n1,2\n"),
    )
    original_last = messages[2]
    metadata = _metadata(original_last, "first", "last", "foreign")
    expected = _TEMPLATE.read_text(encoding="utf-8").format(
        task="fresh request", dataset="last.csv", columns="new, value"
    )
    with fake_open_webui(stored, tmp_path) as lookups:
        returned = _inlet(body, metadata)
    assert lookups == [("first", _OWNER), ("last", _OWNER), ("foreign", _OWNER)]
    observed = cast(list[dict[str, object]], returned["messages"])
    assert observed[0] == {"role": "user", "content": "old request"}
    assert observed[1] == {"role": "assistant", "content": "old reply"}
    assert observed[2] == {"role": "user", "content": expected}
    assert observed[2] is not original_last
    assert observed[3] == {"role": "assistant", "content": "pending"}


@pytest.mark.parametrize(
    ("files", "messages"),
    [
        ((), [{"role": "user", "content": "request"}]),
        (("foreign",), [{"role": "user", "content": "request"}]),
        (("duplicate",), [{"role": "user", "content": "request"}]),
        (("good",), [{"role": "user", "content": ["request"]}]),
        (("good",), [{"role": "assistant", "content": "response"}]),
    ],
    ids=["no-file", "no-owned-file", "refused-header", "non-text-task", "no-user-message"],
)
def test_x1_unrenderable_input_keeps_body_equal(
    tmp_path: Path,
    files: tuple[str, ...],
    messages: list[dict[str, object]],
) -> None:
    """X1: every unrenderable branch returns a body equal to the original."""
    stored = (
        StoredFile("foreign", "other-user", "other.csv", b"good,value\n1,2\n"),
        StoredFile("duplicate", _OWNER, "duplicate.csv", b"same,same\n1,2\n"),
        StoredFile("good", _OWNER, "good.csv", b"good,value\n1,2\n"),
    )
    body: dict[str, object] = {"messages": copy.deepcopy(messages)}
    before = copy.deepcopy(body)
    metadata: dict[str, object] = {"files": [{"id": file_id} for file_id in files]}
    if messages and messages[0]["role"] == "user":
        metadata["user_message"] = messages[0]
    with fake_open_webui(stored, tmp_path):
        returned = _inlet(body, metadata)
    assert returned == before


def test_x2_aliasing_keeps_request_metadata_and_prior_message_objects(tmp_path: Path) -> None:
    """X2: aliased user_message and files remain original; only a fresh message is rendered."""
    preceding = {"role": "user", "content": "earlier request"}
    assistant = {"role": "assistant", "content": "earlier response"}
    last: dict[str, object] = {"role": "user", "content": "y = sin(x), x in [0, 1]", "id": "source"}
    body: dict[str, object] = {"messages": [preceding, assistant, last]}
    metadata = _metadata(last, "sales")
    request = filter_request()
    metadata["request_state"] = request
    before_metadata = copy.deepcopy(metadata)
    before_body = copy.deepcopy(body)
    stored = StoredFile("sales", _OWNER, "sales.csv", (DATA_ROOT / "sales.csv").read_bytes())
    with fake_open_webui((stored,), tmp_path):
        returned = _inlet(body, metadata)
    observed = cast(list[dict[str, object]], returned["messages"])
    assert observed[:2] == cast(list[dict[str, object]], before_body["messages"])[:2]
    assert observed[-1] is not last
    assert last == {"role": "user", "content": "y = sin(x), x in [0, 1]", "id": "source"}
    assert metadata == before_metadata
    assert metadata["user_message"] is last
    assert vars(request.state) == {}


def test_x3_generator_detects_a_template_byte_change(tmp_path: Path) -> None:
    """X3: a clean generator check passes; a template-only one-byte drift names the filter."""
    clean = run_generator(REPO_ROOT, "--check")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    clone = copy_tracked_tree(tmp_path / "repo")
    template = clone / "corpus/python/capture_prompt_v1.txt"
    original = template.read_bytes()
    changed = b"!" + original[1:]
    assert changed != original and len(changed) == len(original)
    template.write_bytes(changed)
    drifted = run_generator(clone, "--check")
    assert drifted.returncode == 1, drifted.stdout + drifted.stderr
    assert "paste-in/figure_verification_filter.py" in drifted.stdout + drifted.stderr
