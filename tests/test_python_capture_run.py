# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Gate for the COMMITTED capture runs (contract .agent/archive/contracts/m12u7.md).

R1-R11 and S1-S4 live in capture.record and capture.harness and are called here, never restated.
What this file adds is what neither predicate set can say about a committed run: that the run is
COMPLETE (R5 admits "its own set plus sentinels and nothing else", R3 only agrees record_count with
the rows PRESENT, so a 3-of-50 run grades clean under both), that its bytes are TRACKED rather than
gitignored evidence, that no held-out capture was ever committed, and that the discovered run list
is non-empty so no loop over it can pass vacuously.

Run discovery is re-implemented here rather than imported: a broken discovery in the module under
test would otherwise hide the very run this file exists to grade.
"""

import subprocess
from pathlib import Path

from capture.corpus import REPO_ROOT, load_corpus
from capture.harness import validate_stats
from capture.record import CAPTURES_ROOT, load_run
from capture.record import validate as validate_records

DESIGN_RUN = "m12-design"
RUN_FILES = ("run.json", "records.ndjson", "stats.json")
# 24 + 24 committed design prompts plus the two public sentinels.
DESIGN_ROW_COUNT = 50


def _runs() -> list[Path]:
    return sorted(path for path in CAPTURES_ROOT.iterdir() if path.is_dir())


def _git(*argv: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(  # noqa: S603
        ["git", *argv],  # noqa: S607
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        text=True,
    )


def test_t1_committed_runs_grade_clean() -> None:
    """T1 -- every committed run answers both predicate sets clean, over a non-empty list."""
    runs = _runs()
    assert runs, f"no capture run under {CAPTURES_ROOT}"
    for directory in runs:
        assert validate_records(directory) == [], directory
        assert validate_stats(directory) == [], directory


def test_t2_design_run_is_complete() -> None:
    """T2 -- the design run holds every committed design prompt and both sentinels, exactly."""
    corpus = load_corpus()
    expected = {prompt.id for prompt in corpus.design.prompts} | {
        prompt.id for prompt in corpus.sentinels.prompts
    }
    assert len(expected) == DESIGN_ROW_COUNT
    run = load_run(CAPTURES_ROOT / DESIGN_RUN)
    assert {record.prompt_id for record in run.records} == expected


def test_t3_committed_run_bytes_are_tracked() -> None:
    """T3 -- the run is committed evidence: not gitignored, and tracked by name."""
    for name in RUN_FILES:
        probe = f"{CAPTURES_ROOT.relative_to(REPO_ROOT)}/{DESIGN_RUN}/{name}"
        # --no-index is load-bearing: check-ignore suppresses TRACKED paths by default, so the
        # negative reads clean for the wrong reason once the file lands.
        ignored = _git("check-ignore", "--no-index", probe)
        assert ignored.returncode == 1, f"{probe} is gitignored: {ignored.stdout}"
        tracked = _git("ls-files", "--error-unmatch", probe)
        assert tracked.returncode == 0, f"{probe} is untracked: {tracked.stderr}"


def test_t4_no_heldout_capture_is_committed() -> None:
    """T4 -- ruling 7: the held-out set stays ungenerated until the M13 config is frozen."""
    for directory in _runs():
        kind = load_run(directory).manifest.kind
        assert kind != "heldout", f"{directory} commits a held-out capture"
