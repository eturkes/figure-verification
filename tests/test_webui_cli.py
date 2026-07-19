# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Pin the Open WebUI harness CLI without starting processes or opening sockets."""

import os
from pathlib import Path
from typing import NoReturn

import pytest

import webui.__main__ as cli
from webui.bootstrap import SmokeResult
from webui.client import PersistedChatResult, WebUIClient, WebUIProvisionError
from webui.settings import Settings


class _ServeCalledError(RuntimeError):
    """Stop the fake serve branch after recording its argument."""


class _ExecedError(RuntimeError):
    """Stand in for a successful, non-returning execve call."""


_SENTINEL = Settings()


@pytest.mark.parametrize("command", ["serve", "bootstrap", "stub"])
def test_parse_args_accepts_command(command: str) -> None:
    assert cli._parse_args([command]).command == command


def test_parse_args_accepts_chat_prompt() -> None:
    args = cli._parse_args(["chat", "--prompt", "x"])

    assert args.command == "chat"
    assert args.prompt == "x"


@pytest.mark.parametrize("argv", [["chat"], ["chat", "--prompt", ""], ["chat", "--prompt", " "]])
def test_parse_args_rejects_chat_without_non_empty_prompt(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli._parse_args(argv)


def test_parse_args_rejects_unknown_command() -> None:
    with pytest.raises(SystemExit):
        cli._parse_args(["x"])


def test_main_dispatches_serve_with_one_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Settings] = []

    def fake_serve(settings: Settings) -> NoReturn:
        seen.append(settings)
        raise _ServeCalledError

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: _SENTINEL))
    monkeypatch.setattr(cli, "_serve", fake_serve)

    with pytest.raises(_ServeCalledError):
        cli.main(["serve"])

    assert seen == [_SENTINEL]


def test_main_dispatches_stub_with_one_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Settings] = []

    def fake_stub(settings: Settings) -> None:
        seen.append(settings)

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: _SENTINEL))
    monkeypatch.setattr(cli, "serve_stub", fake_stub)

    assert cli.main(["stub"]) == 0
    assert seen == [_SENTINEL]


def test_main_dispatches_bootstrap_with_one_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Settings] = []

    def fake_bootstrap(settings: Settings) -> int:
        seen.append(settings)
        return 0

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: _SENTINEL))
    monkeypatch.setattr(cli, "_bootstrap", fake_bootstrap)

    assert cli.main(["bootstrap"]) == 0
    assert seen == [_SENTINEL]


def test_main_dispatches_chat_and_prints_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def fake_authenticate(_self: WebUIClient) -> str:
        calls.append("authenticate")
        return "jwt"

    def fake_run_persisted_chat(
        _self: WebUIClient,
        prompt: str,
    ) -> PersistedChatResult:
        calls.append(f"chat:{prompt}")
        return PersistedChatResult(final_text="answer", chart_url="http://chart.test/1")

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: _SENTINEL))
    monkeypatch.setattr(WebUIClient, "authenticate", fake_authenticate)
    monkeypatch.setattr(WebUIClient, "run_persisted_chat", fake_run_persisted_chat)

    assert cli.main(["chat", "--prompt", "x"]) == 0
    assert calls == ["authenticate", "chat:x"]
    assert capsys.readouterr().out == "answer\nhttp://chart.test/1\n"


def test_main_chat_maps_provision_error_to_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_authenticate(_self: WebUIClient) -> str:
        return "jwt"

    def fake_run_persisted_chat(
        _self: WebUIClient,
        _prompt: str,
    ) -> PersistedChatResult:
        message = "chat failed"
        raise WebUIProvisionError(message)

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: _SENTINEL))
    monkeypatch.setattr(WebUIClient, "authenticate", fake_authenticate)
    monkeypatch.setattr(WebUIClient, "run_persisted_chat", fake_run_persisted_chat)

    assert cli.main(["chat", "--prompt", "x"]) == 1
    assert capsys.readouterr().out == ""


def test_main_chat_without_prompt_errors() -> None:
    with pytest.raises(SystemExit):
        cli.main(["chat"])


def test_serve_execs_open_webui_with_hermetic_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "open-webui"
    binary.touch()
    settings = Settings(webui_bin=binary)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("WEBUI_PROVISION_LEAK", "x")

    def fake_execve(path: str, argv: list[str], env: dict[str, str]) -> NoReturn:
        assert path == str(binary)
        assert argv == [
            str(binary),
            "serve",
            "--host",
            settings.host,
            "--port",
            str(settings.port),
        ]
        assert env["OFFLINE_MODE"] == "true"
        assert env["PATH"] == "/usr/bin"
        assert "WEBUI_PROVISION_LEAK" not in env
        raise _ExecedError

    monkeypatch.setattr(os, "execve", fake_execve)

    with pytest.raises(_ExecedError):
        cli._serve(settings)


def test_serve_rejects_missing_binary(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        cli._serve(Settings(webui_bin=tmp_path / "absent"))

    assert exc.value.code == 1


@pytest.mark.parametrize(("b", "expected"), [(True, 0), (False, 1)])
def test_bootstrap_returns_smoke_status(
    monkeypatch: pytest.MonkeyPatch, *, b: bool, expected: int
) -> None:
    def fake_run_bootstrap(_client: object, _settings: Settings) -> SmokeResult:
        return SmokeResult(
            model_ids=(),
            tool_server_ids=(),
            model_enumerated=b,
            tool_registered=b,
        )

    monkeypatch.setattr(cli, "run_bootstrap", fake_run_bootstrap)

    assert cli._bootstrap(Settings()) == expected


def test_bootstrap_maps_provision_error_to_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_bootstrap(_client: object, _settings: Settings) -> SmokeResult:
        message = "provisioning failed"
        raise WebUIProvisionError(message)

    monkeypatch.setattr(cli, "run_bootstrap", fake_run_bootstrap)

    assert cli._bootstrap(Settings()) == 1
