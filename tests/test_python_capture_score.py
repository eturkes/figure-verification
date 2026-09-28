# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.9 scorer: the held-out acceptance measurement and its EXACTLY-ONCE guard.

Contract: `.agent/contracts/m10u9.md` predicate group S. Each docstring carries its predicate's
acceptance check; the contract's wording wins wherever a body would assert more.

Skeleton: each body is `pytest.skip` until M10.9's implementation lands. The close deletes every
skip, this line, and nothing else.
"""

import pytest


def test_s1_three_outcomes_and_no_verifier_call_on_transport() -> None:
    """S1: a non-200 record scores `transport_error` with the verifier never called; a 200 record
    scores `verified` or `refused` + code through `verify_python_source` over the de-fenced source.
    Accept: a call-counting bomb stays at 0 for a transport row; one witness per outcome."""
    pytest.skip("M10.9 skeleton: the scorer is unwritten.")


def test_s2_the_declared_target_comes_from_the_record() -> None:
    """S2: the target is the record's `dataset_name` over tracked CSV bytes. Accept: a program
    reading `/mnt/uploads/weather.csv` on a `sales.csv` record scores `refused`."""
    pytest.skip("M10.9 skeleton: the scorer is unwritten.")


def test_s3_denominators_exclude_sentinels_and_keep_transport_rows() -> None:
    """S3: category totals count held-out rows only; a transport row stays in its denominator and
    enters neither numerator. Accept: a planted third sentinel moves no denominator; a complicated
    transport row lowers `blocked`."""
    pytest.skip("M10.9 skeleton: the scorer is unwritten.")


def test_s4_acceptance_boundaries() -> None:
    """S4: `acceptance_met` = complete, no transport rows, 10*v >= 7*t per category, both sentinel
    outcomes. Accept: 14/20 true, 13/20 false per category; each sentinel flip, one transport row
    and one missing row each false alone."""
    pytest.skip("M10.9 skeleton: the scorer is unwritten.")


def test_s5_per_row_table_shape() -> None:
    """S5: one row per record sorted by `prompt_id` with the contract's exact key set; `code`
    non-null iff refused; `mark/x/y/reduction` non-null iff verified. Accept: key set + both
    iff-conjuncts over a mixed run."""
    pytest.skip("M10.9 skeleton: the scorer is unwritten.")


def test_s6_score_bytes_are_deterministic_and_strict() -> None:
    """S6: two derivations are byte-identical and the encoded file decodes strictly. Accept: equal
    bytes + a planted unknown key refused."""
    pytest.skip("M10.9 skeleton: the scorer is unwritten.")


def test_s7_cli_rc_tracks_drift_never_acceptance() -> None:
    """S7: `python -m capture score` bare = re-derive + compare, rc 1 on drift or a missing
    `score.json`; rc never depends on `acceptance_met`. Accept: a met and an unmet score both rc 0,
    a drifted one rc 1."""
    pytest.skip("M10.9 skeleton: the scorer is unwritten.")


def test_s8_exactly_once_guard() -> None:
    """S8: `heldout_guard(root)` is empty only for exactly one complete `m10-heldout` run with a
    `score.json`. Accept: 0, 1, 2 held-out runs give 1, 0, 1 failures; a wrong name, a missing
    row and an absent `score.json` give 1 failure each."""
    pytest.skip("M10.9 skeleton: the scorer is unwritten.")
