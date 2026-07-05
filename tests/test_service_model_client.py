# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M3.2b model-proposer client tests: prompt assembly, envelope extraction, error split.

Patches model_client._build_async_client to return an httpx.AsyncClient backed by a
MockTransport, so no socket binds and every branch runs deterministically. The weather
fixture (data/weather.csv + data/schemas/weather.json) exercises every _describe_column
arm. Handlers that ignore the request name it `_request` (ruff exempts the dummy name);
the happy handler captures the request to assert the sent prompt. The not-found and
factory tests install no transport -- they short-circuit or never dispatch.
"""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from verifier import canon
from verifier.service import model_client
from verifier.service.model_client import (
    DatasetNotFoundError,
    ModelUpstreamError,
    propose_spec,
)
from verifier.service.settings import Settings

_ROOT = Path(__file__).parents[1]
_DATA = _ROOT / "data"
# Representative reply content: the client returns it verbatim as bytes and NEVER decodes it
# as VPlot (deliberately not a complete spec), so a malformed proposal still flows downstream
# to a 200 verdict -- the metered model-failure mode.
_CONTENT = '{"version": "vplot-0.1", "mark": "bar"}'


def _settings() -> Settings:
    return Settings(data_dir=_DATA)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Point _build_async_client at a MockTransport-backed client running `handler`."""

    def build(settings: Settings) -> httpx.AsyncClient:
        # Mirror the real factory's timeout wiring (harmless under MockTransport).
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=settings.model_timeout
        )

    monkeypatch.setattr(model_client, "_build_async_client", build)


def _returns(response: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    """A handler that ignores the request and returns a fixed response."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    return handler


def test_propose_spec_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        body = {"choices": [{"message": {"role": "assistant", "content": _CONTENT}}]}
        return httpx.Response(200, json=body)

    _install(monkeypatch, handler)
    result = asyncio.run(
        propose_spec("Plot average temperature by city", "weather.csv", _settings())
    )

    # Raw content bytes, verbatim and undecoded.
    assert result == _CONTENT.encode("utf-8")

    request = captured["request"]
    assert str(request.url) == "http://127.0.0.1:8001/v1/chat/completions"
    sent = json.loads(request.content)
    assert sent["model"] == "Qwen2-0.5B-Instruct-int4-sym-ov"
    assert sent["temperature"] == 0
    assert sent["max_tokens"] == 512

    system, user = sent["messages"]
    assert system["role"] == "system"
    assert "vplot-0.1" in system["content"]
    assert user["role"] == "user"

    # The binding to copy verbatim carries the live dataset hash.
    csv_bytes = (_DATA / "weather.csv").read_bytes()
    binding = json.dumps({"name": "weather.csv", "hash": canon.hash_dataset(csv_bytes)})
    assert binding in user["content"]

    # Every _describe_column arm reached the prompt (numeric+unit, numeric no-unit, temporal,
    # string) alongside the header, a sample value, and the request.
    for line in (
        "date: temporal (date)",
        "city: string",
        "temp_c: numeric (scale 1, unit °C)",
        "aqi: numeric (scale 0)",
        "date,city,temp_c,precip_mm,aqi",
        "London",
        "Plot average temperature by city",
    ):
        assert line in user["content"]


def test_propose_spec_unreachable_raises_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        msg = "connection refused"
        raise httpx.ConnectError(msg)

    _install(monkeypatch, handler)
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 503
    assert "unreachable" in str(exc_info.value)


def test_propose_spec_non_2xx_raises_502(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _returns(httpx.Response(500, json={"error": "boom"})))
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 502
    assert "HTTP 500" in str(exc_info.value)


def test_propose_spec_non_json_body_raises_502(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _returns(httpx.Response(200, content=b"not json {")))
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 502
    assert "not a chat-completion envelope" in str(exc_info.value)


def test_propose_spec_invalid_envelope_raises_502(monkeypatch: pytest.MonkeyPatch) -> None:
    # `message` omits the required `content` -> the strict envelope decode raises
    # ValidationError -> an upstream fault (502), never a 200.
    body = {"choices": [{"message": {"role": "assistant"}}]}
    _install(monkeypatch, _returns(httpx.Response(200, json=body)))
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 502
    assert "not a chat-completion envelope" in str(exc_info.value)


def test_propose_spec_no_choices_raises_502(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _returns(httpx.Response(200, json={"choices": []})))
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 502
    assert "no choices" in str(exc_info.value)


def test_propose_spec_empty_content_raises_502(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"choices": [{"message": {"content": ""}}]}
    _install(monkeypatch, _returns(httpx.Response(200, json=body)))
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 502
    assert "content is empty" in str(exc_info.value)


def test_propose_spec_absent_dataset_raises_not_found() -> None:
    # No transport installed: the not-found short-circuits before any HTTP dispatch.
    with pytest.raises(DatasetNotFoundError) as exc_info:
        asyncio.run(propose_spec("req", "absent.csv", _settings()))
    assert exc_info.value.dataset_name == "absent.csv"


def test_propose_spec_traversal_dataset_raises_not_found() -> None:
    # A name escaping data_dir (M3.3's DatasetName would already block it; this is the
    # defense-in-depth confinement branch): resolves outside the root -> not found.
    with pytest.raises(DatasetNotFoundError):
        asyncio.run(propose_spec("req", "../weather.csv", _settings()))


def test_propose_spec_directory_name_raises_not_found() -> None:
    # A name resolving to a directory inside data_dir (here the real schemas/ dir) clears
    # confinement but is not a readable file: read_bytes raises IsADirectoryError, mapped to
    # not-found rather than an uncaught 500. The same branch fires for a *.csv-named directory
    # -- the case M3.3's DatasetName cannot exclude.
    with pytest.raises(DatasetNotFoundError):
        asyncio.run(propose_spec("req", "schemas", _settings()))


def test_propose_spec_manifest_missing_raises_not_found(tmp_path: Path) -> None:
    # CSV present but its manifest absent: the manifest read (the second read) raises
    # FileNotFoundError, still mapped to not-found -- locks the csv-present/manifest-missing
    # arm distinctly from the both-absent case.
    (tmp_path / "orphan.csv").write_bytes(b"a,b\n1,2\n")
    with pytest.raises(DatasetNotFoundError):
        asyncio.run(propose_spec("req", "orphan.csv", Settings(data_dir=tmp_path)))


def test_build_async_client_applies_timeout() -> None:
    client = model_client._build_async_client(Settings(data_dir=_DATA, model_timeout=7.5))
    try:
        assert isinstance(client, httpx.AsyncClient)
        assert client.timeout == httpx.Timeout(7.5)
    finally:
        asyncio.run(client.aclose())
