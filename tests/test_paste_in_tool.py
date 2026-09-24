# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.0 tool: the ONE model-visible callable over python mode.

Contract: `.agent/archive/contracts/m10u0.md` predicate group T. Each docstring carries its
predicate's acceptance check; the check is the test's specification and the contract's wording
wins wherever a body would assert more.

The tool is a transport, never an authority. It hands the model's exact bytes and the user's exact
uploaded bytes to `verify_python_source` and reports what that returns. Every predicate here exists
to keep a second opinion out of the verdict: no fixture answer, no echo of model text, no
normalization of the path the program named, no fall-back read of a file the caller does not own.
"""

import builtins
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Never, cast, get_args

import pytest

from paste_in_support import (
    StoredFile,
    fake_open_webui,
    invoke_tool,
    load_tool_module,
    owui_driver_output,
)
from verifier.pysrc import DatasetTarget, RefusalCode, Refused, Verdict, Verified
from verifier.pysrc import verify_python_source as core_verify

# Hand-stated closed sets: deriving either from production would let the tool and the test drift
# together. The two reply strings are the whole model-facing vocabulary (amendment T4-1), and the
# refusal codes pin the unit's 52-member invariant surface.
_CHART_PRODUCED = "The chart is ready."
_CHART_NOT_PRODUCED = "No chart was produced."
_TOOL_VERDICTS = frozenset({_CHART_PRODUCED, _CHART_NOT_PRODUCED})

_REFUSAL_CODES = (
    "source_too_large",
    "source_not_utf8",
    "source_has_nul",
    "line_too_long",
    "source_not_tokenizable",
    "too_many_tokens",
    "nesting_too_deep",
    "unbalanced_brackets",
    "indent_too_deep",
    "source_not_parsable",
    "statement_not_admitted",
    "expression_not_admitted",
    "import_not_admitted",
    "assign_target_not_admitted",
    "call_target_not_admitted",
    "keyword_not_admitted",
    "attribute_not_admitted",
    "operator_not_admitted",
    "literal_not_admitted",
    "name_not_bound",
    "no_mark",
    "multiple_marks",
    "mark_arity_not_projected",
    "mark_not_valid_for_arm",
    "x_not_a_grid",
    "y_not_over_grid",
    "grid_not_representable",
    "expression_not_projected",
    "label_not_literal",
    "name_rebound",
    "no_terminal",
    "statement_after_terminal",
    "statement_not_projected",
    "arm_ambiguous",
    "no_source",
    "multiple_sources",
    "source_not_literal",
    "column_not_literal",
    "column_not_from_source",
    "aggregation_not_projected",
    "figure_orphans_mark",
    "source_not_supplied",
    "target_mismatch",
    "csv_too_large",
    "csv_not_parsable",
    "column_not_present",
    "column_not_numeric",
    "value_not_in_profile",
    "value_not_finite",
    "work_budget_exceeded",
    "category_not_unique",
    "x_not_ordered",
)

_USER_ID = "user-1"
_SALES_PATH = "/mnt/uploads/sales.csv"
_SALES_BYTES = b"region,revenue\nUS,12\nEU,9\n"


def _program(path: str, trailer: str = "") -> str:
    """A program that verifies against `_SALES_BYTES` when it names the attached file."""
    return (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("{path}")\n'
        'plt.bar(df["region"], df["revenue"])\n'
        "plt.show()\n"
        f"{trailer}"
    )


def _metadata(*file_ids: str) -> dict[str, object]:
    """Open WebUI's chat metadata shape: the attachment list the browser forwards."""
    return {"files": [{"id": file_id, "name": f"{file_id}.csv"} for file_id in file_ids]}


def test_t1_exactly_one_model_visible_callable(tmp_path: Path) -> None:
    """T1: OWUI's spec builder over the artifact returns one spec, reserved params absent.

    The parameter set equals the declared non-reserved set, so `__metadata__` and its siblings
    never reach the model.
    """
    payload = owui_driver_output(
        """
        import asyncio
        import inspect
        import json
        import pathlib

        from open_webui.utils.plugin import load_tool_module_by_id
        from open_webui.utils.tools import get_functions_from_tool, get_tool_specs

        def parameters(function, reserved):
            return [
                name
                for name in inspect.signature(function).parameters
                if name.startswith("__") == reserved
            ]

        async def main():
            artifact = pathlib.Path(__file__).with_name("figure_verification_tool.py")
            tool, _frontmatter = await load_tool_module_by_id(
                "m10u0_test", content=artifact.read_text(encoding="utf-8")
            )
            functions = get_functions_from_tool(tool)
            specs = get_tool_specs(tool)
            print(
                "M10U0_RESULT="
                + json.dumps(
                    {
                        "function_names": [f.__name__ for f in functions],
                        "spec_names": [spec["name"] for spec in specs],
                        "declared": {
                            f.__name__: parameters(f, False) for f in functions
                        },
                        "reserved": {
                            f.__name__: parameters(f, True) for f in functions
                        },
                        "properties": {
                            spec["name"]: list(spec["parameters"]["properties"])
                            for spec in specs
                        },
                    },
                    sort_keys=True,
                )
            )

        asyncio.run(main())
        """,
        tmp_path,
        "M10U0_RESULT",
    )
    observed: dict[str, dict[str, list[str]] | list[str]] = json.loads(payload)
    function_names = observed["function_names"]
    spec_names = observed["spec_names"]
    assert isinstance(function_names, list)
    assert isinstance(spec_names, list)
    assert len(function_names) == 1
    assert spec_names == function_names
    operation = function_names[0]
    declared = observed["declared"]
    reserved = observed["reserved"]
    properties = observed["properties"]
    assert isinstance(declared, dict)
    assert isinstance(reserved, dict)
    assert isinstance(properties, dict)
    # The reserved parameters ARE declared on the method, which is what makes their absence from
    # the schema a finding rather than a tautology.
    assert reserved[operation] == ["__metadata__", "__user__"]
    assert len(declared[operation]) == 1
    assert properties[operation] == declared[operation]


@dataclass(frozen=True, slots=True)
class _Case:
    """One scripted sequence of core verdicts and the reply the tool must derive from it."""

    name: str
    attachments: int
    verdicts: tuple[Verdict, ...]
    expected: str


def _verified() -> Verified:
    """A real `Verified`, taken from the core rather than hand-built."""
    verdict = core_verify(
        _program(_SALES_PATH),
        declared_target=DatasetTarget(path=_SALES_PATH, content=_SALES_BYTES),
    )
    assert isinstance(verdict, Verified)
    return verdict


def _stored(count: int) -> list[StoredFile]:
    return [
        StoredFile(
            file_id=f"file-{index}",
            user_id=_USER_ID,
            filename=f"file-{index}.csv",
            content=_SALES_BYTES,
        )
        for index in range(count)
    ]


def test_t2_verdict_comes_from_verify_python_source_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T2: a mutant returning the pass string for a refused program goes red.

    Two more mutants ignore the refusal code -- one stopping at the first verdict, one taking the
    last -- and both go red, so neither half of the derivation is reachable without the core.
    """
    module = load_tool_module()
    program = _program(_SALES_PATH)
    verified = _verified()
    cases = (
        _Case("verified", 1, (verified,), _CHART_PRODUCED),
        _Case("refused", 1, (Refused("source_too_large"),), _CHART_NOT_PRODUCED),
        # Only `target_mismatch` means "right program, wrong file", so only it may keep the scan
        # going; every other refusal is this program's answer and ends it.
        _Case("mismatch-then-verified", 2, (Refused("target_mismatch"), verified), _CHART_PRODUCED),
        _Case(
            "refused-then-verified",
            2,
            (Refused("column_not_numeric"), verified),
            _CHART_NOT_PRODUCED,
        ),
    )
    targets: list[str] = []

    def actual(case: _Case) -> str:
        remaining = list(case.verdicts)

        def scripted(source: str, *, declared_target: object) -> Verdict:
            assert source == program
            assert isinstance(declared_target, DatasetTarget)
            targets.append(declared_target.path)
            return remaining.pop(0)

        monkeypatch.setattr(module, "verify_python_source", scripted)
        stored = _stored(case.attachments)
        with fake_open_webui(stored, tmp_path):
            return invoke_tool(
                module,
                program,
                metadata=_metadata(*(item.file_id for item in stored)),
                user={"id": _USER_ID},
            )

    def text(verdict: Verdict) -> str:
        return _CHART_PRODUCED if isinstance(verdict, Verified) else _CHART_NOT_PRODUCED

    def assert_derivation(render: Callable[[_Case], str]) -> None:
        for case in cases:
            assert render(case) == case.expected, case.name

    with pytest.raises(AssertionError):
        assert_derivation(lambda _case: _CHART_PRODUCED)
    with pytest.raises(AssertionError):
        assert_derivation(lambda case: text(case.verdicts[0]))
    with pytest.raises(AssertionError):
        assert_derivation(lambda case: text(case.verdicts[-1]))

    assert_derivation(actual)
    assert targets == [
        "/mnt/uploads/file-0.csv",
        "/mnt/uploads/file-0.csv",
        "/mnt/uploads/file-0.csv",
        "/mnt/uploads/file-1.csv",
        "/mnt/uploads/file-0.csv",
    ]


def test_t3_core_receives_the_uploaded_bytes_for_the_named_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T3: bytes handed to the core are byte-identical to the fake store's.

    A program naming a file the chat does not carry returns the refusal instead of verifying.
    """
    module = load_tool_module()
    # CRLF plus a byte no UTF-8 decoder accepts: a reader that decoded and re-encoded loses both.
    content = b"region,revenue\r\nUS,12\r\nEU,\xff\r\n"
    program = _program(_SALES_PATH)
    stored = [StoredFile(file_id="file-1", user_id=_USER_ID, filename="sales.csv", content=content)]
    calls: list[tuple[str, object]] = []

    def spy(source: str, *, declared_target: object) -> Verdict:
        calls.append((source, declared_target))
        return Refused("value_not_in_profile")

    monkeypatch.setattr(module, "verify_python_source", spy)
    with fake_open_webui(stored, tmp_path) as lookups:
        present = invoke_tool(module, program, metadata=_metadata("file-1"), user={"id": _USER_ID})
        absent = invoke_tool(module, program, metadata={"files": []}, user={"id": _USER_ID})

    assert present == _CHART_NOT_PRODUCED
    assert absent == _CHART_NOT_PRODUCED
    assert lookups == [("file-1", _USER_ID)]
    # No attachment means no target the core could be asked about, so the second call never
    # reaches it: an absent file cannot verify by any route.
    assert calls == [(program, DatasetTarget(path=_SALES_PATH, content=content))]


def test_t4_return_text_is_closed_and_echoes_no_model_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T4: the return value is a member of the closed verdict set.

    A program whose source carries a marker string returns text that does not contain it. Refusal
    codes are OUT of the reply by amendment T4-1: five of them carry a banned admission stem.
    """
    assert get_args(RefusalCode) == _REFUSAL_CODES
    module = load_tool_module()
    marker = "MODEL_BYTES_MUST_NOT_ECHO_71C9"
    program = _program(_SALES_PATH, trailer=f"# {marker}\n")
    verdicts: list[Verdict] = [
        _verified(),
        *(Refused(cast(RefusalCode, code)) for code in _REFUSAL_CODES),
    ]
    selected: Verdict = verdicts[0]
    calls = 0

    def scripted(source: str, *, declared_target: object) -> Verdict:
        nonlocal calls
        calls += 1
        assert source == program
        assert isinstance(declared_target, DatasetTarget)
        return selected

    monkeypatch.setattr(module, "verify_python_source", scripted)
    outputs: list[str] = []
    with fake_open_webui(_stored(1), tmp_path):
        for verdict in verdicts:
            selected = verdict
            outputs.append(
                invoke_tool(module, program, metadata=_metadata("file-0"), user={"id": _USER_ID})
            )

    assert len(outputs) == 53
    assert calls == 53
    assert set(outputs) == _TOOL_VERDICTS
    assert all(marker not in output for output in outputs)


def test_t5_target_is_the_named_path_with_the_uploaded_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T5: `DatasetTarget(path=<read_csv literal>, content=<uploaded bytes>)`, unnormalized.

    A program reading `/mnt/uploads/other.csv` against an attached `sales.csv` refuses
    `target_mismatch`; the path is compared byte-for-byte inside the core.
    """
    module = load_tool_module()
    stored = [
        StoredFile(file_id="file-1", user_id=_USER_ID, filename="sales.csv", content=_SALES_BYTES)
    ]
    calls: list[tuple[str, object, Verdict]] = []

    def spy(source: str, *, declared_target: object) -> Verdict:
        assert isinstance(declared_target, DatasetTarget)
        verdict = core_verify(source, declared_target=declared_target)
        calls.append((source, declared_target, verdict))
        return verdict

    monkeypatch.setattr(module, "verify_python_source", spy)
    matching = _program(_SALES_PATH)
    mismatch = _program("/mnt/uploads/other.csv")
    with fake_open_webui(stored, tmp_path):
        produced = invoke_tool(
            module, matching, metadata=_metadata("file-1"), user={"id": _USER_ID}
        )
        withheld = invoke_tool(
            module, mismatch, metadata=_metadata("file-1"), user={"id": _USER_ID}
        )

    assert produced == _CHART_PRODUCED
    assert withheld == _CHART_NOT_PRODUCED
    target = DatasetTarget(path=_SALES_PATH, content=_SALES_BYTES)
    assert [(source, declared) for source, declared, _verdict in calls] == [
        (matching, target),
        (mismatch, target),
    ]
    assert isinstance(calls[0][2], Verified)
    refused = calls[1][2]
    assert isinstance(refused, Refused)
    assert refused.code == "target_mismatch"


def test_t6_file_access_is_ownership_checked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T6: the ownership-checked accessor is the one called, with no fall-back path.

    A store that answers `None` for a foreign id makes the tool refuse rather than read the file
    another way.
    """
    module = load_tool_module()
    program = _program("/mnt/uploads/foreign.csv")
    stored = [
        StoredFile(
            file_id="foreign-file",
            user_id="owning-user",
            filename="foreign.csv",
            content=_SALES_BYTES,
        )
    ]

    foreign_target = "the core was asked about a file the caller does not own"
    fallback_file_read = "tool attempted a fall-back file read"
    fallback_path_read = "tool attempted a fall-back Path.read_bytes"

    def bomb_verify(source: str, *, declared_target: object) -> Never:
        del source, declared_target
        raise AssertionError(foreign_target)

    def fallback_open(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError(fallback_file_read)

    def fallback_read_bytes(_path: Path) -> Never:
        raise AssertionError(fallback_path_read)

    monkeypatch.setattr(module, "verify_python_source", bomb_verify)
    # The bombs are withdrawn before the assertions: pytest reads `os.environ` through `open`
    # while it writes the call-phase report, so one surviving the body kills the whole run.
    with (
        fake_open_webui(stored, tmp_path) as lookups,
        monkeypatch.context() as patch,
    ):
        patch.setattr(builtins, "open", fallback_open)
        patch.setattr(Path, "read_bytes", fallback_read_bytes)
        output = invoke_tool(
            module,
            program,
            metadata=_metadata("foreign-file"),
            user={"id": "requesting-user"},
        )

    assert output == _CHART_NOT_PRODUCED
    # One ownership-checked lookup, whose `None` is the whole access decision: no second route
    # exists, which the two bombs above prove by never firing.
    assert lookups == [("foreign-file", "requesting-user")]
