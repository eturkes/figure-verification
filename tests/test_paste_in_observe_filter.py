# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.2 O6: the outlet can only withhold a core pass, never admit a refusal.

Contract: `.agent/archive/contracts/m10u2.md` O6 + A1; `.agent/archive/contracts/m10u1.md` F4/F5
and A1/A3 fix the filter's callable, backend-owned tuple receipt and the persisted output shape.
"""

import asyncio
import base64
import importlib
import math
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from observe_support import (
    OBS_MAX_BYTES,
    OBS_TAG,
    committed_sales_verdict,
    observation_for,
    stdout_for,
)
from oracle_filter import status_event
from paste_in_support import StoredFile, fake_open_webui
from verifier.pysrc import Verified

_USER_ID = "observation-owner"
_PASSED = "Figure verification passed"
_FAILED = "Figure verification failed, no image produced"
_PROGRAM = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    'df = pd.read_csv("/mnt/uploads/sales.csv")\n'
    'g = df.groupby("region")["revenue"].sum()\n'
    "plt.bar(g.index, g.values)\n"
    "plt.show()\n"
)
_REFUSED_PROGRAM = "import matplotlib.pyplot as plt\nplt.bar(1, 2)\nplt.show()\n"


def _png_uri() -> str:
    """Encode a complete one-pixel PNG rather than passing only a base64 magic prefix."""

    def chunk(name: bytes, contents: bytes) -> bytes:
        header = struct.pack(">I", len(contents)) + name + contents
        return header + struct.pack(">I", zlib.crc32(name + contents))

    blob = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(blob).decode("ascii")


_PNG_URI = _png_uri()


@dataclass
class _RPC:
    stdout: str
    stderr: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, event: dict[str, Any]) -> dict[str, object]:
        assert event["type"] == "execute:python"
        assert set(event["data"]) == {"id", "code", "session_id", "files"}
        self.calls.append(event)
        return {"stdout": self.stdout, "stderr": self.stderr, "result": None}


@dataclass
class _Emitter:
    events: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _body() -> dict[str, Any]:
    return {
        "messages": [
            {"role": "user", "content": "Earlier message stays unchanged."},
            {
                "role": "assistant",
                "content": "Model narration has no authority over the figure.",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Model narration."}],
                    }
                ],
            },
        ]
    }


def _receipt(program: str) -> SimpleNamespace:
    # Backend request state is shared between the tool and filter but their generated module
    # namespaces are not. The carrier is a built-in tuple, never the tool's Receipt instance.
    carrier = ("figure-verification-receipt/1", program, ("owned-file",), None)
    return SimpleNamespace(state=SimpleNamespace(figure_verification_receipt=carrier))


def _render(
    tmp_path: Path,
    stdout: str,
    *,
    program: str = _PROGRAM,
    receipt: bool = True,
    stderr: str = "",
) -> tuple[dict[str, Any], _RPC, _Emitter, list[tuple[str, str]]]:
    """Drive the actual outlet with independently constructed request, owned store and RPC."""
    rpc = _RPC(stdout, stderr)
    emitter = _Emitter()
    body = _body()
    stored = StoredFile(
        file_id="owned-file",
        user_id=_USER_ID,
        filename="sales.csv",
        content=(Path(__file__).resolve().parent.parent / "data" / "sales.csv").read_bytes(),
    )
    request = _receipt(program) if receipt else SimpleNamespace(state=SimpleNamespace())
    with fake_open_webui([stored], tmp_path) as looked_up:
        output = asyncio.run(
            importlib.import_module("webui.paste_in.filter")
            .Filter()
            .outlet(
                body,
                __user__={"id": _USER_ID},
                __request__=request,
                __event_call__=rpc,
                __event_emitter__=emitter,
                __metadata__={"session_id": "local-session"},
            )
        )
    assert isinstance(output, dict)
    return output, rpc, emitter, looked_up


def _assert_text(output: dict[str, Any], text: str) -> None:
    messages = output["messages"]
    assert messages[0] == {"role": "user", "content": "Earlier message stays unchanged."}
    message = messages[-1]
    assert message["content"] == text
    assert isinstance(message["output"], list)
    assert len(message["output"]) == 1
    item = message["output"][0]
    assert item["type"] == "message"
    assert item["content"] == [{"type": "output_text", "text": text}]


def _observed_stdout() -> tuple[Verified, str]:
    verified = committed_sales_verdict("bar")
    return verified, stdout_for(observation_for(verified, "categorical")) + _PNG_URI + "\n"


def test_o6_matching_observation_preserves_pass_with_one_inline_image(tmp_path: Path) -> None:
    """O6: authentic Verified plus a matching artist publishes F5's text and one files event."""
    verified, stdout = _observed_stdout()
    output, rpc, emitter, looked_up = _render(tmp_path, stdout)
    _assert_text(output, _PASSED + "\n\n" + verified.certificate.interpretation)
    assert emitter.events == [
        {"type": "files", "data": {"files": [{"type": "image", "url": _PNG_URI}]}}
    ]
    assert len(rpc.calls) == 1
    assert looked_up == [("owned-file", _USER_ID)]


@pytest.mark.parametrize(
    "failure",
    ["missing", "unparseable", "duplicate", "oversized", "mismatching", "extra-artist", "stderr"],
)
def test_o6_verified_with_bad_observation_withholds_figure(tmp_path: Path, failure: str) -> None:
    """O6: every observation failure turns the re-derived PASS into FAIL before publication."""
    verified, good = _observed_stdout()
    if failure == "missing":
        stdout = _PNG_URI + "\n"
    elif failure == "unparseable":
        stdout = OBS_TAG + "{broken-json\n" + _PNG_URI + "\n"
    elif failure == "duplicate":
        stdout = good.replace(
            _PNG_URI, stdout_for(observation_for(verified, "categorical")) + _PNG_URI
        )
    elif failure == "oversized":
        payload = observation_for(verified, "categorical")
        payload["xaxis"]["ticks"][0][1] = "Z" * OBS_MAX_BYTES
        stdout = stdout_for(payload) + _PNG_URI + "\n"
    elif failure == "mismatching":
        payload = observation_for(verified, "categorical")
        patch = payload["containers"][0][0]
        patch[3] = math.nextafter(float.fromhex(patch[3]), math.inf).hex()
        stdout = stdout_for(payload) + _PNG_URI + "\n"
    elif failure == "extra-artist":
        payload = observation_for(verified, "categorical")
        payload["lines"] = [[[(0.0).hex(), (0.0).hex()]]]
        stdout = stdout_for(payload) + _PNG_URI + "\n"
    else:
        assert failure == "stderr"
        stdout = good
    output, rpc, emitter, looked_up = _render(
        tmp_path, stdout, stderr="observer error" if failure == "stderr" else ""
    )
    _assert_text(output, _FAILED)
    reasons = {
        "missing": "no_observation",
        "unparseable": "no_observation",
        "duplicate": "no_observation",
        "oversized": "no_observation",
        "mismatching": "observation_mismatch",
        "extra-artist": "observation_mismatch",
        "stderr": "sandbox_error",
    }
    assert emitter.events == [status_event(reasons[failure])]
    assert len(rpc.calls) == 1
    assert looked_up == [("owned-file", _USER_ID)]


@pytest.mark.parametrize("carrier", ["refused", "missing-receipt"])
def test_o6_refused_or_unrecorded_call_never_consults_observation(
    tmp_path: Path, carrier: str
) -> None:
    """O6: a core refusal or absent receipt fails without an RPC, even if the fake would match."""
    _verified, matching = _observed_stdout()
    output, rpc, emitter, looked_up = _render(
        tmp_path,
        matching,
        program=_REFUSED_PROGRAM if carrier == "refused" else _PROGRAM,
        receipt=carrier == "refused",
    )
    _assert_text(output, _FAILED)
    assert rpc.calls == []
    reason = "mark_not_valid_for_arm" if carrier == "refused" else "no_tool_call"
    assert emitter.events == [status_event(reason)]
    assert looked_up == ([("owned-file", _USER_ID)] if carrier == "refused" else [])
