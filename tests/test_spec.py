# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""S1-S6: liveness invariants of the attached state.

`.agent/spec.md` is imported by CLAUDE.md, so MAIN and every teammate hold it from session start
and read every line as current law. Liveness itself is a judgment no test can make. What IS
decidable is whether the file still points at things that exist, and a dead row is the one most
likely to point at something that does not: a retired corpus, an unwritten archive record, a
deferral whose acceptance check was never stated. Also decidable is which section a row sits in,
which is what keeps the spine in one place (S6).

The pointer sweep skips `Accept:` clauses -- a deferral names the artifact it will CREATE, so
those paths stay absent by design until the row closes.

Each expectation is hand-stated rather than read back from the artifact it guards. This file
imports no `verifier` symbol: coverage source stays `verifier` only.
"""

import re
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC = _REPO_ROOT / ".agent" / "spec.md"
_DEFERRED = _REPO_ROOT / ".agent" / "deferred.md"
_CONTRACTS = _REPO_ROOT / ".agent" / "contracts"
_ARCHIVE_CONTRACTS = _REPO_ROOT / ".agent" / "archive" / "contracts"

_GIT = shutil.which("git")

_EXPECTED_SECTIONS = ("Intent", "Artifacts", "Decisions", "Deferred", "Phase")

# Roots whose contents are tracked, so a pointer at one either resolves or is dead. Bare `corpus/`
# and `bench/` stay out: rows legitimately name run outputs that no commit carries.
_POINTER_ROOTS = (".agent/", ".claude/rules/", "docs/")

# A gitignored runtime env, built by `uv sync` rather than committed, so `git ls-files` never
# lists it and the Artifacts entry naming its interpreter is still live.
_UNTRACKED_BY_DESIGN = frozenset({".venv-model/bin/python"})

_PLACEHOLDER = ("<", "…", "*", "?")

# Unit ids carry an optional letter suffix (`M12.6b` closed with `m12u6b.md`), and a pattern
# without it reads `M12.6b CLOSED` as `M12.6` followed by junk: S5 then skips the unit and S6
# reads it as open.
_UNIT = re.compile(r"M(\d+)\.(\d+)([a-z]?)")


def _tracked() -> frozenset[str]:
    assert _GIT is not None, "git is absent from PATH"
    completed = subprocess.run(  # noqa: S603
        [_GIT, "ls-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(completed.stdout.splitlines())


def _resolves(token: str, tracked: frozenset[str]) -> bool:
    if token in tracked or token in _UNTRACKED_BY_DESIGN:
        return True
    prefix = token.rstrip("/") + "/"
    return any(path.startswith(prefix) for path in tracked)


def _path_tokens(text: str) -> list[str]:
    """Backticked words naming a repo path: a `/` or an `.md` tail, no placeholder, no URL."""
    tokens: list[str] = []
    for span in re.findall(r"`([^`]+)`", text):
        for word in span.split():
            token = word.rstrip(".,;:")
            if "://" in token or any(char in token for char in _PLACEHOLDER):
                continue
            if "/" in token or token.endswith(".md"):
                tokens.append(token)
    return tokens


def _closed(section: str, unit: re.Match[str]) -> bool:
    """Emphasis is stripped with the whitespace: `Deferred` writes its unit ids as `**M13.3**`
    headings, so a tail test that stops at `**` is blind in the one form the section uses."""
    return section[unit.end() :].lstrip("* \t\n").startswith("CLOSED")


def _section(name: str) -> str:
    text = _SPEC.read_text(encoding="utf-8")
    body = re.search(rf"^## {name}$\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert body is not None, f"section {name!r} missing from spec.md"
    return body.group(1)


def test_s1_spec_carries_the_five_sections_in_order() -> None:
    """S1: the attached state keeps its five sections, in order. Acceptance: a renamed, dropped
    or reordered `## ` heading fails -- a reader orienting from spec.md navigates by them."""
    headings = tuple(re.findall(r"^## (.+)$", _SPEC.read_text(encoding="utf-8"), re.MULTILINE))
    assert headings == _EXPECTED_SECTIONS


def test_s2_every_artifacts_path_is_tracked() -> None:
    """S2: every path `Artifacts` names is committed. Acceptance: a renamed or deleted artifact
    leaves a run command no session can execute, and fails here."""
    tracked = _tracked()
    tokens = _path_tokens(_section("Artifacts"))
    assert tokens, "no paths found in Artifacts"
    dangling = [token for token in tokens if not _resolves(token, tracked)]
    assert not dangling, f"Artifacts names untracked paths: {dangling}"


def test_s3_every_deferral_carries_an_acceptance_check() -> None:
    """S3: each queue row states what would close it. Acceptance: a row with no `Accept:` fails
    -- an acceptance check written later is written without the evidence that motivated it."""
    rows = [line for line in _DEFERRED.read_text(encoding="utf-8").splitlines() if line[:2] == "- "]
    assert rows, "no deferral rows found"
    missing = [row[:60] for row in rows if "Accept:" not in row]
    assert not missing, f"deferral rows with no acceptance check: {missing}"


def test_s4_every_rules_docs_and_archive_pointer_resolves() -> None:
    """S4: rules, docs and archive pointers in the attached state resolve. Acceptance: a moved or
    deleted target fails -- the pointer is how detail stays out of spec.md, so a dead one silently
    deletes the detail instead of relocating it."""
    tracked = _tracked()
    dangling: list[str] = []
    for path in (_SPEC, _DEFERRED):
        for line in path.read_text(encoding="utf-8").splitlines():
            live, _, _ = line.partition("Accept:")
            dangling += [
                f"{path.name}: {token}"
                for token in _path_tokens(live)
                if token.startswith(_POINTER_ROOTS) and not _resolves(token, tracked)
            ]
    assert not dangling, f"dangling pointers: {dangling}"


def test_s5_every_closed_unit_has_its_contract_archived() -> None:
    """S5: a unit marked CLOSED in `Phase` finished its close. Acceptance: a contract still in
    `.agent/contracts/`, or missing from `.agent/archive/contracts/`, fails -- CLOSED in the
    attached state and an unmoved contract are the same green until this fires."""
    phase = _section("Phase")
    units = [match.groups() for match in _UNIT.finditer(phase) if _closed(phase, match)]
    assert units, "no closed units found in Phase"
    unfinished: list[str] = []
    for milestone, unit, suffix in units:
        name = f"m{milestone}u{unit}{suffix}.md"
        if not (_ARCHIVE_CONTRACTS / name).exists():
            unfinished.append(f"{name} absent from .agent/archive/contracts/")
        if (_CONTRACTS / name).exists():
            unfinished.append(f"{name} still in .agent/contracts/")
    assert not unfinished, unfinished


def test_s6_the_spine_lives_in_deferred_and_phase_records_only_closed_units() -> None:
    """S6: `Deferred` owns the unfinished units -- the spine -- and `Phase` records the phase plus
    the units already closed. Acceptance: a unit written into `Phase` without CLOSED fails, and so
    does a unit marked CLOSED inside `Deferred`; either one splits what is left to do across two
    sections, and a reader navigating to one of them reads a spine that is missing a unit."""
    phase, deferred = _section("Phase"), _section("Deferred")
    open_in_phase = [m.group(0) for m in _UNIT.finditer(phase) if not _closed(phase, m)]
    assert not open_in_phase, f"Phase names units that are not CLOSED: {open_in_phase}"
    closed_in_deferred = [m.group(0) for m in _UNIT.finditer(deferred) if _closed(deferred, m)]
    assert not closed_in_deferred, f"Deferred names closed units: {closed_in_deferred}"
