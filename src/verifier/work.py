# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Consumer-neutral run-local logical-work admission.

A meter admits each consumer-defined non-negative charge atomically before the guarded work;
refusal preserves the prior count and reports the exact limit, consumption, and requested cost.
"""

from dataclasses import dataclass

__all__ = ["WorkBudget", "WorkBudgetExceededError"]


class WorkBudgetExceededError(Exception):
    """One atomic charge that would cross a cumulative work ceiling."""

    def __init__(self, *, limit: int, consumed: int, required: int) -> None:
        message = f"work limit {limit}: {consumed} consumed + {required} required"
        super().__init__(message)
        self.limit = limit
        self.consumed = consumed
        self.required = required


@dataclass(slots=True)
class WorkBudget:
    """Mutable cumulative meter shared across every operation in one consumer run."""

    limit: int
    consumed: int = 0

    def __post_init__(self) -> None:
        if type(self.limit) is not int or self.limit < 0:
            msg = f"work limit must be a non-negative integer, got {self.limit!r}"
            raise ValueError(msg)
        if type(self.consumed) is not int or not 0 <= self.consumed <= self.limit:
            msg = (
                "work consumption must be an integer between zero and the limit, "
                f"got {self.consumed!r}"
            )
            raise ValueError(msg)

    def charge(self, required: int) -> None:
        """Admit ``required`` atomically, or leave consumption unchanged and refuse."""
        if type(required) is not int or required < 0:
            msg = f"required work must be a non-negative integer, got {required!r}"
            raise ValueError(msg)
        if required > self.limit - self.consumed:
            raise WorkBudgetExceededError(
                limit=self.limit,
                consumed=self.consumed,
                required=required,
            )
        self.consumed += required
