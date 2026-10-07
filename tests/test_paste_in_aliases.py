# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q43 wrapper: the admin's column aliases reach the verdict through the tool Valve + receipt.

User ruling (session 7): contract `.agent/archive/contracts/q43.md` approved as drafted. V1: the
production tool's `Valves.column_aliases` (one line per column, `<column> = <alias>, <alias>`,
blank lines ignored); Open WebUI builds `Valves(**form)` on save, so a malformed line, an empty
alias or an alias repeated in one line fails the save; default empty; the demo tool inherits it.
V2: the tool records the parsed aliases in its receipt (`/2`), and the outlet's verdict reads them
from that receipt alone. `pydantic` is the version Open WebUI 0.10.2 pins.
"""

import asyncio
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from paste_in_support import (
    REPO_ROOT,
    StoredFile,
    artifact_import_environment,
    execute_artifact,
    fake_open_webui,
    filter_body,
    filter_request,
    invoke_filter,
    load_bundle,
    load_filter_module,
    recorded_request,
)
from webui.paste_in import demo_tool, tool
from webui.paste_in.aliases import parse_aliases
from webui.paste_in.receipt import RECEIPT_ATTR, Receipt, read_receipt, write_receipt

_USER = "user-1"
_WEATHER = b"date,city,temp_c,precip_mm\n2024-01-01,Sapporo,1.5,0.5\n2024-01-02,Naha,2.5,1.5\n"
_PROGRAM = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    'df = pd.read_csv("/mnt/uploads/weather.csv")\n'
    'g = df.groupby("city")["temp_c"].mean()\n'
    "plt.bar(g.index, g.values)\n"
    "plt.show()\n"
)
_REQUEST = "average temperature for each city"
_TEXT = "temp_c = temperature\nprecip_mm = rainfall"
_PARSED = (("temp_c", "temperature"), ("precip_mm", "rainfall"))


def test_q43_v1_the_valve_text_parses_one_line_per_column() -> None:
    full_width = "体温 ＝ 温度、熱，ねつ"  # noqa: RUF001 - the full-width separators themselves
    text = f"temp_c = temperature, 気温\n\n  \n{full_width}\nprecip_mm=rain fall\nratio = x=y\n"
    assert parse_aliases(text) == (
        ("temp_c", "temperature"),
        ("temp_c", "気温"),
        ("体温", "温度"),
        ("体温", "熱"),
        ("体温", "ねつ"),
        ("precip_mm", "rain fall"),
        ("ratio", "x=y"),
    )
    assert parse_aliases("") == ()
    assert parse_aliases("\n \n") == ()


@pytest.mark.parametrize(
    ("text", "fault"),
    [
        ("temp_c temperature", "line 1: write <column> = <alias>, <alias>"),
        ("temp_c = temperature\n\ncity", "line 3: write <column> = <alias>, <alias>"),
        (" = temperature", "line 1: the column name is empty"),
        ("temp_c =", "line 1: an alias is empty"),
        ("temp_c = temperature,", "line 1: an alias is empty"),
        ("temp_c = temperature, , heat", "line 1: an alias is empty"),
        ("temp_c = temperature, temperature", "line 1: an alias repeats"),
        ("temp_c = temperature\ntemp_c = heat", "line 2: temp_c already has a line"),
    ],
    ids=[
        "no-equals",
        "no-equals-line-3",
        "no-column",
        "no-alias",
        "trailing",
        "gap",
        "repeat",
        "twice",
    ],
)
def test_q43_v1_a_malformed_line_fails_the_save(text: str, fault: str) -> None:
    """OWUI's save runs `Valves(**form)`; the validator's error names the line."""
    with pytest.raises(ValueError, match=fault):
        parse_aliases(text)
    with pytest.raises(ValidationError, match=fault):
        tool.Tools.Valves(column_aliases=text)


def test_q43_v1_the_valve_survives_owuis_save_and_load_round_trip() -> None:
    """Save: `Valves(**form)` + `model_dump(exclude_unset=True)`; load: `Valves(**stored)`."""
    stored = tool.Tools.Valves(column_aliases=_TEXT).model_dump(exclude_unset=True)
    assert stored == {"column_aliases": _TEXT}
    assert parse_aliases(tool.Tools.Valves(**stored).column_aliases) == _PARSED


def test_q43_v1_the_default_valve_is_empty_and_the_demo_inherits_it() -> None:
    """OWUI sets `valves` only on an instance that already holds one (`utils/tools.py`)."""
    for tools in (tool.Tools(), demo_tool.Tools()):
        assert tools.valves.column_aliases == ""
        assert parse_aliases(tools.valves.column_aliases) == ()
    assert "Valves" not in vars(demo_tool.Tools)
    assert "__init__" not in vars(demo_tool.Tools)
    assert tool.Tools.Valves().model_dump() == {"column_aliases": ""}


def test_q43_v2_the_model_supplies_no_alias() -> None:
    """The one model-visible parameter stays `program`; reserved names never reach the model."""
    parameters = inspect.signature(tool.Tools.draw_figure).parameters
    assert list(parameters) == ["self", "program", "__metadata__", "__user__", "__request__"]


@pytest.mark.parametrize(
    "relative",
    ["paste-in/figure_verification_tool.py", "webui/demo-paste-in/figure_verification_tool.py"],
)
def test_q43_v1_each_generated_tool_carries_the_valve(relative: str) -> None:
    bundle = load_bundle()
    path = REPO_ROOT / relative
    text = path.read_text(encoding="utf-8")
    with artifact_import_environment(bundle, text):
        module = execute_artifact(text, path, "artifact_under_test")
        tools = module.Tools()
        assert tools.valves.column_aliases == ""
        with pytest.raises(ValidationError, match="an alias repeats"):
            module.Tools.Valves(column_aliases="temp_c = heat, heat")


def _draw(tools: tool.Tools, tmp_path: Path) -> tuple[str, Receipt | None]:
    request = filter_request()
    stored = [StoredFile("file-0", _USER, "weather.csv", _WEATHER)]
    metadata: dict[str, object] = {
        "files": [{"id": "file-0"}],
        "user_message": {"content": _REQUEST},
    }
    with fake_open_webui(stored, tmp_path):
        reply = asyncio.run(
            tools.draw_figure(
                _PROGRAM, __metadata__=metadata, __user__={"id": _USER}, __request__=request
            )
        )
    return reply, read_receipt(request)


def test_q43_v2_the_tool_verifies_and_records_its_valve_aliases(tmp_path: Path) -> None:
    """Strict: `temperature` names `temp_c` only through the admin's alias."""
    plain = tool.Tools()
    reply, receipt = _draw(plain, tmp_path)
    assert reply == "No chart was produced."
    assert receipt is not None and receipt.aliases == ()

    aliased = tool.Tools()
    aliased.valves = tool.Tools.Valves(column_aliases=_TEXT)
    reply, receipt = _draw(aliased, tmp_path)
    assert reply == "The chart is ready."
    assert receipt == Receipt(_PROGRAM, ("file-0",), _REQUEST, _PARSED)


def test_q43_v2_the_receipt_carries_aliases_as_builtin_tuples() -> None:
    request = filter_request()
    write_receipt(request, Receipt("source", ("one",), "text", _PARSED))
    raw = getattr(request.state, RECEIPT_ATTR)
    assert raw == ("figure-verification-receipt/2", "source", ("one",), "text", _PARSED)
    assert read_receipt(request) == Receipt("source", ("one",), "text", _PARSED)


def _outlet_reason(aliases: tuple[tuple[str, str], ...], tmp_path: Path) -> str:
    """The outlet's own verdict: `no_browser` = Verified (no RPC caller), else the refusal."""
    events: list[dict[str, object]] = []

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    stored = [StoredFile("file-0", _USER, "weather.csv", _WEATHER)]
    with fake_open_webui(stored, tmp_path):
        invoke_filter(
            load_filter_module(),
            filter_body("MODEL_REPLY_SENTINEL"),
            request=recorded_request(_PROGRAM, ("file-0",), _REQUEST, aliases),
            user={"id": _USER},
            metadata={"session_id": "session"},
            event_emitter=emit,
        )
    statuses = [event for event in events if event["type"] == "status"]
    assert len(statuses) == 1
    data = statuses[0]["data"]
    assert isinstance(data, dict)
    description = data["description"]
    assert isinstance(description, str)
    return description.rsplit("(", 1)[1].rstrip(")")


def test_q43_v2_the_outlet_verdict_reads_the_receipt_aliases(tmp_path: Path) -> None:
    assert _outlet_reason((), tmp_path) == "column_not_named"
    assert _outlet_reason(_PARSED, tmp_path) == "no_browser"
