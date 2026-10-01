# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""`GET /certificate/{plot_id}` reads under the larger of the two certificate MIME ceilings.

Both shipped MIME strings are 51 bytes, so the two ceilings are numerically equal and an output
assertion cannot tell which profile the route consulted. An argument spy names the MIMEs the
route asked for, and a stubbed ceiling that DIVERGES per MIME shows the read receives the larger.
"""

from pathlib import Path
from typing import Any

import pytest
from litestar.testing import TestClient

from verifier import attestation
from verifier.service import app as app_module
from verifier.service.archive import Archive, ArchiveNotFoundError
from verifier.service.settings import Settings

_V02 = "application/vnd.figure-verification.vcert.v0.2+json"
_V03 = "application/vnd.figure-verification.vcert.v0.3+json"


@pytest.mark.parametrize(("v02_limit", "v03_limit"), [(1000, 2000), (3000, 2000)])
def test_certificate_read_ceiling_is_the_larger_mime_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, v02_limit: int, v03_limit: int
) -> None:
    asked: list[tuple[int, str]] = []
    read: list[int] = []

    def ceiling(max_payload_bytes: int, *, payload_type: str = _V02) -> int:
        asked.append((max_payload_bytes, payload_type))
        return {_V02: v02_limit, _V03: v03_limit}[payload_type]

    def read_certificate(_self: Archive, _address: str, *, max_bytes: int, **_kw: Any) -> bytes:
        read.append(max_bytes)
        raise ArchiveNotFoundError

    monkeypatch.setattr(attestation, "envelope_byte_limit", ceiling)
    monkeypatch.setattr(Archive, "read_certificate", read_certificate)
    settings = Settings(data_dir=tmp_path, state_dir=tmp_path / "state", max_attestation_bytes=777)
    with TestClient(app=app_module.create_app(settings)) as client:
        response = client.get("/certificate/" + "a" * 64)

    assert response.status_code == 404
    assert sorted(asked) == [(777, _V02), (777, _V03)]
    assert read == [max(v02_limit, v03_limit)]
