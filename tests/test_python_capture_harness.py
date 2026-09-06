# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Red suite for M12.6b — the capture INSTRUMENT (live driver + offline derived stats).

One test per check-set row of .agent/contracts/m12u6b.md; each docstring states that row's OWN
acceptance check. Authored diff-blind against the contract, never against capture/harness.py.

Hardware-free: every live-transport row drives httpx.MockTransport, so no backend, no accelerator
and no network are reachable from this file. The positive control is the committed golden run
tests/golden/capture-golden-v1/, whose statistic is HAND-STATED here rather than re-derived.

capture/ sits outside the coverage source, so a predicate without a near-miss refusal test ships
unpinned: every row below must refuse a near miss of the SAME family, not only a generic outsider.
"""

import ast
import hashlib
import json
import shutil
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx
import msgspec
import pytest

import capture.harness as harness_module  # type: ignore[import-not-found,unused-ignore]
from capture.corpus import CATEGORIES, Kind, Prompt, load_corpus, render_capture_prompt
from capture.harness import (
    CHAT_PATH,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT,
    HEALTH_PATH,
    MAX_PARSE_BYTES,
    NO_STATUS,
    STATS_NAME,
    STATS_PREDICATES,
    STATS_VERSION,
    CaptureConfig,
    CaptureStats,
    Outcome,
    SentinelStat,
    StatBlock,
    StatsRun,
    capture_one,
    defence,
    derive_stats,
    encode_stats,
    load_stats_run,
    main,
    parses,
    run_capture,
    select_rows,
    validate_stats,
    write_stats,
)
from capture.record import (
    BANNED_REQUEST_KEYS,
    CAPTURE_MODE,
    RECORDS_NAME,
    REQUEST_KEYS,
    RUN_NAME,
    CaptureRecord,
    Provenance,
    RepoProvenance,
    Run,
    RunManifest,
    ServiceProvenance,
    Usage,
    build_record,
    build_request_body,
    check_outcome_shape,
    encode_records,
    encode_run,
    load_run,
    validate,
    write_run,
)

_GOLDEN_ROOT = Path(__file__).parent / "golden" / "capture-golden-v1"
_MODEL = "Qwen2.5-Coder-0.5B-Instruct"
_BASE_URL = "http://backend.test"
_MAX_TOKENS = 257
_TEMPERATURE = 0.2
_ZERO_SHA256 = "0" * 64


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _prompt(kind: Kind, prompt_id: str) -> Prompt:
    return next(
        prompt
        for row_kind, prompt in load_corpus().rows()
        if row_kind == kind and prompt.id == prompt_id
    )


def _provenance() -> Provenance:
    return Provenance(
        repo=RepoProvenance(
            git_commit=None,
            git_dirty=False,
            model_repo_id="Qwen/Qwen2.5-Coder-0.5B-Instruct",
            model_revision="ea3f2471cf1b1f0db85067f1ef93848e38e88c25",
            engine_dtype="float16",
            runtime_lock_sha256=_ZERO_SHA256,
            capture_prompt_sha256=(
                "a18162f788cce976a55458545c5761e2fd5b8b924e116ac137ffc4deb004964e"
            ),
        ),
        service=ServiceProvenance(
            model_name=_MODEL,
            device="fixture-device",
            structured_output=True,
        ),
        host=None,
    )


def _manifest(  # noqa: PLR0913 — one fixture knob per manifest identity field
    directory: Path,
    *,
    kind: Kind = "design",
    record_count: int = 0,
    model: str = _MODEL,
    base_url: str = _BASE_URL,
    max_tokens: int = _MAX_TOKENS,
    temperature: float = _TEMPERATURE,
) -> RunManifest:
    return RunManifest(
        version="python-capture-1",
        mode="python_raw_unconstrained",
        run=directory.name,
        kind=kind,
        model=model,
        model_base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
        record_count=record_count,
        provenance=_provenance(),
    )


def _request_body(
    prompt: Prompt,
    *,
    model: str = _MODEL,
    max_tokens: int = _MAX_TOKENS,
    temperature: float = _TEMPERATURE,
) -> bytes:
    return build_request_body(
        prompt=render_capture_prompt(prompt),
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _record(  # noqa: PLR0913 — one fixture knob per disjoint outcome field
    *,
    directory: Path,
    kind: Kind,
    prompt: Prompt,
    http_status: int = 200,
    content: str | None = "x = 1\n",
    finish_reason: str | None = "stop",
    usage: Usage | None = None,
    error: str | None = None,
) -> CaptureRecord:
    if http_status != 200:
        content = None
        finish_reason = None
        usage = None
        error = error or f"backend returned {http_status}"
    elif usage is None:
        usage = Usage(prompt_tokens=11, completion_tokens=7, total_tokens=18)
    return build_record(
        run=directory.name,
        prompt=prompt,
        kind=kind,
        request_body=_request_body(prompt),
        http_status=http_status,
        content=content,
        finish_reason=finish_reason,
        usage=usage,
        error=error,
    )


def _run(directory: Path, records: tuple[CaptureRecord, ...], *, kind: Kind = "design") -> Run:
    ordered = tuple(sorted(records, key=lambda record: record.prompt_id))
    manifest = _manifest(directory, kind=kind, record_count=len(ordered))
    return Run(
        directory=directory,
        manifest=manifest,
        records=ordered,
        run_bytes=encode_run(manifest),
        records_bytes=encode_records(ordered),
    )


def _golden_stats() -> CaptureStats:
    by_category: dict[str, StatBlock] = {
        "simple": StatBlock(
            records=1,
            replies=1,
            fenced=0,
            parsed=1,
            truncated=0,
            fence_rate=0.0,
            parse_rate=1.0,
            truncation_rate=0.0,
        ),
        "complicated": StatBlock(
            records=1,
            replies=1,
            fenced=0,
            parsed=0,
            truncated=1,
            fence_rate=0.0,
            parse_rate=0.0,
            truncation_rate=1.0,
        ),
    }
    return CaptureStats(
        version="python-capture-stats-1",
        mode="python_raw_unconstrained",
        run="capture-golden-v1",
        kind="design",
        record_count=3,
        by_category=by_category,
        sentinels=(
            SentinelStat(
                prompt_id="sentinel-simple",
                category="simple",
                http_status=503,
                fenced=None,
                parsed=None,
                truncated=None,
            ),
        ),
    )


def _golden_directory(tmp_path: Path, name: str = "capture-golden-v1") -> Path:
    directory = tmp_path / name
    directory.mkdir()
    shutil.copy2(_GOLDEN_ROOT / RUN_NAME, directory / RUN_NAME)
    shutil.copy2(_GOLDEN_ROOT / RECORDS_NAME, directory / RECORDS_NAME)
    write_stats(directory, _golden_stats())
    return directory


def _with_stats(stats_run: StatsRun, **changes: object) -> StatsRun:
    stats = msgspec.structs.replace(stats_run.stats, **changes)
    return msgspec.structs.replace(
        stats_run,
        stats=stats,
        stats_bytes=encode_stats(stats),
    )


def _stats_failure_ids(
    stats_run: StatsRun, predicate_ids: tuple[str, ...] = ("S1", "S2", "S3", "S4")
) -> set[str]:
    return {
        predicate_id for predicate_id in predicate_ids if STATS_PREDICATES[predicate_id](stats_run)
    }


def _failure_ids(failures: list[str]) -> set[str]:
    return {failure.split(":", 1)[0] for failure in failures}


def _json_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()


def _ok_response(content: str = "x = 1\n", finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "fixture-completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        },
    )


def _capture(
    prompt: Prompt,
    responder: Callable[[httpx.Request], httpx.Response],
) -> Outcome:
    expected = _request_body(prompt)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL(f"{_BASE_URL}{CHAT_PATH}")
        assert request.headers["content-type"] == "application/json"
        assert request.content == expected
        return responder(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return capture_one(
            client,
            base_url=_BASE_URL,
            prompt=prompt,
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
        )


def _assert_fault(
    outcome: Outcome,
    *,
    expected_status: int,
    error_fragments: tuple[str, ...],
    directory: Path,
    prompt: Prompt,
) -> None:
    assert outcome.http_status == expected_status
    assert outcome.content is None
    assert outcome.finish_reason is None
    assert outcome.usage is None
    assert outcome.error is not None
    assert all(fragment in outcome.error for fragment in error_fragments)
    record = build_record(
        run=directory.name,
        prompt=prompt,
        kind="design",
        request_body=_request_body(prompt),
        http_status=outcome.http_status,
        content=outcome.content,
        finish_reason=outcome.finish_reason,
        usage=outcome.usage,
        error=outcome.error,
    )
    assert check_outcome_shape(_run(directory, (record,))) == []


def _run_driver(
    client: httpx.Client,
    directory: Path,
    rows: tuple[tuple[Kind, Prompt], ...],
) -> tuple[CaptureRecord, ...]:
    return run_capture(
        client,
        directory,
        rows=rows,
        kind="design",
        config=CaptureConfig(
            base_url=_BASE_URL,
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
        ),
        provenance=_provenance(),
        progress=False,
    )


def _main_rc(argv: list[str]) -> int:
    try:
        return main(argv)
    except SystemExit as exc:
        assert isinstance(exc.code, int)
        return exc.code


def _seed_cli_run(
    directory: Path,
    prompt: Prompt,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    content: str = "old = True\n",
) -> CaptureRecord:
    request_body = build_request_body(
        prompt=render_capture_prompt(prompt),
        model=_MODEL,
        max_tokens=max_tokens,
        temperature=0.0,
    )
    record = build_record(
        run=directory.name,
        prompt=prompt,
        kind="design",
        request_body=request_body,
        http_status=200,
        content=content,
        finish_reason="stop",
        usage=Usage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        error=None,
    )
    manifest = _manifest(
        directory,
        record_count=1,
        base_url=DEFAULT_BASE_URL,
        max_tokens=max_tokens,
        temperature=0.0,
    )
    write_run(directory, manifest, (record,))
    write_stats(directory, derive_stats(load_run(directory)))
    return record


def _patch_cli_world(
    monkeypatch: pytest.MonkeyPatch,
    captures_root: Path,
    rows: tuple[tuple[Kind, Prompt], ...],
    responder: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    real_client = httpx.Client
    requests: list[httpx.Request] = []

    def traced(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responder(request)

    def client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        assert "transport" not in kwargs
        return real_client(*args, transport=httpx.MockTransport(traced), **kwargs)

    def selected(
        _corpus: object, kind: Kind, *, sentinels: bool
    ) -> tuple[tuple[Kind, Prompt], ...]:
        assert kind == "design"
        assert sentinels is False
        return rows

    provenance = _provenance()
    monkeypatch.setattr(harness_module, "CAPTURES_ROOT", captures_root)
    monkeypatch.setattr(harness_module, "select_rows", selected)
    monkeypatch.setattr(
        harness_module,
        "collect_repo_provenance",
        lambda *_args, **_kwargs: provenance.repo,
    )
    monkeypatch.setattr(
        harness_module,
        "collect_host_provenance",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("capture.harness.httpx.Client", client_factory)
    return requests


def test_s_shape(tmp_path: Path) -> None:
    """S-shape — S1 + S2 + S4 each fail on one mutation of the golden stats and nothing else.

    Accept when: a foreign ``version`` and a foreign ``mode`` each fail S1 alone; a ``run``,
    ``kind`` or ``record_count`` disagreeing with the run manifest fails S2 alone; a dropped or
    extra ``by_category`` key, a sentinel row that is not one of the run's sentinel records, and a
    category block whose ``records`` sum plus the sentinel count misses ``record_count`` each fail
    S4 alone. The unmodified golden yields no S-failure at all.
    """
    stats_run = load_stats_run(_golden_directory(tmp_path))
    assert tuple(STATS_PREDICATES) == ("S1", "S2", "S3", "S4")
    assert _stats_failure_ids(stats_run) == set()

    shape_ids = ("S1", "S2", "S4")
    s1_mutations: tuple[dict[str, object], ...] = (
        {"version": "python-capture-stats-0"},
        {"mode": "vplot_json_guided"},
    )
    for changes in s1_mutations:
        assert _stats_failure_ids(_with_stats(stats_run, **changes), shape_ids) == {"S1"}
    s2_mutations: tuple[dict[str, object], ...] = (
        {"run": "capture-golden-near-miss"},
        {"kind": "heldout"},
        {"record_count": 4},
    )
    for changes in s2_mutations:
        assert _stats_failure_ids(_with_stats(stats_run, **changes), shape_ids) == {"S2"}

    dropped = dict(stats_run.stats.by_category)
    dropped.pop("complicated")
    extra: dict[str, StatBlock] = dict(stats_run.stats.by_category)
    extra["simple-near-miss"] = stats_run.stats.by_category["simple"]
    alien_sentinel = msgspec.structs.replace(
        stats_run.stats.sentinels[0], prompt_id="sentinel-complicated"
    )
    simple = stats_run.stats.by_category["simple"]
    wrong_sum = dict(stats_run.stats.by_category)
    wrong_sum["simple"] = msgspec.structs.replace(simple, records=2)
    s4_mutations: tuple[dict[str, object], ...] = (
        {"by_category": dropped},
        {"by_category": extra},
        {"sentinels": (alien_sentinel,)},
        {"by_category": wrong_sum},
    )
    for changes in s4_mutations:
        assert _stats_failure_ids(_with_stats(stats_run, **changes), shape_ids) == {"S4"}


def test_s3_reproduce(tmp_path: Path) -> None:
    """S3 — the committed stats.json IS the re-derivation from the committed records.

    Accept when: ``validate_stats`` returns ``[]`` on the golden, and a stats.json edited by one
    count, one rate digit, or one key-order swap fails S3 while the records stay untouched.
    """
    directory = _golden_directory(tmp_path)
    stats_path = directory / STATS_NAME
    original = stats_path.read_bytes()
    assert validate_stats(directory) == []

    count_doc: dict[str, Any] = json.loads(original)
    count_doc["by_category"]["simple"]["fenced"] = 1
    rate_doc: dict[str, Any] = json.loads(original)
    rate_doc["by_category"]["simple"]["parse_rate"] = 0.9
    order_doc: dict[str, Any] = json.loads(original)
    blocks = order_doc["by_category"]
    order_doc["by_category"] = {
        "complicated": blocks["complicated"],
        "simple": blocks["simple"],
    }

    for mutant in (_json_bytes(count_doc), _json_bytes(rate_doc), _json_bytes(order_doc)):
        stats_path.write_bytes(mutant)
        assert _failure_ids(validate_stats(directory)) == {"S3"}
    stats_path.write_bytes(original)
    assert validate_stats(directory) == []


def test_h1_body_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H1 — every outbound body is build_request_body's bytes and nothing else.

    Accept when: the content captured by the mock transport equals
    ``build_request_body(prompt=render_capture_prompt(row), model=…, max_tokens=…,
    temperature=…)`` byte for byte, the emitted record's ``request_sha256`` is that sha256, and the
    request key set is exactly ``REQUEST_KEYS`` with no member of ``BANNED_REQUEST_KEYS``.
    """
    prompt = _prompt("design", "design-simple-01")
    row: tuple[Kind, Prompt] = ("design", prompt)
    directory = tmp_path / "h1-run"
    expected = _request_body(prompt)
    builder_calls: list[tuple[str, str, int, float]] = []
    original_builder: Callable[..., bytes] = build_request_body

    def traced_builder(*, prompt: str, model: str, max_tokens: int, temperature: float) -> bytes:
        builder_calls.append((prompt, model, max_tokens, temperature))
        return original_builder(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    monkeypatch.setattr(harness_module, "build_request_body", traced_builder)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL(f"{_BASE_URL}{CHAT_PATH}")
        assert request.headers["content-type"] == "application/json"
        assert request.content == expected
        return _ok_response()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert len(_run_driver(client, directory, (row,))) == 1

    assert builder_calls == [(render_capture_prompt(prompt), _MODEL, _MAX_TOKENS, _TEMPERATURE)]
    captured = load_run(directory)
    assert len(captured.records) == 1
    record = captured.records[0]
    assert record.request_sha256 == _sha256(expected)
    assert REQUEST_KEYS == ("max_tokens", "messages", "model", "temperature")
    assert record.request_keys == ("max_tokens", "messages", "model", "temperature")
    assert not (set(record.request_keys) & BANNED_REQUEST_KEYS)


def test_h2_row_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """H2 — run scope is the manifest's kind plus the sentinels, in corpus order.

    Accept when: ``design`` selects the 48 design rows followed by both sentinels in corpus order,
    the no-sentinels form selects exactly 48, and ``--kind heldout`` without the acknowledgement
    flag exits non-zero having issued ZERO requests through the transport.
    """
    expected_ids = (
        "design-simple-01",
        "design-simple-02",
        "design-simple-03",
        "design-simple-04",
        "design-simple-05",
        "design-simple-06",
        "design-simple-07",
        "design-simple-08",
        "design-simple-09",
        "design-simple-10",
        "design-simple-11",
        "design-simple-12",
        "design-simple-13",
        "design-simple-14",
        "design-simple-15",
        "design-simple-16",
        "design-simple-17",
        "design-simple-18",
        "design-simple-19",
        "design-simple-20",
        "design-simple-21",
        "design-simple-22",
        "design-simple-23",
        "design-simple-24",
        "design-complicated-01",
        "design-complicated-02",
        "design-complicated-03",
        "design-complicated-04",
        "design-complicated-05",
        "design-complicated-06",
        "design-complicated-07",
        "design-complicated-08",
        "design-complicated-09",
        "design-complicated-10",
        "design-complicated-11",
        "design-complicated-12",
        "design-complicated-13",
        "design-complicated-14",
        "design-complicated-15",
        "design-complicated-16",
        "design-complicated-17",
        "design-complicated-18",
        "design-complicated-19",
        "design-complicated-20",
        "design-complicated-21",
        "design-complicated-22",
        "design-complicated-23",
        "design-complicated-24",
        "sentinel-simple",
        "sentinel-complicated",
    )
    corpus = load_corpus()
    selected = select_rows(corpus, "design", sentinels=True)
    assert tuple(prompt.id for _, prompt in selected) == expected_ids
    assert tuple(kind for kind, _ in selected) == ("design",) * 48 + ("sentinels",) * 2

    without_sentinels = select_rows(corpus, "design", sentinels=False)
    assert tuple(prompt.id for _, prompt in without_sentinels) == expected_ids[:48]
    assert tuple(kind for kind, _ in without_sentinels) == ("design",) * 48

    transport_calls = 0
    real_client = httpx.Client

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        pytest.fail("held-out guard reached the transport")

    def client_factory(*_args: Any, **_kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("capture.harness.httpx.Client", client_factory)
    assert _main_rc(["run", "--run", "heldout-run", "--kind", "heldout"]) == 2
    assert transport_calls == 0


def test_h3_per_row_flush(tmp_path: Path) -> None:
    """H3 — the directory is a valid gradeable capture after every row.

    Accept when: after row k the directory grades clean under ``capture.record.validate`` and its
    manifest ``record_count`` is k; a driver interrupted after row k leaves exactly that state on
    disk, with run.json, records.ndjson and stats.json all present and mutually consistent.
    """
    first = _prompt("design", "design-simple-01")
    second = _prompt("design", "design-complicated-01")
    rows: tuple[tuple[Kind, Prompt], ...] = (("design", first), ("design", second))
    expected_bodies = (_request_body(first), _request_body(second))
    directory = tmp_path / "h3-run"
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        assert request.method == "POST"
        assert request.url.path == CHAT_PATH
        assert request.content == expected_bodies[calls]
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return _ok_response()

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        suppress(KeyboardInterrupt),
    ):
        _run_driver(client, directory, rows)

    assert calls == 2
    assert {path.name for path in directory.iterdir()} == {RUN_NAME, RECORDS_NAME, STATS_NAME}
    committed = load_run(directory)
    assert committed.manifest.record_count == 1
    assert tuple(record.prompt_id for record in committed.records) == ("design-simple-01",)
    assert validate(directory) == []
    assert validate_stats(directory) == []


def test_h4_ok_mapping(tmp_path: Path) -> None:
    """H4 — a 200 envelope is copied verbatim into the record.

    Accept when: content, ``finish_reason`` and all three usage counts equal the envelope's, a
    non-ASCII reply keeps its exact bytes (``content_bytes`` counts UTF-8 bytes, not characters),
    and ``error`` is None.
    """
    prompt = _prompt("design", "design-simple-01")
    rows: tuple[tuple[Kind, Prompt], ...] = (("design", prompt),)
    directory = tmp_path / "h4-run"
    content = "print('café ☕ — 東京')\n"
    raw = content.encode("utf-8")
    assert len(raw) != len(content)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == CHAT_PATH
        assert request.headers["content-type"] == "application/json"
        assert request.content == _request_body(prompt)
        return httpx.Response(
            200,
            json={
                "id": "fixture-completion",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content,
                            "extra": "loose decoder must ignore this",
                        },
                        "finish_reason": "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": 13,
                    "completion_tokens": 29,
                    "total_tokens": 42,
                },
                "extra": "loose decoder must ignore this too",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert len(_run_driver(client, directory, rows)) == len(rows)

    record = load_run(directory).records[0]
    assert record.http_status == 200
    assert record.content == content
    assert record.content_sha256 == _sha256(raw)
    assert record.content_bytes == len(raw)
    assert record.finish_reason == "length"
    assert record.usage == Usage(prompt_tokens=13, completion_tokens=29, total_tokens=42)
    assert record.error is None


def test_h5_fault_mapping(tmp_path: Path) -> None:
    """H5 — every unusable exchange takes the fault arm with its status named in the error.

    Accept when: a non-200 records the SERVER's status; a transport error, an undecodable body, an
    envelope with no usable choice, and a ``finish_reason`` outside ``FINISH_REASONS`` each record
    ``NO_STATUS`` with a non-empty ``error`` naming the observed status; in every arm all five
    reply fields are absent, so ``capture.record.check_outcome_shape`` reports nothing.
    """
    prompt = _prompt("design", "design-simple-01")

    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "engine is loading"}})

    def disconnected(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    def undecodable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff")

    def empty_choices(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    def foreign_finish(_request: httpx.Request) -> httpx.Response:
        return _ok_response(finish_reason="tool_calls")

    cases = (
        (unavailable, 503, ("503",)),
        (disconnected, NO_STATUS, ("connection refused",)),
        (undecodable, NO_STATUS, ("200",)),
        (empty_choices, NO_STATUS, ("200",)),
        (foreign_finish, NO_STATUS, ("200", "tool_calls")),
    )
    retained: list[Outcome] = []
    for index, (responder, status, fragments) in enumerate(cases):
        outcome = _capture(prompt, responder)
        retained.append(outcome)
        _assert_fault(
            outcome,
            expected_status=status,
            error_fragments=fragments,
            directory=tmp_path / f"h5-{index}",
            prompt=prompt,
        )
    assert len(retained) == 5
    assert NO_STATUS == 0


def test_h8_defence() -> None:
    """H8 — one de-fencer, and it survives an unterminated fence.

    Accept when: a closed fence yields its inner block; an UNTERMINATED fence (the truncation
    shape) yields the remainder rather than the whole reply; an unfenced reply is returned
    unchanged with ``fenced`` False; a fence with a language tag is stripped; and a ``` that is not
    at the start of a line does not open a fence. ``fenced`` agrees with the extraction in all five.

    End-of-string terminates an opening-fence line: `````python`` is fenced with an empty inner
    block. Inner source bytes, including the newline immediately before a closer, stay unchanged.
    """
    cases = (
        ("```\nx = 1\n```", (True, "x = 1\n")),
        ("```\nx = 1\n", (True, "x = 1\n")),
        ("x = 1\n", (False, "x = 1\n")),
        ("```python\nprint('ok')\n```", (True, "print('ok')\n")),
        ("prefix ```python\nx = 1\n```", (False, "prefix ```python\nx = 1\n```")),
        ("```python", (True, "")),
    )
    for content, expected in cases:
        assert defence(content) == expected


def test_h9_parse_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """H9 — the parse statistic is total over adversarial bytes and refuses an empty module.

    Accept when: a real program scores parsed; a blank body, a comment-only body, a body over
    ``MAX_PARSE_BYTES``, a body carrying a NUL byte, and 2000-deep nested parentheses all score
    NOT parsed and none of them raises. A call-counting bomb pins the byte cap before ``ast.parse``.
    """
    over_cap = "x=1\n" * ((MAX_PARSE_BYTES // 4) + 1)
    deeply_nested = "(" * 2000 + "0" + ")" * 2000
    assert MAX_PARSE_BYTES == 1 << 20
    assert len(over_cap.encode("utf-8")) > MAX_PARSE_BYTES
    assert parses("x = 1\n") is True
    for content in ("", " \n\t", "# comment only\n", "x = '\x00'\n", deeply_nested):
        assert parses(content) is False
    assert parses(over_cap) is False

    parse_calls = 0

    def parse_bomb(*_args: object, **_kwargs: object) -> ast.AST:
        nonlocal parse_calls
        parse_calls += 1
        message = "over-cap content reached ast.parse"
        raise AssertionError(message)

    monkeypatch.setattr(ast, "parse", parse_bomb)
    assert parses(over_cap) is False
    assert parse_calls == 0


def test_h10_denominators(tmp_path: Path) -> None:
    """H10 — rates count replies, and a sentinel never reaches a category denominator.

    Accept when: a run holding sentinels of both categories leaves every ``by_category`` block's
    ``records`` free of them; a fault is excluded from ``replies`` and from all three numerators;
    and the category ``records`` sum plus the sentinel row count equals ``record_count``.
    """
    directory = tmp_path / "h10-run"
    records = (
        _record(
            directory=directory,
            kind="design",
            prompt=_prompt("design", "design-simple-01"),
            content="```python\nx = 1\n```",
        ),
        _record(
            directory=directory,
            kind="design",
            prompt=_prompt("design", "design-simple-02"),
            http_status=503,
        ),
        _record(
            directory=directory,
            kind="design",
            prompt=_prompt("design", "design-complicated-01"),
            content="for",
            finish_reason="length",
        ),
        _record(
            directory=directory,
            kind="design",
            prompt=_prompt("design", "design-complicated-02"),
            http_status=NO_STATUS,
            error="connection refused",
        ),
        _record(
            directory=directory,
            kind="sentinels",
            prompt=_prompt("sentinels", "sentinel-simple"),
            content="```python\nsentinel = 1\n```",
        ),
        _record(
            directory=directory,
            kind="sentinels",
            prompt=_prompt("sentinels", "sentinel-complicated"),
            http_status=503,
        ),
    )
    stats = derive_stats(_run(directory, records))
    assert stats.record_count == 6
    assert stats.by_category == {
        "simple": StatBlock(
            records=2,
            replies=1,
            fenced=1,
            parsed=1,
            truncated=0,
            fence_rate=1.0,
            parse_rate=1.0,
            truncation_rate=0.0,
        ),
        "complicated": StatBlock(
            records=2,
            replies=1,
            fenced=0,
            parsed=0,
            truncated=1,
            fence_rate=0.0,
            parse_rate=0.0,
            truncation_rate=1.0,
        ),
    }
    assert {sentinel.prompt_id: sentinel for sentinel in stats.sentinels} == {
        "sentinel-simple": SentinelStat(
            prompt_id="sentinel-simple",
            category="simple",
            http_status=200,
            fenced=True,
            parsed=True,
            truncated=False,
        ),
        "sentinel-complicated": SentinelStat(
            prompt_id="sentinel-complicated",
            category="complicated",
            http_status=503,
            fenced=None,
            parsed=None,
            truncated=None,
        ),
    }
    assert sum(block.records for block in stats.by_category.values()) + len(stats.sentinels) == 6


def test_h11_undefined_rates(tmp_path: Path) -> None:
    """H11 — an undefined rate is None, never 0.0.

    Accept when: a category whose every record is a fault reports ``replies`` 0 and all three rates
    ``None``; the encoded stats.json spells them ``null``; and a category with replies but zero
    fenced replies reports ``0.0``, so the two cases stay distinguishable on disk.
    """
    directory = tmp_path / "h11-run"
    records = (
        _record(
            directory=directory,
            kind="design",
            prompt=_prompt("design", "design-simple-01"),
            http_status=503,
        ),
        _record(
            directory=directory,
            kind="design",
            prompt=_prompt("design", "design-complicated-01"),
            content="x = 1\n",
        ),
    )
    stats = derive_stats(_run(directory, records))
    simple = stats.by_category["simple"]
    complicated = stats.by_category["complicated"]
    assert simple == StatBlock(
        records=1,
        replies=0,
        fenced=0,
        parsed=0,
        truncated=0,
        fence_rate=None,
        parse_rate=None,
        truncation_rate=None,
    )
    assert complicated.fence_rate == 0.0
    assert complicated.parse_rate == 1.0
    assert complicated.truncation_rate == 0.0

    raw = encode_stats(stats)
    document: dict[str, Any] = json.loads(raw)
    simple_doc = document["by_category"]["simple"]
    complicated_doc = document["by_category"]["complicated"]
    assert (
        simple_doc["fence_rate"],
        simple_doc["parse_rate"],
        simple_doc["truncation_rate"],
    ) == (None, None, None)
    assert complicated_doc["fence_rate"] == 0.0
    assert b'"fence_rate": null' in raw
    assert b'"fence_rate": 0.0' in raw


def test_h12_canonical_stats_bytes() -> None:
    """H12 — stats.json is canonical and carries no clock.

    Accept when: the encoded bytes are indent-2 with exactly one trailing newline; ``by_category``
    keys appear in ``CATEGORIES`` declaration order; every stats struct's ``__struct_fields__``
    equals a hand-stated exact tuple; and no field name or encoded byte carries a timestamp.
    """
    assert STATS_VERSION == "python-capture-stats-1"
    assert CAPTURE_MODE == "python_raw_unconstrained"
    assert CATEGORIES == ("simple", "complicated")
    assert StatBlock.__struct_fields__ == (
        "records",
        "replies",
        "fenced",
        "parsed",
        "truncated",
        "fence_rate",
        "parse_rate",
        "truncation_rate",
    )
    assert SentinelStat.__struct_fields__ == (
        "prompt_id",
        "category",
        "http_status",
        "fenced",
        "parsed",
        "truncated",
    )
    assert CaptureStats.__struct_fields__ == (
        "version",
        "mode",
        "run",
        "kind",
        "record_count",
        "by_category",
        "sentinels",
    )
    assert StatsRun.__struct_fields__ == ("run", "stats", "stats_bytes")
    assert Outcome.__struct_fields__ == (
        "request_body",
        "http_status",
        "content",
        "finish_reason",
        "usage",
        "error",
    )

    stats = _golden_stats()
    raw = encode_stats(stats)
    expected = msgspec.json.format(msgspec.json.encode(stats), indent=2) + b"\n"
    assert raw == expected
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    assert raw.index(b'"simple": {') < raw.index(b'"complicated": {')

    field_names = (
        *StatBlock.__struct_fields__,
        *SentinelStat.__struct_fields__,
        *CaptureStats.__struct_fields__,
        *StatsRun.__struct_fields__,
    )
    for clock in ("timestamp", "created_at", "captured_at", "started_at", "finished_at"):
        assert clock not in field_names
        assert f'"{clock}":'.encode() not in raw


def test_h13_golden_statistic() -> None:
    """H13 — the golden's statistic equals a hand-stated value, never a re-derived one.

    Accept when: ``derive_stats`` over tests/golden/capture-golden-v1/ equals a literal built in
    this file — one reply per category, the complicated reply truncated, the simple one not, zero
    fences, both parse rates hand-stated, and one sentinel row carrying a 503 and no rate.
    """
    expected = _golden_stats()
    actual = derive_stats(load_run(_GOLDEN_ROOT))
    assert actual == expected
    assert actual.by_category["simple"].parse_rate == 1.0
    assert actual.by_category["complicated"].parse_rate == 0.0
    assert actual.by_category["complicated"].truncation_rate == 1.0
    assert actual.sentinels == (
        SentinelStat(
            prompt_id="sentinel-simple",
            category="simple",
            http_status=503,
            fenced=None,
            parsed=None,
            truncated=None,
        ),
    )


def test_h14_resume_overwrite(  # noqa: PLR0915 — one row owns all three directory-state arms
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H14 — a populated run directory refuses, resumes or restarts, never mixes.

    Accept when: a populated directory refuses by default with zero requests issued; the resume
    form drives ONLY the missing prompt ids and preserves the committed rows byte for byte; the
    resume form refuses when the rebuilt manifest disagrees with the committed one in any field
    but ``record_count``; and the overwrite form restarts from empty.

    A committed prompt id outside the freshly selected rows refuses resume. Keeping that row would
    silently widen the run beyond its selected scope; dropping it would violate resume preservation.
    """
    captures = tmp_path / "captures"
    captures.mkdir()
    first = _prompt("design", "design-simple-01")
    second = _prompt("design", "design-simple-02")
    alien = _prompt("design", "design-simple-03")
    rows: tuple[tuple[Kind, Prompt], ...] = (("design", first), ("design", second))
    expected_bodies = {
        _request_body(first, max_tokens=512, temperature=0.0),
        _request_body(second, max_tokens=512, temperature=0.0),
    }

    def responder(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url == httpx.URL(f"{DEFAULT_BASE_URL}{HEALTH_PATH}")
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "model_name": _MODEL,
                    "device": "fixture-device",
                    "structured_output": True,
                    "vplot_schema_sha256": "sha256:" + "a" * 64,
                    "formula_schema_sha256": "sha256:" + "b" * 64,
                },
            )
        assert request.method == "POST"
        assert request.url == httpx.URL(f"{DEFAULT_BASE_URL}{CHAT_PATH}")
        assert request.headers["content-type"] == "application/json"
        assert request.content in expected_bodies
        return _ok_response(content="new = True\n")

    requests = _patch_cli_world(monkeypatch, captures, rows, responder)

    resume_dir = captures / "resume-run"
    preserved = _seed_cli_run(resume_dir, first)
    preserved_line = encode_records((preserved,)).splitlines()[0]
    base_args = ["run", "--run", "resume-run", "--kind", "design", "--no-sentinels"]
    assert _main_rc(base_args) != 0
    assert requests == []

    assert _main_rc([*base_args, "--resume"]) == 0
    posts = [request for request in requests if request.method == "POST"]
    assert len(posts) == 1
    assert posts[0].content == _request_body(second, max_tokens=512, temperature=0.0)
    resumed = load_run(resume_dir)
    assert tuple(record.prompt_id for record in resumed.records) == (
        "design-simple-01",
        "design-simple-02",
    )
    assert resumed.records[0] == preserved
    assert preserved_line in resumed.records_bytes.splitlines()
    assert validate(resume_dir) == []
    assert validate_stats(resume_dir) == []

    mismatch_dir = captures / "mismatch-run"
    old_mismatch = _seed_cli_run(
        mismatch_dir,
        first,
        max_tokens=DEFAULT_MAX_TOKENS - 1,
        content="mismatched old row\n",
    )
    old_mismatch_line = encode_records((old_mismatch,)).splitlines()[0]
    mismatch_args = [
        "run",
        "--run",
        "mismatch-run",
        "--kind",
        "design",
        "--no-sentinels",
    ]
    requests.clear()
    assert _main_rc([*mismatch_args, "--resume"]) != 0
    assert not [request for request in requests if request.method == "POST"]

    alien_dir = captures / "alien-run"
    _seed_cli_run(alien_dir, alien)
    requests.clear()
    assert (
        _main_rc(
            [
                "run",
                "--run",
                "alien-run",
                "--kind",
                "design",
                "--no-sentinels",
                "--resume",
            ]
        )
        != 0
    )
    assert not [request for request in requests if request.method == "POST"]

    requests.clear()
    assert _main_rc([*mismatch_args, "--overwrite"]) == 0
    assert len([request for request in requests if request.method == "POST"]) == 2
    overwritten = load_run(mismatch_dir)
    assert tuple(record.prompt_id for record in overwritten.records) == (
        "design-simple-01",
        "design-simple-02",
    )
    assert {record.content for record in overwritten.records} == {"new = True\n"}
    assert old_mismatch_line not in overwritten.records_bytes.splitlines()
    assert validate(mismatch_dir) == []
    assert validate_stats(mismatch_dir) == []


def test_h15_cli(  # noqa: PLR0915 — one row owns the complete run/stats CLI matrix
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H15 — the two subcommands exit as contracted.

    Accept when: ``stats`` returns 0 on the golden and 1 on a broken run; ``stats`` with no
    argument grades every run under the captures root; ``stats --write`` regenerates a deleted or
    stale stats.json to byte-identical content; and a non-finite or non-positive timeout refuses
    before any request is issued.
    """
    assert DEFAULT_BASE_URL == "http://127.0.0.1:8001"
    assert DEFAULT_MAX_TOKENS == 512
    assert DEFAULT_TIMEOUT == 300.0
    captures = tmp_path / "cli-captures"
    captures.mkdir()
    prompt = _prompt("design", "design-simple-01")
    rows: tuple[tuple[Kind, Prompt], ...] = (("design", prompt),)
    expected_body = _request_body(prompt, max_tokens=512, temperature=0.0)

    def responder(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url == httpx.URL(f"{DEFAULT_BASE_URL}{HEALTH_PATH}")
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "model_name": _MODEL,
                    "device": "fixture-device",
                    "structured_output": True,
                },
            )
        assert request.method == "POST"
        assert request.url == httpx.URL(f"{DEFAULT_BASE_URL}{CHAT_PATH}")
        assert request.headers["content-type"] == "application/json"
        assert request.content == expected_body
        return _ok_response()

    requests = _patch_cli_world(monkeypatch, captures, rows, responder)
    run_args = [
        "run",
        "--run",
        "h15-run",
        "--kind",
        "design",
        "--no-sentinels",
        "--timeout",
        "2.5",
    ]
    assert _main_rc(run_args) == 0
    assert [request.method for request in requests] == ["GET", "POST"]
    assert validate(captures / "h15-run") == []
    assert validate_stats(captures / "h15-run") == []

    invalid_timeouts = ("0", "-0", "-1", "nan", "-nan", "inf", "-inf", "1e400")
    for index, token in enumerate(invalid_timeouts):
        requests.clear()
        assert (
            _main_rc(
                [
                    "run",
                    "--run",
                    f"invalid-timeout-{index}",
                    "--kind",
                    "design",
                    "--no-sentinels",
                    "--timeout",
                    token,
                ]
            )
            == 2
        )
        assert requests == []

    golden_parent = tmp_path / "golden"
    golden_parent.mkdir()
    golden = _golden_directory(golden_parent)
    expected_stats = encode_stats(_golden_stats())
    assert _main_rc(["stats", str(golden)]) == 0

    broken = tmp_path / "broken" / "capture-golden-v1"
    shutil.copytree(golden, broken)
    broken_path = broken / STATS_NAME
    broken_doc: dict[str, Any] = json.loads(broken_path.read_bytes())
    broken_doc["by_category"]["simple"]["fenced"] = 1
    broken_path.write_bytes(_json_bytes(broken_doc))
    assert _main_rc(["stats", str(broken)]) == 1

    stats_path = golden / STATS_NAME
    stats_path.unlink()
    assert _main_rc(["stats", "--write", str(golden)]) == 0
    assert stats_path.read_bytes() == expected_stats
    stats_path.write_bytes(b"{}\n")
    assert _main_rc(["stats", "--write", str(golden)]) == 0
    assert stats_path.read_bytes() == expected_stats

    discovered = tmp_path / "discovered"
    alpha = discovered / "alpha"
    beta = discovered / "beta"
    alpha.mkdir(parents=True)
    beta.mkdir()
    (discovered / "not-a-run.txt").write_text("ignored", encoding="utf-8")
    record_calls: list[Path] = []
    stats_calls: list[Path] = []

    def fake_record_validate(directory: Path) -> list[str]:
        record_calls.append(directory)
        return []

    def fake_stats_validate(directory: Path) -> list[str]:
        stats_calls.append(directory)
        return []

    monkeypatch.setattr(harness_module, "CAPTURES_ROOT", discovered)
    monkeypatch.setattr(harness_module, "validate_records", fake_record_validate)
    monkeypatch.setattr(harness_module, "validate_stats", fake_stats_validate)
    assert _main_rc(["stats"]) == 0
    assert record_calls == [alpha, beta]
    assert stats_calls == [alpha, beta]
