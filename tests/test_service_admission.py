# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M5.1f process-local rate + active-job admission tests.

Pins exact integer token refill, lock-safe concurrent admission, capacity-without-token-spend,
permit release on every ownership path, all-POST integration, transport-validation precedence,
RFC-9457 refusal shape, and the cancellation invariant: a cancelled request cannot return its
active slot until the uncancellable native worker actually exits.
"""

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import msgspec
import pytest
from litestar.datastructures import State
from litestar.testing import TestClient

from verifier.checks import CheckResult
from verifier.service import app as app_module
from verifier.service.admission import AdmissionController, JobPermit
from verifier.service.models import Verdict
from verifier.service.pipeline import Outcome
from verifier.service.settings import Settings

_JSON = {"content-type": "application/json"}
_PROBLEM_JSON = "application/problem+json"
_MINUTE_NS = 60_000_000_000


class _Clock:
    """Mutable exact nanosecond clock injected into AdmissionController."""

    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now


def _take_and_release(admission: AdmissionController) -> bool:
    permit = admission.try_acquire()
    if permit is None:
        return False
    with permit:
        pass
    return True


def _failed_outcome() -> Outcome:
    result = CheckResult(
        check="spec.decode",
        method="schema_validation",
        status="fail",
        severity="blocking",
        message="test refusal",
    )
    return Outcome(verdict=Verdict(verified=False, layer="decode", results=(result,)))


def test_token_bucket_refill_is_exact_and_burst_bounded() -> None:
    # rate=2/minute => half a token per 15 seconds. The two initial burst tokens drain exactly;
    # two 15-second checks preserve fractional credit and jointly mint one token. A later full
    # minute refills only to the two-token burst cap, never beyond it.
    clock = _Clock()
    admission = AdmissionController(1, 2, 2, clock=clock)
    assert _take_and_release(admission)
    assert _take_and_release(admission)
    assert not _take_and_release(admission)

    clock.now = _MINUTE_NS // 4
    assert not _take_and_release(admission)
    clock.now = _MINUTE_NS // 2
    assert _take_and_release(admission)

    clock.now += _MINUTE_NS
    assert _take_and_release(admission)
    assert _take_and_release(admission)
    assert not _take_and_release(admission)


def test_capacity_refusal_does_not_spend_rate_credit() -> None:
    clock = _Clock()
    admission = AdmissionController(1, 1, 2, clock=clock)
    held = admission.try_acquire()
    assert held is not None
    # The second token remains untouched while capacity is full. Releasing the active slot makes
    # that exact token immediately usable despite zero elapsed time.
    assert admission.try_acquire() is None
    with held:
        pass
    assert _take_and_release(admission)
    assert admission.try_acquire() is None


def test_injected_clock_must_remain_monotonic() -> None:
    clock = _Clock()
    admission = AdmissionController(1, 1, 1, clock=clock)
    clock.now = -1
    with pytest.raises(RuntimeError, match="clock moved backward"):
        admission.try_acquire()


def test_concurrent_callers_cannot_overspend_bucket_or_capacity() -> None:
    # Sixteen callers cross one barrier together. Both ceilings are four, so exactly four permits
    # may exist while their workers wait; the other twelve must refuse without racing the counters.
    admission = AdmissionController(4, 1, 4, clock=lambda: 0)
    callers = 16
    barrier = threading.Barrier(callers + 1)
    release = threading.Event()
    recorded = threading.Event()
    result_lock = threading.Lock()
    results: list[bool] = []

    def attempt() -> None:
        barrier.wait()
        permit = admission.try_acquire()
        with result_lock:
            results.append(permit is not None)
            if len(results) == callers:
                recorded.set()
        if permit is not None:
            release.wait()
            with permit:
                pass

    threads = [threading.Thread(target=attempt) for _ in range(callers)]
    for thread in threads:
        thread.start()
    barrier.wait()
    assert recorded.wait(timeout=2)
    assert sum(results) == 4
    release.set()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_concurrent_callers_sample_clock_inside_accounting_lock() -> None:
    # A monotonic clock can be sampled by A before B while B acquires the accounting lock first;
    # treating that ordinary lock-order inversion as clock regression would turn concurrency into
    # a 500. Block A inside the injected clock: B must not reach its own sample until A is released,
    # proving the timestamp read and `_updated_ns` transition share one lock.
    first_sample = threading.Event()
    second_started = threading.Event()
    second_sample = threading.Event()
    release_first = threading.Event()
    clock_lock = threading.Lock()
    clock_calls = 0

    def clock() -> int:
        nonlocal clock_calls
        with clock_lock:
            call = clock_calls
            clock_calls += 1
        if call == 1:
            first_sample.set()
            release_first.wait()
        elif call == 2:
            second_sample.set()
        return call

    admission = AdmissionController(2, 1, 2, clock=clock)  # call 0 initializes the clock
    permits: list[JobPermit | None] = []
    errors: list[BaseException] = []

    def acquire(started: threading.Event | None = None) -> None:
        if started is not None:
            started.set()
        try:
            permits.append(admission.try_acquire())
        except BaseException as exc:  # capture a clock-regression fault from the test thread
            errors.append(exc)

    first = threading.Thread(target=acquire)
    second = threading.Thread(target=acquire, args=(second_started,))
    first.start()
    assert first_sample.wait(timeout=2)
    second.start()
    assert second_started.wait(timeout=2)
    sampled_while_first_blocked = second_sample.wait(timeout=0.1)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not sampled_while_first_blocked
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert len(permits) == 2
    for permit in permits:
        assert permit is not None
        with permit:
            pass


def test_worker_success_exception_and_route_exception_release_permits() -> None:
    async def exercise() -> None:
        admission = AdmissionController(1, 1, 4, clock=lambda: 0)

        def add(left: int, *, right: int) -> int:
            return left + right

        first = admission.try_acquire()
        assert first is not None
        with first:
            result = await first.run_sync(add, 2, right=3)
        assert result == 5
        with pytest.raises(RuntimeError, match="no longer route-owned"):
            await first.run_sync(lambda: None)

        second = admission.try_acquire()
        assert second is not None

        def fail() -> None:
            msg = "native failure"
            raise ValueError(msg)

        with second, pytest.raises(ValueError, match="native failure"):
            await second.run_sync(fail)

        # A failure before ownership transfers models an async proposer exception: __exit__ owns
        # release. The fourth acquisition proves all prior active slots returned exactly once.
        third = admission.try_acquire()
        assert third is not None
        with pytest.raises(LookupError), third:
            raise LookupError
        fourth = admission.try_acquire()
        assert fourth is not None
        with fourth:
            pass

    asyncio.run(exercise())


class _RawJsonRequest:
    """Minimal Request shape used to cancel the real verify-only route coroutine."""

    content_type: tuple[str, dict[str, str]] = ("application/json", {})

    async def body(self) -> bytes:
        return b"{}"


def test_cancelled_route_holds_slot_until_native_worker_finishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entered = threading.Event()
    finish = threading.Event()
    returned = threading.Event()

    def slow_verify(_raw: bytes, _settings: Settings) -> Outcome:
        entered.set()
        if not finish.wait(timeout=5):
            msg = "test worker was never released"
            raise RuntimeError(msg)
        returned.set()
        return _failed_outcome()

    monkeypatch.setattr(app_module, "verify_only", slow_verify)
    admission = AdmissionController(1, 1, 2, clock=lambda: 0)
    state = State({"settings": Settings(data_dir=tmp_path), "admission": admission})

    async def exercise() -> None:
        request = cast("Any", _RawJsonRequest())
        handler = cast("Any", app_module.verify_only_route.fn)
        route: asyncio.Task[Verdict] = asyncio.create_task(handler(request, state))
        assert await asyncio.to_thread(entered.wait, 2)

        route.cancel()
        with pytest.raises(asyncio.CancelledError):
            await route
        # The request coroutine is gone, but its run_in_executor work is uncancellable. Capacity
        # must stay occupied; enough rate credit remains, so None proves capacity rather than rate.
        assert admission.try_acquire() is None

        finish.set()
        assert await asyncio.to_thread(returned.wait, 2)
        replacement: JobPermit | None = None
        for _ in range(100):
            replacement = admission.try_acquire()
            if replacement is not None:
                break
            await asyncio.sleep(0.001)
        assert replacement is not None
        with replacement:
            pass

    asyncio.run(exercise())


def test_every_post_refuses_before_work_but_after_transport_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: list[str] = []

    def unexpected(name: str) -> Callable[..., Outcome]:
        def call(*_args: object, **_kwargs: object) -> Outcome:
            called.append(name)
            return _failed_outcome()

        return call

    async def unexpected_propose(*_args: object, **_kwargs: object) -> bytes:
        called.append("propose")
        return b"{}"

    monkeypatch.setattr(app_module, "verify_only", unexpected("verify-only"))
    monkeypatch.setattr(app_module, "verify_and_render", unexpected("verify-and-render"))
    monkeypatch.setattr(app_module, "propose_spec", unexpected_propose)
    settings = Settings(
        data_dir=tmp_path,
        max_body_bytes=64,
        max_active_jobs=1,
        work_rate_per_minute=1,
        work_burst=10,
    )
    app = app_module.create_app(settings)
    admission = cast("AdmissionController", app.state["admission"])
    held = admission.try_acquire()
    assert held is not None
    propose_body = msgspec.json.encode({"user_request": "x", "dataset_name": "sales.csv"})

    with TestClient(app=app) as client, held:
        refused = (
            client.post("/verify-only", content=b"{}", headers=_JSON),
            client.post("/verify-and-render", content=b"{}", headers=_JSON),
            client.post("/propose-spec", content=propose_body, headers=_JSON),
        )
        for response in refused:
            assert response.status_code == 429
            assert response.headers["content-type"] == _PROBLEM_JSON
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.json() == {
                "title": "Too Many Requests",
                "status": 429,
                "detail": "the process-local verifier work limit is currently exhausted",
            }

        # Body/media/query shape gates precede admission, so a full active slot cannot turn their
        # established 4xx outcomes into 429 or consume model/verifier work.
        assert (
            client.post(
                "/verify-only", content=b"{}", headers={"content-type": "text/plain"}
            ).status_code
            == 415
        )
        assert client.post("/verify-only", content=b"x" * 65, headers=_JSON).status_code == 413
        assert client.post("/propose-spec", content=b"{}", headers=_JSON).status_code == 400
        assert (
            client.post(
                "/verify-and-render?include_html=maybe", content=b"{}", headers=_JSON
            ).status_code
            == 400
        )
    assert called == []


def test_rate_exhaustion_returns_429_without_second_worker_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0

    def fast_verify(_raw: bytes, _settings: Settings) -> Outcome:
        nonlocal calls
        calls += 1
        return _failed_outcome()

    monkeypatch.setattr(app_module, "verify_only", fast_verify)
    app = app_module.create_app(
        Settings(
            data_dir=tmp_path,
            max_active_jobs=1,
            work_rate_per_minute=1,
            work_burst=1,
        )
    )
    with TestClient(app=app) as client:
        assert client.post("/verify-only", content=b"{}", headers=_JSON).status_code == 200
        refused = client.post("/verify-only", content=b"{}", headers=_JSON)
    assert refused.status_code == 429
    assert refused.headers["content-type"] == _PROBLEM_JSON
    assert calls == 1
