# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Re-derive every tracked `sha256:` citation of a `data/*.csv` from that CSV's own bytes.

One edit to a demo dataset invalidates its digest in 25 tracked files at once: 23 example specs,
`examples/index.json`, a prose task prompt and a minified runtime golden. Replaying that by hand is
how a stale digest survives in the one file nobody greps. This script recomputes each citation from
the CSV it names, so the repair is idempotent and replayable from a clean base rather than a
remembered hex string -- run it on an already-correct tree and it writes nothing at all.

OWNER RULE: a citation belongs to the last tracked `<name>.csv` spelled before it in the same file,
or, when none precedes it, to the first spelled after it. The second clause is what makes the rule
total over file ORDER: with the "before" clause alone, a citation written above its dataset name is
silently skipped, and a stale digest there survives both this script and its validator. No tracked
file has that shape today, so the clause moves nothing and exists to keep the law true. A file
naming no tracked CSV resolves to no owner and is left untouched, which is what leaves both
lockfiles alone.

Three skips, all BY PATH, because a by-value skip cannot tell a deliberate fixture from a defect:

- `.agent/archive/**` -- an archived record legitimately cites the digest that was live when it was
  written, the same reason `tests/test_spec.py`'s pointer sweep leaves the archive alone.
- the two deliberate-mismatch fixtures -- they declare a wrong digest on purpose, to FAIL
  `dataset.hash_matches_source`. Scoping this by PATH rather than by the all-zeros VALUE matters: a
  future vector written with a different wrong digest would otherwise be "repaired" into a passing
  one, deleting the only negative case the check has.
- `tests/test_canon.py` -- it names `sales.csv` and then pins digests of the canonical spec
  ENCODING, which are digests of an encoding and not of any CSV.

`tests/test_dataset_digests.py` states the same law independently, pins every clause of it, and
sweeps BYTES so that a citation inside a non-UTF-8 tracked file is still covered. This script reads
text because it must write text back; a tracked file that carries a citation and does not decode as
UTF-8 is REPORTED and makes the run exit nonzero, rather than being skipped in silence.

What this rule does NOT decide, stated so the guarantee is not read wider than it is: a citation
whose nearest preceding CSV name is not its real owner, a `data/*.csv` basename outside
`[A-Za-z0-9_-]+`, an upper-case or mixed-case hex token, and a citation split across adjacent source
literals. None occurs in the tree today; each would need a different matcher, not a wider claim.
"""

import hashlib
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"

_CITATION = re.compile(r"sha256:[0-9a-f]{64}")
_CITATION_BYTES = re.compile(rb"sha256:[0-9a-f]{64}")
_CSV_NAME = re.compile(r"[A-Za-z0-9_-]+\.csv")
_DATASET_PATH = re.compile(r"data/[A-Za-z0-9_-]+\.csv")
# Declared wrong on purpose, to fail `dataset.hash_matches_source`. Skipped by PATH, never by value.
_MISMATCH_FIXTURES = (
    "examples/bad_specs/b08_dataset_hash_mismatch.json",
    "examples/formula_bad_specs/fb02_dataset_key.json",
)
# Digests of the canonical spec ENCODING, not of a CSV. `test_canon.py` names sales.csv for its
# fixtures; `test_dataset_digests.py` hand-states test_canon.py's digests as the pin that keeps the
# exemption honest, which makes writing them down turn the pin itself into a citation site.
_NOT_DATASET_DIGESTS = ("tests/test_canon.py", "tests/test_dataset_digests.py")
_HISTORY = ".agent/archive/"


@cache
def _live_digest(name: str) -> str | None:
    """The live `sha256:` citation for `data/<name>`, or None when no such dataset is tracked.

    TRACKED, not merely present: reading an untracked `data/*.csv` would let a stray local file
    steer what this script writes into tracked ones, and the repair stops being replayable from a
    clean base.
    """
    if f"data/{name}" not in _tracked_datasets():
        return None
    return "sha256:" + hashlib.sha256((_DATA / name).read_bytes()).hexdigest()


def _owner(text: str, start: int) -> str | None:
    """The dataset a citation at `start` belongs to: last named before it, else first after it."""
    names = _CSV_NAME.findall(text, 0, start)
    before: list[str] = [n for n in names if _live_digest(n) is not None]
    if before:
        return before[-1]
    after: list[str] = [n for n in _CSV_NAME.findall(text, start) if _live_digest(n) is not None]
    return after[0] if after else None


def _rederive(text: str) -> tuple[str, int]:
    """Return the text with every dataset citation re-derived, plus how many citations moved."""
    if not _CSV_NAME.search(text):
        return text, 0
    pieces: list[str] = []
    cursor = 0
    moved = 0
    for match in _CITATION.finditer(text):
        owner = _owner(text, match.start())
        if owner is None:
            continue
        live = _live_digest(owner)
        if live is None or live == match.group():
            continue
        pieces.append(text[cursor : match.start()])
        pieces.append(live)
        cursor = match.end()
        moved += 1
    pieces.append(text[cursor:])
    return "".join(pieces), moved


def _skipped(name: str) -> bool:
    return name.startswith(_HISTORY) or name in _NOT_DATASET_DIGESTS or name in _MISMATCH_FIXTURES


@cache
def _tracked_names() -> tuple[str, ...]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 -- fixed literal argv
        cwd=_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return tuple(name for name in listing.split("\0") if name)


@cache
def _tracked_datasets() -> frozenset[str]:
    return frozenset(name for name in _tracked_names() if _DATASET_PATH.fullmatch(name))


def main() -> int:
    moved_total = 0
    report: list[str] = []
    unreadable: list[str] = []
    for name in _tracked_names():
        if _skipped(name):
            continue
        path = _ROOT / name
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if not _CITATION_BYTES.search(raw):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            unreadable.append(name)
            continue
        rewritten, moved = _rederive(text)
        if moved:
            path.write_text(rewritten, encoding="utf-8")
            report.append(f"{name} {moved}\n")
            moved_total += moved
    sys.stdout.writelines(report)
    sys.stdout.write(f"re-derived {moved_total} citation(s) across {len(report)} file(s)\n")
    if unreadable:
        sys.stderr.write(
            "citations in tracked files this script cannot rewrite as UTF-8 text; repair them by "
            f"hand: {', '.join(unreadable)}\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
