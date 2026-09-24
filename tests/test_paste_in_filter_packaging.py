# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.1 F8-F9: two paste targets, fail-closed bootstrap, and deterministic demo pins.

Contract: `.agent/contracts/m10u1.md` + A2 (function_states readback). The old heuristic filter
is retired; a byte-drifted or second active global filter cannot satisfy smoke.
"""

import importlib
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from model_backend.models import ChatMessage
from paste_in_support import (
    REPO_ROOT,
    assert_embedded_identity,
    assert_exact_closure,
    copy_tracked_tree,
    load_bundle,
    offending_import_roots,
    run_generator,
)
from verifier.pysrc import DatasetTarget, Verified, verify_python_source
from webui import bootstrap, model_stub
from webui.client import WebUIClient
from webui.settings import Settings

_TOOL_ARTIFACT = "paste-in/figure_verification_tool.py"
_FILTER_ARTIFACT = "paste-in/figure_verification_filter.py"
_EXPECTED_ARTIFACTS = {
    _TOOL_ARTIFACT: "webui.paste_in.tool",
    _FILTER_ARTIFACT: "webui.paste_in.filter",
}


def _filter_source() -> str:
    return (REPO_ROOT / _FILTER_ARTIFACT).read_text(encoding="utf-8")


def test_f8_bundle_declares_exactly_two_generated_paste_targets() -> None:
    """F8: one tool and one outlet filter, each with its own root and no third paste target."""
    bundle = load_bundle()
    assert bundle.ARTIFACTS == _EXPECTED_ARTIFACTS
    for relative, root in _EXPECTED_ARTIFACTS.items():
        artifact = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert artifact == bundle.render(root)
    check = run_generator(REPO_ROOT, "--check")
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.parametrize("relative", [_TOOL_ARTIFACT, _FILTER_ARTIFACT])
def test_f8_check_names_either_paste_target_when_its_committed_bytes_drift(
    relative: str, tmp_path: Path
) -> None:
    """F8: generator --check fails on a one-byte drift in either generated artifact."""
    clone = copy_tracked_tree(tmp_path / "repo")
    victim = clone / relative
    assert victim.is_file()
    victim.write_bytes(victim.read_bytes() + b" ")
    checked = run_generator(clone, "--check")
    assert checked.returncode == 1
    assert relative in checked.stdout + checked.stderr


def test_f8_filter_artifact_has_exact_import_closure_and_only_allowed_roots() -> None:
    """F8/B6: the second artifact embeds every first-party dependency, with no external root."""
    bundle = load_bundle()
    text = _filter_source()
    sources = bundle.embedded_sources(text)
    assert_exact_closure("webui.paste_in.filter", sources)
    assert_embedded_identity(sources)
    assert offending_import_roots(bundle, text) == set()
    assert "webui.paste_in.receipt" in sources
    assert "webui.paste_in.selection" in sources
    assert "verifier.pysrc.verify" in sources


def test_f8_legacy_filter_and_its_behavioral_tests_are_gone() -> None:
    """F8/A2: no previous heuristic implementation or test import survives the handoff."""
    assert not (REPO_ROOT / "webui" / "enforcement_filter.py").exists()
    assert not (REPO_ROOT / "tests" / "test_webui_enforcement_filter.py").exists()
    legacy_import = "webui.enforcement_" + "filter"
    tracked_tests = (REPO_ROOT / "tests").glob("test_*.py")
    users = [
        path.name for path in tracked_tests if legacy_import in path.read_text(encoding="utf-8")
    ]
    assert users == []


class _BootstrapFake:
    """Structural provisioner with explicit function-state readback and five baseline green pins."""

    def __init__(self, function_rows: tuple[object, ...], settings: Settings) -> None:
        self.function_rows = function_rows
        self.settings = settings
        self.filter_calls: list[tuple[str, str, str, str]] = []
        self.tool_calls: list[tuple[str, str, str, str]] = []

    def wait_ready(self) -> None:
        pass

    def authenticate(self) -> str:
        return "jwt"

    def ensure_global_filter(
        self, *, function_id: str, name: str, content: str, description: str
    ) -> None:
        self.filter_calls.append((function_id, name, content, description))

    def ensure_tool(self, *, tool_id: str, name: str, content: str, description: str) -> None:
        self.tool_calls.append((tool_id, name, content, description))

    def ensure_model_tool(self, *, model_id: str, tool_id: str) -> None:
        assert (model_id, tool_id) == (self.settings.model_id, self.settings.tool_id)

    def model_ids(self) -> list[str]:
        return [self.settings.model_id]

    def tool_ids(self) -> list[str]:
        return [self.settings.tool_id]

    def model_tool_ids(self, model_id: str) -> list[str]:
        assert model_id == self.settings.model_id
        return [self.settings.tool_id]

    def function_states(self) -> tuple[object, ...]:
        return self.function_rows


def _function_rows(case: str) -> tuple[object, ...]:
    """Build A2's public NamedTuple through the new client seam, not a surrogate fake type."""
    readback = importlib.import_module("webui.client").FunctionReadback
    content = "stale function source" if case == "drifted" else _filter_source()
    active = case != "inactive"
    global_ = case != "nonglobal"
    filter_id = vars(bootstrap)["FILTER_ID"]
    assert isinstance(filter_id, str)
    filter_row = readback(filter_id, "filter", active, global_, content)
    if case == "missing":
        return ()
    extras: list[object] = []
    if case == "extra-active-filter":
        extras.append(
            readback(
                "operator_filter", "filter", is_active=True, is_global=True, content="other source"
            )
        )
    if case == "extra-inactive-filter":
        extras.append(
            readback(
                "operator_filter", "filter", is_active=False, is_global=True, content="other source"
            )
        )
    if case == "extra-active-tool":
        extras.append(
            readback(
                "operator_tool", "tool", is_active=True, is_global=True, content="other source"
            )
        )
    return (filter_row, *extras)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("current", (True, True, True, True)),
        ("drifted", (False, True, True, False)),
        ("inactive", (True, False, False, False)),
        ("nonglobal", (True, False, True, False)),
        ("extra-active-filter", (True, True, False, False)),
        ("extra-inactive-filter", (True, True, True, True)),
        ("extra-active-tool", (True, True, True, True)),
        ("missing", (False, False, False, False)),
    ],
)
def test_f8_smoke_requires_current_global_active_and_exclusive_filter(
    case: str, expected: tuple[bool, bool, bool, bool]
) -> None:
    """F8/A2: every filter readback conjunct fires independently; unrelated rows stay allowed."""
    settings = Settings()
    client = _BootstrapFake(_function_rows(case), settings)
    result = bootstrap.smoke(cast(bootstrap._Provisioner, client), settings)
    assert (
        result.filter_current,
        result.filter_global_active,
        result.filter_exclusive,
        result.ok,
    ) == expected
    assert result.model_enumerated
    assert result.tool_provisioned
    assert result.model_tool_attached
    assert result.model_tool_exclusive
    assert result.no_tool_servers


def test_f8_client_enumerates_all_functions_and_fetches_each_source_by_id() -> None:
    """F8/A2: the readback reports every function; content comes from the per-id GET."""
    function_id = vars(bootstrap)["FILTER_ID"]
    assert isinstance(function_id, str)
    ids = (function_id, "another_active_filter")
    details = {
        ids[0]: {
            "id": ids[0],
            "type": "filter",
            "is_active": True,
            "is_global": True,
            "content": _filter_source(),
        },
        ids[1]: {
            "id": ids[1],
            "type": "filter",
            "is_active": True,
            "is_global": False,
            "content": "another operator's function",
        },
    }
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "jwt"})
        assert request.headers["authorization"] == "Bearer jwt"
        paths.append(path)
        if path == "/api/v1/functions/":
            return httpx.Response(
                200,
                json=[
                    {key: value for key, value in details[item].items() if key != "content"}
                    for item in ids
                ],
            )
        prefix = "/api/v1/functions/id/"
        assert path.startswith(prefix)
        return httpx.Response(200, json=details[path.removeprefix(prefix)])

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://webui.test") as http:
        client = WebUIClient(http, Settings())
        assert client.authenticate() == "jwt"
        states = client.function_states()
    assert type(states) is tuple
    assert {state.id: state._asdict() for state in states} == details
    assert states[0]._fields == ("id", "type", "is_active", "is_global", "content")
    assert paths.count("/api/v1/functions/") == 1
    assert sorted(paths[1:]) == sorted(f"/api/v1/functions/id/{item}" for item in ids)


def test_f8_bootstrap_provisions_exact_generated_filter_source() -> None:
    """F8: the posted filter bytes are the committed artifact, not a hand-maintained fork."""
    settings = Settings()
    client = _BootstrapFake(_function_rows("current"), settings)
    result = bootstrap.run_bootstrap(cast(bootstrap._Provisioner, client), settings)
    assert result.ok
    assert len(client.filter_calls) == 1
    assert client.filter_calls[0][0] == vars(bootstrap)["FILTER_ID"]
    assert client.filter_calls[0][2] == _filter_source()
    assert len(client.tool_calls) == 1
    assert client.tool_calls[0][2] == (REPO_ROOT / _TOOL_ARTIFACT).read_text(encoding="utf-8")


def _sentinels() -> dict[str, str]:
    payload: dict[str, object] = json.loads(
        (REPO_ROOT / "corpus/python/sentinels.json").read_text()
    )
    rows = cast(list[dict[str, object]], payload["prompts"])
    return {cast(str, row["id"]): cast(str, row["prompt"]) for row in rows}


def _captured_simple_program() -> str:
    """Use committed design-set capture bytes, never the model stub's co-derived constant."""
    records = REPO_ROOT / "corpus/python/captures/m13-design/records.ndjson"
    rows = (json.loads(line) for line in records.read_text().splitlines())
    captured = next(row for row in rows if row["prompt_id"] == "sentinel-simple")
    content = captured["content"]
    assert isinstance(content, str)
    source = content.split("```python\n", 1)[1].split("\n```", 1)[0] + "\n"
    assert "pd.read_csv('/mnt/uploads/sales.csv')" in source
    verdict = verify_python_source(
        source,
        declared_target=DatasetTarget(
            "/mnt/uploads/sales.csv", (REPO_ROOT / "data/sales.csv").read_bytes()
        ),
    )
    assert isinstance(verdict, Verified)
    return source


def _stub_reply(user_prompt: str) -> str:
    messages = (
        ChatMessage(role="system", content="Available Tools: draw_figure"),
        ChatMessage(role="user", content=user_prompt),
    )
    return model_stub._scripted_reply(messages)


def test_f9_embedding_bypass_is_pinned_against_ambient_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9: uploaded CSVs remain offline even when ambient OWUI config says otherwise."""
    monkeypatch.setenv("BYPASS_EMBEDDING_AND_RETRIEVAL", "false")
    settings = Settings()
    assert settings.launch_env()["BYPASS_EMBEDDING_AND_RETRIEVAL"] == "true"
    assert settings.child_env()["BYPASS_EMBEDDING_AND_RETRIEVAL"] == "true"


def test_f9_simple_banner_prompt_calls_draw_figure_with_committed_sentinel_program() -> None:
    """F9: exact pinned simple prompt selects legacy draw_figure and committed program bytes."""
    simple = _sentinels()["sentinel-simple"] + " dataset_name: sales.csv"
    assert f'simple_prompt="{simple}"' in (REPO_ROOT / "webui/launch.sh").read_text()
    reply = json.loads(_stub_reply(simple))
    assert reply == {
        "tool_calls": [
            {"name": "draw_figure", "parameters": {"program": _captured_simple_program()}}
        ]
    }


def test_f9_complicated_banner_prompt_returns_prose_without_tool_call() -> None:
    """F9: the pinned complicated arm does not request execution of a chart program."""
    complicated = _sentinels()["sentinel-complicated"]
    assert f'elaborate_prompt="{complicated}"' in (REPO_ROOT / "webui/launch.sh").read_text()
    reply = _stub_reply(complicated)
    assert reply.strip()
    assert "tool_calls" not in reply
    assert "draw_figure" not in reply
    assert not reply.lstrip().startswith("{")
