# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q37: production + demo ship separate generated pairs that differ in the anchoring rule alone.

User ruling (session 6): production (`paste-in/`) anchors strictly; the demo
(`webui/demo-paste-in/`) keeps Q8's substitution rule. Contract `.agent/archive/contracts/q37.md`.
"""

import asyncio
from pathlib import Path

import pytest

from paste_in_support import (
    REPO_ROOT,
    StoredFile,
    artifact_import_environment,
    execute_artifact,
    fake_open_webui,
    filter_body,
    invoke_tool,
    load_bundle,
    recorded_request,
)
from verifier.pysrc import Refused, Verdict
from webui.paste_in import demo_filter, demo_tool, selection, tool
from webui.paste_in import filter as production_filter
from webui.paste_in.owui_files import UploadedFile

# Hand-stated: path -> (root class name, anchoring rule).
_PAIRS = {
    "paste-in/figure_verification_tool.py": ("Tools", "strict"),
    "paste-in/figure_verification_filter.py": ("Filter", "strict"),
    "webui/demo-paste-in/figure_verification_tool.py": ("Tools", "substitution"),
    "webui/demo-paste-in/figure_verification_filter.py": ("Filter", "substitution"),
}
_USER = "user-1"
_SALES = b"region,month,revenue,orders\nwest,2024-01,1,5\neast,2024-02,2,6\n"
# Draws `month`, which `Chart total revenue` never names: strict refuses, substitution passes.
_PROGRAM = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    'df = pd.read_csv("/mnt/uploads/sales.csv")\n'
    'g = df.groupby("month")["revenue"].sum()\n'
    "plt.bar(g.index, g.values)\n"
    "plt.show()\n"
)
_REQUEST = "Chart total revenue"


def test_q37_s3_each_root_class_states_its_rule_and_inherits_the_rest() -> None:
    assert tool.Tools._ANCHORING == "strict"
    assert production_filter.Filter._ANCHORING == "strict"
    assert demo_tool.Tools._ANCHORING == "substitution"
    assert demo_filter.Filter._ANCHORING == "substitution"
    # By name, not identity: filter suites reload the production module, re-creating its class.
    assert [base.__module__ for base in demo_tool.Tools.__bases__] == ["webui.paste_in.tool"]
    assert [base.__module__ for base in demo_filter.Filter.__bases__] == ["webui.paste_in.filter"]
    for demo in (demo_tool.Tools, demo_filter.Filter):
        assert [name for name, value in vars(demo).items() if callable(value)] == []


@pytest.mark.parametrize("relative", sorted(_PAIRS))
def test_q37_s3_each_generated_artifact_carries_its_rule(relative: str) -> None:
    """The pasted bytes, executed, expose the class OWUI discovers under the pair's rule."""
    bundle = load_bundle()
    path = REPO_ROOT / relative
    text = path.read_text(encoding="utf-8")
    with artifact_import_environment(bundle, text):
        module = execute_artifact(text, path, "artifact_under_test")
    name, rule = _PAIRS[relative]
    assert rule == getattr(module, name)._ANCHORING


@pytest.mark.parametrize(
    ("module", "expected"),
    [(tool, "No chart was produced."), (demo_tool, "The chart is ready.")],
    ids=["production", "demo"],
)
def test_q37_s3_the_tool_verifies_under_its_own_rule(
    module: object, expected: str, tmp_path: Path
) -> None:
    stored = [StoredFile("file-0", _USER, "sales.csv", _SALES)]
    metadata = {"files": [{"id": "file-0"}], "user_message": {"content": _REQUEST}}
    with fake_open_webui(stored, tmp_path):
        reply = invoke_tool(module, _PROGRAM, metadata=metadata, user={"id": _USER})  # type: ignore[arg-type]
    assert reply == expected


def test_q37_s3_selection_threads_the_rule_into_every_dataset_target() -> None:
    upload = UploadedFile("file", "/mnt/uploads/sales.csv", _SALES)
    strict, _ = selection.first_verdict(_PROGRAM, (upload,), _REQUEST, "strict", ())
    assert isinstance(strict, Refused)
    assert strict.code == "column_not_named"
    demo, _ = selection.first_verdict(_PROGRAM, (upload,), _REQUEST, "substitution", ())
    assert not isinstance(demo, Refused)


@pytest.mark.parametrize(
    ("module", "rule"),
    [(production_filter, "strict"), (demo_filter, "substitution")],
    ids=["prod", "demo"],
)
def test_q37_s3_the_outlet_threads_its_rule_to_verdict_and_check_list(
    module: object, rule: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spy at each seam: the verdict call and the check-list renderer receive the class's rule;
    the verdict call also receives the receipt's aliases (Q43)."""
    seen: list[tuple[str, object]] = []
    aliases = (("month", "period"),)

    def verdict(
        _program: str, _attachments: object, _text: object, anchoring: str, threaded: object
    ) -> object:
        seen.append(("verdict", anchoring))
        assert threaded == aliases
        refused: Verdict = Refused("target_mismatch")
        return refused, None

    def render(_reason: object, *, japanese: bool, anchoring: str) -> str:
        assert japanese is False
        seen.append(("render", anchoring))
        return "<p>checks</p>"

    events: list[dict[str, object]] = []

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    monkeypatch.setattr(production_filter, "first_verdict", verdict)
    monkeypatch.setattr(production_filter, "breakdown_html", render)
    with fake_open_webui([], Path(__file__).parent):
        asyncio.run(
            module.Filter().outlet(  # type: ignore[attr-defined]
                filter_body("MODEL_REPLY_SENTINEL"),
                __request__=recorded_request(_PROGRAM, request_text=_REQUEST, aliases=aliases),
                __user__={"id": _USER},
                __metadata__={"session_id": "session"},
                __event_call__=None,
                __event_emitter__=emit,
            )
        )
    assert seen == [("verdict", rule), ("render", rule)]
