# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.0 tool: the ONE model-visible callable over python mode.

Contract: `.agent/contracts/m10u0.md` predicate group T. Each docstring carries its predicate's
acceptance check; the check is the test's specification and the contract's wording wins wherever a
body would assert more.

Skeleton: each body is `pytest.skip`, retired at M10.0's close together with this line.

The tool is a transport, never an authority. It hands the model's exact bytes and the user's exact
uploaded bytes to `verify_python_source` and reports what that returns. Every predicate here exists
to keep a second opinion out of the verdict: no fixture answer, no echo of model text, no
normalization of the path the program named, no fall-back read of a file the caller does not own.
"""

import pytest

_TRACKER = "owned by **M10.0** (`.agent/spec.md` Deferred)"


def test_t1_exactly_one_model_visible_callable() -> None:
    """T1: OWUI's spec builder over the artifact returns one spec, reserved params absent.

    The parameter set equals the declared non-reserved set, so `__metadata__` and its siblings
    never reach the model.
    """
    pytest.skip(_TRACKER)


def test_t2_verdict_comes_from_verify_python_source_alone() -> None:
    """T2: a mutant returning the pass string for a refused program goes red.

    A second mutant that ignores the refusal code goes red too, so neither half of the verdict is
    reachable without the core.
    """
    pytest.skip(_TRACKER)


def test_t3_core_receives_the_uploaded_bytes_for_the_named_path() -> None:
    """T3: bytes handed to the core are byte-identical to the fake store's.

    A program naming a file the chat does not carry returns the refusal instead of verifying.
    """
    pytest.skip(_TRACKER)


def test_t4_return_text_is_closed_and_echoes_no_model_bytes() -> None:
    """T4: the return value is a member of the closed verdict set, refusal codes included.

    A program whose source carries a marker string returns text that does not contain it.
    """
    pytest.skip(_TRACKER)


def test_t5_target_is_the_named_path_with_the_uploaded_content() -> None:
    """T5: `DatasetTarget(path=<read_csv literal>, content=<uploaded bytes>)`, unnormalized.

    A program reading `/mnt/uploads/other.csv` against an attached `sales.csv` refuses
    `target_mismatch`; the path is compared byte-for-byte.
    """
    pytest.skip(_TRACKER)


def test_t6_file_access_is_ownership_checked() -> None:
    """T6: the ownership-checked accessor is the one called, with no fall-back path.

    A fake raising on a foreign id makes the tool refuse rather than read the file another way.
    """
    pytest.skip(_TRACKER)
