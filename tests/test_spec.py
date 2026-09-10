# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""S1-S7: liveness invariants of the attached state and the law surface around it.

`.agent/spec.md` is imported by CLAUDE.md, so MAIN and every teammate hold it from session start
and read every line as current law. Liveness itself is a judgment no test can make. What IS
decidable is whether the file still points at things that exist, and a dead row is the one most
likely to point at something that does not: a retired corpus, an unwritten archive record, a
deferral whose acceptance check was never stated. Also decidable is which section a row sits in,
which is what keeps the spine in one place (S6).

The pointer sweep skips `Accept:` clauses -- a deferral names the artifact it will CREATE, so
those paths stay absent by design until the row closes.

S4 and S7 sweep past `spec.md` itself, each as far as its question stays decidable. S4 adds the
ledger and the scope sources, which carry pointers that strand exactly as the spec's do, and stops
at `.agent/archive/**`, where a record legitimately names a file since deleted outright. S7 covers
every tracked file, archived records included, because its target does not vanish -- closing a unit
MOVES the contract, so a citation of the pre-archive path always has somewhere correct to point.
Neither covers `.claude/rules/*.md`; that gap is queued, not overlooked.

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
_REVIEW = _REPO_ROOT / ".agent" / "review.md"

# S4's sweep: the attached state, the queue and ledger CLAUDE.md binds beside it, and the two
# scope sources `ops.md` names. This is NOT all live law -- `.claude/rules/*.md` carries project
# law and stays out, because those files cite by bare basename (`ops.md`, `oracle.py`) and by
# brace aggregate (`.agent/archive/{roadmap,polish,memory}.md`), neither of which this resolver
# reads; widening to them is queued in `.agent/deferred.md`. Archived records stay out for a
# different reason: a retired unit legitimately names a file later deleted outright, so there is
# nothing to repoint at and history being history would fail the sweep.
_POINTER_SURFACE = (
    _SPEC,
    _DEFERRED,
    _REVIEW,
    _REPO_ROOT / "POC_SCOPE.md",
    _REPO_ROOT / "VPlot_SEMANTICS.md",
)
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

# A token carrying one of these names a SET of paths, not a path: a shape (`<unit>.md`), a glob
# (`m13*.md`) or a brace aggregate (`.agent/archive/{roadmap,polish,memory}.md`). Resolving one
# means expanding it, which this resolver does not do, so it is skipped rather than reported dead.
_PLACEHOLDER = ("<", "…", "*", "?", "{")

# Unit ids carry an optional letter suffix (`M12.6b` closed with `m12u6b.md`), and a pattern
# without it reads `M12.6b CLOSED` as `M12.6` followed by junk: S5 then skips the unit and S6
# reads it as open.
_UNIT = re.compile(r"M(\d+)\.(\d+)([a-z]?)")

# A contract citation names one of the two directories S5 moves a contract between. The character
# class admits no `<` and no `*`, so a shape token and a `paths:` glob are not citations. The two
# lookaheads make the match end where the citation ends: without them a prefix match wins, and
# `<id>.md.bak`, `<id>.md2` or `<id>.md/child` -- none of them files -- each collapse onto the
# tracked `<id>.md` and report green for a path nothing carries.
_CONTRACT_CITATION = re.compile(
    r"\.agent/(?:archive/)?contracts/[A-Za-z0-9][A-Za-z0-9_.-]*\.md(?![A-Za-z0-9_/-])(?!\.[A-Za-z0-9])"
)


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
    """S4: rules, docs and archive pointers in the attached state, the ledger and the scope
    sources resolve. Acceptance: a moved or deleted target fails -- the pointer is how detail
    stays out of the citing file, so a dead one silently deletes the detail instead of relocating
    it."""
    tracked = _tracked()
    dangling: list[str] = []
    for path in _POINTER_SURFACE:
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


def test_s7_every_contract_citation_survives_the_archive_move() -> None:
    """S7: every contract path a tracked file cites is itself tracked. Acceptance: a citation left
    at the pre-archive path fails -- S5 makes the close MOVE the contract, and that move is what
    strands the citations, so the two checks are green together only when the close finished."""
    tracked = _tracked()
    stranded: list[str] = []
    for name in sorted(tracked):
        try:
            text = (_REPO_ROOT / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # a tracked binary carries no citation
            continue
        stranded += [
            f"{name}: {token}" for token in _CONTRACT_CITATION.findall(text) if token not in tracked
        ]
    assert not stranded, f"stranded contract citations: {stranded}"
