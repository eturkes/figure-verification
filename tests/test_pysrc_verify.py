# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Public entry, verdict, plotted table, work + limits — E, T, W of the M13.5 contract,
`.agent/archive/contracts/m13u5.md`.

`verify_python_source` is the only public entry and the only thing M10 consumes. It is PURE: the
CSV arrives as bytes on `declared_target`, and the core never opens a path, reads a clock or draws
a random number.

Each test's docstring carries its predicate's acceptance check.
"""

import ast
import builtins
import hashlib
import inspect
import math
import os
import random
import secrets
import socket
import struct
import time
from collections.abc import Callable, Iterator
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any, NoReturn, cast, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

import verifier
from verifier import pysrc
from verifier.pysrc import spec
from verifier.pysrc.errors import PysrcCallerError
from verifier.pysrc.limits import DEFAULT_LIMITS

_FORMULA_SOURCE = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.linspace(-1, 1, num=3)\n"
    "y = np.abs(x) + 0.2\n"
    "plt.plot(x, y)\n"
    "plt.show()\n"
)
_DATASET_SOURCE = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    'df = pd.read_csv("measurements.csv")\n'
    'plt.bar(df["site"], df["value"])\n'
    "plt.show()\n"
)
_DATASET_BYTES = b"site,value\nwest,3.25\neast,1\ncentral,2.5\n"


def _walk_values(value: object) -> Iterator[object]:
    yield value
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(cast(Any, value)):
            yield from _walk_values(getattr(value, item.name))
    elif isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            yield from _walk_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)


def _float_bits(values: tuple[float, ...]) -> tuple[bytes, ...]:
    return tuple(struct.pack("<d", value) for value in values)


def _binary_source(parts: tuple[str, str, str]) -> str:
    left, operator, right = parts
    return f"(({left}) {operator} ({right}))"


def _function_source(parts: tuple[str, str]) -> str:
    function, argument = parts
    return f"np.{function}({argument})"


def _extend_source(children: SearchStrategy[str]) -> SearchStrategy[str]:
    return st.one_of(
        st.tuples(children, st.sampled_from(("+", "-", "*", "/", "**")), children).map(
            _binary_source
        ),
        st.tuples(
            st.sampled_from(("sin", "cos", "tan", "exp", "log", "sqrt", "abs")), children
        ).map(_function_source),
        children.map(lambda child: f"(-({child}))"),
    )


_EXPR_SOURCES: SearchStrategy[str] = st.recursive(
    st.sampled_from(("x", "0", "1", "-1", "0.2", "np.pi", "np.e")),
    _extend_source,
    max_leaves=7,
)


def _raise_bomb(message: str) -> NoReturn:
    raise AssertionError(message)


class _BombEnvironment:
    def __getitem__(self, _key: object) -> NoReturn:
        _raise_bomb("environment read")

    def __iter__(self) -> NoReturn:
        _raise_bomb("environment read")

    def __contains__(self, _key: object) -> NoReturn:
        _raise_bomb("environment read")

    def get(self, _key: object, _default: object = None) -> NoReturn:
        _raise_bomb("environment read")


# --- E: entry and verdict ---------------------------------------------------------------------


def test_e1_single_public_entry() -> None:
    """`verify_python_source(source, *, declared_target=None, limits=DEFAULT_LIMITS) -> Verdict`.

    Accept: importable from `verifier.pysrc` alone; `Verdict = Verified | Refused`; `__all__`
    pinned as an exact hand-stated set.
    """
    from verifier.pysrc import (  # noqa: PLC0415
        Refused,
        Verdict,
        Verified,
        verify_python_source,
    )

    assert set(pysrc.__all__) == {"verify_python_source", "Verdict", "Verified", "Refused"}
    assert get_args(Verdict.__value__) == (Verified, Refused)
    assert set(Verified.__dataclass_fields__) == {"spec", "table", "certificate"}
    assert set(Refused.__dataclass_fields__) == {"code"}

    parameters = inspect.signature(verify_python_source).parameters
    assert tuple(parameters) == ("source", "declared_target", "limits")
    assert parameters["source"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["source"].default is inspect.Parameter.empty
    assert parameters["declared_target"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["declared_target"].default is None
    assert parameters["limits"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["limits"].default is DEFAULT_LIMITS


def test_e2_refusal_returned_caller_error_raised() -> None:
    """A refusal is a VALUE; a misconfiguration is an exception.

    Accept: an admitted-but-unprojectable program returns `Refused` with a closed code; a
    `PysrcLimits` carrying a zero field raises `PysrcCallerError` out of the entry.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415

    result = verify_python_source("import matplotlib.pyplot as plt\nplt.show()\n")
    assert isinstance(result, Refused)
    assert result.code == "no_mark"

    invalid_limits = replace(DEFAULT_LIMITS, max_csv_bytes=0)
    with pytest.raises(PysrcCallerError, match=r"^limit max_csv_bytes must be >= 1$"):
        verify_python_source("", limits=invalid_limits)


def test_e3_stage_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """prescan -> admit -> project -> bind -> recompute -> integrity -> certify, and no stage
    runs after an earlier one refuses.

    Accept: call-counting bombs on the downstream work, one per refusal reason, per
    `assurance.md` ORDERING law -- never outcome assertions.
    """
    from verifier.pysrc import verify as verify_module  # noqa: PLC0415
    from verifier.pysrc import verify_python_source  # noqa: PLC0415

    def assert_downstream_unreached(seam: str, invoke: Callable[[], object]) -> None:
        calls = 0

        def bomb(*_args: object, **_kwargs: object) -> NoReturn:
            nonlocal calls
            calls += 1
            _raise_bomb(f"downstream stage {seam} ran")

        with monkeypatch.context() as patch:
            patch.setattr(verify_module, seam, bomb)
            invoke()
        assert calls == 0

    assert_downstream_unreached(
        "parse_admitted",
        lambda: verify_python_source("xx", limits=replace(DEFAULT_LIMITS, max_source_bytes=1)),
    )
    assert_downstream_unreached("project", lambda: verify_python_source("pass\n"))
    assert_downstream_unreached(
        "bind_target",
        lambda: verify_python_source("import matplotlib.pyplot as plt\nplt.show()\n"),
    )
    assert_downstream_unreached("recompute", lambda: verify_python_source(_DATASET_SOURCE))
    assert_downstream_unreached(
        "check_integrity",
        lambda: verify_python_source(
            _DATASET_SOURCE,
            declared_target=spec.DatasetTarget(
                path="measurements.csv", content=b"\xef\xbb\xbfsite,value\nwest,1\n"
            ),
        ),
    )
    assert_downstream_unreached(
        "certify",
        lambda: verify_python_source(
            _DATASET_SOURCE,
            declared_target=spec.DatasetTarget(
                path="measurements.csv", content=b"site,value\nwest,1\nwest,2\n"
            ),
        ),
    )


def test_e4_verified_carries_no_source_bytes() -> None:
    """`Verified` holds `spec`, `table`, `certificate` and no model-authored byte beyond the
    certificate's `source_sha256`.

    Accept: `__dataclass_fields__` pinned as an exact set; a recursive scan of a verified result
    for a distinctive submitted identifier finds no occurrence.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    marker = "distinctive_submitted_identifier_7fc9c"
    source = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        f"{marker} = np.linspace(0, 1, num=3)\n"
        f"derived = np.sin({marker})\n"
        f"plt.plot({marker}, derived)\n"
        "plt.show()\n"
    )
    result = verify_python_source(source)

    assert isinstance(result, Verified)
    assert set(result.__dataclass_fields__) == {"spec", "table", "certificate"}
    assert not [
        value for value in _walk_values(result) if isinstance(value, str) and marker in value
    ]


def test_e5_entry_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No filesystem, network, clock, RNG or environment read anywhere in the core.

    Accept: the closed-import pin of `test_pysrc_project.py::test_p12_projection_is_pure` extends
    to every new module; with `open`, `socket` and `time` monkeypatched to raise, every predicate
    in this file still passes.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    def bomb(*_args: object, **_kwargs: object) -> NoReturn:
        _raise_bomb("ambient capability used")

    # The bombs cover globals pytest itself uses, so they must be withdrawn INSIDE the test body:
    # `os.environ` armed past the call phase kills pytest's own progress writer, which reads
    # `os.environ['COLUMNS']` through `shutil.get_terminal_size` between the call-phase report and
    # fixture teardown, and the resulting INTERNALERROR reports nothing about the code under test.
    with monkeypatch.context() as ambient:
        ambient.setattr(builtins, "open", bomb)
        ambient.setattr(socket, "socket", bomb)
        ambient.setattr(time, "time", bomb)
        ambient.setattr(time, "monotonic", bomb)
        ambient.setattr(random, "random", bomb)
        ambient.setattr(random, "randbytes", bomb)
        ambient.setattr(secrets, "token_bytes", bomb)
        ambient.setattr(os, "environ", _BombEnvironment())
        ambient.setattr(os, "getenv", bomb)

        formula = verify_python_source(_FORMULA_SOURCE)
        dataset = verify_python_source(
            _DATASET_SOURCE,
            declared_target=spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES),
        )

    assert isinstance(formula, Verified)
    assert isinstance(dataset, Verified)


@given(expression=_EXPR_SOURCES, samples=st.integers(min_value=2, max_value=9))
def test_e6_entry_is_total(expression: str, samples: int) -> None:
    """Every admitted program verifies or refuses with a closed code -- never raises, never
    returns a half-populated `Verified`.

    Accept: Hypothesis over generated admitted programs, plus a catch-all `except Exception` bomb
    asserting it never fires.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    source = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        f"x = np.linspace(-2, 2, num={samples})\n"
        f"y = {expression}\n"
        "plt.plot(x, y)\n"
        "plt.show()\n"
    )
    try:
        result = verify_python_source(source)
    except Exception as exc:  # pragma: no cover - the assertion is the catch-all bomb
        pytest.fail(f"entry raised {type(exc).__name__}: {exc}", pytrace=False)

    if isinstance(result, Verified):
        assert result.spec is not None
        assert result.table is not None
        assert result.certificate is not None
    else:
        assert isinstance(result, Refused)
        assert isinstance(result.code, str)
        assert result.code


# --- T: the plotted table ---------------------------------------------------------------------


def test_t1_table_shape_invariant() -> None:
    """`PlottedTable(x: tuple[CellValue, ...], y: tuple[float, ...])`, `len(x) == len(y)`.

    Accept: unequal lengths raise `PysrcCallerError` from `__post_init__`; `CellValue = float | str`
    pinned as an exact union.
    """
    from verifier.pysrc.table import CellValue, PlottedTable  # noqa: PLC0415

    assert get_args(CellValue.__value__) == (float, str)
    assert set(PlottedTable.__dataclass_fields__) == {"x", "y"}
    assert PlottedTable(x=(0.0, "one"), y=(1.0, 2.0)).x == (0.0, "one")
    with pytest.raises(PysrcCallerError):
        PlottedTable(x=(0.0,), y=(1.0, 2.0))


def test_t2_table_contents_per_arm() -> None:
    """Formula: grid and evaluated y in grid order. Dataset: the two selected columns in FILE
    order.

    Accept: round-trip witnesses in both arms, values compared as bit patterns.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    formula = verify_python_source(_FORMULA_SOURCE)
    assert isinstance(formula, Verified)
    assert _float_bits(cast(tuple[float, ...], formula.table.x)) == _float_bits((-1.0, 0.0, 1.0))
    assert _float_bits(formula.table.y) == _float_bits((1.2, 0.2, 1.2))

    dataset = verify_python_source(
        _DATASET_SOURCE,
        declared_target=spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES),
    )
    assert isinstance(dataset, Verified)
    assert dataset.table.x == ("west", "east", "central")
    assert _float_bits(dataset.table.y) == _float_bits((3.25, 1.0, 2.5))


def test_t3_canonical_encoding() -> None:
    """One canonical byte encoding: `%a` hex-float; UTF-8 strings prefixed by their unsigned
    64-bit big-endian byte length; no locale or `repr`. `table_sha256` digests exactly those bytes.

    Accept: two structurally equal tables built by different paths encode identically; a one-ulp
    change changes the digest; the prefix shape is fixed by § The remaining suite objections.
    """
    from verifier.pysrc.table import PlottedTable  # noqa: PLC0415

    label = "東京"
    first = PlottedTable(x=(1.5, label), y=(-0.0, 0.2))
    second = PlottedTable(x=(3.0 / 2.0, "".join(("東", "京"))), y=(-0.0, 1.0 / 5.0))
    encoded = first.canonical_bytes()

    assert encoded == second.canonical_bytes()
    assert encoded.startswith(b"pysrc-table-0.1\n")
    assert b"0x1.8000000000000p+0" in encoded
    assert b"-0x0.0p+0" in encoded
    assert b"0x1.999999999999ap-3" in encoded
    label_bytes = label.encode("utf-8")
    assert len(label_bytes).to_bytes(8, byteorder="big", signed=False) + label_bytes in encoded

    x_changed = PlottedTable(x=(math.nextafter(1.5, math.inf), label), y=first.y)
    y_changed = PlottedTable(x=first.x, y=(-0.0, math.nextafter(0.2, math.inf)))
    digest = hashlib.sha256(encoded).digest()
    assert hashlib.sha256(x_changed.canonical_bytes()).digest() != digest
    assert hashlib.sha256(y_changed.canonical_bytes()).digest() != digest


def test_t4_table_bounded_before_it_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """`max_table_rows` is checked BEFORE materialization, not after.

    Accept: a grid at `max_grid_samples + 1` refuses at projection; a CSV exceeding
    `max_table_rows` refuses `work_budget_exceeded` before any cell is converted -- proven by a
    bomb on the cell converter.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415

    grid_source = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "x = np.linspace(0, 1, num=4)\n"
        "y = np.sin(x)\n"
        "plt.plot(x, y)\n"
        "plt.show()\n"
    )
    grid_result = verify_python_source(
        grid_source, limits=replace(DEFAULT_LIMITS, max_grid_samples=3, max_table_rows=10)
    )
    assert isinstance(grid_result, Refused)
    assert grid_result.code == "grid_not_representable"

    def conversion_bomb(_text: str) -> NoReturn:
        _raise_bomb("cell converted before row cap")

    target = spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "float", conversion_bomb)
        csv_result = verify_python_source(
            _DATASET_SOURCE,
            declared_target=target,
            limits=replace(DEFAULT_LIMITS, max_csv_rows=10, max_table_rows=2),
        )
    assert isinstance(csv_result, Refused)
    assert csv_result.code == "work_budget_exceeded"


# --- W: work and limits -----------------------------------------------------------------------


def test_w1_meter_lives_in_the_core() -> None:
    """One meter, in `verifier.pysrc.budget`; the legacy JSON mode imports it from there.

    Accept: `verifier/work.py` absent; `verifier.expr` and `verifier.eval` import from the core;
    the core's closed-import pin still passes.
    """
    package_file = verifier.__file__
    package = Path(package_file).parent
    assert not (package / "work.py").exists()

    for module_name in ("expr.py", "eval.py"):
        tree = ast.parse((package / module_name).read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "verifier.pysrc.budget" in imported
        assert "verifier.work" not in imported

    budget_tree = ast.parse((package / "pysrc" / "budget.py").read_text(encoding="utf-8"))
    budget_roots = {
        node.module.partition(".")[0]
        for node in ast.walk(budget_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert budget_roots == {"dataclasses"}


def test_w2_tariff() -> None:
    """Formula = `samples * y_nodes + 2 * samples`; grid materialization has no node charge.
    Dataset = `sum(1 + len(cell) // 32)` at read time plus `2 * rows`; emitted cells stay flat.

    Accept: exact small-program totals plus 31-byte/32-byte cells differing by one unit. The
    threshold kills a dropped or changed divisor, and double-surcharging emitted cells also fails.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    # Two samples * three y-expression nodes + two table cells per sample = 10. Grid
    # materialization is untariffed; the million-valued exponent costs one node, not one million.
    formula_source = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "x = np.linspace(0, 1, num=2)\n"
        "y = x ** 1000000\n"
        "plt.plot(x, y)\n"
        "plt.show()\n"
    )
    formula_exact = verify_python_source(
        formula_source, limits=replace(DEFAULT_LIMITS, max_work=10)
    )
    formula_short = verify_python_source(formula_source, limits=replace(DEFAULT_LIMITS, max_work=9))
    assert isinstance(formula_exact, Verified)
    assert isinstance(formula_short, Refused)
    assert formula_short.code == "work_budget_exceeded"

    # Header + two rows at two columns = 6 cells read; 2 rows * 2 table cells = 4 more.
    dataset_bytes = b"site,value\na,1\nb,2\n"
    target = spec.DatasetTarget(path="measurements.csv", content=dataset_bytes)
    dataset_exact = verify_python_source(
        _DATASET_SOURCE,
        declared_target=target,
        limits=replace(DEFAULT_LIMITS, max_work=10),
    )
    dataset_short = verify_python_source(
        _DATASET_SOURCE,
        declared_target=target,
        limits=replace(DEFAULT_LIMITS, max_work=9),
    )
    assert isinstance(dataset_exact, Verified)
    assert isinstance(dataset_short, Refused)
    assert dataset_short.code == "work_budget_exceeded"

    # Headers + one row = four flat read units and two emitted cells. Crossing 31 -> 32 bytes adds
    # exactly one READ unit: totals 6 -> 7. A second emitted surcharge would make the latter 8.
    for width, exact_work in ((31, 6), (32, 7)):
        threshold_bytes = f"site,value\n{'a' * width},1\n".encode()
        threshold_target = spec.DatasetTarget(path="measurements.csv", content=threshold_bytes)
        threshold_exact = verify_python_source(
            _DATASET_SOURCE,
            declared_target=threshold_target,
            limits=replace(DEFAULT_LIMITS, max_work=exact_work),
        )
        threshold_short = verify_python_source(
            _DATASET_SOURCE,
            declared_target=threshold_target,
            limits=replace(DEFAULT_LIMITS, max_work=exact_work - 1),
        )
        assert isinstance(threshold_exact, Verified), width
        assert isinstance(threshold_short, Refused), width
        assert threshold_short.code == "work_budget_exceeded", width


def test_w3_atomic_pre_charge_survives_the_move() -> None:
    """A refused charge leaves consumption unchanged; consumption before it is retained.

    Accept: the existing meter tests move with the module and stay green.
    """
    from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError  # noqa: PLC0415

    budget = WorkBudget(limit=5)
    budget.charge(2)
    with pytest.raises(WorkBudgetExceededError) as caught:
        budget.charge(4)
    assert (caught.value.limit, caught.value.consumed, caught.value.required) == (5, 2, 4)
    assert budget.consumed == 2

    budget.charge(3)
    assert budget.consumed == 5


def test_w4_limits_field_set() -> None:
    """`PysrcLimits` has exactly 14 fields, each validated `>= 1`.

    Accept: the field set is a hand-stated literal; each cap has an isolated over-limit witness.
    Four CSV caps share `csv_too_large`; table rows, expression nodes, and work share
    `work_budget_exceeded`, per § The remaining suite objections.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415
    from verifier.pysrc.limits import PysrcLimits, validate_limits  # noqa: PLC0415

    field_names = {
        "max_source_bytes",
        "max_tokens",
        "max_bracket_depth",
        "max_indent_depth",
        "max_line_bytes",
        "min_grid_samples",
        "max_grid_samples",
        "max_csv_bytes",
        "max_csv_rows",
        "max_csv_columns",
        "max_csv_cell_bytes",
        "max_table_rows",
        "max_expr_nodes",
        "max_work",
    }
    assert {item.name for item in fields(PysrcLimits)} == field_names
    for field_name in field_names:
        with pytest.raises(PysrcCallerError, match=rf"^limit {field_name} must be >= 1$"):
            validate_limits(replace(DEFAULT_LIMITS, **{field_name: 0}))

    csv_bytes = b"site,value\nwest,1\neast,2\n"
    csv_target = spec.DatasetTarget(path="measurements.csv", content=csv_bytes)
    csv_caps = (
        ("max_csv_bytes", len(csv_bytes) - 1),
        ("max_csv_rows", 1),
        ("max_csv_columns", 1),
        ("max_csv_cell_bytes", 3),
    )
    for field_name, limit in csv_caps:
        result = verify_python_source(
            _DATASET_SOURCE,
            declared_target=csv_target,
            limits=replace(DEFAULT_LIMITS, **{field_name: limit}),
        )
        assert isinstance(result, Refused), field_name
        assert result.code == "csv_too_large", field_name

    table_cap = verify_python_source(
        _DATASET_SOURCE,
        declared_target=csv_target,
        limits=replace(DEFAULT_LIMITS, max_table_rows=1),
    )
    assert isinstance(table_cap, Refused)
    assert table_cap.code == "work_budget_exceeded"

    expression_source = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "x = np.linspace(0, 1, num=2)\n"
        "y = x ** 1000000\n"
        "plt.plot(x, y)\n"
        "plt.show()\n"
    )
    expression_cap = verify_python_source(
        expression_source, limits=replace(DEFAULT_LIMITS, max_expr_nodes=2)
    )
    work_cap = verify_python_source(expression_source, limits=replace(DEFAULT_LIMITS, max_work=9))
    assert isinstance(expression_cap, Refused)
    assert expression_cap.code == "work_budget_exceeded"
    assert isinstance(work_cap, Refused)
    assert work_cap.code == "work_budget_exceeded"

    joint = verify_python_source(
        _DATASET_SOURCE,
        declared_target=csv_target,
        limits=replace(DEFAULT_LIMITS, max_csv_rows=1, max_csv_columns=1),
    )
    assert isinstance(joint, Refused)
    assert joint.code == "csv_too_large"


def test_w5_max_work_default_is_measured() -> None:
    """`max_work`'s default comes from a measured evaluation rate, not a guess.

    Accept: a benchmark committed under `tools/`; the measured rate and the chosen default both
    appear in the contract's verdict table. The default is hand-stated here as a LITERAL -- reading
    it back from `PysrcLimits` would pin nothing, since the assertion would move with the constant.
    """
    assert DEFAULT_LIMITS.max_work == 390_000

    repository = Path(__file__).resolve().parent.parent
    benchmark = repository / "tools" / "bench_pysrc_work.py"
    assert benchmark.is_file()

    # The contract carries a `| W5 |` row in BOTH its predicate table and its verdict table, so the
    # search starts after the verdicts heading -- the first match is the predicate, which records
    # no number and would pass this test vacuously.
    contract = (repository / ".agent/archive/contracts/m13u5.md").read_text(encoding="utf-8")
    verdicts = contract[contract.index("## Verdicts") :]
    row = next(line for line in verdicts.splitlines() if line.startswith("| W5 |"))
    assert "390_000" in row
    assert "398,458 work/s" in row


# --- M13.5 edge witnesses: verdict paths a normal program never reaches -------------------------


def test_t4_grid_beyond_max_table_rows_refuses_before_building(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row bound is checked against the DECLARED sample count, not after materializing.

    Accept: a 50-sample formula under `max_table_rows=10` refuses `work_budget_exceeded`, and the
    same source verifies under the default limits -- so the refusal tracks the limit rather than
    the source. A call-counting bomb on the materialization proves the check runs BEFORE it.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415
    from verifier.pysrc import verify as verify_module  # noqa: PLC0415

    source = _FORMULA_SOURCE.replace("num=3", "num=50")
    default_result = verify_python_source(source)
    calls = 0

    def materialization_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        nonlocal calls
        calls += 1
        _raise_bomb("grid materialized before row cap")

    with monkeypatch.context() as patch:
        patch.setattr(verify_module, "materialize_grid", materialization_bomb)
        limited_result = verify_python_source(
            source, limits=replace(DEFAULT_LIMITS, max_table_rows=10)
        )

    assert calls == 0
    assert isinstance(default_result, Verified)
    assert isinstance(limited_result, Refused)
    assert limited_result.code == "work_budget_exceeded"


def test_g5_formula_scatter_needs_no_ordering() -> None:
    """`scatter` draws no path, so unordered x misrepresents nothing and G9 does not apply.

    Accept: a descending formula grid verifies under `plt.scatter`; the same grid under `plt.plot`
    refuses `x_not_ordered`, so the pair pins that the scatter arm RETURNS before line checks.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    source = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "x = np.linspace(1, -1, num=3)\n"
        "y = np.abs(x)\n"
        "plt.{mark}(x, y)\n"
        "plt.show()\n"
    )
    scatter = verify_python_source(source.format(mark="scatter"))
    line = verify_python_source(source.format(mark="plot"))

    assert isinstance(scatter, Verified)
    assert isinstance(line, Refused)
    assert line.code == "x_not_ordered"


def test_e_source_with_lone_surrogate_refuses() -> None:
    """A `str` holding an unpaired surrogate has no UTF-8 encoding, so it has no digest.

    Accept: a source carrying `"\\ud800"` refuses `source_not_utf8` rather than raising
    `UnicodeEncodeError` out of the public entry -- the caller gets a verdict, never a traceback.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415

    result = verify_python_source(_FORMULA_SOURCE + "\ud800")

    assert isinstance(result, Refused)
    assert result.code == "source_not_utf8"
