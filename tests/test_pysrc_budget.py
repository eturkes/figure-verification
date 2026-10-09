# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The shared work meter: its own guards + the atomic charge (`verifier.pysrc.budget`).

The figure judge and the CSV reader charge it; its construction + argument guards lost their
witnesses when the JSON-spec evaluator suites retired (M19.7a).
"""

import pytest

from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError


@pytest.mark.parametrize("limit", [-1, 1.0, True], ids=["negative", "float", "bool"])
def test_a_limit_that_is_no_non_negative_int_refuses(limit: object) -> None:
    with pytest.raises(ValueError, match="work limit must be a non-negative integer"):
        WorkBudget(limit)  # type: ignore[arg-type]


@pytest.mark.parametrize("consumed", [-1, 4, 1.0], ids=["negative", "over-limit", "float"])
def test_consumption_outside_zero_to_the_limit_refuses(consumed: object) -> None:
    with pytest.raises(ValueError, match="work consumption must be an integer"):
        WorkBudget(3, consumed)  # type: ignore[arg-type]


@pytest.mark.parametrize("required", [-1, 1.0, True], ids=["negative", "float", "bool"])
def test_a_charge_that_is_no_non_negative_int_refuses(required: object) -> None:
    budget = WorkBudget(3)
    with pytest.raises(ValueError, match="required work must be a non-negative integer"):
        budget.charge(required)  # type: ignore[arg-type]
    assert budget.consumed == 0


def test_a_charge_admits_up_to_the_limit_and_refuses_past_it_atomically() -> None:
    budget = WorkBudget(3, 1)
    budget.charge(2)
    assert budget.consumed == 3
    with pytest.raises(WorkBudgetExceededError) as refused:
        budget.charge(1)
    assert (refused.value.limit, refused.value.consumed, refused.value.required) == (3, 3, 1)
    assert str(refused.value) == "work limit 3: 3 consumed + 1 required"
    assert budget.consumed == 3
