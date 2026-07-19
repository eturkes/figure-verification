# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""End-to-end test for the hardware-free real-socket three-case demo driver."""

import subprocess
import sys
from pathlib import Path

import msgspec
import pytest

from demo.walkthrough import WalkthroughReport

_ROOT = Path(__file__).resolve().parent.parent
_REPORT_PATH = _ROOT / "demo" / "reports" / "e2e_report.json"
_DRIVER_TIMEOUT_S = 120.0
_REPORT_DECODER = msgspec.json.Decoder(WalkthroughReport)
_CASE_NAMES = {
    "g01_verified_certificate_replay",
    "b07_nonexistent_field_blocked",
    "b13_units_and_scale_guarded",
}
_B07_REASON = "field 'profit' does not exist in the table"
_B13_REASON = "quantitative channel 'aqi' traces to manifest column 'aqi', which declares no unit"


def _captured(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_demo_e2e_subprocess_writes_passing_report(tmp_path: Path) -> None:
    _REPORT_PATH.unlink(missing_ok=True)
    stdout_path = tmp_path / "demo.stdout"
    stderr_path = tmp_path / "demo.stderr"
    timed_out = False
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "demo.e2e"],
            cwd=_ROOT,
            stdout=stdout_file,
            stderr=stderr_file,
        )
        try:
            return_code = proc.wait(timeout=_DRIVER_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            return_code = proc.wait(timeout=10)
            timed_out = True

    stdout = _captured(stdout_path)
    stderr = _captured(stderr_path)
    if timed_out:
        pytest.fail(
            f"demo.e2e timed out (post-kill code {return_code})\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
        )
    assert return_code == 0, (
        f"demo.e2e exited with code {return_code}\n"
        f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )
    assert _REPORT_PATH.is_file(), "demo.e2e did not write its JSON report"

    report = _REPORT_DECODER.decode(_REPORT_PATH.read_bytes())
    assert report.status == "PASS"
    assert report.total == 3
    assert report.passed == 3
    assert report.failed == 0
    assert all(result.status == "PASS" for result in report.results)
    assert {result.name for result in report.results} == _CASE_NAMES
    by_name = {result.name: result.detail for result in report.results}

    case_one = by_name["g01_verified_certificate_replay"]
    for field in (
        "dataset_hash",
        "spec_hash",
        "plotted_table_hash",
        "manifest_hash",
        "vega_lite_hash",
    ):
        assert field in case_one
    assert "scale.bar_zero | z3_smt" in case_one
    assert "sort.canonical_order | z3_smt" in case_one
    assert "replay: exact; chart repopulated" in case_one

    case_two = by_name["b07_nonexistent_field_blocked"]
    assert "schema.fields_exist" in case_two
    assert _B07_REASON in case_two

    case_three = by_name["b13_units_and_scale_guarded"]
    assert "label.quantitative_units_present" in case_three
    assert _B13_REASON in case_three
    assert "spec.decode" in case_three
    assert "scale" in case_three
