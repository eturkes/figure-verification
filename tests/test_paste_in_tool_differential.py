# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Differential: generated tool versus owned uploads and the user's formula target."""

from __future__ import annotations

import inspect
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import cast

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn

from oracle_paste_in_tool import ToolContext, oracle_draw_figure
from oracle_request import Neutral, oracle_formula_target
from paste_in_support import REPO_ROOT, StoredFile, fake_open_webui, invoke_tool, load_tool_module
from verifier.pysrc import DeclaredTarget, Refused, Verdict, Verified, spec
from verifier.pysrc import verify_python_source as core_verify
from webui.paste_in.verdicts import CHART_NOT_PRODUCED, CHART_PRODUCED

_GOOD = b"region,revenue\nUS,12\nEU,9\n"
_CONTENTS = (
    _GOOD,
    b"region,revenue\nUS,12\nUS,9\n",
    b"region,revenue\nUS,bad\nEU,9\n",
    b"region,revenue\r\nUS,12\r\nEU,\xff\r\n",
    b"other,amount\nUS,12\nEU,9\n",
)
_NAMES = ("a.csv", "b.csv", "c.csv")
_MUTANT_ENV = "ORC_M10_MUTANT"
_FORMULA_REQUEST = "y = sin(x), x in [0, 1], n = 3"
_FORMULA_PROGRAM = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.linspace(0, 1, num=3)\n"
    "plt.plot(x, np.sin(x))\n"
    "plt.show()\n"
)


@dataclass(frozen=True, slots=True)
class Case:
    program: str
    user: Mapping[str, object] | None
    metadata: Mapping[str, object] | None
    stored: tuple[StoredFile, ...]


def _program(path: str, *, invalid: bool = False) -> str:
    source = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f"frame = pd.read_csv({path!r})\n"
        'plt.bar(frame["region"], frame["revenue"])\n'
        "plt.show()\n"
    )
    return source + ("plt.subplots(2, 2)\n" if invalid else "")


def _case(path: str, *stored: StoredFile, user_id: str | None = "caller") -> Case:
    metadata: Mapping[str, object] = {
        "files": [{"id": row.file_id, "name": "untrusted-name.csv"} for row in stored]
    }
    return Case(_program(path), {"id": user_id} if user_id is not None else None, metadata, stored)


def _formula_case(message: object, *stored: StoredFile, program: str = _FORMULA_PROGRAM) -> Case:
    return Case(
        program,
        {"id": "caller"},
        {
            "files": [{"id": row.file_id, "name": "untrusted-name.csv"} for row in stored],
            "user_message": {"content": message},
        },
        stored,
    )


_MISMATCH_THEN_MATCH = _case(
    "/mnt/uploads/b.csv",
    StoredFile("f0", "caller", "a.csv", _GOOD),
    StoredFile("f1", "caller", "b.csv", _GOOD),
)
_REFUSED_THEN_VERIFIED = _case(
    "/mnt/uploads/a.csv",
    StoredFile("f0", "caller", "a.csv", _CONTENTS[2]),
    StoredFile("f1", "caller", "a.csv", _GOOD),
)
_FOREIGN = _case("/mnt/uploads/a.csv", StoredFile("f0", "other-user", "a.csv", _GOOD))
_FORMULA_NO_FILE = _formula_case(_FORMULA_REQUEST)
_FORMULA_AFTER_CSV = _formula_case(_FORMULA_REQUEST, StoredFile("f0", "caller", "b.csv", _GOOD))
_FORMULA_NO_CARRIER = _formula_case(None, StoredFile("f0", "caller", "a.csv", _GOOD))
_DATASET_WITH_FORMULA = Case(
    _program("/mnt/uploads/a.csv"),
    {"id": "caller"},
    {
        "files": [{"id": "f0", "name": "untrusted-name.csv"}],
        "user_message": {"content": _FORMULA_REQUEST},
    },
    (StoredFile("f0", "caller", "a.csv", _GOOD),),
)
_MODEL_TEXT_IS_NOT_REQUEST = _formula_case(
    None, program=_FORMULA_PROGRAM + f"# {_FORMULA_REQUEST}\n"
)
_ASSISTANT_TEXT_IS_NOT_REQUEST = Case(
    _FORMULA_PROGRAM,
    {"id": "caller"},
    {
        "files": [],
        "user_message": {"content": None},
        "messages": [{"role": "assistant", "content": _FORMULA_REQUEST}],
    },
    (),
)


@st.composite
def _cases(draw: DrawFn) -> Case:
    count = draw(st.integers(min_value=0, max_value=3))
    stored = tuple(
        StoredFile(
            file_id=f"f{index}",
            user_id=draw(st.sampled_from(("caller", "other-user"))),
            filename=_NAMES[index],
            content=draw(st.sampled_from(_CONTENTS)),
        )
        for index in range(count)
    )
    attachment_ids = (*(row.file_id for row in stored), "missing")
    attachments = [
        {"id": draw(st.sampled_from(attachment_ids)), "name": "untrusted-name.csv"}
        for _ in range(draw(st.integers(min_value=0, max_value=3)))
    ]
    message = draw(
        st.sampled_from((None, _FORMULA_REQUEST, "y = sin(x), from 0 to 1, n = 3", "y = x"))
    )
    metadata: Mapping[str, object] | None = draw(
        st.sampled_from(
            (
                None,
                {"files": attachments},
                {"files": attachments, "user_message": {"content": message}},
                {"files": attachments, "user_message": {"content": [message]}},
                {"files": attachments, "messages": [{"content": _FORMULA_REQUEST}]},
            )
        )
    )
    user: Mapping[str, object] | None = draw(
        st.sampled_from((None, {"id": "caller"}, {"id": "other-user"}, {}))
    )
    path = draw(
        st.sampled_from((*(f"/mnt/uploads/{name}" for name in _NAMES), "/mnt/uploads/missing.csv"))
    )
    program = (
        _FORMULA_PROGRAM if draw(st.booleans()) else _program(path, invalid=draw(st.booleans()))
    )
    return Case(program, user, metadata, stored)


def _current_message(case: Case) -> object:
    if case.metadata is None:
        return None
    item = case.metadata.get("user_message")
    return item.get("content") if isinstance(item, Mapping) else None


def _oracle(case: Case) -> tuple[str, tuple[tuple[str, DeclaredTarget], ...], tuple[str, ...]]:
    calls: list[tuple[str, DeclaredTarget]] = []
    parses: list[str] = []

    def spy(program: str, *, declared_target: DeclaredTarget) -> Verdict:
        calls.append((program, declared_target))
        verdict = core_verify(program, declared_target=declared_target)
        # C3 is independently specified: a formula cannot consume an uploaded CSV. This
        # assertion-shaped oracle treatment makes the OLD core/tool combination red at T10.
        if (
            isinstance(declared_target, spec.DatasetTarget)
            and isinstance(verdict, Verified)
            and isinstance(verdict.spec, spec.FormulaPlot)
        ):
            return Refused("target_mismatch")
        return verdict

    def parse(text: str) -> Neutral | None:
        parses.append(text)
        return oracle_formula_target(text)

    files: object = case.metadata.get("files", []) if case.metadata is not None else []
    assert isinstance(files, list)
    user_id: object = case.user.get("id") if case.user is not None else None
    context = ToolContext(
        user_id=user_id if isinstance(user_id, str) else None,
        attachments=files,
        stored={row.file_id: row for row in case.stored},
        user_message=_current_message(case),
    )
    result = oracle_draw_figure(case.program, context, verify=spy, parse=parse)
    return result, tuple(calls), tuple(parses)


def _production(
    case: Case, module: ModuleType, patch: pytest.MonkeyPatch, root: Path
) -> tuple[str, tuple[tuple[str, DeclaredTarget], ...], tuple[str, ...]]:
    calls: list[tuple[str, DeclaredTarget]] = []
    parses: list[str] = []

    def spy(program: str, *, declared_target: DeclaredTarget) -> Verdict:
        calls.append((program, declared_target))
        return core_verify(program, declared_target=declared_target)

    patch.setattr(module, "verify_python_source", spy)
    original = vars(module).get("formula_target")
    if callable(original):
        original_parser = cast(Callable[..., object], original)

        @wraps(original_parser)
        def parse_spy(text: str, *args: object, **kwargs: object) -> object:
            parses.append(text)
            return original_parser(text, *args, **kwargs)

        patch.setattr(module, "formula_target", parse_spy)
    with fake_open_webui(case.stored, root):
        result = invoke_tool(module, case.program, metadata=case.metadata, user=case.user)
    return result, tuple(calls), tuple(parses)


def _assert_agrees(case: Case, module: ModuleType, patch: pytest.MonkeyPatch, root: Path) -> None:
    assert module.__file__ is not None
    assert Path(module.__file__).resolve() == REPO_ROOT / "webui/paste_in/tool.py"
    assert (
        Path(core_verify.__code__.co_filename).resolve()
        == REPO_ROOT / "src/verifier/pysrc/verify.py"
    )
    expected = _oracle(case)
    observed = _production(case, module, patch, root)
    assert observed[:2] == expected[:2], (
        f"case={case!r}; production={observed!r}; oracle={expected!r}"
    )
    current = _current_message(case)
    if expected[2]:
        assert observed[2] == expected[2], (case, observed, expected)
    elif isinstance(current, str):
        # A parser may run before a dataset verdict wins; the candidate must still come last.
        assert observed[2] in {(), (current,)}, (case, observed, expected)
    else:
        assert observed[2] == (), (case, observed, expected)
    assert observed[0] in {CHART_PRODUCED, CHART_NOT_PRODUCED}


def _tool_mutant(module: ModuleType, patch: pytest.MonkeyPatch, kind: str) -> None:
    """Mutate the public operation in memory, leaving the core verification untouched."""
    original = cast(Callable[..., object], module.Tools.draw_figure)

    @wraps(original)
    async def changed(
        self: object,
        program: str,
        __metadata__: Mapping[str, object] | None = None,
        __user__: Mapping[str, object] | None = None,
    ) -> str:
        metadata = dict(__metadata__ or {})
        files = metadata.get("files", [])
        assert isinstance(files, list)
        if kind == "first":
            metadata["files"] = files[:1]
        elif kind == "last":
            metadata["files"] = files[-1:]
        elif kind == "reverse":
            metadata["files"] = files[::-1]
        user = {"id": "other-user"} if kind == "foreign" else __user__
        outcome = original(self, program, __metadata__=metadata, __user__=user)
        if inspect.isawaitable(outcome):
            outcome = await cast(Awaitable[object], outcome)
        assert isinstance(outcome, str)
        return outcome + program if kind == "echo" else outcome

    patch.setattr(module.Tools, "draw_figure", changed)


@pytest.mark.parametrize(
    "case",
    (
        _MISMATCH_THEN_MATCH,
        _REFUSED_THEN_VERIFIED,
        _FOREIGN,
        _case("/mnt/uploads/a.csv", user_id=None),
    ),
    ids=("mismatch-then-match", "refusal-stops", "foreign", "missing-user"),
)
def test_dataset_only_regression(case: Case, tmp_path: Path) -> None:
    """The old scan's owned-file ordering and terminal refusals remain unchanged."""
    module = load_tool_module()
    with pytest.MonkeyPatch.context() as patch:
        _assert_agrees(case, module, patch, tmp_path)


@example(_MISMATCH_THEN_MATCH)
@example(_REFUSED_THEN_VERIFIED)
@example(_FOREIGN)
@example(Case(_program("/mnt/uploads/a.csv"), None, None, ()))
@example(_DATASET_WITH_FORMULA)
@example(_FORMULA_NO_FILE)
@example(_FORMULA_AFTER_CSV)
@example(_FORMULA_NO_CARRIER)
@example(_MODEL_TEXT_IS_NOT_REQUEST)
@example(_ASSISTANT_TEXT_IS_NOT_REQUEST)
@given(case=_cases())
@settings(max_examples=160, deadline=None)
def test_differential_matches_shipped_tool(case: Case) -> None:
    """Both implementations agree on reply, ordered core calls and exact request-parser calls.

    `ORC_M10_MUTANT=first|last|foreign|echo|reverse` reddens this SAME graded property on the
    public-operation mutant; its default invocation compares the unmutated generated tool.
    """
    module = load_tool_module()
    with (
        TemporaryDirectory(prefix="oracle-m10u4-") as directory,
        pytest.MonkeyPatch.context() as patch,
    ):
        mutant = os.environ.get(_MUTANT_ENV)
        if mutant in {"first", "last", "foreign", "echo", "reverse"}:
            _tool_mutant(module, patch, mutant)
        _assert_agrees(case, module, patch, Path(directory))


def test_differential_red_under_first_verdict_mutant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_tool_module()
    with monkeypatch.context() as patch:
        _tool_mutant(module, patch, "first")
        with pytest.raises(AssertionError, match=r"production=.*oracle="):
            _assert_agrees(_MISMATCH_THEN_MATCH, module, patch, tmp_path)


def test_differential_red_under_last_verdict_mutant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_tool_module()
    with monkeypatch.context() as patch:
        _tool_mutant(module, patch, "last")
        with pytest.raises(AssertionError, match=r"production=.*oracle="):
            _assert_agrees(_REFUSED_THEN_VERIFIED, module, patch, tmp_path)


@pytest.mark.parametrize(
    "case",
    (
        _FORMULA_NO_FILE,
        _FORMULA_AFTER_CSV,
        _FORMULA_NO_CARRIER,
        _DATASET_WITH_FORMULA,
        _MODEL_TEXT_IS_NOT_REQUEST,
        _ASSISTANT_TEXT_IS_NOT_REQUEST,
    ),
    ids=(
        "formula-no-file",
        "formula-after-csv",
        "formula-csv-no-carrier",
        "dataset-before-formula",
        "model-text-not-request",
        "assistant-text-not-request",
    ),
)
def test_differential_formula_candidate(case: Case, tmp_path: Path) -> None:
    """T7-T10: formula after CSV, request-only target; rejected when no carrier."""
    module = load_tool_module()
    with pytest.MonkeyPatch.context() as patch:
        _assert_agrees(case, module, patch, tmp_path)
