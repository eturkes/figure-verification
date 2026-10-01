# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9 review reds for formula-contract direct-construction closure."""

from collections.abc import Callable
from typing import cast

import msgspec
import pytest

from verifier import schema

_FORMULA_BYTES = b"""{
  "version": "vplot-formula-0.1",
  "formula": "x",
  "domain": {"start": "0", "stop": "1", "samples": 2, "x_scale": 0, "y_scale": 0},
  "numeric_profile": "rational-half-even-v1",
  "mark": "line",
  "encoding": {
    "x": {"field": "x", "type": "quantitative"},
    "y": {"field": "y", "type": "quantitative"}
  }
}"""


@pytest.mark.parametrize(
    ("struct", "field", "kind"),
    [
        (schema.FormulaXChannel, "__x__", "quantitative"),
        (schema.FormulaXChannel, "x", "__quantitative__"),
        (schema.FormulaYChannel, "__y__", "quantitative"),
        (schema.FormulaYChannel, "y", "__quantitative__"),
    ],
)
def test_formula_channels_refuse_direct_literal_near_misses(
    struct: type[msgspec.Struct], field: str, kind: str
) -> None:
    constructor = cast("Callable[..., object]", struct)
    with pytest.raises(ValueError):
        constructor(field=field, kind=kind)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "__vplot-formula-0.1__"),
        ("numeric_profile", "__rational-half-even-v1__"),
        ("mark", "__line__"),
    ],
)
def test_formula_spec_refuses_direct_enum_near_misses(field: str, value: str) -> None:
    spec = schema.decode_formula_spec(_FORMULA_BYTES)
    with pytest.raises(ValueError):
        msgspec.structs.replace(spec, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("samples", 1),
        ("samples", 100_001),
        ("samples", True),
        ("x_scale", -1),
        ("x_scale", 13),
        ("x_scale", True),
        ("y_scale", -1),
        ("y_scale", 13),
        ("y_scale", True),
    ],
)
def test_formula_domain_refuses_direct_meta_bound_bypasses(field: str, value: object) -> None:
    domain = schema.decode_formula_spec(_FORMULA_BYTES).domain
    with pytest.raises(ValueError):
        msgspec.structs.replace(domain, **{field: value})


def _subclass_cases() -> list[tuple[type[msgspec.Struct], dict[str, object]]]:
    spec = schema.decode_formula_spec(_FORMULA_BYTES)
    return [
        (schema.FormulaXChannel, {"field": "x", "kind": "quantitative"}),
        (schema.FormulaYChannel, {"field": "y", "kind": "quantitative"}),
        (schema.FormulaEncoding, {"x": spec.encoding.x, "y": spec.encoding.y}),
        (
            schema.FormulaDomain,
            {"start": "0", "stop": "1", "samples": 2, "x_scale": 0, "y_scale": 0},
        ),
        (
            schema.FormulaPlotSpec,
            {
                "version": spec.version,
                "formula": spec.formula,
                "domain": spec.domain,
                "numeric_profile": spec.numeric_profile,
                "mark": spec.mark,
                "encoding": spec.encoding,
            },
        ),
    ]


_SUBCLASS_CASES = _subclass_cases()


@pytest.mark.parametrize(
    ("struct", "kwargs"),
    _SUBCLASS_CASES,
    ids=[struct.__name__ for struct, _kwargs in _SUBCLASS_CASES],
)
def test_formula_structs_refuse_undeclared_subclasses(
    struct: type[msgspec.Struct], kwargs: dict[str, object]
) -> None:
    near_miss = type(
        f"_Near{struct.__name__}",
        (struct,),
        {"__annotations__": {"marker": str}, "marker": "__near__"},
    )
    constructor = cast("Callable[..., object]", near_miss)
    with pytest.raises(ValueError):
        constructor(**kwargs)


# The guards beyond the retained reds: each re-checks one more decode-shape rule on direct
# construction, so each carries its own near-miss.
@pytest.mark.parametrize(
    ("field", "value"),
    [("start", "1e3"), ("start", " 0"), ("stop", "01"), ("stop", "1.0000000001"), ("stop", 1)],
)
def test_formula_domain_refuses_direct_decimal_text_bypasses(field: str, value: object) -> None:
    domain = schema.decode_formula_spec(_FORMULA_BYTES).domain
    with pytest.raises(ValueError, match=field):
        msgspec.structs.replace(domain, **{field: value})


@pytest.mark.parametrize("formula", ["x;x", "x\n", "x" * 1025, ""])
def test_formula_spec_refuses_direct_formula_text_bypasses(formula: str) -> None:
    spec = schema.decode_formula_spec(_FORMULA_BYTES)
    with pytest.raises(ValueError, match="formula"):
        msgspec.structs.replace(spec, formula=formula)


def test_formula_spec_admits_the_longest_formula_decode_admits() -> None:
    spec = schema.decode_formula_spec(_FORMULA_BYTES)
    assert msgspec.structs.replace(spec, formula="x" * 1024).formula == "x" * 1024


def test_formula_spec_refuses_a_dataset_mark_near_miss() -> None:
    spec = schema.decode_formula_spec(_FORMULA_BYTES)
    with pytest.raises(ValueError, match="mark"):
        msgspec.structs.replace(spec, mark="bar")


def test_formula_structs_refuse_wrongly_typed_children() -> None:
    spec = schema.decode_formula_spec(_FORMULA_BYTES)
    with pytest.raises(ValueError, match="FormulaDomain"):
        msgspec.structs.replace(spec, domain=spec.encoding)
    with pytest.raises(ValueError, match="FormulaEncoding"):
        msgspec.structs.replace(spec, encoding=spec.domain)
    with pytest.raises(ValueError, match="FormulaXChannel"):
        msgspec.structs.replace(spec.encoding, x=spec.encoding.y)
    with pytest.raises(ValueError, match="FormulaYChannel"):
        msgspec.structs.replace(spec.encoding, y=spec.encoding.x)


class _Text(str):
    __slots__ = ()


class _Int(int):
    pass


@pytest.mark.parametrize(
    ("struct_field", "value"),
    [
        ("mark", _Text("line")),
        ("version", _Text("vplot-formula-0.1")),
        ("numeric_profile", _Text("rational-half-even-v1")),
        ("formula", _Text("x")),
    ],
)
def test_formula_spec_refuses_str_subclass_values(struct_field: str, value: str) -> None:
    spec = schema.decode_formula_spec(_FORMULA_BYTES)
    with pytest.raises(ValueError, match=struct_field):
        msgspec.structs.replace(spec, **{struct_field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [("start", _Text("0")), ("samples", _Int(2)), ("x_scale", _Int(0))],
)
def test_formula_domain_refuses_str_and_int_subclass_values(field: str, value: object) -> None:
    domain = schema.decode_formula_spec(_FORMULA_BYTES).domain
    with pytest.raises(ValueError, match=field):
        msgspec.structs.replace(domain, **{field: value})
