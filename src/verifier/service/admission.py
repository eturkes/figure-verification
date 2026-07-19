# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Process-local admission for every expensive service POST.

One ``AdmissionController`` belongs to one Litestar application process and is shared by all
POST routes. A single lock protects both controls, so concurrent callers cannot overspend the
global token bucket or exceed the active-job ceiling. The bucket uses exact integer
minute-nanosecond credit: one token costs 60_000_000_000 units and an elapsed nanosecond adds
``work_rate_per_minute`` units. Fractional-token credit therefore survives every check without
float rounding or timer-interval truncation; capacity refusals consume no token.

``JobPermit`` starts route-owned, covering async model wait. ``run_sync`` transfers ownership to
the native worker before awaiting it. The await is shielded from request cancellation and the
worker releases the permit in its own ``finally`` block, so a cancelled request cannot expose
capacity while its uncancellable verification/render/archive work is still running. A route
exception before that transfer releases through the permit context manager instead.

This is logical, process-local admission, not a distributed quota or a CPU/memory reservation.
The canonical one-worker uvicorn deployment has one controller; adding processes multiplies the
configured aggregate rate and capacity.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import ParamSpec, TypeVar, cast

from litestar.concurrency import sync_to_thread

_P = ParamSpec("_P")
_T = TypeVar("_T")

_MINUTE_NS = 60_000_000_000
_ROUTE_OWNED = 0
_WORKER_OWNED = 1
_RELEASED = 2


class AdmissionController:
    """Lock-safe token bucket + nonblocking active-job gate for one service process."""

    def __init__(
        self,
        max_active_jobs: int,
        work_rate_per_minute: int,
        work_burst: int,
        *,
        clock: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._max_active_jobs = max_active_jobs
        self._work_rate_per_minute = work_rate_per_minute
        self._bucket_capacity = work_burst * _MINUTE_NS
        self._credit = self._bucket_capacity
        self._clock = clock
        self._updated_ns = clock()
        self._active_jobs = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> JobPermit | None:
        """Spend one rate token and active slot, or refuse immediately without waiting.

        Refill precedes both checks. An active-capacity refusal preserves all bucket credit; a
        rate refusal creates no active job. ``time.monotonic_ns`` cannot move backward, while an
        injected broken clock fails loudly instead of minting or deleting ambiguous credit.
        """
        with self._lock:
            # Sample under the same lock as `_updated_ns`: callers can read monotonic time in one
            # order yet acquire this lock in another, which would otherwise look like regression.
            now = self._clock()
            elapsed = now - self._updated_ns
            if elapsed < 0:
                msg = "admission monotonic clock moved backward"
                raise RuntimeError(msg)
            self._credit = min(
                self._bucket_capacity,
                self._credit + elapsed * self._work_rate_per_minute,
            )
            self._updated_ns = now
            if self._active_jobs >= self._max_active_jobs:
                return None
            if self._credit < _MINUTE_NS:
                return None
            self._credit -= _MINUTE_NS
            self._active_jobs += 1
        return JobPermit(self)

    def _release(self) -> None:
        """Return one active slot; only a live JobPermit calls this exactly once."""
        with self._lock:
            self._active_jobs -= 1


class JobPermit:
    """One admitted job, released by its route or transferred native worker exactly once."""

    def __init__(self, controller: AdmissionController) -> None:
        self._controller = controller
        self._owner = _ROUTE_OWNED
        self._lock = threading.Lock()
        # A cancelled outer request drops its run_sync frame after shield raises. Retaining the
        # inner task here keeps a strong reference until its callback observes completion.
        self._worker_task: asyncio.Task[object] | None = None

    def __enter__(self) -> JobPermit:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        with self._lock:
            release = self._owner == _ROUTE_OWNED
            if release:
                self._owner = _RELEASED
        if release:
            self._controller._release()

    async def run_sync(self, fn: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """Transfer this permit to ``fn``'s worker and await without cancel-propagation.

        ``asyncio.shield`` lets the request task receive cancellation immediately but keeps the
        inner Litestar worker task alive. The synchronous wrapper owns release after transfer,
        including when ``fn`` raises, so capacity remains occupied until native execution ends.
        """
        with self._lock:
            if self._owner != _ROUTE_OWNED:
                msg = "job permit is no longer route-owned"
                raise RuntimeError(msg)
            self._owner = _WORKER_OWNED

        def call_and_release() -> _T:
            return self._call_and_release(fn, *args, **kwargs)

        try:
            worker = asyncio.create_task(sync_to_thread(call_and_release))
        except BaseException:
            with self._lock:
                self._owner = _RELEASED
            self._controller._release()
            raise
        worker_object = cast("asyncio.Task[object]", worker)
        self._worker_task = worker_object
        worker_object.add_done_callback(self._observe_worker)
        return await asyncio.shield(worker)

    def _call_and_release(self, fn: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return fn(*args, **kwargs)
        finally:
            with self._lock:
                self._owner = _RELEASED
            self._controller._release()

    def _observe_worker(self, task: asyncio.Future[object]) -> None:
        """Retain no completed task and observe any exception after caller cancellation."""
        _ = task.exception()
        self._worker_task = None
