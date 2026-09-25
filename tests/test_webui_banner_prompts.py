# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""X5: the launcher's public prompts and stub match the measured sentinel rows."""

from __future__ import annotations

import csv
import io
import json
import re

import msgspec
import pytest

from capture.corpus import CORPUS_ROOT, DATA_ROOT, Prompt, PromptSet, render_capture_prompt
from capture.harness import defence
from capture.record import CAPTURES_ROOT, load_run
from model_backend.models import ChatMessage
from paste_in_support import REPO_ROOT
from test_python_capture_run import DESIGN_RUN
from verifier.pysrc import DatasetTarget, Refused, Verified, verify_python_source
from webui import model_stub


def _sentinels() -> dict[str, Prompt]:
    parsed = msgspec.json.decode((CORPUS_ROOT / "sentinels.json").read_bytes(), type=PromptSet)
    return {prompt.id: prompt for prompt in parsed.prompts}


def _rendered(prompt: Prompt) -> str:
    data_path = DATA_ROOT / prompt.dataset_name
    rows = csv.reader(io.StringIO(data_path.read_text(encoding="utf-8"), newline=""))
    header = next(rows)
    text = (
        (CORPUS_ROOT / "capture_prompt_v1.txt")
        .read_text(encoding="utf-8")
        .format(task=prompt.prompt, dataset=prompt.dataset_name, columns=", ".join(header))
    )
    assert text == render_capture_prompt(prompt)
    return text


def _captured_program(prompt_id: str) -> str:
    run = load_run(CAPTURES_ROOT / DESIGN_RUN)
    record = next(record for record in run.records if record.prompt_id == prompt_id)
    assert record.content is not None, prompt_id
    return defence(record.content)[1]


def _reply(user: str, *, selector: bool = True) -> str:
    system = "Available Tools: draw_figure" if selector else "Ordinary discussion."
    return model_stub._scripted_reply(
        (ChatMessage(role="system", content=system), ChatMessage(role="user", content=user))
    )


def test_x5_banner_prompts_equal_the_sentinels() -> None:
    """X5: each launcher shell assignment equals the public sentinel's exact task text."""
    launch_text = (REPO_ROOT / "webui/launch.sh").read_text(encoding="utf-8")
    entries = re.findall(
        r'^(simple_prompt|elaborate_prompt)="([^"\n]*)"$', launch_text, re.MULTILINE
    )
    assert len(entries) == 2
    sentinels = _sentinels()
    assert dict(entries) == {
        "simple_prompt": sentinels["sentinel-simple"].prompt,
        "elaborate_prompt": sentinels["sentinel-complicated"].prompt,
    }


@pytest.mark.parametrize("prompt_id", ["sentinel-simple", "sentinel-complicated"])
@pytest.mark.parametrize(
    "prefix",
    [
        "Query: ",
        'History:\nUSER: """Earlier Query: decoy"""\nASSISTANT: """prior"""\nQuery: ',
    ],
    ids=["fresh", "history"],
)
def test_x5_stub_answers_rendered_selector_with_the_captured_program(
    prompt_id: str, prefix: str
) -> None:
    """X5: a rendered selector gets exactly one call with the captured source and core verdict."""
    prompt = _sentinels()[prompt_id]
    source = _captured_program(prompt_id)
    target = DatasetTarget("/mnt/uploads/sales.csv", (DATA_ROOT / "sales.csv").read_bytes())
    verdict = verify_python_source(source, declared_target=target)
    if prompt_id == "sentinel-simple":
        assert isinstance(verdict, Verified)
    else:
        assert isinstance(verdict, Refused)
    reply = json.loads(_reply(prefix + _rendered(prompt)))
    assert reply == {"tool_calls": [{"name": "draw_figure", "parameters": {"program": source}}]}


@pytest.mark.parametrize("prompt_id", ["sentinel-simple", "sentinel-complicated"])
@pytest.mark.parametrize(
    "variation",
    ["unrendered", "rendered-with-suffix", "no-selector-system"],
)
def test_x5_stub_keeps_near_miss_turns_as_prose(prompt_id: str, variation: str) -> None:
    """X5: unrendered, suffixed and non-selector turns cannot receive a scripted tool call."""
    prompt = _sentinels()[prompt_id]
    rendered = _rendered(prompt)
    if variation == "unrendered":
        reply = _reply("Query: " + prompt.prompt)
    elif variation == "rendered-with-suffix":
        reply = _reply("Query: " + rendered + "\nextra")
    else:
        reply = _reply("Query: " + rendered, selector=False)
    assert reply
    try:
        decoded = json.loads(reply)
    except json.JSONDecodeError:
        return
    assert not isinstance(decoded, dict) or "tool_calls" not in decoded
