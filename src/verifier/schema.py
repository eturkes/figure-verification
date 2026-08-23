# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""VPlot v0.1 schemas — the restricted chart specs the untrusted model proposes.

The schema gates (syntax only; meaning lives in VPlot_SEMANTICS.md)
define frozen, fail-closed msgspec structs and two entry points: decode_spec for
dataset mode and decode_formula_spec for formula mode. Each turns raw JSON into a
fully shape-validated, total spec or raises. A spec that decodes is never partial
or coerced: strict mode rejects float/bool/null tokens and unknown keys, bounded
tuples enforce array lengths, and a duplicate-key scan rejects the last-wins
ambiguity msgspec tolerates. See memory Stack for the empirically pinned msgspec
behaviors (cited below by finding number).
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
# FormulaText's ASCII-only v0.1 alphabet admits digits, letters, underscore, space,
# parentheses, decimal point, and + - * /. Length in characters therefore equals bytes;
# commas/quotes/semicolons/^/=/brackets/braces are unrepresentable.
FormulaText = Annotated[str, Meta(pattern=r"^(?!.*[\r\n])[0-9A-Za-z_ ().*/+-]+$", max_length=1024)]
# Domain endpoints are bounded decimal STRINGS, never JSON floats: no exponent, leading
# plus/zeroes, or trailing point; at most 18 integer and 9 fractional digits. The grammar
# is self-bounding at 29 characters (sign + 18 + point + 9), so unlike FieldName/DatasetName
# — whose patterns are unbounded — this alias carries NO max_length: a cap here could never
# bind, and dead policy reads as tested policy.
DecimalText = Annotated[
    str, Meta(pattern=r"^(?!.*[\r\n])-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,9})?$")
]

# Filter literals carry no float/Decimal: int|str rejects float/bool/null at decode in
# strict mode (finding 3), keeping the spec re-encode exact. The int is bounded to
# signed 64-bit (the universal integer-column domain); larger or fractional numbers
# travel as bounded strings, lifted per manifest at eval.
FilterInt = Annotated[int, Meta(ge=-(2**63), le=2**63 - 1)]
FilterValue = FilterInt | Annotated[str, Meta(max_length=128)]

# --- closed enums ------------------------------------------------------------
Mark = Literal["bar", "line", "scatter"]
# Formula mode deliberately excludes bars: sampled functions are line/scatter only.
FormulaMark = Literal["line", "scatter"]
NumericProfile = Literal["rational-half-even-v1"]
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


# --- formula encoding --------------------------------------------------------
class FormulaXChannel(_Base, frozen=True, kw_only=True):
    field: Literal["x"]
    kind: Literal["quantitative"] = msgspec.field(name="type")


class FormulaYChannel(_Base, frozen=True, kw_only=True):
    field: Literal["y"]
    kind: Literal["quantitative"] = msgspec.field(name="type")


class FormulaEncoding(_Base, frozen=True, kw_only=True):
    x: FormulaXChannel
    y: FormulaYChannel


# --- dataset binding ---------------------------------------------------------
class Dataset(_Base, frozen=True, kw_only=True):
    name: DatasetName
    # JSON key `hash`; DECLARES the expected SHA-256 of the source bytes. The bind/verify
    # against the actual file bytes is the checks layer — this gate only checks the hash's shape.
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


# Shape only: ordering, representability, grammar, names/functions/exponents, and sample
# distinctness are formula semantic checks, never Struct post-init validation.
class FormulaDomain(_Base, frozen=True, kw_only=True):
    start: DecimalText
    stop: DecimalText
    samples: Annotated[int, Meta(ge=2, le=100_000)]
    x_scale: Annotated[int, Meta(ge=0, le=12)]
    y_scale: Annotated[int, Meta(ge=0, le=12)]


class FormulaPlotSpec(_Base, frozen=True, kw_only=True):
    version: Literal["vplot-formula-0.1"]
    formula: FormulaText
    domain: FormulaDomain
    numeric_profile: NumericProfile
    mark: FormulaMark
    encoding: FormulaEncoding


type DatasetPlotSpec = VPlotSpec
type PlotSpec = VPlotSpec | FormulaPlotSpec


# One module-level strict decoder per external shape (strict is msgspec's default;
# pinned explicitly because fail-closed decode is the whole contract of these gates).
_DECODER = msgspec.json.Decoder(VPlotSpec, strict=True)
_FORMULA_DECODER = msgspec.json.Decoder(FormulaPlotSpec, strict=True)

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


def _decode[T](raw: bytes | str, decoder: msgspec.json.Decoder[T]) -> T:
    """Run the shared UTF-8, strict-shape, then duplicate-key decode mechanics.

    str input is normalized to UTF-8 bytes first so strict decode and the rescan see
    identical bytes; lone surrogates map to DecodeError. For bytes input, msgspec finding
    9's builtin UnicodeDecodeError also maps to DecodeError. The rescan runs only after
    strict decode succeeds, so it sees a bounded shape and solely rejects msgspec's
    duplicate-key last-wins behavior (finding 4).
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
        decoded = decoder.decode(data)
    except UnicodeDecodeError as exc:
        msg = "spec input is not valid UTF-8"
        raise msgspec.DecodeError(msg) from exc
    json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    return decoded


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
    return _decode(raw, _DECODER)


def decode_formula_spec(raw: bytes | str) -> FormulaPlotSpec:
    """Decode raw JSON into a shape-validated FormulaPlotSpec, or raise.

    Failure types and UTF-8/duplicate-key handling match :func:`decode_spec`. This gate is
    syntax only: formula grammar and all cross-field numeric/domain meaning remain formula
    semantic checks, so a shape-valid but semantically doomed spec still decodes.
    """
    return _decode(raw, _FORMULA_DECODER)


def _schema_doc(spec: type[Struct]) -> dict[str, Any]:
    """One spec struct's Draft 2020-12 document. The $schema URI is popped and
    re-appended so it sorts last even if a future msgspec emits its own (finding 5)."""
    doc = msgspec.json.schema(spec)
    doc.pop("$schema", None)
    doc["$schema"] = _DRAFT_2020_12
    return doc


def _schema_text(spec: type[Struct]) -> str:
    """_schema_doc(spec) as deterministic, newline-terminated UTF-8 JSON."""
    return json.dumps(_schema_doc(spec), indent=2, ensure_ascii=False) + "\n"


def json_schema() -> dict[str, Any]:
    """The dataset VPlot JSON Schema, Draft 2020-12 — an ADVISORY mirror of decode_spec,
    not the gate. JSON Schema's `integer` admits zero-fraction floats (1.0, 1e3) that
    strict decode rejects and cannot express the float-token rejection, so the schema is
    slightly more permissive; decode_spec is authoritative."""
    return _schema_doc(VPlotSpec)


def json_schema_text() -> str:
    """json_schema() as deterministic, newline-terminated UTF-8 JSON — the
    byte-exact form committed as schema/vplot-0.1.schema.json."""
    return _schema_text(VPlotSpec)


def formula_json_schema() -> dict[str, Any]:
    """The formula VPlot JSON Schema, Draft 2020-12 — ADVISORY exactly like json_schema():
    decode_formula_spec stays authoritative, and formula semantics (grammar, domain
    ordering, sample distinctness) are verifier checks no JSON Schema can express."""
    return _schema_doc(FormulaPlotSpec)


def formula_json_schema_text() -> str:
    """formula_json_schema() as deterministic, newline-terminated UTF-8 JSON — the
    byte-exact form committed as schema/vplot-formula-0.1.schema.json."""
    return _schema_text(FormulaPlotSpec)
