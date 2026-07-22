# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Derive structure-only OpenVINO xgrammar guidance from the strict VPlot schema.

xgrammar rejects the schema's negative-lookahead ``pattern`` values and ignores
``minLength``/``maxLength``/``format`` when a pattern is present. Guidance therefore strips only
``pattern`` and ``format`` recursively while preserving structural constraints. VPlot semantics
and provenance remain the trusted verifier's job.
"""

import json
from pathlib import Path
from typing import Any, cast

type JSON = None | bool | int | float | str | list[JSON] | dict[str, JSON]

# Stripped by JSON-Schema keyword NAME: safe while no VPlot property or `$defs` entry is literally
# named "pattern"/"format" (v0.1: none). A future such property would need context-aware stripping.
_STRIPPED_GUIDANCE_KEYS = frozenset({"pattern", "format"})


def _strip_guidance(node: JSON) -> JSON:
    if isinstance(node, dict):
        return strip_guidance(node)
    if isinstance(node, list):
        return [_strip_guidance(item) for item in node]
    return node


def strip_guidance(node: dict[str, JSON]) -> dict[str, JSON]:
    """Return a new JSON object with every ``pattern`` and ``format`` key removed."""
    return {
        key: _strip_guidance(value)
        for key, value in node.items()
        if key not in _STRIPPED_GUIDANCE_KEYS
    }


def load_guidance_schema(path: Path) -> str:
    """Load the strict schema and return its pattern/format-stripped JSON guidance."""
    loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = "VPlot schema root must be a JSON object"
        raise TypeError(msg)
    schema = cast("dict[str, JSON]", loaded)
    return json.dumps(strip_guidance(schema))
