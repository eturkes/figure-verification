# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M12.3 red suite — xgrammar schema guidance on the torch/transformers engine.

Diff-blind: written against `.scratch/m12u3-contract.md` and the normative registers ONLY, never
against MAIN's implementation. One test per contract predicate id; the id leads the test name so a
failure names the predicate it falsifies. Predicates encode MAIN's phase-1 rulings, including G18's
model-authoritative stop ids.

The suite runs on the root `.venv` (py3.13), which has no torch, transformers, or xgrammar. An
isolated engine import receives strict `sys.modules` fakes for both native packages without
replacing the canonical `model_backend.engine` module used by the existing suite.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Never, cast, get_args

import pytest

from model_backend.schema_guidance import load_guidance_schema
from model_backend.settings import (
    DATASET_SCHEMA_ID,
    FORMULA_SCHEMA_ID,
    GuidanceSchemaId,
    Settings,
)

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_PATH = _ROOT / "model_backend" / "engine.py"
_ENGINE_MODULE_NAME = "model_backend._m12u3_engine_under_test"
_MISSING = object()
_FACTORY_KEY = object()


@dataclass(frozen=True)
class _RecordedCall:
    args: tuple[object, ...]
    kwargs: dict[str, object]
    result: object | None = None


def _raise_type(message: object) -> Never:
    raise TypeError(message)


def _raise_value(message: str) -> Never:
    raise ValueError(message)


def _raise_runtime(message: str) -> Never:
    raise RuntimeError(message)


class _FatalSetupError(BaseException):
    pass


class _Vector:
    def __init__(self, tokens: tuple[int, ...]) -> None:
        self.tokens = tokens
        self.shape = (len(tokens),)

    def __getitem__(self, key: object) -> int:
        if isinstance(key, int):
            return self.tokens[key]
        _raise_type(key)


class _Matrix:
    def __init__(self, tokens: tuple[int, ...], *, device: str | None = None) -> None:
        self.tokens = tokens
        self.device = device
        self.shape = (1, len(tokens))

    def to(self, device: str) -> _Matrix:
        return _Matrix(self.tokens, device=device)

    def __getitem__(self, key: object) -> object:
        if not isinstance(key, tuple) or len(key) != 2:
            _raise_type(key)
        row, column = key
        if row == 0 and isinstance(column, slice):
            return _Vector(self.tokens[column])
        if row == 0 and isinstance(column, int):
            return self.tokens[column]
        if row == slice(None) and isinstance(column, slice):
            return _Matrix(self.tokens[column], device=self.device)
        _raise_type(key)


class _Encoding(dict[str, object]):
    def __init__(self, prompt_tokens: tuple[int, ...] = (11, 12, 13)) -> None:
        super().__init__(
            input_ids=_Matrix(prompt_tokens),
            attention_mask=_Matrix(tuple(1 for _ in prompt_tokens)),
        )
        self.to_calls: list[str] = []
        self.moved_input_ids: object | None = None

    def to(self, device: str) -> _Encoding:
        self.to_calls.append(device)
        for key, value in tuple(self.items()):
            if isinstance(value, _Matrix):
                self[key] = value.to(device)
        self.moved_input_ids = self["input_ids"]
        return self


class _Tokenizer:
    def __init__(
        self,
        *,
        encoding: _Encoding | None = None,
        decoded: str = "{}",
        vocab_size: int = 7,
        eos_token_id: object = 4242,
    ) -> None:
        self.encoding = encoding if encoding is not None else _Encoding()
        self.decoded = decoded
        self.eos_token_id = eos_token_id
        self._vocab = {f"token-{index}": index for index in range(vocab_size)}
        self.apply_calls: list[tuple[list[dict[str, str]], dict[str, object]]] = []
        self.decode_calls: list[tuple[object, bool]] = []

    def __len__(self) -> int:
        return len(self._vocab)

    def get_vocab(self) -> dict[str, int]:
        return dict(self._vocab)

    def apply_chat_template(self, messages: list[dict[str, str]], **kwargs: object) -> _Encoding:
        self.apply_calls.append((messages, dict(kwargs)))
        return self.encoding

    def decode(self, ids: object, *, skip_special_tokens: bool) -> str:
        self.decode_calls.append((ids, skip_special_tokens))
        return self.decoded


class _GenerationConfig:
    def __init__(self, eos_token_id: object, pad_token_id: object) -> None:
        self.eos_token_id = eos_token_id
        self.pad_token_id = pad_token_id


class _ModelConfig:
    def __init__(self, vocab_size: int) -> None:
        self.vocab_size = vocab_size


class _Model:
    def __init__(
        self,
        *,
        suffixes: tuple[tuple[int, ...], ...] = ((7, 3),),
        eos_token_id: object = (9, 3),
        pad_token_id: object = 77,
        vocab_size: int = 31,
    ) -> None:
        self.suffixes = suffixes
        self.generation_config = _GenerationConfig(eos_token_id, pad_token_id)
        self.config = _ModelConfig(vocab_size)
        self.to_calls: list[str] = []
        self.generate_calls: list[dict[str, object]] = []

    def to(self, device: str) -> _Model:
        self.to_calls.append(device)
        return self

    def generate(self, **kwargs: object) -> _Matrix:
        call_index = len(self.generate_calls)
        self.generate_calls.append(dict(kwargs))
        processors = kwargs.get("logits_processor")
        if processors is not None:
            if not isinstance(processors, list):
                _raise_type("logits_processor must be list-like")
            for processor in processors:
                if isinstance(processor, _FakeLogitsProcessor):
                    processor.consume()
        input_ids = kwargs["input_ids"]
        if not isinstance(input_ids, _Matrix):
            _raise_type("input_ids must be a 2-D tensor stand-in")
        suffix = self.suffixes[min(call_index, len(self.suffixes) - 1)]
        return _Matrix(input_ids.tokens + suffix, device=input_ids.device)


class _Runtime:
    def __init__(self, tokenizer: _Tokenizer, model: _Model) -> None:
        self.tokenizer = tokenizer
        self.model = model
        self.tokenizer_load_calls: list[_RecordedCall] = []
        self.model_load_calls: list[_RecordedCall] = []


_ACTIVE_RUNTIME: list[_Runtime | None] = [None]


def _runtime() -> _Runtime:
    runtime = _ACTIVE_RUNTIME[0]
    if runtime is None:
        _raise_runtime("test must install a fake runtime")
    return runtime


class _FakeAutoTokenizer:
    @classmethod
    def from_pretrained(
        cls,
        pretrained_model_name_or_path: object,
        *inputs: object,
        **kwargs: object,
    ) -> _Tokenizer:
        runtime = _runtime()
        runtime.tokenizer_load_calls.append(
            _RecordedCall((pretrained_model_name_or_path, *inputs), dict(kwargs), runtime.tokenizer)
        )
        return runtime.tokenizer


class _FakeAutoModelForCausalLM:
    @classmethod
    def from_pretrained(
        cls,
        pretrained_model_name_or_path: object,
        *model_args: object,
        **kwargs: object,
    ) -> _Model:
        runtime = _runtime()
        runtime.model_load_calls.append(
            _RecordedCall((pretrained_model_name_or_path, *model_args), dict(kwargs), runtime.model)
        )
        return runtime.model


class _FakeTransformersLogitsProcessor:
    def __call__(self, _input_ids: object, _scores: object) -> object:
        raise NotImplementedError


class _FakeLogitsProcessorList(list[object]):
    pass


class _XGrammarState:
    def __init__(self) -> None:
        self.tokenizer_info_calls: list[_RecordedCall] = []
        self.tokenizer_infos: list[_FakeTokenizerInfo] = []
        self.compiler_init_calls: list[_RecordedCall] = []
        self.compilers: list[_FakeGrammarCompiler] = []
        self.compile_calls: list[_RecordedCall] = []
        self.processors: list[_FakeLogitsProcessor] = []
        self.tokenizer_info_error: BaseException | None = None
        self.compiler_init_error: BaseException | None = None
        self.compile_fail_at: set[int] = set()
        self.ignore_requested_vocab_size = False

    def clear_calls(self) -> None:
        self.tokenizer_info_calls.clear()
        self.tokenizer_infos.clear()
        self.compiler_init_calls.clear()
        self.compilers.clear()
        self.compile_calls.clear()
        self.processors.clear()


_ACTIVE_XGRAMMAR_STATE: list[_XGrammarState | None] = [None]


def _xgrammar_state() -> _XGrammarState:
    state = _ACTIVE_XGRAMMAR_STATE[0]
    if state is None:
        _raise_runtime("test must install fake xgrammar state")
    return state


def _bind_primary_argument(
    name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> tuple[object, dict[str, object]]:
    if len(args) > 1:
        _raise_type(f"too many positional arguments for {name}")
    remaining = dict(kwargs)
    if args:
        if name in remaining:
            _raise_type(f"multiple values for {name}")
        return args[0], remaining
    if name not in remaining:
        _raise_type(f"missing required argument: {name}")
    return remaining.pop(name), remaining


class _FakeTokenizerInfo:
    __slots__ = ("_vocab_size", "source_tokenizer", "stop_token_ids")

    def __init__(
        self,
        key: object,
        *,
        source_tokenizer: object,
        vocab_size: int,
        stop_token_ids: tuple[int, ...],
    ) -> None:
        if key is not _FACTORY_KEY:
            _raise_type("TokenizerInfo must come from from_huggingface")
        self.source_tokenizer = source_tokenizer
        self._vocab_size = vocab_size
        self.stop_token_ids = stop_token_ids

    @property
    def vocab_size(self) -> int:
        return self._vocab_size

    @staticmethod
    def from_huggingface(*args: object, **kwargs: object) -> _FakeTokenizerInfo:
        state = _xgrammar_state()
        state.tokenizer_info_calls.append(_RecordedCall(tuple(args), dict(kwargs)))
        if state.tokenizer_info_error is not None:
            raise state.tokenizer_info_error

        tokenizer, options = _bind_primary_argument("tokenizer", tuple(args), dict(kwargs))
        unknown = set(options) - {"vocab_size", "stop_token_ids"}
        if unknown:
            _raise_type(f"unexpected TokenizerInfo kwargs: {sorted(unknown)}")
        raw_stop_ids = options.get("stop_token_ids")
        if isinstance(raw_stop_ids, list) and not raw_stop_ids:
            _raise_value("stop_token_ids cannot be empty")

        get_vocab: Any = getattr(tokenizer, "get_vocab", None)
        if get_vocab is None:
            _raise_value("tokenizer must provide get_vocab")
        raw_vocab: Any = get_vocab()
        if not isinstance(raw_vocab, dict):
            _raise_value("get_vocab must return a dictionary")
        vocab = cast("dict[str, int]", raw_vocab)
        derived_vocab_size = max(len(vocab), max(vocab.values()) + 1)
        requested_vocab_size = options.get("vocab_size")
        reported_vocab_size = (
            derived_vocab_size
            if state.ignore_requested_vocab_size or not requested_vocab_size
            else requested_vocab_size
        )
        if not isinstance(reported_vocab_size, int):
            _raise_type("vocab_size must be an integer")

        if raw_stop_ids is None:
            raw_stop_ids = getattr(tokenizer, "eos_token_id", None)
        if isinstance(raw_stop_ids, int):
            stop_token_ids = (raw_stop_ids,)
        elif isinstance(raw_stop_ids, list) and all(isinstance(item, int) for item in raw_stop_ids):
            stop_token_ids = tuple(raw_stop_ids)
        else:
            _raise_type("stop_token_ids must be an int or list[int]")

        result = _FakeTokenizerInfo(
            _FACTORY_KEY,
            source_tokenizer=tokenizer,
            vocab_size=reported_vocab_size,
            stop_token_ids=stop_token_ids,
        )
        state.tokenizer_infos.append(result)
        return result


class _FakeCompiledGrammar:
    __slots__ = ("_tokenizer_info", "ordinal", "schema")

    def __init__(
        self,
        key: object,
        *,
        schema: object,
        tokenizer_info: _FakeTokenizerInfo,
        ordinal: int,
    ) -> None:
        if key is not _FACTORY_KEY:
            _raise_type("CompiledGrammar must come from GrammarCompiler")
        self.schema = schema
        self._tokenizer_info = tokenizer_info
        self.ordinal = ordinal

    @property
    def tokenizer_info(self) -> _FakeTokenizerInfo:
        return self._tokenizer_info


class _FakeGrammarCompiler:
    def __init__(
        self,
        tokenizer_info: _FakeTokenizerInfo,
        *,
        max_threads: int = 8,
        cache_enabled: bool = True,
        cache_limit_bytes: int = -1,
    ) -> None:
        if not isinstance(tokenizer_info, _FakeTokenizerInfo):
            _raise_value("Please convert the tokenizer to TokenizerInfo")
        state = _xgrammar_state()
        state.compiler_init_calls.append(
            _RecordedCall(
                (tokenizer_info,),
                {
                    "max_threads": max_threads,
                    "cache_enabled": cache_enabled,
                    "cache_limit_bytes": cache_limit_bytes,
                },
                self,
            )
        )
        if state.compiler_init_error is not None:
            raise state.compiler_init_error
        self.tokenizer_info = tokenizer_info
        state.compilers.append(self)

    def compile_json_schema(self, *args: object, **kwargs: object) -> _FakeCompiledGrammar:
        state = _xgrammar_state()
        original_kwargs = dict(kwargs)
        schema, options = _bind_primary_argument("schema", tuple(args), dict(kwargs))
        allowed = {
            "any_whitespace",
            "indent",
            "separators",
            "strict_mode",
            "max_whitespace_cnt",
            "any_order",
        }
        unknown = set(options) - allowed
        if unknown:
            _raise_type(f"unexpected compile kwargs: {sorted(unknown)}")
        if not isinstance(schema, (str, dict)):
            _raise_value("schema must be the engine's string or dict form")

        call_index = len(state.compile_calls)
        if call_index in state.compile_fail_at:
            state.compile_calls.append(_RecordedCall(tuple(args), original_kwargs))
            _raise_runtime(f"synthetic compile failure at call {call_index}")
        result = _FakeCompiledGrammar(
            _FACTORY_KEY,
            schema=schema,
            tokenizer_info=self.tokenizer_info,
            ordinal=call_index,
        )
        state.compile_calls.append(_RecordedCall(tuple(args), original_kwargs, result))
        return result


class _FakeLogitsProcessor(_FakeTransformersLogitsProcessor):
    def __init__(self, compiled_grammar: _FakeCompiledGrammar | list[_FakeCompiledGrammar]) -> None:
        candidate = compiled_grammar[0] if isinstance(compiled_grammar, list) else compiled_grammar
        _ = candidate.tokenizer_info.vocab_size
        self.compiled_grammar = compiled_grammar
        self._used = False
        _xgrammar_state().processors.append(self)

    def consume(self) -> None:
        if self._used:
            _raise_runtime("a LogitsProcessor cannot be reused across generate calls")
        self._used = True


@dataclass(frozen=True)
class _Harness:
    engine_module: Any
    xgrammar: _XGrammarState


@pytest.fixture
def harness() -> Iterator[_Harness]:

    state = _XGrammarState()
    transformers = ModuleType("transformers")
    transformers.__dict__.update(
        {
            "AutoModelForCausalLM": _FakeAutoModelForCausalLM,
            "AutoTokenizer": _FakeAutoTokenizer,
            "LogitsProcessor": _FakeTransformersLogitsProcessor,
            "LogitsProcessorList": _FakeLogitsProcessorList,
        }
    )

    xgrammar = ModuleType("xgrammar")
    contrib = ModuleType("xgrammar.contrib")
    hf = ModuleType("xgrammar.contrib.hf")
    xgrammar.__dict__.update(
        {
            "__path__": [],
            "CompiledGrammar": _FakeCompiledGrammar,
            "GrammarCompiler": _FakeGrammarCompiler,
            "TokenizerInfo": _FakeTokenizerInfo,
            "contrib": contrib,
            "hf": hf,
        }
    )
    contrib.__dict__.update({"__path__": [], "hf": hf})
    hf.__dict__["LogitsProcessor"] = _FakeLogitsProcessor

    replacements = {
        "transformers": transformers,
        "xgrammar": xgrammar,
        "xgrammar.contrib": contrib,
        "xgrammar.contrib.hf": hf,
    }
    previous = {name: sys.modules.get(name, _MISSING) for name in replacements}
    previous_engine = sys.modules.get(_ENGINE_MODULE_NAME, _MISSING)
    previous_runtime = _ACTIVE_RUNTIME[0]
    previous_state = _ACTIVE_XGRAMMAR_STATE[0]
    sys.modules.update(replacements)
    _ACTIVE_XGRAMMAR_STATE[0] = state

    spec = importlib.util.spec_from_file_location(_ENGINE_MODULE_NAME, _ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_ENGINE_MODULE_NAME] = module
    spec.loader.exec_module(module)
    try:
        yield _Harness(module, state)
    finally:
        _ACTIVE_RUNTIME[0] = previous_runtime
        _ACTIVE_XGRAMMAR_STATE[0] = previous_state
        for name, prior in previous.items():
            if prior is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = cast("ModuleType", prior)
        if previous_engine is _MISSING:
            sys.modules.pop(_ENGINE_MODULE_NAME, None)
        else:
            sys.modules[_ENGINE_MODULE_NAME] = cast("ModuleType", previous_engine)


def _install_runtime(
    *,
    tokenizer: _Tokenizer | None = None,
    model: _Model | None = None,
) -> _Runtime:
    runtime = _Runtime(
        tokenizer if tokenizer is not None else _Tokenizer(),
        model if model is not None else _Model(),
    )
    _ACTIVE_RUNTIME[0] = runtime
    return runtime


def _loaded_engine(
    harness: _Harness,
    *,
    settings: Settings | None = None,
    tokenizer: _Tokenizer | None = None,
    model: _Model | None = None,
) -> tuple[Any, _Runtime]:
    runtime = _install_runtime(tokenizer=tokenizer, model=model)
    selected = settings if settings is not None else Settings()
    return harness.engine_module.Engine.load(selected), runtime


def _generate(
    engine: Any,
    *,
    guided_schema: GuidanceSchemaId | None = None,
    temperature: float = 0.0,
    max_tokens: int = 7,
) -> Any:
    return engine.generate(
        [{"role": "user", "content": "hello"}],
        temperature=temperature,
        max_tokens=max_tokens,
        guided_schema=guided_schema,
    )


def _assert_backend_error(
    harness: _Harness,
    exc: BaseException,
    *,
    status: int,
    error_type: str,
) -> None:
    assert isinstance(exc, harness.engine_module.BackendError)
    assert exc.status == status
    assert exc.error_type == error_type


def _schema_path(path: Path) -> Path:
    return path if path.is_absolute() else _ROOT / path


def _compiled_for(harness: _Harness, schema_id: GuidanceSchemaId) -> _FakeCompiledGrammar:
    index = 0 if schema_id == DATASET_SCHEMA_ID else 1
    compiled = harness.xgrammar.compile_calls[index].result
    assert isinstance(compiled, _FakeCompiledGrammar)
    return compiled


def test_g1_load_compiles_exactly_one_grammar_per_guidance_schema_id(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_path = Path("pins/dataset.json")
    formula_path = Path("pins/formula.json")
    load_calls: list[Path] = []

    def fake_load(path: Path) -> str:
        load_calls.append(path)
        return f"guidance:{path}"

    monkeypatch.setattr(harness.engine_module, "load_guidance_schema", fake_load)
    monkeypatch.setattr(harness.engine_module, "schema_digest", lambda path: f"sha256:{path}")
    _loaded_engine(
        harness,
        settings=Settings(vplot_schema_path=dataset_path, formula_schema_path=formula_path),
    )

    selector_ids = get_args(GuidanceSchemaId.__value__)
    assert selector_ids == ("vplot-0.1", "vplot-formula-0.1")
    assert selector_ids == (DATASET_SCHEMA_ID, FORMULA_SCHEMA_ID)
    assert load_calls == [dataset_path, formula_path]
    assert len(harness.xgrammar.tokenizer_info_calls) == 1
    assert len(harness.xgrammar.compiler_init_calls) == 1
    assert len(harness.xgrammar.compilers) == 1
    assert [call.args for call in harness.xgrammar.compile_calls] == [
        (f"guidance:{dataset_path}",),
        (f"guidance:{formula_path}",),
    ]
    compiled = [call.result for call in harness.xgrammar.compile_calls]
    assert len(compiled) == len(selector_ids) == 2
    assert compiled[0] is not compiled[1]


def test_g2_tokenizer_info_gets_the_loaded_tokenizer_and_the_model_config_vocab_size(
    harness: _Harness,
) -> None:
    tokenizer = _Tokenizer(vocab_size=7)
    model = _Model(vocab_size=31)

    _loaded_engine(harness, tokenizer=tokenizer, model=model)

    assert len(tokenizer) == 7
    assert model.config.vocab_size == 31
    assert len(tokenizer) != model.config.vocab_size
    assert len(harness.xgrammar.tokenizer_info_calls) == 1
    call = harness.xgrammar.tokenizer_info_calls[0]
    info = harness.xgrammar.tokenizer_infos[0]
    assert info.source_tokenizer is tokenizer
    assert "vocab_size" in call.kwargs
    assert call.kwargs["vocab_size"] == model.config.vocab_size
    assert info.vocab_size == model.config.vocab_size


def test_g2b_vocab_width_guard_refuses_a_forged_mismatch_before_native_compile(
    harness: _Harness,
) -> None:
    """Guard-only forgery: installed xgrammar reports the requested width; this fake does not."""
    harness.xgrammar.ignore_requested_vocab_size = True
    tokenizer = _Tokenizer(vocab_size=7)
    model = _Model(vocab_size=31)
    runtime = _install_runtime(tokenizer=tokenizer, model=model)

    with pytest.raises(Exception) as exc_info:
        harness.engine_module.Engine.load(Settings())

    _assert_backend_error(
        harness,
        exc_info.value,
        status=500,
        error_type="guidance_unusable",
    )
    assert harness.xgrammar.tokenizer_infos[0].vocab_size == 7
    assert harness.xgrammar.compiler_init_calls == []
    assert harness.xgrammar.compile_calls == []
    assert runtime.model.to_calls == []


def test_g3_compiled_text_is_the_stripped_guidance_never_the_strict_schema(
    harness: _Harness,
) -> None:
    settings = Settings()
    _loaded_engine(harness, settings=settings)

    paths = [settings.vplot_schema_path, settings.formula_schema_path]
    expected = [load_guidance_schema(_schema_path(path)) for path in paths]
    actual = [cast("str", call.args[0]) for call in harness.xgrammar.compile_calls]
    assert actual == expected
    for path, guidance_text in zip(paths, actual, strict=True):
        strict_text = _schema_path(path).read_text(encoding="utf-8")
        assert '"pattern"' in strict_text
        assert '"pattern"' not in guidance_text
        assert guidance_text != strict_text


def test_g4_compile_json_schema_receives_the_measured_format_bounds(
    harness: _Harness,
) -> None:
    # Hand-stated literals, never read back from the engine's constants. any_order=True was
    # measured to admit an endless run of one property, and unbounded whitespace lets a finished
    # document be padded instead of terminated; neither schema stopped inside 768 tokens under
    # them. Both bounds constrain FORMAT alone.
    _loaded_engine(harness)

    assert len(harness.xgrammar.compile_calls) == 2
    for call in harness.xgrammar.compile_calls:
        assert len(call.args) == 1
        assert isinstance(call.args[0], str)
        assert call.kwargs == {
            "strict_mode": True,
            "any_order": False,
            "max_whitespace_cnt": 8,
        }


@pytest.mark.parametrize(
    "failure_site",
    ["compiler-construction", "dataset-compile", "formula-compile", "base-exception"],
)
def test_g5_compile_failure_refuses_guidance_unusable_with_zero_device_transfers(
    harness: _Harness, failure_site: str
) -> None:
    if failure_site == "compiler-construction":
        harness.xgrammar.compiler_init_error = RuntimeError("synthetic constructor failure")
        expected_compile_calls = 0
    elif failure_site == "dataset-compile":
        harness.xgrammar.compile_fail_at.add(0)
        expected_compile_calls = 1
    elif failure_site == "formula-compile":
        harness.xgrammar.compile_fail_at.add(1)
        expected_compile_calls = 2
    else:
        harness.xgrammar.compiler_init_error = _FatalSetupError("must escape")
        expected_compile_calls = 0

    runtime = _install_runtime()
    if failure_site == "base-exception":
        with pytest.raises(_FatalSetupError):
            harness.engine_module.Engine.load(Settings())
    else:
        with pytest.raises(Exception) as exc_info:
            harness.engine_module.Engine.load(Settings())
        _assert_backend_error(
            harness,
            exc_info.value,
            status=500,
            error_type="guidance_unusable",
        )

    assert len(harness.xgrammar.compile_calls) == expected_compile_calls
    assert runtime.model.to_calls == []


def test_g6_tokenizer_info_failure_refuses_with_the_same_shape_and_zero_transfers(
    harness: _Harness,
) -> None:
    harness.xgrammar.tokenizer_info_error = ValueError("synthetic tokenizer conversion failure")
    failed_runtime = _install_runtime()

    with pytest.raises(Exception) as exc_info:
        harness.engine_module.Engine.load(Settings())

    _assert_backend_error(
        harness,
        exc_info.value,
        status=500,
        error_type="guidance_unusable",
    )
    assert len(harness.xgrammar.tokenizer_info_calls) == 1
    assert harness.xgrammar.compiler_init_calls == []
    assert failed_runtime.model.to_calls == []


def test_g6b_unusable_ids_precede_every_native_guidance_call(harness: _Harness) -> None:
    harness.xgrammar.tokenizer_info_error = ValueError("must remain unreachable")
    invalid_ids = _Model(eos_token_id=str(3))
    runtime = _install_runtime(model=invalid_ids)

    with pytest.raises(Exception) as exc_info:
        harness.engine_module.Engine.load(Settings(structured_output=True))

    _assert_backend_error(
        harness,
        exc_info.value,
        status=500,
        error_type="generation_config_unusable",
    )
    assert harness.xgrammar.tokenizer_info_calls == []
    assert harness.xgrammar.compiler_init_calls == []
    assert harness.xgrammar.compile_calls == []
    assert runtime.model.to_calls == []


def test_g7_structured_output_disabled_performs_zero_grammar_work_at_load(
    harness: _Harness,
) -> None:
    _engine, runtime = _loaded_engine(
        harness,
        settings=Settings(structured_output=False),
    )

    assert harness.xgrammar.tokenizer_info_calls == []
    assert harness.xgrammar.compiler_init_calls == []
    assert harness.xgrammar.compile_calls == []
    assert runtime.model.to_calls == ["cuda"]


def test_g8_schema_sha256_behaviour_is_unchanged_in_both_states(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_path = Path("pins/dataset.json")
    formula_path = Path("pins/formula.json")
    load_calls: list[Path] = []
    digest_calls: list[Path] = []

    def fake_load(path: Path) -> str:
        load_calls.append(path)
        return f"guidance:{path}"

    def fake_digest(path: Path) -> str:
        digest_calls.append(path)
        return f"sha256:{path}"

    monkeypatch.setattr(harness.engine_module, "load_guidance_schema", fake_load)
    monkeypatch.setattr(harness.engine_module, "schema_digest", fake_digest)
    enabled, _runtime = _loaded_engine(
        harness,
        settings=Settings(vplot_schema_path=dataset_path, formula_schema_path=formula_path),
    )

    assert load_calls == [dataset_path, formula_path]
    assert digest_calls == [dataset_path, formula_path]
    assert enabled.schema_sha256(DATASET_SCHEMA_ID) == f"sha256:{dataset_path}"
    assert enabled.schema_sha256(FORMULA_SCHEMA_ID) == f"sha256:{formula_path}"

    disabled, _runtime = _loaded_engine(
        harness,
        settings=Settings(
            structured_output=False,
            vplot_schema_path=Path("missing/dataset.json"),
            formula_schema_path=Path("missing/formula.json"),
        ),
    )
    assert load_calls == [dataset_path, formula_path]
    assert digest_calls == [dataset_path, formula_path]
    assert disabled.schema_sha256(DATASET_SCHEMA_ID) is None
    assert disabled.schema_sha256(FORMULA_SCHEMA_ID) is None


def test_g9_unguided_request_constructs_no_processor_and_passes_no_logits_processor(
    harness: _Harness,
) -> None:
    engine, runtime = _loaded_engine(
        harness,
        settings=Settings(structured_output=True),
    )
    assert len(harness.xgrammar.compile_calls) == 2
    processors_before = len(harness.xgrammar.processors)

    result = _generate(engine, guided_schema=None)

    assert result.text == "{}"
    assert len(harness.xgrammar.processors) == processors_before == 0
    assert len(runtime.model.generate_calls) == 1
    assert "logits_processor" not in runtime.model.generate_calls[0]


@pytest.mark.parametrize("schema_id", [DATASET_SCHEMA_ID, FORMULA_SCHEMA_ID])
@pytest.mark.parametrize("temperature", [0.0, 0.25], ids=["greedy", "sampled"])
def test_g10_guided_request_selects_that_ids_compiled_grammar_by_identity(
    harness: _Harness,
    schema_id: GuidanceSchemaId,
    temperature: float,
) -> None:
    engine, runtime = _loaded_engine(harness)
    expected = _compiled_for(harness, schema_id)

    result = _generate(engine, guided_schema=schema_id, temperature=temperature)

    assert result.text == "{}"
    assert len(harness.xgrammar.processors) == 1
    processor = harness.xgrammar.processors[0]
    assert processor.compiled_grammar is expected
    container = runtime.model.generate_calls[0]["logits_processor"]
    assert isinstance(container, list)
    assert len(container) == 1
    assert container[0] is processor
    assert runtime.model.generate_calls[0]["do_sample"] is (temperature > 0)


def test_g11_two_calls_construct_two_distinct_processor_objects(harness: _Harness) -> None:
    engine, runtime = _loaded_engine(harness)
    expected = _compiled_for(harness, DATASET_SCHEMA_ID)

    _generate(engine, guided_schema=DATASET_SCHEMA_ID)
    _generate(engine, guided_schema=DATASET_SCHEMA_ID)

    assert len(harness.xgrammar.processors) == 2
    first, second = harness.xgrammar.processors
    assert first is not second
    assert first.compiled_grammar is expected
    assert second.compiled_grammar is expected
    assert runtime.model.generate_calls[0]["logits_processor"] == [first]
    assert runtime.model.generate_calls[1]["logits_processor"] == [second]


@pytest.mark.parametrize("schema_id", [DATASET_SCHEMA_ID, FORMULA_SCHEMA_ID])
def test_g12_disabled_guidance_with_a_named_schema_generates_unguided_without_error(
    harness: _Harness, schema_id: GuidanceSchemaId
) -> None:
    engine, runtime = _loaded_engine(
        harness,
        settings=Settings(structured_output=False),
    )

    result = _generate(engine, guided_schema=schema_id)

    assert result.text == "{}"
    assert harness.xgrammar.compile_calls == []
    assert harness.xgrammar.processors == []
    assert len(runtime.model.generate_calls) == 1
    assert "logits_processor" not in runtime.model.generate_calls[0]


def test_g13_caller_matches_the_declared_logits_processor_list_type(
    harness: _Harness,
) -> None:
    """Pin declared API conformance; a plain list works today but is not the declared type."""
    engine, runtime = _loaded_engine(harness)

    _generate(engine, guided_schema=DATASET_SCHEMA_ID)

    processor = harness.xgrammar.processors[0]
    container = runtime.model.generate_calls[0]["logits_processor"]
    assert type(container) is _FakeLogitsProcessorList
    assert container == [processor]


def test_g14_over_cap_prompt_with_a_named_schema_refuses_before_any_grammar_work(
    harness: _Harness,
) -> None:
    tokenizer = _Tokenizer(encoding=_Encoding((1, 2, 3, 4)))
    engine, runtime = _loaded_engine(
        harness,
        settings=Settings(structured_output=True, max_prompt_len=3),
        tokenizer=tokenizer,
    )
    before = (
        len(harness.xgrammar.tokenizer_info_calls),
        len(harness.xgrammar.compiler_init_calls),
        len(harness.xgrammar.compile_calls),
        len(harness.xgrammar.processors),
    )

    with pytest.raises(Exception) as exc_info:
        _generate(engine, guided_schema=DATASET_SCHEMA_ID)

    _assert_backend_error(
        harness,
        exc_info.value,
        status=400,
        error_type="prompt_too_long",
    )
    assert before == (1, 1, 2, 0)
    assert (
        len(harness.xgrammar.tokenizer_info_calls),
        len(harness.xgrammar.compiler_init_calls),
        len(harness.xgrammar.compile_calls),
        len(harness.xgrammar.processors),
    ) == before
    assert runtime.model.generate_calls == []


def test_g15_greedy_pins_survive_beside_an_attached_processor(harness: _Harness) -> None:
    model = _Model(eos_token_id=[9, 3], pad_token_id=77)
    engine, runtime = _loaded_engine(harness, model=model)

    _generate(
        engine,
        guided_schema=FORMULA_SCHEMA_ID,
        temperature=0.0,
        max_tokens=5,
    )

    kwargs = runtime.model.generate_calls[0]
    assert kwargs["do_sample"] is False
    assert kwargs["num_beams"] == 1
    assert kwargs["max_new_tokens"] == 5
    assert kwargs["pad_token_id"] == 77
    assert "eos_token_id" not in kwargs
    assert kwargs["logits_processor"] == [harness.xgrammar.processors[0]]


def test_g16_guided_output_still_enforces_the_response_byte_ceiling(
    harness: _Harness,
) -> None:
    tokenizer = _Tokenizer(decoded="éé")
    engine, runtime = _loaded_engine(
        harness,
        settings=Settings(max_response_bytes=3),
        tokenizer=tokenizer,
    )

    with pytest.raises(Exception) as exc_info:
        _generate(engine, guided_schema=DATASET_SCHEMA_ID)

    _assert_backend_error(
        harness,
        exc_info.value,
        status=500,
        error_type="response_too_large",
    )
    assert len(harness.xgrammar.processors) == 1
    assert len(runtime.model.generate_calls) == 1
    assert len(tokenizer.decode_calls) == 1


def test_g17_engine_module_imports_no_torch() -> None:
    pattern = re.compile(r"(?m)^[ \t]*(?:from[ \t]+torch\b|import[ \t]+[^#\n]*\btorch\b)")
    positive_control = "from torch import Tensor\nimport os, torch as torch_module\n"
    assert len(pattern.findall(positive_control)) == 2

    source = _ENGINE_PATH.read_text(encoding="utf-8")
    assert "class Engine" in source
    assert pattern.findall(source) == []


def test_g18_tokenizer_info_uses_the_models_normalized_stop_token_set(
    harness: _Harness,
) -> None:
    tokenizer = _Tokenizer(eos_token_id=4242)
    model = _Model(
        suffixes=((7, 9),),
        eos_token_id=[9, 3, 9],
        pad_token_id=77,
    )
    engine, runtime = _loaded_engine(harness, tokenizer=tokenizer, model=model)

    assert len(harness.xgrammar.tokenizer_info_calls) == 1
    call = harness.xgrammar.tokenizer_info_calls[0]
    assert "stop_token_ids" in call.kwargs
    stop_token_ids = call.kwargs["stop_token_ids"]
    assert type(stop_token_ids) is list
    assert stop_token_ids == [3, 9]
    assert set(stop_token_ids) == {3, 9}
    assert tokenizer.eos_token_id not in stop_token_ids
    assert harness.xgrammar.tokenizer_infos[0].stop_token_ids == (3, 9)

    result = _generate(engine, guided_schema=DATASET_SCHEMA_ID, max_tokens=3)

    assert result.finish_reason == "stop"
    assert "eos_token_id" not in runtime.model.generate_calls[0]
