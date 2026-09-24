# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Every tracked citation of a demo dataset's sha256 equals that CSV's live digest.

`data/sales.csv`'s digest is pinned in 24 tracked files. The example corpus checks its own share
(`test_examples.py`), but `model_backend/guidance_oracle.py` embeds the digest in a prose task
prompt that nothing pinned: a stale digest there ships green through all eight gate stages. This
suite sweeps `git ls-files` rather than a path list, so a file added later is covered once its
citation resolves to an owner.

THE LAW. A `sha256:<64 lower-case hex>` token in a tracked file that names a tracked `data/*.csv`
equals that dataset's live digest. The owner is the last such CSV name spelled before the token, or,
when none precedes it, the first spelled after it -- so the rule is total over file ORDER and a
citation written above its dataset name cannot hide. The sweep reads BYTES, so a citation inside a
tracked file that is not valid UTF-8 is covered too.

Three exemptions, all BY PATH, and each one PINNED here rather than trusted:

- `.agent/archive/**` cites the digest that was live when it was written, exactly as
  `test_spec.py`'s pointer sweep leaves the archive alone. It is history, so there is nothing to
  repoint at.
- the two deliberate-mismatch fixtures declare a wrong digest to FAIL
  `dataset.hash_matches_source`; the pin below demands they stay NON-LIVE. Keying this by path
  rather than by the all-zeros value is what stops a future vector with a different wrong digest
  from being silently repaired into a passing one.
- `tests/test_canon.py` pins digests of the canonical spec ENCODING, not of any CSV; the pin below
  states its citation set as literals, so a real dataset citation moving in fails here.

What the law does NOT decide, so that it is not read wider than it holds: a citation whose nearest
named CSV is not its real owner, a `data/*.csv` basename outside `[A-Za-z0-9_-]+`, an upper-case or
mixed-case hex token, and a citation split across adjacent source literals. None occurs in the tree;
each would need a different matcher rather than a wider claim.

`tools/rederive_dataset_hashes.py` is the repair, and it states the same law in its own code so that
a defect in one is not inherited by the other.
"""

import hashlib
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_CITATION = re.compile(rb"sha256:[0-9a-f]{64}")
_CSV_NAME = re.compile(rb"[A-Za-z0-9_-]+\.csv")
_DATASET_PATH = re.compile(r"data/[A-Za-z0-9_-]+\.csv")
_MISMATCH_FIXTURES = (
    "examples/bad_specs/b08_dataset_hash_mismatch.json",
    "examples/formula_bad_specs/fb02_dataset_key.json",
)
# This file is exempt for the same reason test_canon.py is, and the reason is worth naming: the
# literals below are that file's digests, hand-stated HERE as its pin, so writing them down turns
# this module into a citation site for the very sweep it defines. Its own literals are pinned by
# equality against tests/test_canon.py, which is what the last test asserts.
_NOT_DATASET_DIGESTS = ("tests/test_canon.py", "tests/test_dataset_digests.py")
_HISTORY = ".agent/archive/"
# Floor against a vacuous sweep: a resolver defect that finds nothing would otherwise pass.
_SALES_CITATION_FLOOR = 24

# Hand-stated so the exemption cannot absorb a real dataset citation. These are digests of the
# canonical spec ENCODING; an addition or a removal must be re-audited rather than re-derived.
_CANON_DIGESTS = frozenset(
    {
        "sha256:05053f5c55599b847c3fdb3c738931372706cdc33f08ebf6cd337c7713fe8533",
        "sha256:4f8e01a5645ff7807c62c71cadc220a21a3f7641cdd48cd700cbcfb9036208b9",
        "sha256:634e8a9bdf628b0f8b0cf99ef6cb45167ec882450dff4e77a1492860d8472160",
        "sha256:6b9268d3f0f95dd8ce488d3bc2dce35469ea29b9674d67d5c4b9ff3cc6376ad8",
        "sha256:72bbc5136f489b7201c3903aed10feac1764f370b9869bdfe78992e75eb9d025",
        "sha256:990615ee353d3f4c534c141cf3ff993cbee0b15a9453806d9f8fd3b31c6cbe67",
        "sha256:9dfeb1d5e76632ef38f20fe2a630e49ea5a3ac2ab4d9780b4fb127db8740810e",
        "sha256:c9a6a1659e5630d59717f5f87f8148c765d8bf0c9e3dec86cf64311e17f82bb8",
        "sha256:d31b9cba88803946e945969c0b1d01acc8011af7af678f8fbfb80a1b193c606d",
        "sha256:e36a4396d094f0bb92d48d9a72ad8c51902953e06573baeefaff829fce85d29c",
    }
)


def _tracked_names() -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 -- fixed literal argv
        cwd=_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return [name for name in listing.split("\0") if name]


def _live_digests() -> dict[bytes, bytes]:
    """Every TRACKED `data/*.csv` by basename. An untracked one is not a truth source."""
    return {
        path.name.encode(): b"sha256:" + hashlib.sha256(path.read_bytes()).hexdigest().encode()
        for path in sorted(
            _ROOT / name for name in _tracked_names() if _DATASET_PATH.fullmatch(name)
        )
    }


def _tracked_blobs() -> list[tuple[str, bytes]]:
    blobs: list[tuple[str, bytes]] = []
    for name in _tracked_names():
        try:
            blobs.append((name, (_ROOT / name).read_bytes()))
        except OSError:
            continue
    return blobs


def _owner(raw: bytes, start: int, live: dict[bytes, bytes]) -> bytes | None:
    """The dataset a citation at `start` belongs to: last named before it, else first after it."""
    before: list[bytes] = [n for n in _CSV_NAME.findall(raw[:start]) if n in live]
    if before:
        return before[-1]
    after: list[bytes] = [n for n in _CSV_NAME.findall(raw[start:]) if n in live]
    return after[0] if after else None


def _exempt(name: str) -> bool:
    return name.startswith(_HISTORY) or name in _NOT_DATASET_DIGESTS or name in _MISMATCH_FIXTURES


def _citations() -> list[tuple[str, bytes, bytes]]:
    """Every (file, dataset, citation) the law covers, over every tracked file's raw bytes."""
    live = _live_digests()
    found: list[tuple[str, bytes, bytes]] = []
    for name, raw in _tracked_blobs():
        if _exempt(name):
            continue
        for match in _CITATION.finditer(raw):
            owner = _owner(raw, match.start(), live)
            if owner is None:
                continue
            found.append((name, owner, match.group()))
    return found


def test_every_tracked_dataset_digest_is_live() -> None:
    live = _live_digests()
    citations = _citations()
    stale = [
        f"{name} cites {cited.decode()} for {dataset.decode()}, live is {live[dataset].decode()}"
        for name, dataset, cited in citations
        if cited != live[dataset]
    ]
    assert stale == []
    sales = [c for c in citations if c[1] == b"sales.csv"]
    assert len(sales) >= _SALES_CITATION_FLOOR


def test_the_owner_rule_is_total_over_file_order() -> None:
    # A citation written ABOVE its dataset name resolves to that dataset, not to nothing. With the
    # "last name before it" clause alone, such a token is skipped and a stale digest there survives
    # both this sweep and the repair script.
    live = _live_digests()
    stale = b"sha256:" + b"f" * 64
    below = b'{"name": "sales.csv", "hash": "' + stale + b'"}'
    above = b'{"hash": "' + stale + b'", "name": "sales.csv"}'
    for raw in (below, above):
        match = _CITATION.search(raw)
        assert match is not None
        assert _owner(raw, match.start(), live) == b"sales.csv"
    # A file naming no tracked CSV owns no citation, which is what leaves both lockfiles alone.
    orphan = b'"digest": "' + stale + b'"'
    orphan_match = _CITATION.search(orphan)
    assert orphan_match is not None
    assert _owner(orphan, orphan_match.start(), live) is None


def test_only_a_tracked_dataset_is_a_truth_source() -> None:
    # A stray untracked `data/*.csv` must not become an owner. It would make this sweep's verdict
    # depend on the working tree, and it would make `rederive_dataset_hashes.py` write a tracked
    # citation from an untracked file -- which is exactly the replayable-from-a-clean-base
    # guarantee X2 states.
    intruder = _ROOT / "data" / "not-tracked-review-probe.csv"
    baseline = _live_digests()
    intruder.write_bytes(b"region,revenue\nEU,1\n")
    try:
        assert _live_digests() == baseline
    finally:
        intruder.unlink()
    assert intruder.name.encode() not in baseline


def test_the_mismatch_fixtures_keep_a_non_live_digest() -> None:
    # b08 and fb02 exist to FAIL dataset.hash_matches_source. A re-derivation that repaired them
    # would delete the only negative case the check has, and every suite would stay green. The
    # demand is NON-LIVE rather than all-zeros: the exemption is keyed by path, so a vector
    # rewritten with some other wrong digest stays a valid negative and stays covered here.
    live = set(_live_digests().values())
    for name in _MISMATCH_FIXTURES:
        raw = (_ROOT / name).read_bytes()
        cited = _CITATION.findall(raw)
        assert cited, f"{name} carries no digest citation at all"
        assert set(cited) & live == set()


def test_the_exempt_file_cites_exactly_its_canonical_digests() -> None:
    # The exemption holds only while tests/test_canon.py's digests are all of canonical BYTES. An
    # exact literal set is what catches a STALE dataset citation moving in: a stale digest equals no
    # LIVE digest, so a "cites nothing live" pin would pass it through.
    live = set(_live_digests().values())
    for name in _NOT_DATASET_DIGESTS:
        raw = (_ROOT / name).read_bytes()
        cited = {token.decode() for token in _CITATION.findall(raw)}
        assert cited == _CANON_DIGESTS
        assert {token.encode() for token in cited} & live == set()
