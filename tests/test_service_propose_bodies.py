# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Both proposer routes answer every bounded malformed body with 400, never 500 (contract S9).

The duplicate-key pre-scan reads the body through the stdlib parser, whose own caps raise outside
`json.JSONDecodeError`: a 5000-digit integer trips the int-string conversion limit (ValueError) and
10,000 nested arrays trip the recursion limit (RecursionError). Either must still be transport
misuse, refused before any model call.
"""

from pathlib import Path

import pytest
from litestar.testing import TestClient

from verifier.service import app as app_module
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parents[1]
_HUGE_INT = b"9" * 5000
_DEEP = b"[" * 10_000 + b"]" * 10_000


@pytest.mark.parametrize(
    ("path", "extra"),
    [("/propose-spec", b', "dataset_name": "sales.csv"'), ("/propose-formula", b"")],
)
@pytest.mark.parametrize("value", [_HUGE_INT, _DEEP], ids=["huge-int", "deep-nesting"])
def test_a_parser_capped_body_is_a_400_before_any_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str, extra: bytes, value: bytes
) -> None:
    called: list[str] = []

    async def bomb(*_args: object, **_kwargs: object) -> bytes:
        called.append(path)
        return b"{}"

    monkeypatch.setattr(app_module, "propose_spec", bomb)
    monkeypatch.setattr(app_module, "propose_formula", bomb)
    settings = Settings(data_dir=_ROOT / "data", state_dir=tmp_path / "state")
    body = b'{"user_request": ' + value + extra + b"}"
    with TestClient(app=app_module.create_app(settings)) as client:
        response = client.post(path, content=body, headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert called == []
