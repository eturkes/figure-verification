# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Standalone Open WebUI outlet filter for unverified chart-like replies.

This file is both repo code and the exact function source provisioned into Open WebUI. Keep it
stdlib-only and free of repo imports: Open WebUI import-executes the posted bytes in its own Python
environment. The classifier is intentionally heuristic. It catches common direct-chart forms as a
guardrail; it is neither a security boundary nor part of the verifier's correctness claim.

Only the final assistant message is eligible for rewriting. A block log records signal names and
content length, never assistant content, so diagnostics do not copy potentially sensitive text.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Final

FILTER_ID: Final = "verified_plot_guard"
FILTER_NAME: Final = "Verified Plot Guard"
FILTER_DESCRIPTION: Final = (
    "Routes common direct-chart replies back through Figure Verifier; heuristic guardrail only."
)
BLOCKED_NOTICE: Final = (
    "This chart was blocked because it bypassed Figure Verifier. Ask me to create it through "
    "Figure Verifier so its data and provenance can be checked."
)

_LOGGER = logging.getLogger(FILTER_ID)

_FENCE = re.compile(
    r"(?ms)^[ ]{0,3}```(?P<info>[^\r\n`]*)\r?\n"
    r"(?P<body>.*?)(?:^[ ]{0,3}```[ \t]*(?:\r?\n|\Z)|\Z)"
)
_SVG = re.compile(r"<\s*svg(?:\s|>)", re.IGNORECASE)
_DATA_IMAGE = re.compile(r"\bdata:image/[a-z0-9.+-]+(?:;[^\s,]*)?,", re.IGNORECASE)
_CODE_SIGNALS: Final = (
    (
        "matplotlib",
        re.compile(
            r"\b(?:matplotlib|pyplot)\b|\bplt\s*\.\s*"
            r"(?:bar|barh|hist|imshow|pie|plot|scatter|stackplot|stem)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "plotly",
        re.compile(
            r"\bplotly\b|\b(?:px|go)\s*\.\s*(?:area|bar|box|figure|histogram|line|pie|scatter)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "altair",
        re.compile(r"\baltair\b|\balt\s*\.\s*chart\b", re.IGNORECASE),
    ),
    (
        "seaborn",
        re.compile(
            r"\bseaborn\b|\bsns\s*\.\s*"
            r"(?:barplot|boxplot|catplot|displot|histplot|lineplot|pairplot|scatterplot|violinplot)\b",
            re.IGNORECASE,
        ),
    ),
)
_VEGA_STRUCTURE_KEYS: Final = frozenset(
    {"data", "dataset", "datasets", "facet", "hconcat", "layer", "repeat", "vconcat"}
)


def _fences(text: str) -> tuple[tuple[str, str], ...]:
    """Return normalized info strings + bodies for closed or EOF-terminated Markdown fences."""
    return tuple(
        (match["info"].strip().casefold(), match["body"]) for match in _FENCE.finditer(text)
    )


def _json_candidates(text: str, fences: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    """Whole reply plus JSON/Vega-labelled fence bodies that might hold a chart spec."""
    candidates = [text.strip()]
    candidates.extend(
        body.strip()
        for info, body in fences
        if not info or info.split(maxsplit=1)[0] in {"json", "vega", "vega-lite", "vegalite"}
    )
    return tuple(candidate for candidate in candidates if candidate)


def _is_vega_lite_json(candidate: str) -> bool:
    """Whether one complete JSON value has a Vega-Lite schema marker or chart structure."""
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, RecursionError):
        return False
    if not isinstance(value, dict):
        return False

    schema = value.get("$schema")
    if isinstance(schema, str) and "vega.github.io/schema/vega-lite/" in schema.casefold():
        return True
    return (
        "mark" in value
        and isinstance(value.get("encoding"), dict)
        and not _VEGA_STRUCTURE_KEYS.isdisjoint(value)
    )


def chart_signals(text: str) -> tuple[str, ...]:
    """Return canonical, deduplicated signals for common direct-chart representations."""
    fences = _fences(text)
    signals: list[str] = []

    fenced_text = tuple(f"{info}\n{body}" for info, body in fences)
    for name, pattern in _CODE_SIGNALS:
        if any(pattern.search(candidate) for candidate in fenced_text):
            signals.append(name)
    if any(info.split(maxsplit=1)[0] == "mermaid" for info, _body in fences if info):
        signals.append("mermaid")
    if _SVG.search(text):
        signals.append("svg")
    if any(_is_vega_lite_json(candidate) for candidate in _json_candidates(text, fences)):
        signals.append("vega-lite")
    if _DATA_IMAGE.search(text):
        signals.append("data-image")
    return tuple(signals)


def function_source() -> str:
    """Return this standalone module verbatim for Open WebUI's function create/update API."""
    return Path(__file__).read_text(encoding="utf-8")


class Filter:
    """Open WebUI function contract: rewrite a chart-like final assistant message in-place."""

    def outlet(self, body: dict[str, object]) -> dict[str, object]:
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return body
        message = messages[-1]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return body
        content = message.get("content")
        if not isinstance(content, str):
            return body

        signals = chart_signals(content)
        if not signals:
            return body
        message["content"] = BLOCKED_NOTICE
        _LOGGER.warning(
            "Blocked unverified chart-like assistant output: signals=%s chars=%d",
            ",".join(signals),
            len(content),
        )
        return body
