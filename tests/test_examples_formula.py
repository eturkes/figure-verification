# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9.1-M9.2 formula corpus checks: decode shape and bounded expression parsing."""

import json
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any

import msgspec
import pytest

from verifier.errors import VerificationError
from verifier.expr import parse_expr, print_expr
from verifier.limits import VerificationLimits
from verifier.schema import FormulaPlotSpec, decode_formula_spec

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "formula_good_specs"
_BAD_DIR = _EXAMPLES / "formula_bad_specs"
_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["formula_good_specs"]
_BAD: list[dict[str, Any]] = _INDEX["formula_bad_specs"]
_BAD_DECODE = [entry for entry in _BAD if not entry["decodes"]]
_BAD_LATER = [entry for entry in _BAD if entry["decodes"]]

# The COMPLETE expected shape per good file: (mark, formula, start, stop, samples,
# x_scale, y_scale). Pinning only mark+formula let a domain drift silently, and these
# domains are load-bearing — they are the planned M9.3/M9.4 pass-goldens.
_EXPECTED_GOOD = {
    "f01_square.json": ("line", "x**2", "-3", "3", 13, 1, 2),
    "f02_linear.json": ("line", "2*x + 1", "0", "10", 11, 0, 0),
    "f03_cubic.json": ("scatter", "x*(x - 1)*(x + 1)", "-2", "2", 21, 1, 3),
    "f04_rational.json": ("line", "1/(1 + x*x)", "-5", "5", 41, 1, 4),
    "f05_absolute_value.json": ("line", "abs(x)", "-4", "4", 17, 1, 1),
    "f06_quadratic.json": ("scatter", "-x**2 + 3*x - 2", "0", "3", 7, 1, 2),
}
_EXPECTED_DECODE_MESSAGES = {
    "fb01_wrong_version.json": "$.version",
    "fb02_dataset_key.json": "unknown field `dataset`",
    "fb03_bar_mark.json": "$.mark",
    "fb04_y_field.json": "$.encoding.y.field",
    "fb05_x_type.json": "$.encoding.x.type",
    "fb06_code_injection.json": "$.formula",
    "fb07_formula_newline.json": "$.formula",
    "fb08_samples_below_min.json": "$.domain.samples",
    "fb09_numeric_start_token.json": "$.domain.start",
    "fb10_negative_x_scale.json": "$.domain.x_scale",
    "fb11_numeric_profile.json": "$.numeric_profile",
    "fb12_duplicate_mark.json": "duplicate object key: 'mark'",
    "fb13_exponent_decimal.json": "$.domain.stop",
    "fb14_missing_domain.json": "required field `domain`",
}
_EXPECTED_LATER = {
    "fb15_disallowed_function.json": ("parser", "formula.functions_allowed", "parser"),
    "fb16_disallowed_name.json": ("parser", "formula.names_allowed", "parser"),
    "fb17_reversed_domain.json": ("domain", "formula.domain_ordered", "domain checks"),
    "fb18_division_by_zero.json": ("evaluation", "formula.values_defined", "evaluation/sampling"),
    "fb19_exponent_too_large.json": (
        "parser/evaluation",
        "formula.exponents_bounded",
        "parser/domain checks",
    ),
    "fb20_sample_collision.json": (
        "sampling",
        "formula.sample_points_strictly_increasing",
        "evaluation/sampling",
    ),
}


_EXPECTED_GOOD_AST = {
    "f01_square.json": "(pow x 2)",
    "f02_linear.json": "(add (mul 2 x) 1)",
    "f03_cubic.json": "(mul (mul x (sub x 1)) (add x 1))",
    "f04_rational.json": "(div 1 (add 1 (mul x x)))",
    "f05_absolute_value.json": "(abs x)",
    "f06_quadratic.json": "(sub (add (neg (pow x 2)) (mul 3 x)) 2)",
}
_BAD_PARSER = [entry for entry in _BAD_LATER if str(entry["caught_by"]).startswith("parser")]
_BAD_AFTER_PARSER = [entry for entry in _BAD_LATER if entry not in _BAD_PARSER]


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(entry["file"]).stem for entry in entries]


def test_formula_corpus_meets_floor_and_inventory() -> None:
    assert len(_GOOD) >= 6
    assert len(_BAD) >= 14
    assert {entry["file"] for entry in _GOOD} == set(_EXPECTED_GOOD)
    assert {entry["file"] for entry in _BAD_DECODE} == set(_EXPECTED_DECODE_MESSAGES)
    assert {entry["file"] for entry in _BAD_LATER} == set(_EXPECTED_LATER)
    intents = [entry["intent"] for entry in [*_GOOD, *_BAD]]
    assert all(isinstance(intent, str) and intent for intent in intents)
    assert len(intents) == len(set(intents))


@pytest.mark.parametrize(
    ("subdir", "entries"),
    [("formula_good_specs", _GOOD), ("formula_bad_specs", _BAD)],
)
def test_formula_index_matches_filesystem(subdir: str, entries: list[dict[str, Any]]) -> None:
    on_disk = {path.name for path in (_EXAMPLES / subdir).glob("*.json")}
    indexed = {entry["file"] for entry in entries}
    assert on_disk == indexed


@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_formula_good_spec_decodes_to_its_complete_pinned_shape(entry: dict[str, Any]) -> None:
    spec = decode_formula_spec((_GOOD_DIR / entry["file"]).read_bytes())
    assert isinstance(spec, FormulaPlotSpec)
    assert entry["decodes"] is True
    assert (entry["mark"], entry["formula"]) == _EXPECTED_GOOD[entry["file"]][:2]
    domain = spec.domain
    assert (
        spec.mark,
        spec.formula,
        domain.start,
        domain.stop,
        domain.samples,
        domain.x_scale,
        domain.y_scale,
    ) == _EXPECTED_GOOD[entry["file"]]


@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_formula_good_spec_schedule_is_exact_and_strictly_increasing(
    entry: dict[str, Any],
) -> None:
    """The property that makes these files usable as M9.3/M9.4 pass-goldens: every declared
    endpoint is exactly representable at x_scale, and quantizing the evenly-spaced schedule
    HALF_EVEN keeps it strictly increasing. Computed here from the spec alone — an
    independent oracle, not the (not-yet-written) sampler."""
    spec = decode_formula_spec((_GOOD_DIR / entry["file"]).read_bytes())
    domain = spec.domain
    quantum = Fraction(1, 10**domain.x_scale)
    start, stop = Fraction(domain.start), Fraction(domain.stop)
    assert start < stop
    assert start % quantum == 0, "start is not exactly representable at x_scale"
    assert stop % quantum == 0, "stop is not exactly representable at x_scale"
    step = (stop - start) / (domain.samples - 1)
    # Counts of whole quanta: exact integers, so HALF_EVEN is Fraction.__round__ and no
    # binary float ever enters. round() on a Fraction is already ties-to-even.
    counts = [round((start + step * index) / quantum) for index in range(domain.samples)]
    assert counts[0] == start / quantum
    assert counts[-1] == stop / quantum
    assert all(a < b for a, b in pairwise(counts))


@pytest.mark.parametrize("entry", _BAD_DECODE, ids=_ids(_BAD_DECODE))
def test_formula_bad_spec_decode_layer_rejected(entry: dict[str, Any]) -> None:
    assert entry["layer"] == "decode"
    assert entry["decodes"] is False
    assert entry["caught_by"] == "decode_formula_spec"
    assert isinstance(entry["check"], str) and entry["check"]
    assert isinstance(entry["reason"], str) and entry["reason"]
    with pytest.raises(msgspec.ValidationError) as exc_info:
        decode_formula_spec((_BAD_DIR / entry["file"]).read_bytes())
    assert type(exc_info.value) is msgspec.ValidationError
    assert _EXPECTED_DECODE_MESSAGES[entry["file"]] in str(exc_info.value)


@pytest.mark.parametrize("entry", _BAD_LATER, ids=_ids(_BAD_LATER))
def test_formula_bad_spec_later_layer_still_decodes(entry: dict[str, Any]) -> None:
    spec = decode_formula_spec((_BAD_DIR / entry["file"]).read_bytes())
    assert isinstance(spec, FormulaPlotSpec)
    assert entry["decodes"] is True
    assert (entry["layer"], entry["check"], entry["caught_by"]) == _EXPECTED_LATER[entry["file"]]
    assert isinstance(entry["reason"], str) and entry["reason"]


@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_formula_good_spec_parses_to_pinned_canonical_ast(entry: dict[str, Any]) -> None:
    spec = decode_formula_spec((_GOOD_DIR / entry["file"]).read_bytes())
    parsed = parse_expr(
        spec.formula,
        allowed_vars=frozenset({"x"}),
        limits=VerificationLimits(),
    )
    assert print_expr(parsed.ast) == _EXPECTED_GOOD_AST[entry["file"]]


@pytest.mark.parametrize("entry", _BAD_PARSER, ids=_ids(_BAD_PARSER))
def test_formula_bad_spec_parser_layer_rejected_by_declared_check(entry: dict[str, Any]) -> None:
    spec = decode_formula_spec((_BAD_DIR / entry["file"]).read_bytes())
    with pytest.raises(VerificationError) as exc_info:
        parse_expr(
            spec.formula,
            allowed_vars=frozenset({"x"}),
            limits=VerificationLimits(),
        )
    assert exc_info.value.check == entry["check"]


@pytest.mark.parametrize("entry", _BAD_AFTER_PARSER, ids=_ids(_BAD_AFTER_PARSER))
def test_formula_bad_spec_deferred_past_parser_parses_cleanly(entry: dict[str, Any]) -> None:
    spec = decode_formula_spec((_BAD_DIR / entry["file"]).read_bytes())
    parsed = parse_expr(
        spec.formula,
        allowed_vars=frozenset({"x"}),
        limits=VerificationLimits(),
    )
    assert print_expr(parsed.ast)
