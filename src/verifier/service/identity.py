# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Persistent service signing identity + independently pinned historical trust.

The state and key paths are trusted operator configuration, but their filesystem objects are
still treated adversarially: final components are opened relative to already-open directory file
descriptors with ``O_NOFOLLOW``; directories/files must be owned by the effective service user and
grant no group/world permissions. A missing raw Ed25519 key is written + fsynced under a random
0600 temporary name, then published without replacement by one hard link. Concurrent first starts
therefore see either absence or all 32 bytes, never a partially written final file. Directory
fsyncs make each created/published entry durable under the local-filesystem contract.

Every current public key is likewise preserved, content-addressed by
``sha256(raw_public_key)``. Preservation is not trust: ``trusted_keys`` contains only the current
signer plus canonical historical keyids explicitly pinned in ``Settings``. Merely finding a public
key in state, an archive, or a future HTTP response never admits it.
"""

import hashlib
import os
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from verifier.service.settings import Settings

__all__ = [
    "IdentityError",
    "Signer",
    "SigningIdentity",
    "keyid_for_public_key",
    "load_identity",
    "open_state_directory",
    "validate_state_metadata",
]

_KEY_BYTES = 32
_PUBLIC_KEYS_DIRECTORY = "public-keys"
_PUBLIC_KEY_SUFFIX = ".ed25519.pub"
_NO_GROUP_OR_WORLD = stat.S_IRWXG | stat.S_IRWXO
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
# O_NONBLOCK lets writerless FIFOs reach regular-file validation without awaiting a writer; it is
# inert for regular files.
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class IdentityError(RuntimeError):
    """Signing state is unsafe, malformed, unavailable, or inconsistent with configured pins."""


@dataclass(frozen=True, slots=True)
class Signer:
    """One persistent Ed25519 signer and its content-derived public identity."""

    keyid: str
    public_key_bytes: bytes
    public_key: Ed25519PublicKey = field(repr=False)
    private_key: Ed25519PrivateKey = field(repr=False)


@dataclass(frozen=True, slots=True)
class SigningIdentity:
    """Current signer plus the closed, independently configured verification-key policy."""

    signer: Signer
    trusted_keys: Mapping[str, Ed25519PublicKey] = field(repr=False)


def keyid_for_public_key(public_key_bytes: bytes) -> str:
    """Return the canonical keyid for exactly one raw 32-byte Ed25519 public key."""
    public_object: object = public_key_bytes
    if not isinstance(public_object, bytes) or len(public_key_bytes) != _KEY_BYTES:
        msg = f"raw Ed25519 public key must contain exactly {_KEY_BYTES} bytes"
        raise ValueError(msg)
    return "sha256:" + hashlib.sha256(public_key_bytes).hexdigest()


def validate_state_metadata(
    metadata: os.stat_result, *, subject: str, expect_directory: bool
) -> None:
    """Require an effective-owner, owner-private regular file or directory."""
    expected = (
        stat.S_ISDIR(metadata.st_mode) if expect_directory else stat.S_ISREG(metadata.st_mode)
    )
    kind = "directory" if expect_directory else "regular file"
    if not expected:
        msg = f"{subject} must be a no-follow {kind}"
        raise IdentityError(msg)
    if metadata.st_uid != os.geteuid():
        msg = f"{subject} must be owned by effective uid {os.geteuid()}"
        raise IdentityError(msg)
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & _NO_GROUP_OR_WORLD:
        msg = f"{subject} grants group/world permissions: mode {mode:#05o}"
        raise IdentityError(msg)


def _open_directory_path(path: Path, *, subject: str) -> int:
    try:
        descriptor = os.open(path, _DIRECTORY_FLAGS)
    except OSError as exc:
        msg = f"{subject} must be an available no-follow directory"
        raise IdentityError(msg) from exc
    return descriptor


def _open_secure_directory_path(path: Path, *, subject: str) -> int:
    descriptor = _open_directory_path(path, subject=subject)
    try:
        validate_state_metadata(os.fstat(descriptor), subject=subject, expect_directory=True)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _open_secure_directory_at(parent_fd: int, name: str, *, subject: str) -> int:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        msg = f"{subject} must be an available no-follow directory"
        raise IdentityError(msg) from exc
    try:
        validate_state_metadata(os.fstat(descriptor), subject=subject, expect_directory=True)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def open_state_directory(path: Path) -> int:
    """Create/reopen the owner-private state directory and return its no-follow descriptor."""
    parent_fd = _open_directory_path(path.parent, subject="state-directory parent")
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        else:
            os.fsync(parent_fd)
        return _open_secure_directory_at(parent_fd, path.name, subject="state directory")
    finally:
        os.close(parent_fd)


def _ensure_public_key_directory(state_fd: int) -> int:
    try:
        os.mkdir(_PUBLIC_KEYS_DIRECTORY, 0o700, dir_fd=state_fd)
    except FileExistsError:
        pass
    else:
        os.fsync(state_fd)
    return _open_secure_directory_at(
        state_fd, _PUBLIC_KEYS_DIRECTORY, subject="public-key directory"
    )


def _read_secure_file(parent_fd: int, name: str, *, subject: str) -> bytes:
    try:
        descriptor = os.open(name, _READ_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        msg = f"{subject} must be an available no-follow regular file"
        raise IdentityError(msg) from exc
    try:
        metadata = os.fstat(descriptor)
        validate_state_metadata(metadata, subject=subject, expect_directory=False)
        if metadata.st_size != _KEY_BYTES:
            msg = f"{subject} must contain exactly {_KEY_BYTES} raw bytes; got {metadata.st_size}"
            raise IdentityError(msg)

        chunks: list[bytes] = []
        remaining = _KEY_BYTES + 1
        while True:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
        if len(value) != _KEY_BYTES:
            msg = f"{subject} changed while reading; expected exactly {_KEY_BYTES} raw bytes"
            raise IdentityError(msg)
        return value
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            msg = "atomic key write made no progress"
            raise IdentityError(msg)
        offset += written


def _atomic_publish(parent_fd: int, name: str, value: bytes) -> bool:
    """Publish complete bytes iff ``name`` is absent; return whether this caller won."""
    while True:
        temporary = f".identity-{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(temporary, _CREATE_FLAGS, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            continue
        break

    published = False
    try:
        try:
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, value)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

        try:
            os.link(
                temporary,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
        else:
            os.fsync(parent_fd)
            published = True
    finally:
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
    return published


def _load_or_create_private_key(parent_fd: int, name: str, *, subject: str) -> bytes:
    try:
        return _read_secure_file(parent_fd, name, subject=subject)
    except FileNotFoundError:
        candidate = Ed25519PrivateKey.generate().private_bytes_raw()
        if _atomic_publish(parent_fd, name, candidate):
            return candidate
        return _read_secure_file(parent_fd, name, subject=subject)


def _public_key_name(keyid: str) -> str:
    return keyid.removeprefix("sha256:") + _PUBLIC_KEY_SUFFIX


def _preserve_public_key(public_dir_fd: int, keyid: str, raw_public_key: bytes) -> None:
    name = _public_key_name(keyid)
    if not _atomic_publish(public_dir_fd, name, raw_public_key):
        existing = _read_secure_file(public_dir_fd, name, subject=f"public key {keyid}")
        if existing != raw_public_key:
            msg = f"preserved public key {keyid} disagrees with the current signer"
            raise IdentityError(msg)


def _load_pinned_public_key(public_dir_fd: int, keyid: str) -> Ed25519PublicKey:
    try:
        raw = _read_secure_file(
            public_dir_fd, _public_key_name(keyid), subject=f"trusted public key {keyid}"
        )
    except FileNotFoundError as exc:
        msg = f"trusted public key {keyid} is not preserved in signing state"
        raise IdentityError(msg) from exc
    if keyid_for_public_key(raw) != keyid:
        msg = f"trusted public key file does not match pinned keyid {keyid}"
        raise IdentityError(msg)
    return Ed25519PublicKey.from_public_bytes(raw)


def _load_identity(settings: Settings) -> SigningIdentity:
    state_fd = open_state_directory(settings.state_dir)
    try:
        key_path = cast("Path", settings.signing_key_file)
        if key_path.parent == settings.state_dir:
            key_parent_fd = os.dup(state_fd)
        else:
            key_parent_fd = _open_secure_directory_path(
                key_path.parent, subject="signing-key parent"
            )
        try:
            raw_private_key = _load_or_create_private_key(
                key_parent_fd, key_path.name, subject="signing key"
            )
        finally:
            os.close(key_parent_fd)

        # Every 32-byte value is a valid Ed25519 seed; size was checked before this boundary.
        private_key = Ed25519PrivateKey.from_private_bytes(raw_private_key)
        public_key = private_key.public_key()
        raw_public_key = public_key.public_bytes_raw()
        keyid = keyid_for_public_key(raw_public_key)
        signer = Signer(
            keyid=keyid,
            public_key_bytes=raw_public_key,
            public_key=public_key,
            private_key=private_key,
        )

        public_dir_fd = _ensure_public_key_directory(state_fd)
        try:
            _preserve_public_key(public_dir_fd, keyid, raw_public_key)
            trusted: dict[str, Ed25519PublicKey] = {keyid: public_key}
            for pinned_keyid in settings.trusted_keyids:
                if pinned_keyid not in trusted:
                    trusted[pinned_keyid] = _load_pinned_public_key(public_dir_fd, pinned_keyid)
        finally:
            os.close(public_dir_fd)
        return SigningIdentity(signer=signer, trusted_keys=MappingProxyType(trusted))
    finally:
        os.close(state_fd)


def load_identity(settings: Settings) -> SigningIdentity:
    """Create/reopen the persistent signer and materialize the explicit trusted-key policy."""
    settings_object: object = settings
    if not isinstance(settings_object, Settings):
        msg = "settings must be a validated service Settings instance"
        raise TypeError(msg)
    try:
        return _load_identity(settings)
    except IdentityError:
        raise
    except OSError as exc:
        msg = "could not initialize persistent signing identity"
        raise IdentityError(msg) from exc
