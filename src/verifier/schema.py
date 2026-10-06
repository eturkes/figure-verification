# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""VPlot v0.1 / v0.2 schemas — the restricted chart specs the untrusted model proposes.

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
import re
from typing import Annotated, Any, Literal, cast, get_args

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
_FORMULA_TEXT_PATTERN = r"^(?!.*[\r\n])[0-9A-Za-z_ ().*/+-]+$"
_FORMULA_TEXT_MAX_LENGTH = 1024
FormulaText = Annotated[
    str, Meta(pattern=_FORMULA_TEXT_PATTERN, max_length=_FORMULA_TEXT_MAX_LENGTH)
]
# Domain endpoints are bounded decimal STRINGS, never JSON floats: no exponent, leading
# plus/zeroes, or trailing point; at most 18 integer and 9 fractional digits. The grammar
# is self-bounding at 29 characters (sign + 18 + point + 9), so unlike FieldName/DatasetName
# — whose patterns are unbounded — this alias carries NO max_length: a cap here could never
# bind, and dead policy reads as tested policy.
_DECIMAL_TEXT_PATTERN = r"^(?!.*[\r\n])-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,9})?$"
DecimalText = Annotated[str, Meta(pattern=_DECIMAL_TEXT_PATTERN)]

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
FormulaVersion = Literal["vplot-formula-0.1"]
FormulaXField = Literal["x"]
FormulaYField = Literal["y"]
FormulaChannelType = Literal["quantitative"]
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


# --- formula direct-construction closure (finding 10) --------------------------
# Literal + Meta bind DECODE only. Each formula struct therefore re-checks its own fields in
# __post_init__, which msgspec also runs on decode and on msgspec.structs.replace, and refuses
# an undeclared subclass: its extra fields reach the deterministic encoder, and strict decode
# then refuses those bytes. Shape only; formula meaning stays in the semantic checks.
_FORMULA_TEXT_RE = re.compile(_FORMULA_TEXT_PATTERN)
_DECIMAL_TEXT_RE = re.compile(_DECIMAL_TEXT_PATTERN)


def _require_declared(instance: Struct, declared: type[Struct]) -> None:
    if type(instance) is not declared:
        msg = f"{type(instance).__name__} is not the declared {declared.__name__}"
        raise ValueError(msg)


def _require_member(value: object, alias: object, field: str) -> None:
    allowed = get_args(alias)
    if type(value) is not str or value not in allowed:
        msg = f"{field} must be one of {allowed}"
        raise ValueError(msg)


def _require_int(value: object, low: int, high: int, field: str) -> None:
    if type(value) is not int or not low <= value <= high:
        msg = f"{field} must be an int in [{low}, {high}]"
        raise ValueError(msg)


def _require_text(value: object, pattern: re.Pattern[str], field: str) -> None:
    # msgspec applies a Meta pattern with re.search; the patterns anchor themselves.
    if type(value) is not str or pattern.search(value) is None:
        msg = f"{field} does not match its declared pattern"
        raise ValueError(msg)


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
    field: FormulaXField
    kind: FormulaChannelType = msgspec.field(name="type")

    def __post_init__(self) -> None:
        _require_declared(self, FormulaXChannel)
        _require_member(self.field, FormulaXField, "field")
        _require_member(self.kind, FormulaChannelType, "type")


class FormulaYChannel(_Base, frozen=True, kw_only=True):
    field: FormulaYField
    kind: FormulaChannelType = msgspec.field(name="type")

    def __post_init__(self) -> None:
        _require_declared(self, FormulaYChannel)
        _require_member(self.field, FormulaYField, "field")
        _require_member(self.kind, FormulaChannelType, "type")


class FormulaEncoding(_Base, frozen=True, kw_only=True):
    x: FormulaXChannel
    y: FormulaYChannel

    def __post_init__(self) -> None:
        _require_declared(self, FormulaEncoding)
        _require_declared(self.x, FormulaXChannel)
        _require_declared(self.y, FormulaYChannel)


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


class Derive(_Base, frozen=True, kw_only=True, tag_field="op", tag="derive"):
    """vplot-0.2 (Q3): one computed numeric column, `expr` in the shared expr-0.1 grammar over the
    running table's numeric columns, quantized once HALF_EVEN at `scale`. Meaning =
    VPlot_SEMANTICS.md section 3; this gate checks shape only."""

    expr: FormulaText
    output: FieldName = msgspec.field(name="as")  # JSON key `as` (a keyword)
    scale: Annotated[int, Meta(ge=0, le=12)]


Transform = Select | Filter | GroupBy | Aggregate | Sort
# vplot-0.2 widens the union by `derive` alone; vplot-0.1 keeps its own, so a v0.1 spec cannot
# carry a derive and the proposer's pinned v0.1 schema never moves (verifier-only first).
TransformV02 = Select | Filter | GroupBy | Aggregate | Sort | Derive


# --- top-level spec ----------------------------------------------------------
# Arrays are bounded tuples, not lists (finding 7): deeply immutable + hashable.
class VPlotSpec(_Base, frozen=True, kw_only=True):
    version: Literal["vplot-0.1"]
    dataset: Dataset
    transform: Annotated[tuple[Transform, ...], Meta(max_length=64)]
    mark: Mark
    encoding: Encoding


class VPlotSpecV02(_Base, frozen=True, kw_only=True):
    """vplot-0.2: vplot-0.1 plus the `derive` transform; every other member is identical."""

    version: Literal["vplot-0.2"]
    dataset: Dataset
    transform: Annotated[tuple[TransformV02, ...], Meta(max_length=64)]
    mark: Mark
    encoding: Encoding


# Shape only: ordering, representability, grammar, names/functions/exponents, and sample
# distinctness are formula semantic checks, never Struct post-init validation. The post-init
# re-checks the decode shape alone (finding 10).
_MIN_SAMPLES = 2
_MAX_SAMPLES = 100_000
_MAX_SCALE = 12


class FormulaDomain(_Base, frozen=True, kw_only=True):
    start: DecimalText
    stop: DecimalText
    samples: Annotated[int, Meta(ge=_MIN_SAMPLES, le=_MAX_SAMPLES)]
    x_scale: Annotated[int, Meta(ge=0, le=_MAX_SCALE)]
    y_scale: Annotated[int, Meta(ge=0, le=_MAX_SCALE)]

    def __post_init__(self) -> None:
        _require_declared(self, FormulaDomain)
        _require_text(self.start, _DECIMAL_TEXT_RE, "start")
        _require_text(self.stop, _DECIMAL_TEXT_RE, "stop")
        _require_int(self.samples, _MIN_SAMPLES, _MAX_SAMPLES, "samples")
        _require_int(self.x_scale, 0, _MAX_SCALE, "x_scale")
        _require_int(self.y_scale, 0, _MAX_SCALE, "y_scale")


class FormulaPlotSpec(_Base, frozen=True, kw_only=True):
    version: FormulaVersion
    formula: FormulaText
    domain: FormulaDomain
    numeric_profile: NumericProfile
    mark: FormulaMark
    encoding: FormulaEncoding

    def __post_init__(self) -> None:
        _require_declared(self, FormulaPlotSpec)
        _require_member(self.version, FormulaVersion, "version")
        _require_text(self.formula, _FORMULA_TEXT_RE, "formula")
        if len(self.formula) > _FORMULA_TEXT_MAX_LENGTH:
            msg = f"formula exceeds {_FORMULA_TEXT_MAX_LENGTH} characters"
            raise ValueError(msg)
        _require_declared(self.domain, FormulaDomain)
        _require_member(self.numeric_profile, NumericProfile, "numeric_profile")
        _require_member(self.mark, FormulaMark, "mark")
        _require_declared(self.encoding, FormulaEncoding)


type DatasetPlotSpec = VPlotSpec | VPlotSpecV02
type PlotSpec = VPlotSpec | VPlotSpecV02 | FormulaPlotSpec


# One module-level strict decoder per external shape (strict is msgspec's default;
# pinned explicitly because fail-closed decode is the whole contract of these gates).
_DECODER = msgspec.json.Decoder(VPlotSpec, strict=True)
_DECODER_V02 = msgspec.json.Decoder(VPlotSpecV02, strict=True)
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


class _VersionProbe(Struct, frozen=True):
    """Reads the `version` member alone; every other member is ignored here and decoded strictly
    by the decoder it selects. Typed `str | None`, so a non-string version fails at once."""

    version: str | None = None


_VERSION_PROBE = msgspec.json.Decoder(_VersionProbe)


def _dataset_decoder(
    raw: bytes | str,
) -> msgspec.json.Decoder[VPlotSpec] | msgspec.json.Decoder[VPlotSpecV02]:
    """`vplot-0.2` selects the v0.2 decoder; anything else -- malformed JSON, a missing or unknown
    version -- takes the v0.1 decoder, whose strict decode then reports the fault. Skipping an
    unknown member, the lenient probe recurses where the strict decoders refuse at once, so a
    deeply nested body also falls through to them (closing review S17)."""
    try:
        probe = _VERSION_PROBE.decode(raw)
    except (msgspec.DecodeError, msgspec.ValidationError, UnicodeError, RecursionError):
        return _DECODER
    return _DECODER_V02 if probe.version == "vplot-0.2" else _DECODER


def decode_spec(raw: bytes | str) -> DatasetPlotSpec:
    """Decode raw JSON into a validated VPlotSpec or VPlotSpecV02 (by `version`), or raise.

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
    decoder: msgspec.json.Decoder[DatasetPlotSpec] = cast(
        "msgspec.json.Decoder[DatasetPlotSpec]", _dataset_decoder(raw)
    )
    return _decode(raw, decoder)


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


def json_schema_v02() -> dict[str, Any]:
    """The vplot-0.2 JSON Schema, ADVISORY exactly like json_schema(). No proposer is pinned to
    it: the proposer keeps vplot-0.1 (verifier-only first)."""
    return _schema_doc(VPlotSpecV02)


def json_schema_v02_text() -> str:
    """json_schema_v02() as deterministic, newline-terminated UTF-8 JSON — the byte-exact form
    committed as schema/vplot-0.2.schema.json."""
    return _schema_text(VPlotSpecV02)


def formula_json_schema() -> dict[str, Any]:
    """The formula VPlot JSON Schema, Draft 2020-12 — ADVISORY exactly like json_schema():
    decode_formula_spec stays authoritative, and formula semantics (grammar, domain
    ordering, sample distinctness) are verifier checks no JSON Schema can express."""
    return _schema_doc(FormulaPlotSpec)


def formula_json_schema_text() -> str:
    """formula_json_schema() as deterministic, newline-terminated UTF-8 JSON — the
    byte-exact form committed as schema/vplot-formula-0.1.schema.json."""
    return _schema_text(FormulaPlotSpec)
