# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Core resource-policy vocabulary + byte-bounded file reads (M5.1a)."""

import io
from pathlib import Path
from typing import cast

import pytest

import verifier.limits as limits_module
from verifier.errors import VerificationError
from verifier.limits import VerificationLimits, read_bounded

_DEFAULTS = {
    "max_csv_bytes": 8 * 1024 * 1024,
    "max_manifest_bytes": 256 * 1024,
    "max_manifest_columns": 1_000,
    "max_source_rows": 100_000,
    "max_source_cells": 1_000_000,
    "max_plotted_cells": 1_000_000,
    "max_eval_work_units": 10_000_000,
    "max_render_rows": 10_000,
    "max_smt_terms": 100_000,
    "max_vega_bytes": 16 * 1024 * 1024,
    "max_svg_bytes": 32 * 1024 * 1024,
    "max_html_bytes": 32 * 1024 * 1024,
    "max_attestation_bytes": 1024 * 1024,
    "smt_timeout_ms": 1_000,
}


def test_verification_limits_defaults_and_overrides_are_frozen() -> None:
    defaults = VerificationLimits()
    assert {name: getattr(defaults, name) for name in _DEFAULTS} == _DEFAULTS
    overridden = VerificationLimits(max_csv_bytes=7, smt_timeout_ms=3)
    assert overridden.max_csv_bytes == 7
    assert overridden.smt_timeout_ms == 3
    name = "max_csv_bytes"  # dynamic name bypasses mypy's static frozen-field rejection
    with pytest.raises(AttributeError):
        setattr(overridden, name, 8)


@pytest.mark.parametrize("field", tuple(_DEFAULTS))
def test_verification_limits_reject_every_nonpositive_field(field: str) -> None:
    values = dict(_DEFAULTS)
    values[field] = 0
    with pytest.raises(ValueError, match=field):
        VerificationLimits(**values)


@pytest.mark.parametrize("value", [cast("int", 1.5), cast("int", bool(1))])
def test_verification_limits_reject_noninteger_runtime_values(value: int) -> None:
    with pytest.raises(ValueError, match="max_csv_bytes"):
        VerificationLimits(max_csv_bytes=value)


@pytest.mark.parametrize("size", [4, 5])
def test_read_bounded_accepts_boundary_minus_one_and_boundary(tmp_path: Path, size: int) -> None:
    path = tmp_path / "source.bin"
    expected = bytes(range(size))
    path.write_bytes(expected)
    assert read_bounded(path, 5) == expected


def test_read_bounded_rejects_boundary_plus_one(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"123456")
    with pytest.raises(VerificationError, match="byte limit of 5") as exc_info:
        read_bounded(path, 5)
    assert exc_info.value.check == "resource.file_bytes"


class _TrackingReader(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.requests: list[int | None] = []

    def read(self, size: int | None = -1, /) -> bytes:
        self.requests.append(size)
        return super().read(size)

    def close(self) -> None:
        # Keep tell()/requests observable after read_bounded exits its context manager.
        return None


def test_read_bounded_is_chunked_and_consumes_only_limit_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = limits_module._READ_CHUNK_BYTES + 5
    reader = _TrackingReader(b"x" * (cap + limits_module._READ_CHUNK_BYTES))
    expected_path = Path("virtual.bin")

    def open_tracking(path: Path, mode: str, buffering: int) -> _TrackingReader:
        assert path == expected_path
        assert (mode, buffering) == ("rb", 0)
        return reader

    monkeypatch.setattr(Path, "open", open_tracking)
    with pytest.raises(VerificationError) as exc_info:
        read_bounded(expected_path, cap)
    assert exc_info.value.check == "resource.file_bytes"
    assert reader.tell() == cap + 1
    assert None not in reader.requests
    assert max(cast("list[int]", reader.requests)) <= limits_module._READ_CHUNK_BYTES


def test_read_bounded_preserves_absence_and_operator_faults(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_bounded(tmp_path / "absent.bin", 5)
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(IsADirectoryError):
        read_bounded(directory, 5)


def test_read_bounded_rejects_invalid_cap_before_io(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        read_bounded(tmp_path / "absent.bin", -1)
    with pytest.raises(ValueError, match="non-negative integer"):
        read_bounded(tmp_path / "absent.bin", cast("int", 1.5))
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    assert read_bounded(empty, 0) == b""
