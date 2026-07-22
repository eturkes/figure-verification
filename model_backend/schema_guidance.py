# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Derive structure-only OpenVINO xgrammar guidance from the strict VPlot schema.

xgrammar rejects the schema's negative-lookahead ``pattern`` values and ignores
``minLength``/``maxLength``/``format`` when a pattern is present. Guidance therefore strips only
``pattern`` and ``format`` recursively while preserving structural constraints. VPlot semantics
and provenance remain the trusted verifier's job.
"""

import hashlib
import json
import math
from pathlib import Path
from typing import Any, cast

type JSON = None | bool | int | float | str | list[JSON] | dict[str, JSON]

__all__ = ["load_guidance_schema", "schema_digest", "strip_guidance"]

# Stripped by JSON-Schema keyword NAME: safe while no VPlot property or `$defs` entry is literally
# named "pattern"/"format" (v0.1: none). A future such property would need context-aware stripping.
_STRIPPED_GUIDANCE_KEYS = frozenset({"pattern", "format"})

# Draft 2020-12 vocabulary names. This is structural recognition, not semantic validation;
# the dependency-free loader rejects empty/arbitrary JSON objects before xgrammar sees them.
_JSON_SCHEMA_KEYWORDS = frozenset(
    {
        "$anchor",
        "$comment",
        "$defs",
        "$dynamicAnchor",
        "$dynamicRef",
        "$id",
        "$ref",
        "$schema",
        "$vocabulary",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "contains",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "default",
        "dependentRequired",
        "dependentSchemas",
        "deprecated",
        "description",
        "else",
        "enum",
        "examples",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "if",
        "items",
        "maxContains",
        "maximum",
        "maxItems",
        "maxLength",
        "maxProperties",
        "minContains",
        "minimum",
        "minItems",
        "minLength",
        "minProperties",
        "multipleOf",
        "not",
        "oneOf",
        "pattern",
        "patternProperties",
        "prefixItems",
        "properties",
        "propertyNames",
        "readOnly",
        "required",
        "then",
        "title",
        "type",
        "unevaluatedItems",
        "unevaluatedProperties",
        "uniqueItems",
        "writeOnly",
    }
)


def _reject_non_finite_constant(token: str) -> object:
    msg = f"non-finite JSON constant is not permitted: {token}"
    raise ValueError(msg)


def _parse_finite_float(token: str) -> object:
    value = float(token)
    if not math.isfinite(value):
        msg = f"non-finite JSON number is not permitted: {token}"
        raise ValueError(msg)
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> object:
    loaded: dict[str, object] = {}
    for key, value in pairs:
        if key in loaded:
            msg = f"duplicate JSON object key: {key!r}"
            raise ValueError(msg)
        loaded[key] = value
    return loaded


def _require_json_schema(schema: dict[str, JSON]) -> None:
    if not schema or not any(key in _JSON_SCHEMA_KEYWORDS for key in schema):
        msg = "VPlot schema root must be a non-empty JSON Schema object"
        raise ValueError(msg)


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
    loaded: Any = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_non_finite_constant,
        parse_float=_parse_finite_float,
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(loaded, dict):
        msg = "VPlot schema root must be a JSON object"
        raise TypeError(msg)
    schema = cast("dict[str, JSON]", loaded)
    _require_json_schema(schema)
    return json.dumps(strip_guidance(schema))


def schema_digest(path: Path) -> str:
    """Return the SHA-256 identity of the schema's exact raw file bytes."""
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
