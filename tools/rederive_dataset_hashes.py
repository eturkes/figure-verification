# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Re-derive every tracked `sha256:` citation of a `data/*.csv` from that CSV's own bytes.

One edit to a demo dataset invalidates its digest in 25 tracked files at once: 23 example specs,
`examples/index.json`, a prose task prompt and a minified runtime golden. Replaying that by hand is
how a stale digest survives in the one file nobody greps. This script recomputes each citation from
the CSV it names, so the repair is idempotent and replayable from a clean base rather than a
remembered hex string -- run it on an already-correct tree and it writes nothing at all.

Binding rule, textual and total: a citation belongs to the LAST `<name>.csv` spelled before it in
the same file. That covers every shape the repo uses -- a JSON `dataset` object naming `name` one
line above `hash`, `examples/index.json`'s `datasets` array, `model_backend/guidance_oracle.py`'s
prose task prompt, `webui/model_stub.py`'s minified reply -- and it resolves to no dataset at all in
the files citing digests of other things (both lockfiles), which are left untouched. A file naming
no tracked CSV is skipped before any citation is read.

Three skips. `.agent/archive/**` is skipped because an archived record legitimately cites the digest
that was live when it was written -- re-deriving one would rewrite history, which is the same reason
`tests/test_spec.py`'s pointer sweep leaves the archive alone. The other two are measured rather
than assumed. `sha256:0000...` is skipped BY VALUE:
`examples/bad_specs/b08_dataset_hash_mismatch.json` and
`examples/formula_bad_specs/fb02_dataset_key.json` declare it on purpose, to fail the
`dataset.hash_matches_source` check, so re-deriving it would delete the negative case.
`tests/test_canon.py` is skipped BY PATH: it names `sales.csv` and then pins eleven digests of the
CANONICAL SPEC BYTES, which are digests of an encoding and not of any CSV. Of the 33 tracked files
that both name a dataset and cite a digest, it is the only one whose citations are not dataset
digests, and all eleven of its citations are non-live.

`tests/test_dataset_digests.py` states the same law independently and pins every clause of it,
including that the skipped file cites no live dataset digest.
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
_CSV_NAME = re.compile(r"[A-Za-z0-9_-]+\.csv")
_MISMATCH_FIXTURE = "sha256:" + "0" * 64
_NOT_DATASET_DIGESTS = ("tests/test_canon.py",)
_HISTORY = ".agent/archive/"


@cache
def _live_digest(name: str) -> str | None:
    """The live `sha256:` citation for `data/<name>`, or None when no such dataset is tracked."""
    path = _DATA / name
    if not path.is_file():
        return None
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _rederive(text: str) -> tuple[str, int]:
    """Return the text with every dataset citation re-derived, plus how many citations moved."""
    if not _CSV_NAME.search(text):
        return text, 0
    pieces: list[str] = []
    cursor = 0
    moved = 0
    for match in _CITATION.finditer(text):
        names = _CSV_NAME.findall(text, 0, match.start())
        if match.group() == _MISMATCH_FIXTURE or not names:
            continue
        live = _live_digest(names[-1])
        if live is None or live == match.group():
            continue
        pieces.append(text[cursor : match.start()])
        pieces.append(live)
        cursor = match.end()
        moved += 1
    pieces.append(text[cursor:])
    return "".join(pieces), moved


def _tracked_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 -- fixed literal argv
        cwd=_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return [_ROOT / name for name in listing.split("\0") if name]


def main() -> int:
    moved_total = 0
    report: list[str] = []
    for path in _tracked_files():
        name = path.relative_to(_ROOT).as_posix()
        if name in _NOT_DATASET_DIGESTS or name.startswith(_HISTORY):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rewritten, moved = _rederive(text)
        if moved:
            path.write_text(rewritten, encoding="utf-8")
            report.append(f"{name} {moved}\n")
            moved_total += moved
    sys.stdout.writelines(report)
    sys.stdout.write(f"re-derived {moved_total} citation(s) across {len(report)} file(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
