# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.2 O1/O2: the tagged matplotlib inventory is parsed and read by a closed mark map.

Contract: `.agent/archive/contracts/m10u2.md` § A1. A malformed or unrecognized observation can only
withhold; none of these tests uses the uncommitted Pyodide spike as an expected-output table.
"""

import ast
import copy
import importlib
import json
from dataclasses import replace
from types import ModuleType
from typing import Any, cast

import pytest

from observe_support import OBS_MAX_BYTES, OBS_TAG, dataset_verdict, observation_for, stdout_for
from verifier.pysrc import Verified


def _module() -> ModuleType:
    return importlib.import_module("webui.paste_in.observe")


def _parsed(payload: dict[str, Any]) -> tuple[ModuleType, object]:
    module = _module()
    observed = module.parse_observation(stdout_for(payload))
    assert observed is not None
    return module, cast(object, observed)


def _matches(verified: Verified, payload: dict[str, Any]) -> bool:
    module, observed = _parsed(payload)
    return bool(module.observation_matches(verified, observed))


def test_o1_observer_source_compiles_defines_reader_and_avoids_rewriter() -> None:
    """O1: compile the sandbox observer; it reads the wire fields without the rewrite trigger."""
    module = _module()
    assert module.OBSERVATION_TAG == "FIGURE_VERIFICATION_OBSERVATION:"
    assert module.OBSERVATION_MAX_BYTES == 16_777_216
    source = module.OBSERVER_SOURCE
    assert type(source) is str
    assert "matplotlib" not in source
    tree = ast.parse(source)
    compile(tree, "<figure-observer>", "exec")
    assert any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_figure_verification_observe"
        for node in ast.walk(tree)
    )
    fields = {
        value.value
        for value in ast.walk(tree)
        if isinstance(value, ast.Constant) and type(value.value) is str
    }
    assert {
        "axes",
        "lines",
        "collections",
        "containers",
        "patches",
        "images",
        "texts",
        "xaxis",
        "yaxis",
        "units",
        "ticks",
    } <= fields


def test_o1_wrapper_inlines_observer_without_renderer_patch_trigger() -> None:
    """O1: the wrapper embeds the observer while the model's literal import remains encoded."""
    module = _module()
    wrapper = importlib.import_module("webui.paste_in.filter").wrapper_code(
        "import matplotlib.pyplot as plt\nplt.show()\n"
    )
    assert type(wrapper) is str
    assert "matplotlib" not in wrapper
    assert "_figure_verification_observe" in wrapper
    assert module.OBSERVATION_TAG in wrapper
    compile(wrapper, "<figure-wrapper>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


@pytest.mark.parametrize("mark", ["line", "scatter", "bar", "barh"])
def test_o2_closed_mark_map_and_one_matching_artist(mark: str) -> None:
    """O2: hand-pin four reader keys and accept exactly one artist of the projected kind."""
    module = _module()
    assert set(module.READERS) == {"line", "scatter", "bar", "barh"}
    verified = dataset_verdict(cast(Any, mark), "numeric")
    assert _matches(verified, observation_for(verified))


@pytest.mark.parametrize("mark", ["line", "scatter", "bar", "barh"])
@pytest.mark.parametrize("field", ["lines", "collections", "containers"])
def test_o2_wrong_or_extra_artist_withholds(mark: str, field: str) -> None:
    """O2: removing the one expected artist or adding a foreign kind never publishes a PNG."""
    verified = dataset_verdict(cast(Any, mark), "numeric")
    baseline = observation_for(verified)
    own = {"line": "lines", "scatter": "collections", "bar": "containers", "barh": "containers"}[
        mark
    ]
    changed = copy.deepcopy(baseline)
    if field == own:
        changed[field] = []
    elif field == "containers":
        changed[field] = [[[(0.0).hex(), (0.0).hex(), (1.0).hex(), (1.0).hex()]]]
    else:
        changed[field] = [[[(0.0).hex(), (1.0).hex()]]]
    assert not _matches(verified, changed)


@pytest.mark.parametrize("mark", ["line", "scatter", "bar", "barh"])
@pytest.mark.parametrize("field", ["axes", "patches", "images", "texts"])
def test_o2_axes_and_extra_artist_inventory_withholds(mark: str, field: str) -> None:
    """O2: reject another axes, a stray patch, an image, or plotted text independently."""
    verified = dataset_verdict(cast(Any, mark), "numeric")
    changed = observation_for(verified)
    changed[field] = 2 if field == "axes" else 1
    assert not _matches(verified, changed)


def test_o2_unmapped_mark_has_no_fallback_reader() -> None:
    """O2: a projected mark outside the closed map blocks even with a valid line artist."""
    verified = dataset_verdict("line", "numeric")
    specimen = replace(verified, spec=replace(verified.spec, mark=cast(Any, "area")))
    assert not _matches(specimen, observation_for(verified))


@pytest.mark.parametrize("mark", ["line", "scatter", "bar", "barh"])
def test_o2_second_artist_of_own_kind_withholds(mark: str) -> None:
    """O2: two correctly typed artists still violate the one-mark observation."""
    verified = dataset_verdict(cast(Any, mark), "numeric")
    changed = observation_for(verified)
    field = {"line": "lines", "scatter": "collections", "bar": "containers", "barh": "containers"}[
        mark
    ]
    changed[field].append(copy.deepcopy(changed[field][0]))
    assert not _matches(verified, changed)


def test_o1_one_tagged_stdout_line_amid_non_observation_output() -> None:
    """O1: an unrelated stdout line cannot replace or corrupt the sole tagged line."""
    verified = dataset_verdict("line", "numeric")
    module = _module()
    stdout = stdout_for(observation_for(verified), prefix="log before observation\n")
    observed = module.parse_observation(stdout + "log after observation\n")
    assert observed is not None
    assert module.observation_matches(verified, observed)


def _malformed_payload(kind: str, payload: dict[str, Any]) -> str:  # noqa: PLR0912
    # One explicit branch per independent malformed wire shape prevents cases sharing a path.
    changed = copy.deepcopy(payload)
    if kind == "missing-tag":
        return stdout_for(changed).replace(OBS_TAG, "other:", 1)
    if kind == "duplicate-tag":
        return stdout_for(changed) * 2
    if kind == "oversized-tag":
        changed["xaxis"]["ticks"][0][1] = "X" * OBS_MAX_BYTES
        return stdout_for(changed)
    if kind == "non-finite-json":
        return stdout_for(changed).replace('"axes":1', '"axes":NaN', 1)
    if kind == "infinite-json":
        return stdout_for(changed).replace('"axes":1', '"axes":Infinity', 1)
    if kind == "missing-key":
        del changed["patches"]
    elif kind == "extra-key":
        changed["unrecognized"] = []
    elif kind == "nested-missing-key":
        del changed["xaxis"]["units"]
    elif kind == "nested-extra-key":
        changed["xaxis"]["unrecognized"] = 1
    elif kind == "boolean-count":
        changed["images"] = True
    elif kind == "boolean-axes":
        changed["axes"] = True
    elif kind == "bad-hex":
        changed["lines"][0][0][1] = "zero"
    elif kind == "non-finite-hex":
        changed["lines"][0][0][1] = "nan"
    elif kind == "bad-tick-hex":
        # `float.fromhex("bad")` is the finite 2989.0, which A1 accepts.
        changed["xaxis"]["ticks"][0][0] = "zero"
    elif kind == "bad-units-hex":
        changed["xaxis"]["units"] = [["north", "inf"]]
    elif kind == "wrong-axis-shape":
        changed["yaxis"]["ticks"] = "not a list"
    else:
        message = f"unknown malformed payload: {kind}"
        raise AssertionError(message)
    return stdout_for(changed)


@pytest.mark.parametrize(
    "kind",
    [
        "missing-tag",
        "duplicate-tag",
        "oversized-tag",
        "non-finite-json",
        "infinite-json",
        "missing-key",
        "extra-key",
        "nested-missing-key",
        "nested-extra-key",
        "boolean-count",
        "boolean-axes",
        "bad-hex",
        "non-finite-hex",
        "bad-tick-hex",
        "bad-units-hex",
        "wrong-axis-shape",
    ],
)
def test_o1_parser_rejects_malformed_observation(kind: str) -> None:
    """O1: exact tag, one bounded line, closed fields, integer counts, finite hex values."""
    module = _module()
    verified = dataset_verdict("line", "categorical")
    payload = observation_for(verified, "categorical")
    bad = _malformed_payload(kind, payload)
    assert module.parse_observation(bad) is None


def test_o1_parser_preserves_all_finite_binary64_values() -> None:
    """O1: finite hex float64 travels without rounding through JSON parse and comparison."""
    module = _module()
    verified = dataset_verdict("line", "numeric")
    payload = observation_for(verified)
    assert payload["lines"][0][0][0] == (0.000001).hex()
    observed = module.parse_observation(stdout_for(payload))
    assert observed is not None
    assert module.observation_matches(verified, observed)


def test_o1_parser_rejects_invalid_utf8_length_not_character_count() -> None:
    """O1: a JSON-valid line under the character cap yet over the UTF-8 cap withholds."""
    module = _module()
    verified = dataset_verdict("line", "categorical")
    payload = observation_for(verified, "categorical")
    payload["xaxis"]["ticks"][0][1] = "é" * (OBS_MAX_BYTES // 2)
    raw_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    stdout = OBS_TAG + raw_json + "\n"
    assert len(stdout) < OBS_MAX_BYTES < len(stdout.encode("utf-8"))
    assert json.loads(raw_json) == payload
    assert module.parse_observation(stdout) is None
