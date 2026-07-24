# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Portable regression net for the hardware-gated OpenVINO model backend.

The gate environment deliberately lacks the native runtime's numpy dependency. Install a tiny
module boundary before importing ``model_backend.engine``; every test supplies fake tokenizer and
pipeline objects, so no accelerator, model load, or native generation enters the locked suite.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Literal, cast

import pytest
from jsonschema import Draft202012Validator
from litestar.testing import TestClient

from model_backend.schema_guidance import load_guidance_schema, schema_digest, strip_guidance
from model_backend.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PATH = _ROOT / "schema" / "vplot-0.1.schema.json"
_GOOD_SPECS_DIR = _ROOT / "examples" / "good_specs"

_LENGTH = object()


class _FakeOpenVinoGenAI(ModuleType):
    GenerationFinishReason = SimpleNamespace(LENGTH=_LENGTH)

    class StructuredOutputConfig:
        def __init__(self, *, json_schema: str) -> None:
            self.json_schema = json_schema


_OPENVINO_GENAI = _FakeOpenVinoGenAI("openvino_genai")
sys.modules["openvino_genai"] = _OPENVINO_GENAI

from model_backend.app import create_app  # noqa: E402
from model_backend.engine import BackendError, Engine, GenResult  # noqa: E402
from model_backend.models import ChatMessage  # noqa: E402
from model_backend.verified_chart import (  # noqa: E402
    VERIFIED_CHART_REPLY,
    is_verified_chart_summary,
)


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
    def __init__(self) -> None:
        self.max_new_tokens = 0
        self.do_sample = False
        self.temperature = 0.0
        self.structured_output_config: _FakeOpenVinoGenAI.StructuredOutputConfig | None = None


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
        self.last_config: _Config | None = None

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
        self.last_config = config
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


def _read_json_object(path: Path) -> dict[str, Any]:
    loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


def _patch_pipeline(monkeypatch: pytest.MonkeyPatch) -> _Pipe:
    tokenizer = _Tokenizer(3)
    pipe = _Pipe(tokenizer)

    def load(_model_dir: str, _device: str, **_config: int) -> _Pipe:
        return pipe

    monkeypatch.setattr(_OPENVINO_GENAI, "LLMPipeline", load, raising=False)
    return pipe


def _loaded_engine(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> tuple[Engine, _Pipe]:
    pipe = _patch_pipeline(monkeypatch)
    return Engine.load(settings), pipe


def test_strip_guidance_removes_only_pattern_and_format_recursively() -> None:
    source: dict[str, Any] = {
        "pattern": "^root$",
        "format": "date-time",
        "required": ["outer"],
        "additionalProperties": False,
        "$defs": {
            "Inner": {
                "anyOf": [
                    {"type": "string", "pattern": "^x$", "minLength": 1},
                    {
                        "type": "object",
                        "properties": {"value": {"type": "string", "format": "uri"}},
                    },
                ]
            }
        },
    }

    assert strip_guidance(source) == {
        "required": ["outer"],
        "additionalProperties": False,
        "$defs": {
            "Inner": {
                "anyOf": [
                    {"type": "string", "minLength": 1},
                    {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    },
                ]
            }
        },
    }
    assert source["pattern"] == "^root$"
    assert source["format"] == "date-time"

    strict = _read_json_object(_SCHEMA_PATH)
    strict_text = json.dumps(strict)
    assert '"pattern"' in strict_text
    guidance_text = json.dumps(strip_guidance(strict))
    assert '"pattern"' not in guidance_text
    assert '"format"' not in guidance_text
    for structural_key in ("required", "additionalProperties", "anyOf", "$defs"):
        assert f'"{structural_key}"' in guidance_text


def test_guidance_schema_is_valid_and_accepts_all_good_goldens() -> None:
    strict = _read_json_object(_SCHEMA_PATH)
    guidance = strip_guidance(strict)
    Draft202012Validator.check_schema(guidance)
    validator = Draft202012Validator(guidance)
    good_specs = sorted(_GOOD_SPECS_DIR.glob("g*.json"))
    assert len(good_specs) == 10
    for spec_path in good_specs:
        validator.validate(_read_json_object(spec_path))


def test_load_guidance_schema_round_trips_and_fails_closed(tmp_path: Path) -> None:
    strict = _read_json_object(_SCHEMA_PATH)
    guidance_text = load_guidance_schema(_SCHEMA_PATH)

    assert '"pattern"' not in guidance_text
    assert '"format"' not in guidance_text
    assert json.loads(guidance_text) == strip_guidance(strict)
    with pytest.raises(FileNotFoundError):
        load_guidance_schema(tmp_path / "missing.json")

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_guidance_schema(invalid)


def test_load_guidance_schema_rejects_duplicate_keys(tmp_path: Path) -> None:
    schema_path = tmp_path / "duplicate.json"
    schema_path.write_text('{"type":"object","type":"array"}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_guidance_schema(schema_path)


@pytest.mark.parametrize(
    "source",
    ['{"type": NaN}', '{"type": Infinity}', '{"type": -Infinity}', '{"minimum": 1e400}'],
    ids=["nan", "positive-infinity", "negative-infinity", "overflow-float"],
)
def test_load_guidance_schema_rejects_non_finite_numbers(tmp_path: Path, source: str) -> None:
    schema_path = tmp_path / "non-finite.json"
    schema_path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="non-finite JSON"):
        load_guidance_schema(schema_path)


@pytest.mark.parametrize("source", ["{}", '{"foo": 1}'], ids=["empty", "no-schema-keyword"])
def test_load_guidance_schema_rejects_non_schema_objects(tmp_path: Path, source: str) -> None:
    schema_path = tmp_path / "not-schema.json"
    schema_path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty JSON Schema"):
        load_guidance_schema(schema_path)


def test_load_guidance_schema_keeps_non_object_root_as_type_error(tmp_path: Path) -> None:
    schema_path = tmp_path / "array.json"
    schema_path.write_text("[]", encoding="utf-8")

    with pytest.raises(TypeError, match="root must be a JSON object"):
        load_guidance_schema(schema_path)


def test_schema_digest_is_stable_raw_byte_sha256(tmp_path: Path) -> None:
    compact = tmp_path / "compact.json"
    spaced = tmp_path / "spaced.json"
    compact.write_text('{"type":"object"}', encoding="utf-8")
    spaced.write_text('{"type": "object"}', encoding="utf-8")

    digest = schema_digest(compact)
    hex_digest = digest.removeprefix("sha256:")
    assert digest.startswith("sha256:")
    assert len(hex_digest) == 64
    assert hex_digest == hex_digest.lower()
    assert set(hex_digest) <= set("0123456789abcdef")
    assert schema_digest(compact) == digest
    assert schema_digest(spaced) != digest


def test_structured_output_settings_defaults_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().structured_output is True
    assert Settings().vplot_schema_path == Path("schema/vplot-0.1.schema.json")

    monkeypatch.delenv("MODEL_BACKEND_STRUCTURED_OUTPUT", raising=False)
    monkeypatch.delenv("MODEL_BACKEND_VPLOT_SCHEMA_PATH", raising=False)
    assert Settings.from_env().structured_output is True

    monkeypatch.setenv("MODEL_BACKEND_STRUCTURED_OUTPUT", "TrUe")
    assert Settings.from_env().structured_output is True
    monkeypatch.setenv("MODEL_BACKEND_STRUCTURED_OUTPUT", "OFF")
    assert Settings.from_env().structured_output is False

    monkeypatch.setenv("MODEL_BACKEND_STRUCTURED_OUTPUT", "yes")
    monkeypatch.setenv("MODEL_BACKEND_VPLOT_SCHEMA_PATH", "custom/vplot.json")
    assert Settings.from_env().vplot_schema_path == Path("custom/vplot.json")

    monkeypatch.setenv("MODEL_BACKEND_STRUCTURED_OUTPUT", "sometimes")
    with pytest.raises(ValueError, match="invalid boolean value"):
        Settings.from_env()


def test_health_reports_loaded_schema_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    _patch_pipeline(monkeypatch)

    with TestClient(app=create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model_name": settings.model_name,
        "device": settings.device,
        "structured_output": True,
        "vplot_schema_sha256": schema_digest(settings.vplot_schema_path),
    }


def test_health_reports_disabled_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        structured_output=False,
        vplot_schema_path=Path("missing-but-disabled.json"),
    )
    _patch_pipeline(monkeypatch)

    with TestClient(app=create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model_name": settings.model_name,
        "device": settings.device,
        "structured_output": False,
        "vplot_schema_sha256": None,
    }


def test_engine_applies_structured_output_config_when_enabled_and_guided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    engine, pipe = _loaded_engine(monkeypatch, settings)

    engine.generate(
        [{"role": "user", "content": "hello"}], temperature=0.0, max_tokens=7, guided=True
    )

    assert pipe.last_config is not None
    structured = pipe.last_config.structured_output_config
    assert isinstance(structured, _FakeOpenVinoGenAI.StructuredOutputConfig)
    expected = load_guidance_schema(Path("schema/vplot-0.1.schema.json"))
    assert structured.json_schema == expected
    assert '"pattern"' not in structured.json_schema
    assert '"format"' not in structured.json_schema


def test_engine_omits_structured_output_config_when_not_guided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    engine, pipe = _loaded_engine(monkeypatch, settings)

    engine.generate(
        [{"role": "user", "content": "hello"}],
        temperature=0.0,
        max_tokens=7,
        guided=False,
    )

    assert pipe.last_config is not None
    assert pipe.last_config.structured_output_config is None


def test_engine_omits_structured_output_config_when_disabled_even_if_guided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        structured_output=False,
        vplot_schema_path=Path("missing-but-disabled.json"),
    )
    engine, pipe = _loaded_engine(monkeypatch, settings)

    engine.generate(
        [{"role": "user", "content": "hello"}], temperature=0.0, max_tokens=7, guided=True
    )

    assert pipe.last_config is not None
    assert pipe.last_config.structured_output_config is None


def test_engine_admits_exact_token_boundary_without_duplicate_special_tokens() -> None:
    engine, tokenizer, pipe = _engine(3)
    messages = [{"role": "user", "content": "hello"}]

    result = engine.generate(messages, temperature=0.0, max_tokens=7, guided=False)

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
        engine.generate(
            [{"role": "user", "content": "hello"}], temperature=0.0, max_tokens=7, guided=False
        )

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
    engine = Engine.load(
        Settings(
            model_dir=Path("model"),
            device="NPU",
            structured_output=False,
            max_prompt_len=5,
        )
    )

    with pytest.raises(BackendError):
        engine.generate(
            [{"role": "user", "content": "hello"}], temperature=0.0, max_tokens=7, guided=False
        )
    assert calls == [("model", "NPU", {"MAX_PROMPT_LEN": 5})]
    assert pipe.generate_calls == 0


class _AppEngine:
    def __init__(self) -> None:
        self.generate_calls = 0
        self.last_guided: bool | None = None

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        guided: bool,
    ) -> GenResult:
        assert messages == [{"role": "user", "content": "hello"}]
        assert temperature == 0.0
        assert max_tokens >= 1
        self.generate_calls += 1
        self.last_guided = guided
        return GenResult(text="{}", prompt_tokens=1, completion_tokens=1, finish_reason="stop")


class _RejectingAppEngine:
    def generate(
        self,
        _messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        guided: bool,
    ) -> GenResult:
        assert temperature == 0.0
        assert max_tokens >= 1
        assert guided is False
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


def test_backend_threads_guided_json_per_request(monkeypatch: pytest.MonkeyPatch) -> None:
    guided_engine = _AppEngine()
    monkeypatch.setattr(Engine, "load", classmethod(lambda _cls, _settings: guided_engine))
    guided_payload = b'{"messages":[{"role":"user","content":"hello"}],"guided_json":true}'
    with TestClient(app=create_app(Settings())) as client:
        guided_response = client.post("/v1/chat/completions", content=guided_payload)

    assert guided_response.status_code == 200
    assert guided_engine.last_guided is True

    unguided_engine = _AppEngine()
    monkeypatch.setattr(Engine, "load", classmethod(lambda _cls, _settings: unguided_engine))
    unguided_payload = b'{"messages":[{"role":"user","content":"hello"}]}'
    with TestClient(app=create_app(Settings())) as client:
        unguided_response = client.post("/v1/chat/completions", content=unguided_payload)

    assert unguided_response.status_code == 200
    assert unguided_engine.last_guided is False


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


# --- Open WebUI post-verified-chart summarize turn -----------------------------------------

# The verifier success summary (src/verifier/service/app.py), as OWUI str()-ifies it into the
# post-chart summarize turn's citation context (a <source> block in the system prompt).
_VERIFIER_SUMMARY = "Verified chart for sales.csv: all 5 checks passed."
_OWUI_SUMMARIZE_SYSTEM = f'<source id="1" name="verifier/proposeSpec">{_VERIFIER_SUMMARY}</source>'


def _msg(role: Literal["system", "user", "assistant"], content: str) -> ChatMessage:
    return ChatMessage(role=role, content=content)


@pytest.mark.parametrize(
    "messages",
    [
        (_msg("system", _OWUI_SUMMARIZE_SYSTEM), _msg("user", "Plot revenue vs orders.")),
        (_msg("user", _OWUI_SUMMARIZE_SYSTEM),),  # RAG-into-user-message injection variant
        (_msg("system", "Verified chart for orders.parquet: all 12 checks passed."),),
    ],
    ids=["system-context", "user-context", "other-dataset-and-count"],
)
def test_is_verified_chart_summary_detects_post_chart_turn(
    messages: tuple[ChatMessage, ...],
) -> None:
    assert is_verified_chart_summary(messages) is True


@pytest.mark.parametrize(
    "messages",
    [
        (_msg("system", "Available Tools: proposeSpec"), _msg("user", "plot revenue by month")),
        (
            _msg("system", "You are proposing a VPlot v0.1 chart specification."),
            _msg("user", "total revenue by month"),
        ),
        (_msg("user", "Can you verify my chart? It has 5 checks."),),
        (_msg("user", "hello there world"),),
    ],
    ids=["tool-selector", "vplot-proposer", "near-miss-prose", "plain-chat"],
)
def test_is_verified_chart_summary_ignores_other_turns(
    messages: tuple[ChatMessage, ...],
) -> None:
    assert is_verified_chart_summary(messages) is False


def test_backend_returns_fixed_reply_without_generating_on_verified_chart_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _AppEngine()
    monkeypatch.setattr(Engine, "load", classmethod(lambda _cls, _settings: engine))
    payload = {
        "messages": [
            {"role": "system", "content": _OWUI_SUMMARIZE_SYSTEM},
            {"role": "user", "content": "Plot a scatter chart of revenue versus orders."},
        ]
    }
    with TestClient(app=create_app(Settings())) as client:
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    body = response.json()
    # The fixed closing line replaces the 0.5B proposer's free-text filler; the model never ran.
    assert engine.generate_calls == 0
    assert body["object"] == "chat.completion"
    assert body["model"] == Settings().model_name
    choice = body["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"] == {"role": "assistant", "content": VERIFIED_CHART_REPLY}
    # Usage is a word-count proxy (no generation ran), matching the hardware-free stub's shape.
    usage = body["usage"]
    assert usage["completion_tokens"] == len(VERIFIED_CHART_REPLY.split())
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_backend_generates_when_no_verified_chart_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _AppEngine()
    monkeypatch.setattr(Engine, "load", classmethod(lambda _cls, _settings: engine))
    with TestClient(app=create_app(Settings())) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200
    # No verifier summary -> the model runs (canned path is summary-gated, not the default).
    assert engine.generate_calls == 1
    assert response.json()["choices"][0]["message"]["content"] == "{}"
