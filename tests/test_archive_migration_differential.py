# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""p3/p43: the committed M9.7a differential runs and detects logical row loss."""

import pytest

from archive_migration_differential import main


def test_small_migration_corpus_and_planted_row_loss(capsys: pytest.CaptureFixture[str]) -> None:
    """Empty + linked/unlinked attempts cover small shapes; lost oracle rows must fail loudly."""
    cases = ("empty", "attempt-with-plot", "attempt-without-plot")
    arguments = [argument for case in cases for argument in ("--case", case)]
    assert main(arguments) == 0
    table = capsys.readouterr().out
    for case in cases:
        assert case in table
    for section in (
        "table_info",
        "rows",
        "blob_content_sha256",
        "logical_blob_bytes",
        "meta",
        "user_version",
        "foreign_key_check",
        "integrity_check",
        "rootpages",
        "trigger_behavior",
    ):
        assert f"{section} | PASS | PASS | PASS" in table
    assert "file_size | EXPECTED-DIVERGENT" in table
    assert "page_count | EXPECTED-DIVERGENT" in table
    assert "FAIL" not in table

    assert main(["--case", "attempt-with-plot", "--plant-row-loss"]) == 1
    planted = capsys.readouterr().out
    assert "rows | FAIL" in planted
    assert "comparison failed: attempt-with-plot:rows" in planted
