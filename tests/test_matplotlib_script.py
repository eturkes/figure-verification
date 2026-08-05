# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Binary64 fidelity, fixed-language source, canonical bytes, limits, and hash binding."""

import ast
import hashlib
import inspect
import json
import math
import os
import subprocess
import sys
import tokenize
import tomllib
from dataclasses import FrozenInstanceError, fields, replace
from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from typing import Any, NoReturn, cast

import msgspec
import pytest

from verifier import canon, checks, formula_prepare, matplotlib_script
from verifier.errors import VerificationError
from verifier.formula_prepare import PreparedFormula
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import FormulaMark, FormulaPlotSpec, decode_formula_spec

_ROOT = Path(__file__).resolve().parent.parent
_GOOD_DIR = _ROOT / "examples/formula_good_specs"
_BAD_DIR = _ROOT / "examples/formula_bad_specs"
_INDEX: dict[str, Any] = json.loads((_ROOT / "examples/index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["formula_good_specs"]
_BAD: list[dict[str, Any]] = _INDEX["formula_bad_specs"]

_F02_LINE_GOLDEN = b"""import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

x = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
y = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0]
fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
ax.plot(x, y, color="#2563eb", linewidth=2.0)
ax.set_xscale("linear")
ax.set_yscale("linear")
ax.set_xlim(0.0, 10.0)
ax.set_xlabel("x")
ax.set_ylabel("y")
ax.grid(True, color="#d1d5db", linewidth=0.8)
fig.tight_layout()
plt.show()
"""
_F06_SCATTER_GOLDEN = b"""import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

x = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
y = [-2.0, -0.75, 0.0, 0.25, 0.0, -0.75, -2.0]
fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
ax.scatter(x, y, color="#2563eb", s=24.0)
ax.set_xscale("linear")
ax.set_yscale("linear")
ax.set_xlim(0.0, 3.0)
ax.set_xlabel("x")
ax.set_ylabel("y")
ax.grid(True, color="#d1d5db", linewidth=0.8)
fig.tight_layout()
plt.show()
"""
_THREE_POINT_GOLDEN = b"""import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

x = [0.0, 1.0, 2.0]
y = [0.0, 1.0, 2.0]
fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
ax.plot(x, y, color="#2563eb", linewidth=2.0)
ax.set_xscale("linear")
ax.set_yscale("linear")
ax.set_xlim(0.0, 2.0)
ax.set_xlabel("x")
ax.set_ylabel("y")
ax.grid(True, color="#d1d5db", linewidth=0.8)
fig.tight_layout()
plt.show()
"""


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(entry["file"]).stem for entry in entries]


def _spec(  # noqa: PLR0913
    formula: str,
    *,
    bounds: tuple[str, str] = ("0", "1"),
    samples: int = 2,
    x_scale: int = 0,
    y_scale: int = 0,
    mark: FormulaMark = "line",
) -> FormulaPlotSpec:
    start, stop = bounds
    raw: dict[str, Any] = {
        "version": "vplot-formula-0.1",
        "formula": formula,
        "domain": {
            "start": start,
            "stop": stop,
            "samples": samples,
            "x_scale": x_scale,
            "y_scale": y_scale,
        },
        "numeric_profile": "rational-half-even-v1",
        "mark": mark,
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
    return decode_formula_spec(msgspec.json.encode(raw))


def _prepare(
    spec: FormulaPlotSpec,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> PreparedFormula:
    core = checks.verify_formula_run(spec, limits=limits)
    evidence = core.require_evidence()
    preparation = formula_prepare.prepare_formula(spec, evidence, limits=limits)
    prepared = preparation.prepared
    assert core.report.passed
    assert preparation.report.passed
    assert prepared is not None
    return prepared


def _artifact(
    spec: FormulaPlotSpec,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> matplotlib_script.MatplotlibScriptArtifact:
    run = matplotlib_script.emit_matplotlib_script(_prepare(spec, limits=limits), limits=limits)
    artifact = run.artifact
    assert run.report.passed
    assert artifact is not None
    return artifact


def _fidelity_failure(prepared: PreparedFormula) -> checks.CheckResult:
    run = matplotlib_script.emit_matplotlib_script(prepared)
    assert not run.report.passed
    assert run.artifact is None
    assert run.report.results[:-1] == prepared.results
    failure = run.report.results[-1]
    assert failure.check == "render.float64_fidelity"
    assert failure.method == "deterministic_recompute"
    assert failure.status == "fail"
    return failure


def _half_even_at_scale(value: Fraction, scale: int) -> Fraction:
    factor = 10**scale
    scaled = value * factor
    sign = -1 if scaled.numerator < 0 else 1
    quotient, remainder = divmod(abs(scaled.numerator), scaled.denominator)
    twice = 2 * remainder
    if twice > scaled.denominator or (twice == scaled.denominator and quotient % 2 == 1):
        quotient += 1
    return Fraction(sign * quotient, factor)


def _independent_projection(value: Decimal, scale: int) -> tuple[float, str]:
    projected = float(value)
    assert math.isfinite(projected)
    assert _half_even_at_scale(Fraction.from_float(projected), scale) == Fraction(value)
    if projected == 0.0:
        projected = 0.0
    return projected, repr(projected)


def _statement_source(text: str, statement: ast.stmt) -> str:
    source = ast.get_source_segment(text, statement)
    assert source is not None
    return source


def _numeric_value(text: str, node: ast.expr) -> float:
    if isinstance(node, ast.Constant):
        assert type(node.value) is float
        value = node.value
    else:
        assert isinstance(node, ast.UnaryOp)
        assert isinstance(node.op, ast.USub)
        assert isinstance(node.operand, ast.Constant)
        assert type(node.operand.value) is float
        value = -node.operand.value
    assert ast.get_source_segment(text, node) == repr(value)
    return value


def _assignment_values(text: str, statement: ast.stmt, name: str) -> tuple[float, ...]:
    assert isinstance(statement, ast.Assign)
    assert len(statement.targets) == 1
    target = statement.targets[0]
    assert isinstance(target, ast.Name)
    assert target.id == name
    assert isinstance(statement.value, ast.List)
    return tuple(_numeric_value(text, element) for element in statement.value.elts)


def _assert_closed_script(  # noqa: PLR0913
    script: bytes,
    *,
    mark: FormulaMark,
    x_values: tuple[float, ...],
    y_values: tuple[float, ...],
    x_start: float,
    x_stop: float,
) -> None:
    text = script.decode("ascii")
    assert text.encode("utf-8") == script
    assert script.endswith(b"\n") and not script.endswith(b"\n\n")
    assert b"\r" not in script and b"\t" not in script
    assert all(not line.endswith(b" ") for line in script.splitlines())
    assert all(not line.startswith(b" ") for line in script.splitlines() if line)
    assert not any(
        token.type == tokenize.COMMENT for token in tokenize.tokenize(BytesIO(script).readline)
    )

    tree = ast.parse(text)
    assert len(tree.body) == 15
    assert _statement_source(text, tree.body[0]) == "import matplotlib"
    assert _statement_source(text, tree.body[1]) == 'matplotlib.use("Agg")'
    assert _statement_source(text, tree.body[2]) == "import matplotlib.pyplot as plt"
    assert _assignment_values(text, tree.body[3], "x") == x_values
    assert _assignment_values(text, tree.body[4], "y") == y_values

    mark_line = (
        'ax.plot(x, y, color="#2563eb", linewidth=2.0)'
        if mark == "line"
        else 'ax.scatter(x, y, color="#2563eb", s=24.0)'
    )
    expected_statements = (
        "fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)",
        mark_line,
        'ax.set_xscale("linear")',
        'ax.set_yscale("linear")',
        f"ax.set_xlim({x_start!r}, {x_stop!r})",
        'ax.set_xlabel("x")',
        'ax.set_ylabel("y")',
        'ax.grid(True, color="#d1d5db", linewidth=0.8)',
        "fig.tight_layout()",
        "plt.show()",
    )
    assert tuple(_statement_source(text, statement) for statement in tree.body[5:]) == (
        expected_statements
    )

    forbidden_nodes = (
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Lambda,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.If,
        ast.With,
        ast.AsyncWith,
        ast.Try,
        ast.Match,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.Await,
        ast.Yield,
        ast.YieldFrom,
        ast.Global,
        ast.Nonlocal,
    )
    assert not any(isinstance(node, forbidden_nodes) for node in ast.walk(tree))
    strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert strings == {"Agg", "linear", "x", "y", "#2563eb", "#d1d5db"}
    assert all(
        "://" not in value and "data:" not in value and "/" not in value and "\\" not in value
        for value in strings
    )


def _forged_rows(
    prepared: PreparedFormula,
    rows: tuple[tuple[Decimal, Decimal], ...],
) -> PreparedFormula:
    table = msgspec.structs.replace(prepared.evidence.plotted_table, rows=rows)
    evidence = replace(prepared.evidence, plotted_table=table)
    return replace(prepared, evidence=evidence)


def _forged_source(
    prepared: PreparedFormula,
    *,
    start: Decimal | None = None,
    stop: Decimal | None = None,
) -> PreparedFormula:
    source = prepared.evidence.formula_source
    if start is not None:
        source = msgspec.structs.replace(source, start=start)
    if stop is not None:
        source = msgspec.structs.replace(source, stop=stop)
    evidence = replace(prepared.evidence, formula_source=source)
    return replace(prepared, evidence=evidence)


def _fixed_structure(script: bytes) -> tuple[str, ...]:
    lines = script.decode("ascii").splitlines()
    return tuple(line for index, line in enumerate(lines) if index not in {4, 5, 10})


_DETERMINISM_PROGRAM = r"""
import msgspec
from verifier import checks, formula_prepare, matplotlib_script
from verifier.schema import decode_formula_spec
raw = msgspec.json.encode({
    "version": "vplot-formula-0.1",
    "formula": "2*x+1",
    "domain": {"start": "0", "stop": "10", "samples": 11, "x_scale": 0, "y_scale": 0},
    "numeric_profile": "rational-half-even-v1",
    "mark": "line",
    "encoding": {
        "x": {"field": "x", "type": "quantitative"},
        "y": {"field": "y", "type": "quantitative"},
    },
})
spec = decode_formula_spec(raw)
evidence = checks.verify_formula_run(spec).require_evidence()
prepared = formula_prepare.prepare_formula(spec, evidence).prepared
assert prepared is not None
artifact = matplotlib_script.emit_matplotlib_script(prepared).artifact
assert artifact is not None
print(artifact.matplotlib_script.hex())
print(artifact.matplotlib_script_hash)
"""


def test_module_boundary_public_surface_and_exact_byte_dataflow() -> None:
    source_path = _ROOT / "src/verifier/matplotlib_script.py"
    source = source_path.read_text(encoding="utf-8")
    module = ast.parse(source)
    imported: list[tuple[str, str, str | None]] = []
    for statement in module.body:
        if isinstance(statement, ast.Import):
            imported.extend(("import", item.name, item.asname) for item in statement.names)
        elif isinstance(statement, ast.ImportFrom):
            assert statement.module is not None
            imported.extend((statement.module, item.name, item.asname) for item in statement.names)
    assert imported == [
        ("import", "math", None),
        ("collections.abc", "Mapping", None),
        ("dataclasses", "dataclass", None),
        ("dataclasses", "field", None),
        ("decimal", "Decimal", None),
        ("fractions", "Fraction", None),
        ("types", "MappingProxyType", None),
        ("typing", "cast", None),
        ("verifier", "canon", None),
        ("verifier", "checks", None),
        ("verifier.errors", "VerificationError", None),
        ("verifier.formula_prepare", "PreparedFormula", None),
        ("verifier.limits", "DEFAULT_LIMITS", None),
        ("verifier.limits", "VerificationLimits", None),
        ("verifier.schema", "FormulaMark", None),
        ("verifier.schema", "FormulaPlotSpec", None),
    ]
    assert "matplotlib" not in {module_name for _kind, module_name, _alias in imported}
    assert "vl_convert" not in source
    assert "verifier.render" not in source

    calls = {
        node.func.id
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls.isdisjoint({"eval", "exec", "compile", "open", "__import__"})

    emitter = next(
        statement
        for statement in module.body
        if isinstance(statement, ast.FunctionDef) and statement.name == "emit_matplotlib_script"
    )
    assert any(
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "size"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "len"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == "script"
        for node in ast.walk(emitter)
    )

    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = cast("list[str]", cast("dict[str, Any]", project["project"])["dependencies"])
    assert not any(
        dependency.partition("<")[0].partition(">")[0] == "matplotlib"
        for dependency in dependencies
    )

    assert matplotlib_script.SCRIPT_TEMPLATE_VERSION == "matplotlib-script-0.1"
    assert matplotlib_script.__all__ == [
        "SCRIPT_TEMPLATE_VERSION",
        "MatplotlibScriptArtifact",
        "MatplotlibScriptRun",
        "emit_matplotlib_script",
    ]
    signature = inspect.signature(matplotlib_script.emit_matplotlib_script)
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == ("prepared", "limits")
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].annotation is PreparedFormula
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[1].annotation is VerificationLimits
    assert parameters[1].default is DEFAULT_LIMITS
    assert signature.return_annotation is matplotlib_script.MatplotlibScriptRun


def test_fresh_import_and_build_never_load_display_dependencies() -> None:
    program = r"""
import builtins
import sys
original_import = builtins.__import__
def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.partition(".")[0]
    if root in {"matplotlib", "vl_convert"}:
        raise AssertionError(name)
    if name == "verifier.render" or (name == "verifier" and "render" in fromlist):
        raise AssertionError(name)
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded
import msgspec
from verifier import checks, formula_prepare, matplotlib_script
from verifier.schema import decode_formula_spec
raw = msgspec.json.encode({
    "version": "vplot-formula-0.1",
    "formula": "0",
    "domain": {"start": "0", "stop": "1", "samples": 2, "x_scale": 0, "y_scale": 0},
    "numeric_profile": "rational-half-even-v1",
    "mark": "line",
    "encoding": {
        "x": {"field": "x", "type": "quantitative"},
        "y": {"field": "y", "type": "quantitative"},
    },
})
spec = decode_formula_spec(raw)
evidence = checks.verify_formula_run(spec).require_evidence()
prepared = formula_prepare.prepare_formula(spec, evidence).prepared
assert prepared is not None
run = matplotlib_script.emit_matplotlib_script(prepared)
assert run.artifact is not None
assert not any(name == "matplotlib" or name.startswith("matplotlib.") for name in sys.modules)
assert not any(name == "vl_convert" or name.startswith("vl_convert.") for name in sys.modules)
assert "verifier.render" not in sys.modules
print(len(run.artifact.matplotlib_script))
"""
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", program],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == "385\n"
    assert completed.stderr == ""


def test_public_types_are_frozen_slotted_identity_bound_and_ordered() -> None:
    prepared = _prepare(_spec("0"))
    run = matplotlib_script.emit_matplotlib_script(prepared)
    artifact = run.artifact
    assert artifact is not None

    assert tuple(item.name for item in fields(matplotlib_script.MatplotlibScriptArtifact)) == (
        "spec",
        "evidence",
        "results",
        "matplotlib_script",
        "matplotlib_script_hash",
    )
    assert tuple(item.name for item in fields(matplotlib_script.MatplotlibScriptRun)) == (
        "report",
        "artifact",
    )
    assert not hasattr(run, "__dict__")
    assert not hasattr(artifact, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(run, "artifact", None)  # noqa: B010
    with pytest.raises(FrozenInstanceError):
        setattr(artifact, "matplotlib_script_hash", "changed")  # noqa: B010

    assert artifact.spec is prepared.spec
    assert artifact.evidence is prepared.evidence
    assert artifact.results is run.report.results
    assert artifact.results[: len(prepared.results)] == prepared.results
    assert tuple(result.check for result in artifact.results[-5:]) == (
        "render.float64_fidelity",
        "render.axes_linear",
        "render.x_domain_exact",
        "render.points_match_evidence",
        "render.matplotlib_script_allowlisted",
    )
    assert tuple(result.method for result in artifact.results[-5:]) == (
        "deterministic_recompute",
        "construction",
        "construction",
        "construction",
        "construction",
    )
    assert tuple(result.message for result in artifact.results[-5:]) == (
        "every plotted value and domain endpoint survives float64 projection at its declared "
        "Decimal scale; projected x remains strictly increasing",
        "the fixed template sets both axes to linear scales",
        "the fixed template sets x limits to the float64 projections of the certified domain "
        "endpoints",
        "the fixed template inlines only the validated float64 projections of this evidence "
        "table's x/y points",
        "closed line/scatter dispatch selects a fixed script template; only verifier-derived "
        "finite x/y and domain numeric literals vary",
    )
    assert all(result.status == "pass" for result in artifact.results[-5:])


@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_good_formula_corpus_emits_only_independently_admitted_points(
    entry: dict[str, Any],
) -> None:
    spec = decode_formula_spec((_GOOD_DIR / entry["file"]).read_bytes())
    prepared = _prepare(spec)
    run = matplotlib_script.emit_matplotlib_script(prepared)
    artifact = run.artifact
    assert artifact is not None
    source = prepared.evidence.formula_source
    rows = prepared.evidence.plotted_table.rows
    x_values = tuple(
        _independent_projection(cast("Decimal", row[0]), source.x_scale)[0] for row in rows
    )
    y_values = tuple(
        _independent_projection(cast("Decimal", row[1]), source.y_scale)[0] for row in rows
    )
    x_start = _independent_projection(source.start, source.x_scale)[0]
    x_stop = _independent_projection(source.stop, source.x_scale)[0]

    _assert_closed_script(
        artifact.matplotlib_script,
        mark=spec.mark,
        x_values=x_values,
        y_values=y_values,
        x_start=x_start,
        x_stop=x_stop,
    )
    assert artifact.matplotlib_script_hash == canon.hash_matplotlib_script(
        artifact.matplotlib_script
    )
    assert len(x_values) == len(rows) == len(y_values)


def test_line_and_scatter_scripts_match_inline_byte_goldens() -> None:
    line = _artifact(decode_formula_spec((_GOOD_DIR / "f02_linear.json").read_bytes()))
    scatter = _artifact(decode_formula_spec((_GOOD_DIR / "f06_quadratic.json").read_bytes()))
    assert line.matplotlib_script == _F02_LINE_GOLDEN
    assert len(line.matplotlib_script) == 483
    assert line.matplotlib_script_hash == (
        "sha256:8861069e6a140ecd4bca9c8d85873477f9d50408f9f0c13ad350a7e640be7cd9"
    )
    assert scatter.matplotlib_script == _F06_SCATTER_GOLDEN
    assert len(scatter.matplotlib_script) == 438
    assert scatter.matplotlib_script_hash == (
        "sha256:03c7cd2d5406c068eecd8f6e3658cc9b99a09772c4425c5e3e897c8e15a77974"
    )


_MUTATIONS = (
    ("bar", b"ax.plot(", b"ax.bar("),
    ("dynamic-getattr", b"ax.plot(", b'getattr(ax, "plot")('),
    ("dunder-class", b"ax.plot(", b"ax.__class__.plot("),
    ("dunder-getattribute", b"ax.plot(", b'ax.__getattribute__("plot")('),
    ("dynamic-import", b"plt.show()\n", b'__import__("os")\nplt.show()\n'),
    ("open", b"plt.show()\n", b'open("/tmp/x")\nplt.show()\n'),
    ("eval", b"plt.show()\n", b'eval("1")\nplt.show()\n'),
    ("exec", b"plt.show()\n", b'exec("pass")\nplt.show()\n'),
    ("compile", b"plt.show()\n", b'compile("1", "x", "eval")\nplt.show()\n'),
    ("os-system", b"plt.show()\n", b'os.system("x")\nplt.show()\n'),
    ("subprocess", b"plt.show()\n", b'subprocess.run(["x"])\nplt.show()\n'),
    ("socket", b"plt.show()\n", b"socket.socket()\nplt.show()\n"),
    (
        "urllib",
        b"plt.show()\n",
        b'urllib.request.urlopen("https://example.test")\nplt.show()\n',
    ),
    ("savefig", b"plt.show()\n", b'fig.savefig("/tmp/x")\nplt.show()\n'),
    ("comment", b"plt.show()\n", b"# model formula\nplt.show()\n"),
    (
        "extra-import",
        b"import matplotlib.pyplot as plt\n",
        b"import os\nimport matplotlib.pyplot as plt\n",
    ),
    (
        "interactive-backend",
        b'matplotlib.use("Agg")',
        b'matplotlib.use("TkAgg")',
    ),
    (
        "backend-after-pyplot",
        b'matplotlib.use("Agg")\nimport matplotlib.pyplot as plt',
        b'import matplotlib.pyplot as plt\nmatplotlib.use("Agg")',
    ),
    ("missing-x-scale", b'ax.set_xscale("linear")\n', b""),
    ("log-x-scale", b'ax.set_xscale("linear")', b'ax.set_xscale("log")'),
    ("missing-y-scale", b'ax.set_yscale("linear")\n', b""),
    ("padded-domain", b"ax.set_xlim(0.0, 10.0)", b"ax.set_xlim(-0.5, 10.5)"),
    ("formula-title", b"plt.show()\n", b'ax.set_title("2*x+1")\nplt.show()\n'),
    ("url", b"plt.show()\n", b'url = "https://example.test"\nplt.show()\n'),
    ("loop", b"plt.show()\n", b"for _ in ():\n    pass\nplt.show()\n"),
    (
        "second-series",
        b"plt.show()\n",
        b'ax.plot(x, y, color="#2563eb", linewidth=2.0)\nplt.show()\n',
    ),
    (
        "generated-x",
        b"x = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]",
        b"x = list(range(11))",
    ),
    (
        "reverse-y",
        b"y = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0]",
        b"y = [21.0, 19.0, 17.0, 15.0, 13.0, 11.0, 9.0, 7.0, 5.0, 3.0, 1.0]",
    ),
    (
        "drop-middle",
        b"y = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0]",
        b"y = [1.0, 3.0, 5.0, 7.0, 9.0, 13.0, 15.0, 17.0, 19.0, 21.0]",
    ),
    (
        "duplicate-last",
        b"y = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0]",
        b"y = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0, 21.0]",
    ),
    (
        "add-synthetic",
        b"y = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0]",
        b"y = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0, 23.0]",
    ),
    (
        "swap-x-y",
        (
            b"x = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]\n"
            b"y = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0]"
        ),
        (
            b"x = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0]\n"
            b"y = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]"
        ),
    ),
    ("missing-show", b"plt.show()\n", b""),
    ("duplicate-show", b"plt.show()\n", b"plt.show()\nplt.show()\n"),
    ("missing-domain", b"ax.set_xlim(0.0, 10.0)\n", b""),
    ("reversed-domain", b"ax.set_xlim(0.0, 10.0)", b"ax.set_xlim(10.0, 0.0)"),
    ("y-derived-domain", b"ax.set_xlim(0.0, 10.0)", b"ax.set_xlim(1.0, 21.0)"),
    ("log-y-scale", b'ax.set_yscale("linear")', b'ax.set_yscale("log")'),
    ("model-label", b'ax.set_xlabel("x")', b'ax.set_xlabel("model x")'),
    ("trailing-space", b"import matplotlib\n", b"import matplotlib \n"),
    ("quote-drift", b'matplotlib.use("Agg")', b"matplotlib.use('Agg')"),
)


@pytest.mark.parametrize("_name,old,new", _MUTATIONS, ids=[case[0] for case in _MUTATIONS])
def test_static_allowlist_rejects_forbidden_or_data_mutated_source(
    _name: str,
    old: bytes,
    new: bytes,
) -> None:
    mutated = _F02_LINE_GOLDEN.replace(old, new, 1)
    assert mutated != _F02_LINE_GOLDEN
    with pytest.raises(AssertionError):
        _assert_closed_script(
            mutated,
            mark="line",
            x_values=tuple(float(index) for index in range(11)),
            y_values=tuple(float(2 * index + 1) for index in range(11)),
            x_start=0.0,
            x_stop=10.0,
        )


def test_nonpalindromic_points_domain_and_fixed_structure_are_exact() -> None:
    artifact = _artifact(_spec("3*x+7", bounds=("2.5", "7.5"), samples=3, x_scale=1, y_scale=1))
    _assert_closed_script(
        artifact.matplotlib_script,
        mark="line",
        x_values=(2.5, 5.0, 7.5),
        y_values=(14.5, 22.0, 29.5),
        x_start=2.5,
        x_stop=7.5,
    )

    other = _artifact(_spec("x*x", bounds=("2.5", "7.5"), samples=3, x_scale=1, y_scale=1))
    assert _fixed_structure(artifact.matplotlib_script) == _fixed_structure(other.matplotlib_script)


def test_equivalent_tables_ignore_formula_source_spec_hash_paths_and_urls() -> None:
    left = _prepare(_spec("x-x", bounds=("0", "2"), samples=3))
    right = _prepare(_spec("0*x", bounds=("0", "2"), samples=3))
    left_artifact = matplotlib_script.emit_matplotlib_script(left).artifact
    right_artifact = matplotlib_script.emit_matplotlib_script(right).artifact
    assert left_artifact is not None
    assert right_artifact is not None
    assert left.spec.formula != right.spec.formula
    assert left.evidence.formula_source.ast != right.evidence.formula_source.ast
    assert left.evidence.spec_hash != right.evidence.spec_hash
    assert left_artifact.matplotlib_script == right_artifact.matplotlib_script
    assert left_artifact.matplotlib_script_hash == right_artifact.matplotlib_script_hash
    for forbidden in (
        left.spec.formula,
        right.spec.formula,
        left.evidence.formula_source.ast,
        right.evidence.formula_source.ast,
        left.evidence.spec_hash,
        right.evidence.spec_hash,
        "/model.py",
        "https://example.test",
    ):
        assert forbidden.encode() not in left_artifact.matplotlib_script

    leading_zero = _artifact(_spec("007.500", y_scale=3))
    assert b"007.500" not in leading_zero.matplotlib_script
    assert b"y = [7.5, 7.5]" in leading_zero.matplotlib_script


@pytest.mark.parametrize(
    ("value", "scale", "literal"),
    (
        (Decimal(0), 0, "0.0"),
        (Decimal("-0"), 0, "0.0"),
        (Decimal("0.1"), 1, "0.1"),
        (Decimal("-0.75"), 2, "-0.75"),
        (Decimal(1), 0, "1.0"),
        (Decimal(100000000000000000000), 0, "1e+20"),
        (Decimal("0.000000000001"), 12, "1e-12"),
    ),
)
def test_float_literal_is_shortest_roundtripping_and_canonicalizes_zero(
    value: Decimal,
    scale: int,
    literal: str,
) -> None:
    projected, emitted = matplotlib_script._float_literal(value, scale, "test")
    assert emitted == literal == repr(projected)
    assert float(emitted) == projected
    assert math.copysign(1.0, projected) == 1.0 if projected == 0.0 else True


def test_public_negative_x_canonicalizes_evaluator_zero_before_emission() -> None:
    artifact = _artifact(_spec("-x"))
    assert b"y = [0.0, -1.0]" in artifact.matplotlib_script
    assert b"-0.0" not in artifact.matplotlib_script


@pytest.mark.parametrize(
    ("formula", "literal"),
    (("0.000000000001", "1e-12"), ("-0.000000000001", "-1e-12")),
)
def test_public_scale_twelve_smallest_nonzero_quantum_passes_as_normal_float(
    formula: str,
    literal: str,
) -> None:
    artifact = _artifact(_spec(formula, y_scale=12))
    assert f"y = [{literal}, {literal}]".encode() in artifact.matplotlib_script
    assert abs(float(literal)) > sys.float_info.min


def test_scale_twelve_loss_and_integer_nonroundtrip_fail_semantically() -> None:
    large_loss = _prepare(_spec("1000000.000000000001", y_scale=12))
    failure = _fidelity_failure(large_loss)
    assert failure.message == ("row 0 y does not survive float64 projection at declared scale 12")

    integer_loss = _prepare(_spec("9007199254740993"))
    failure = _fidelity_failure(integer_loss)
    assert failure.message == ("row 0 y does not survive float64 projection at declared scale 0")


def test_float64_fidelity_uses_declared_scale_not_decimal_exponent() -> None:
    prepared = _prepare(_spec("0"))
    exponent_scale_value = Decimal("0.1")
    forged = _forged_rows(
        prepared,
        (
            (Decimal(0), exponent_scale_value),
            (Decimal(1), exponent_scale_value),
        ),
    )
    assert exponent_scale_value.as_tuple().exponent == -1
    assert forged.evidence.formula_source.y_scale == 0
    failure = _fidelity_failure(forged)
    assert failure.message == "row 0 y does not survive float64 projection at declared scale 0"


def test_finite_power_of_two_control_passes_while_public_overflows_fail() -> None:
    finite = _artifact(_spec("(2**64)**15"))
    assert b"inf" not in finite.matplotlib_script.lower()
    y_value = float(Decimal(2**960))
    assert repr(y_value).encode() in finite.matplotlib_script

    for formula in ("(2**64)**16", "1000000000000000000**64", "99999**62"):
        prepared = _prepare(_spec(formula))
        failure = _fidelity_failure(prepared)
        assert failure.message == "row 0 y projects to non-finite float64"


def test_half_even_endpoint_tie_pair_distinguishes_even_and_odd_retained_digit() -> None:
    admitted = _artifact(
        _spec(
            "0",
            bounds=("562949953421312.2", "562949953421313.2"),
            x_scale=1,
        )
    )
    projected = float(Decimal("562949953421312.2"))
    assert Fraction.from_float(projected) == Fraction(2251799813685249, 4)
    assert _half_even_at_scale(Fraction.from_float(projected), 1) == Fraction(
        Decimal("562949953421312.2")
    )
    assert b"x = [562949953421312.2, 562949953421313.2]" in admitted.matplotlib_script

    refused = _prepare(
        _spec(
            "0",
            bounds=("562949953421312.3", "562949953421313.3"),
            x_scale=1,
        )
    )
    failure = _fidelity_failure(refused)
    assert failure.message == ("row 0 x does not survive float64 projection at declared scale 1")


def test_repr_trap_and_projected_x_collision_are_rejected_end_to_end() -> None:
    repr_trap = _prepare(_spec("0", bounds=("18014398509481990", "18014398509481996")))
    assert repr(float(Decimal(18014398509481990))) == "1.801439850948199e+16"
    assert Decimal(repr(float(Decimal(18014398509481990)))) == Decimal(18014398509481990)
    failure = _fidelity_failure(repr_trap)
    assert failure.message == ("row 0 x does not survive float64 projection at declared scale 0")

    collision = _prepare(
        _spec(
            "0",
            bounds=("18014398509481988", "18014398509481992"),
            samples=3,
        )
    )
    failure = _fidelity_failure(collision)
    assert failure.message == ("row 1 x does not survive float64 projection at declared scale 0")


def test_forged_projected_x_and_domain_defenses_fail_closed() -> None:
    prepared = _prepare(_spec("0", bounds=("0", "2"), samples=3))

    duplicate_x = _forged_rows(
        prepared,
        (
            (Decimal(0), Decimal(0)),
            (Decimal(1), Decimal(0)),
            (Decimal(1), Decimal(0)),
        ),
    )
    assert _fidelity_failure(duplicate_x).message == (
        "projected float64 x values are not strictly increasing between rows 1 and 2"
    )

    wrong_start = _forged_rows(
        prepared,
        ((Decimal(1), Decimal(0)), (Decimal(2), Decimal(0))),
    )
    assert _fidelity_failure(wrong_start).message == (
        "projected domain start does not match projected first x value"
    )

    wrong_stop = _forged_rows(
        prepared,
        ((Decimal(0), Decimal(0)), (Decimal(1), Decimal(0))),
    )
    assert _fidelity_failure(wrong_stop).message == (
        "projected domain stop does not match projected last x value"
    )


def test_forged_domain_endpoints_are_independently_scale_checked() -> None:
    left_base = _forged_rows(
        _prepare(_spec("0", bounds=("18014398509481992", "18014398509481996"))),
        (
            (Decimal(18014398509481992), Decimal(0)),
            (Decimal(18014398509481996), Decimal(0)),
        ),
    )
    bad_left = _forged_source(left_base, start=Decimal(18014398509481990))
    assert _fidelity_failure(bad_left).message == (
        "domain start does not survive float64 projection at declared scale 0"
    )

    right_base = _forged_rows(
        _prepare(_spec("0", bounds=("18014398509481988", "18014398509481992"))),
        (
            (Decimal(18014398509481988), Decimal(0)),
            (Decimal(18014398509481992), Decimal(0)),
        ),
    )
    bad_right = _forged_source(right_base, stop=Decimal(18014398509481990))
    assert _fidelity_failure(bad_right).message == (
        "domain stop does not survive float64 projection at declared scale 0"
    )


@pytest.mark.parametrize(
    ("formula", "y_scale", "message"),
    (
        (
            "9007199254740993",
            0,
            "row 0 y does not survive float64 projection at declared scale 0",
        ),
        ("(2**64)**16", 0, "row 0 y projects to non-finite float64"),
        (
            "1000000.000000000001",
            12,
            "row 0 y does not survive float64 projection at declared scale 12",
        ),
    ),
    ids=("integer-nonroundtrip", "nonfinite", "scale-12-loss"),
)
def test_fidelity_refusal_precedes_template_hash_and_success_results(
    formula: str,
    y_scale: int,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepare(_spec(formula, y_scale=y_scale))
    calls = {"render": 0, "hash": 0, "success": 0}

    def forbidden_render(
        _projection: matplotlib_script._Projection,
        _mark: FormulaMark,
    ) -> NoReturn:
        calls["render"] += 1
        raise AssertionError

    def forbidden_hash(_script: bytes) -> NoReturn:
        calls["hash"] += 1
        raise AssertionError

    def forbidden_success() -> NoReturn:
        calls["success"] += 1
        raise AssertionError

    monkeypatch.setattr(matplotlib_script, "_render_script", forbidden_render)
    monkeypatch.setattr(canon, "hash_matplotlib_script", forbidden_hash)
    monkeypatch.setattr(matplotlib_script, "_success_checks", forbidden_success)
    failure = _fidelity_failure(prepared)
    assert failure.message == message
    assert calls == {"render": 0, "hash": 0, "success": 0}


def test_projection_failures_stop_before_later_projection_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepare(_spec("0", bounds=("0", "2"), samples=3))
    duplicate_x = _forged_rows(
        prepared,
        (
            (Decimal(0), Decimal(0)),
            (Decimal(1), Decimal(0)),
            (Decimal(1), Decimal(0)),
        ),
    )
    original = matplotlib_script._float_literal
    labels: list[str] = []

    def recorded(value: Decimal, scale: int, label: str) -> tuple[float, str]:
        labels.append(label)
        return original(value, scale, label)

    monkeypatch.setattr(matplotlib_script, "_float_literal", recorded)
    _fidelity_failure(duplicate_x)
    assert labels == ["row 0 x", "row 1 x", "row 2 x"]

    labels.clear()
    wrong_start = _forged_rows(
        prepared,
        ((Decimal(1), Decimal(0)), (Decimal(2), Decimal(0))),
    )
    _fidelity_failure(wrong_start)
    assert labels == ["row 0 x", "row 1 x", "domain start", "domain stop"]


def test_script_byte_gate_is_inclusive_threaded_and_precedes_hash_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepare(decode_formula_spec((_GOOD_DIR / "f02_linear.json").read_bytes()))
    exact = msgspec.structs.replace(DEFAULT_LIMITS, max_matplotlib_script_bytes=483)
    admitted = matplotlib_script.emit_matplotlib_script(prepared, limits=exact)
    assert admitted.artifact is not None
    assert admitted.artifact.matplotlib_script == _F02_LINE_GOLDEN

    calls = {"hash": 0, "success": 0}

    def forbidden_hash(_script: bytes) -> NoReturn:
        calls["hash"] += 1
        raise AssertionError

    def forbidden_success() -> NoReturn:
        calls["success"] += 1
        raise AssertionError

    monkeypatch.setattr(canon, "hash_matplotlib_script", forbidden_hash)
    monkeypatch.setattr(matplotlib_script, "_success_checks", forbidden_success)
    too_small = msgspec.structs.replace(DEFAULT_LIMITS, max_matplotlib_script_bytes=482)
    with pytest.raises(VerificationError) as caught:
        matplotlib_script.emit_matplotlib_script(prepared, limits=too_small)
    assert caught.value.check == "resource.matplotlib_script_bytes"
    assert str(caught.value) == "matplotlib script has 483 bytes; limit is 482"
    assert calls == {"hash": 0, "success": 0}


def test_hash_receives_exact_returned_bytes_once_and_domain_binds_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepare(_spec("0"))
    captured: list[bytes] = []
    sentinel = "sha256:" + "ab" * 32
    original_hash = canon.hash_matplotlib_script

    def recording_hash(script: bytes) -> str:
        captured.append(script)
        return sentinel

    monkeypatch.setattr(canon, "hash_matplotlib_script", recording_hash)
    run = matplotlib_script.emit_matplotlib_script(prepared)
    artifact = run.artifact
    assert artifact is not None
    assert captured == [artifact.matplotlib_script]
    assert captured[0] is artifact.matplotlib_script
    assert artifact.matplotlib_script_hash == sentinel

    script = _F02_LINE_GOLDEN
    tag = f"vplot-matplotlib-script/{canon.CANON_VERSION}\n".encode()
    expected = "sha256:" + hashlib.sha256(tag + script).hexdigest()
    assert original_hash(script) == expected
    mutated = script.replace(b'ax.set_xlabel("x")', b'ax.set_xlabel("X")', 1)
    assert len(mutated) == len(script)
    assert original_hash(mutated) != expected


def test_repeated_context_locale_and_hashseed_emission_is_byte_deterministic() -> None:
    prepared = _prepare(decode_formula_spec((_GOOD_DIR / "f02_linear.json").read_bytes()))
    first = matplotlib_script.emit_matplotlib_script(prepared).artifact
    second = matplotlib_script.emit_matplotlib_script(prepared).artifact
    assert first is not None
    assert second is not None
    assert first.matplotlib_script == second.matplotlib_script
    assert first.matplotlib_script_hash == second.matplotlib_script_hash

    with localcontext() as context:
        context.prec = 1
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        hostile = matplotlib_script.emit_matplotlib_script(prepared).artifact
    assert hostile is not None
    assert hostile.matplotlib_script == first.matplotlib_script
    assert hostile.matplotlib_script_hash == first.matplotlib_script_hash

    outputs: set[str] = set()
    for seed, locale in (("0", "C"), ("1", "C.UTF-8"), ("42", "C")):
        environment = os.environ | {"PYTHONHASHSEED": seed, "LC_ALL": locale}
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", _DETERMINISM_PROGRAM],
            cwd=_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stderr == ""
        outputs.add(completed.stdout)
    assert len(outputs) == 1
    assert outputs == {
        _F02_LINE_GOLDEN.hex()
        + "\nsha256:8861069e6a140ecd4bca9c8d85873477f9d50408f9f0c13ad350a7e640be7cd9\n"
    }


def test_joint_formula_and_script_boundaries_are_simultaneously_exact() -> None:
    script_bytes = len(_THREE_POINT_GOLDEN)
    assert script_bytes == 395
    limits = msgspec.structs.replace(
        DEFAULT_LIMITS,
        max_formula_samples=3,
        max_formula_work_units=18,
        max_plotted_cells=6,
        max_render_rows=3,
        max_smt_terms=55,
        max_matplotlib_script_bytes=script_bytes,
    )
    spec = _spec("x", bounds=("0", "2"), samples=3)

    def prepare_under(
        policy: VerificationLimits,
    ) -> tuple[
        checks.FormulaVerificationRun,
        formula_prepare.FormulaPreparationRun,
        PreparedFormula,
    ]:
        core = checks.verify_formula_run(spec, limits=policy)
        assert core.report.passed
        assert core.trace.formula_work_units == 18
        evidence = core.require_evidence()
        assert len(evidence.plotted_table.rows) == 3
        preparation = formula_prepare.prepare_formula(spec, evidence, limits=policy)
        assert preparation.report.passed
        assert preparation.formal_trace[0].term_count == 55
        prepared = preparation.prepared
        assert prepared is not None
        return core, preparation, prepared

    _core, _preparation, prepared = prepare_under(limits)
    admitted = matplotlib_script.emit_matplotlib_script(prepared, limits=limits)
    assert admitted.artifact is not None
    assert admitted.artifact.matplotlib_script == _THREE_POINT_GOLDEN

    too_small = msgspec.structs.replace(limits, max_matplotlib_script_bytes=script_bytes - 1)
    small_core, small_preparation, small_prepared = prepare_under(too_small)
    assert small_core.report.passed
    assert small_preparation.report.passed
    with pytest.raises(VerificationError) as caught:
        matplotlib_script.emit_matplotlib_script(small_prepared, limits=too_small)
    assert caught.value.check == "resource.matplotlib_script_bytes"
    assert str(caught.value) == "matplotlib script has 395 bytes; limit is 394"


def test_mark_dispatch_allowlist_is_exact_and_immutable() -> None:
    assert set(matplotlib_script._MARK_CALLS) == {"line", "scatter"}
    with pytest.raises(TypeError):
        cast("dict[str, str]", matplotlib_script._MARK_CALLS)["line"] = "changed"


@pytest.mark.parametrize("mark", ("bar", "plot", "__class__", "__getattribute__"))
def test_mark_dispatch_rejects_direct_near_miss_before_template_hash_or_results(
    mark: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepare(_spec("0"))
    invalid_spec = msgspec.structs.replace(prepared.spec, mark=cast("FormulaMark", mark))
    invalid = replace(prepared, spec=invalid_spec)
    calls = {"template": 0, "hash": 0, "success": 0}

    class ForbiddenTemplate:
        def format(self, **_kwargs: object) -> NoReturn:
            calls["template"] += 1
            raise AssertionError

    def forbidden_hash(_script: bytes) -> NoReturn:
        calls["hash"] += 1
        raise AssertionError

    def forbidden_success() -> NoReturn:
        calls["success"] += 1
        raise AssertionError

    monkeypatch.setattr(matplotlib_script, "_TEMPLATE", ForbiddenTemplate())
    monkeypatch.setattr(canon, "hash_matplotlib_script", forbidden_hash)
    monkeypatch.setattr(matplotlib_script, "_success_checks", forbidden_success)
    with pytest.raises(KeyError) as caught:
        matplotlib_script.emit_matplotlib_script(invalid)
    assert caught.value.args == (mark,)
    assert calls == {"template": 0, "hash": 0, "success": 0}


def test_bad_formula_corpus_never_produces_emitter_input_or_artifact() -> None:
    blocked = 0
    for entry in _BAD:
        raw = (_BAD_DIR / entry["file"]).read_bytes()
        if not entry["decodes"]:
            with pytest.raises(msgspec.ValidationError):
                decode_formula_spec(raw)
            blocked += 1
            continue
        spec = decode_formula_spec(raw)
        core = checks.verify_formula_run(spec)
        if core.evidence is None:
            assert not core.report.passed
            blocked += 1
            continue
        preparation = formula_prepare.prepare_formula(spec, core.evidence)
        assert preparation.prepared is None
        assert not preparation.report.passed
        blocked += 1
    assert blocked == len(_BAD)
