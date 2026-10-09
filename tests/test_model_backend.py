# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Contract net for the hardware-gated transformers model backend.

The root gate has no transformers and no torch. Install one fake ``transformers`` module before
the engine import; opaque Python stand-ins cover only the tensor and BatchEncoding protocols the
engine uses. Special-token metadata rides the MODEL's generation_config, matching the engine's own
authority, so the tokenizer stand-in carries none.
"""

from __future__ import annotations

import re
import sys
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, cast

import pytest
from litestar.testing import TestClient

from model_backend.models import ChatMessage, ModelCard
from model_backend.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_PATH = _ROOT / "model_backend" / "engine.py"
_SMOKE_PATH = _ROOT / "model_backend" / "smoke.py"
# The package's probe runs only on the isolated .venv-model runtime and imports torch, which the
# served app never carries.
_PROBE_PATHS = (_SMOKE_PATH,)
_PROBE_ONLY_IMPORTS = re.compile(r"^\s*(?:import|from)\s+torch\b", re.MULTILINE)


class _Vector:
    def __init__(self, tokens: tuple[int, ...]) -> None:
        self.tokens = tokens
        self.shape = (len(tokens),)

    def __getitem__(self, key: object) -> Any:
        # Integer indexing ONLY, matching a real 1-D tensor. Admitting the 2-D `(0, -1)` spelling
        # here would let the terminal read regress to the form R02 reversed: green against a
        # tolerant fake, IndexError against every real completion.
        if isinstance(key, int):
            return self.tokens[key]
        raise TypeError(key)


class _Matrix:
    def __init__(self, tokens: tuple[int, ...], *, device: str | None = None) -> None:
        self.tokens = tokens
        self.device = device
        self.shape = (1, len(tokens))

    def to(self, device: str) -> _Matrix:
        return _Matrix(self.tokens, device=device)

    def __getitem__(self, key: object) -> Any:
        if not isinstance(key, tuple) or len(key) != 2:
            raise TypeError(key)
        row, column = key
        if isinstance(column, slice):
            sliced = self.tokens[column]
            if row == 0:
                return _Vector(sliced)
            if row == slice(None):
                return _Matrix(sliced, device=self.device)
        if row == 0 and isinstance(column, int):
            return self.tokens[column]
        raise TypeError(key)


def _tensor_tokens(value: object) -> tuple[int, ...]:
    assert isinstance(value, (_Matrix, _Vector))
    return value.tokens


class _Encoding(dict[str, object]):
    def __init__(
        self,
        prompt_tokens: tuple[int, ...] = (11, 12, 13),
        *,
        include_input_ids: bool = True,
        include_attention_mask: bool = True,
        extras: dict[str, object] | None = None,
    ) -> None:
        super().__init__()
        if include_input_ids:
            self["input_ids"] = _Matrix(prompt_tokens)
        if include_attention_mask:
            self["attention_mask"] = _Matrix(tuple(1 for _ in prompt_tokens))
        if extras is not None:
            self.update(extras)
        self.to_calls: list[str] = []
        self.moved_input_ids: object | None = None

    def to(self, device: str) -> _Encoding:
        self.to_calls.append(device)
        for key, value in tuple(self.items()):
            if isinstance(value, _Matrix):
                self[key] = value.to(device)
        self.moved_input_ids = self.get("input_ids")
        return self


class _Tokenizer:
    """Carries its OWN special-token ids, deliberately disagreeing with the model's.

    The engine must never read them. Holding them here makes that a measured claim: a mutant
    reading this side classifies differently instead of dying on a missing attribute.
    """

    def __init__(
        self,
        *,
        encoding: _Encoding | None = None,
        decoded: str | tuple[str, ...] = "{}",
        eos_token_id: object = 4242,
        pad_token_id: object = 4243,
    ) -> None:
        self.encoding = encoding if encoding is not None else _Encoding()
        self.decoded = (decoded,) if isinstance(decoded, str) else decoded
        self.eos_token_id = eos_token_id
        self.pad_token_id = pad_token_id
        self.apply_calls: list[tuple[list[dict[str, str]], dict[str, object]]] = []
        self.decode_calls: list[tuple[object, bool]] = []
        self._decode_lock = threading.Lock()

    def apply_chat_template(self, messages: list[dict[str, str]], **kwargs: object) -> _Encoding:
        self.apply_calls.append((messages, dict(kwargs)))
        return self.encoding

    def decode(self, ids: object, *, skip_special_tokens: bool) -> str:
        with self._decode_lock:
            call_index = len(self.decode_calls)
            self.decode_calls.append((ids, skip_special_tokens))
            return self.decoded[min(call_index, len(self.decoded) - 1)]


class _GenerationConfig:
    """The model's own special-token metadata: the engine's sole authority for both ids."""

    def __init__(self, eos_token_id: object, pad_token_id: object) -> None:
        self.eos_token_id = eos_token_id
        self.pad_token_id = pad_token_id


class _ModelConfig:
    """The model's declared vocabulary width: the engine's sole authority for the mask width.

    Deliberately DISAGREES with the tokenizer's length, exactly as the pinned snapshot does.
    Reading the tokenizer's width instead is silent and leaves the excess logits unmasked.
    """

    def __init__(self, vocab_size: object = 151936) -> None:
        self.vocab_size = vocab_size


class _Model:
    def __init__(
        self,
        *,
        suffixes: tuple[tuple[int, ...], ...] = ((7, 2),),
        eos_token_id: object = 2,
        pad_token_id: object = None,
        generate_hook: Callable[[int], None] | None = None,
    ) -> None:
        self.suffixes = suffixes
        self.generation_config = _GenerationConfig(eos_token_id, pad_token_id)
        self.config = _ModelConfig()
        self.generate_hook = generate_hook
        self.to_calls: list[str] = []
        self.generate_calls: list[dict[str, object]] = []
        self._generate_lock = threading.Lock()

    def to(self, device: str) -> _Model:
        self.to_calls.append(device)
        return self

    def generate(self, **kwargs: object) -> _Matrix:
        with self._generate_lock:
            call_index = len(self.generate_calls)
            self.generate_calls.append(dict(kwargs))
        if self.generate_hook is not None:
            self.generate_hook(call_index)
        input_ids = kwargs["input_ids"]
        assert isinstance(input_ids, _Matrix)
        suffix = self.suffixes[min(call_index, len(self.suffixes) - 1)]
        return _Matrix(input_ids.tokens + suffix, device=input_ids.device)


class _FakeAutoTokenizer:
    @classmethod
    def from_pretrained(cls, *_args: object, **_kwargs: object) -> _Tokenizer:
        pytest.fail("test must install a tokenizer loader")


class _FakeAutoModelForCausalLM:
    @classmethod
    def from_pretrained(cls, *_args: object, **_kwargs: object) -> _Model:
        pytest.fail("test must install a model loader")


# engine.py imports transformers alone; importing the real one would pull torch into a test
# environment that deliberately has neither.
_TRANSFORMERS = ModuleType("transformers")
_TRANSFORMERS.AutoTokenizer = _FakeAutoTokenizer  # type: ignore[attr-defined]
_TRANSFORMERS.AutoModelForCausalLM = _FakeAutoModelForCausalLM  # type: ignore[attr-defined]
sys.modules["transformers"] = _TRANSFORMERS


from model_backend.app import create_app  # noqa: E402
from model_backend.engine import BackendError, Engine, GenResult  # noqa: E402


class _Runtime:
    def __init__(self, tokenizer: _Tokenizer, model: _Model) -> None:
        self.tokenizer = tokenizer
        self.model = model
        self.tokenizer_load_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.model_load_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tokenizer: _Tokenizer | None = None,
    model: _Model | None = None,
) -> _Runtime:
    runtime = _Runtime(
        tokenizer if tokenizer is not None else _Tokenizer(),
        model if model is not None else _Model(),
    )

    def load_tokenizer(
        _cls: type[_FakeAutoTokenizer], /, *args: object, **kwargs: object
    ) -> _Tokenizer:
        runtime.tokenizer_load_calls.append((args, dict(kwargs)))
        return runtime.tokenizer

    def load_model(
        _cls: type[_FakeAutoModelForCausalLM], /, *args: object, **kwargs: object
    ) -> _Model:
        runtime.model_load_calls.append((args, dict(kwargs)))
        return runtime.model

    monkeypatch.setattr(_FakeAutoTokenizer, "from_pretrained", classmethod(load_tokenizer))
    monkeypatch.setattr(_FakeAutoModelForCausalLM, "from_pretrained", classmethod(load_model))
    return runtime


def _loaded_engine(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: Settings | None = None,
    tokenizer: _Tokenizer | None = None,
    model: _Model | None = None,
) -> tuple[Any, _Runtime]:
    runtime = _patch_runtime(monkeypatch, tokenizer=tokenizer, model=model)
    selected = settings if settings is not None else Settings()
    return Engine.load(selected), runtime


def _generate(engine: Any, *, temperature: float = 0.0, max_tokens: int = 7) -> Any:
    return engine.generate(
        [{"role": "user", "content": "hello"}],
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _assert_backend_error(
    exc: BaseException, *, status: int, error_type: str, message: str | None = None
) -> None:
    assert isinstance(exc, BackendError)
    assert exc.status == status
    assert exc.error_type == error_type
    if message is not None:
        assert str(exc) == message


def test_p01_over_cap_prompt_raises_exact_backend_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _Tokenizer(encoding=_Encoding((1, 2, 3, 4)))
    engine, _runtime = _loaded_engine(
        monkeypatch,
        settings=Settings(max_prompt_len=3),
        tokenizer=tokenizer,
    )

    with pytest.raises(BackendError) as exc_info:
        _generate(engine)

    _assert_backend_error(
        exc_info.value,
        status=400,
        error_type="prompt_too_long",
        message="tokenized prompt exceeds the 3-token ceiling",
    )


def test_p02_default_prompt_cap_emits_canonical_http_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _Tokenizer(encoding=_Encoding(tuple(range(1537))))
    runtime = _patch_runtime(monkeypatch, tokenizer=tokenizer)

    with TestClient(app=create_app(Settings())) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert response.content == (
        b'{"error":{"message":"tokenized prompt exceeds the 1536-token ceiling",'
        b'"type":"prompt_too_long"}}'
    )
    assert runtime.model.generate_calls == []


def test_p03_over_cap_prompt_never_calls_model_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def generation_bomb(_call_index: int) -> None:
        pytest.fail("model.generate must remain unreachable after prompt refusal")

    model = _Model(generate_hook=generation_bomb)
    engine, runtime = _loaded_engine(
        monkeypatch,
        settings=Settings(max_prompt_len=2),
        tokenizer=_Tokenizer(encoding=_Encoding((1, 2, 3))),
        model=model,
    )

    with pytest.raises(BackendError):
        _generate(engine)

    assert runtime.model.generate_calls == []


def test_p04_generate_receives_the_post_move_input_object_by_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoding = _Encoding((41, 42, 43))
    engine, runtime = _loaded_engine(monkeypatch, tokenizer=_Tokenizer(encoding=encoding))

    _generate(engine)

    assert encoding.moved_input_ids is not None
    assert runtime.model.generate_calls[0]["input_ids"] is encoding.moved_input_ids


def test_p05_chat_template_call_is_single_and_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _Tokenizer()
    engine, _runtime = _loaded_engine(monkeypatch, tokenizer=tokenizer)
    messages = [{"role": "user", "content": "hello"}]

    engine.generate(
        messages,
        temperature=0.0,
        max_tokens=7,
    )

    assert tokenizer.apply_calls == [
        (
            messages,
            {
                "tokenize": True,
                "add_generation_prompt": True,
                "return_tensors": "pt",
                "return_dict": True,
            },
        )
    ]


def test_p06_encoding_move_uses_the_configured_nondefault_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoding = _Encoding()
    settings = Settings(device="cuda:7")
    engine, _runtime = _loaded_engine(
        monkeypatch,
        settings=settings,
        tokenizer=_Tokenizer(encoding=encoding),
    )

    _generate(engine)

    assert encoding.to_calls == ["cuda:7"]


def test_p07_eos_at_the_one_token_cap_finishes_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _runtime = _loaded_engine(
        monkeypatch,
        tokenizer=_Tokenizer(decoded=""),
        model=_Model(suffixes=((2,),), eos_token_id=[9, 2]),
    )

    result = _generate(engine, max_tokens=1)

    assert result.finish_reason == "stop"
    assert result.completion_tokens == 1
    assert result.text == ""


def test_p08_terminal_eos_under_cap_finishes_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _runtime = _loaded_engine(
        monkeypatch,
        model=_Model(suffixes=((8, 2),), eos_token_id=[9, 2]),
    )

    result = _generate(engine, max_tokens=3)

    assert result.finish_reason == "stop"
    assert result.completion_tokens == 2


def test_p09_nonterminal_eos_at_cap_finishes_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _runtime = _loaded_engine(
        monkeypatch,
        model=_Model(suffixes=((2, 8),), eos_token_id=[9, 2]),
    )

    result = _generate(engine, max_tokens=2)

    assert result.finish_reason == "length"
    assert result.completion_tokens == 2


def test_p10_zero_length_suffix_finishes_stop_without_terminal_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No-EOS-under-cap is unreachable with the pinned production config. The fake keeps D7 total
    # and makes the zero-length terminal-index guard observable.
    engine, _runtime = _loaded_engine(
        monkeypatch,
        tokenizer=_Tokenizer(decoded=""),
        model=_Model(suffixes=((),), eos_token_id=[9, 2]),
    )

    result = _generate(engine, max_tokens=1)

    assert result.finish_reason == "stop"
    assert result.completion_tokens == 0
    assert result.text == ""


def test_p10b_nonterminal_suffix_under_cap_finishes_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fourth D7 cell, kept distinct from the empty-suffix one: tokens were generated, none of
    # them terminal-EOS, and the cap stayed untouched. Unreachable in production (no custom
    # stopping criteria are installed) and reachable through the fake, so the 2x2 stays total.
    engine, _runtime = _loaded_engine(
        monkeypatch,
        model=_Model(suffixes=((2, 8),), eos_token_id=[9, 2]),
    )

    result = _generate(engine, max_tokens=5)

    assert result.finish_reason == "stop"
    assert result.completion_tokens == 2


def test_p11_usage_counts_are_hand_stated_from_prompt_and_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _runtime = _loaded_engine(
        monkeypatch,
        tokenizer=_Tokenizer(encoding=_Encoding((21, 22, 23, 24))),
        model=_Model(suffixes=((8, 2),), eos_token_id=2),
    )

    result = _generate(engine, max_tokens=7)

    assert result.prompt_tokens == 4
    assert result.completion_tokens == 2


def test_p11b_decode_reads_the_suffix_once_with_special_tokens_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fake returns its canned reply whichever ids it is handed, so the RECORDED call is the
    # only witness here. Without it, skip_special_tokens=False survives the whole suite while
    # leaking <|im_end|> into the text the verifier parses.
    engine, runtime = _loaded_engine(
        monkeypatch,
        tokenizer=_Tokenizer(encoding=_Encoding((21, 22, 23, 24))),
        model=_Model(suffixes=((8, 2),), eos_token_id=2),
    )

    _generate(engine, max_tokens=7)

    assert len(runtime.tokenizer.decode_calls) == 1
    decoded_ids, skip_special_tokens = runtime.tokenizer.decode_calls[0]
    assert _tensor_tokens(decoded_ids) == (8, 2)
    assert skip_special_tokens is True


class _BlockingText(str):
    entered: threading.Event
    release: threading.Event

    def __new__(
        cls, value: str, entered: threading.Event, release: threading.Event
    ) -> _BlockingText:
        instance = super().__new__(cls, value)
        instance.entered = entered
        instance.release = release
        return instance

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        self.entered.set()
        assert self.release.wait(2.0)
        return super().encode(encoding, errors)


def test_p12_response_ceiling_is_exact_and_checked_after_lock_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encode_entered = threading.Event()
    release_encode = threading.Event()
    second_generated = threading.Event()

    def note_generation(call_index: int) -> None:
        if call_index == 1:
            second_generated.set()

    tokenizer = _Tokenizer(decoded=(_BlockingText("éé", encode_entered, release_encode), "ok"))
    engine, _runtime = _loaded_engine(
        monkeypatch,
        settings=Settings(max_response_bytes=3),
        tokenizer=tokenizer,
        model=_Model(suffixes=((7, 2), (7, 2)), generate_hook=note_generation),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_generate, engine)
        assert encode_entered.wait(1.0)
        second = executor.submit(_generate, engine)
        try:
            assert second_generated.wait(1.0)
        finally:
            release_encode.set()
        with pytest.raises(BackendError) as exc_info:
            first.result()
        second_result = second.result()

    _assert_backend_error(
        exc_info.value,
        status=500,
        error_type="response_too_large",
        message="generated response exceeded the 3-byte ceiling",
    )
    assert second_result.text == "ok"


def test_p16_pretrained_calls_and_model_placement_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        model_dir=Path("snapshots/model"),
        device="cuda:9",
    )
    _engine, runtime = _loaded_engine(monkeypatch, settings=settings)

    assert runtime.tokenizer_load_calls == [(("snapshots/model",), {"local_files_only": True})]
    assert runtime.model_load_calls == [
        (("snapshots/model",), {"dtype": "float16", "local_files_only": True})
    ]
    assert runtime.model.to_calls == ["cuda:9"]


@pytest.mark.parametrize(
    ("raw_eos", "terminal", "finish_reason"),
    [
        (3, 3, "stop"),
        ([3], 3, "stop"),
        (0, 0, "stop"),
        ((5, 3), 3, "stop"),
        ({5, 3}, 5, "stop"),
        (frozenset({5, 3}), 4, "length"),
    ],
    ids=["scalar", "list", "zero", "tuple", "set", "frozenset-nonmember"],
)
def test_p17_eos_admits_the_closed_container_domain(
    monkeypatch: pytest.MonkeyPatch, raw_eos: object, terminal: int, finish_reason: str
) -> None:
    # The admitted set is observable only through classification: no eos override reaches
    # generate, because the model's own config already governs the stopping criterion. The
    # frozenset row is the disagreement witness — its terminal token is outside the set.
    engine, runtime = _loaded_engine(
        monkeypatch,
        model=_Model(suffixes=((terminal,),), eos_token_id=raw_eos),
    )

    result = _generate(engine, max_tokens=1)

    assert result.finish_reason == finish_reason
    assert "eos_token_id" not in runtime.model.generate_calls[0]


@pytest.mark.parametrize(
    "raw_eos",
    [object(), [], ["3"], "3", b"3", (n for n in (3,)), [3.0], {"3": 3}],
    ids=["object", "empty", "text-member", "text", "bytes", "generator", "float-member", "map"],
)
def test_p17_eos_refuses_every_inadmissible_shape(
    monkeypatch: pytest.MonkeyPatch, raw_eos: object
) -> None:
    # str, bytes, a generator and a mapping are all iterable and none carries token ids, so the
    # container domain is a closed list/tuple/set/frozenset rather than "iterable of int". No
    # int() coercion anywhere, which is what keeps the float member out.
    runtime = _patch_runtime(monkeypatch, model=_Model(eos_token_id=raw_eos))

    with pytest.raises(BackendError) as exc_info:
        Engine.load(Settings())

    _assert_backend_error(exc_info.value, status=500, error_type="generation_config_unusable")
    assert runtime.model.to_calls == []


def test_p17b_list_eos_always_yields_scalar_pad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The latent defect this pins: pad_token_id is scalar-only upstream, so forwarding the eos
    # set as the pad raises inside generate for every model declaring more than one eos id.
    engine, runtime = _loaded_engine(
        monkeypatch,
        model=_Model(eos_token_id=[9, 3], pad_token_id=None),
    )

    _generate(engine)

    kwargs = runtime.model.generate_calls[0]
    assert kwargs["pad_token_id"] == 3
    assert type(kwargs["pad_token_id"]) is int


def test_p18_declared_pad_wins_even_outside_eos_else_minimum_eos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected: list[int] = []
    for raw_pad in (77, None):
        engine, runtime = _loaded_engine(
            monkeypatch,
            model=_Model(eos_token_id=[9, 3], pad_token_id=raw_pad),
        )
        _generate(engine)
        selected.append(cast("int", runtime.model.generate_calls[0]["pad_token_id"]))

    assert selected == [77, 3]


def test_p18b_token_id_authority_is_the_model_config_not_the_tokenizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The tokenizer names a NARROWER eos set and a different pad — the split the pinned snapshot
    # actually ships. Under tokenizer authority the terminal 3 falls outside the set, so the cap
    # reclassifies the reply as "length", and the forwarded pad becomes 11. Both assertions flip
    # the moment the authority moves, which is what makes this a disagreement witness rather than
    # a value that agrees by accident.
    engine, runtime = _loaded_engine(
        monkeypatch,
        tokenizer=_Tokenizer(eos_token_id=[9], pad_token_id=11),
        model=_Model(suffixes=((8, 3),), eos_token_id=[9, 3], pad_token_id=5),
    )

    result = _generate(engine, max_tokens=2)

    assert result.finish_reason == "stop"
    assert runtime.model.generate_calls[0]["pad_token_id"] == 5


def test_p19_generation_kwargs_are_exact_for_greedy_and_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for temperature in (0.0, 0.25):
        engine, runtime = _loaded_engine(
            monkeypatch,
            model=_Model(eos_token_id=[9, 3], pad_token_id=77),
        )
        _generate(engine, temperature=temperature, max_tokens=5)
        kwargs = runtime.model.generate_calls[0]
        # No eos override: the model's generation config already carries the authoritative set,
        # and forwarding a derived one could only narrow it.
        expected: dict[str, object] = {
            "input_ids": runtime.tokenizer.encoding.moved_input_ids,
            "attention_mask": runtime.tokenizer.encoding["attention_mask"],
            "do_sample": temperature > 0,
            "num_beams": 1,
            "max_new_tokens": 5,
            "pad_token_id": 77,
        }
        if temperature > 0:
            expected["temperature"] = 0.25
        assert kwargs == expected


def test_p20_concurrent_generation_never_overlaps_model_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    state_lock = threading.Lock()
    active = 0

    def overlap_bomb(call_index: int) -> None:
        nonlocal active
        with state_lock:
            active += 1
            assert active == 1, "model.generate calls overlapped"
        if call_index == 0:
            first_entered.set()
            assert release_first.wait(2.0)
        else:
            second_entered.set()
        with state_lock:
            active -= 1

    engine, _runtime = _loaded_engine(
        monkeypatch,
        model=_Model(suffixes=((7, 2), (7, 2)), generate_hook=overlap_bomb),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_generate, engine)
        assert first_entered.wait(1.0)
        second = executor.submit(_generate, engine)
        try:
            assert not second_entered.wait(0.2)
        finally:
            release_first.set()
        first.result()
        second.result()


_RETIRED_ENGINE_TERMS = r"\b(?:openvino|ov_genai|npu)\b"
_RETIRED_PACKAGE_TERMS = r"\b(?:openvino|npu|int4|intel-accel)\b"


def test_p21_engine_source_has_no_retired_runtime_terms() -> None:
    text = _ENGINE_PATH.read_text(encoding="utf-8").casefold()
    assert "class engine" in text  # positive control: the intended source was read
    # Word-bounded on purpose: a bare substring scan matches "npu" inside every "input_ids".
    assert re.findall(_RETIRED_ENGINE_TERMS, "an ov_genai NPU import".casefold()) == [
        "ov_genai",
        "npu",
    ]
    assert re.findall(_RETIRED_ENGINE_TERMS, text) == []


def test_p22_model_cards_are_backend_neutral_in_struct_and_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ModelCard(id="model", created=0).owned_by == "local"
    _patch_runtime(monkeypatch)
    with TestClient(app=create_app(Settings())) as client:
        response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["owned_by"] == "local"


def test_p23_package_docstrings_have_no_retired_runtime_terms() -> None:
    paths = (_ROOT / "model_backend" / "__init__.py", _ROOT / "model_backend" / "__main__.py")
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths).casefold()
    assert "model_backend" in text  # positive control: both package files were readable
    assert re.findall(_RETIRED_PACKAGE_TERMS, "OpenVINO INT4 NPU intel-accel".casefold()) == [
        "openvino",
        "int4",
        "npu",
        "intel-accel",
    ]
    assert re.findall(_RETIRED_PACKAGE_TERMS, text) == []


def test_p24_smoke_probe_exists_and_cannot_be_pytest_collected() -> None:
    assert _SMOKE_PATH.is_file()
    assert not _SMOKE_PATH.name.startswith("test_")
    # Bare mypy includes model_backend/, so the repository gate supplies the import/type half.


def test_p26_bool_eos_refuses_while_bool_pad_uses_eos_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # bool is an int subclass, so a config reporting False would otherwise bind vocabulary
    # token 0 as end-of-sequence. EOS refuses and PAD degrades: the asymmetry is deliberate.
    for raw_eos in (False, [False]):
        runtime = _patch_runtime(monkeypatch, model=_Model(eos_token_id=raw_eos))
        with pytest.raises(BackendError) as exc_info:
            Engine.load(Settings())
        _assert_backend_error(exc_info.value, status=500, error_type="generation_config_unusable")
        assert runtime.model.to_calls == []

    engine, runtime = _loaded_engine(
        monkeypatch,
        model=_Model(eos_token_id=[9, 3], pad_token_id=False),
    )
    _generate(engine)
    assert runtime.model.generate_calls[0]["pad_token_id"] == 3


def test_p27_negative_eos_refuses_while_negative_pad_uses_distinct_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for raw_eos in (-1, [3, -1]):
        runtime = _patch_runtime(monkeypatch, model=_Model(eos_token_id=raw_eos))
        with pytest.raises(BackendError) as exc_info:
            Engine.load(Settings())
        _assert_backend_error(exc_info.value, status=500, error_type="generation_config_unusable")
        assert runtime.model.to_calls == []

    # Disagreement witness: the declared pad and the fallback are distinct literals, so an
    # implementation forwarding the declared value could not pass.
    engine, runtime = _loaded_engine(
        monkeypatch,
        model=_Model(eos_token_id=[9, 3], pad_token_id=-7),
    )
    _generate(engine)
    assert runtime.model.generate_calls[0]["pad_token_id"] == 3


def test_p29_admission_forwards_maskless_mapping_but_requires_input_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    position_ids = object()
    maskless = _Encoding(
        (11, 12),
        include_attention_mask=False,
        extras={"position_ids": position_ids},
    )
    engine, runtime = _loaded_engine(
        monkeypatch,
        tokenizer=_Tokenizer(encoding=maskless),
    )
    _generate(engine)
    kwargs = runtime.model.generate_calls[0]
    assert "attention_mask" not in kwargs
    assert kwargs["input_ids"] is maskless.moved_input_ids
    assert kwargs["position_ids"] is position_ids

    missing_input = _Encoding(include_input_ids=False)
    engine, runtime = _loaded_engine(
        monkeypatch,
        tokenizer=_Tokenizer(encoding=missing_input),
    )
    with pytest.raises(BackendError) as exc_info:
        _generate(engine)
    _assert_backend_error(exc_info.value, status=500, error_type="tokenizer_unusable")
    assert runtime.model.generate_calls == []


def test_p30_load_order_costs_nothing_downstream_of_each_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A call-counting bomb rather than an outcome assertion: unusable id metadata is decidable
    # from metadata, so it costs zero device transfers.
    id_runtime = _patch_runtime(monkeypatch, model=_Model(eos_token_id=str(3)))
    with pytest.raises(BackendError) as exc_info:
        Engine.load(Settings())

    _assert_backend_error(exc_info.value, status=500, error_type="generation_config_unusable")
    assert len(id_runtime.tokenizer_load_calls) == 1
    assert len(id_runtime.model_load_calls) == 1
    assert id_runtime.model.to_calls == []


def test_p31_probe_only_imports_never_reach_a_served_module() -> None:
    # Positive control first: the pattern finds the real import inside each probe, so the empty
    # results below are a measurement rather than a broken regex.
    for path in _PROBE_PATHS:
        assert path.is_file()
        assert not path.name.startswith("test_")
        assert _PROBE_ONLY_IMPORTS.findall(path.read_text(encoding="utf-8")) != []

    # Hand-stated closed set: a new module here must be classified as probe or served before it
    # inherits this pin, rather than joining a derived set that would cover it silently.
    served = {path.name for path in (_ROOT / "model_backend").glob("*.py")} - {
        path.name for path in _PROBE_PATHS
    }
    assert served == {
        "__init__.py",
        "__main__.py",
        "app.py",
        "engine.py",
        "adapter.py",
        "models.py",
        "settings.py",
        "snapshot.py",
    }
    for name in sorted(served):
        text = (_ROOT / "model_backend" / name).read_text(encoding="utf-8")
        assert _PROBE_ONLY_IMPORTS.findall(text) == [], name


class _AppEngine:
    def __init__(self) -> None:
        self.generate_calls = 0

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> GenResult:
        assert messages == [{"role": "user", "content": "hello"}]
        assert temperature == 0.0
        assert max_tokens >= 1
        self.generate_calls += 1
        return GenResult(text="{}", prompt_tokens=1, completion_tokens=1, finish_reason="stop")


class _RejectingAppEngine:
    def generate(
        self,
        _messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
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


_MESSAGES_FIELD = b'"messages":[{"role":"user","content":"hello"}]'


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
