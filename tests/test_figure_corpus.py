# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19 rule corpus on the host: every case through the real reader and the judge.

`tests/figure_corpus/*.toml`: per rule, programs that must block with that rule's reason and
honest twins (`rule = <reason>`) that must pass. The bundle leg reruns the same cases in the
installed Pyodide (`.agent/measurements/`, M19.6).
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest

from verifier.figure import reader
from verifier.figure.description import parse_description
from verifier.figure.judge import Sources, judge
from verifier.figure.reasons import Blocked

_CORPUS = Path(__file__).parent / "figure_corpus"
_DATA = Path(__file__).resolve().parents[1] / "data"


def _cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(_CORPUS.glob("*.toml")):
        cases += tomllib.loads(path.read_text(encoding="utf-8"))["case"]
    return cases


_ALL = _cases()


@pytest.mark.parametrize("case", _ALL, ids=[case["id"] for case in _ALL])
def test_corpus_case(case: dict[str, Any]) -> None:
    program = case["program"].replace("{data}", str(_DATA)).replace("{corpus}", str(_CORPUS))
    described = parse_description(reader.run(program))
    assert described is not None
    files: tuple[tuple[str, bytes], ...] = ()
    if "csv" in case:
        path = _DATA / case["csv"]
        path = path if path.is_file() else _CORPUS / case["csv"]
        files = ((case["csv"], path.read_bytes()),)
    sources = Sources(files, case.get("request"), case.get("anchoring", "strict"))
    verdict = judge(described, sources)
    if case["expect"] == "pass":
        assert not isinstance(verdict, Blocked), verdict
    else:
        assert isinstance(verdict, Blocked)
        assert verdict.reason == case["expect"]
        if "site" in case:
            assert verdict.site == case["site"]


def test_corpus_ids_are_unique() -> None:
    ids = [case["id"] for case in _ALL]
    assert len(ids) == len(set(ids))


# The integrity reasons (M19.3), hand-stated: each has a blocking case, each rule an honest twin.
_RUN = (
    "program_syntax_error",
    "program_error",
    "module_not_available",
    "figure_too_large",
    "no_figure",
    "multiple_figures",
    "glyph_missing",
)
_RULES = (
    "raster_image",
    "axes_not_judged",
    "axes_twin",
    "axes_overlap",
    "artist_not_judged",
    "no_data",
    "mark_not_in_data",
    "scale_not_linear",
    "axis_inverted",
    "zero_not_in_limits",
    "tick_label_mismatch",
    "point_clipped",
    "mark_hidden",
    "value_not_finite",
    "bar_not_from_zero",
    "bars_overlap",
    "x_not_ordered",
    "hist_counts",
    "pie_not_whole",
    "area_not_from_zero",
    "marker_size_varies",
    "marker_color_varies",
    "legend_mismatch",
    "category_not_unique",
    "value_not_found",
    "label_not_in_request",
    "column_not_requested",
    "column_not_named",
    "label_not_consistent",
)
_SOURCE_FAULTS = ("csv_not_parsable",)


@pytest.mark.parametrize("reason", _RUN + _RULES + _SOURCE_FAULTS)
def test_every_integrity_reason_has_a_blocking_case(reason: str) -> None:
    assert any(case["expect"] == reason for case in _ALL)


@pytest.mark.parametrize("reason", _RULES)
def test_every_integrity_rule_has_an_honest_twin(reason: str) -> None:
    assert any(case["expect"] == "pass" and case.get("rule") == reason for case in _ALL)


def test_every_honest_case_names_the_rule_it_twins() -> None:
    reasons = set(_RUN + _RULES)
    for case in _ALL:
        if case["expect"] == "pass":
            assert case.get("rule") in reasons | {None}
