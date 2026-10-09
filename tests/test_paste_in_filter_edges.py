# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Outlet helper edges the contract suite reaches only through whole replies (M10.1 F4/F5, kept by
M19.5): the PNG line reader, the reply rewrite and the inlet's header refusals."""

import asyncio

import pytest

from paste_in_support import valid_png_uri
from verifier.figure.description import TAG
from verifier.pysrc.budget import WorkBudgetExceededError
from verifier.pysrc.errors import PysrcRefusalError
from webui.paste_in import filter as outlet
from webui.paste_in.owui_files import UploadedFile

_PNG = valid_png_uri()


def test_a_second_png_anywhere_in_stdout_withholds() -> None:
    assert outlet._png_uri(_PNG + "\nother output " + _PNG) is None


def test_unrelated_data_words_leave_one_png() -> None:
    assert outlet._png_uri("患者data: rendering started\n" + _PNG) == _PNG
    assert outlet._png_uri("metadata: rendering started\n" + _PNG) == _PNG


def test_a_png_inside_the_description_line_is_no_image() -> None:
    assert outlet._png_uri(TAG + '{"x": "' + _PNG + '"}') is None


def test_a_broken_png_is_no_image() -> None:
    assert outlet._png_uri("data:image/png;base64,AAAA") is None
    assert outlet._png_uri("data:image/png;base64,!!!!") is None


def test_rewrite_creates_the_reply_when_none_exists() -> None:
    body: dict[str, object] = {}
    outlet._rewrite(body, "text")
    assert body["messages"] == [
        {
            "role": "assistant",
            "content": "text",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "text"}],
                }
            ],
        }
    ]
    user_only: dict[str, object] = {"messages": [{"role": "user", "content": "q"}]}
    outlet._rewrite(user_only, "text")
    messages = user_only["messages"]
    assert isinstance(messages, list) and len(messages) == 2
    assert messages[0] == {"role": "user", "content": "q"}


@pytest.mark.parametrize(
    "fault",
    [
        PysrcRefusalError("csv_not_parsable"),
        WorkBudgetExceededError(limit=1, consumed=1, required=1),
    ],
)
def test_a_header_the_reader_refuses_renders_the_no_file_template(
    fault: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object) -> object:
        raise fault

    monkeypatch.setattr(outlet, "_read_csv", refuse)
    attachment = UploadedFile("f", "/mnt/uploads/a.csv", b"a\n1\n")
    rendered = outlet.Filter()._render("task", (attachment,))
    assert rendered == outlet.Filter._TEMPLATES.no_file.format(task="task")
    assert asyncio.iscoroutinefunction(outlet.Filter.inlet)
