# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""VPlot v0.1 schema — the restricted chart spec the untrusted model proposes.

The schema gate (syntax only; meaning lives in VPlot_SEMANTICS.md, M1.2b). It
defines frozen, fail-closed msgspec structs and one entry point, decode_spec,
turning raw JSON into a fully validated VPlotSpec or raising. A spec that decodes
is total — never partial or coerced: strict mode rejects float/bool/null tokens
and unknown keys, bounded tuples enforce array lengths, and a duplicate-key scan
rejects the last-wins ambiguity msgspec tolerates. See memory Stack for the
empirically pinned msgspec behaviors (cited below by finding number).
"""

import json
from typing import Annotated, Any, Literal

import msgspec
from msgspec import Meta, Struct, ValidationError

# --- constrained scalar aliases ----------------------------------------------
# Each pattern leads with (?!.*[\r\n]): re's `$` also matches just before a
# trailing newline, so the lookahead is what forbids embedded newlines.
FieldName = Annotated[str, Meta(pattern=r"^(?!.*[\r\n])[A-Za-z_][A-Za-z0-9_]*$", max_length=64)]
DatasetName = Annotated[
    str, Meta(pattern=r"^(?!.*[\r\n])[A-Za-z0-9][A-Za-z0-9._-]*\.csv$", max_length=128)
]
DatasetHash = Annotated[str, Meta(pattern=r"^(?!.*[\r\n])sha256:[0-9a-f]{64}$")]

# Filter literals carry no float/Decimal: int|str rejects float/bool/null at
# decode in strict mode (finding 3), keeping the M1.4 spec re-encode exact.
# Decimals, where a field needs them, travel as bounded strings, lifted per manifest.
FilterValue = int | Annotated[str, Meta(max_length=128)]

# --- closed enums ------------------------------------------------------------
Mark = Literal["bar", "line", "scatter"]
ChannelType = Literal["quantitative", "temporal", "ordinal", "nominal"]
AggFn = Literal["sum", "mean", "count", "min", "max"]
CmpOp = Literal["eq", "ne", "lt", "le", "gt", "ge"]
SortOrder = Literal["ascending", "descending"]


# --- shared struct config ----------------------------------------------------
# forbid_unknown_fields + frozen propagate to subclasses at runtime, but kw_only
# does NOT, and mypy's dataclass_transform reads each class's own kwargs — so
# every concrete struct repeats frozen=True, kw_only=True (finding 1).
class _Base(Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    pass


# --- encoding ----------------------------------------------------------------
class Channel(_Base, frozen=True, kw_only=True):
    field: FieldName
    # msgspec.field via the module (not a bare `field`): the attribute above
    # shadows the name for mypy in this class body. JSON key `type` (reserved).
    kind: ChannelType = msgspec.field(name="type")


class Encoding(_Base, frozen=True, kw_only=True):
    x: Channel
    y: Channel
    color: Channel | None = None


# --- dataset binding ---------------------------------------------------------
class Dataset(_Base, frozen=True, kw_only=True):
    name: DatasetName
    hash: DatasetHash  # JSON key `hash`; binds the spec to the exact source bytes


# --- transforms (tagged union on `op`) ---------------------------------------
# Explicit tag_field + lowercase tag per member (finding 2): else msgspec tags on
# the class name under a `type` field, colliding with the channel `type` key.
class Select(_Base, frozen=True, kw_only=True, tag_field="op", tag="select"):
    fields: Annotated[tuple[FieldName, ...], Meta(min_length=1, max_length=64)]


class Filter(_Base, frozen=True, kw_only=True, tag_field="op", tag="filter"):
    field: FieldName
    cmp: CmpOp
    value: FilterValue


class GroupBy(_Base, frozen=True, kw_only=True, tag_field="op", tag="group_by"):
    keys: Annotated[tuple[FieldName, ...], Meta(min_length=1, max_length=32)]


class Measure(_Base, frozen=True, kw_only=True):
    field: FieldName
    fn: AggFn
    output: FieldName = msgspec.field(name="as")  # JSON key `as` (a keyword)


class Aggregate(_Base, frozen=True, kw_only=True, tag_field="op", tag="aggregate"):
    measures: Annotated[tuple[Measure, ...], Meta(min_length=1, max_length=32)]


class SortKey(_Base, frozen=True, kw_only=True):
    field: FieldName
    order: SortOrder


class Sort(_Base, frozen=True, kw_only=True, tag_field="op", tag="sort"):
    by: Annotated[tuple[SortKey, ...], Meta(min_length=1, max_length=32)]


Transform = Select | Filter | GroupBy | Aggregate | Sort


# --- top-level spec ----------------------------------------------------------
# Arrays are bounded tuples, not lists (finding 7): deeply immutable + hashable.
class VPlotSpec(_Base, frozen=True, kw_only=True):
    version: Literal["vplot-0.1"]
    dataset: Dataset
    transform: Annotated[tuple[Transform, ...], Meta(max_length=64)]
    mark: Mark
    encoding: Encoding


# One module-level strict decoder (strict is msgspec's default; pinned explicitly
# because fail-closed decode is the whole contract of this gate).
_DECODER = msgspec.json.Decoder(VPlotSpec, strict=True)

_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """object_pairs_hook: msgspec keeps the last of duplicate keys silently
    (finding 4), so re-scan the well-formed JSON and reject any repeat."""
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            msg = f"duplicate object key: {key!r}"
            raise ValidationError(msg)
        seen.add(key)
    return dict(pairs)


def decode_spec(raw: bytes | str) -> VPlotSpec:
    """Decode raw JSON into a validated VPlotSpec, or raise.

    Raises msgspec.DecodeError on malformed JSON, msgspec.ValidationError on any
    schema violation (unknown key, bad enum, float/bool/null where a scalar is
    required, length/pattern breach) or a duplicate object key. A returned spec
    is total: every field present and correctly typed.
    """
    spec = _DECODER.decode(raw)
    json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    return spec


def json_schema() -> dict[str, Any]:
    """The VPlot JSON Schema, Draft 2020-12. The $schema URI is stamped last so a
    future msgspec that emits its own cannot override our dialect (finding 5)."""
    return {**msgspec.json.schema(VPlotSpec), "$schema": _DRAFT_2020_12}


def json_schema_text() -> str:
    """json_schema() as deterministic, newline-terminated UTF-8 JSON — the
    byte-exact form committed as schema/vplot-0.1.schema.json."""
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
