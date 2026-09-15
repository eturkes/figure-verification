# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Every tracked citation of a demo dataset's sha256 equals that CSV's live digest.

`data/sales.csv`'s digest is pinned in 25 tracked files. The example corpus checks its own share
(`test_examples.py`) and `webui/model_stub.py` rides g01's golden, but
`model_backend/guidance_oracle.py` embeds the digest in a prose task prompt that nothing pinned: a
stale digest there ships green through all eight gate stages. This suite sweeps `git ls-files`
rather than a path list, so a file added later is covered on the day it lands.

The law, total over the LIVE tree: a `sha256:<64 hex>` token in a file that NAMES a tracked
`data/*.csv` is that dataset's live digest, or the all-zeros deliberate-mismatch fixture. Measured
at the unit that wrote this: 33 tracked files both name a dataset and cite a digest, and 32 obey the
law outright. The one exception is `tests/test_canon.py`, whose eleven citations are digests of the
CANONICAL SPEC BYTES rather than of any CSV; it is exempt by path and the exemption is pinned below
by asserting it cites no live dataset digest at all, so a real citation moving into it fails.
`.agent/archive/**` is out of scope for a different reason: an archived record legitimately cites
the digest that was live when it was written, exactly as `test_spec.py`'s pointer sweep leaves the
archive alone.

`tools/rederive_dataset_hashes.py` is the repair, and it states the same law in its own code so
that a defect in one is not inherited by the other.
"""

import hashlib
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"

_CITATION = re.compile(r"sha256:[0-9a-f]{64}")
_CSV_NAME = re.compile(r"[A-Za-z0-9_-]+\.csv")
_MISMATCH_FIXTURE = "sha256:" + "0" * 64
# Digests of the canonical spec ENCODING, not of a CSV; the file names sales.csv for its fixtures.
_NOT_DATASET_DIGESTS = ("tests/test_canon.py",)
_HISTORY = ".agent/archive/"
# Floor against a vacuous sweep: a resolver defect that finds nothing would otherwise pass.
_SALES_CITATION_FLOOR = 25


def _live_digests() -> dict[str, str]:
    return {
        path.name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(_DATA.glob("*.csv"))
    }


def _tracked_text_files() -> list[tuple[str, str]]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 -- fixed literal argv
        cwd=_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    files: list[tuple[str, str]] = []
    for name in listing.split("\0"):
        if not name:
            continue
        try:
            files.append((name, (_ROOT / name).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return files


def _citations() -> list[tuple[str, str, str]]:
    """Every (file, dataset, citation) the law covers; the dataset is the last CSV named before
    the citation."""
    live = _live_digests()
    found: list[tuple[str, str, str]] = []
    for name, text in _tracked_text_files():
        if name in _NOT_DATASET_DIGESTS or name.startswith(_HISTORY):
            continue
        for match in _CITATION.finditer(text):
            named = [n for n in _CSV_NAME.findall(text, 0, match.start()) if n in live]
            if not named or match.group() == _MISMATCH_FIXTURE:
                continue
            found.append((name, named[-1], match.group()))
    return found


def test_every_tracked_dataset_digest_is_live() -> None:
    live = _live_digests()
    citations = _citations()
    stale = [
        f"{name} cites {cited} for {dataset}, live is {live[dataset]}"
        for name, dataset, cited in citations
        if cited != live[dataset]
    ]
    assert stale == []
    sales = [c for c in citations if c[1] == "sales.csv"]
    assert len(sales) >= _SALES_CITATION_FLOOR


def test_the_mismatch_fixtures_keep_the_zero_digest() -> None:
    # b08 and fb02 exist to FAIL dataset.hash_matches_source. A re-derivation that repaired them
    # would delete the only negative case the check has, and every suite would stay green.
    fixtures = (
        _ROOT / "examples/bad_specs/b08_dataset_hash_mismatch.json",
        _ROOT / "examples/formula_bad_specs/fb02_dataset_key.json",
    )
    for path in fixtures:
        assert _MISMATCH_FIXTURE in path.read_text(encoding="utf-8")
    assert _MISMATCH_FIXTURE not in _live_digests().values()


def test_the_exempt_file_cites_no_live_dataset_digest() -> None:
    # The exemption holds only while tests/test_canon.py's digests are all of canonical BYTES. A
    # live dataset digest appearing there makes it a real citation site that the sweep must cover.
    live = set(_live_digests().values())
    for name in _NOT_DATASET_DIGESTS:
        text = (_ROOT / name).read_text(encoding="utf-8")
        assert _CITATION.search(text) is not None
        assert set(_CITATION.findall(text)) & live == set()
