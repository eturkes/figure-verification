# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.4 request-bound formula candidate in the generated Open WebUI tool.

Contract: `.agent/archive/contracts/m10u4.md` predicate group T. The request is user-owned;
program bytes and other conversation fields never author a declared target.
"""

import sys
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest

from paste_in_support import (
    REPO_ROOT,
    StoredFile,
    assert_embedded_identity,
    fake_open_webui,
    invoke_tool,
    load_bundle,
    load_tool_module,
    offending_import_roots,
    run_generator,
)
from verifier.pysrc import DatasetTarget, FormulaTarget, Refused, Verdict, Verified, spec
from verifier.pysrc import verify_python_source as core_verify
from webui.paste_in import selection

_USER_ID = "user-1"
_CSV_BYTES = b"site,value\nwest,1\neast,2\n"
_FORMULA_SOURCE = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.linspace(0, 1, num=3)\n"
    "y = np.sin(x)\n"
    "plt.plot(x, y)\n"
    "plt.show()\n"
)
_REQUEST = "y = sin(x), x in [0, 1], n = 3"
_READY = "The chart is ready."
_BLOCKED = "No chart was produced."


def _dataset_source(path: str) -> str:
    return (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("{path}")\n'
        'plt.bar(df["site"], df["value"])\n'
        "plt.show()\n"
    )


def _metadata(request: object, *file_ids: str) -> dict[str, object]:
    return {
        "user_message": {"content": request},
        "files": [{"id": file_id, "name": f"{file_id}.csv"} for file_id in file_ids],
    }


def _stored(file_id: str, filename: str, content: bytes = _CSV_BYTES) -> StoredFile:
    return StoredFile(file_id=file_id, user_id=_USER_ID, filename=filename, content=content)


def _grid() -> spec.Grid:
    return spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(1)), 3)


def test_t7_attachment_order_beats_formula_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T7: attachments run in chat order and a matching CSV wins before any formula target."""
    module = load_tool_module()
    program = _dataset_source("/mnt/uploads/relevant.csv")
    target = FormulaTarget(spec.Fn("sin", spec.Var()), _grid())
    parsed: list[str] = []

    def parser(text: str) -> FormulaTarget:
        parsed.append(text)
        return target

    seen: list[tuple[object, Verdict]] = []

    def spy(source: str, *, declared_target: object) -> Verdict:
        assert source == program
        verdict = core_verify(
            source, declared_target=cast(DatasetTarget | FormulaTarget, declared_target)
        )
        seen.append((declared_target, verdict))
        return verdict

    monkeypatch.setattr(selection, "formula_target", parser)
    monkeypatch.setattr(selection, "verify_python_source", spy)
    stored = [_stored("first", "wrong.csv"), _stored("second", "relevant.csv")]
    with fake_open_webui(stored, tmp_path) as lookups:
        reply = invoke_tool(
            module,
            program,
            metadata=_metadata(_REQUEST, "first", "second"),
            user={"id": _USER_ID},
        )
    assert parsed == [_REQUEST]
    assert lookups == [("first", _USER_ID), ("second", _USER_ID)]
    assert reply == _READY
    assert [declaration for declaration, _verdict in seen] == [
        DatasetTarget("/mnt/uploads/wrong.csv", _CSV_BYTES),
        DatasetTarget("/mnt/uploads/relevant.csv", _CSV_BYTES),
    ]
    assert isinstance(seen[0][1], Refused) and seen[0][1].code == "target_mismatch"
    assert isinstance(seen[1][1], Verified)
    assert seen[1][1].certificate.provenance == "artifact"


def test_t7_formula_candidate_follows_unrelated_csv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T7: a formula program's unrelated CSV mismatches, then user formula binds it."""
    module = load_tool_module()
    seen: list[tuple[object, Verdict]] = []

    def spy(source: str, *, declared_target: object) -> Verdict:
        assert source == _FORMULA_SOURCE
        verdict = core_verify(
            source, declared_target=cast(DatasetTarget | FormulaTarget, declared_target)
        )
        seen.append((declared_target, verdict))
        return verdict

    monkeypatch.setattr(selection, "verify_python_source", spy)
    with fake_open_webui([_stored("one", "unrelated.csv")], tmp_path) as lookups:
        reply = invoke_tool(
            module,
            _FORMULA_SOURCE,
            metadata=_metadata(_REQUEST, "one"),
            user={"id": _USER_ID},
        )
    assert reply == _READY
    assert lookups == [("one", _USER_ID)]
    assert len(seen) == 2
    assert seen[0][0] == DatasetTarget("/mnt/uploads/unrelated.csv", _CSV_BYTES)
    assert isinstance(seen[0][1], Refused) and seen[0][1].code == "target_mismatch"
    assert seen[1][0] == FormulaTarget(
        spec.Fn("sin", spec.Var()),
        _grid(),
    )
    assert isinstance(seen[1][1], Verified)
    assert seen[1][1].certificate.provenance == "artifact"


def test_t8_parser_receives_current_user_message_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T8: the parser gets one exact user_message.content, not source/history/assistant text."""
    module = load_tool_module()
    program = _FORMULA_SOURCE + "# y = cos(x), x in [0, 2]\n"
    unrelated = "y = x**2, x in [5, 9]"
    metadata = _metadata(_REQUEST)
    metadata["__messages__"] = [
        {"role": "user", "content": unrelated},
        {"role": "assistant", "content": unrelated},
    ]
    metadata["history"] = [{"role": "user", "content": unrelated}]
    parsed: list[str] = []
    expected = FormulaTarget(spec.Fn("sin", spec.Var()), _grid())

    def parser(text: str) -> FormulaTarget:
        parsed.append(text)
        return expected

    targets: list[object] = []

    def spy(source: str, *, declared_target: object) -> Verdict:
        assert source == program
        targets.append(declared_target)
        return core_verify(source, declared_target=cast(FormulaTarget, declared_target))

    monkeypatch.setattr(selection, "formula_target", parser)
    monkeypatch.setattr(selection, "verify_python_source", spy)
    with fake_open_webui([], tmp_path):
        reply = invoke_tool(module, program, metadata=metadata, user={"id": _USER_ID})
    assert reply == _READY
    assert parsed == [_REQUEST]
    assert targets == [expected]


@pytest.mark.parametrize("content", [None, 3, b"y=x, x in [0,1]", ["y=x, x in [0,1]"]])
def test_t8_non_string_user_message_never_calls_parser(
    content: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T8: non-string content cannot be forwarded or coerced into a request target."""
    module = load_tool_module()
    calls: list[object] = []

    def parser(text: object) -> None:
        calls.append(text)

    monkeypatch.setattr(selection, "formula_target", parser)
    with fake_open_webui([], tmp_path):
        reply = invoke_tool(
            module, _FORMULA_SOURCE, metadata=_metadata(content), user={"id": _USER_ID}
        )
    assert reply == _BLOCKED
    assert calls == []


@pytest.mark.parametrize("user_message", [None, _REQUEST, [], {"other": _REQUEST}])
def test_t8_malformed_user_message_never_calls_parser(
    user_message: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T8: a non-mapping or content-free user_message cannot substitute another field."""
    module = load_tool_module()
    calls: list[object] = []

    def parser(text: object) -> None:
        calls.append(text)

    monkeypatch.setattr(selection, "formula_target", parser)
    metadata = {"user_message": user_message, "fallback": _REQUEST}
    with fake_open_webui([], tmp_path):
        reply = invoke_tool(module, _FORMULA_SOURCE, metadata=metadata, user={"id": _USER_ID})
    assert reply == _BLOCKED
    assert calls == []


def test_t8_no_fallback_to_other_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """T8: no carrier in the current user text cannot be supplied by another message or source."""
    module = load_tool_module()
    program = _FORMULA_SOURCE + f"# {_REQUEST}\n"
    current = "Please draw a chart."
    metadata = _metadata(current)
    metadata["__messages__"] = [{"role": "user", "content": _REQUEST}]
    metadata["assistant_message"] = {"content": _REQUEST}
    parsed: list[str] = []

    def parser(text: str) -> None:
        parsed.append(text)

    monkeypatch.setattr(selection, "formula_target", parser)
    with fake_open_webui([], tmp_path):
        reply = invoke_tool(module, program, metadata=metadata, user={"id": _USER_ID})
    assert reply == _BLOCKED
    assert parsed == [current]


def test_t9_formula_without_attachment_binds_request(tmp_path: Path) -> None:
    """T9: a valid user carrier verifies a formula when no CSV is attached."""
    module = load_tool_module()
    with fake_open_webui([], tmp_path):
        reply = invoke_tool(
            module, _FORMULA_SOURCE, metadata=_metadata(_REQUEST), user={"id": _USER_ID}
        )
    assert reply == _READY


def test_t9_without_carrier_or_attachment_still_blocks(tmp_path: Path) -> None:
    """T9: no user target and no attachment retain the blocked result."""
    module = load_tool_module()
    with fake_open_webui([], tmp_path):
        reply = invoke_tool(
            module,
            _FORMULA_SOURCE,
            metadata=_metadata("Please draw a chart"),
            user={"id": _USER_ID},
        )
    assert reply == _BLOCKED


def test_t10_formula_with_csv_but_no_request_carrier_blocks(tmp_path: Path) -> None:
    """T10: the old internal-provenance formula/CSV pass can no longer produce a chart."""
    module = load_tool_module()
    with fake_open_webui([_stored("one", "unrelated.csv")], tmp_path):
        reply = invoke_tool(
            module,
            _FORMULA_SOURCE,
            metadata=_metadata("Please draw a chart", "one"),
            user={"id": _USER_ID},
        )
    assert reply == _BLOCKED


def test_t11_generated_artifact_carries_request_core_without_new_imports() -> None:
    """T11: the paste-in has request.py in its exact core closure and no external imports."""
    bundle = load_bundle()
    artifact = REPO_ROOT / "paste-in" / "figure_verification_tool.py"
    text = artifact.read_text(encoding="utf-8")
    sources = bundle.embedded_sources(text)
    checked = run_generator(REPO_ROOT, "--check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "verifier.pysrc.request" in sources
    assert_embedded_identity(sources)
    assert offending_import_roots(bundle, text) == set()
    assert "re" in sys.stdlib_module_names
    assert "unicodedata" in sys.stdlib_module_names
