# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Diff-blind M12.1 runtime-lock and settings-port contract suite.

Predicates P1, P6-P13, and P15-P18 stay red until MAIN implements the feature. P2-P5 and P19 pin
ratified invariants that are green at the seed. Expectations are hand-stated and never read from
the production constants that they pin.
"""

import ast
import hashlib
import importlib
import json
import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Protocol, cast, get_args

import msgspec
import pytest

import model_backend.settings as backend_settings
from model_backend.settings import GuidanceSchemaId, Settings

_ROOT = Path(__file__).resolve().parent.parent


class _TrackingEnv:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.read_keys: set[str] = set()

    def get(self, key: str, default: str | None = None) -> str | None:
        self.read_keys.add(key)
        return self._values.get(key, default)


class _FileEntryLike(Protocol):
    sha256: str
    size: int


class _ManifestLike(Protocol):
    repo_id: str
    revision: str
    files: dict[str, _FileEntryLike]


class _VerifyReportLike(Protocol):
    missing: tuple[str, ...]
    mismatched: tuple[str, ...]
    unexpected: tuple[str, ...]
    unreadable: tuple[str, ...]

    @property
    def ok(self) -> bool: ...


class _FileEntryFactory(Protocol):
    def __call__(self, *, sha256: str, size: int) -> _FileEntryLike: ...


class _ManifestFactory(Protocol):
    def __call__(
        self,
        *,
        repo_id: str,
        revision: str,
        files: dict[str, _FileEntryLike],
    ) -> _ManifestLike: ...


class _VerifyReportFactory(Protocol):
    def __call__(
        self,
        *,
        missing: tuple[str, ...],
        mismatched: tuple[str, ...],
        unexpected: tuple[str, ...],
        unreadable: tuple[str, ...],
    ) -> _VerifyReportLike: ...


class _SnapshotModule(Protocol):
    SNAPSHOT_MANIFEST_PATH: Path
    SNAPSHOT_ROOT: Path
    SNAPSHOT_REPO_ID: str
    SNAPSHOT_REVISION: str
    ManifestError: type[ValueError]
    FileEntry: _FileEntryFactory
    Manifest: _ManifestFactory
    VerifyReport: _VerifyReportFactory
    load_manifest: Callable[[Path], _ManifestLike]
    verify_snapshot: Callable[[_ManifestLike, Path], _VerifyReportLike]
    main: Callable[[Sequence[str] | None], int]


_SYNTHETIC_REPO_ID = "synthetic/repository"
_SYNTHETIC_REVISION = "0123456789abcdef0123456789abcdef01234567"
_SYNTHETIC_FILES: tuple[tuple[str, bytes, str, int], ...] = (
    (
        "alpha.bin",
        b"alpha",
        "8ed3f6ad685b959ead7022518e1af76cd816f8e8ec7ccdda1ed4018e8f2223f8",
        5,
    ),
    (
        "nested/beta.bin",
        b"beta",
        "f44e64e75f3948e9f73f8dfa94721c4ce8cbb4f265c4790c702b2d41cfbf2753",
        4,
    ),
    (
        "zero.bin",
        b"",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        0,
    ),
)


def _snapshot_module() -> _SnapshotModule:
    module_path = Path("model_backend/snapshot.py")
    assert module_path.is_file(), "M12.1 feature absent: model_backend/snapshot.py"
    source = module_path.read_text(encoding="utf-8")
    assert source.startswith("# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception\n")
    import_roots: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            import_roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            import_roots.add(node.module.partition(".")[0])
    assert import_roots.isdisjoint({"torch", "transformers", "xgrammar", "huggingface_hub"})

    module: ModuleType = importlib.import_module("model_backend.snapshot")
    return cast("_SnapshotModule", module)


def _write_synthetic_manifest(path: Path) -> None:
    files = {
        relative: {"sha256": digest, "size": size}
        for relative, _content, digest, size in _SYNTHETIC_FILES
    }
    path.write_text(
        json.dumps(
            {
                "repo_id": _SYNTHETIC_REPO_ID,
                "revision": _SYNTHETIC_REVISION,
                "files": files,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _synthetic_snapshot(
    snapshot: _SnapshotModule, tmp_path: Path
) -> tuple[_ManifestLike, Path, Path]:
    root = tmp_path / "snapshot"
    root.mkdir(parents=True)
    entries: dict[str, _FileEntryLike] = {}
    for relative, content, digest, size in _SYNTHETIC_FILES:
        assert len(content) == size
        assert hashlib.sha256(content).hexdigest() == digest
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries[relative] = snapshot.FileEntry(sha256=digest, size=size)

    manifest_path = tmp_path / "snapshot.json"
    _write_synthetic_manifest(manifest_path)
    manifest = snapshot.Manifest(
        repo_id=_SYNTHETIC_REPO_ID,
        revision=_SYNTHETIC_REVISION,
        files=entries,
    )
    return manifest, root, manifest_path


def _assert_report(
    report: _VerifyReportLike,
    *,
    missing: tuple[str, ...] = (),
    mismatched: tuple[str, ...] = (),
    unexpected: tuple[str, ...] = (),
    unreadable: tuple[str, ...] = (),
) -> None:
    assert report.missing == missing
    assert report.mismatched == mismatched
    assert report.unexpected == unexpected
    assert report.unreadable == unreadable
    expected_ok = not any((missing, mismatched, unexpected, unreadable))
    assert report.ok is expected_ok


def _main_status(snapshot: _SnapshotModule, manifest_path: Path, root: Path) -> int:
    return snapshot.main(["--verify", "--manifest", str(manifest_path), "--root", str(root)])


def _string_table(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return cast("dict[str, object]", value)


def test_p01_settings_defaults_are_literal_pins() -> None:
    """P1 pins every default independently of the constants that supply it."""
    settings = Settings()

    assert settings.device == "cuda"
    assert settings.model_dir == Path("models/Qwen2.5-Coder-0.5B-Instruct")
    assert settings.model_name == "Qwen2.5-Coder-0.5B-Instruct"
    assert settings.structured_output is True
    assert settings.vplot_schema_path == Path("schema/vplot-0.1.schema.json")
    assert settings.formula_schema_path == Path("schema/vplot-formula-0.1.schema.json")
    assert settings.max_prompt_len == 1536
    assert settings.max_body_bytes == 131072
    assert settings.host == "127.0.0.1"
    assert settings.port == 8001
    assert settings.max_tokens == 512
    assert settings.max_response_bytes == 65536


def test_p02_struct_fields_exact_tuple() -> None:
    """P2 keeps the environment-backed settings vocabulary closed."""
    assert Settings.__struct_fields__ == (
        "model_dir",
        "model_name",
        "device",
        "structured_output",
        "vplot_schema_path",
        "formula_schema_path",
        "max_prompt_len",
        "max_body_bytes",
        "host",
        "port",
        "max_tokens",
        "max_response_bytes",
    )


def test_p03_env_name_set_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """P3 pins every read name and makes all values distinguishable."""
    env = _TrackingEnv(
        {
            "MODEL_BACKEND_MODEL_DIR": "custom/model-dir",
            "MODEL_BACKEND_MODEL_NAME": "custom-model-name",
            "MODEL_BACKEND_DEVICE": "custom-device",
            "MODEL_BACKEND_STRUCTURED_OUTPUT": "false",
            "MODEL_BACKEND_VPLOT_SCHEMA_PATH": "custom/vplot.json",
            "MODEL_BACKEND_FORMULA_SCHEMA_PATH": "custom/formula.json",
            "MODEL_BACKEND_MAX_PROMPT_LEN": "101",
            "MODEL_BACKEND_MAX_BODY_BYTES": "102",
            "MODEL_BACKEND_HOST": "192.0.2.10",
            "MODEL_BACKEND_PORT": "8103",
            "MODEL_BACKEND_MAX_TOKENS": "104",
            "MODEL_BACKEND_MAX_RESPONSE_BYTES": "105",
            "MODEL_BACKEND_PYSRC_SCHEMA_PATH": "must-not-be-read.json",
        }
    )
    monkeypatch.setattr(backend_settings, "os", SimpleNamespace(environ=env))

    assert Settings.from_env() == Settings(
        model_dir=Path("custom/model-dir"),
        model_name="custom-model-name",
        device="custom-device",
        structured_output=False,
        vplot_schema_path=Path("custom/vplot.json"),
        formula_schema_path=Path("custom/formula.json"),
        max_prompt_len=101,
        max_body_bytes=102,
        host="192.0.2.10",
        port=8103,
        max_tokens=104,
        max_response_bytes=105,
    )
    assert env.read_keys == {
        "MODEL_BACKEND_MODEL_DIR",
        "MODEL_BACKEND_MODEL_NAME",
        "MODEL_BACKEND_DEVICE",
        "MODEL_BACKEND_STRUCTURED_OUTPUT",
        "MODEL_BACKEND_VPLOT_SCHEMA_PATH",
        "MODEL_BACKEND_FORMULA_SCHEMA_PATH",
        "MODEL_BACKEND_MAX_PROMPT_LEN",
        "MODEL_BACKEND_MAX_BODY_BYTES",
        "MODEL_BACKEND_HOST",
        "MODEL_BACKEND_PORT",
        "MODEL_BACKEND_MAX_TOKENS",
        "MODEL_BACKEND_MAX_RESPONSE_BYTES",
    }


def test_p04_guidance_schema_id_has_no_python_member() -> None:
    """P4 pins the closed selector and refuses the nearest deferred-mode id."""
    assert get_args(GuidanceSchemaId.__value__) == (
        "vplot-0.1",
        "vplot-formula-0.1",
    )
    paths = Settings(
        vplot_schema_path=Path("pinned/dataset.json"),
        formula_schema_path=Path("pinned/formula.json"),
    ).guidance_schema_paths()
    assert set(paths) == {"vplot-0.1", "vplot-formula-0.1"}
    assert paths == {
        "vplot-0.1": Path("pinned/dataset.json"),
        "vplot-formula-0.1": Path("pinned/formula.json"),
    }
    with pytest.raises(KeyError):
        cast("dict[str, Path]", paths)["pysrc-0.1"]


def test_p05_bound_guards_still_refuse_zero() -> None:
    """P5 pins all four guard messages by exact equality, not regex search."""
    with pytest.raises(ValueError) as max_tokens:
        Settings(max_tokens=0)
    assert str(max_tokens.value) == "max_tokens must be >= 1, got 0"

    with pytest.raises(ValueError) as max_response_bytes:
        Settings(max_response_bytes=0)
    assert str(max_response_bytes.value) == "max_response_bytes must be >= 1, got 0"

    with pytest.raises(ValueError) as max_body_bytes:
        Settings(max_body_bytes=0)
    assert str(max_body_bytes.value) == "max_body_bytes must be >= 1, got 0"

    with pytest.raises(ValueError) as max_prompt_len:
        Settings(max_prompt_len=0)
    assert str(max_prompt_len.value) == "max_prompt_len must be >= 1, got 0"


def test_p05b_bound_guards_still_refuse_negative() -> None:
    """P5 keeps a `< 1` guard distinguishable from a falsy-value guard (review ruling M05)."""
    with pytest.raises(ValueError) as max_tokens:
        Settings(max_tokens=-1)
    assert str(max_tokens.value) == "max_tokens must be >= 1, got -1"

    with pytest.raises(ValueError) as max_response_bytes:
        Settings(max_response_bytes=-1)
    assert str(max_response_bytes.value) == "max_response_bytes must be >= 1, got -1"

    with pytest.raises(ValueError) as max_body_bytes:
        Settings(max_body_bytes=-1)
    assert str(max_body_bytes.value) == "max_body_bytes must be >= 1, got -1"

    with pytest.raises(ValueError) as max_prompt_len:
        Settings(max_prompt_len=-1)
    assert str(max_prompt_len.value) == "max_prompt_len must be >= 1, got -1"


def test_p06_snapshot_manifest_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """P6 pins the real manifest and rejects malformed pins before verification."""
    manifest_path = Path("model_backend/runtime/snapshot.json")
    assert manifest_path.is_file(), "P6 feature absent: snapshot.json"

    snapshot = _snapshot_module()
    assert issubclass(snapshot.ManifestError, ValueError)
    assert Path("model_backend/runtime/snapshot.json") == snapshot.SNAPSHOT_MANIFEST_PATH
    assert Path("models/Qwen2.5-Coder-0.5B-Instruct") == snapshot.SNAPSHOT_ROOT
    raw_manifest = manifest_path.read_bytes()
    assert raw_manifest.endswith(b"\n")
    encoded_manifest = cast("dict[str, object]", json.loads(raw_manifest))
    assert set(encoded_manifest) == {"repo_id", "revision", "files"}
    assert list(encoded_manifest) == sorted(encoded_manifest)
    encoded_files = _string_table(encoded_manifest["files"])
    assert list(encoded_files) == sorted(encoded_files)
    for encoded_entry in encoded_files.values():
        entry_table = _string_table(encoded_entry)
        assert list(entry_table) == sorted(entry_table)

    manifest = snapshot.load_manifest(manifest_path)
    assert manifest.repo_id == "Qwen/Qwen2.5-Coder-0.5B-Instruct"
    assert manifest.revision == "ea3f2471cf1b1f0db85067f1ef93848e38e88c25"
    assert set(manifest.files) == {
        ".gitattributes",
        "LICENSE",
        "README.md",
        "config.json",
        "generation_config.json",
        "merges.txt",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
    }
    for entry in manifest.files.values():
        assert re.fullmatch(r"[0-9a-f]{64}", entry.sha256) is not None
        assert type(entry.size) is int
        assert entry.size > 0

    digest = "8ed3f6ad685b959ead7022518e1af76cd816f8e8ec7ccdda1ed4018e8f2223f8"
    malformed_sources = (
        (
            '{"repo_id":"synthetic/repository",'
            '"revision":"0123456789abcdef0123456789abcdef01234567",'
            '"files":{"alpha.bin":{"sha256":"'
            + digest
            + '","size":5},"alpha.bin":{"sha256":"'
            + digest
            + '","size":5}}}'
        ),
        (
            '{"repo_id":"synthetic/repository",'
            '"revision":"0123456789abcdef0123456789abcdef01234567","files":{}}'
        ),
        json.dumps(
            {
                "repo_id": _SYNTHETIC_REPO_ID,
                "revision": _SYNTHETIC_REVISION,
                "files": {"../outside.bin": {"sha256": digest, "size": 5}},
            }
        ),
        json.dumps(
            {
                "repo_id": _SYNTHETIC_REPO_ID,
                "revision": _SYNTHETIC_REVISION,
                "files": {"/outside.bin": {"sha256": digest, "size": 5}},
            }
        ),
        json.dumps(
            {
                "repo_id": _SYNTHETIC_REPO_ID,
                "revision": _SYNTHETIC_REVISION,
                "files": {"alpha.bin": {"sha256": digest.upper(), "size": 5}},
            }
        ),
    )
    malformed_path = tmp_path / "malformed.json"
    root = tmp_path / "must-not-read"
    root.mkdir()
    (root / "alpha.bin").write_bytes(b"alpha")
    original_read_bytes = Path.read_bytes
    snapshot_reads: list[Path] = []
    verify_calls = 0

    def guarded_read_bytes(path: Path) -> bytes:
        if path == malformed_path:
            return original_read_bytes(path)
        snapshot_reads.append(path)
        message = f"malformed manifest reached filesystem read: {path}"
        raise AssertionError(message)

    def verify_bomb(_manifest: _ManifestLike, _root: Path) -> _VerifyReportLike:
        nonlocal verify_calls
        verify_calls += 1
        pytest.fail("malformed manifest reached verify_snapshot", pytrace=False)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(snapshot, "verify_snapshot", verify_bomb)
    for source in malformed_sources:
        malformed_path.write_text(source + "\n", encoding="utf-8")
        with pytest.raises(snapshot.ManifestError):
            snapshot.load_manifest(malformed_path)
        assert _main_status(snapshot, malformed_path, root) != 0
    assert snapshot_reads == []
    assert verify_calls == 0


def test_p06b_manifest_digest_and_total_size(tmp_path: Path) -> None:
    """P6 stops the manifest and the weights from co-drifting (review ruling M10).

    The whole-manifest digest moves on any entry edit, and the total size is the revision's own
    measured byte count, so neither side can be edited alone to make a stale pin agree.
    """
    snapshot = _snapshot_module()
    manifest_path = Path("model_backend/runtime/snapshot.json")
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == (
        "cbaed3c5441ef489d0b4ff3bc1e767429f0f170657253de0bcee23d33fdadd93"
    )
    manifest = snapshot.load_manifest(manifest_path)
    assert sum(entry.size for entry in manifest.files.values()) == 999604233
    assert len(manifest.files) == 10

    # The digest pins the FILE, not a re-encoding: a manifest rebuilt from its own decoded
    # entries must reproduce the committed bytes, so canonical form is part of the pin.
    rebuilt = tmp_path / "rebuilt.json"
    rebuilt.write_text(
        json.dumps(
            {
                "repo_id": manifest.repo_id,
                "revision": manifest.revision,
                "files": {
                    relative: {"sha256": entry.sha256, "size": entry.size}
                    for relative, entry in manifest.files.items()
                },
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert rebuilt.read_bytes() == manifest_path.read_bytes()


def test_p07_verifier_clean_tree_exits_zero(tmp_path: Path) -> None:
    """P7 accepts an exact 3-file tree, including a zero-byte file."""
    snapshot = _snapshot_module()
    manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path)
    report = snapshot.verify_snapshot(manifest, root)

    _assert_report(report)
    assert _main_status(snapshot, manifest_path, root) == 0
    entry = manifest.files["alpha.bin"]
    assert isinstance(entry, msgspec.Struct)
    assert isinstance(manifest, msgspec.Struct)
    assert isinstance(report, msgspec.Struct)
    for value, field, replacement in (
        (entry, "size", 6),
        (manifest, "repo_id", "changed/repository"),
        (report, "missing", ("changed.bin",)),
    ):
        with pytest.raises(AttributeError):
            setattr(value, field, replacement)

    positional_entry = cast("Callable[[str, int], object]", snapshot.FileEntry)
    with pytest.raises(TypeError):
        positional_entry(
            "8ed3f6ad685b959ead7022518e1af76cd816f8e8ec7ccdda1ed4018e8f2223f8",
            5,
        )
    positional_manifest = cast(
        "Callable[[str, str, dict[str, _FileEntryLike]], object]", snapshot.Manifest
    )
    with pytest.raises(TypeError):
        positional_manifest(_SYNTHETIC_REPO_ID, _SYNTHETIC_REVISION, manifest.files)
    positional_report = cast(
        "Callable[[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]], object]",
        snapshot.VerifyReport,
    )
    with pytest.raises(TypeError):
        positional_report((), (), (), ())


def test_p08_flipped_byte_is_mismatched_only(tmp_path: Path) -> None:
    """P8 isolates content metadata drift and refuses manifest-path symlinks."""
    snapshot = _snapshot_module()
    manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path / "flipped")
    (root / "nested/beta.bin").write_bytes(b"Beta")

    _assert_report(
        snapshot.verify_snapshot(manifest, root),
        mismatched=("nested/beta.bin",),
    )
    assert _main_status(snapshot, manifest_path, root) != 0

    linked_manifest, linked_root, _linked_path = _synthetic_snapshot(snapshot, tmp_path / "linked")
    outside = tmp_path / "outside-alpha.bin"
    outside.write_bytes(b"alpha")
    linked_alpha = linked_root / "alpha.bin"
    linked_alpha.unlink()
    linked_alpha.symlink_to(outside)
    _assert_report(
        snapshot.verify_snapshot(linked_manifest, linked_root),
        mismatched=("alpha.bin",),
    )

    dangling_manifest, dangling_root, _dangling_path = _synthetic_snapshot(
        snapshot, tmp_path / "dangling"
    )
    dangling_alpha = dangling_root / "alpha.bin"
    dangling_alpha.unlink()
    dangling_alpha.symlink_to(tmp_path / "missing-target.bin")
    _assert_report(
        snapshot.verify_snapshot(dangling_manifest, dangling_root),
        mismatched=("alpha.bin",),
    )

    sized_manifest, sized_root, _sized_path = _synthetic_snapshot(snapshot, tmp_path / "wrong-size")
    sized_entries = dict(sized_manifest.files)
    sized_entries["alpha.bin"] = snapshot.FileEntry(
        sha256="8ed3f6ad685b959ead7022518e1af76cd816f8e8ec7ccdda1ed4018e8f2223f8",
        size=6,
    )
    wrong_size = snapshot.Manifest(
        repo_id=_SYNTHETIC_REPO_ID,
        revision=_SYNTHETIC_REVISION,
        files=sized_entries,
    )
    _assert_report(
        snapshot.verify_snapshot(wrong_size, sized_root),
        mismatched=("alpha.bin",),
    )


def test_p09_deleted_file_is_missing_only(tmp_path: Path) -> None:
    """P9 classifies one deletion and both unusable root shapes as missing."""
    snapshot = _snapshot_module()
    manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path / "deleted")
    (root / "alpha.bin").unlink()

    _assert_report(snapshot.verify_snapshot(manifest, root), missing=("alpha.bin",))
    assert _main_status(snapshot, manifest_path, root) != 0

    absent_root = tmp_path / "does-not-exist"
    all_paths = ("alpha.bin", "nested/beta.bin", "zero.bin")
    _assert_report(snapshot.verify_snapshot(manifest, absent_root), missing=all_paths)
    assert _main_status(snapshot, manifest_path, absent_root) != 0

    root_file = tmp_path / "root-is-file"
    root_file.write_bytes(b"not a directory")
    _assert_report(snapshot.verify_snapshot(manifest, root_file), missing=all_paths)
    assert _main_status(snapshot, manifest_path, root_file) != 0


def test_p10_extra_file_is_unexpected_only(tmp_path: Path) -> None:
    """P10 isolates regular and symlink extras while ignoring empty directories."""
    snapshot = _snapshot_module()
    manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path / "regular")
    (root / "empty-directory").mkdir()
    _assert_report(snapshot.verify_snapshot(manifest, root))

    (root / "extra.bin").write_bytes(b"extra")
    _assert_report(snapshot.verify_snapshot(manifest, root), unexpected=("extra.bin",))
    assert _main_status(snapshot, manifest_path, root) != 0

    linked_manifest, linked_root, linked_manifest_path = _synthetic_snapshot(
        snapshot, tmp_path / "links"
    )
    outside = tmp_path / "outside-extra.bin"
    outside.write_bytes(b"outside")
    (linked_root / "linked-extra.bin").symlink_to(outside)
    (linked_root / "dangling-extra.bin").symlink_to(tmp_path / "absent-extra.bin")
    _assert_report(
        snapshot.verify_snapshot(linked_manifest, linked_root),
        unexpected=("dangling-extra.bin", "linked-extra.bin"),
    )
    assert _main_status(snapshot, linked_manifest_path, linked_root) != 0


def test_p11_extra_under_cache_dir_is_ignored(tmp_path: Path) -> None:
    """P11 ignores Hugging Face metadata below the root cache directory."""
    snapshot = _snapshot_module()
    manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path)
    metadata = root / ".cache/huggingface/download/metadata.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("metadata", encoding="utf-8")

    _assert_report(snapshot.verify_snapshot(manifest, root))
    assert _main_status(snapshot, manifest_path, root) == 0


def test_p12_nested_cache_ignored_but_cache_named_file_is_not(tmp_path: Path) -> None:
    """P12 distinguishes a cache ancestor from a regular file named `.cache`."""
    snapshot = _snapshot_module()
    manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path)
    nested_metadata = root / "outer/.cache/huggingface/metadata.json"
    nested_metadata.parent.mkdir(parents=True)
    nested_metadata.write_text("metadata", encoding="utf-8")
    named_cache_file = root / "nested/literal/.cache"
    named_cache_file.parent.mkdir(parents=True)
    named_cache_file.write_bytes(b"not a cache directory")

    _assert_report(
        snapshot.verify_snapshot(manifest, root),
        unexpected=("nested/literal/.cache",),
    )
    assert _main_status(snapshot, manifest_path, root) != 0


def test_p13_four_fault_classes_are_disjoint_and_independent(tmp_path: Path) -> None:
    """P13 keeps all four amended fault classes independent and disjoint."""
    snapshot = _snapshot_module()
    manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path)
    (root / "alpha.bin").unlink()
    (root / "nested/beta.bin").write_bytes(b"Beta")
    unreadable_path = root / "zero.bin"
    unreadable_path.chmod(0)
    (root / "extra.bin").write_bytes(b"extra")

    try:
        report = snapshot.verify_snapshot(manifest, root)
        _assert_report(
            report,
            missing=("alpha.bin",),
            mismatched=("nested/beta.bin",),
            unexpected=("extra.bin",),
            unreadable=("zero.bin",),
        )
        assert _main_status(snapshot, manifest_path, root) != 0
        fault_sets = (
            set(report.missing),
            set(report.mismatched),
            set(report.unexpected),
            set(report.unreadable),
        )
        assert all(fault_set for fault_set in fault_sets)
        assert all(
            left.isdisjoint(right)
            for index, left in enumerate(fault_sets)
            for right in fault_sets[index + 1 :]
        )
    finally:
        unreadable_path.chmod(0o600)


def test_p15_runtime_pyproject_pins() -> None:
    """P15 pins the isolated Python 3.12 runtime and its five direct packages."""
    runtime_project_path = Path("model_backend/runtime/pyproject.toml")
    assert runtime_project_path.is_file(), "P15 feature absent: runtime pyproject.toml"
    source = runtime_project_path.read_text(encoding="utf-8")
    assert source.startswith("# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception\n")
    document = cast("dict[str, object]", tomllib.loads(source))
    project = _string_table(document["project"])
    assert project["requires-python"] == "==3.12.*"
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    assert all(isinstance(dependency, str) for dependency in dependencies)
    assert set(dependencies) == {
        "torch==2.7.1+cu126",
        "transformers==5.16.1",
        "accelerate==1.14.0",
        "tokenizers==0.23.1",
        "xgrammar==0.2.3",
    }

    tool = _string_table(document["tool"])
    uv = _string_table(tool["uv"])
    indexes = uv["index"]
    assert isinstance(indexes, list)
    index_tables = [_string_table(index) for index in indexes]
    cuda_indexes = [index for index in index_tables if index.get("name") == "pytorch-cu126"]
    assert len(cuda_indexes) == 1
    assert cuda_indexes[0]["url"] == "https://download.pytorch.org/whl/cu126"
    assert cuda_indexes[0]["explicit"] is True
    sources = _string_table(uv["sources"])
    torch_source = _string_table(sources["torch"])
    assert torch_source["index"] == "pytorch-cu126"


def test_p16_runtime_lock_pins_torch_cu126() -> None:
    """P16 pins the resolved torch package to the explicit CUDA 12.6 registry."""
    runtime_lock_path = Path("model_backend/runtime/uv.lock")
    assert runtime_lock_path.is_file(), "P16 feature absent: runtime uv.lock"
    document = cast(
        "dict[str, object]",
        tomllib.loads(runtime_lock_path.read_text(encoding="utf-8")),
    )
    assert document["requires-python"] == "==3.12.*"
    packages = document["package"]
    assert isinstance(packages, list)
    package_tables = [_string_table(package) for package in packages]
    torch_packages = [package for package in package_tables if package.get("name") == "torch"]
    assert len(torch_packages) == 1
    torch_package = torch_packages[0]
    assert torch_package["version"] == "2.7.1+cu126"
    source = _string_table(torch_package["source"])
    assert source["registry"] == "https://download.pytorch.org/whl/cu126"


def test_p17_runtime_files_tracked_not_ignored() -> None:
    """P17 separately pins repository tracking and ignore-pattern behavior."""
    tracked = subprocess.run(
        [
            "/usr/bin/git",
            "ls-files",
            "--error-unmatch",
            "--",
            "model_backend/runtime/uv.lock",
            "model_backend/runtime/pyproject.toml",
            "model_backend/runtime/README.md",
            "model_backend/runtime/snapshot.json",
        ],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, tracked.stderr

    runtime_paths = (
        "model_backend/runtime/uv.lock\n"
        "model_backend/runtime/pyproject.toml\n"
        "model_backend/runtime/README.md\n"
        "model_backend/runtime/snapshot.json\n"
    )
    ignored_runtime = subprocess.run(
        ["/usr/bin/git", "check-ignore", "--no-index", "--stdin"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
        input=runtime_paths,
    )
    assert ignored_runtime.returncode == 1, ignored_runtime.stdout

    ignored_models = subprocess.run(
        ["/usr/bin/git", "check-ignore", "--no-index", "--quiet", "models/"],
        cwd=_ROOT,
        check=False,
    )
    assert ignored_models.returncode == 0


def test_p18_mypy_overrides_added_and_openvino_retained() -> None:
    """P18 pins the runtime import overrides and excludes unused package overrides."""
    document = cast(
        "dict[str, object]",
        tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8")),
    )
    tool = _string_table(document["tool"])
    mypy = _string_table(tool["mypy"])
    overrides = mypy["overrides"]
    assert isinstance(overrides, list)
    module_groups: set[frozenset[str]] = set()
    for override_value in overrides:
        override = _string_table(override_value)
        assert override["ignore_missing_imports"] is True
        modules = override["module"]
        if isinstance(modules, str):
            module_groups.add(frozenset({modules}))
        else:
            assert isinstance(modules, list)
            assert all(isinstance(module, str) for module in modules)
            module_groups.add(frozenset(cast("list[str]", modules)))

    assert frozenset({"torch", "torch.*"}) in module_groups
    assert frozenset({"transformers", "transformers.*"}) in module_groups
    assert frozenset({"xgrammar", "xgrammar.*"}) in module_groups
    assert frozenset({"openvino_genai", "openvino_genai.*"}) in module_groups
    all_modules = set().union(*module_groups)
    assert "accelerate" not in all_modules
    assert "accelerate.*" not in all_modules
    assert "tokenizers" not in all_modules
    assert "tokenizers.*" not in all_modules


def test_p19_root_lock_matches_ratified_digest() -> None:
    """P19 compares the root lock with the ratified pre-M12 content digest."""
    digest = hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest()
    assert digest == "b10ce54f90acb804b636d34226fbcd4a72e2df19790ba42e9839c91909c759c1"


def test_p20_snapshot_identity_is_bound_across_surfaces() -> None:
    """P20 binds three independently writable identities (review ruling H08).

    Settings pick the directory the server loads, the manifest names the revision the verifier
    checks, and the verifier root joins them. Each literal is hand-stated first; the equalities
    that follow ARE the cross-surface claim, so deriving them is the assertion itself.
    """
    snapshot = _snapshot_module()
    settings = Settings()

    assert settings.model_dir == Path("models/Qwen2.5-Coder-0.5B-Instruct")
    assert settings.model_name == "Qwen2.5-Coder-0.5B-Instruct"
    assert Path("models/Qwen2.5-Coder-0.5B-Instruct") == snapshot.SNAPSHOT_ROOT
    assert Path("model_backend/runtime/snapshot.json") == snapshot.SNAPSHOT_MANIFEST_PATH
    assert snapshot.SNAPSHOT_REPO_ID == "Qwen/Qwen2.5-Coder-0.5B-Instruct"
    assert snapshot.SNAPSHOT_REVISION == "ea3f2471cf1b1f0db85067f1ef93848e38e88c25"

    manifest = snapshot.load_manifest(snapshot.SNAPSHOT_MANIFEST_PATH)
    assert manifest.repo_id == snapshot.SNAPSHOT_REPO_ID
    assert manifest.revision == snapshot.SNAPSHOT_REVISION
    assert settings.model_dir == snapshot.SNAPSHOT_ROOT
    assert snapshot.SNAPSHOT_ROOT.name == settings.model_name
    assert snapshot.SNAPSHOT_REPO_ID.rpartition("/")[2] == settings.model_name


def test_p22_write_regenerates_and_verify_never_blesses(tmp_path: Path) -> None:
    """P22 keeps regeneration idempotent and keeps `--verify` read-only (review ruling M16)."""
    snapshot = _snapshot_module()
    _manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path)
    write_argv = ["--write", "--manifest", str(manifest_path), "--root", str(root)]

    assert snapshot.main(write_argv) == 0
    written = manifest_path.read_bytes()
    assert snapshot.main(write_argv) == 0
    assert manifest_path.read_bytes() == written

    assert written.endswith(b"\n")
    decoded = _string_table(json.loads(written))
    assert list(decoded) == sorted(decoded)
    assert decoded["repo_id"] == snapshot.SNAPSHOT_REPO_ID
    assert decoded["revision"] == snapshot.SNAPSHOT_REVISION
    assert set(_string_table(decoded["files"])) == {"alpha.bin", "nested/beta.bin", "zero.bin"}

    assert _main_status(snapshot, manifest_path, root) == 0
    assert manifest_path.read_bytes() == written

    (root / "alpha.bin").write_bytes(b"ALPHA")
    assert _main_status(snapshot, manifest_path, root) != 0
    assert manifest_path.read_bytes() == written


def test_p23_unlistable_directory_is_unreadable_and_refuses_to_write(tmp_path: Path) -> None:
    """P23 pins the fourth fault class over a directory: diagnose the tree, never crash on it."""
    snapshot = _snapshot_module()
    manifest, root, manifest_path = _synthetic_snapshot(snapshot, tmp_path)
    blocked = root / "blocked"
    blocked.mkdir()
    (blocked / "hidden.bin").write_bytes(b"hidden")
    before = manifest_path.read_bytes()
    blocked.chmod(0)

    try:
        _assert_report(snapshot.verify_snapshot(manifest, root), unreadable=("blocked",))
        assert _main_status(snapshot, manifest_path, root) != 0
        write_status = snapshot.main(
            ["--write", "--manifest", str(manifest_path), "--root", str(root)]
        )
        assert write_status != 0
        assert manifest_path.read_bytes() == before
    finally:
        blocked.chmod(0o700)
