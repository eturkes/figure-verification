# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic tests for the VPlot v0.1 schema gate (fuzz lives in the property suite).

Asserts: a full spec decodes to a typed, total object; every documented error
layer raises at decode; duplicate keys are rejected; specs are frozen + hashable
and kw-only; every struct is frozen + fail-closed by introspection; the golden
schema is Draft-2020-12 valid and byte-equals the committed file.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import msgspec
import pytest
from jsonschema import Draft202012Validator

from verifier import schema
from verifier.schema import Filter, VPlotSpec, decode_spec, json_schema, json_schema_text

HASH = "sha256:" + "0" * 64

# Every concrete struct (the union members + composites); _Base is abstract config.
_STRUCTS: list[type[msgspec.Struct]] = [
    schema.Channel,
    schema.Encoding,
    schema.Dataset,
    schema.Select,
    schema.Filter,
    schema.GroupBy,
    schema.Measure,
    schema.Aggregate,
    schema.SortKey,
    schema.Sort,
    schema.VPlotSpec,
    schema.FormulaXChannel,
    schema.FormulaYChannel,
    schema.FormulaEncoding,
    schema.FormulaDomain,
    schema.FormulaPlotSpec,
]


def _enc(d: dict[str, Any]) -> bytes:
    return msgspec.json.encode(d)


def _good() -> dict[str, Any]:
    """A fresh, fully populated valid spec dict (every transform op, color set)."""
    return {
        "version": "vplot-0.1",
        "dataset": {"name": "sales.csv", "hash": HASH},
        "transform": [
            {"op": "select", "fields": ["region", "revenue"]},
            {"op": "filter", "field": "region", "cmp": "eq", "value": "West"},
            {"op": "group_by", "keys": ["region"]},
            {"op": "aggregate", "measures": [{"field": "revenue", "fn": "sum", "as": "total"}]},
            {"op": "sort", "by": [{"field": "total", "order": "descending"}]},
        ],
        "mark": "bar",
        "encoding": {
            "x": {"field": "region", "type": "nominal"},
            "y": {"field": "total", "type": "quantitative"},
            "color": {"field": "region", "type": "nominal"},
        },
    }


def _with_transform(t: list[dict[str, Any]]) -> bytes:
    return _enc(_good() | {"transform": t})


def _filter(value: Any) -> bytes:
    return _with_transform([{"op": "filter", "field": "x", "cmp": "gt", "value": value}])


def _select(fields: list[Any]) -> bytes:
    return _with_transform([{"op": "select", "fields": fields}])


def _dataset(name: str, hash_: str) -> bytes:
    return _enc(_good() | {"dataset": {"name": name, "hash": hash_}})


def _bad_encoding(x: dict[str, Any]) -> bytes:
    """Spec with a tampered x-channel dict and a valid y, for channel-level rejects."""
    y = {"field": "total", "type": "quantitative"}
    return _enc(_good() | {"encoding": {"x": x, "y": y}})


def _formula() -> dict[str, Any]:
    """A fresh shape-valid formula spec dict."""
    return {
        "version": "vplot-formula-0.1",
        "formula": "x",
        "domain": {"start": "0", "stop": "1", "samples": 2, "x_scale": 0, "y_scale": 0},
        "numeric_profile": "rational-half-even-v1",
        "mark": "line",
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }


def _formula_top(**changes: Any) -> dict[str, Any]:
    raw = _formula()
    raw.update(changes)
    return raw


def _formula_domain(**changes: Any) -> dict[str, Any]:
    raw = _formula()
    domain = cast("dict[str, Any]", raw["domain"])
    domain.update(changes)
    return raw


def _formula_channel(channel: str, **changes: Any) -> dict[str, Any]:
    raw = _formula()
    encoding = cast("dict[str, Any]", raw["encoding"])
    selected = cast("dict[str, Any]", encoding[channel])
    selected.update(changes)
    return raw


def _formula_without_domain() -> dict[str, Any]:
    raw = _formula()
    del raw["domain"]
    return raw


type FormulaCase = tuple[str, str, str, int, int, int, str]


def _formula_case(case: FormulaCase) -> dict[str, Any]:
    formula, start, stop, samples, x_scale, y_scale, mark = case
    raw = _formula_top(formula=formula, mark=mark)
    domain = cast("dict[str, Any]", raw["domain"])
    domain.update(
        start=start,
        stop=stop,
        samples=samples,
        x_scale=x_scale,
        y_scale=y_scale,
    )
    return raw


_FORMULA_GOOD_CASES: list[FormulaCase] = [
    ("x**2", "-3", "3", 13, 1, 2, "line"),
    ("2*x + 1", "0", "10", 11, 0, 0, "line"),
    ("x*(x - 1)*(x + 1)", "-2", "2", 21, 1, 3, "scatter"),
    ("1/(1 + x*x)", "-5", "5", 41, 1, 4, "line"),
    ("abs(x)", "-4", "4", 17, 1, 1, "line"),
    ("-x**2 + 3*x - 2", "0", "3", 7, 1, 2, "scatter"),
]
_FORMULA_GOOD_IDS = ["square", "linear", "cubic", "rational", "absolute", "quadratic"]
_FORMULA_BYTES = _enc(_formula())
_FORMULA_DUP_MARK = _FORMULA_BYTES.replace(b'"mark":"line"', b'"mark":"line","mark":"scatter"', 1)
_FORMULA_REJECTS: dict[str, tuple[bytes, str]] = {
    "wrong_version": (_enc(_formula_top(version="vplot-formula-0.2")), "$.version"),
    "dataset_key": (
        _enc(_formula_top(dataset={"name": "sales.csv", "hash": HASH})),
        "unknown field `dataset`",
    ),
    "bar_mark": (_enc(_formula_top(mark="bar")), "$.mark"),
    "wrong_y_field": (_enc(_formula_channel("y", field="z")), "$.encoding.y.field"),
    "wrong_x_type": (_enc(_formula_channel("x", type="ordinal")), "$.encoding.x.type"),
    "code_injection_alphabet": (
        _enc(_formula_top(formula="__import__('os').system('ls')")),
        "$.formula",
    ),
    "formula_newline": (_enc(_formula_top(formula="x\n+1")), "$.formula"),
    "samples_below_min": (_enc(_formula_domain(samples=1)), "$.domain.samples"),
    "numeric_start_token": (_enc(_formula_domain(start=0)), "$.domain.start"),
    "negative_x_scale": (_enc(_formula_domain(x_scale=-1)), "$.domain.x_scale"),
    "numeric_profile": (_enc(_formula_top(numeric_profile="float64")), "$.numeric_profile"),
    "duplicate_mark": (_FORMULA_DUP_MARK, "duplicate object key: 'mark'"),
    "exponent_decimal": (_enc(_formula_domain(stop="1e3")), "$.domain.stop"),
    "missing_domain": (_enc(_formula_without_domain()), "required field `domain`"),
}


_GOOD_BYTES = _enc(_good())
# Inject a duplicate key with a CONFLICTING but individually-valid value: msgspec decodes
# it silently (last-wins), so only decode_spec's rescan rejects the resulting ambiguity.
_DUP_TOP = _GOOD_BYTES.replace(b'"mark":"bar"', b'"mark":"bar","mark":"line"', 1)
_DUP_NESTED = _GOOD_BYTES.replace(
    b'"name":"sales.csv"', b'"name":"sales.csv","name":"other.csv"', 1
)

# Each raw input must raise ValidationError at decode, tagged by the layer it breaks.
_REJECTS: dict[str, bytes] = {
    "unknown_top_field": _enc(_good() | {"bogus": 1}),
    "unknown_mark": _enc(_good() | {"mark": "pie"}),
    "unknown_op": _with_transform([{"op": "drop", "fields": ["x"]}]),
    "unknown_agg_fn": _with_transform(
        [{"op": "aggregate", "measures": [{"field": "x", "fn": "median", "as": "m"}]}]
    ),
    "unknown_channel_type": _bad_encoding({"field": "region", "type": "categorical"}),
    "unknown_cmp": _with_transform([{"op": "filter", "field": "x", "cmp": "==", "value": 1}]),
    "float_value": _filter(1.5),
    "bool_value": _with_transform([{"op": "filter", "field": "x", "cmp": "gt", "value": True}]),
    "null_value": _filter(None),
    "wrong_version": _enc(_good() | {"version": "vplot-0.2"}),
    "bad_field_pattern": _select(["1bad"]),
    "field_name_too_long": _select(["a" * 65]),
    "empty_fields": _select([]),
    "too_many_transforms": _with_transform([{"op": "select", "fields": ["x"]}] * 65),
    "trailing_newline_field": _select(["x\n"]),
    "control_char_field": _select(["x\ty"]),
    "newline_dataset_name": _dataset("a\n.csv", HASH),
    "bad_dataset_name": _dataset("noext", HASH),
    "bad_hash": _dataset("sales.csv", "sha256:zz"),
    "trailing_newline_hash": _dataset("sales.csv", HASH + "\n"),
    "int_value_overflows_int64": _filter(2**63),  # le = 2**63 - 1
    # Structural contract guards: missing required field, missing tag, wrong container
    # types, the un-renamed Python keys behind type/as, and empty min-length tuples.
    "missing_required_field": _enc({k: v for k, v in _good().items() if k != "mark"}),
    "missing_op_tag": _with_transform([{"fields": ["x"]}]),
    "transform_not_array": _enc(_good() | {"transform": {}}),
    "select_fields_not_array": _with_transform([{"op": "select", "fields": "x"}]),
    "channel_uses_kind_not_type": _bad_encoding({"field": "region", "kind": "nominal"}),
    "measure_uses_output_not_as": _with_transform(
        [{"op": "aggregate", "measures": [{"field": "x", "fn": "sum", "output": "m"}]}]
    ),
    "empty_keys": _with_transform([{"op": "group_by", "keys": []}]),
    "empty_measures": _with_transform([{"op": "aggregate", "measures": []}]),
    "empty_by": _with_transform([{"op": "sort", "by": []}]),
}


def test_full_spec_decodes_to_typed_total_object() -> None:
    spec = decode_spec(_GOOD_BYTES)
    assert isinstance(spec, VPlotSpec)
    assert spec.version == "vplot-0.1"
    assert [type(t).__name__ for t in spec.transform] == [
        "Select",
        "Filter",
        "GroupBy",
        "Aggregate",
        "Sort",
    ]
    assert spec.encoding.color is not None


def test_minimal_spec_decodes() -> None:
    """Empty transform and an omitted optional color both decode (default applied)."""
    raw = _enc(
        {
            "version": "vplot-0.1",
            "dataset": {"name": "a.csv", "hash": HASH},
            "transform": [],
            "mark": "line",
            "encoding": {
                "x": {"field": "a", "type": "temporal"},
                "y": {"field": "b", "type": "quantitative"},
            },
        }
    )
    spec = decode_spec(raw)
    assert spec.transform == ()
    assert spec.encoding.color is None


def test_numeric_string_filter_value_decodes() -> None:
    """A numeric STRING value is syntactically valid; its numeric sense is an eval check."""
    spec = decode_spec(_filter("1.2"))
    t = spec.transform[0]
    assert isinstance(t, Filter)
    assert t.value == "1.2"


def test_integer_filter_value_within_int64_decodes() -> None:
    """An int filter literal at the upper int64 boundary decodes (2**63 is rejected)."""
    spec = decode_spec(_filter(2**63 - 1))
    t = spec.transform[0]
    assert isinstance(t, Filter)
    assert t.value == 2**63 - 1


@pytest.mark.parametrize("raw", _REJECTS.values(), ids=list(_REJECTS))
def test_decode_rejects_invalid(raw: bytes) -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(raw)


@pytest.mark.parametrize("raw", [_DUP_TOP, _DUP_NESTED], ids=["top", "nested"])
def test_duplicate_key_rejected(raw: bytes) -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(raw)


def test_duplicate_key_would_silently_pass_a_bare_decoder() -> None:
    """The rescan is load-bearing: a bare msgspec decoder last-wins on a duplicate key,
    accepting the conflicting value (mark, dataset name) decode_spec rejects."""
    bare = msgspec.json.Decoder(VPlotSpec)
    assert bare.decode(_DUP_TOP).mark == "line"
    assert bare.decode(_DUP_NESTED).dataset.name == "other.csv"


def test_malformed_json_raises_decode_error() -> None:
    with pytest.raises(msgspec.DecodeError):
        decode_spec(b"{ not json")


@pytest.mark.parametrize("raw", [b"[]", b"42", b'"x"', b"true", b"null"])
def test_non_object_input_rejected(raw: bytes) -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(raw)


def test_str_input_is_normalized_and_decodes() -> None:
    """A str spec is normalized to UTF-8 bytes and decodes like its bytes form."""
    spec = decode_spec(_GOOD_BYTES.decode("utf-8"))
    assert isinstance(spec, VPlotSpec)


def test_lone_surrogate_str_maps_to_decode_error() -> None:
    """An unencodable str (lone surrogate) raises DecodeError, not UnicodeEncodeError."""
    with pytest.raises(msgspec.DecodeError):
        decode_spec(chr(0xD800))


def test_invalid_utf8_bytes_maps_to_decode_error() -> None:
    """Invalid UTF-8 inside a JSON string raises DecodeError, not UnicodeDecodeError."""
    with pytest.raises(msgspec.DecodeError):
        decode_spec(b'{"version":"\xff\xfe"}')


@pytest.mark.parametrize("case", _FORMULA_GOOD_CASES, ids=_FORMULA_GOOD_IDS)
def test_formula_good_specs_decode_to_declared_fields(case: FormulaCase) -> None:
    formula, start, stop, samples, x_scale, y_scale, mark = case
    spec = schema.decode_formula_spec(_enc(_formula_case(case)))
    assert isinstance(spec, schema.FormulaPlotSpec)
    assert spec.version == "vplot-formula-0.1"
    assert spec.formula == formula
    assert (spec.domain.start, spec.domain.stop) == (start, stop)
    assert (spec.domain.samples, spec.domain.x_scale, spec.domain.y_scale) == (
        samples,
        x_scale,
        y_scale,
    )
    assert spec.numeric_profile == "rational-half-even-v1"
    assert spec.mark == mark
    assert (spec.encoding.x.field, spec.encoding.x.kind) == ("x", "quantitative")
    assert (spec.encoding.y.field, spec.encoding.y.kind) == ("y", "quantitative")


@pytest.mark.parametrize(
    "raw",
    [_FORMULA_BYTES, _FORMULA_BYTES.decode("utf-8")],
    ids=["bytes", "str"],
)
def test_formula_decode_accepts_bytes_and_str(raw: bytes | str) -> None:
    assert schema.decode_formula_spec(raw).formula == "x"


@pytest.mark.parametrize(
    ("raw", "message"),
    _FORMULA_REJECTS.values(),
    ids=list(_FORMULA_REJECTS),
)
def test_formula_decode_rejects_invalid_shape(raw: bytes, message: str) -> None:
    with pytest.raises(msgspec.ValidationError) as exc_info:
        schema.decode_formula_spec(raw)
    assert type(exc_info.value) is msgspec.ValidationError
    assert message in str(exc_info.value)


def test_formula_duplicate_key_would_silently_pass_a_bare_decoder() -> None:
    bare = msgspec.json.Decoder(schema.FormulaPlotSpec)
    assert bare.decode(_FORMULA_DUP_MARK).mark == "scatter"
    with pytest.raises(msgspec.ValidationError, match="duplicate object key"):
        schema.decode_formula_spec(_FORMULA_DUP_MARK)


@pytest.mark.parametrize(
    "raw",
    [b"{ not json", chr(0xD800), b'{"version":"\xff"}'],
    ids=["malformed", "lone-surrogate-str", "invalid-utf8-bytes"],
)
def test_formula_decode_maps_malformed_or_non_utf8_to_decode_error(raw: bytes | str) -> None:
    with pytest.raises(msgspec.DecodeError) as exc_info:
        schema.decode_formula_spec(raw)
    assert type(exc_info.value) is msgspec.DecodeError


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("samples", 2),
        ("samples", 100_000),
        ("x_scale", 0),
        ("x_scale", 12),
        ("y_scale", 0),
        ("y_scale", 12),
    ],
)
def test_formula_domain_inclusive_boundaries_decode(field: str, value: int) -> None:
    raw = _formula()
    domain = cast("dict[str, Any]", raw["domain"])
    domain[field] = value
    spec = schema.decode_formula_spec(_enc(raw))
    assert getattr(spec.domain, field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("samples", 1),
        ("samples", 100_001),
        ("x_scale", -1),
        ("x_scale", 13),
        ("y_scale", -1),
        ("y_scale", 13),
    ],
)
def test_formula_domain_boundary_plus_one_rejected(field: str, value: int) -> None:
    raw = _formula()
    domain = cast("dict[str, Any]", raw["domain"])
    domain[field] = value
    with pytest.raises(msgspec.ValidationError):
        schema.decode_formula_spec(_enc(raw))


def test_formula_text_max_length_decodes() -> None:
    formula = "x" * 1024
    assert schema.decode_formula_spec(_enc(_formula_top(formula=formula))).formula == formula


def test_formula_text_boundary_plus_one_rejected() -> None:
    with pytest.raises(msgspec.ValidationError, match="length <= 1024"):
        schema.decode_formula_spec(_enc(_formula_top(formula="x" * 1025)))


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "-0",
        "9" * 18,
        "-" + "9" * 18,
        "1." + "2" * 9,
        "9" * 18 + "." + "9" * 9,
        "-" + "9" * 18 + "." + "9" * 9,
    ],
    ids=[
        "zero",
        "negative-zero",
        "18-integer",
        "negative-18-integer",
        "9-fraction",
        "both-max",
        # 29 characters: the longest token the grammar admits, which is why DecimalText
        # carries no max_length — a cap could never bind before the pattern does.
        "longest-token",
    ],
)
def test_formula_decimal_text_digit_boundaries_decode(value: str) -> None:
    spec = schema.decode_formula_spec(_enc(_formula_domain(start=value)))
    assert spec.domain.start == value


@pytest.mark.parametrize(
    "value",
    ["9" * 19, "0." + "1" * 10],
    ids=["19-integer", "10-fraction"],
)
def test_formula_decimal_text_boundary_plus_one_rejected(value: str) -> None:
    with pytest.raises(msgspec.ValidationError):
        schema.decode_formula_spec(_enc(_formula_domain(start=value)))


# One case per lexical rule the DecimalText grammar claims. Without these, a pattern
# loosened to accept a leading plus, leading zeroes, or a bare/trailing point still passes
# every other decimal vector, so the claimed canonical spelling would go unenforced.
@pytest.mark.parametrize(
    "value",
    ["+1", "01", "-01", "00", "1.", ".1", "-.1", "1_000", " 1", "1 ", "--1", "-", ""],
    ids=[
        "leading-plus",
        "leading-zero",
        "negative-leading-zero",
        "double-zero",
        "trailing-point",
        "bare-fraction",
        "negative-bare-fraction",
        "digit-separator",
        "leading-space",
        "trailing-space",
        "double-sign",
        "sign-only",
        "empty",
    ],
)
def test_formula_decimal_text_rejects_non_canonical_spellings(value: str) -> None:
    with pytest.raises(msgspec.ValidationError, match=r"\$\.domain\.start"):
        schema.decode_formula_spec(_enc(_formula_domain(start=value)))


# The closed alphabet IS the claim that code-injection shapes are unrepresentable at
# decode, so pin it character by character: a class widened by even one of these passes
# every good spec, every bad-corpus entry, and both length-boundary vectors.
@pytest.mark.parametrize(
    "char",
    [
        ",",
        "'",
        '"',
        ";",
        "^",
        "=",
        "[",
        "]",
        "{",
        "}",
        "\\",
        ":",
        "!",
        "<",
        ">",
        "#",
        "?",
        "|",
        "&",
        "$",
        "%",
        "@",
        "~",
        "`",
        "\r",
        "\n",
        "\t",
        "\x00",
        "é",
    ],
)
def test_formula_text_rejects_every_excluded_character(char: str) -> None:
    with pytest.raises(msgspec.ValidationError, match=r"\$\.formula"):
        schema.decode_formula_spec(_enc(_formula_top(formula=f"x + 1{char}")))


def test_plot_spec_aliases_accept_both_modes() -> None:
    dataset: schema.DatasetPlotSpec = decode_spec(_GOOD_BYTES)
    formula: schema.FormulaPlotSpec = schema.decode_formula_spec(_FORMULA_BYTES)
    specs: tuple[schema.PlotSpec, ...] = (dataset, formula)
    assert [spec.version for spec in specs] == ["vplot-0.1", "vplot-formula-0.1"]


def test_formula_spec_is_frozen_hashable_and_deeply_immutable() -> None:
    spec = schema.decode_formula_spec(_FORMULA_BYTES)
    assert hash(spec) == hash(schema.decode_formula_spec(_FORMULA_BYTES))
    attr = "formula"
    with pytest.raises(AttributeError):
        setattr(spec, attr, "x + 1")
    nested_attr = "samples"
    with pytest.raises(AttributeError):
        setattr(spec.domain, nested_attr, 3)


def test_spec_is_frozen_hashable_and_deeply_immutable() -> None:
    spec = decode_spec(_GOOD_BYTES)
    assert hash(spec) == hash(decode_spec(_GOOD_BYTES))  # value-hashed across two decodes
    assert isinstance(spec.transform, tuple)  # JSON arrays decode to tuples, not lists
    select = spec.transform[0]
    assert isinstance(select, schema.Select)
    assert isinstance(select.fields, tuple)  # nested array is a tuple too
    attr = "mark"  # variable name dodges B010 while exercising the frozen guard
    with pytest.raises(AttributeError):
        setattr(spec, attr, "line")
    nested_attr = "fields"  # a nested struct is frozen too, not only the root
    with pytest.raises(AttributeError):
        setattr(select, nested_attr, ())


@pytest.mark.parametrize("struct", _STRUCTS, ids=lambda s: s.__name__)
def test_positional_construction_rejected(struct: type[msgspec.Struct]) -> None:
    ctor = cast("Callable[..., object]", struct)  # kw_only → any positional arg raises
    with pytest.raises(TypeError):
        ctor("x")


@pytest.mark.parametrize("struct", _STRUCTS, ids=lambda s: s.__name__)
def test_structs_are_frozen_and_fail_closed(struct: type[msgspec.Struct]) -> None:
    cfg = struct.__struct_config__
    assert cfg.frozen
    assert cfg.forbid_unknown_fields


def test_golden_schema_is_draft_2020_12_valid_and_byte_stable() -> None:
    Draft202012Validator.check_schema(json_schema())  # raises if not a valid 2020-12 schema
    golden_path = Path(__file__).resolve().parent.parent / "schema" / "vplot-0.1.schema.json"
    assert golden_path.read_bytes() == json_schema_text().encode("utf-8")  # byte-exact
