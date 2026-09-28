# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.9 review witnesses (reviewer-3 F1, F2): only the manifest's own population is counted, a
duplicate cannot turn a miss into acceptance, and an unscorable directory hides no later drift."""

from pathlib import Path

import pytest

import test_python_capture_score as fixtures
from capture.corpus import Category
from capture.harness import main
from capture.score import ScoreError


@pytest.mark.parametrize("category", ["simple", "complicated"])
def test_foreign_kind_cannot_inflate_category_numerator(category: Category) -> None:
    run = fixtures.full_run(13, 13)
    extra = fixtures.record(
        f"design-{category}-01",
        "verified" if category == "simple" else "refused",
        category=category,
        kind="design",
    )
    try:
        summary = fixtures.document(fixtures.make_run([*run.records, extra]))["summary"]
    except ScoreError:
        return
    key = "verified" if category == "simple" else "blocked"
    assert summary[category][key] == 13, summary


def test_duplicate_row_cannot_turn_a_miss_into_cli_acceptance(tmp_path: Path) -> None:
    directory = tmp_path / "m10-heldout"
    run = fixtures.full_run(13, 14, directory=directory)
    duplicate = next(
        row for row in run.records if row.kind == "heldout" and row.category == "simple"
    )
    malformed = fixtures.make_run([*run.records, duplicate], directory)
    fixtures.save_run(malformed)
    try:
        status = main(["score", "--write", str(directory)])
        summary = fixtures.document(malformed)["summary"]
    except ScoreError:
        return
    assert status != 0 or summary["acceptance_met"] is False, summary


def test_unscorable_directory_does_not_hide_later_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = tmp_path / "sentinels-only"
    second = tmp_path / "missing-score"
    fixtures.save_run(fixtures.full_run(kind="sentinels", directory=first))
    fixtures.save_run(fixtures.full_run(directory=second))
    try:
        status = main(["score", str(first), str(second)])
    except ScoreError:
        pytest.fail("score CLI aborts on ScoreError before reporting the later directory")
    assert status == 1
    captured = capsys.readouterr()
    assert str(first) in captured.err
    assert str(second) in captured.err


def test_a_duplicated_row_alone_makes_the_run_incomplete() -> None:
    """A1(3), pinned on its own: every expected id present once plus ONE duplicate of a REFUSED
    complicated row, so no numerator moves and only the cardinality conjunct can decide
    (closing review H4: the acceptance-only witness let either duplicate fix mask the other)."""
    run = fixtures.full_run()
    duplicate = next(
        row for row in run.records if row.kind == "heldout" and row.category == "complicated"
    )
    summary = fixtures.document(fixtures.make_run([*run.records, duplicate]))["summary"]
    assert summary["complicated"] == {"total": 20, "blocked": 20}
    assert summary["complete"] is False
    assert summary["acceptance_met"] is False


def test_a_duplicated_verified_row_is_counted_once() -> None:
    """A1(2), pinned on its own: a 13/20 run plus a duplicate of one VERIFIED simple row still
    reads 13, whatever completeness says (closing review H4)."""
    run = fixtures.full_run(13, 20)
    duplicate = next(
        row
        for row in run.records
        if row.kind == "heldout"
        and row.category == "simple"
        and fixtures.document(fixtures.make_run([row], kind="heldout"))["rows"][0]["outcome"]
        == "verified"
    )
    summary = fixtures.document(fixtures.make_run([*run.records, duplicate]))["summary"]
    assert summary["simple"] == {"total": 20, "verified": 13}
