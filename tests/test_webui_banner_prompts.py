# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""X5: the launcher's six banner arms, the stub's scripted programs and their verdicts (M19.5).

Each arm's program runs through the real reader and judge on the host, under the demo's
substitution anchoring, the way the outlet runs it in the browser: the CSV at the sandbox's
`/mnt/uploads/` path, the Japanese font when the program or the CSV holds non-ASCII text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from model_backend.models import ChatMessage
from paste_in_support import REPO_ROOT
from verifier.figure import reader
from verifier.figure.description import parse_description
from verifier.figure.judge import Passed, Sources, judge
from webui import banner, model_stub

_DATA = REPO_ROOT / "data"
_FONT = REPO_ROOT / "tests" / "fonts" / "NotoSansJP-subset.ttf"
# Hand-stated: arm -> (launcher variable, CSV, the stub arm's verdict).
_ARMS = {
    "simple": ("simple_prompt", "sales.csv", "pass"),
    "misleading": ("misleading_prompt", "sales.csv", "zero_not_in_limits"),
    "ja-simple": ("ja_simple_prompt", "sales.csv", "pass"),
    "ja-misleading": ("ja_misleading_prompt", "sales.csv", "zero_not_in_limits"),
    "ja-clinic-simple": ("ja_clinic_simple_prompt", "clinic_ja.csv", "pass"),
    "ja-clinic-misleading": ("ja_clinic_misleading_prompt", "clinic_ja.csv", "axis_inverted"),
}


def _arms() -> dict[str, banner.Arm]:
    return {arm.id: arm for arm in banner.load().arms}


def _reply(user: str, *, selector: bool = True) -> str:
    system = "Available Tools: draw_figure" if selector else "Ordinary discussion."
    return model_stub._scripted_reply(
        (ChatMessage(role="system", content=system), ChatMessage(role="user", content=user))
    )


def test_x5_the_banner_set_is_the_six_arms() -> None:
    arms = _arms()
    assert {key: (arm.dataset, arm.expect) for key, arm in arms.items()} == {
        key: (dataset, expect) for key, (_variable, dataset, expect) in _ARMS.items()
    }


def test_x5_launcher_assignments_equal_the_banner_prompts() -> None:
    launch = (REPO_ROOT / "webui/launch.sh").read_text(encoding="utf-8")
    assigned = dict(re.findall(r'^([a-z_]+_prompt)="([^"\n]*)"$', launch, re.MULTILINE))
    arms = _arms()
    assert assigned == {variable: arms[key].prompt for key, (variable, _, _) in _ARMS.items()}


@pytest.mark.parametrize("arm_id", list(_ARMS))
@pytest.mark.parametrize(
    "prefix",
    ["Query: ", 'History:\nUSER: """Earlier Query: decoy"""\nASSISTANT: """prior"""\nQuery: '],
    ids=["fresh", "history"],
)
def test_x5_the_stub_answers_each_rendered_arm_with_its_program(arm_id: str, prefix: str) -> None:
    arm = _arms()[arm_id]
    reply = json.loads(_reply(prefix + banner.rendered(arm)))
    assert reply == {
        "tool_calls": [{"name": "draw_figure", "parameters": {"program": arm.program}}]
    }


@pytest.mark.parametrize("arm_id", list(_ARMS))
@pytest.mark.parametrize("variation", ["bare", "rendered-with-suffix", "no-selector-system"])
def test_x5_near_misses_stay_prose(arm_id: str, variation: str) -> None:
    arm = _arms()[arm_id]
    if variation == "bare":
        reply = _reply("Query: " + arm.prompt)
    elif variation == "rendered-with-suffix":
        reply = _reply("Query: " + banner.rendered(arm) + " ")
    else:
        reply = _reply("Query: " + banner.rendered(arm), selector=False)
    assert reply == "Chart request completed."


@pytest.mark.parametrize("arm_id", list(_ARMS))
def test_x5_each_stub_program_reaches_its_verdict(arm_id: str) -> None:
    arm = _arms()[arm_id]
    content = (_DATA / arm.dataset).read_bytes()
    program = arm.program.replace("/mnt/uploads/", f"{_DATA}/")
    font = None if program.isascii() and content.isascii() else str(_FONT)
    described = parse_description(reader.run(program, font))
    assert described is not None
    verdict = judge(described, Sources(((arm.dataset, content),), arm.prompt, "substitution"))
    reached = "pass" if isinstance(verdict, Passed) else verdict.reason
    assert reached == _ARMS[arm_id][2]


def test_x5_a_blocked_arm_marks_the_distorting_call() -> None:
    """The site of the misleading arm's verdict is its `plt.ylim` line (ruling 13)."""
    arm = _arms()["misleading"]
    program = arm.program.replace("/mnt/uploads/", f"{_DATA}/")
    described = parse_description(reader.run(program))
    assert described is not None
    verdict = judge(described, Sources((("sales.csv", (_DATA / "sales.csv").read_bytes()),)))
    assert not isinstance(verdict, Passed)
    assert verdict.site is not None
    assert program.splitlines()[verdict.site - 1] == "plt.ylim(30000, 45000)"


def test_x5_rendering_uses_the_demo_file_template(tmp_path: Path) -> None:
    arm = _arms()["simple"]
    (tmp_path / "sales.csv").write_bytes(b"a,b\n1,2\n")
    text = banner.rendered(arm, tmp_path)
    assert text.startswith(arm.prompt + "\n\nUse the CSV file at /mnt/uploads/sales.csv.")
    assert "Its columns are a, b." in text
    assert text.endswith(
        "Return one complete Python program as bare source text, no Markdown fences.\n"
    )
