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

# Filter literals carry no float/Decimal: int|str rejects float/bool/null at decode in
# strict mode (finding 3), keeping the M1.4 spec re-encode exact. The int is bounded to
# signed 64-bit (the universal integer-column domain); larger or fractional numbers
# travel as bounded strings, lifted per manifest at eval.
FilterInt = Annotated[int, Meta(ge=-(2**63), le=2**63 - 1)]
FilterValue = FilterInt | Annotated[str, Meta(max_length=128)]

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
    # JSON key `hash`; DECLARES the expected SHA-256 of the source bytes. The bind/verify
    # against the actual file bytes is M1.5 — this gate only checks the hash's shape.
    hash: DatasetHash


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

    The only two failure modes: msgspec.DecodeError on malformed or non-UTF-8 JSON,
    msgspec.ValidationError on any schema violation (unknown key, bad enum,
    float/bool/null where a scalar is required, length/pattern breach) or a duplicate
    object key. A returned spec is total: every field present and correctly typed.

    str input is normalized to UTF-8 bytes first so the strict decode and the
    duplicate-key rescan see identical bytes, and a lone surrogate maps to DecodeError
    instead of leaking UnicodeEncodeError. For bytes input, msgspec finding 9 shows that
    Decoder.decode can raise builtin UnicodeDecodeError for invalid UTF-8 inside a JSON
    string; that also maps to DecodeError. Callers guarding DecodeError and ValidationError
    therefore see the documented decode failure instead of an escaping builtin. The rescan
    runs only after the decode succeeds, so it sees solely the bounded VPlotSpec shape (no
    pathological depth); its sole job is to reject the duplicate keys msgspec silently
    last-wins (finding 4).
    """
    if isinstance(raw, str):
        try:
            data = raw.encode("utf-8")
        except UnicodeEncodeError as exc:
            msg = "spec input is not valid UTF-8"
            raise msgspec.DecodeError(msg) from exc
    else:
        data = raw
    try:
        spec = _DECODER.decode(data)
    except UnicodeDecodeError as exc:
        msg = "spec input is not valid UTF-8"
        raise msgspec.DecodeError(msg) from exc
    json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    return spec


def json_schema() -> dict[str, Any]:
    """The VPlot JSON Schema, Draft 2020-12 — an ADVISORY mirror of decode_spec, not the
    gate. JSON Schema's `integer` admits zero-fraction floats (1.0, 1e3) that strict
    decode rejects and cannot express the float-token rejection, so the schema is
    slightly more permissive; decode_spec is authoritative. The $schema URI is popped
    and re-appended so it sorts last even if a future msgspec emits its own (finding 5)."""
    doc = msgspec.json.schema(VPlotSpec)
    doc.pop("$schema", None)
    doc["$schema"] = _DRAFT_2020_12
    return doc


def json_schema_text() -> str:
    """json_schema() as deterministic, newline-terminated UTF-8 JSON — the
    byte-exact form committed as schema/vplot-0.1.schema.json."""
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
