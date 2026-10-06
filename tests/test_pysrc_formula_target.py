# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.4 core target widening.

Contract: `.agent/archive/contracts/m10u4.md` predicate group C. Each test states the
expected tree, refusal code, declared gap or certificate bytes independently.
"""

from dataclasses import FrozenInstanceError, fields
from fractions import Fraction
from typing import get_args, get_type_hints

import pytest
from hypothesis import given
from hypothesis import strategies as st

from verifier.pysrc import RefusalCode, Refused, Verified, spec, verify_python_source
from verifier.pysrc.certificate import CERTIFICATE_VERSION, CoreCertificate, certify
from verifier.pysrc.request import formula_target

_FORMULA_SOURCE = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.linspace(0, 1, num=3)\n"
    "y = np.sin(x)\n"
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
_DATASET_BYTES = b"site,value\nwest,1\neast,2\n"
_ARTIFACT_GAP = "The emitted image is not compared against this table."
_INTENT_GAP = (
    "The plotted values are the submitted program's own expression, not a target the user stated."
)
_NO_ARTIFACT = (
    "No user artifact was consumed. The plotted values come from the submitted program alone."
)
_SAMPLES_GAP = "The request states no sample count. The submitted program sets it."
_INTERVAL_GAP = (
    "The request states no x interval. The submitted program sets the interval "
    "and the sample count."
)
_BASE_INTERPRETATION = (
    "Chart type: line. The data comes from the submitted program. Y computes sin(x). "
    "X runs from 0 to 1 in 3 samples. Numbers follow the profile binary64-libm-v1."
)


def _num(value: int | float) -> spec.Num:
    return spec.Num(Fraction(value))


def _grid(*, start: int = 0, stop: int = 1, samples: int = 3) -> spec.Grid:
    return spec.Grid(_num(start), _num(stop), samples)


def _sin_target(grid: spec.Grid | None = None) -> spec.FormulaTarget:
    return spec.FormulaTarget(spec.Fn("sin", spec.Var()), grid)


def _dataset_target() -> spec.DatasetTarget:
    return spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES)


def test_c1_interval_shape_is_frozen_slotted_and_inclusive() -> None:
    """C1: Interval has exactly start/stop, frozen slots, and carries the inclusive endpoint."""
    interval_type = spec.Interval
    assert tuple(field.name for field in fields(interval_type)) == ("start", "stop")
    assert interval_type.__slots__ == ("start", "stop")
    interval = interval_type(_num(0), _num(1))
    assert interval.start == _num(0)
    assert interval.stop == _num(1)
    assert not hasattr(interval, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(interval, "stop", _num(2))  # noqa: B010
    assert tuple(field.name for field in fields(spec.FormulaTarget)) == ("y", "grid")
    assert get_type_hints(spec.FormulaTarget)["grid"] == spec.Grid | spec.Interval | None
    assert spec.FormulaTarget(y=spec.Var()).grid is None


def test_c2_formula_y_mismatch_refuses_alone() -> None:
    """C2: a wrong y with an otherwise matching Grid refuses target_mismatch."""
    result = verify_python_source(
        _FORMULA_SOURCE,
        declared_target=spec.FormulaTarget(spec.Fn("cos", spec.Var()), _grid()),
    )
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"


def test_c2_grid_start_mismatch_refuses_alone() -> None:
    """C2: a wrong Grid start with the matching y/stop/samples refuses."""
    result = verify_python_source(_FORMULA_SOURCE, declared_target=_sin_target(_grid(start=2)))
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"


def test_c2_grid_stop_mismatch_refuses_alone() -> None:
    """C2: a wrong Grid stop with the matching y/start/samples refuses."""
    result = verify_python_source(_FORMULA_SOURCE, declared_target=_sin_target(_grid(stop=2)))
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"


def test_c2_grid_samples_mismatch_refuses_alone() -> None:
    """C2: a Grid samples mismatch alone refuses target_mismatch."""
    result = verify_python_source(_FORMULA_SOURCE, declared_target=_sin_target(_grid(samples=4)))
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"


def test_c2_interval_start_mismatch_refuses_alone() -> None:
    """C2: Interval compares the projected start even when the program's samples differ."""
    interval = spec.Interval(_num(2), _num(1))
    result = verify_python_source(
        _FORMULA_SOURCE, declared_target=spec.FormulaTarget(spec.Fn("sin", spec.Var()), interval)
    )
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"


def test_c2_interval_stop_mismatch_refuses_alone() -> None:
    """C2: Interval compares the projected inclusive stop independently."""
    interval = spec.Interval(_num(0), _num(2))
    result = verify_python_source(
        _FORMULA_SOURCE, declared_target=spec.FormulaTarget(spec.Fn("sin", spec.Var()), interval)
    )
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"


def test_c2_interval_ignores_sample_count() -> None:
    """C2: a target with an interval but no n verifies programs at different sample counts."""
    interval = spec.Interval(_num(0), _num(1))
    target = spec.FormulaTarget(spec.Fn("sin", spec.Var()), interval)
    original = verify_python_source(_FORMULA_SOURCE, declared_target=target)
    different = verify_python_source(
        _FORMULA_SOURCE.replace("num=3", "num=5"), declared_target=target
    )
    assert isinstance(original, Verified)
    assert isinstance(different, Verified)
    assert isinstance(original.spec, spec.FormulaPlot)
    assert isinstance(different.spec, spec.FormulaPlot)
    assert original.spec.grid.samples == 3
    assert different.spec.grid.samples == 5


def test_c2_no_domain_does_not_compare_grid() -> None:
    """C2: a formula-only target compares y but leaves start, stop and n open."""
    different = verify_python_source(
        _FORMULA_SOURCE.replace("np.linspace(0, 1, num=3)", "np.linspace(3, 5, num=7)"),
        declared_target=_sin_target(),
    )
    assert isinstance(different, Verified)
    assert isinstance(different.spec, spec.FormulaPlot)
    assert different.spec.grid == _grid(start=3, stop=5, samples=7)


def test_c2_no_folding_of_mathematically_equal_y() -> None:
    """C2: Neg(Num(5)) differs from Num(-5) even if the plotted numbers coincide."""
    source = _FORMULA_SOURCE.replace("y = np.sin(x)", "y = x + -5")
    target = spec.FormulaTarget(spec.Bin("add", spec.Var(), _num(-5)), _grid())
    result = verify_python_source(source, declared_target=target)
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"


def test_c3_formula_program_rejects_dataset_target() -> None:
    """C3: a formula cannot verify against a supplied CSV even if its code reads no file."""
    result = verify_python_source(_FORMULA_SOURCE, declared_target=_dataset_target())
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"


def test_c3_unchanged_cells_of_the_arm_target_matrix() -> None:
    """C3: every other arm-by-target cell retains its explicit verdict and provenance."""
    results = (
        verify_python_source(_DATASET_SOURCE),
        verify_python_source(_DATASET_SOURCE, declared_target=_dataset_target()),
        verify_python_source(_DATASET_SOURCE, declared_target=_sin_target()),
        verify_python_source(_FORMULA_SOURCE),
        verify_python_source(_FORMULA_SOURCE, declared_target=_sin_target(_grid())),
    )
    assert isinstance(results[0], Refused) and results[0].code == "source_not_supplied"
    assert isinstance(results[1], Verified) and results[1].certificate.provenance == "artifact"
    assert isinstance(results[2], Refused) and results[2].code == "source_not_supplied"
    assert isinstance(results[3], Verified) and results[3].certificate.provenance == "internal"
    assert isinstance(results[4], Verified) and results[4].certificate.provenance == "artifact"


def test_c4_dataset_with_non_none_target_has_artifact_provenance() -> None:
    """C4: the bound dataset cell of the matrix publishes artifact provenance."""
    result = verify_python_source(_DATASET_SOURCE, declared_target=_dataset_target())
    assert isinstance(result, Verified)
    assert result.certificate.provenance == "artifact"


@given(
    st.sampled_from(
        [
            ("np.sin(x)", spec.Fn("sin", spec.Var())),
            ("np.cos(x)", spec.Fn("cos", spec.Var())),
            ("x + 1", spec.Bin("add", spec.Var(), _num(1))),
        ]
    ),
    st.integers(min_value=0, max_value=3),
    st.integers(min_value=1, max_value=4),
    st.integers(min_value=2, max_value=6),
    st.sampled_from(["grid", "interval", "none"]),
)
def test_c4_every_bound_formula_property(
    case: tuple[str, spec.Expr], start: int, step: int, samples: int, domain: str
) -> None:
    """C4: drawn programs with user-bound y/optional domains always claim artifact provenance."""
    expression, expected_y = case
    stop = start + step
    source = (
        "import numpy as np\nimport matplotlib.pyplot as plt\n"
        f"x = np.linspace({start}, {stop}, num={samples})\n"
        f"y = {expression}\nplt.plot(x, y)\nplt.show()\n"
    )
    grid = spec.Grid(_num(start), _num(stop), samples)
    if domain == "grid":
        declared_domain: spec.Grid | spec.Interval | None = grid
    elif domain == "interval":
        declared_domain = spec.Interval(_num(start), _num(stop))
    else:
        declared_domain = None
    result = verify_python_source(
        source, declared_target=spec.FormulaTarget(expected_y, declared_domain)
    )
    assert isinstance(result, Verified)
    assert result.certificate.provenance == "artifact"


def test_c5_bound_dataset_and_unbound_formula_gaps_remain_exact() -> None:
    """C5: dataset binding and unbound formula retain their exact old gap sets."""
    dataset = verify_python_source(_DATASET_SOURCE, declared_target=_dataset_target())
    internal = verify_python_source(_FORMULA_SOURCE)
    assert isinstance(dataset, Verified)
    assert isinstance(internal, Verified)
    assert set(dataset.certificate.declared_open) == {_ARTIFACT_GAP}
    assert set(internal.certificate.declared_open) == {
        _ARTIFACT_GAP,
        _INTENT_GAP,
        _NO_ARTIFACT,
    }


def test_c5_grid_bound_formula_only_has_artifact_gap() -> None:
    """C5: exact-domain formula binding consumes the user's request artifact."""
    result = verify_python_source(_FORMULA_SOURCE, declared_target=_sin_target(_grid()))
    assert isinstance(result, Verified)
    assert set(result.certificate.declared_open) == {_ARTIFACT_GAP}


def test_c5_interval_bound_formula_names_samples_gap_exactly() -> None:
    """C5: request interval binds y/x but leaves n to the submitted program."""
    result = verify_python_source(
        _FORMULA_SOURCE,
        declared_target=spec.FormulaTarget(
            spec.Fn("sin", spec.Var()), spec.Interval(_num(0), _num(1))
        ),
    )
    assert isinstance(result, Verified)
    assert set(result.certificate.declared_open) == {_ARTIFACT_GAP, _SAMPLES_GAP}


def test_c5_no_domain_formula_names_interval_gap_exactly() -> None:
    """C5: request y-only target binds y but leaves the interval and n open."""
    result = verify_python_source(_FORMULA_SOURCE, declared_target=_sin_target())
    assert isinstance(result, Verified)
    assert set(result.certificate.declared_open) == {_ARTIFACT_GAP, _INTERVAL_GAP}


def test_c6_unbound_formula_interpretation_is_byte_unchanged() -> None:
    """C6: an unbound formula certificate keeps its original complete sentence bytes."""
    result = verify_python_source(_FORMULA_SOURCE)
    assert isinstance(result, Verified)
    assert result.certificate.interpretation == _BASE_INTERPRETATION


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        (
            "grid",
            "Chart type: line. The data comes from the submitted program. "
            "The formula, the x interval and the sample count match the request. "
            "Y computes sin(x). X runs from 0 to 1 in 3 samples. "
            "Numbers follow the profile binary64-libm-v1.",
        ),
        (
            "interval",
            "Chart type: line. The data comes from the submitted program. "
            "The formula and the x interval match the request. "
            "Y computes sin(x). X runs from 0 to 1 in 3 samples. "
            "Numbers follow the profile binary64-libm-v1.",
        ),
        (
            "none",
            "Chart type: line. The data comes from the submitted program. "
            "The formula matches the request. "
            "Y computes sin(x). X runs from 0 to 1 in 3 samples. "
            "Numbers follow the profile binary64-libm-v1.",
        ),
    ],
    ids=["grid", "interval", "formula-only"],
)
def test_c6_bound_interpretation_is_byte_pinned(domain: str, expected: str) -> None:
    """C6: one exact sentence follows the source sentence for each target domain form."""
    if domain == "grid":
        target = _sin_target(_grid())
    elif domain == "interval":
        target = spec.FormulaTarget(spec.Fn("sin", spec.Var()), spec.Interval(_num(0), _num(1)))
    else:
        target = _sin_target()
    result = verify_python_source(_FORMULA_SOURCE, declared_target=target)
    assert isinstance(result, Verified)
    assert result.certificate.interpretation == expected


def test_q9_certificate_reads_a_grid_sample_mismatch_as_unconsumed() -> None:
    """`_target_consumed` checks a Grid target's sample count before its bounds: binding refuses
    that target first, so only a direct `certify` call reaches it, and it publishes `internal`."""
    verdict = verify_python_source(_FORMULA_SOURCE)
    assert isinstance(verdict, Verified) and isinstance(verdict.spec, spec.FormulaPlot)
    plot = verdict.spec
    for samples, provenance in (
        (plot.grid.samples, "artifact"),
        (plot.grid.samples + 1, "internal"),
    ):
        target = spec.FormulaTarget(plot.y, spec.Grid(plot.grid.start, plot.grid.stop, samples))
        assert certify(plot, verdict.table, b"", target, None).provenance == provenance


def test_c7_certificate_and_refusal_vocabulary_stay_closed() -> None:
    """C7: version, K1's field set and all 54 refusal codes stay unchanged."""
    assert CERTIFICATE_VERSION == "pysrc-cert-0.1"
    assert set(CoreCertificate.__dataclass_fields__) == {
        "version",
        "source_sha256",
        "spec_sha256",
        "table_sha256",
        "group_counts",
        "provenance",
        "artifact_sha256",
        "numeric_profile",
        "checks",
        "declared_open",
        "interpretation",
    }
    assert len(get_args(RefusalCode)) == 54


_SQUARE_OVER_ARANGE = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.arange(-5, 6)\n"
    "y = x**2\n"
    "plt.plot(x, y)\n"
    "plt.show()\n"
)


@pytest.mark.parametrize(
    ("sentence", "verified"),
    [
        ("Plot y = x**2, x ∈ [-5, 5]", True),
        ("Plot y = x**2, x ∈ [-5, 5], n = 11", True),
        ("Plot y = x**2, x ∈ [-5, 4]", False),
        ("Plot y = x**2, x ∈ [-4, 5]", False),
        ("Plot y = x**2, x ∈ [-5, 5], n = 10", False),
    ],
)
def test_q17_a_negative_arange_binds_its_request_by_exact_value(
    sentence: str, *, verified: bool
) -> None:
    """Q17 (user ruling): the request keeps `-5` as `Neg(Num(5))` while projection folds `arange`
    bounds to `Num(-5)`; both fold to -5, so `x ∈ [-5, 5]` binds `np.arange(-5, 6)` -- with or
    without `n = 11` -- and a different bound or count still refuses `target_mismatch`."""
    target = formula_target(sentence)
    assert target is not None
    result = verify_python_source(_SQUARE_OVER_ARANGE, declared_target=target)
    if verified:
        assert isinstance(result, Verified)
        # The certificate reads the SAME bound predicate: a bound target is consumed provenance.
        assert result.certificate.provenance == "artifact"
    else:
        assert isinstance(result, Refused)
        assert result.code == "target_mismatch"


def test_q17_a_bound_binary64_rounds_still_compares_by_tree() -> None:
    """Q17: value comparison needs a bound binary64 computes EXACTLY. `1/49*49` folds to 1 in exact
    arithmetic but the program computes 0.9999999999999999, so against `x ∈ [1, 2]` it compares by
    tree and refuses -- the bound the program draws is not the bound the user stated."""
    source = _FORMULA_SOURCE.replace(
        "np.linspace(0, 1, num=3)", "np.linspace(1 / 49 * 49, 2, num=3)"
    )
    target = formula_target("Plot y = sin(x), x ∈ [1, 2]")
    assert target is not None
    result = verify_python_source(source, declared_target=target)
    assert isinstance(result, Refused)
    assert result.code == "target_mismatch"
    control = formula_target("Plot y = sin(x), x ∈ [1 / 49 * 49, 2]")
    assert control is not None
    assert isinstance(verify_python_source(source, declared_target=control), Verified)
