# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.0 exposure: python mode is the demo's ONE operation and JSON mode is unreachable.

Contract: `.agent/contracts/m10u0.md` predicate group E. Each docstring carries its predicate's
acceptance check; the check is the test's specification and the contract's wording wins wherever a
body would assert more.

Open WebUI filters the model-visible callable set by `function_name_filter_list` for a tool server
and by the workspace model's attached tool ids for a provisioned tool. Two independent surfaces can
each re-admit `proposeSpec`, so the predicate is stated over the ENUMERATED set rather than over
either surface's configuration.
"""

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from capture.corpus import banned_terms
from paste_in_support import (
    load_tool_module,
    owui_tool_descriptions,
    public_tool_operation,
)
from webui.bootstrap import SmokeResult, smoke
from webui.client import WebUIClient
from webui.settings import Settings


class _SmokeClient:
    def __init__(self, *, model_id: str, tool_id: str, tool_row_present: bool) -> None:
        self._model_id = model_id
        self._tool_id = tool_id
        self._tool_row_present = tool_row_present

    def wait_ready(self) -> None:
        pytest.fail("smoke must not wait")

    def authenticate(self) -> str:
        pytest.fail("smoke must not authenticate")

    def ensure_global_filter(
        self,
        *,
        function_id: str,
        name: str,
        content: str,
        description: str,
    ) -> None:
        del function_id, name, content, description
        pytest.fail("smoke must not provision the filter")

    def ensure_tool(
        self,
        *,
        tool_id: str,
        name: str,
        content: str,
        description: str,
    ) -> None:
        del tool_id, name, content, description
        pytest.fail("smoke must not provision the tool")

    def ensure_model_tool(self, *, model_id: str, tool_id: str) -> None:
        del model_id, tool_id
        pytest.fail("smoke must not mutate the model")

    def model_ids(self) -> list[str]:
        return [self._model_id]

    def tool_ids(self) -> list[str]:
        return [self._tool_id] if self._tool_row_present else []

    def tool_server_ids(self) -> list[str]:
        pytest.fail("smoke must not read the retired JSON tool server")

    def model_tool_ids(self, model_id: str) -> list[str]:
        assert model_id == self._model_id
        return [self._tool_id]


def _enabled_server_operations(connections_text: str) -> set[str]:
    decoded: object = json.loads(connections_text)
    assert isinstance(decoded, list)
    operations: set[str] = set()
    for connection in decoded:
        assert isinstance(connection, dict)
        config = connection.get("config")
        assert isinstance(config, dict)
        if not config.get("enable"):
            continue
        filtered = config.get("function_name_filter_list")
        assert isinstance(filtered, list)
        assert all(isinstance(name, str) for name in filtered)
        operations.update(cast(list[str], filtered))
    return operations


def test_e1_model_visible_callable_set_is_exactly_the_python_operation() -> None:
    """E1: the enumerated set equals `{<operation name>}` over settings + provisioned state.

    A re-added tool-server registration fails the test, so JSON mode cannot return by config drift.
    """
    operation_name, _operation = public_tool_operation(load_tool_module())
    assert operation_name != "proposeSpec"
    settings = Settings()
    connections_text = settings.launch_env().get("TOOL_SERVER_CONNECTIONS", "[]")
    server_operations = _enabled_server_operations(connections_text)
    visible = server_operations | {operation_name}
    assert visible == {operation_name}

    planted_connections = json.loads(connections_text)
    assert isinstance(planted_connections, list)
    planted_connections.append(
        {
            "config": {
                "enable": True,
                "function_name_filter_list": ["proposeSpec"],
            }
        }
    )
    planted = _enabled_server_operations(json.dumps(planted_connections)) | {operation_name}
    assert planted == {operation_name, "proposeSpec"}
    with pytest.raises(AssertionError):
        assert planted == {operation_name}


def test_e2_tool_provisioning_converges_to_the_artifact_bytes() -> None:
    """E2: two `ensure_tool` runs leave one row whose content equals the committed artifact.

    Idempotence is the predicate; the second run must update rather than duplicate.
    """
    tool_id = "figure_verification"
    tool_name = "Figure Verification"
    description = "Draw one chart from the uploaded data."
    tool_path = f"/api/v1/tools/id/{tool_id}"
    rows: dict[str, dict[str, object]] = {}
    writes: list[str] = []
    expected: dict[str, str] = {}

    def response_row(payload: dict[str, object]) -> dict[str, object]:
        return {
            **payload,
            "user_id": "admin-1",
            "specs": [],
            "access_grants": [],
            "updated_at": 1,
            "created_at": 1,
        }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "jwt"})
        assert request.headers["Authorization"] == "Bearer jwt"
        if request.method == "GET" and path == tool_path:
            if tool_id not in rows:
                return httpx.Response(404, json={"detail": "Not found"})
            return httpx.Response(200, json=rows[tool_id])
        if request.method == "POST" and path in {
            "/api/v1/tools/create",
            f"{tool_path}/update",
        }:
            payload: object = json.loads(request.content)
            assert isinstance(payload, dict)
            assert payload["id"] == tool_id
            assert payload["name"] == tool_name
            assert payload["content"] == expected["content"]
            assert payload["meta"] == {"description": description}
            phase = "create" if path.endswith("/create") else "update"
            if phase == "create":
                assert tool_id not in rows
            else:
                assert tool_id in rows
            writes.append(phase)
            rows[tool_id] = response_row(payload)
            return httpx.Response(200, json=rows[tool_id])
        pytest.fail(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://webui.test") as http:
        client = WebUIClient(http, Settings())
        client.authenticate()
        artifact = (
            Path(__file__).resolve().parent.parent / "paste-in" / "figure_verification_tool.py"
        )
        assert artifact.is_file()
        artifact_bytes = artifact.read_bytes()
        expected["content"] = artifact_bytes.decode("utf-8")
        kwargs = {
            "tool_id": tool_id,
            "name": tool_name,
            "content": expected["content"],
            "description": description,
        }
        client.ensure_tool(**kwargs)
        rows[tool_id]["content"] = expected["content"] + "# planted drift\n"
        client.ensure_tool(**kwargs)

    assert writes == ["create", "update"]
    assert set(rows) == {tool_id}
    content = rows[tool_id]["content"]
    assert isinstance(content, str)
    assert content.encode("utf-8") == artifact_bytes


def test_e3_tool_description_carries_no_admission_vocabulary(tmp_path: Path) -> None:
    """E3: `capture/corpus.py`'s banned-stem regex finds no match in the model-facing description.

    A planted stem fires it. Ruling 6 binds every model-facing string, not only corpus prompts.
    """
    descriptions = owui_tool_descriptions(tmp_path)
    assert len(descriptions) == 1
    description = descriptions[0]
    assert banned_terms(description) == []
    assert banned_terms(f"{description} Validate the source.") == ["Validate"]


def test_e4_bootstrap_smoke_reports_the_python_tool_attached() -> None:
    """E4: the readback flag is false with the tool row absent and true with it present.

    Smoke proves provisioning took, so a silent provisioning failure cannot read as a demo defect.
    """
    settings = Settings()

    def result(*, tool_row_present: bool) -> SmokeResult:
        return smoke(
            _SmokeClient(
                model_id=settings.model_id,
                tool_id=settings.tool_id,
                tool_row_present=tool_row_present,
            ),
            settings,
        )

    absent = result(tool_row_present=False)
    present = result(tool_row_present=True)
    assert not absent.tool_provisioned
    assert present.tool_provisioned
    # The model lists the tool id in BOTH readbacks, so a dangling attachment alone cannot make
    # smoke green: the workspace row has to exist too.
    assert absent.model_tool_attached
    assert present.model_tool_attached
    assert not absent.ok
    assert present.ok
