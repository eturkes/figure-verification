# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q72 gallery (`docs/gallery{,.ja}.md`, `tools/render_gallery.py`): each blocked behavior beside an
honest chart, every pair a checked case.

The generator re-runs every case through the reader + judge before it writes; these tests keep the
committed pages current with no rendering: the pages equal `markdown()`, every image is tracked
and referenced, each entry pairs a blocking case of its reason with a passing one, every
figure-level reason outside the hand-stated exclusions has an entry, and each gallery-only twin
passes the real reader + judge (the rule corpus's own cases run in `tests/test_figure_corpus.py`).
"""

import importlib.util
import os
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from verifier.figure import reader
from verifier.figure.description import parse_description
from verifier.figure.judge import Sources, judge
from verifier.figure.reasons import Blocked
from webui.paste_in.checks import CHECK_OF

_ROOT = Path(__file__).resolve().parents[1]
_GALLERY = _ROOT / "docs" / "gallery"
# Reasons with no chart to show, hand-stated: the run never drew one figure (no_figure,
# multiple_figures: the reader returns no PNG for two), the verifier itself failed (verifier_error),
# or the attached file failed before any value was read (csv_*, work_budget_exceeded).
_EXCLUDED = frozenset(
    {
        "no_figure",
        "multiple_figures",
        "verifier_error",
        "csv_too_large",
        "csv_not_parsable",
        "work_budget_exceeded",
    }
)
_FIGURE_CHECKS = ("figure", "parts", "axes", "marks", "values", "columns")


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "render_gallery", _ROOT / "tools/render_gallery.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entries() -> list[dict[str, Any]]:
    text = (_GALLERY / "entries.toml").read_text(encoding="utf-8")
    return cast("list[dict[str, Any]]", tomllib.loads(text)["entry"])


def _tracked() -> set[str]:
    listed = subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(_ROOT), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return {os.fsdecode(raw) for raw in listed.split(b"\0") if raw}


@pytest.mark.parametrize(("language", "page"), [("en", "gallery.md"), ("ja", "gallery.ja.md")])
def test_q72_gallery_pages_are_current(language: str, page: str) -> None:
    """Each page = the generator's text for the committed entries, cases and checklist rows."""
    expected = cast("str", _generator().markdown(language))
    assert (_ROOT / "docs" / page).read_text(encoding="utf-8") == expected


def test_q72_gallery_images_are_tracked_and_referenced() -> None:
    entries = _entries()
    named = {entry["blocked"] for entry in entries} | {e["twin"] for e in entries if "twin" in e}
    tracked = _tracked()
    for name in named:
        assert f"docs/gallery/{name}.png" in tracked, name
    assert {path.stem for path in _GALLERY.glob("*.png")} == named


def test_q72_each_entry_pairs_a_block_of_its_reason_with_a_pass() -> None:
    cases = cast("dict[str, dict[str, Any]]", _generator().cases())
    for entry in _entries():
        assert cases[entry["blocked"]]["expect"] == entry["reason"], entry["blocked"]
        if "twin" in entry:
            assert cases[entry["twin"]]["expect"] == "pass", entry["twin"]
        assert entry["en"] and entry["ja"], entry["reason"]


def test_q72_every_figure_level_reason_has_an_entry() -> None:
    reasons = [entry["reason"] for entry in _entries()]
    assert len(reasons) == len(set(reasons))
    shown = {reason for reason, check in CHECK_OF.items() if check in _FIGURE_CHECKS}
    assert set(reasons) == shown - _EXCLUDED
    assert shown >= _EXCLUDED


_TWINS = tomllib.loads((_GALLERY / "cases.toml").read_text(encoding="utf-8"))["case"]


@pytest.mark.parametrize("case", _TWINS, ids=[case["id"] for case in _TWINS])
def test_q72_gallery_twin_passes(case: dict[str, Any]) -> None:
    assert case["expect"] == "pass"
    described = parse_description(reader.run(case["program"]))
    assert described is not None
    verdict = judge(described, Sources((), case.get("request"), "strict"))
    assert not isinstance(verdict, Blocked), verdict
