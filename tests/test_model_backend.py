# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Portable regression net for the hardware-gated OpenVINO model backend.

The gate environment deliberately lacks the native runtime's numpy dependency. Install a tiny
module boundary before importing ``model_backend.engine``; every test supplies fake tokenizer and
pipeline objects, so no accelerator, model load, or native generation enters the locked suite.
"""

import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from litestar.testing import TestClient

_LENGTH = object()


class _FakeOpenVinoGenAI(ModuleType):
    GenerationFinishReason = SimpleNamespace(LENGTH=_LENGTH)


_OPENVINO_GENAI = _FakeOpenVinoGenAI("openvino_genai")
sys.modules["openvino_genai"] = _OPENVINO_GENAI

from model_backend.app import create_app  # noqa: E402
from model_backend.engine import BackendError, Engine, GenResult  # noqa: E402
from model_backend.settings import Settings  # noqa: E402


class _Tensor:
    def __init__(self, token_count: int) -> None:
        self.shape = (1, token_count)


class _Tokenized:
    def __init__(self, token_count: int) -> None:
        self.input_ids = _Tensor(token_count)


class _Tokenizer:
    def __init__(self, token_count: int) -> None:
        self.token_count = token_count
        self.encode_calls: list[tuple[str, bool, int]] = []
        self.encoded: _Tokenized | None = None

    def apply_chat_template(
        self, messages: list[dict[str, str]], *, add_generation_prompt: bool
    ) -> str:
        assert add_generation_prompt is True
        return f"templated:{messages!r}"

    def encode(self, prompt: str, *, add_special_tokens: bool, max_length: int) -> _Tokenized:
        self.encode_calls.append((prompt, add_special_tokens, max_length))
        # Model either native behavior (the full count) or a tokenizer that truncates at the
        # sentinel. Both expose cap+1 for an overlong prompt and must fail closed.
        self.encoded = _Tokenized(min(self.token_count, max_length))
        return self.encoded

    def decode(self, tokens: tuple[int, ...]) -> str:
        assert tokens == (7,)
        return "{}"


class _Config:
    max_new_tokens = 0
    do_sample = False
    temperature = 0.0


class _Metrics:
    def get_num_input_tokens(self) -> int:
        return 3

    def get_num_generated_tokens(self) -> int:
        return 1


class _Encoded:
    tokens = ((7,),)
    perf_metrics = _Metrics()
    finish_reasons = (object(),)


class _Pipe:
    def __init__(self, tokenizer: _Tokenizer) -> None:
        self.tokenizer = tokenizer
        self.config_calls = 0
        self.generate_calls = 0

    def get_tokenizer(self) -> _Tokenizer:
        return self.tokenizer

    def get_generation_config(self) -> _Config:
        self.config_calls += 1
        return _Config()

    def generate(self, tokenized: _Tokenized, config: _Config) -> _Encoded:
        # Generation must consume the exact admitted buffer, never a string it can template or
        # tokenize differently after the preflight decision.
        assert tokenized is self.tokenizer.encoded
        assert config.max_new_tokens == 7
        self.generate_calls += 1
        return _Encoded()


def _engine(token_count: int, *, max_prompt_len: int = 3) -> tuple[Engine, _Tokenizer, _Pipe]:
    tokenizer = _Tokenizer(token_count)
    pipe = _Pipe(tokenizer)
    return (
        Engine(
            pipe,
            tokenizer,
            max_prompt_len=max_prompt_len,
            max_response_bytes=1024,
        ),
        tokenizer,
        pipe,
    )


def test_engine_admits_exact_token_boundary_without_duplicate_special_tokens() -> None:
    engine, tokenizer, pipe = _engine(3)
    messages = [{"role": "user", "content": "hello"}]

    result = engine.generate(messages, temperature=0.0, max_tokens=7)

    prompt = f"templated:{messages!r}"
    assert tokenizer.encode_calls == [(prompt, False, 4)]
    assert pipe.config_calls == 1
    assert pipe.generate_calls == 1
    assert result == GenResult(
        text="{}", prompt_tokens=3, completion_tokens=1, finish_reason="stop"
    )


@pytest.mark.parametrize("token_count", [4, 100], ids=["one-over", "sentinel-truncation"])
def test_engine_rejects_overlong_prompt_before_native_generation(token_count: int) -> None:
    engine, tokenizer, pipe = _engine(token_count)

    with pytest.raises(BackendError, match=r"prompt.*token ceiling") as exc_info:
        engine.generate([{"role": "user", "content": "hello"}], temperature=0.0, max_tokens=7)

    assert exc_info.value.status == 400
    assert exc_info.value.error_type == "prompt_too_long"
    assert tokenizer.encode_calls[0][1:] == (False, 4)
    assert pipe.config_calls == 0
    assert pipe.generate_calls == 0


def test_engine_load_retains_prompt_cap_and_npu_static_shape_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, int]]] = []
    tokenizer = _Tokenizer(6)
    pipe = _Pipe(tokenizer)

    def load(model_dir: str, device: str, **config: int) -> _Pipe:
        calls.append((model_dir, device, config))
        return pipe

    monkeypatch.setattr(_OPENVINO_GENAI, "LLMPipeline", load, raising=False)
    engine = Engine.load(Settings(model_dir=Path("model"), device="NPU", max_prompt_len=5))

    with pytest.raises(BackendError):
        engine.generate([{"role": "user", "content": "hello"}], temperature=0.0, max_tokens=7)
    assert calls == [("model", "NPU", {"MAX_PROMPT_LEN": 5})]
    assert pipe.generate_calls == 0


class _AppEngine:
    def __init__(self) -> None:
        self.generate_calls = 0

    def generate(
        self, messages: list[dict[str, str]], *, temperature: float, max_tokens: int
    ) -> GenResult:
        assert messages == [{"role": "user", "content": "hello"}]
        assert temperature == 0.0
        assert max_tokens >= 1
        self.generate_calls += 1
        return GenResult(text="{}", prompt_tokens=1, completion_tokens=1, finish_reason="stop")


class _RejectingAppEngine:
    def generate(
        self, _messages: list[dict[str, str]], *, temperature: float, max_tokens: int
    ) -> GenResult:
        assert temperature == 0.0
        assert max_tokens >= 1
        msg = "prompt is too long"
        raise BackendError(msg, status=400, error_type="prompt_too_long")


def test_backend_body_cap_accepts_boundary_and_rejects_plus_one_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _AppEngine()
    monkeypatch.setattr(Engine, "load", classmethod(lambda _cls, _settings: engine))
    payload = b'{"messages":[{"role":"user","content":"hello"}]}'
    settings = Settings(max_body_bytes=len(payload))

    with TestClient(app=create_app(settings)) as client:
        exact = client.post("/v1/chat/completions", content=payload)

        def over_limit() -> Iterator[bytes]:
            yield payload
            yield b" "

        over = client.post("/v1/chat/completions", content=over_limit())

    assert exact.status_code == 200
    assert over.status_code == 413
    # The +1 body is still valid JSON if decoded. No second call proves the cap fired first.
    assert engine.generate_calls == 1


def test_backend_request_body_setting_default_env_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().max_body_bytes == 128 * 1024
    monkeypatch.setenv("MODEL_BACKEND_MAX_BODY_BYTES", "17")
    assert Settings.from_env().max_body_bytes == 17
    with pytest.raises(ValueError, match="max_body_bytes"):
        Settings(max_body_bytes=0)


def test_backend_error_response_keeps_exact_openai_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _RejectingAppEngine()
    monkeypatch.setattr(Engine, "load", classmethod(lambda _cls, _settings: engine))
    with TestClient(app=create_app(Settings())) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert response.content == (
        b'{"error":{"message":"prompt is too long","type":"prompt_too_long"}}'
    )
    assert response.json() == {
        "error": {"message": "prompt is too long", "type": "prompt_too_long"}
    }
