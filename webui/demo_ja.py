# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The Japanese demo prompt set (M17.3): four requests, their CSVs, the model-authored replies.

`webui/demo_ja.json` holds each request beside the raw reply the real backend wrote for it, taken
at the demo adapter's generation parameters, so the stub replays model-authored bytes exactly as it
replays the committed design capture for the English pair. The set lives outside
`corpus/python/`: that corpus has a closed dataset list, and every committed run partitions its
sentinel rows. `python -m webui.demo_ja` re-captures every reply from a live backend.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import httpx
import msgspec

from capture.harness import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
from capture.record import (
    HostProvenance,
    RepoProvenance,
    ServiceProvenance,
    build_request_body,
    collect_host_provenance,
    collect_repo_provenance,
)
from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.csvread import _read_csv
from verifier.pysrc.limits import DEFAULT_LIMITS
from webui.paste_in.demo_filter import Filter as DemoFilter
from webui.settings import Settings

DEMO_JA = Path(__file__).with_name("demo_ja.json")
DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


class Capture(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Where the replies came from: the tree, the serving backend, the host, the sent caps."""

    repo: RepoProvenance
    service: ServiceProvenance
    host: HostProvenance | None
    temperature: float
    max_tokens: int


class DemoPrompt(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    id: str
    dataset: str
    expect: Literal["pass", "fail"]
    prompt: str
    content: str


class DemoSet(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    version: Literal["demo-ja-1"]
    capture: Capture | None
    prompts: tuple[DemoPrompt, ...]


class _Health(msgspec.Struct):
    model_name: str
    device: str
    structured_output: bool


def load(path: Path = DEMO_JA) -> DemoSet:
    return msgspec.json.decode(path.read_bytes(), type=DemoSet)


def rendered(prompt: DemoPrompt, data_root: Path = DATA_ROOT) -> str:
    """The user message the demo inlet builds for this request over its attached CSV."""
    header, _rows = _read_csv(
        (data_root / prompt.dataset).read_bytes(),
        DEFAULT_LIMITS,
        WorkBudget(DEFAULT_LIMITS.max_work),
    )
    return DemoFilter._TEMPLATE.format(
        task=prompt.prompt, dataset=prompt.dataset, columns=", ".join(header)
    )


def encode(demo: DemoSet) -> bytes:
    """Indented UTF-8 with a trailing newline, so a re-capture diffs line by line."""
    return msgspec.json.format(msgspec.json.encode(demo), indent=2) + b"\n"


def _capture(demo: DemoSet, settings: Settings) -> DemoSet:
    """Ask the live backend once per request, at the adapter's own generation parameters."""
    repo = collect_repo_provenance()
    host = collect_host_provenance()
    base = settings.model_backend_url.rstrip("/")
    with httpx.Client(timeout=600) as client:
        health = client.get(base.removesuffix("/v1") + "/health")
        health.raise_for_status()
        served = msgspec.json.decode(health.content, type=_Health)
        prompts: list[DemoPrompt] = []
        for prompt in demo.prompts:
            reply = client.post(
                f"{base}/chat/completions",
                content=build_request_body(
                    prompt=rendered(prompt),
                    model=settings.model_id,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    temperature=DEFAULT_TEMPERATURE,
                ),
                headers={"Content-Type": "application/json"},
            )
            reply.raise_for_status()
            content = reply.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content:
                msg = f"{prompt.id}: the backend returned no reply text"
                raise ValueError(msg)
            prompts.append(msgspec.structs.replace(prompt, content=content))
    service = ServiceProvenance(
        model_name=served.model_name,
        device=served.device,
        structured_output=served.structured_output,
    )
    capture = Capture(
        repo=repo,
        service=service,
        host=host,
        temperature=DEFAULT_TEMPERATURE,
        max_tokens=DEFAULT_MAX_TOKENS,
    )
    return msgspec.structs.replace(demo, capture=capture, prompts=tuple(prompts))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m webui.demo_ja",
        description=(
            "Capture the model reply for each Japanese demo prompt from a running model backend. "
            "The command rewrites webui/demo_ja.json."
        ),
    )
    parser.parse_args(argv)
    DEMO_JA.write_bytes(encode(_capture(load(), Settings.from_env())))
    sys.stdout.write(f"wrote {DEMO_JA}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
