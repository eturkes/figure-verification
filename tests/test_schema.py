# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic tests for the VPlot v0.1 schema gate (fuzz lives in M1.2b).

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


def _bad_x_type(type_: str) -> bytes:
    enc = {"x": {"field": "region", "type": type_}, "y": {"field": "total", "type": "quantitative"}}
    return _enc(_good() | {"encoding": enc})


_GOOD_BYTES = _enc(_good())
# Inject a duplicate key into otherwise-valid JSON (msgspec last-wins silently).
_DUP_TOP = _GOOD_BYTES.replace(
    b'"version":"vplot-0.1"', b'"version":"vplot-0.1","version":"vplot-0.1"', 1
)
_DUP_NESTED = _GOOD_BYTES.replace(
    b'"name":"sales.csv"', b'"name":"sales.csv","name":"sales.csv"', 1
)

# Each raw input must raise ValidationError at decode, tagged by the layer it breaks.
_REJECTS: dict[str, bytes] = {
    "unknown_top_field": _enc(_good() | {"bogus": 1}),
    "unknown_mark": _enc(_good() | {"mark": "pie"}),
    "unknown_op": _with_transform([{"op": "drop", "fields": ["x"]}]),
    "unknown_agg_fn": _with_transform(
        [{"op": "aggregate", "measures": [{"field": "x", "fn": "median", "as": "m"}]}]
    ),
    "unknown_channel_type": _bad_x_type("categorical"),
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
    """A numeric STRING value is syntactically valid; its numeric sense is an M1.4 check."""
    spec = decode_spec(_filter("1.2"))
    t = spec.transform[0]
    assert isinstance(t, Filter)
    assert t.value == "1.2"


@pytest.mark.parametrize("raw", _REJECTS.values(), ids=list(_REJECTS))
def test_decode_rejects_invalid(raw: bytes) -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(raw)


@pytest.mark.parametrize("raw", [_DUP_TOP, _DUP_NESTED], ids=["top", "nested"])
def test_duplicate_key_rejected(raw: bytes) -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(raw)


def test_malformed_json_raises_decode_error() -> None:
    with pytest.raises(msgspec.DecodeError):
        decode_spec(b"{ not json")


@pytest.mark.parametrize("raw", [b"[]", b"42", b'"x"', b"true", b"null"])
def test_non_object_input_rejected(raw: bytes) -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(raw)


def test_spec_is_frozen_and_hashable() -> None:
    spec = decode_spec(_GOOD_BYTES)
    assert hash(spec) == hash(decode_spec(_GOOD_BYTES))  # value-hashed → deeply immutable
    attr = "mark"  # variable name dodges B010 while exercising the frozen guard
    with pytest.raises(AttributeError):
        setattr(spec, attr, "line")


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
    assert json_schema_text() == golden_path.read_text(encoding="utf-8")
