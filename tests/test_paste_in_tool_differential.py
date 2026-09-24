# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Differential: the generated tool against an independent authenticated-upload scan."""

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

from oracle_paste_in_tool import oracle_draw_figure
from paste_in_support import REPO_ROOT, StoredFile, fake_open_webui, invoke_tool, load_tool_module
from verifier.pysrc import DatasetTarget, Verdict
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
    metadata: Mapping[str, object] | None = draw(st.sampled_from((None, {"files": attachments})))
    user: Mapping[str, object] | None = draw(
        st.sampled_from((None, {"id": "caller"}, {"id": "other-user"}, {}))
    )
    path = draw(
        st.sampled_from((*(f"/mnt/uploads/{name}" for name in _NAMES), "/mnt/uploads/missing.csv"))
    )
    return Case(_program(path, invalid=draw(st.booleans())), user, metadata, stored)


def _oracle(case: Case) -> tuple[str, tuple[tuple[str, DatasetTarget], ...]]:
    calls: list[tuple[str, DatasetTarget]] = []

    def spy(program: str, *, declared_target: DatasetTarget) -> Verdict:
        calls.append((program, declared_target))
        return core_verify(program, declared_target=declared_target)

    files: object = case.metadata.get("files", []) if case.metadata is not None else []
    assert isinstance(files, list)
    user_id: object = case.user.get("id") if case.user is not None else None
    result = oracle_draw_figure(
        case.program,
        user_id=user_id if isinstance(user_id, str) else None,
        attachments=files,
        stored={row.file_id: row for row in case.stored},
        verify=spy,
    )
    return result, tuple(calls)


def _production(
    case: Case, module: ModuleType, patch: pytest.MonkeyPatch, root: Path
) -> tuple[str, tuple[tuple[str, DatasetTarget], ...]]:
    calls: list[tuple[str, DatasetTarget]] = []

    def spy(program: str, *, declared_target: DatasetTarget) -> Verdict:
        calls.append((program, declared_target))
        return core_verify(program, declared_target=declared_target)

    patch.setattr(module, "verify_python_source", spy)
    with fake_open_webui(case.stored, root):
        result = invoke_tool(module, case.program, metadata=case.metadata, user=case.user)
    return result, tuple(calls)


def _assert_agrees(case: Case, module: ModuleType, patch: pytest.MonkeyPatch, root: Path) -> None:
    assert module.__file__ is not None
    assert Path(module.__file__).resolve() == REPO_ROOT / "webui/paste_in/tool.py"
    assert (
        Path(core_verify.__code__.co_filename).resolve()
        == REPO_ROOT / "src/verifier/pysrc/verify.py"
    )
    expected = _oracle(case)
    observed = _production(case, module, patch, root)
    assert observed == expected, f"case={case!r}; production={observed!r}; oracle={expected!r}"
    assert observed[0] in {CHART_PRODUCED, CHART_NOT_PRODUCED}


def _tool_mutant(module: ModuleType, patch: pytest.MonkeyPatch, kind: str) -> None:
    """Mutate the public operation in memory; its original code still handles each candidate.

    First/last keep only the selected candidate; reverse preserves all candidates but changes
    their order. Foreign substitutes the caller's identity, and echo appends the submitted source.
    """
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


@example(_MISMATCH_THEN_MATCH)
@example(_REFUSED_THEN_VERIFIED)
@example(_FOREIGN)
@example(Case(_program("/mnt/uploads/a.csv"), None, None, ()))
@given(case=_cases())
@settings(max_examples=160, deadline=None)
def test_differential_matches_shipped_tool(case: Case) -> None:
    """Both implementations agree on reply AND the ordered `(program, DatasetTarget)` calls.

    `ORC_M10_MUTANT=first|last|foreign|echo|reverse` makes the SAME graded property go red on a
    public-operation mutant; the default gate run always compares the unmutated generated tool.
    """
    module = load_tool_module()
    with (
        TemporaryDirectory(prefix="oracle-m10u0-") as directory,
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
