# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Every repository command answers `--help` and refuses an unknown argument before it acts.

A command that ignores its arguments runs its whole job on `--help`: a renderer rewrites tracked
files, `python -m model_backend` loads a model and serves it. argparse gives the shared contract:
`--help` prints the usage + exits 0, an unknown argument exits 2 with an error.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_COMMANDS = (
    ("tools/generate_paste_in.py",),
    ("tools/mutate.py",),
    ("tools/mutation_credit.py",),
    ("tools/render_diagrams.py",),
    ("tools/render_gallery.py",),
    ("tools/render_nucllei_guide.py",),
    ("tools/subset_test_font.py",),
    ("-m", "model_backend"),
    ("-m", "model_backend.smoke"),
    ("-m", "model_backend.snapshot"),
    ("-m", "webui"),
)


def _run(command: tuple[str, ...], argument: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, *command, argument],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("command", _COMMANDS, ids=" ".join)
def test_help_exits_clean_and_an_unknown_argument_exits_2(command: tuple[str, ...]) -> None:
    helped = _run(command, "--help")
    assert helped.returncode == 0 and helped.stdout.startswith("usage:"), helped.stdout[-500:]
    refused = _run(command, "--no-such-option")  # a required argument may be named first
    assert refused.returncode == 2 and "error:" in refused.stderr, refused.stderr[-500:]


def test_the_command_set_is_every_tracked_entry_point() -> None:
    """A new command joins `_COMMANDS`: every tracked `tools/*.py` + each package `__main__` or
    module that runs as `__main__` outside the measurement harnesses (those: the replay driver's
    `rerun_all.py::cli_contract`)."""
    listed = subprocess.run(
        ["git", "ls-files", "tools/*.py", "model_backend/*.py", "webui/*.py"],  # noqa: S607
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    entries = set()
    for name in listed:
        if 'if __name__ == "__main__":' not in (_ROOT / name).read_text(encoding="utf-8"):
            continue
        module = name.removesuffix(".py").removesuffix("/__main__").replace("/", ".")
        entries.add((name,) if name.startswith("tools/") else ("-m", module))
    assert entries == set(_COMMANDS)
