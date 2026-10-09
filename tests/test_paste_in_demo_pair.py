# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q37: production + demo ship separate generated pairs; the anchoring rule and the inlet templates
differ (Q40, M19.5 W3), the tool is shared.

User ruling (session 6): production (`paste-in/`) anchors strictly; the demo
(`webui/demo-paste-in/`) keeps Q8's substitution rule. Contract `.agent/archive/contracts/q37.md`;
M19.5 moves the rule onto the filter alone, since the tool no longer decides anything.
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
    load_bundle,
    recorded_request,
)
from verifier.figure import reader
from webui.paste_in import demo_filter, demo_tool, templates, tool
from webui.paste_in import filter as production_filter

# Hand-stated: path -> (root class name, anchoring rule of its filter or None for a tool).
_PAIRS = {
    "paste-in/figure_verification_tool.py": ("Tools", None),
    "paste-in/figure_verification_filter.py": ("Filter", "strict"),
    "webui/demo-paste-in/figure_verification_tool.py": ("Tools", None),
    "webui/demo-paste-in/figure_verification_filter.py": ("Filter", "substitution"),
}
_USER = "user-1"
_SALES = b"region,month,revenue,orders\nwest,2024-01,1,5\neast,2024-02,2,6\n"
# Draws `month`, which `Chart total revenue` never names: strict blocks, substitution passes.
_PROGRAM = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    'df = pd.read_csv("/mnt/uploads/sales.csv")\n'
    'g = df.groupby("month")["revenue"].sum()\n'
    "plt.bar(g.index, g.values)\n"
    "plt.show()\n"
)
_REQUEST = "Chart total revenue"
_STRICT_COVERS = (
    "if your request names a column, it names every drawn column; labels name only drawn columns"
)
_SUBSTITUTION_COVERS = (
    "no drawn column replaces a column your request names; labels name only drawn columns"
)


def test_q37_s3_each_root_class_states_its_rule_and_inherits_the_rest() -> None:
    assert production_filter.Filter._ANCHORING == "strict"
    assert production_filter.Filter._TEMPLATES is templates.PRODUCTION_TEMPLATES
    assert demo_filter.Filter._ANCHORING == "substitution"
    assert demo_filter.Filter._TEMPLATES is templates.DEMO_TEMPLATES
    for name in ("file", "no_file"):
        production = getattr(templates.PRODUCTION_TEMPLATES, name)
        demo = getattr(templates.DEMO_TEMPLATES, name)
        assert production.removesuffix(templates.TRANSPORT) + templates.FORMAT == demo
    # By name, not identity: filter suites reload the production module, re-creating its class.
    assert [base.__module__ for base in demo_tool.Tools.__bases__] == ["webui.paste_in.tool"]
    assert [base.__module__ for base in demo_filter.Filter.__bases__] == ["webui.paste_in.filter"]
    assert "_ANCHORING" not in vars(tool.Tools)
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
    discovered = getattr(module, name)
    if rule is None:
        assert not hasattr(discovered, "_ANCHORING")
    else:
        assert rule == discovered._ANCHORING


def _outlet(module: object, tmp_path: Path) -> list[dict[str, object]]:
    """Run one outlet over a host-reader browser; return its emitted events."""
    events: list[dict[str, object]] = []
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "sales.csv").write_bytes(_SALES)

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    async def browser(_payload: dict[str, object]) -> dict[str, object]:
        program = _PROGRAM.replace("/mnt/uploads/", f"{uploads}/")
        return {"stdout": reader.run(program), "stderr": None}

    stored = [StoredFile("file-0", _USER, "sales.csv", _SALES)]
    with fake_open_webui(stored, tmp_path):
        asyncio.run(
            module.Filter().outlet(  # type: ignore[attr-defined]
                filter_body("MODEL_REPLY_SENTINEL"),
                __request__=recorded_request(_PROGRAM, ("file-0",), _REQUEST),
                __user__={"id": _USER},
                __metadata__={"session_id": "session"},
                __event_call__=browser,
                __event_emitter__=emit,
            )
        )
    return events


@pytest.mark.parametrize(
    ("module", "statuses", "covers"),
    [
        (production_filter, ["column_not_named"], _STRICT_COVERS),
        (demo_filter, [], _SUBSTITUTION_COVERS),
    ],
    ids=["production", "demo"],
)
def test_q37_s3_the_outlet_threads_its_rule_to_verdict_and_check_list(
    module: object, statuses: list[str], covers: str, tmp_path: Path
) -> None:
    """One program, one request: strict blocks the unnamed drawn column, substitution passes;
    each check list states its own artifact's rule."""
    events = _outlet(module, tmp_path)
    reasons = [
        str(event["data"]["description"]).rsplit("(", 1)[1].rstrip(")")  # type: ignore[index]
        for event in events
        if event["type"] == "status"
    ]
    assert reasons == statuses
    (embed,) = [event for event in events if event["type"] == "embeds"]
    document = embed["data"]["embeds"][0]  # type: ignore[index]
    assert covers in document
    assert (_SUBSTITUTION_COVERS if covers == _STRICT_COVERS else _STRICT_COVERS) not in document
