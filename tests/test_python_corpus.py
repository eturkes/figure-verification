# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Structural gate for the python-mode prompt corpus (contract .agent/archive/contracts/m12u5.md).

Predicates C1-C10 live in capture.corpus and are called here, never restated: a test that
re-implements a check pins its own copy instead of the shipped one. What this file adds on top of
the calls is what the validator cannot check about ITSELF -- strict-decode refusal against
near-miss inputs, the closed predicate set, the closed idiom vocabulary, the banned-term matcher's
false-positive band, the rendered capture prompt's exact bytes, and the two invariant surfaces
(I1, I5) that live in the tree rather than in the data.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import msgspec
import pytest

from capture.corpus import (
    CORPUS_ROOT,
    IDIOMS,
    PREDICATES,
    REPO_ROOT,
    Corpus,
    PromptSet,
    banned_terms,
    load_corpus,
    render_capture_prompt,
    validate,
)

# Empty since the corpus was filled; kept as the seed mechanism for any future corpus extension.
_SEED_PENDING: frozenset[str] = frozenset()

_VALID_ROW: dict[str, Any] = {
    "id": "design-simple-01",
    "category": "simple",
    "idiom": "scatter_xy",
    "dataset_name": "sales.csv",
    "prompt": "Plot a scatter chart of revenue versus orders.",
}

_SENTINEL_SIMPLE_RENDERED = (
    "Plot a scatter chart of revenue versus orders.\n"
    "\n"
    "Use the CSV file at /mnt/uploads/sales.csv. "
    "Its columns are month, region, revenue, orders.\n"
    "Draw the figure with matplotlib.\n"
    "\n"
    "Return one complete Python program as bare source text, no Markdown fences.\n"
)


@pytest.fixture
def corpus() -> Corpus:
    """The committed corpus, strictly decoded."""
    return load_corpus()


@pytest.mark.parametrize("predicate_id", list(PREDICATES))
def test_committed_corpus_satisfies_every_predicate(corpus: Corpus, predicate_id: str) -> None:
    """C1-C10 -- each contract predicate reports zero failures against the committed corpus."""
    if predicate_id in _SEED_PENDING:
        pytest.skip("corpus seeded at M12.5; prod-m12u5 fills the 88 prompt cells")
    assert PREDICATES[predicate_id](corpus) == []


def test_predicate_set_is_closed() -> None:
    """The contract's ten predicates are exactly what the validator runs -- no more, no fewer."""
    assert set(PREDICATES) == {f"C{n}" for n in range(1, 11)}


def test_validate_prefixes_every_failure_with_its_predicate_id(tmp_path: Path) -> None:
    """A broken copy reports through validate(), so the aggregate never silences a predicate."""
    root = tmp_path / "python"
    shutil.copytree(CORPUS_ROOT, root)
    manifest = root / "design" / "manifest.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["prompts"][0]["prompt"] = "Plot whatever the allowlist supports."
    manifest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    failures = validate(root)

    assert any(line.startswith("C6: design-simple-01:") for line in failures)
    assert all(line.split(":", 1)[0] in PREDICATES for line in failures)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param({"note": "extra"}, id="unknown-field"),
        pytest.param({"category": "Simple"}, id="category-case"),
        pytest.param({"category": "complex"}, id="category-spelling"),
        pytest.param({"dataset_name": "sales"}, id="dataset-without-suffix"),
        pytest.param({"dataset_name": "../data/sales.csv"}, id="dataset-traversal"),
        pytest.param({"prompt": 3}, id="non-string-prompt"),
        pytest.param({"id": None}, id="null-id"),
    ],
)
def test_strict_decode_refuses_near_miss_rows(mutation: dict[str, Any]) -> None:
    """C1's refusal arm: forbid_unknown_fields plus Literal members reject same-family inputs."""
    row = {**_VALID_ROW, **mutation}
    payload = {"version": "python-corpus-1", "kind": "design", "prompts": [row]}
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(json.dumps(payload).encode(), type=PromptSet)


@pytest.mark.parametrize("missing", ["version", "kind", "prompts"])
def test_strict_decode_requires_every_set_field(missing: str) -> None:
    """A set file cannot omit its version, its kind or its rows."""
    payload = {"version": "python-corpus-1", "kind": "design", "prompts": [_VALID_ROW]}
    del payload[missing]
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(json.dumps(payload).encode(), type=PromptSet)


def test_idiom_vocabulary_is_the_contracted_literal() -> None:
    """The vocabulary becomes M13's design vocabulary, so drift in it is a scope change."""
    assert IDIOMS == {
        "simple": (
            "bar_category_sum",
            "bar_category_mean",
            "bar_category_extremum",
            "bar_time_sum",
            "line_time_series",
            "line_time_multi_series",
            "scatter_xy",
            "scatter_xy_grouped",
        ),
        "complicated": (
            "subplot_grid",
            "twin_axis",
            "statistical_fit",
            "derived_metric",
            "distribution_plot",
            "styled_annotation",
            "composite_marks",
            "external_or_interactive",
        ),
    }


@pytest.mark.parametrize(
    "text",
    [
        "Plot the unsupported columns.",
        "Add whatever the allowlist permits.",
        "Write code the verifier will accept.",
        "Emit a comment if the request is not supported.",
        "Stay inside the sandbox policy.",
        "Reject anything outside the restricted set.",
        "Validate the program before plotting.",
        "Skip any blocked construct.",
    ],
)
def test_banned_matcher_catches_admission_vocabulary(text: str) -> None:
    """Ruling 6 is enforced mechanically, so the matcher must fire on every framing of it."""
    assert banned_terms(text)


@pytest.mark.parametrize(
    "text",
    [
        "Plot a scatter chart of revenue versus orders.",
        "Show total revenue by region as a bar chart.",
        "Overlay a linear regression line on temperature over time.",
        "Draw a 2x2 grid of subplots with a KPI panel and an annotated peak month.",
        "Chart precipitation for each city, sorted by the average value.",
        "Add a secondary axis for orders and a rolling seven-day mean.",
    ],
)
def test_banned_matcher_admits_ordinary_plot_language(text: str) -> None:
    """A fail-closed matcher that also refuses legitimate asks would distort the corpus."""
    assert banned_terms(text) == []


def test_rendered_capture_prompt_is_byte_exact(corpus: Corpus) -> None:
    """The pinned sha means wire bytes only if rendering is pinned too."""
    sentinel = next(p for p in corpus.sentinels.prompts if p.id == "sentinel-simple")
    assert render_capture_prompt(sentinel) == _SENTINEL_SIMPLE_RENDERED


def test_corpus_tree_holds_no_python_module() -> None:
    """I1 -- a corpus PACKAGE would shadow tests/corpus.py under pytest's pythonpath."""
    assert sorted(CORPUS_ROOT.parent.rglob("*.py")) == []


def test_capture_records_are_tracked_not_ignored() -> None:
    """I5 -- M12.7 commits captures; bench/reports/ is the gitignored counter-example."""
    probe = "corpus/python/captures/m12-design/row.json"
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "--no-index", probe],  # noqa: S607
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        text=True,
    )
    assert result.returncode == 1, f"{probe} is gitignored: {result.stdout}"
