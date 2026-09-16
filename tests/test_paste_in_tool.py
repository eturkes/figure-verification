# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.0 tool: the ONE model-visible callable over python mode.

Contract: `.agent/contracts/m10u0.md` predicate group T. Each docstring carries its predicate's
acceptance check; the check is the test's specification and the contract's wording wins wherever a
body would assert more.

The tool is a transport, never an authority. It hands the model's exact bytes and the user's exact
uploaded bytes to `verify_python_source` and reports what that returns. Every predicate here exists
to keep a second opinion out of the verdict: no fixture answer, no echo of model text, no
normalization of the path the program named, no fall-back read of a file the caller does not own.
"""

import builtins
import json
import os
import subprocess
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Never, cast, get_args

import pytest

from paste_in_support import REPO_ROOT, invoke_tool, load_tool_module

# Hand-stated closed set: deriving this from `RefusalCode` would let the tool and test
# drift together.
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


def test_t1_exactly_one_model_visible_callable(tmp_path: Path) -> None:
    """T1: OWUI's spec builder over the artifact returns one spec, reserved params absent.

    The parameter set equals the declared non-reserved set, so `__metadata__` and its siblings
    never reach the model.
    """
    artifact = REPO_ROOT / "paste-in" / "figure_verification_tool.py"
    assert artifact.is_file()
    isolated = tmp_path / "figure_verification_tool.py"
    isolated.write_bytes(artifact.read_bytes())
    driver = textwrap.dedent(
        """
        import asyncio
        import inspect
        import json
        import pathlib

        from open_webui.utils.plugin import load_tool_module_by_id
        from open_webui.utils.tools import get_functions_from_tool, get_tool_specs

        async def main():
            artifact = pathlib.Path(__file__).with_name("figure_verification_tool.py")
            tool, _frontmatter = await load_tool_module_by_id(
                "m10u0_test", content=artifact.read_text(encoding="utf-8")
            )
            functions = get_functions_from_tool(tool)
            specs = get_tool_specs(tool)
            declared = {
                function.__name__: [
                    name
                    for name in inspect.signature(function).parameters
                    if not name.startswith("__")
                ]
                for function in functions
            }
            raw_properties = {
                spec["name"]: list(spec["parameters"]["properties"])
                for spec in specs
            }
            model_properties = {
                name: [parameter for parameter in parameters if not parameter.startswith("__")]
                for name, parameters in raw_properties.items()
            }
            print(
                "M10U0_RESULT="
                + json.dumps(
                    {
                        "function_names": [function.__name__ for function in functions],
                        "spec_names": [spec["name"] for spec in specs],
                        "declared": declared,
                        "raw_properties": raw_properties,
                        "model_properties": model_properties,
                    },
                    sort_keys=True,
                )
            )

        asyncio.run(main())
        """
    )
    driver_path = tmp_path / "driver.py"
    driver_path.write_text(driver, encoding="utf-8")
    primary = REPO_ROOT if (REPO_ROOT / ".venv-webui").is_dir() else REPO_ROOT.parents[2]
    interpreter = primary / ".venv-webui" / "bin" / "python"
    assert interpreter.is_file()
    env = os.environ.copy()
    env.update(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS": "false",
            "OFFLINE_MODE": "true",
            "PYTHONPATH": "",
        }
    )
    result = subprocess.run(  # noqa: S603
        [str(interpreter), str(driver_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("M10U0_RESULT="))
    observed: dict[str, dict[str, list[str]] | list[str]] = json.loads(line.partition("=")[2])
    function_names = observed["function_names"]
    spec_names = observed["spec_names"]
    assert isinstance(function_names, list)
    assert isinstance(spec_names, list)
    assert len(function_names) == 1
    assert spec_names == function_names
    operation = function_names[0]
    declared = observed["declared"]
    raw_properties = observed["raw_properties"]
    model_properties = observed["model_properties"]
    assert isinstance(declared, dict)
    assert isinstance(raw_properties, dict)
    assert isinstance(model_properties, dict)
    assert len(declared[operation]) == 1
    assert model_properties[operation] == declared[operation]
    assert set(raw_properties[operation]) - set(model_properties[operation]) == {
        "__metadata__",
        "__request__",
        "__user__",
    }


def test_t2_verdict_comes_from_verify_python_source_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T2: a mutant returning the pass string for a refused program goes red.

    A second mutant that ignores the refusal code goes red too, so neither half of the verdict is
    reachable without the core.
    """
    from verifier.pysrc import (  # noqa: PLC0415
        DatasetTarget,
        RefusalCode,
        Refused,
        Verdict,
        Verified,
        verify_python_source,
    )

    module = load_tool_module()
    assert module.VERIFIED_TEXT == "verified"
    assert module.REFUSED_PREFIX == "refused:"
    program = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("/mnt/uploads/sales.csv")\n'
        'plt.bar(df["region"], df["revenue"])\n'
        "plt.show()\n"
    )
    content = b"region,revenue\nUS,12\nEU,9\n"
    path = "/mnt/uploads/sales.csv"
    target = DatasetTarget(path=path, content=content)
    verified = verify_python_source(program, declared_target=target)
    assert isinstance(verified, Verified)
    verdicts: dict[RefusalCode | None, Verdict] = {
        None: verified,
        "source_too_large": Refused("source_too_large"),
        "target_mismatch": Refused("target_mismatch"),
    }
    selected: RefusalCode | None = None
    metadata: dict[str, object] = {"files": [{"id": "file-1", "name": "sales.csv"}]}
    user: dict[str, object] = {"id": "user-1"}
    request = object()
    reader_calls = 0
    verifier_calls = 0

    async def fake_reader(*args: object, **kwargs: object) -> tuple[str, bytes]:
        nonlocal reader_calls
        reader_calls += 1
        assert args == ()
        assert kwargs == {"metadata": metadata, "user": user, "request": request}
        return path, content

    def fake_verify(source: str, *, declared_target: object) -> Verdict:
        nonlocal verifier_calls
        verifier_calls += 1
        assert source == program
        assert declared_target == target
        return verdicts[selected]

    monkeypatch.setattr(module, "read_attached_file", fake_reader)
    monkeypatch.setattr(module, "verify_python_source", fake_verify)

    def actual(code: RefusalCode | None) -> str:
        nonlocal selected
        selected = code
        return invoke_tool(
            module,
            program,
            metadata=metadata,
            user=user,
            request=request,
        )

    def assert_derivation(render: Callable[[RefusalCode | None], str]) -> None:
        assert render(None) == "verified"
        assert render("source_too_large") == "refused:source_too_large"
        assert render("target_mismatch") == "refused:target_mismatch"

    with pytest.raises(AssertionError):
        assert_derivation(lambda _code: "verified")
    with pytest.raises(AssertionError):
        assert_derivation(lambda code: "verified" if code is None else "refused")
    assert_derivation(actual)
    assert reader_calls == 3
    assert verifier_calls == 3


def test_t3_core_receives_the_uploaded_bytes_for_the_named_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T3: bytes handed to the core are byte-identical to the fake store's.

    A program naming a file the chat does not carry returns the refusal instead of verifying.
    """
    from verifier.pysrc import DatasetTarget, Refused, Verdict  # noqa: PLC0415

    module = load_tool_module()
    path = "/mnt/uploads/sales.csv"
    content = b"region,revenue\r\nUS,12\r\nEU,\xff\r\n"
    program = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("{path}")\n'
        'plt.bar(df["region"], df["revenue"])\n'
        "plt.show()\n"
    )
    present: dict[str, object] = {"files": [{"id": "file-1", "name": "sales.csv"}]}
    absent: dict[str, object] = {"files": []}
    user: dict[str, object] = {"id": "user-1"}
    request = object()
    calls: list[tuple[str, object]] = []

    async def fake_reader(*args: object, **kwargs: object) -> tuple[str, bytes]:
        assert args == ()
        assert set(kwargs) == {"metadata", "user", "request"}
        assert kwargs["user"] is user
        assert kwargs["request"] is request
        if kwargs["metadata"] is absent:
            raise FileNotFoundError
        assert kwargs["metadata"] is present
        return path, content

    def fake_verify(source: str, *, declared_target: object) -> Verdict:
        calls.append((source, declared_target))
        if declared_target is None:
            return Refused("source_not_supplied")
        assert isinstance(declared_target, DatasetTarget)
        assert declared_target.path == path
        assert declared_target.content == content
        return Refused("value_not_in_profile")

    monkeypatch.setattr(module, "read_attached_file", fake_reader)
    monkeypatch.setattr(module, "verify_python_source", fake_verify)

    assert (
        invoke_tool(module, program, metadata=present, user=user, request=request)
        == "refused:value_not_in_profile"
    )
    assert (
        invoke_tool(module, program, metadata=absent, user=user, request=request)
        == "refused:source_not_supplied"
    )
    assert calls == [(program, DatasetTarget(path=path, content=content)), (program, None)]


def test_t4_return_text_is_closed_and_echoes_no_model_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T4: the return value is a member of the closed verdict set, refusal codes included.

    A program whose source carries a marker string returns text that does not contain it.
    """
    from verifier.pysrc import (  # noqa: PLC0415
        DatasetTarget,
        RefusalCode,
        Refused,
        Verdict,
        Verified,
        verify_python_source,
    )

    assert get_args(RefusalCode) == _REFUSAL_CODES
    module = load_tool_module()
    marker = "MODEL_BYTES_MUST_NOT_ECHO_71C9"
    path = "/mnt/uploads/sales.csv"
    content = b"region,revenue\nUS,12\nEU,9\n"
    program = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("{path}")\n'
        'plt.bar(df["region"], df["revenue"])\n'
        "plt.show()\n"
        f"# {marker}\n"
    )
    target = DatasetTarget(path=path, content=content)
    verified = verify_python_source(program, declared_target=target)
    assert isinstance(verified, Verified)
    verdicts: list[Verdict] = [
        verified,
        *(Refused(cast(RefusalCode, code)) for code in _REFUSAL_CODES),
    ]
    selected: Verdict = verified
    metadata: dict[str, object] = {"files": [{"id": "file-1", "name": "sales.csv"}]}
    user: dict[str, object] = {"id": "user-1"}
    request = object()
    reader_calls = 0
    verifier_calls = 0

    async def fake_reader(*args: object, **kwargs: object) -> tuple[str, bytes]:
        nonlocal reader_calls
        reader_calls += 1
        assert args == ()
        assert kwargs == {"metadata": metadata, "user": user, "request": request}
        return path, content

    def fake_verify(source: str, *, declared_target: object) -> Verdict:
        nonlocal verifier_calls
        verifier_calls += 1
        assert source == program
        assert declared_target == target
        return selected

    monkeypatch.setattr(module, "read_attached_file", fake_reader)
    monkeypatch.setattr(module, "verify_python_source", fake_verify)
    outputs: list[str] = []
    for verdict in verdicts:
        selected = verdict
        outputs.append(invoke_tool(module, program, metadata=metadata, user=user, request=request))

    expected = {"verified", *(f"refused:{code}" for code in _REFUSAL_CODES)}
    assert len(outputs) == 53
    assert set(outputs) == expected
    assert all(marker not in output for output in outputs)
    assert reader_calls == 53
    assert verifier_calls == 53


def test_t5_target_is_the_named_path_with_the_uploaded_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T5: `DatasetTarget(path=<read_csv literal>, content=<uploaded bytes>)`, unnormalized.

    A program reading `/mnt/uploads/other.csv` against an attached `sales.csv` refuses
    `target_mismatch`; the path is compared byte-for-byte.
    """
    from verifier.pysrc import DatasetTarget, verify_python_source  # noqa: PLC0415

    module = load_tool_module()
    attached_path = "/mnt/uploads/sales.csv"
    content = b"region,revenue\nUS,12\nEU,9\n"
    metadata: dict[str, object] = {"files": [{"id": "file-1", "name": "sales.csv"}]}
    user: dict[str, object] = {"id": "user-1"}
    request = object()
    calls: list[tuple[str, object]] = []

    def source(path: str) -> str:
        return (
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n"
            f'df = pd.read_csv("{path}")\n'
            'plt.bar(df["region"], df["revenue"])\n'
            "plt.show()\n"
        )

    async def fake_reader(*args: object, **kwargs: object) -> tuple[str, bytes]:
        assert args == ()
        assert kwargs == {"metadata": metadata, "user": user, "request": request}
        return attached_path, content

    def spy_verify(program: str, *, declared_target: object) -> object:
        calls.append((program, declared_target))
        assert isinstance(declared_target, DatasetTarget)
        return verify_python_source(program, declared_target=declared_target)

    monkeypatch.setattr(module, "read_attached_file", fake_reader)
    monkeypatch.setattr(module, "verify_python_source", spy_verify)

    matching = source(attached_path)
    mismatch = source("/mnt/uploads/other.csv")
    assert (
        invoke_tool(module, matching, metadata=metadata, user=user, request=request) == "verified"
    )
    assert (
        invoke_tool(module, mismatch, metadata=metadata, user=user, request=request)
        == "refused:target_mismatch"
    )
    target = DatasetTarget(path=attached_path, content=content)
    assert calls == [(matching, target), (mismatch, target)]


def test_t6_file_access_is_ownership_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """T6: the ownership-checked accessor is the one called, with no fall-back path.

    A fake raising on a foreign id makes the tool refuse rather than read the file another way.
    """
    from verifier.pysrc import Refused, Verdict  # noqa: PLC0415

    module = load_tool_module()
    program = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("/mnt/uploads/foreign.csv")\n'
        'plt.bar(df["region"], df["revenue"])\n'
        "plt.show()\n"
    )
    metadata: dict[str, object] = {"files": [{"id": "foreign-file", "name": "foreign.csv"}]}
    user: dict[str, object] = {"id": "requesting-user"}
    request = object()
    reader_calls = 0
    verifier_calls = 0

    foreign_file = "foreign file"
    fallback_file_read = "tool attempted a fallback file read"
    fallback_path_read = "tool attempted a fallback Path.read_bytes"

    async def foreign_reader(*args: object, **kwargs: object) -> tuple[str, bytes]:
        nonlocal reader_calls
        reader_calls += 1
        assert args == ()
        assert kwargs == {"metadata": metadata, "user": user, "request": request}
        raise PermissionError(foreign_file)

    def fake_verify(source: str, *, declared_target: object) -> Verdict:
        nonlocal verifier_calls
        verifier_calls += 1
        assert source == program
        assert declared_target is None
        return Refused("source_not_supplied")

    def fallback_open(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError(fallback_file_read)

    def fallback_read_bytes(_path: Path) -> Never:
        raise AssertionError(fallback_path_read)

    with monkeypatch.context() as patch:
        patch.setattr(module, "read_attached_file", foreign_reader)
        patch.setattr(module, "verify_python_source", fake_verify)
        patch.setattr(builtins, "open", fallback_open)
        patch.setattr(Path, "read_bytes", fallback_read_bytes)
        output = invoke_tool(module, program, metadata=metadata, user=user, request=request)

    assert output == "refused:source_not_supplied"
    assert reader_calls == 1
    assert verifier_calls == 1
