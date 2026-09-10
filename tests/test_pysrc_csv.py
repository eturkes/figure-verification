# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Target binding + the safe CSV profile — C1-C11 of `.agent/archive/contracts/m13u5.md`.

The sandbox parses the user's file with `pandas.read_csv`; the verifier may not depend on pandas
and parses with stdlib `csv` + `float`. Everything the two would read differently is REFUSED, so
the profile is deliberately narrow: refusing is cheap, and plotting a number the verifier parsed
differently from the renderer is the failure this project exists to prevent.

Each test carries its predicate's acceptance check in the docstring.
"""

from fractions import Fraction
from typing import get_args

from verifier.pysrc import spec

_DATASET_BYTES = b"site,value\nwest,1\neast,2\n"


def _dataset_source(path: str = "measurements.csv", *, mark: str = "bar") -> str:
    return (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("{path}")\n'
        f'plt.{mark}(df["site"], df["value"])\n'
        "plt.show()\n"
    )


def _formula_source(grid_call: str = "np.linspace(0, 1, num=3)") -> str:
    return (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        f"x = {grid_call}\n"
        "y = np.sin(x)\n"
        "plt.plot(x, y)\n"
        "plt.show()\n"
    )


def _sin_target(*, grid: spec.Grid | None) -> spec.FormulaTarget:
    return spec.FormulaTarget(y=spec.Fn("sin", spec.Var()), grid=grid)


def test_c1_declared_target_union() -> None:
    """`DeclaredTarget = DatasetTarget(path, content) | FormulaTarget(y, grid)`.

    Accept: exact-set pin on the union; a total map over it carries a missing-arm mutant.
    `FormulaTarget` holds a parsed `spec.Expr` tree, so the core needs no expression parser.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    assert get_args(spec.DeclaredTarget.__value__) == (spec.DatasetTarget, spec.FormulaTarget)
    assert set(spec.DatasetTarget.__dataclass_fields__) == {"path", "content"}
    assert set(spec.FormulaTarget.__dataclass_fields__) == {"y", "grid"}

    dataset_target = spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES)
    dataset = verify_python_source(_dataset_source(), declared_target=dataset_target)
    assert isinstance(dataset, Verified)

    grid = spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(1)), 3)
    formula = verify_python_source(_formula_source(), declared_target=_sin_target(grid=grid))
    assert isinstance(formula, Verified)


def test_c2_dataset_arm_without_bytes_refuses() -> None:
    """No `DatasetTarget` -> `source_not_supplied`, including when a `FormulaTarget` is supplied
    instead -- it carries no bytes.

    Accept: both witnesses; the `FormulaTarget` case must NOT reach `target_mismatch`.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415

    no_target = verify_python_source(_dataset_source())
    wrong_kind = verify_python_source(
        _dataset_source(),
        declared_target=_sin_target(grid=None),
    )
    for result in (no_target, wrong_kind):
        assert isinstance(result, Refused)
        assert result.code == "source_not_supplied"


def test_c3_path_binding_is_byte_exact() -> None:
    """`DatasetPlot.source.path` equals `DatasetTarget.path` byte-for-byte -- no normalization,
    no `Path` resolution, no case folding.

    Accept: near-miss witnesses each refusing `target_mismatch` -- trailing slash, `./` prefix,
    differing case, and a Unicode-equivalent but non-identical spelling.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    source_path = "café.csv"
    exact = verify_python_source(
        _dataset_source(source_path),
        declared_target=spec.DatasetTarget(path=source_path, content=_DATASET_BYTES),
    )
    assert isinstance(exact, Verified)

    near_misses = (
        "café.csv/",
        "./café.csv",
        "CAFÉ.CSV",
        "café.csv",
    )
    for target_path in near_misses:
        result = verify_python_source(
            _dataset_source(source_path),
            declared_target=spec.DatasetTarget(path=target_path, content=_DATASET_BYTES),
        )
        assert isinstance(result, Refused)
        assert result.code == "target_mismatch"


def test_c4_formula_target_compares_structurally() -> None:
    """With a `FormulaTarget`, the projected `y` must equal `target.y` structurally, and the grid
    must equal `target.grid` when that is given.

    Accept: structural-equality witness pairs, including two spellings of one grid that M13.3
    makes equal; a mismatch refuses `target_mismatch`.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    grid = spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(4)), 5)
    target = _sin_target(grid=grid)
    arange = verify_python_source(_formula_source("np.arange(0, 5)"), declared_target=target)
    linspace = verify_python_source(
        _formula_source("np.linspace(0, 4, num=5)"), declared_target=target
    )
    expression_only = verify_python_source(
        _formula_source("np.arange(0, 5)"), declared_target=_sin_target(grid=None)
    )
    assert isinstance(arange, Verified)
    assert isinstance(linspace, Verified)
    assert isinstance(expression_only, Verified)

    wrong_expression = verify_python_source(
        _formula_source("np.arange(0, 5)"),
        declared_target=spec.FormulaTarget(y=spec.Fn("cos", spec.Var()), grid=grid),
    )
    wrong_grid = verify_python_source(
        _formula_source("np.arange(0, 5)"),
        declared_target=_sin_target(
            grid=spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(3)), 4)
        ),
    )
    for result in (wrong_expression, wrong_grid):
        assert isinstance(result, Refused)
        assert result.code == "target_mismatch"


def test_c5_formula_arm_never_silently_consumes_a_target() -> None:
    """Every formula arm declares that no user artifact was consumed; a supplied dataset target
    also declares that its file was not read.

    Accept: both `declared_open` strings byte-pinned across all three formula/target combinations.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    no_artifact_sentence = (
        "No user artifact was consumed. The plotted values come from the submitted program alone."
    )
    unused_file_sentence = "The supplied data file was not read by this chart."
    grid = spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(1)), 3)
    targets: tuple[spec.DeclaredTarget | None, ...] = (
        None,
        spec.DatasetTarget(path="unused.csv", content=_DATASET_BYTES),
        _sin_target(grid=grid),
    )
    results = [
        verify_python_source(_formula_source(), declared_target=target) for target in targets
    ]
    assert all(isinstance(result, Verified) for result in results)
    certificates = [result.certificate for result in results if isinstance(result, Verified)]
    assert [certificate.provenance for certificate in certificates] == [
        "internal",
        "internal",
        "artifact",
    ]
    assert all(no_artifact_sentence in certificate.declared_open for certificate in certificates)
    assert unused_file_sentence not in certificates[0].declared_open
    assert unused_file_sentence in certificates[1].declared_open
    assert unused_file_sentence not in certificates[2].declared_open


def test_c6_strict_structural_profile() -> None:
    """UTF-8 without BOM, one header, at least one data row, fixed width, no post-quote junk.

    Accept: BOM, header-only, short row, long row, and post-quote junk each refuse
    `csv_not_parsable`. The row floor prevents vacuous C8 column classification.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    valid = verify_python_source(
        _dataset_source(),
        declared_target=spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES),
    )
    assert isinstance(valid, Verified)

    malformed = {
        "bom": b"\xef\xbb\xbfsite,value\nwest,1\n",
        "header-only": b"site,value\n",
        "short-row": b"site,value\nwest\n",
        "long-row": b"site,value\nwest,1,extra\n",
        "post-quote-junk": b'site,value\nwest,"1"junk\n',
    }
    for name, content in malformed.items():
        result = verify_python_source(
            _dataset_source(),
            declared_target=spec.DatasetTarget(path="measurements.csv", content=content),
        )
        assert isinstance(result, Refused), name
        assert result.code == "csv_not_parsable", name


def test_c7_columns_present_and_unambiguous() -> None:
    """Both named columns present in the header, matched byte-for-byte; a duplicate header name
    refuses.

    Accept: present, absent, and duplicate witnesses; absent -> `column_not_present`; duplicate
    -> `csv_not_parsable` per § The remaining suite objections.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    witnesses = {
        "present": b"site,value\nwest,1\n",
        "absent": b"Site,value\nwest,1\n",
        "duplicate": b"site,value,site\nwest,1,east\n",
    }
    results = {
        name: verify_python_source(
            _dataset_source(),
            declared_target=spec.DatasetTarget(path="measurements.csv", content=content),
        )
        for name, content in witnesses.items()
    }
    assert isinstance(results["present"], Verified)
    assert isinstance(results["absent"], Refused)
    assert results["absent"].code == "column_not_present"
    assert isinstance(results["duplicate"], Refused)
    assert results["duplicate"].code == "csv_not_parsable"


def test_c8_numeric_where_a_number_is_required() -> None:
    """Classify by stdlib `float(text)` success, then apply profile admission and the column role.

    Accept: every mark sees numeric, categorical, and mixed columns. The explicit y pair is
    `ten,20` -> mixed/value-not-in-profile versus `ten,twelve` -> categorical/column-not-numeric.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    classes: tuple[tuple[str, bytes, dict[str, str | None]], ...] = (
        (
            "numeric",
            b"site,value\n1,10\n2,20\n",
            {"bar": None, "plot": None, "scatter": None},
        ),
        (
            # `plot` verifies here by G9, a user ruling: a categorical line x is admitted when
            # every category appears exactly once, which `west`/`east` satisfies. `scatter` alone
            # still requires a numeric x.
            "categorical-x",
            b"site,value\nwest,10\neast,20\n",
            {"bar": None, "plot": None, "scatter": "column_not_numeric"},
        ),
        (
            # A mark whose x may be EITHER numeric or categorical reads a mixed column as a role
            # fault, not a cell fault: neither kind is satisfied, so the fix is another column.
            # `scatter` wants a number outright, so its mixed column refuses at the first cell.
            "mixed-x",
            b"site,value\n1,10\nwest,20\n",
            {
                "bar": "column_not_numeric",
                "plot": "column_not_numeric",
                "scatter": "value_not_in_profile",
            },
        ),
        (
            "categorical-y",
            b"site,value\n1,ten\n2,twelve\n",
            {
                "bar": "column_not_numeric",
                "plot": "column_not_numeric",
                "scatter": "column_not_numeric",
            },
        ),
        (
            "mixed-y",
            b"site,value\n1,ten\n2,20\n",
            {
                "bar": "value_not_in_profile",
                "plot": "value_not_in_profile",
                "scatter": "value_not_in_profile",
            },
        ),
        (
            "float-numeric-but-outside-ascii-profile-y",
            (
                "site,value\n"
                "1,\N{FULLWIDTH DIGIT ONE}\N{FULLWIDTH DIGIT TWO}\N{FULLWIDTH DIGIT THREE}\n"
                "2,\N{FULLWIDTH DIGIT FOUR}\N{FULLWIDTH DIGIT FIVE}\N{FULLWIDTH DIGIT SIX}\n"
            ).encode(),
            {
                "bar": "value_not_in_profile",
                "plot": "value_not_in_profile",
                "scatter": "value_not_in_profile",
            },
        ),
    )
    for class_name, content, expectations in classes:
        for mark, expected_code in expectations.items():
            result = verify_python_source(
                _dataset_source(mark=mark),
                declared_target=spec.DatasetTarget(path="measurements.csv", content=content),
            )
            if expected_code is None:
                assert isinstance(result, Verified), (class_name, mark)
            else:
                assert isinstance(result, Refused), (class_name, mark)
                assert result.code == expected_code, (class_name, mark)


def test_c9_no_null_or_bool_survives() -> None:
    """Sweep NA and bool-like cells before classifying either selected column.

    Accept: every NA spelling is plain and quoted in x and y. `True`, `FALSE`, and `true` refuse
    inside otherwise-numeric and otherwise-categorical x and y columns.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    na_spellings = {
        "",
        "#N/A",
        "#N/A N/A",
        "#NA",
        "-1.#IND",
        "-1.#QNAN",
        "-NaN",
        "-nan",
        "1.#IND",
        "1.#QNAN",
        "<NA>",
        "N/A",
        "NA",
        "NULL",
        "NaN",
        "None",
        "n/a",
        "nan",
        "null",
    }
    source = _dataset_source(mark="bar")
    for spelling in na_spellings:
        for form, cell in (("plain", spelling), ("quoted", f'"{spelling}"')):
            contents = (
                ("x", f"site,value\n{cell},1\n".encode()),
                ("y", f"site,value\nkept,{cell}\n".encode()),
            )
            for selected_column, content in contents:
                result = verify_python_source(
                    source,
                    declared_target=spec.DatasetTarget(path="measurements.csv", content=content),
                )
                assert isinstance(result, Refused), (selected_column, form, spelling)
                assert result.code == "value_not_in_profile", (selected_column, form, spelling)

    for spelling in ("True", "FALSE", "true"):
        for form, cell in (("plain", spelling), ("quoted", f'"{spelling}"')):
            contexts = {
                "numeric-x": f"site,value\n1,1\n{cell},2\n",
                "categorical-x": f"site,value\nwest,1\n{cell},2\n",
                "numeric-y": f"site,value\n1,1\n2,{cell}\n",
                "categorical-y": f"site,value\n1,west\n2,{cell}\n",
            }
            for context, text in contexts.items():
                result = verify_python_source(
                    source,
                    declared_target=spec.DatasetTarget(
                        path="measurements.csv", content=text.encode()
                    ),
                )
                assert isinstance(result, Refused), (context, form, spelling)
                assert result.code == "value_not_in_profile", (context, form, spelling)

    # Stage 1 is case-SENSITIVE, so a case variant outside the 19 spellings survives it. Which
    # predicate it then meets depends on stage 2, and the two witnesses below split there.
    #
    # `NuLL` is not float-parsable, so it classifies categorical and a bar x accepts it.
    case_sensitive_near_miss = verify_python_source(
        source,
        declared_target=spec.DatasetTarget(
            path="measurements.csv", content=b"site,value\nNuLL,1\n"
        ),
    )
    assert isinstance(case_sensitive_near_miss, Verified)

    # `NAN` is the one token where stdlib `float` and pandas disagree in the direction stage 2's
    # ruling anticipates: `float("NAN")` succeeds, so the column classifies numeric and the
    # ASCII-only profile refuses the cell -- while pandas keeps `'NAN'` as a string even alone in a
    # column (measured, host pandas 3.0.5; `NaN`/`nan` ARE swept by stage 1, `NAN` is not). So this
    # is a conservative FALSE REFUSAL of a chart pandas would have drawn, which is the safe
    # direction the ruling names: the divergence can only reclassify toward a refusal.
    float_parsable_near_miss = verify_python_source(
        source,
        declared_target=spec.DatasetTarget(path="measurements.csv", content=b"site,value\nNAN,1\n"),
    )
    assert isinstance(float_parsable_near_miss, Refused)
    assert float_parsable_near_miss.code == "value_not_in_profile"


def test_c10_profile_boundaries_are_mixed_columns() -> None:
    """Every out-of-profile numeric candidate is a cell fault inside a mixed numeric column.

    Accept: all 13 named boundary families carry an in-profile companion row and refuse
    `value_not_in_profile`; representative boundary values inside the measured region verify.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    outside_profile: dict[str, tuple[str, ...]] = {
        "exponent": ("1e2",),
        "leading-plus": ("+1",),
        "surrounding-whitespace": (" 1", "1 "),
        "leading-or-trailing-point": (".5", "1."),
        "redundant-leading-zero": ("01",),
        "underscore": ("1_0",),
        "thousands-separator": ("1,000",),
        "hex": ("0x1f",),
        "seven-decimals": ("0.1234567",),
        "sixteen-significant-digits": ("1234567890.123456",),
        "out-of-range": ("2147483648",),
        "non-finite": ("inf",),
        "negative-zero": ("-0.0",),
    }
    assert len(outside_profile) == 13
    source = _dataset_source(mark="scatter")
    for boundary, candidates in outside_profile.items():
        for candidate in candidates:
            cell = f'"{candidate}"' if "," in candidate else candidate
            content = f"site,value\n1,1\n2,{cell}\n".encode()
            result = verify_python_source(
                source,
                declared_target=spec.DatasetTarget(path="measurements.csv", content=content),
            )
            assert isinstance(result, Refused), (boundary, candidate)
            assert result.code == "value_not_in_profile", (boundary, candidate)

    inside_profile = (
        b"site,value\n1,-2147483648\n2,2147483647\n3,123456789.123456\n4,0\n5,0.000001\n"
    )
    accepted = verify_python_source(
        source,
        declared_target=spec.DatasetTarget(path="measurements.csv", content=inside_profile),
    )
    assert isinstance(accepted, Verified)


def test_c11_source_order_is_preserved() -> None:
    """Row order is file order. The verifier never sorts, and the legacy total-sort closure is
    not reused.

    Accept: a CSV whose rows are not sorted by x plots in file order; a sort-injecting mutant goes
    red.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    content = b"site,value\n3,30\n1,10\n2,20\n"
    result = verify_python_source(
        _dataset_source(mark="scatter"),
        declared_target=spec.DatasetTarget(path="measurements.csv", content=content),
    )
    assert isinstance(result, Verified)
    assert result.table.x == (3.0, 1.0, 2.0)
    assert result.table.y == (30.0, 10.0, 20.0)


# --- M13.5 edge witnesses: the stdlib-`csv` refusal paths ---------------------------------------
# Each names a byte shape `pandas.read_csv` and stdlib `csv` could read differently, so the profile
# refuses it. Contract: `.agent/archive/contracts/m13u5.md` C. Confirmed reachable; all three refuse
# `csv_not_parsable` through the public entry.


def test_csv_bare_carriage_return_is_not_parsable() -> None:
    """A lone CR is a row separator to stdlib `csv` and a line terminator to pandas.

    Accept: `b"a,b\\r1,2\\n"` refuses `csv_not_parsable`; the same bytes with CRLF verify, so the
    refusal is the BARE CR and not the carriage return itself.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    source = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("measurements.csv")\n'
        'plt.bar(df["a"], df["b"])\n'
        "plt.show()\n"
    )
    bare_cr = verify_python_source(
        source,
        declared_target=spec.DatasetTarget(path="measurements.csv", content=b"a,b\r1,2\n"),
    )
    crlf = verify_python_source(
        source,
        declared_target=spec.DatasetTarget(path="measurements.csv", content=b"a,b\r\n1,2\r\n"),
    )

    assert isinstance(bare_cr, Refused)
    assert bare_cr.code == "csv_not_parsable"
    assert isinstance(crlf, Verified)


def test_csv_invalid_utf8_is_not_parsable() -> None:
    """Undecodable bytes that are neither the BOM nor NUL reach the decode and refuse there.

    Accept: `b"a,b\\n\\xff\\xfe,2\\n"` refuses `csv_not_parsable`. BOM and NUL refuse one step
    earlier, so the witness must use bytes that survive to `content.decode("utf-8")`.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415

    result = verify_python_source(
        _dataset_source(),
        declared_target=spec.DatasetTarget(path="measurements.csv", content=b"a,b\n\xff\xfe,2\n"),
    )

    assert isinstance(result, Refused)
    assert result.code == "csv_not_parsable"


def test_csv_empty_content_is_not_parsable() -> None:
    """Empty content yields no header row at all.

    Accept: `b""` refuses `csv_not_parsable`; a header-only file refuses too, but for the row
    count rather than the missing header, so the two must not collapse to one code path.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415

    result = verify_python_source(
        _dataset_source(),
        declared_target=spec.DatasetTarget(path="measurements.csv", content=b""),
    )

    assert isinstance(result, Refused)
    assert result.code == "csv_not_parsable"
