# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Property + fuzz tests for the VPlot v0.1 schema gate (deterministic cases: test_schema).

The contract under test (VPlot_SEMANTICS.md §9): decode_spec is decode-or-raise, never
partial. For ANY input it returns a fully typed VPlotSpec or raises ONLY ValidationError /
DecodeError. Properties:
  - arbitrary bytes / text / JSON never yield a partial or coerced object;
  - a generated schema-valid spec decodes, and decode is a fixed point of encode-then-decode;
  - a JSON float anywhere a FilterValue sits is rejected at decode (finding 3);
  - json_schema_text() is byte-identical across PYTHONHASHSEED (golden determinism, subprocess).
"""

import os
import string
import subprocess
import sys
from pathlib import Path
from typing import Any

import msgspec
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

from verifier.schema import VPlotSpec, decode_spec

# decode_spec's entire failure surface for bytes|str input (anything else = a contract breach).
_DECODE_ERRORS = (msgspec.ValidationError, msgspec.DecodeError)

# --- valid-component strategies (mirror the schema's constrained aliases) -----------------
_FIELD_FIRST = string.ascii_letters + "_"
_FIELD_CHARS = string.ascii_letters + string.digits + "_"
_DS_FIRST = string.ascii_letters + string.digits
_DS_CHARS = _DS_FIRST + "._-"
_HEX = "0123456789abcdef"
_MARKS = ("bar", "line", "scatter")
_CHANNEL_TYPES = ("quantitative", "temporal", "ordinal", "nominal")
_AGG_FNS = ("sum", "mean", "count", "min", "max")
_CMP_OPS = ("eq", "ne", "lt", "le", "gt", "ge")
_SORT_ORDERS = ("ascending", "descending")

# int64-bounded ints + UTF-8-safe bounded strings = the two valid FilterValue arms.
_INT64 = st.integers(min_value=-(2**63), max_value=2**63 - 1)
_VALUE_TEXT = st.text(st.characters(codec="utf-8"), max_size=128)
_FILTER_VALUES: SearchStrategy[int | str] = _INT64 | _VALUE_TEXT


@st.composite
def _field_names(draw: DrawFn) -> str:
    """^[A-Za-z_][A-Za-z0-9_]*$, length 1..64."""
    return draw(st.sampled_from(_FIELD_FIRST)) + draw(st.text(alphabet=_FIELD_CHARS, max_size=63))


@st.composite
def _dataset_names(draw: DrawFn) -> str:
    """^[A-Za-z0-9][A-Za-z0-9._-]*\\.csv$, length ≤128 (1 + ≤123 + 4)."""
    return (
        draw(st.sampled_from(_DS_FIRST)) + draw(st.text(alphabet=_DS_CHARS, max_size=123)) + ".csv"
    )


@st.composite
def _dataset_hashes(draw: DrawFn) -> str:
    return "sha256:" + draw(st.text(alphabet=_HEX, min_size=64, max_size=64))


@st.composite
def _channels(draw: DrawFn) -> dict[str, str]:
    return {"field": draw(_field_names()), "type": draw(st.sampled_from(_CHANNEL_TYPES))}


def _measures() -> SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {"field": _field_names(), "fn": st.sampled_from(_AGG_FNS), "as": _field_names()}
    )


def _sort_keys() -> SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries({"field": _field_names(), "order": st.sampled_from(_SORT_ORDERS)})


def _transforms() -> SearchStrategy[dict[str, Any]]:
    return st.one_of(
        st.fixed_dictionaries(
            {"op": st.just("select"), "fields": st.lists(_field_names(), min_size=1, max_size=64)}
        ),
        st.fixed_dictionaries(
            {
                "op": st.just("filter"),
                "field": _field_names(),
                "cmp": st.sampled_from(_CMP_OPS),
                "value": _FILTER_VALUES,
            }
        ),
        st.fixed_dictionaries(
            {"op": st.just("group_by"), "keys": st.lists(_field_names(), min_size=1, max_size=32)}
        ),
        st.fixed_dictionaries(
            {"op": st.just("aggregate"), "measures": st.lists(_measures(), min_size=1, max_size=32)}
        ),
        st.fixed_dictionaries(
            {"op": st.just("sort"), "by": st.lists(_sort_keys(), min_size=1, max_size=32)}
        ),
    )


@st.composite
def _valid_spec_dicts(draw: DrawFn) -> dict[str, Any]:
    encoding: dict[str, Any] = {"x": draw(_channels()), "y": draw(_channels())}
    if draw(st.booleans()):
        encoding["color"] = draw(_channels())
    return {
        "version": "vplot-0.1",
        "dataset": {"name": draw(_dataset_names()), "hash": draw(_dataset_hashes())},
        "transform": draw(st.lists(_transforms(), max_size=64)),
        "mark": draw(st.sampled_from(_MARKS)),
        "encoding": encoding,
    }


# A minimal schema-valid spec: the explicit SUCCESS example for the decode-or-raise fuzz tests
# (whose random inputs realistically never form a valid spec) and the float-rejection base.
_BASE_SPEC: dict[str, Any] = {
    "version": "vplot-0.1",
    "dataset": {"name": "d.csv", "hash": "sha256:" + "0" * 64},
    "transform": [],
    "mark": "bar",
    "encoding": {
        "x": {"field": "a", "type": "nominal"},
        "y": {"field": "b", "type": "quantitative"},
    },
}
_BASE_SPEC_BYTES = msgspec.json.encode(_BASE_SPEC)


# --- never-partial: decode-or-raise over arbitrary input ----------------------------------
# Each fuzz test pins the SUCCESS leg with an explicit valid @example (findings 7/8: random
# bytes/text/JSON never realistically form a valid spec, so the VPlotSpec assertion would
# otherwise be unreached); the random inputs exercise the RAISE leg + never-partial.
@given(raw=st.binary(max_size=512))
@example(raw=_BASE_SPEC_BYTES)
def test_arbitrary_bytes_decode_or_raise(raw: bytes) -> None:
    try:
        spec = decode_spec(raw)
    except _DECODE_ERRORS:
        return
    assert type(spec) is VPlotSpec


@given(raw=st.text(max_size=512))
@example(raw=_BASE_SPEC_BYTES.decode("utf-8"))
def test_arbitrary_text_decode_or_raise(raw: str) -> None:
    """The str path (UTF-8 normalize, lone-surrogate → DecodeError) is decode-or-raise too."""
    try:
        spec = decode_spec(raw)
    except _DECODE_ERRORS:
        return
    assert type(spec) is VPlotSpec


_JSON_LEAVES = (
    st.none()
    | st.booleans()
    | st.integers()  # unbounded → exercises the int64 FilterValue bound
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(st.characters(codec="utf-8"), max_size=32)
)
_JSON_VALUES = st.recursive(
    _JSON_LEAVES,
    lambda children: (
        st.lists(children, max_size=8)
        | st.dictionaries(st.text(st.characters(codec="utf-8"), max_size=16), children, max_size=8)
    ),
    max_leaves=20,
)


@given(value=_JSON_VALUES)
@example(value=_BASE_SPEC)
def test_arbitrary_json_decode_or_raise(value: object) -> None:
    """Structurally-valid JSON that does not match the schema raises; never a partial object."""
    try:
        spec = decode_spec(msgspec.json.encode(value))
    except _DECODE_ERRORS:
        return
    assert type(spec) is VPlotSpec


# --- round-trip: decode is a fixed point of encode∘decode ---------------------------------
@given(spec_dict=_valid_spec_dicts())
def test_valid_spec_decodes_and_reencode_is_a_fixed_point(spec_dict: dict[str, Any]) -> None:
    """A generated schema-valid spec decodes to a VPlotSpec; re-encoding and decoding again
    yields an equal, equally-hashing value (decode never coerces away information — the M1.4
    canonical-hashing precondition)."""
    spec = decode_spec(msgspec.json.encode(spec_dict))
    assert type(spec) is VPlotSpec
    again = decode_spec(msgspec.json.encode(spec))
    assert spec == again
    assert hash(spec) == hash(again)


# --- float rejection (finding 3): no number slot admits a float token ---------------------
@given(value=st.floats(allow_nan=False, allow_infinity=False), cmp=st.sampled_from(_CMP_OPS))
def test_float_filter_value_rejected(value: float, cmp: str) -> None:
    """A JSON float where a FilterValue (int|str) sits is rejected at decode: strict mode
    admits neither float→int nor float→str. msgspec always emits a float token (2.0→`2.0`)."""
    raw = msgspec.json.encode(
        {**_BASE_SPEC, "transform": [{"op": "filter", "field": "a", "cmp": cmp, "value": value}]}
    )
    with pytest.raises(msgspec.ValidationError):
        decode_spec(raw)


# --- golden determinism across processes (memory: PYTHONHASHSEED subprocess check) --------
_GOLDEN = Path(__file__).resolve().parent.parent / "schema" / "vplot-0.1.schema.json"
_EMIT_GOLDEN = (
    "import sys; from verifier.schema import json_schema_text; "
    "sys.stdout.buffer.write(json_schema_text().encode('utf-8'))"
)


@pytest.mark.parametrize("seed", ["0", "1", "12345"])
def test_golden_schema_byte_identical_across_hash_seeds(seed: str) -> None:
    """json_schema_text() is byte-identical regardless of PYTHONHASHSEED (no set/dict hash
    ordering leaks into the golden), and equals the committed file across fresh processes."""
    proc = subprocess.run(  # noqa: S603 — fixed argv, sys.executable, trusted literal code
        [sys.executable, "-c", _EMIT_GOLDEN],
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )
    assert proc.stdout == _GOLDEN.read_bytes()
