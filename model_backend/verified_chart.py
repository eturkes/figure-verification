# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic closing reply for Open WebUI's post-verified-chart summarize turn.

Open WebUI's legacy function-calling loop, once the verifier has certified and embedded a chart,
injects the verifier's success summary into a follow-up completion and RE-PROMPTS this backend for a
human-facing final answer. Left to the 0.5B proposer, that answer is free-text filler unrelated to
the chart (observed: a fabricated "increases efficiency by 20% [1]" study citation). This module
lets the backend RECOGNIZE that one turn and return a fixed sentence instead of generating. It is
the only cosmetic determinism added to the proposer: tool selection, the verifier's guided spec
generation, and every verifier guarantee (certification, provenance, rendering) stay model-driven
and untouched.

Recognition is a wire contract, not an import. The verifier (src/verifier/service/app.py) emits the
success summary ``Verified chart for {dataset}: all {N} checks passed.``; Open WebUI stores the
chart Location as the message embed and str()-ifies that summary into this turn's citation context
(a ``<source ...>...</source>`` block in the system prompt). We match the summary SHAPE here without
importing the verifier -- this is the untrusted proposer, so the two packages stay decoupled, and
matching the summary (not Open WebUI's citation wrapper) keeps recognition robust to Open WebUI
changing that wrapper. The summary exists only AFTER verification, so it appears in NEITHER the
tool-selector turn, the verifier's own pre-verify guided generation turn, nor ordinary chat -- only
this post-chart turn. A crafted user message echoing the exact summary would also trip it; harmless
in this demo backend, since the verifier re-decodes and re-verifies every real proposal regardless.

VERIFIED_CHART_REPLY is the single source of truth shared with the hardware-free E2E stub
(webui/model_stub.py adopts it as its final-summary reply), so the live NPU backend and the scripted
stub close the verified-plot demo with the identical line.
"""

import re

from model_backend.models import ChatMessage

VERIFIED_CHART_REPLY = "Figure Verifier confirmed the chart; all checks passed."

# Mirrors the verifier success summary f"Verified chart for {dataset}: all {N} checks passed."
# (src/verifier/service/app.py). Dataset name and check count vary per request; the surrounding
# text is fixed. No DOTALL: the summary is single-line, so `.` stops recognition at a line break.
_SUMMARY_RE = re.compile(r"Verified chart for .+?: all \d+ checks passed\.")


def is_verified_chart_summary(messages: tuple[ChatMessage, ...]) -> bool:
    """Report whether any message carries the verifier's post-verification success summary.

    True only on Open WebUI's post-verified-chart summarize turn (see module docstring); the caller
    then returns VERIFIED_CHART_REPLY instead of generating a fresh answer.
    """
    return any(_SUMMARY_RE.search(message.content) for message in messages)
