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
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from verifier import canon
from verifier.service import model_client
from verifier.service.model_client import (
    DatasetNotFoundError,
    ModelUpstreamError,
    ProposerPolicyError,
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

    def stream_handler(request: httpx.Request) -> httpx.Response:
        response = handler(request)
        if not response.is_stream_consumed:
            return response
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=_TrackingStream((response.content,)),
        )

    def build(settings: Settings) -> httpx.AsyncClient:
        # Mirror the real factory's timeout wiring (harmless under MockTransport).
        return httpx.AsyncClient(
            transport=httpx.MockTransport(stream_handler), timeout=settings.model_timeout
        )

    monkeypatch.setattr(model_client, "_build_async_client", build)


def _returns(response: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    """A handler that ignores the request and returns a fixed response."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    return handler


def _chat_response(content: str = _CONTENT) -> bytes:
    """One compact valid chat-completion envelope as bytes."""
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


class _TrackingStream(httpx.AsyncByteStream):
    """Chunked response stream recording which chunks the bounded reader requested."""

    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.yielded = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.yielded += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _FailingStream(httpx.AsyncByteStream):
    """One partial body chunk followed by a transport read failure."""

    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"partial":'
        msg = "stream reset"
        raise httpx.ReadError(msg)

    async def aclose(self) -> None:
        self.closed = True


def test_propose_spec_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        body = {"choices": [{"message": {"role": "assistant", "content": _CONTENT}}]}
        return httpx.Response(200, json=body, headers={"content-encoding": "identity"})

    _install(monkeypatch, handler)
    result = asyncio.run(
        propose_spec("Plot average temperature by city", "weather.csv", _settings())
    )

    # Raw content bytes, verbatim and undecoded.
    assert result == _CONTENT.encode("utf-8")

    request = captured["request"]
    assert str(request.url) == "http://127.0.0.1:8001/v1/chat/completions"
    sent = json.loads(request.content)
    assert request.headers["accept-encoding"] == "identity"
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

    # The incremental byte-budget builder must preserve the pre-M5 prompt byte-for-byte; even a
    # newline drift changes the deterministic weak-model observation for a fixed backend/config.
    sample = "\n".join((_DATA / "weather.csv").read_text(encoding="utf-8").splitlines()[:6])
    columns = "\n".join(
        [
            "date: temporal (date)",
            "city: string",
            "temp_c: numeric (scale 1, unit °C)",
            "precip_mm: numeric (scale 1, unit mm)",
            "aqi: numeric (scale 0)",
        ]
    )
    assert user["content"] == "\n".join(
        [
            "Dataset name: weather.csv",
            "Copy this dataset binding verbatim into the spec's dataset field:",
            binding,
            "Columns (use these exact names):",
            columns,
            "Sample rows (CSV with header, up to 5 data row(s)):",
            sample,
            "User request: Plot average temperature by city",
            "Reply with only the VPlot JSON spec.",
        ]
    )


def test_user_request_utf8_byte_boundary_and_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two-byte scalars pin bytes rather than code points. The exact 4-byte request reaches the
    # old backend path; lowering the inclusive cap by one refuses before a second dispatch.
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_chat_response())

    _install(monkeypatch, handler)
    request = "éé"
    exact = Settings(data_dir=_DATA, max_user_request_bytes=4)
    assert asyncio.run(propose_spec(request, "weather.csv", exact)) == _CONTENT.encode()
    assert calls == 1

    over = Settings(data_dir=_DATA, max_user_request_bytes=3)
    with pytest.raises(ProposerPolicyError, match="user request") as exc_info:
        asyncio.run(propose_spec(request, "weather.csv", over))
    assert exc_info.value.resource == "resource.user_request_bytes"
    assert calls == 1


def test_assembled_prompt_byte_boundary_and_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    # Derive the real message-content byte count once under the generous default. That exact cap
    # dispatches unchanged; cap-1 fails during assembly and the spy sees no second backend call.
    baseline = _settings()
    manifest, csv_bytes = model_client._load_dataset_context("weather.csv", baseline)
    messages = model_client._build_messages("req", "weather.csv", manifest, csv_bytes, baseline)
    prompt_bytes = sum(len(message["content"].encode("utf-8")) for message in messages)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_chat_response())

    _install(monkeypatch, handler)
    exact = Settings(data_dir=_DATA, max_prompt_bytes=prompt_bytes)
    assert asyncio.run(propose_spec("req", "weather.csv", exact)) == _CONTENT.encode()
    assert calls == 1

    over = Settings(data_dir=_DATA, max_prompt_bytes=prompt_bytes - 1)
    with pytest.raises(ProposerPolicyError, match="assembled proposer prompt") as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", over))
    assert exc_info.value.resource == "resource.prompt_bytes"
    assert calls == 1


def test_maximum_sample_row_setting_does_not_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings admits signed-int64 max. Sampling the finite bounded CSV with that value must not
    # compute max+1 for islice (outside sys.maxsize); it simply consumes every available row.
    _install(monkeypatch, _returns(httpx.Response(200, content=_chat_response())))
    settings = Settings(data_dir=_DATA, model_sample_rows=2**63 - 1)
    assert asyncio.run(propose_spec("req", "weather.csv", settings)) == _CONTENT.encode()


def test_oversized_sample_fails_before_final_prompt_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One giant sampled cell crosses the remaining budget. Patch finish() only as an observation:
    # incremental admission must raise while appending that cell, before the whole user prompt is
    # joined or any backend client is built.
    csv_bytes = b"value\n" + b"x" * 10_000 + b"\n"
    manifest_bytes = b'{"dataset":"large.csv","columns":[{"type":"string","name":"value"}]}'
    (tmp_path / "schemas").mkdir()
    (tmp_path / "large.csv").write_bytes(csv_bytes)
    (tmp_path / "schemas" / "large.json").write_bytes(manifest_bytes)
    finished = False

    def finish(_self: model_client._PromptAssembler) -> str:
        nonlocal finished
        finished = True
        return "unexpected"

    monkeypatch.setattr(model_client._PromptAssembler, "finish", finish)
    settings = Settings(
        data_dir=tmp_path,
        max_csv_bytes=len(csv_bytes),
        max_manifest_bytes=len(manifest_bytes),
        max_prompt_bytes=3_000,
    )
    with pytest.raises(ProposerPolicyError) as exc_info:
        asyncio.run(propose_spec("req", "large.csv", settings))
    assert exc_info.value.resource == "resource.prompt_bytes"
    assert finished is False


@pytest.mark.parametrize(
    ("limit_field", "resource"),
    [
        ("max_csv_bytes", "resource.csv_bytes"),
        ("max_manifest_bytes", "resource.manifest_bytes"),
    ],
)
def test_dataset_file_byte_boundary_and_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_field: str,
    resource: str,
) -> None:
    csv_bytes = b"value\nok\n"
    manifest_bytes = b'{"dataset":"tiny.csv","columns":[{"type":"string","name":"value"}]}'
    (tmp_path / "schemas").mkdir()
    (tmp_path / "tiny.csv").write_bytes(csv_bytes)
    (tmp_path / "schemas" / "tiny.json").write_bytes(manifest_bytes)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_chat_response())

    _install(monkeypatch, handler)
    assert (
        asyncio.run(
            propose_spec(
                "req",
                "tiny.csv",
                Settings(
                    data_dir=tmp_path,
                    max_csv_bytes=len(csv_bytes),
                    max_manifest_bytes=len(manifest_bytes),
                ),
            )
        )
        == _CONTENT.encode()
    )
    assert calls == 1

    csv_limit = len(csv_bytes) - (limit_field == "max_csv_bytes")
    manifest_limit = len(manifest_bytes) - (limit_field == "max_manifest_bytes")
    with pytest.raises(ProposerPolicyError) as exc_info:
        asyncio.run(
            propose_spec(
                "req",
                "tiny.csv",
                Settings(
                    data_dir=tmp_path,
                    max_csv_bytes=csv_limit,
                    max_manifest_bytes=manifest_limit,
                ),
            )
        )
    assert exc_info.value.resource == resource
    assert calls == 1


def test_manifest_column_policy_short_circuits_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_chat_response())

    _install(monkeypatch, handler)
    with pytest.raises(ProposerPolicyError) as exc_info:
        asyncio.run(
            propose_spec("req", "weather.csv", Settings(data_dir=_DATA, max_manifest_columns=1))
        )
    assert exc_info.value.resource == "resource.manifest_columns"
    assert calls == 0


def test_propose_spec_unreachable_raises_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        msg = "connection refused"
        raise httpx.ConnectError(msg)

    _install(monkeypatch, handler)
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 503
    assert "unreachable" in str(exc_info.value)


def test_propose_spec_stream_read_error_raises_503(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FailingStream()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    _install(monkeypatch, handler)
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 503
    assert stream.closed is True


def test_propose_spec_non_2xx_raises_502(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _returns(httpx.Response(500, json={"error": "boom"})))
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 502
    assert "HTTP 500" in str(exc_info.value)


def test_exact_backend_prompt_too_long_shape_raises_policy_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"error": {"message": "prompt exceeds token ceiling", "type": "prompt_too_long"}}
    _install(monkeypatch, _returns(httpx.Response(400, json=body)))

    with pytest.raises(ProposerPolicyError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))

    assert exc_info.value.resource == "resource.prompt_tokens"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            500,
            json={"error": {"message": "prompt exceeds token ceiling", "type": "prompt_too_long"}},
        ),
        httpx.Response(
            400,
            json={"error": {"message": "prompt exceeds token ceiling", "type": "other"}},
        ),
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "prompt exceeds token ceiling",
                    "type": "prompt_too_long",
                    "extra": True,
                }
            },
        ),
        httpx.Response(
            400,
            json={
                "error": {"message": "prompt exceeds token ceiling", "type": "prompt_too_long"},
                "extra": True,
            },
        ),
        httpx.Response(
            400,
            content=b'{"error":{"message":"x","type":"prompt_too_long"}}',
            headers={"content-type": "text/plain"},
        ),
        httpx.Response(
            400,
            content=(b'{"error":{"message":"x","type":"other","type":"prompt_too_long"}}'),
            headers={"content-type": "application/json"},
        ),
        httpx.Response(
            400,
            content=b'{"error": {"message":"x","type":"prompt_too_long"}}',
            headers={"content-type": "application/json"},
        ),
    ],
    ids=[
        "wrong-status",
        "wrong-type",
        "inner-extra",
        "outer-extra",
        "wrong-media-type",
        "duplicate-key",
        "noncanonical-json",
    ],
)
def test_backend_error_shape_spoofs_stay_upstream_502(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _install(monkeypatch, _returns(response))
    with pytest.raises(ModelUpstreamError) as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 502


def test_encoded_model_response_is_refused_before_decompression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The client requests identity and consumes raw bytes. A backend ignoring that request is an
    # unusable 502 response, never an input to HTTPX's transparent decompressor or JSON decoder.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=_TrackingStream((_chat_response(),)),
        )

    _install(monkeypatch, handler)
    with pytest.raises(ModelUpstreamError, match="unsupported content encoding") as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", _settings()))
    assert exc_info.value.status == 502


def test_model_response_exact_byte_boundary_and_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _chat_response()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=body)

    _install(monkeypatch, handler)
    exact = Settings(data_dir=_DATA, max_model_response_bytes=len(body))
    assert asyncio.run(propose_spec("req", "weather.csv", exact)) == _CONTENT.encode()

    over = Settings(data_dir=_DATA, max_model_response_bytes=len(body) - 1)
    with pytest.raises(ModelUpstreamError, match="exceeds byte limit") as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", over))
    assert exc_info.value.status == 502
    assert calls == 2


@pytest.mark.parametrize("status", [200, 500])
def test_chunked_oversized_response_stops_at_limit_plus_one_before_decode(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    # The first chunk reaches the inclusive cap, the second is the +1 probe, and the tail must
    # never be requested. Patch envelope extraction as a non-vacuity witness for decode ordering.
    stream = _TrackingStream((b"12345", b"6", b"tail-must-not-be-read"))
    decoded = False

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, stream=stream)

    def extract(_response_bytes: bytes) -> bytes:
        nonlocal decoded
        decoded = True
        return b"unexpected"

    _install(monkeypatch, handler)
    monkeypatch.setattr(model_client, "_extract_content", extract)
    settings = Settings(data_dir=_DATA, max_model_response_bytes=5)
    with pytest.raises(ModelUpstreamError, match="exceeds byte limit") as exc_info:
        asyncio.run(propose_spec("req", "weather.csv", settings))
    assert exc_info.value.status == 502
    assert stream.yielded == 2
    assert stream.closed is True
    assert decoded is False


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
