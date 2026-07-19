# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Open WebUI harness entry point: serve, provision, chat, or run the model stub."""

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from typing import NoReturn, cast

import httpx

from webui.bootstrap import run_bootstrap
from webui.client import WebUIClient, WebUIProvisionError
from webui.model_stub import serve as serve_stub
from webui.settings import Settings

_LOGGER = logging.getLogger(__name__)


def _serve(settings: Settings) -> NoReturn:
    binary = settings.webui_bin
    if not binary.is_file():
        _LOGGER.error("Open WebUI executable not found: %s", binary)
        raise SystemExit(1)

    argv = [
        str(binary),
        "serve",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
    ]
    os.execve(str(binary), argv, settings.child_env())  # noqa: S606


def _bootstrap(settings: Settings) -> int:
    try:
        with httpx.Client(
            base_url=settings.base_url,
            timeout=settings.request_timeout,
        ) as http:
            result = run_bootstrap(WebUIClient(http, settings), settings)
    except WebUIProvisionError:
        _LOGGER.exception("Open WebUI provisioning failed")
        return 1

    if not result.ok:
        _LOGGER.error(
            "Open WebUI smoke check failed: model_enumerated=%s tool_registered=%s",
            result.model_enumerated,
            result.tool_registered,
        )
        return 1

    _LOGGER.info(
        "Open WebUI provisioning smoke passed: models=%d tool_servers=%d",
        len(result.model_ids),
        len(result.tool_server_ids),
    )
    return 0


def _chat(settings: Settings, prompt: str) -> int:
    """Authenticate, run one persisted chat, and print only its result to stdout."""
    try:
        with httpx.Client(
            base_url=settings.base_url,
            timeout=settings.request_timeout,
        ) as http:
            client = WebUIClient(http, settings)
            client.authenticate()
            result = client.run_persisted_chat(prompt)
    except WebUIProvisionError:
        _LOGGER.exception("Open WebUI chat failed")
        return 1

    output = result.final_text
    if result.chart_url is not None:
        output = f"{output}\n{result.chart_url}"
    sys.stdout.write(f"{output}\n")
    return 0


def _non_empty_prompt(value: str) -> str:
    """Argparse converter rejecting an empty or whitespace-only chat prompt."""
    if not value.strip():
        msg = "--prompt must not be empty"
        raise argparse.ArgumentTypeError(msg)
    return value


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "bootstrap", "stub", "chat"))
    parser.add_argument("--prompt", type=_non_empty_prompt)
    args = parser.parse_args(argv)
    if cast("str", args.command) == "chat" and args.prompt is None:
        parser.error("chat requires --prompt")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    command = cast("str", args.command)
    settings = Settings.from_env()

    if command == "serve":
        _serve(settings)
    elif command == "stub":
        serve_stub(settings)
        return 0
    elif command == "chat":
        return _chat(settings, cast("str", args.prompt))
    else:
        return _bootstrap(settings)


if __name__ == "__main__":
    raise SystemExit(main())
