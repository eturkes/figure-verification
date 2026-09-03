# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Content pin for the gitignored model snapshot — manifest form, verifier, regeneration.

The weights tree (`models/<name>/`) is too large to track, so its identity is tracked instead:
`model_backend/runtime/snapshot.json` pins the HF repo id, the revision SHA and one
{sha256, size} pair per revision file. `--verify` re-derives that pin from disk; `--write`
regenerates the manifest from the tree.

Fail classes stay DISJOINT and are reported together — `missing` | `mismatched` | `unexpected` |
`unreadable`, never one boolean: each names a different wrong thing, and a merged verdict would
report content drift for a path whose bytes were never observed. Verification continues past every
fault, so one run diagnoses the whole tree.

Symlinks are never followed. A pinned path must be a REGULAR file; a symlink standing where a
pinned file belongs is `mismatched` however its target reads, and a symlink that is not pinned is
`unexpected`. `.cache/` directories at any depth are skipped — hf_hub writes download metadata
below the snapshot root that is not part of the revision.

Interpreter = the ROOT `.venv` (py3.13): stdlib + msgspec only. Importing `torch`, `transformers`,
`xgrammar` or `huggingface_hub` here would bind the gate to the py3.12 runtime venv, so those stay
out. Fetching the snapshot is a documented operator step (`model_backend/runtime/README.md`), never
a gate step.
"""

import argparse
import hashlib
import json
import re
import stat
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Final, cast

import msgspec

SNAPSHOT_MANIFEST_PATH: Final[Path] = Path("model_backend/runtime/snapshot.json")
SNAPSHOT_ROOT: Final[Path] = Path("models/Qwen2.5-Coder-0.5B-Instruct")
SNAPSHOT_REPO_ID: Final = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
SNAPSHOT_REVISION: Final = "ea3f2471cf1b1f0db85067f1ef93848e38e88c25"

# hf_hub download bookkeeping lands under this directory name; it is not revision content.
_CACHE_DIR_NAME: Final = ".cache"
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
# Exit codes: 1 = the tree disagrees with the manifest, 2 = the manifest itself is unusable.
_EXIT_FAULTS: Final = 1
_EXIT_MANIFEST: Final = 2


class ManifestError(ValueError):
    """The manifest itself is unusable, so no tree state can be reported against it."""


class FileEntry(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One pinned revision file. Both fields are compared; a size disagreement is a mismatch."""

    sha256: str
    size: int


class Manifest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """The committed pin: repo identity plus every revision file, keyed by relative POSIX path."""

    repo_id: str
    revision: str
    files: dict[str, FileEntry]


class VerifyReport(msgspec.Struct, frozen=True, kw_only=True):
    """Four disjoint fault sets over one tree, each sorted so a run is byte-reproducible."""

    missing: tuple[str, ...]
    mismatched: tuple[str, ...]
    unexpected: tuple[str, ...]
    unreadable: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """True only when every fault set is empty."""
        return not (self.missing or self.mismatched or self.unexpected or self.unreadable)


_MANIFEST_DECODER: Final = msgspec.json.Decoder(Manifest)


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Refuse duplicate object keys, which stdlib json and msgspec both resolve last-win."""
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            message = f"duplicate manifest key {key!r}"
            raise ManifestError(message)
        seen.add(key)
    return dict(pairs)


def _relative_key_fault(relative: str) -> str | None:
    """Name why a manifest key may not address a file under the snapshot root, else None."""
    if not relative:
        return "is empty"
    pure = PurePosixPath(relative)
    if pure.is_absolute():
        return "is absolute"
    if ".." in pure.parts:
        return "contains a '..' component"
    if pure.as_posix() != relative:
        return "is not a normalized relative POSIX path"
    return None


def _validate_manifest(manifest: Manifest, path: Path) -> None:
    """Refuse every manifest a verification run could not answer for, before touching the tree."""
    if not manifest.files:
        message = f"snapshot manifest {path} pins no files"
        raise ManifestError(message)
    for relative, entry in manifest.files.items():
        fault = _relative_key_fault(relative)
        if fault is not None:
            message = f"snapshot manifest {path} key {relative!r} {fault}"
            raise ManifestError(message)
        if _SHA256_PATTERN.fullmatch(entry.sha256) is None:
            message = (
                f"snapshot manifest {path} entry {relative!r} sha256 is not "
                "64 lowercase hexadecimal characters"
            )
            raise ManifestError(message)
        if entry.size < 0:
            message = f"snapshot manifest {path} entry {relative!r} size is negative"
            raise ManifestError(message)


def load_manifest(path: Path) -> Manifest:
    """Decode and validate one manifest. Every malformed input raises ManifestError.

    Validation completes before any snapshot file is opened, so a malformed pin can never
    half-verify a tree.
    """
    raw = path.read_bytes()
    try:
        json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
    except json.JSONDecodeError as exc:
        message = f"snapshot manifest {path} is not valid JSON: {exc}"
        raise ManifestError(message) from exc
    try:
        manifest = _MANIFEST_DECODER.decode(raw)
    except msgspec.DecodeError as exc:
        message = f"snapshot manifest {path} does not match the pinned shape: {exc}"
        raise ManifestError(message) from exc
    _validate_manifest(manifest, path)
    return manifest


def _digest(target: Path) -> str:
    """Hash one file in chunks; the largest pinned file is ~942 MiB."""
    with target.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _classify_pinned(target: Path, entry: FileEntry) -> str:
    """Return the fault name for one pinned path, or an empty string when it verifies."""
    try:
        status = target.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except OSError:
        return "unreadable"
    # lstat never follows, so a symlink reports as one and can never borrow its target's bytes.
    if not stat.S_ISREG(status.st_mode):
        return "mismatched"
    if status.st_size != entry.size:
        return "mismatched"
    try:
        digest = _digest(target)
    except OSError:
        return "unreadable"
    return "" if digest == entry.sha256 else "mismatched"


def _walk_files(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (relative paths of every non-directory entry, relative unlistable directories).

    `.cache` directories are pruned at any depth. A symlink is never descended, so it is
    reported as an entry of its own. A root that is absent or is not a directory yields nothing:
    the pinned paths under it are already reported missing.
    """
    found: list[str] = []
    unreadable: list[str] = []
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        directory, prefix = stack.pop()
        try:
            children = sorted(directory.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            unreadable.append(prefix.rstrip("/") or ".")
            continue
        for child in children:
            relative = f"{prefix}{child.name}"
            if child.is_dir() and not child.is_symlink():
                if child.name != _CACHE_DIR_NAME:
                    stack.append((child, f"{relative}/"))
            else:
                found.append(relative)
    return tuple(found), tuple(unreadable)


def verify_snapshot(manifest: Manifest, root: Path) -> VerifyReport:
    """Compare one snapshot tree with its manifest, reporting all four fault classes at once."""
    faults: dict[str, list[str]] = {"missing": [], "mismatched": [], "unreadable": []}
    for relative, entry in manifest.files.items():
        fault = _classify_pinned(root / relative, entry)
        if fault:
            faults[fault].append(relative)
    discovered, unlistable = _walk_files(root)
    return VerifyReport(
        missing=tuple(sorted(faults["missing"])),
        mismatched=tuple(sorted(faults["mismatched"])),
        unexpected=tuple(sorted(path for path in discovered if path not in manifest.files)),
        unreadable=tuple(sorted(faults["unreadable"] + list(unlistable))),
    )


def _encode_manifest(manifest: Manifest) -> bytes:
    """Serialize one manifest to its canonical committed form: sorted keys, trailing newline."""
    payload = {
        "repo_id": manifest.repo_id,
        "revision": manifest.revision,
        "files": {
            relative: {"sha256": entry.sha256, "size": entry.size}
            for relative, entry in manifest.files.items()
        },
    }
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _build_manifest(root: Path) -> Manifest:
    """Hash every revision file below one snapshot root. Raises ManifestError on unusable trees."""
    discovered, unlistable = _walk_files(root)
    if unlistable:
        message = f"snapshot root {root} has unlistable directories: {', '.join(unlistable)}"
        raise ManifestError(message)
    if not discovered:
        message = f"snapshot root {root} holds no files"
        raise ManifestError(message)
    entries: dict[str, FileEntry] = {}
    for relative in sorted(discovered):
        target = root / relative
        status = target.lstat()
        # A symlink must never be pinned: its bytes are not in the tree that is verified.
        if not stat.S_ISREG(status.st_mode):
            message = f"snapshot root {root} entry {relative!r} is not a regular file"
            raise ManifestError(message)
        entries[relative] = FileEntry(sha256=_digest(target), size=status.st_size)
    return Manifest(repo_id=SNAPSHOT_REPO_ID, revision=SNAPSHOT_REVISION, files=entries)


def _format_report(report: VerifyReport, root: Path, pinned: int) -> str:
    """Render one operator-facing verdict. Faults print one class per line, paths comma-joined."""
    if report.ok:
        return f"snapshot {root} matches the manifest: {pinned} files\n"
    lines = [f"snapshot {root} does not match the manifest:"]
    lines += [
        f"  {name}: {', '.join(paths)}"
        for name, paths in (
            ("missing", report.missing),
            ("mismatched", report.mismatched),
            ("unexpected", report.unexpected),
            ("unreadable", report.unreadable),
        )
        if paths
    ]
    return "\n".join(lines) + "\n"


def _verify(manifest_path: Path, root: Path) -> int:
    try:
        manifest = load_manifest(manifest_path)
    except (ManifestError, OSError) as exc:
        sys.stderr.write(f"{exc}\n")
        return _EXIT_MANIFEST
    report = verify_snapshot(manifest, root)
    sys.stdout.write(_format_report(report, root, len(manifest.files)))
    return 0 if report.ok else _EXIT_FAULTS


def _write(manifest_path: Path, root: Path) -> int:
    try:
        manifest = _build_manifest(root)
    except (ManifestError, OSError) as exc:
        sys.stderr.write(f"{exc}\n")
        return _EXIT_MANIFEST
    manifest_path.write_bytes(_encode_manifest(manifest))
    sys.stdout.write(f"wrote {manifest_path}: {len(manifest.files)} files\n")
    return 0


def _parse_args(argv: Sequence[str] | None) -> tuple[bool, Path, Path]:
    parser = argparse.ArgumentParser(
        prog="python -m model_backend.snapshot",
        description="Verify or write the manifest that pins the local model snapshot.",
        allow_abbrev=False,
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--verify",
        action="store_true",
        help="compare the snapshot directory with the manifest",
    )
    action.add_argument(
        "--write",
        action="store_true",
        help="write the manifest from the snapshot directory",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=SNAPSHOT_MANIFEST_PATH,
        metavar="PATH",
        help="the manifest file (default: %(default)s)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=SNAPSHOT_ROOT,
        metavar="PATH",
        help="the snapshot directory (default: %(default)s)",
    )
    parsed = parser.parse_args(argv)
    return (
        cast("bool", parsed.write),
        cast("Path", parsed.manifest),
        cast("Path", parsed.root),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one snapshot command and RETURN its exit status, so callers keep control."""
    write, manifest_path, root = _parse_args(argv)
    if write:
        return _write(manifest_path, root)
    return _verify(manifest_path, root)


if __name__ == "__main__":
    raise SystemExit(main())
