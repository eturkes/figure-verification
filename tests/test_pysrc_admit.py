# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""A1-A12 over `verifier.pysrc.admit`.

Contract: `.agent/contracts/m13u2.md`.

This module IS the pass/fail boundary, so the suite is written against the ALLOWLIST property
rather than against a sample of bad programs: every admitted family gets a NEAR-MISS witness
(`np.linspaces`, `plt.plott`, `import numpy as onp`), because a denylist and an allowlist agree on
every input anyone thought of and diverge only on the ones nobody did.

The admitted maps are pinned as hand-written literals. A test that reads `ADMITTED_CALL_TARGETS` to
build its expectation would ratify whatever the module happens to contain.
"""

import ast
from pathlib import Path
from typing import get_args

import pytest

from verifier.pysrc import admit as admit_module
from verifier.pysrc.admit import (
    ADMITTED_CALL_TARGETS,
    ADMITTED_CONSTANT_ATTRS,
    ADMITTED_IMPORTS,
    ADMITTED_KEYWORDS,
    parse_admitted,
)
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS
from verifier.pysrc.prescan import prescan

_PRELUDE = "import numpy as np\nimport matplotlib.pyplot as plt\n"

# One fully-decorated program in the intended idiom, used as the positive control everywhere.
_SIMPLE = (
    _PRELUDE
    + """x = np.linspace(0, 2 * np.pi, num=200)
y = np.sin(x)
plt.plot(x, y, label="sin(x)")
plt.title("sin(x) over one period")
plt.xlabel("x")
plt.ylabel("sin(x)")
plt.legend()
plt.grid(True)
plt.show()
"""
)


def _code(text: str) -> RefusalCode:
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(text)
    return caught.value.code


def test_a1_unparsable_source_becomes_a_verdict() -> None:
    """A1: `ast.parse` failures are verdicts, never tracebacks.

    Acceptance: a program the PRE-SCAN admits but the parser rejects yields `source_not_parsable`
    with the `SyntaxError` retained as the cause. The `prescan` call is the reachability proof --
    without it this path could be unreachable in production and the test would still pass."""
    source = "x = = 1\n"
    assert prescan(source.encode(), DEFAULT_LIMITS) == source

    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    assert caught.value.code == "source_not_parsable"
    assert isinstance(caught.value.__cause__, SyntaxError)


def test_a2_the_intended_idiom_is_admitted() -> None:
    """A2: the allowlist admits what the demo's simple arm actually asks for."""
    tree = parse_admitted(_SIMPLE)
    assert isinstance(tree, ast.Module)
    assert len(tree.body) == 11


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # Expression classes the subset never names.
        ("x = [1, 2, 3]\n", "expression_not_admitted"),
        ("x = (1, 2)\n", "expression_not_admitted"),
        ("x = {1: 2}\n", "expression_not_admitted"),
        ("x = {1, 2}\n", "expression_not_admitted"),
        (_PRELUDE + "x = np.sin(1)[0]\n", "expression_not_admitted"),
        (_PRELUDE + "x = [np.sin(i) for i in np.arange(3)]\n", "expression_not_admitted"),
        ("x = lambda t: t\n", "expression_not_admitted"),
        ("x = f'{1}'\n", "expression_not_admitted"),
        ("x = 1 if 2 else 3\n", "expression_not_admitted"),
        ("x = 1 < 2\n", "expression_not_admitted"),
        ("x = 1 and 2\n", "expression_not_admitted"),
        (_PRELUDE + "plt.show(*[])\n", "expression_not_admitted"),
        # Statement classes the subset never names.
        ("for i in range(3):\n    pass\n", "statement_not_admitted"),
        ("while True:\n    pass\n", "statement_not_admitted"),
        ("def f():\n    pass\n", "statement_not_admitted"),
        ("class C:\n    pass\n", "statement_not_admitted"),
        ("if 1:\n    x = 1\n", "statement_not_admitted"),
        ("try:\n    x = 1\nexcept Exception:\n    pass\n", "statement_not_admitted"),
        ("with open('f') as f:\n    pass\n", "statement_not_admitted"),
        ("assert 1\n", "statement_not_admitted"),
        ("raise SystemExit\n", "statement_not_admitted"),
        ("del x\n", "statement_not_admitted"),
        ("x: int = 1\n", "statement_not_admitted"),
        ("x = 1\nx += 1\n", "statement_not_admitted"),
        ("from numpy import sin\n", "statement_not_admitted"),
        ("pass\n", "statement_not_admitted"),
        ("global x\n", "statement_not_admitted"),
        # A bare expression statement that is not a call.
        ('"""A module docstring."""\n', "statement_not_admitted"),
        ("x = 1\nx\n", "statement_not_admitted"),
    ],
)
def test_a2_admission_is_positive_not_a_denylist(source: str, expected: RefusalCode) -> None:
    """A2: a node type absent from the allowlist refuses.

    Acceptance: every construct here is refused by the CLOSED TAIL rather than by a rule naming it,
    which is the property a denylist cannot have."""
    assert _code(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import numpy\n", "import_not_admitted"),
        ("import numpy as onp\n", "import_not_admitted"),
        ("import matplotlib.pyplot\n", "import_not_admitted"),
        ("import matplotlib.pyplot as pyplot\n", "import_not_admitted"),
        ("import matplotlib\n", "import_not_admitted"),
        ("import os\n", "import_not_admitted"),
        ("import numpy as np, os\n", "import_not_admitted"),
        ("from numpy import sin\n", "statement_not_admitted"),
        ("from numpy import *\n", "statement_not_admitted"),
    ],
)
def test_a3_the_import_set_is_exact(source: str, expected: RefusalCode) -> None:
    """A3: two modules, two fixed aliases, nothing else.

    Acceptance: the alias is REQUIRED, so `import numpy` refuses as loudly as `import os` -- every
    downstream target string is `<alias>.<attr>`, and a free alias would make the allowlist depend
    on model-chosen text."""
    assert _code(source) == expected


def test_a3_both_admitted_imports_bind_their_alias() -> None:
    """A3: the import is what binds the alias for later use."""
    parse_admitted("import numpy as np\nx = np.pi\n")
    parse_admitted("import matplotlib.pyplot as plt\nplt.show()\n")
    # Both aliases in one statement: the loop over `node.names` must bind each.
    parse_admitted("import numpy as np, matplotlib.pyplot as plt\nplt.plot(np.pi)\n")


@pytest.mark.parametrize(
    "call",
    [
        "np.linspaces(0, 1)",
        "np.sinh(1)",
        "np.mean(1)",
        "np.array(1)",
        "np.zeros(1)",
        "plt.plott(1)",
        "plt.plot3D(1)",
        "plt.hist(1)",
        "plt.imshow(1)",
        "plt.savefig('x')",
        "plt.style(1)",
        "np.log10(1)",
        "np.power(1, 2)",
    ],
)
def test_a4_call_targets_are_a_closed_set(call: str) -> None:
    """A4: a near-miss of every admitted family refuses.

    Acceptance: the witnesses differ from an admitted target by one character, one suffix or one
    sibling name -- exactly the inputs on which an allowlist and a denylist disagree."""
    assert _code(_PRELUDE + call + "\n") == "call_target_not_admitted"


@pytest.mark.parametrize("call", ["plt.subplots(2, 2)", "plt.subplots()", "plt.subplot(1, 1, 1)"])
def test_a5_multi_axes_forms_refuse_by_construction(call: str) -> None:
    """A5: `plt.subplots` refuses because the projection targets exactly ONE chart.

    Acceptance: the code is `call_target_not_admitted`, the same code every unlisted target gets --
    a dedicated `multi_panel` code would mean a named ban, and a named ban is a denylist entry that
    the next unnamed multi-Axes idiom would walk straight past."""
    assert _code(_PRELUDE + call + "\n") == "call_target_not_admitted"


def test_a5_subplots_is_absent_from_the_allowlist() -> None:
    """A5: the refusal is structural. Acceptance: no `subplot`-shaped target is listed at all."""
    assert not [t for t in ADMITTED_CALL_TARGETS if "subplot" in t]


def test_a6_admitted_keywords_pass() -> None:
    """A6: each admitted keyword is reachable on its own target."""
    parse_admitted(_PRELUDE + "x = np.linspace(0, 1, num=10)\n")
    parse_admitted(_PRELUDE + "plt.plot(1, 2, label='a')\n")
    parse_admitted(_PRELUDE + "plt.scatter(1, 2, label='a')\n")
    parse_admitted(_PRELUDE + "plt.bar(1, 2, label='a')\n")


@pytest.mark.parametrize(
    "call",
    [
        # Unknown everywhere.
        "plt.plot(1, color='r')",
        "plt.plot(1, linewidth=2)",
        "plt.plot(1, cmap='viridis')",
        "np.linspace(0, 1, endpoint=False)",
        "plt.show(block=True)",
        "plt.grid(axis='x')",
        # Admitted on ANOTHER target: the per-target closure is the predicate.
        "plt.plot(1, num=5)",
        "np.linspace(0, 1, label='a')",
        # No statically known keyword set at all.
        "plt.legend(**{})",
    ],
)
def test_a6_keywords_are_closed_per_target(call: str) -> None:
    """A6: a keyword admitted on one target is not thereby admitted on another.

    Acceptance: `num` passes on `np.linspace` and refuses on `plt.plot`, so a defect collapsing the
    per-target map into one shared keyword set is caught."""
    assert _code(_PRELUDE + call + "\n") == "keyword_not_admitted"


def test_a6_the_keyword_map_is_total_over_the_target_set() -> None:
    """A6: every admitted target has a keyword entry.

    Acceptance: exact set equality. The lookup is unguarded, so a target added to the call set
    without a keyword entry would raise `KeyError` -- a crash, not a verdict -- on first use."""
    assert set(ADMITTED_KEYWORDS) == set(ADMITTED_CALL_TARGETS)


@pytest.mark.parametrize(
    "source",
    [
        "import matplotlib.pyplot as plt\nplt.plot(x)\n",
        "import numpy as np\nx = y + 1\n",
        "import numpy as np\nx = x + 1\n",
        "np.sin(1)\n",
        "plt.show()\n",
        "x = np.pi\n",
    ],
)
def test_a7_every_name_is_bound_before_use(source: str) -> None:
    """A7: a free name refuses, and binding order is respected.

    Acceptance: `x = x + 1` refuses -- the right-hand side is admitted BEFORE the target is bound,
    so a defect binding first would admit a program that reads an undefined name."""
    assert _code(source) == "name_not_bound"


def test_a7_assignment_binds_for_later_statements() -> None:
    """A7: a bound name is admitted afterwards, so the check is order-sensitive, not a ban."""
    parse_admitted(_PRELUDE + "x = 1\ny = x + 1\nplt.plot(x, y)\n")


@pytest.mark.parametrize(
    "source",
    [
        _PRELUDE + "x = np.random.rand(3)\n",
        _PRELUDE + "x = np.linalg.norm(1)\n",
        _PRELUDE + "plt.axes.Axes(1)\n",
        _PRELUDE + "x = np.ma.masked\n",
    ],
)
def test_a8_attribute_depth_is_bounded(source: str) -> None:
    """A8: `np.random.rand` refuses on CHAIN DEPTH, not on the leaf name.

    Acceptance: the code is `attribute_not_admitted` rather than `call_target_not_admitted`,
    pinning that the depth-1 bound fires before any name lookup -- otherwise adding one leaf to the
    allowlist could admit a whole submodule."""
    assert _code(source) == "attribute_not_admitted"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (_PRELUDE + "x = np.__class__\n", "attribute_not_admitted"),
        (_PRELUDE + "np.__class__()\n", "attribute_not_admitted"),
        (_PRELUDE + "x = np._core\n", "attribute_not_admitted"),
        ("_x = 1\n", "assign_target_not_admitted"),
        ("__builtins__ = 1\n", "assign_target_not_admitted"),
    ],
)
def test_a9_dunder_and_private_names_refuse(source: str, expected: RefusalCode) -> None:
    """A9: the underscore convention is enforced on both attributes and assignment targets.

    Acceptance: dunder ATTRIBUTE access is the standard escape from an attribute allowlist, so it
    is refused by shape rather than by listing the dunders that exist today."""
    assert _code(source) == expected


@pytest.mark.skip(reason="A10: needs the re-authored math corpus (M13.5); red until it exists")
def test_a10_the_admitted_set_round_trips_the_design_corpus() -> None:
    """A10: every simple-arm design program admits and sampled complicated ones refuse.

    Acceptance: run over `corpus/python/` after M13.5 re-authors it against math prompts. Recorded
    now so the suite is not silently narrowed when the corpus lands."""
    raise NotImplementedError


def test_a11_refusal_carries_no_source_bytes() -> None:
    """A11: as M13.1 P10, extended to the admission vocabulary.

    Acceptance: a distinctive marker in the source appears nowhere in the exception, so
    model-authored text cannot ride an admission verdict into a log."""
    marker = "S3CR3T_MARKER_TEXT"
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(f"import {marker}\n")
    assert caught.value.code == "import_not_admitted"
    assert str(caught.value) == "import_not_admitted"
    assert marker not in str(caught.value)
    assert marker not in repr(caught.value)


def test_a11_every_admission_refusal_code_is_reachable() -> None:
    """A11: the admission half of the closed vocabulary has no dead member."""
    observed = {
        _code("x = = 1\n"),
        _code("pass\n"),
        _code("x = [1]\n"),
        _code("import os\n"),
        _code("a = b = 1\n"),
        _code(_PRELUDE + "plt.hist(1)\n"),
        _code(_PRELUDE + "plt.show(block=True)\n"),
        _code(_PRELUDE + "x = np.random.rand(1)\n"),
        _code("x = 1 % 2\n"),
        _code("x = None\n"),
        _code("x = y\n"),
    }
    assert observed == {
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
    }


def test_a11_the_refusal_vocabulary_is_exactly_its_two_halves() -> None:
    """A11: `RefusalCode` is the union of the pre-scan and admission sets and nothing more.

    Acceptance: exact set equality against hand-stated literals. Widening an enum in a language
    without exhaustiveness checking leaves every consumer green, so a code added with no witness is
    caught here rather than by whichever total map forgets it first."""
    prescan_codes = {
        "source_too_large",
        "source_not_utf8",
        "source_has_nul",
        "line_too_long",
        "source_not_tokenizable",
        "too_many_tokens",
        "nesting_too_deep",
        "unbalanced_brackets",
        "indent_too_deep",
    }
    admit_codes = {
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
    }
    assert set(get_args(RefusalCode)) == prescan_codes | admit_codes
    assert not (prescan_codes & admit_codes)


def test_a12_admission_never_evaluates() -> None:
    """A12: the module parses and inspects; it never calls into the interpreter.

    Acceptance: an AST walk over the committed module source, not a grep -- the module docstring
    names these builtins on purpose, and a textual search would either trip on the prose or be
    weakened to avoid it."""
    tree = ast.parse(Path(admit_module.__file__).read_text(encoding="utf-8"))
    banned = {"eval", "exec", "compile", "getattr", "setattr", "globals", "locals", "__import__"}
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    assert not (referenced & banned)


@pytest.mark.parametrize(
    "expression",
    ["1 + 2", "1 - 2", "1 * 2", "1 / 2", "1 ** 2", "-1", "-np.pi", "2 * np.pi * 3", "np.e ** 2"],
)
def test_operators_and_constants_in_the_admitted_set(expression: str) -> None:
    """The admitted arithmetic closes over the formulas the simple arm needs."""
    parse_admitted(_PRELUDE + f"x = {expression}\n")


@pytest.mark.parametrize(
    "expression", ["1 % 2", "1 // 2", "1 @ 2", "1 ^ 2", "1 | 2", "1 & 2", "1 << 2", "+1", "~1"]
)
def test_operators_outside_the_admitted_set_refuse(expression: str) -> None:
    """Near-misses of the admitted operator classes: the same node type, an unlisted operator."""
    assert _code(f"x = {expression}\n") == "operator_not_admitted"


def test_not_is_refused_as_an_operator() -> None:
    """`not x` is a `UnaryOp`, so it reaches the operator check rather than the expression tail."""
    assert _code("x = 1\ny = not x\n") == "operator_not_admitted"


@pytest.mark.parametrize("literal", ["1", "1.5", "'text'", "True", "False"])
def test_admitted_literal_kinds(literal: str) -> None:
    parse_admitted(f"x = {literal}\n")


@pytest.mark.parametrize("literal", ["None", "1j", "b'bytes'", "..."])
def test_literals_outside_the_admitted_set_refuse(literal: str) -> None:
    assert _code(f"x = {literal}\n") == "literal_not_admitted"


def test_the_literal_set_is_an_exact_type_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Narrowing the literal set must actually narrow admission.

    Acceptance: with `bool` withdrawn, `True` refuses while `1` still passes. `bool` subclasses
    `int`, so an `isinstance` membership test agrees with the exact-type test on every input while
    `bool` is listed and silently keeps admitting `True` once it is not -- the mutant survives every
    other test in this file, and this is the one that kills it."""
    monkeypatch.setattr(admit_module, "_ADMITTED_LITERAL_TYPES", (int, float, str))
    assert _code("x = True\n") == "literal_not_admitted"
    parse_admitted("x = 1\n")


@pytest.mark.parametrize("attribute", ["np.pi", "np.e"])
def test_admitted_constant_attributes(attribute: str) -> None:
    parse_admitted(_PRELUDE + f"x = {attribute}\n")


@pytest.mark.parametrize("attribute", ["np.inf", "np.nan", "np.newaxis", "plt.rcParams"])
def test_constant_attributes_outside_the_admitted_set_refuse(attribute: str) -> None:
    """Near-misses of `np.pi`: a bare attribute read on an admitted alias, unlisted leaf."""
    assert _code(_PRELUDE + f"x = {attribute}\n") == "attribute_not_admitted"


@pytest.mark.parametrize(
    "source", ["a = b = 1\n", "a, b = 1, 2\n", "[a, b] = 1, 2\n", "x = 1\nx.y = 2\n"]
)
def test_assignment_targets_are_a_single_plain_name(source: str) -> None:
    assert _code(source) == "assign_target_not_admitted"


def test_a_call_whose_target_is_not_an_attribute_refuses() -> None:
    """A bare builtin call and a call on a call both miss the `<alias>.<attr>` shape."""
    assert _code("print('x')\n") == "call_target_not_admitted"
    assert _code(_PRELUDE + "plt.plot(1)(2)\n") == "call_target_not_admitted"


def test_arguments_are_admitted_recursively() -> None:
    """Refusal reaches inside a call: an admitted target does not launder its arguments."""
    assert _code(_PRELUDE + "plt.plot([1, 2])\n") == "expression_not_admitted"
    assert _code(_PRELUDE + "plt.plot(np.hstack(1))\n") == "call_target_not_admitted"
    assert _code(_PRELUDE + "np.linspace(0, 1, num=[3])\n") == "expression_not_admitted"
    assert _code(_PRELUDE + "x = np.sin(np.cos(undefined))\n") == "name_not_bound"


def test_the_empty_program_is_admitted() -> None:
    """Admission answers "may these bytes run"; demanding a chart is projection's predicate."""
    assert parse_admitted("").body == []


def test_the_admitted_maps_are_pinned_as_literals() -> None:
    """The subset itself is the deliverable, so its contents are stated here by hand.

    Acceptance: exact equality against literals. Widening the subset must fail this test and be
    ratified deliberately, which is the only thing standing between a calibration nudge and a
    silently moved pass/fail boundary."""
    expected_targets = frozenset(
        {
            "np.linspace",
            "np.arange",
            "np.sin",
            "np.cos",
            "np.tan",
            "np.exp",
            "np.log",
            "np.sqrt",
            "np.abs",
            "plt.plot",
            "plt.scatter",
            "plt.bar",
            "plt.title",
            "plt.xlabel",
            "plt.ylabel",
            "plt.legend",
            "plt.grid",
            "plt.show",
        }
    )
    expected_attrs = frozenset({"np.pi", "np.e"})
    assert ADMITTED_IMPORTS == {"matplotlib.pyplot": "plt", "numpy": "np"}
    assert expected_attrs == ADMITTED_CONSTANT_ATTRS
    assert expected_targets == ADMITTED_CALL_TARGETS
    assert {t: sorted(k) for t, k in ADMITTED_KEYWORDS.items() if k} == {
        "np.linspace": ["num"],
        "plt.plot": ["label"],
        "plt.scatter": ["label"],
        "plt.bar": ["label"],
    }
