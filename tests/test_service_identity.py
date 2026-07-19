# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M5.3b persistent signer, secure filesystem boundary, rotation, and trust policy."""

import os
import secrets
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from verifier.service import identity
from verifier.service.identity import IdentityError, keyid_for_public_key, load_identity
from verifier.service.settings import Settings

_RAW_BYTES = 32


def _settings(
    state_dir: Path, *, key_file: Path | None = None, pins: tuple[str, ...] = ()
) -> Settings:
    return Settings(
        data_dir=state_dir.parent / "data",
        state_dir=state_dir,
        signing_key_file=key_file,
        trusted_keyids=pins,
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def _public_path(state_dir: Path, keyid: str) -> Path:
    digest = keyid.removeprefix("sha256:")
    return state_dir / "public-keys" / f"{digest}.ed25519.pub"


def test_create_reopen_persists_one_secure_identity(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    settings = _settings(state_dir)
    first = load_identity(settings)
    key_file = cast("Path", settings.signing_key_file)
    public_file = _public_path(state_dir, first.signer.keyid)

    assert first.signer.keyid == keyid_for_public_key(first.signer.public_key_bytes)
    assert key_file.read_bytes() == first.signer.private_key.private_bytes_raw()
    assert public_file.read_bytes() == first.signer.public_key_bytes
    assert len(key_file.read_bytes()) == _RAW_BYTES
    assert (_mode(state_dir), _mode(key_file)) == (0o700, 0o600)
    assert (_mode(state_dir / "public-keys"), _mode(public_file)) == (0o700, 0o600)
    assert tuple(first.trusted_keys) == (first.signer.keyid,)
    assert isinstance(first.trusted_keys, MappingProxyType)
    with pytest.raises(TypeError):
        cast("dict[str, Ed25519PublicKey]", first.trusted_keys)["extra"] = first.signer.public_key

    second = load_identity(settings)
    assert second.signer.keyid == first.signer.keyid
    assert second.signer.private_key.private_bytes_raw() == key_file.read_bytes()
    message = b"restart-stable signer"
    second.signer.public_key.verify(first.signer.private_key.sign(message), message)


def test_first_creation_fsyncs_key_files_and_containing_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_fsync = os.fsync
    synced_kinds: list[int] = []

    def tracking_fsync(descriptor: int) -> None:
        synced_kinds.append(stat.S_IFMT(os.fstat(descriptor).st_mode))
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", tracking_fsync)
    load_identity(_settings(tmp_path / "state"))
    assert synced_kinds.count(stat.S_IFREG) == 2  # private temp + preserved public temp
    assert synced_kinds.count(stat.S_IFDIR) >= 6  # mkdir/link/unlink durability barriers


def test_concurrent_first_start_publishes_only_one_complete_key(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    settings = _settings(state_dir)
    with ThreadPoolExecutor(max_workers=12) as executor:
        loaded = tuple(executor.map(lambda _: load_identity(settings), range(24)))

    assert len({item.signer.keyid for item in loaded}) == 1
    assert len({item.signer.private_key.private_bytes_raw() for item in loaded}) == 1
    key_file = cast("Path", settings.signing_key_file)
    assert len(key_file.read_bytes()) == _RAW_BYTES
    assert _mode(key_file) == 0o600


def test_external_key_file_and_explicit_rotation_preserve_history_without_auto_trust(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    external = tmp_path / "operator-keys"
    external.mkdir(mode=0o700)
    first = load_identity(_settings(state_dir, key_file=external / "first.key"))
    second_settings = _settings(state_dir, key_file=external / "second.key")
    second = load_identity(second_settings)

    assert first.signer.keyid != second.signer.keyid
    assert _public_path(state_dir, first.signer.keyid).read_bytes() == first.signer.public_key_bytes
    assert tuple(second.trusted_keys) == (second.signer.keyid,)
    assert first.signer.keyid not in second.trusted_keys
    message = b"old signer"
    old_signature = first.signer.private_key.sign(message)
    with pytest.raises(InvalidSignature):
        second.trusted_keys[second.signer.keyid].verify(old_signature, message)

    pinned = load_identity(
        _settings(
            state_dir,
            key_file=external / "second.key",
            pins=(first.signer.keyid, second.signer.keyid),
        )
    )
    assert tuple(pinned.trusted_keys) == (second.signer.keyid, first.signer.keyid)
    pinned.trusted_keys[first.signer.keyid].verify(old_signature, message)
    assert load_identity(second_settings).signer.keyid == second.signer.keyid


def test_external_key_parent_must_be_owner_private(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    external = tmp_path / "operator-keys"
    external.mkdir(mode=0o755)
    with pytest.raises(IdentityError, match="signing-key parent grants group/world"):
        load_identity(_settings(state_dir, key_file=external / "signing.key"))


@pytest.mark.parametrize("state_kind", ["symlink", "file"])
def test_state_final_component_rejects_symlink_and_non_directory(
    tmp_path: Path, state_kind: str
) -> None:
    state_dir = tmp_path / "state"
    if state_kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        state_dir.symlink_to(target, target_is_directory=True)
    else:
        state_dir.write_bytes(b"not a directory")

    with pytest.raises(IdentityError, match="state directory"):
        load_identity(_settings(state_dir))


def test_state_parent_must_exist_as_a_directory(tmp_path: Path) -> None:
    missing_parent = tmp_path / "absent" / "state"
    with pytest.raises(IdentityError, match="state-directory parent"):
        load_identity(_settings(missing_parent))


@pytest.mark.parametrize("key_kind", ["symlink", "directory"])
def test_key_final_component_rejects_symlink_and_non_regular(tmp_path: Path, key_kind: str) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    key_file = state_dir / "signing.key"
    if key_kind == "symlink":
        target = tmp_path / "target.key"
        target.write_bytes(b"x" * _RAW_BYTES)
        key_file.symlink_to(target)
    else:
        key_file.mkdir()

    with pytest.raises(IdentityError, match="signing key"):
        load_identity(_settings(state_dir))


def test_writerless_fifo_private_key_rejects_without_blocking(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    settings = _settings(state_dir)
    load_identity(settings)
    key_file = cast("Path", settings.signing_key_file)
    key_file.unlink()
    os.mkfifo(key_file, 0o600)

    captured: list[IdentityError] = []

    def reopen() -> None:
        try:
            load_identity(settings)
        except IdentityError as exc:
            captured.append(exc)

    thread = threading.Thread(target=reopen, daemon=True)
    thread.start()
    thread.join(timeout=5.0)
    if thread.is_alive():
        writer = os.open(key_file, os.O_WRONLY)
        os.close(writer)
        thread.join(timeout=5.0)
        pytest.fail("os.open FIFO _READ_FLAGS O_NONBLOCK")

    assert len(captured) == 1
    assert isinstance(captured[0], IdentityError)


@pytest.mark.parametrize(
    ("target", "mode", "message"),
    [("state", 0o750, "state directory"), ("key", 0o640, "signing key")],
)
def test_state_and_key_reject_group_world_permissions(
    tmp_path: Path, target: str, mode: int, message: str
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    key_file = state_dir / "signing.key"
    if target == "state":
        state_dir.chmod(mode)
    else:
        key_file.write_bytes(b"x" * _RAW_BYTES)
        key_file.chmod(mode)

    with pytest.raises(IdentityError, match=rf"{message} grants group/world"):
        load_identity(_settings(state_dir))


def test_wrong_owner_metadata_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    actual_uid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: actual_uid + 1)
    with pytest.raises(IdentityError, match="must be owned"):
        load_identity(_settings(state_dir))


def test_wrong_owner_private_key_metadata_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    settings = _settings(state_dir)
    load_identity(settings)
    actual_fstat = os.fstat
    wrong_uid = os.geteuid() + 1

    def key_owned_elsewhere(descriptor: int) -> os.stat_result:
        metadata = actual_fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode):
            values = list(metadata)
            values[4] = wrong_uid
            return os.stat_result(values)
        return metadata

    monkeypatch.setattr(os, "fstat", key_owned_elsewhere)
    with pytest.raises(IdentityError, match="signing key must be owned"):
        load_identity(settings)


@pytest.mark.parametrize("size", [0, _RAW_BYTES - 1, _RAW_BYTES + 1])
def test_private_key_rejects_wrong_size(tmp_path: Path, size: int) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    key_file = state_dir / "signing.key"
    key_file.write_bytes(b"x" * size)
    key_file.chmod(0o600)
    with pytest.raises(IdentityError, match="exactly 32 raw bytes"):
        load_identity(_settings(state_dir))


@pytest.mark.parametrize("public_fault", ["symlink-dir", "open-dir", "insecure-dir"])
def test_public_key_directory_rejects_unsafe_shapes(tmp_path: Path, public_fault: str) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    public_dir = state_dir / "public-keys"
    if public_fault == "symlink-dir":
        target = tmp_path / "public-target"
        target.mkdir()
        public_dir.symlink_to(target, target_is_directory=True)
    elif public_fault == "open-dir":
        public_dir.mkdir(mode=0o700)
        public_dir.chmod(0o755)
    else:
        public_dir.write_bytes(b"not a directory")

    with pytest.raises(IdentityError, match="public-key directory"):
        load_identity(_settings(state_dir))


def test_preserved_current_public_key_rejects_tamper_and_permissions(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    settings = _settings(state_dir)
    loaded = load_identity(settings)
    public_file = _public_path(state_dir, loaded.signer.keyid)

    public_file.write_bytes(b"z" * _RAW_BYTES)
    with pytest.raises(IdentityError, match="disagrees with the current signer"):
        load_identity(settings)

    public_file.write_bytes(loaded.signer.public_key_bytes)
    public_file.chmod(0o644)
    with pytest.raises(IdentityError, match=r"public key .* grants group/world"):
        load_identity(settings)


def test_historical_pin_requires_preserved_hash_matching_public_key(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    current = load_identity(_settings(state_dir))
    missing_pin = "sha256:" + "f" * 64
    with pytest.raises(IdentityError, match="is not preserved"):
        load_identity(_settings(state_dir, pins=(missing_pin,)))

    wrong_raw = b"w" * _RAW_BYTES
    wrong_pin = "sha256:" + "e" * 64
    wrong_file = _public_path(state_dir, wrong_pin)
    wrong_file.write_bytes(wrong_raw)
    wrong_file.chmod(0o600)
    with pytest.raises(IdentityError, match="does not match pinned keyid"):
        load_identity(_settings(state_dir, pins=(wrong_pin,)))

    assert current.signer.keyid not in {missing_pin, wrong_pin}


def test_read_detects_file_change_after_metadata_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    key_file = state_dir / "signing.key"
    key_file.write_bytes(b"x" * _RAW_BYTES)
    key_file.chmod(0o600)
    descriptor = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(os, "read", lambda _descriptor, _size: b"")
    try:
        with pytest.raises(IdentityError, match="changed while reading"):
            identity._read_secure_file(descriptor, key_file.name, subject="signing key")
    finally:
        os.close(descriptor)


def test_atomic_writer_handles_partial_progress_and_refuses_zero_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = bytearray()

    def partial_write(_descriptor: int, value: memoryview) -> int:
        count = min(3, len(value))
        received.extend(value[:count])
        return count

    monkeypatch.setattr(os, "write", partial_write)
    identity._write_all(7, b"abcdefgh")
    assert received == b"abcdefgh"

    monkeypatch.setattr(os, "write", lambda _descriptor, _value: 0)
    with pytest.raises(IdentityError, match="made no progress"):
        identity._write_all(7, b"x")


def test_atomic_publish_retries_private_temp_name_collision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collision = tmp_path / ".identity-collision.tmp"
    collision.write_bytes(b"occupied")
    tokens = iter(("collision", "fresh"))
    monkeypatch.setattr(secrets, "token_hex", lambda _size: next(tokens))
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert identity._atomic_publish(descriptor, "published", b"complete")
    finally:
        os.close(descriptor)
    assert (tmp_path / "published").read_bytes() == b"complete"
    assert collision.read_bytes() == b"occupied"


def test_atomic_publish_cleans_and_syncs_temporary_file_after_write_fault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(secrets, "token_hex", lambda _size: "fault")

    def fail_write(_descriptor: int, _value: bytes) -> None:
        detail = "injected write fault"
        raise IdentityError(detail)

    monkeypatch.setattr(identity, "_write_all", fail_write)
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(IdentityError, match="injected write fault"):
            identity._atomic_publish(descriptor, "unpublished", b"secret")
    finally:
        os.close(descriptor)
    assert not (tmp_path / ".identity-fault.tmp").exists()
    assert not (tmp_path / "unpublished").exists()


def test_lost_private_key_publication_reopens_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    winner = b"w" * _RAW_BYTES
    calls = 0

    def fake_read(_parent_fd: int, _name: str, *, subject: str) -> bytes:
        nonlocal calls
        assert subject == "signing key"
        calls += 1
        if calls == 1:
            raise FileNotFoundError
        return winner

    monkeypatch.setattr(identity, "_read_secure_file", fake_read)
    monkeypatch.setattr(identity, "_atomic_publish", lambda *_args: False)
    assert identity._load_or_create_private_key(3, "key", subject="signing key") == winner


def test_public_keyid_and_load_type_boundaries() -> None:
    for bad in (b"", b"x" * (_RAW_BYTES + 1), cast("bytes", "not-bytes")):
        with pytest.raises(ValueError, match="exactly 32 bytes"):
            keyid_for_public_key(bad)
    with pytest.raises(TypeError, match="validated service Settings"):
        load_identity(cast("Settings", object()))


def test_unexpected_os_fault_is_normalized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")

    def fail(_settings: Settings) -> Any:
        detail = "sensitive platform detail"
        raise OSError(detail)

    monkeypatch.setattr(identity, "_load_identity", fail)
    with pytest.raises(IdentityError, match="could not initialize") as caught:
        load_identity(settings)
    assert "sensitive" not in str(caught.value)
