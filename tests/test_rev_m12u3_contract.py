# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Red contract checks for M12.3 guidance integration gaps."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_PROBE = r"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


class _Vector:
    def __init__(self, tokens):
        self.tokens = tuple(tokens)
        self.shape = (len(self.tokens),)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.tokens[key]
        raise TypeError(key)


class _Matrix:
    def __init__(self, tokens, *, device=None):
        self.tokens = tuple(tokens)
        self.device = device
        self.shape = (1, len(self.tokens))

    def to(self, device):
        return _Matrix(self.tokens, device=device)

    def __getitem__(self, key):
        if not isinstance(key, tuple) or len(key) != 2:
            raise TypeError(key)
        row, column = key
        if row == 0 and isinstance(column, slice):
            return _Vector(self.tokens[column])
        raise TypeError(key)


class _Encoding(dict):
    def __init__(self, prompt):
        super().__init__(
            input_ids=_Matrix(prompt),
            attention_mask=_Matrix(tuple(1 for _ in prompt)),
        )

    def to(self, device):
        for key, value in tuple(self.items()):
            if isinstance(value, _Matrix):
                self[key] = value.to(device)
        return self


class _Tokenizer:
    def __init__(self, prompt=(11, 12, 13), decoded="{}"):
        self.encoding = _Encoding(prompt)
        self.decoded = decoded

    def __len__(self):
        return 151665

    def apply_chat_template(self, _messages, **_kwargs):
        return self.encoding

    def decode(self, _ids, *, skip_special_tokens):
        assert skip_special_tokens is True
        return self.decoded


class _Model:
    def __init__(
        self,
        *,
        vocab_size=151936,
        eos_token_id=(151645, 151643),
        pad_token_id=151643,
        suffix=(7, 151645),
    ):
        self.config = SimpleNamespace(vocab_size=vocab_size)
        self.generation_config = SimpleNamespace(
            eos_token_id=list(eos_token_id),
            pad_token_id=pad_token_id,
        )
        self.suffix = tuple(suffix)
        self.to_calls = []
        self.generate_calls = []

    def to(self, device):
        self.to_calls.append(device)
        return self

    def generate(self, **kwargs):
        self.generate_calls.append(dict(kwargs))
        input_ids = kwargs["input_ids"]
        assert isinstance(input_ids, _Matrix)
        return _Matrix(input_ids.tokens + self.suffix, device=input_ids.device)


STATE = {
    "token_info_calls": [],
    "compile_calls": [],
    "processors": [],
    "compiler_error": False,
}
TOKENIZER = _Tokenizer()
MODEL = _Model()


class _AutoTokenizer:
    @classmethod
    def from_pretrained(cls, *_args, **_kwargs):
        return TOKENIZER


class _AutoModelForCausalLM:
    @classmethod
    def from_pretrained(cls, *_args, **_kwargs):
        return MODEL


class _TokenizerInfo:
    def __init__(self, vocab_size, stop_token_ids):
        self.vocab_size = vocab_size
        self.stop_token_ids = stop_token_ids

    @classmethod
    def from_huggingface(
        cls,
        tokenizer,
        *,
        vocab_size=None,
        stop_token_ids=None,
    ):
        STATE["token_info_calls"].append(
            (tokenizer, vocab_size, stop_token_ids)
        )
        return cls(vocab_size, stop_token_ids)


class _CompiledGrammar:
    def __init__(self, schema, tokenizer_info):
        self.schema = schema
        self.tokenizer_info = tokenizer_info


class _GrammarCompiler:
    def __init__(
        self,
        tokenizer_info,
        *,
        max_threads=8,
        cache_enabled=True,
        cache_limit_bytes=-1,
    ):
        del max_threads, cache_enabled, cache_limit_bytes
        if STATE["compiler_error"]:
            raise RuntimeError("compiler construction failed")
        self.tokenizer_info = tokenizer_info

    def compile_json_schema(
        self,
        schema,
        *,
        any_whitespace=True,
        indent=None,
        separators=None,
        strict_mode=True,
        max_whitespace_cnt=None,
        any_order=False,
    ):
        del any_whitespace, indent, separators, max_whitespace_cnt
        STATE["compile_calls"].append((schema, strict_mode, any_order))
        return _CompiledGrammar(schema, self.tokenizer_info)


class _LogitsProcessor:
    def __init__(self, compiled_grammar):
        self.compiled_grammar = compiled_grammar
        STATE["processors"].append(self)


transformers = ModuleType("transformers")
transformers.AutoTokenizer = _AutoTokenizer
transformers.AutoModelForCausalLM = _AutoModelForCausalLM
transformers.LogitsProcessorList = list
sys.modules["transformers"] = transformers

xgrammar = ModuleType("xgrammar")
xgrammar.__path__ = []
xgrammar.TokenizerInfo = _TokenizerInfo
xgrammar.GrammarCompiler = _GrammarCompiler
xgrammar.CompiledGrammar = _CompiledGrammar
contrib = ModuleType("xgrammar.contrib")
contrib.__path__ = []
hf = ModuleType("xgrammar.contrib.hf")
hf.LogitsProcessor = _LogitsProcessor
contrib.hf = hf
xgrammar.contrib = contrib
sys.modules["xgrammar"] = xgrammar
sys.modules["xgrammar.contrib"] = contrib
sys.modules["xgrammar.contrib.hf"] = hf

from model_backend.engine import BackendError, Engine
from model_backend.settings import DATASET_SCHEMA_ID, Settings


def _load(*, max_prompt_len=1536):
    return Engine.load(
        Settings(
            structured_output=True,
            device="cuda:7",
            max_prompt_len=max_prompt_len,
        )
    )


scenario = sys.argv[1]
if scenario == "stop-authority":
    engine = _load()
    assert engine is not None
    assert len(STATE["token_info_calls"]) == 1
    tokenizer, vocab_size, stop_token_ids = STATE["token_info_calls"][0]
    assert tokenizer is TOKENIZER
    assert vocab_size == 151936
    assert type(stop_token_ids) is list
    assert set(stop_token_ids) == {151643, 151645}
    assert MODEL.to_calls == ["cuda:7"]
elif scenario == "compiler-failure":
    STATE["compiler_error"] = True
    with pytest.raises(BackendError) as exc_info:
        _load()
    assert exc_info.value.status == 500
    assert exc_info.value.error_type == "guidance_unusable"
    assert len(STATE["token_info_calls"]) == 1
    assert MODEL.to_calls == []
elif scenario == "enabled-generation":
    MODEL.generation_config.eos_token_id = [9, 3]
    MODEL.generation_config.pad_token_id = 77
    MODEL.suffix = (7, 3)
    engine = _load(max_prompt_len=3)
    assert len(STATE["compile_calls"]) == 2

    engine.generate(
        [{"role": "user", "content": "hello"}],
        temperature=0.0,
        max_tokens=5,
        guided_schema=None,
    )
    assert STATE["processors"] == []
    first = MODEL.generate_calls[0]
    assert "logits_processor" not in first

    engine.generate(
        [{"role": "user", "content": "hello"}],
        temperature=0.0,
        max_tokens=5,
        guided_schema=DATASET_SCHEMA_ID,
    )
    assert len(STATE["processors"]) == 1
    second = MODEL.generate_calls[1]
    assert second["do_sample"] is False
    assert second["num_beams"] == 1
    assert second["max_new_tokens"] == 5
    assert second["pad_token_id"] == 77
    assert "eos_token_id" not in second
    assert second["logits_processor"] == [STATE["processors"][0]]

    prior_processors = len(STATE["processors"])
    prior_calls = len(MODEL.generate_calls)
    TOKENIZER.encoding = _Encoding((1, 2, 3, 4))
    with pytest.raises(BackendError) as exc_info:
        engine.generate(
            [{"role": "user", "content": "hello"}],
            temperature=0.0,
            max_tokens=5,
            guided_schema=DATASET_SCHEMA_ID,
        )
    assert exc_info.value.status == 400
    assert exc_info.value.error_type == "prompt_too_long"
    assert len(STATE["processors"]) == prior_processors
    assert len(MODEL.generate_calls) == prior_calls
else:
    raise AssertionError(scenario)
"""


def _run_probe(scenario: str) -> None:
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE, scenario],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_tokenizer_info_uses_model_eos_authority() -> None:
    """B01: xgrammar stop tokens must equal the model generation-config EOS set."""
    _run_probe("stop-authority")


def test_compiler_constructor_failure_is_typed_before_transfer() -> None:
    """B02: every grammar-preparation fault keeps the one typed load surface."""
    _run_probe("compiler-failure")


def test_enabled_generation_pins_null_precedence_and_option_values() -> None:
    """B03/B04: exercise enabled guidance and assert values, not only kwarg shape."""
    _run_probe("enabled-generation")
