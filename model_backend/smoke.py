# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Live smoke probe for a running backend — `python -m model_backend.smoke`.

Runs against an already-serving backend on settings.host/port from the isolated .venv-model
runtime project, so it needs the accelerator that `python -m model_backend` needed. A probe, not
a test: pytest never collects it and coverage never sees it, while ruff and mypy do lint it.

Three assertions, then one machine-readable report line:
1. GET /v1/models lists exactly the served model, backend-neutral owner.
2. POST /v1/chat/completions returns non-empty content for a fixed greedy prompt, timed for a
   generated-tokens-per-second figure.
3. POST with a repetition-built over-cap prompt returns 400 and the byte-exact refusal envelope
   the verifier's model client re-encodes and compares. Any drift there silently reclassifies a
   policy refusal into an upstream fault, so the comparison is on bytes, never on a decoded dict.

Exit code 0 means every assertion held.
"""

import sys
import time
from typing import Any

import httpx

from model_backend.settings import Settings

_TIMEOUT = httpx.Timeout(600.0, connect=10.0)
# F5's own prompt pair, kept byte-identical so this probe's output stays comparable to the
# recorded port evidence.
_SYSTEM_PROMPT = "Reply with one Python statement only."
_USER_PROMPT = "Print the sum of 2 and 3."
_SMOKE_MAX_TOKENS = 64


class SmokeError(Exception):
    """One probe assertion did not hold."""


def _require(condition: bool, message: str) -> None:  # noqa: FBT001 - probe assertion helper
    if not condition:
        raise SmokeError(message)


def _check_models(client: httpx.Client, settings: Settings) -> None:
    """Assert /v1/models lists exactly the served model under a backend-neutral owner."""
    response = client.get("/v1/models")
    _require(response.status_code == httpx.codes.OK, f"/v1/models status {response.status_code}")
    cards: Any = response.json()["data"]
    _require(len(cards) == 1, f"/v1/models listed {len(cards)} cards, expected 1")
    card: Any = cards[0]
    _require(
        card["id"] == settings.model_name,
        f"/v1/models id {card['id']!r} != {settings.model_name!r}",
    )
    _require(card["owned_by"] == "local", f"/v1/models owned_by {card['owned_by']!r} != 'local'")


def _check_completion(client: httpx.Client) -> tuple[int, float]:
    """Generate once from the fixed greedy prompt; return (completion_tokens, seconds)."""
    started = time.perf_counter()
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_PROMPT},
            ],
            "temperature": 0.0,
            "max_tokens": _SMOKE_MAX_TOKENS,
        },
    )
    elapsed = time.perf_counter() - started
    _require(response.status_code == httpx.codes.OK, f"completion status {response.status_code}")
    body: Any = response.json()
    content: str = body["choices"][0]["message"]["content"]
    _require(content.strip() != "", "completion returned empty content")
    completion_tokens: int = body["usage"]["completion_tokens"]
    _require(completion_tokens > 0, "completion reported zero generated tokens")
    return completion_tokens, elapsed


def _check_over_cap_refusal(client: httpx.Client, settings: Settings) -> None:
    """Assert the byte-exact prompt_too_long envelope at the configured cap."""
    # Built by repetition: every repeated word costs at least one token, so the templated prompt
    # provably exceeds the cap without depending on any one tokenizer's vocabulary.
    over_cap = "data " * (settings.max_prompt_len + 64)
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": over_cap}], "temperature": 0.0},
    )
    _require(
        response.status_code == httpx.codes.BAD_REQUEST,
        f"over-cap status {response.status_code}, expected 400",
    )
    _require(
        response.headers["content-type"].partition(";")[0].strip() == "application/json",
        f"over-cap media type {response.headers['content-type']!r}",
    )
    expected = (
        b'{"error":{"message":"tokenized prompt exceeds the '
        + str(settings.max_prompt_len).encode("ascii")
        + b'-token ceiling","type":"prompt_too_long"}}'
    )
    _require(
        response.content == expected,
        f"over-cap body {response.content!r} != {expected!r}",
    )


def _accelerator_report(settings: Settings) -> str:
    """Describe the accelerator this probe just exercised, as key=value fields."""
    import torch  # noqa: PLC0415 — only the two probes in this package may import torch

    if not settings.device.startswith("cuda") or not torch.cuda.is_available():
        return f'gpu="none" capability="none" cuda_available={torch.cuda.is_available()}'
    index = torch.cuda.current_device()
    major, minor = torch.cuda.get_device_capability(index)
    return (
        f'gpu="{torch.cuda.get_device_name(index)}" capability={major}.{minor} cuda_available=True'
    )


def main() -> int:
    """Probe the running backend and print one report line. Returns a process exit code."""
    settings = Settings.from_env()
    base_url = f"http://{settings.host}:{settings.port}"
    with httpx.Client(base_url=base_url, timeout=_TIMEOUT) as client:
        _check_models(client, settings)
        completion_tokens, elapsed = _check_completion(client)
        _check_over_cap_refusal(client, settings)
    sys.stdout.write(
        f"smoke=ok device={settings.device} {_accelerator_report(settings)} "
        f'dtype=float16 model="{settings.model_name}" '
        f"completion_tokens={completion_tokens} seconds={elapsed:.3f} "
        f"tok_s={completion_tokens / elapsed:.3f}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
