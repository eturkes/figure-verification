# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Numeric profile `binary64-libm-v1` — N1-N8 of `.agent/contracts/m13u5.md`.

The executed program is numpy float64 and rounds at EVERY operator, so the verifier evaluates the
projected tree operator by operator in binary64. An exact-rational engine rounding once at the end
would compute a number the program never computes; the more precise engine is the less faithful
one. Every comparison here is on BIT PATTERNS, never with a tolerance.

Skeleton: each body is `pytest.skip` and its docstring carries the predicate's acceptance check.
"""

import pytest


def test_n1_rounds_at_every_node() -> None:
    """Round-at-each-node, not exact-then-round.

    Accept: a witness expression where exact-rational-then-round and round-at-each-node differ;
    the evaluator must produce the round-at-each-node value AND it must equal numpy's on the same
    expression, compared as bit patterns.
    """
    pytest.skip("M13.5 skeleton")


def test_n2_literal_conversion_is_the_executed_float() -> None:
    """`Num(Fraction(0.1))` evaluates to the float64 `0.1`, never to a rounded `1/10`.

    Accept: hex-float literal comparison for `0.1` and for the non-binary decimal `0.2`
    (`assurance.md` exactness-witness law).
    """
    pytest.skip("M13.5 skeleton")


def test_n3_ieee_domain_results_instead_of_exceptions() -> None:
    """Domain and overflow faults reproduce numpy's IEEE values rather than raising.

    Accept: table-driven differential against numpy, compared on bit patterns, for `x/0` -> +-inf,
    `0/0` -> nan, `log(0)` -> -inf, `log(x<0)` -> nan, `sqrt(x<0)` -> nan, negative base with
    non-integral exponent -> nan, `exp` overflow -> inf. No `ValueError`, `ZeroDivisionError` or
    `OverflowError` escapes the evaluator.
    """
    pytest.skip("M13.5 skeleton")


def test_n4_non_finite_is_the_sole_domain_refusal() -> None:
    """Any non-finite reaching the table refuses `value_not_finite`, and nothing else does.

    Accept: one witness per N3 row reaches `value_not_finite`; a mutant that gives any single
    domain fault its own code kills no test that this one does not already kill.
    """
    pytest.skip("M13.5 skeleton")


def test_n5_constants_match_numpy() -> None:
    """`Const("pi")` and `Const("e")` are `math.pi` / `math.e` and bit-equal numpy's.

    Accept: hex-float literals asserted in both directions.
    """
    pytest.skip("M13.5 skeleton")


def test_n6_grid_matches_numpy_bit_for_bit() -> None:
    """Grid materialization reproduces `np.linspace` and `np.arange` exactly.

    Accept: differential against numpy over the M13.3 grid corpus, bit patterns, zero
    disagreements. `Grid.stop` is inclusive; `arange` bounds are integers only.
    """
    pytest.skip("M13.5 skeleton")


def test_n7_profile_splits_operators_into_two_classes() -> None:
    """`binary64-libm-v1` names a standard-exact class and a libm-dependent class.

    Accept: the class table is a hand-stated LITERAL in the test, never read from production
    (`assurance.md`: a test reading a production constant pins nothing). Standard-exact =
    `add sub mul div`, unary minus, `abs`, `sqrt`, literal conversion, `pi`, `e`, both grid
    constructors. libm-dependent = `sin cos tan exp log`, `pow`. The certificate's profile string
    is byte-pinned.
    """
    pytest.skip("M13.5 skeleton")


def test_n8_published_band_is_measured_including_pow() -> None:
    """The 1-ulp band is a measurement on a named environment pair, not a proof.

    Accept: the published band string names the pair and the sample size; `pow` carries its own
    measurement rather than inheriting the band, recorded in the contract's verdict table.
    """
    pytest.skip("M13.5 skeleton")
