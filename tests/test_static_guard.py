# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""G1: the verification core remains independent of captured proposer prompts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from capture.corpus import CAPTURE_PROMPT_SHA256, CORPUS_ROOT, REPO_ROOT, load_corpus


def _core_sources() -> tuple[Path, ...]:
    listed = subprocess.check_output(
        ["/usr/bin/git", "ls-files", "-z", "--", "src/verifier"], cwd=REPO_ROOT
    )
    files = tuple(REPO_ROOT / Path(os.fsdecode(raw)) for raw in listed.split(b"\0") if raw)
    assert files and any(path.name == "admit.py" for path in files)
    return files


def test_g1_verification_core_holds_no_prompt_text() -> None:
    """G1: no template line, template digest or corpus prompt occurs in tracked core source."""
    template = (CORPUS_ROOT / "capture_prompt_v1.txt").read_text(encoding="utf-8")
    lines = [(number, line) for number, line in enumerate(template.splitlines(), 1) if line.strip()]
    corpus = load_corpus()
    prompts = tuple(prompt for _kind, prompt in corpus.rows())
    assert lines and prompts
    for path in _core_sources():
        source = path.read_bytes()
        name = path.relative_to(REPO_ROOT)
        if CAPTURE_PROMPT_SHA256.encode("ascii") in source:
            pytest.fail(f"{name}: capture prompt digest appears in the verification core")
        for number, line in lines:
            if line.encode("utf-8") in source:
                pytest.fail(f"{name}: capture template line {number} appears in the core")
        for prompt in prompts:
            if prompt.prompt.encode("utf-8") in source:
                pytest.fail(f"{name}: corpus row {prompt.id} appears in the core")
