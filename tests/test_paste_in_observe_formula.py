# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.2 O5: compare observed formula floats with expression-derived uncertainty intervals.

Contract: `.agent/archive/contracts/m10u2.md` § A1 R1/R4. These test cases come from verified
programs; the cancellation observation is constructed independently from a last-bit perturbation
of one transcendental, not read from a precomputed expected-output table.
"""

import importlib
import math
from typing import Any, Literal, cast

import pytest

from observe_support import formula_verdict, observation_for, stdout_for
from verifier.pysrc import Verified


def _matches(verdict: Verified, payload: dict[str, Any]) -> bool:
    module = importlib.import_module("webui.paste_in.observe")
    observed = module.parse_observation(stdout_for(payload))
    assert observed is not None
    return bool(module.observation_matches(verdict, observed))


def _points(verdict: Verified, payload: dict[str, Any]) -> list[list[str]]:
    series = payload["lines" if verdict.spec.mark == "line" else "collections"]
    return cast(list[list[str]], series[0])


@pytest.mark.parametrize(
    "expression", ["np.sin(x)", "np.cos(x)", "np.tan(x)", "np.exp(x)", "np.log(x)", "x**1.3"]
)
def test_o5_each_libm_call_has_one_ulp_room_at_point_argument(expression: str) -> None:
    """O5: sin/cos/tan/exp/log/pow each admit a finite one-ulp renderer difference."""
    verdict = formula_verdict(expression, bounds=("0.2", "0.6"))
    payload = observation_for(verdict)
    assert _matches(verdict, payload)
    observed_y = _points(verdict, payload)[0][1]
    _points(verdict, payload)[0][1] = math.nextafter(float.fromhex(observed_y), math.inf).hex()
    assert _matches(verdict, payload)


@pytest.mark.parametrize("mark", ["line", "scatter"])
def test_o5_sin_of_point_arithmetic_releases(mark: Literal["line", "scatter"]) -> None:
    """O5/R4: sin(2*x) releases: the argument is point arithmetic, not an interval."""
    verdict = formula_verdict("np.sin(2*x)", mark=mark)
    payload = observation_for(verdict)
    assert _matches(verdict, payload)
    _points(verdict, payload)[1][1] = math.nextafter(verdict.table.y[1], math.inf).hex()
    assert _matches(verdict, payload)


@pytest.mark.parametrize("expression", ["x + 0.2", "x - 0.2", "x * 0.2", "x / 3"])
def test_o5_point_arithmetic_is_not_widened(expression: str) -> None:
    """O5/R4: arithmetic of point operands yields one correctly rounded point."""
    verdict = formula_verdict(expression, bounds=("0.2", "0.6"))
    payload = observation_for(verdict)
    assert _matches(verdict, payload)
    y = float.fromhex(_points(verdict, payload)[0][1])
    _points(verdict, payload)[0][1] = math.nextafter(y, math.inf).hex()
    assert not _matches(verdict, payload)


@pytest.mark.parametrize(
    "expression,bounds",
    [("np.sqrt(x)", ("1", "4")), ("np.abs(x)", ("-1", "1")), ("-x", ("0", "1"))],
)
def test_o5_sqrt_abs_negation_stay_points(expression: str, bounds: tuple[str, str]) -> None:
    """O5: correctly rounded sqrt, abs and unary minus cannot borrow libm uncertainty."""
    verdict = formula_verdict(expression, bounds=bounds)
    payload = observation_for(verdict)
    assert _matches(verdict, payload)
    y = float.fromhex(_points(verdict, payload)[1][1])
    _points(verdict, payload)[1][1] = math.nextafter(y, math.inf).hex()
    assert not _matches(verdict, payload)


def test_o5_signed_zero_normalized_by_matplotlib_still_releases() -> None:
    """O5/R1: negative zero in the real table equals positive zero in the artist."""
    verdict = formula_verdict("-x", bounds=("0", "1"))
    assert math.copysign(1.0, verdict.table.y[0]) == -1.0
    payload = observation_for(verdict)
    assert float.fromhex(_points(verdict, payload)[0][1]) == 0.0
    _points(verdict, payload)[0][1] = (0.0).hex()
    assert _matches(verdict, payload)


@pytest.mark.parametrize("mark", ["line", "scatter"])
def test_o5_formula_x_requires_exact_binary64_samples(mark: Literal["line", "scatter"]) -> None:
    """O5: a one-ulp change in one sampled x blocks despite every y matching the table."""
    verdict = formula_verdict("np.sin(x)", mark=mark)
    payload = observation_for(verdict)
    assert _matches(verdict, payload)
    points = _points(verdict, payload)
    points[1][0] = math.nextafter(float.fromhex(points[1][0]), math.inf).hex()
    assert not _matches(verdict, payload)


@pytest.mark.parametrize("mark", ["line", "scatter"])
def test_o5_y_one_ulp_beyond_libm_interval_withholds(mark: Literal["line", "scatter"]) -> None:
    """O5: the first allowed sin ulp releases; the next one outside the band withholds."""
    verdict = formula_verdict("np.sin(x)", bounds=("0.2", "0.6"), mark=mark)
    payload = observation_for(verdict)
    first = _points(verdict, payload)[0]
    y = verdict.table.y[0]
    first[1] = math.nextafter(y, math.inf).hex()
    assert _matches(verdict, payload)
    first[1] = math.nextafter(math.nextafter(y, math.inf), math.inf).hex()
    assert not _matches(verdict, payload)
    first[1] = math.nextafter(y, -math.inf).hex()
    assert _matches(verdict, payload)
    first[1] = math.nextafter(math.nextafter(y, -math.inf), -math.inf).hex()
    assert not _matches(verdict, payload)


def test_o5_cancellation_allows_many_y_ulps_when_source_ops_differ() -> None:
    """O5: near pi/4, half a sin ulp changes the tiny sin-cos result by many y ulps."""
    verdict = formula_verdict(
        "np.sin(x) - np.cos(x)",
        bounds=("0.7853981633974483", "0.7853981633994483"),
        samples=41,
    )
    payload = observation_for(verdict)
    assert _matches(verdict, payload)
    x = verdict.table.x[1]
    y = verdict.table.y[1]
    assert isinstance(x, float)
    candidate = y + math.ulp(math.sin(x)) / 2
    assert (candidate - y) / math.ulp(y) > 1_000_000
    _points(verdict, payload)[1][1] = candidate.hex()
    assert _matches(verdict, payload)


@pytest.mark.parametrize("expression", ["np.sin(np.cos(x))", "np.sin(x)**2", "np.exp(-x**2)"])
def test_q18_interval_libm_argument_releases_at_host_value(expression: str) -> None:
    """Q18 (user ruling; supersedes the O5/R4 reading that withheld these): a libm call or an
    integer `**` over an interval argument encloses its result -- monotone ends, extrema, 1 ulp
    outward per call -- so the host values release, and one y moved 1 ulp past its enclosure
    withholds."""
    verdict = formula_verdict(expression, bounds=("0.1", "1.0"))
    payload = observation_for(verdict)
    assert _matches(verdict, payload)
    spec = cast("Any", verdict.spec)
    x = verdict.table.x[1]
    assert isinstance(x, float)
    bounds = importlib.import_module("webui.paste_in.observe")._interval(spec.y, x)
    assert bounds is not None
    _points(verdict, payload)[1][1] = math.nextafter(bounds[1], math.inf).hex()
    assert not _matches(verdict, payload)


def test_o5_zero_crossing_interval_divisor_withholds() -> None:
    """O5: a finite host inverse still blocks when its interval denominator crosses zero."""
    verdict = formula_verdict(
        "1 / (np.sin(x) - np.cos(x))",
        bounds=("0.7853981633974483", "0.7853981633994483"),
        samples=41,
    )
    assert all(math.isfinite(y) for y in verdict.table.y)
    assert not _matches(verdict, observation_for(verdict))


def test_o5_outward_arithmetic_nonfinite_endpoint_withholds() -> None:
    """O5: a finite power near binary64 max cannot release with an infinite widened endpoint."""
    limit = "1.3407807929942596e+154"
    verdict = formula_verdict("x**2 * 1.0", bounds=(limit, limit), samples=2)
    y = verdict.table.y[0]
    assert math.isfinite(y)
    assert math.nextafter(math.nextafter(y, math.inf), math.inf) == math.inf
    assert not _matches(verdict, observation_for(verdict))
