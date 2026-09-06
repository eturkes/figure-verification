# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Structural gate for the python-mode capture record format (contract .agent/contracts/m12u6.md).

Predicates R1-R11 live in capture.record and are called here, never restated: a test that
re-implements a check pins its own copy instead of the shipped one. What this file adds on top of
the calls is what the validator cannot check about ITSELF -- strict-decode refusal against
near-miss inputs, the closed predicate set, the hand-authored golden run, one-field mutations that
must kill exactly one predicate each, the outbound body shape, the injected subprocess seams, and
the CLI.

Every expected byte here is hand-stated, never read back from capture.record or from the golden:
that is what makes the golden a pin rather than a mirror.
"""

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import msgspec
import pytest

import capture.record as record_module
from capture.corpus import CAPTURE_PROMPT_SHA256, Kind, Prompt, load_corpus, render_capture_prompt
from capture.record import (
    BANNED_REQUEST_KEYS,
    FINISH_REASONS,
    PREDICATES,
    REQUEST_KEYS,
    CaptureRecord,
    HostProvenance,
    Provenance,
    RepoProvenance,
    Run,
    RunManifest,
    ServiceProvenance,
    Usage,
    build_request_body,
    check_canonical_bytes,
    check_content_integrity,
    check_corpus_binding,
    check_outcome_shape,
    check_provenance,
    check_request_reproduces,
    check_run_identity,
    check_run_scope,
    check_unguided,
    check_usage,
    check_versions,
    collect_host_provenance,
    collect_repo_provenance,
    decode_records,
    decode_run,
    encode_records,
    encode_run,
    load_run,
    validate,
    write_run,
)

_RUN_ID = "capture-test-v1"
_MODEL = "Qwen2.5-Coder-0.5B-Instruct"
_CAPTURE_PROMPT_SHA256 = "a18162f788cce976a55458545c5761e2fd5b8b924e116ac137ffc4deb004964e"
_ZERO_SHA256 = "0000000000000000000000000000000000000000000000000000000000000000"
_GOLDEN_ROOT = Path(__file__).parent / "golden" / "capture-golden-v1"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _request_bytes(prompt: str, *, model: str = _MODEL, max_tokens: int = 256) -> bytes:
    # Key order is hand-stated, never sorted: canonical order is msgspec declaration order at every
    # level, which REQUEST_KEYS restates for the top level alone (contract m12u6, R-mode).
    return json.dumps(
        {
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "model": model,
            "temperature": 0.0,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _record(  # noqa: PLR0913 — one keyword per response-shape field
    *,
    run: str,
    kind: Kind,
    prompt: Prompt,
    http_status: int = 200,
    content: str | None = "print('ok')\n",
    finish_reason: str | None = "stop",
    usage: Usage | None = None,
    error: str | None = None,
) -> CaptureRecord:
    rendered = render_capture_prompt(prompt)
    content_raw = None if content is None else content.encode()
    return CaptureRecord(
        version="python-capture-1",
        mode="python_raw_unconstrained",
        run=run,
        prompt_id=prompt.id,
        kind=kind,
        category=prompt.category,
        idiom=prompt.idiom,
        dataset_name=prompt.dataset_name,
        prompt_sha256=_sha256(rendered.encode()),
        request_sha256=_sha256(_request_bytes(rendered)),
        request_keys=("max_tokens", "messages", "model", "temperature"),
        http_status=http_status,
        content=content,
        content_sha256=None if content_raw is None else _sha256(content_raw),
        content_bytes=None if content_raw is None else len(content_raw),
        finish_reason=finish_reason,
        usage=(
            usage
            if usage is not None
            else Usage(prompt_tokens=11, completion_tokens=7, total_tokens=18)
            if http_status == 200
            else None
        ),
        error=error,
    )


def _sound_run(tmp_path: Path) -> Run:
    rows = {(kind, prompt.id): prompt for kind, prompt in load_corpus().rows()}
    records = (
        _record(
            run=_RUN_ID,
            kind="design",
            prompt=rows[("design", "design-complicated-01")],
            content="print('complicated')\n",
            finish_reason="length",
        ),
        _record(run=_RUN_ID, kind="design", prompt=rows[("design", "design-simple-01")]),
        _record(
            run=_RUN_ID,
            kind="sentinels",
            prompt=rows[("sentinels", "sentinel-simple")],
            http_status=503,
            content=None,
            finish_reason=None,
            usage=None,
            error="backend unavailable",
        ),
    )
    manifest = RunManifest(
        version="python-capture-1",
        mode="python_raw_unconstrained",
        run=_RUN_ID,
        kind="design",
        model=_MODEL,
        model_base_url="http://127.0.0.1:8001/v1",
        max_tokens=256,
        temperature=0.0,
        record_count=len(records),
        provenance=Provenance(
            repo=RepoProvenance(
                git_commit=None,
                git_dirty=False,
                model_repo_id="Qwen/Qwen2.5-Coder-0.5B-Instruct",
                model_revision="ea3f2471cf1b1f0db85067f1ef93848e38e88c25",
                engine_dtype="float16",
                runtime_lock_sha256=_ZERO_SHA256,
                capture_prompt_sha256=_CAPTURE_PROMPT_SHA256,
            ),
            service=ServiceProvenance(model_name=_MODEL, device="cuda", structured_output=True),
            host=HostProvenance(
                driver_version="580.178.04",
                compute_cap="6.1",
                gpu_name="NVIDIA GeForce MX150",
                memory_total_mib=2002,
            ),
        ),
    )
    return Run(
        directory=tmp_path / _RUN_ID,
        manifest=manifest,
        records=records,
        run_bytes=msgspec.json.encode(manifest) + b"\n",
        records_bytes=b"".join(msgspec.json.encode(record) + b"\n" for record in records),
    )


def _with_record(run: Run, index: int = 0, **changes: object) -> Run:
    records = list(run.records)
    records[index] = msgspec.structs.replace(records[index], **changes)
    return msgspec.structs.replace(run, records=tuple(records))


def _with_repo(run: Run, **changes: object) -> Run:
    repo = msgspec.structs.replace(run.manifest.provenance.repo, **changes)
    provenance = msgspec.structs.replace(run.manifest.provenance, repo=repo)
    manifest = msgspec.structs.replace(run.manifest, provenance=provenance)
    return msgspec.structs.replace(run, manifest=manifest)


def _golden_manifest() -> RunManifest:
    return RunManifest(
        version="python-capture-1",
        mode="python_raw_unconstrained",
        run="capture-golden-v1",
        kind="design",
        model="Qwen2.5-Coder-0.5B-Instruct",
        model_base_url="http://127.0.0.1:8001",
        max_tokens=512,
        temperature=0.0,
        record_count=3,
        provenance=Provenance(
            repo=RepoProvenance(
                git_commit="f69afe7de2ed4670574a8f2f8906d507e45ead88",
                git_dirty=False,
                model_repo_id="Qwen/Qwen2.5-Coder-0.5B-Instruct",
                model_revision="ea3f2471cf1b1f0db85067f1ef93848e38e88c25",
                engine_dtype="float16",
                runtime_lock_sha256=(
                    "c5c2c2458b8de334b7341134d0b00a5397f298c68d9a8469e35d953da6fbe94e"
                ),
                capture_prompt_sha256=(
                    "a18162f788cce976a55458545c5761e2fd5b8b924e116ac137ffc4deb004964e"
                ),
            ),
            service=ServiceProvenance(
                model_name="Qwen2.5-Coder-0.5B-Instruct",
                device="cuda",
                structured_output=True,
            ),
            host=HostProvenance(
                driver_version="580.178.04",
                compute_cap="6.1",
                gpu_name="NVIDIA GeForce MX150",
                memory_total_mib=2048,
            ),
        ),
    )


def _golden_records() -> tuple[CaptureRecord, ...]:
    return (
        CaptureRecord(
            version="python-capture-1",
            mode="python_raw_unconstrained",
            run="capture-golden-v1",
            prompt_id="design-complicated-01",
            kind="design",
            category="complicated",
            idiom="subplot_grid",
            dataset_name="sales.csv",
            prompt_sha256="0de47c3d8194f671b63867f8ac983f4e4eaff6db89903dcd327eac9e45cc46f6",
            request_sha256="2a928749bef2045b7da1564c157fb6d00ce78eeab5da1866d2db7413da43a9cc",
            request_keys=("max_tokens", "messages", "model", "temperature"),
            http_status=200,
            content=(
                "import pandas as pd\n"
                "import matplotlib.pyplot as plt\n"
                "\n"
                "df = pd.read_csv('/mnt/uploads/sales.csv')\n"
                "fig, axes = plt.subplots(2, 2)\n"
                "axes[0, 0].set_title('revenue 360° view')\n"
                "for region, part in df.groupby('re"
            ),
            content_sha256="f9e37dc96942aa17e6e304d94a3a02b23a180855cb9555207adfa26826d6a9c3",
            content_bytes=204,
            finish_reason="length",
            usage=Usage(prompt_tokens=167, completion_tokens=512, total_tokens=679),
            error=None,
        ),
        CaptureRecord(
            version="python-capture-1",
            mode="python_raw_unconstrained",
            run="capture-golden-v1",
            prompt_id="design-simple-01",
            kind="design",
            category="simple",
            idiom="bar_category_sum",
            dataset_name="sales.csv",
            prompt_sha256="37e501a47bb9fb29b3f707d7325efab79a97ce9c4418dbd3d0b6432ba9ca7171",
            request_sha256="e1003cc1869da4f111f1cfdbed18de006eb7b2de5bc8c73f4a34b5ad436bf898",
            request_keys=("max_tokens", "messages", "model", "temperature"),
            http_status=200,
            content=(
                "import pandas as pd\n"
                "import matplotlib.pyplot as plt\n"
                "\n"
                "df = pd.read_csv('/mnt/uploads/sales.csv')\n"
                "totals = df.groupby('region')['revenue'].sum()\n"
                "plt.bar(totals.index, totals.values)\n"
                "plt.xlabel('region')\n"
                "plt.ylabel('revenue')\n"
                "plt.show()\n"
            ),
            content_sha256="7fe6627fc904e624ae90d46ca097c1f01a7043393965dc918b1a4172a83379b7",
            content_bytes=234,
            finish_reason="stop",
            usage=Usage(prompt_tokens=118, completion_tokens=74, total_tokens=192),
            error=None,
        ),
        CaptureRecord(
            version="python-capture-1",
            mode="python_raw_unconstrained",
            run="capture-golden-v1",
            prompt_id="sentinel-simple",
            kind="sentinels",
            category="simple",
            idiom="scatter_xy",
            dataset_name="sales.csv",
            prompt_sha256="6a0b87c92be9b91a413256ac6aea0dd3a85a52ae25a98cfb898c0f152c0a05df",
            request_sha256="deef51161fbb02b1f09458c862b00abeb39187605b56dee024a50a775387471b",
            request_keys=("max_tokens", "messages", "model", "temperature"),
            http_status=503,
            content=None,
            content_sha256=None,
            content_bytes=None,
            finish_reason=None,
            usage=None,
            error="backend returned 503: engine is loading",
        ),
    )


def _canonicalized(run: Run) -> Run:
    return msgspec.structs.replace(
        run,
        run_bytes=encode_run(run.manifest),
        records_bytes=encode_records(run.records),
    )


def _with_manifest(run: Run, **changes: object) -> Run:
    return msgspec.structs.replace(run, manifest=msgspec.structs.replace(run.manifest, **changes))


def test_r1_versions(tmp_path: Path) -> None:
    """R1: check_versions returns [] on a sound run, and a failure line naming the offending
    record when a record or the manifest carries a foreign mode or version."""
    run = _sound_run(tmp_path)
    assert check_versions(run) == []

    manifest_version = msgspec.structs.replace(run.manifest, version="python-capture-0")
    manifest_mode = msgspec.structs.replace(run.manifest, mode="vplot_json_guided")
    for manifest in (manifest_version, manifest_mode):
        assert check_versions(msgspec.structs.replace(run, manifest=manifest))

    for field, value in (("version", "python-capture-0"), ("mode", "vplot_json_guided")):
        record = msgspec.structs.replace(run.records[0], **{field: value})
        mutant = msgspec.structs.replace(run, records=(record, *run.records[1:]))
        failures = check_versions(mutant)
        assert failures
        assert run.records[0].prompt_id in "\n".join(failures)


def test_r2_unguided(tmp_path: Path) -> None:
    """R2: check_unguided returns [] on a sound run; a record whose request_keys adds, drops or
    reorders a key fails, and a record naming any member of BANNED_REQUEST_KEYS fails."""
    run = _sound_run(tmp_path)
    expected = ("max_tokens", "messages", "model", "temperature")
    assert (
        frozenset({"grammar", "guided_json", "guided_schema", "response_format"})
        == BANNED_REQUEST_KEYS
    )
    assert check_unguided(run) == []

    near_misses = (
        (*expected, "seed"),
        expected[1:],
        ("messages", "max_tokens", "model", "temperature"),
        *((*expected, key) for key in sorted(BANNED_REQUEST_KEYS)),
    )
    for request_keys in near_misses:
        record = msgspec.structs.replace(run.records[0], request_keys=request_keys)
        failures = check_unguided(msgspec.structs.replace(run, records=(record, *run.records[1:])))
        assert failures
        assert record.prompt_id in "\n".join(failures)


def test_r3_run_identity(tmp_path: Path) -> None:
    """R3: check_run_identity returns [] on a sound run; a directory renamed away from
    manifest.run, a record carrying a different run, a wrong record_count and a duplicated
    prompt_id each fail."""
    run = _sound_run(tmp_path)
    assert check_run_identity(run) == []

    renamed = msgspec.structs.replace(run, directory=run.directory.with_name("renamed"))
    wrong_record = msgspec.structs.replace(run.records[0], run="another-run")
    record_mismatch = msgspec.structs.replace(run, records=(wrong_record, *run.records[1:]))
    wrong_count = msgspec.structs.replace(
        run, manifest=msgspec.structs.replace(run.manifest, record_count=4)
    )
    duplicate = msgspec.structs.replace(run.records[1], prompt_id=run.records[0].prompt_id)
    duplicate_id = msgspec.structs.replace(run, records=(run.records[0], duplicate, run.records[2]))
    for mutant in (renamed, record_mismatch, wrong_count, duplicate_id):
        assert check_run_identity(mutant)


def test_r4_corpus_binding(tmp_path: Path) -> None:
    """R4: check_corpus_binding returns [] on a sound run; an unknown prompt_id, a mismatched
    category/idiom/dataset_name and a prompt_sha256 that is not sha256 of the re-rendered capture
    prompt each fail."""
    run = _sound_run(tmp_path)
    assert check_corpus_binding(run) == []

    mutations = (
        {"prompt_id": "design-simple-99"},
        {"kind": "heldout"},
        {"category": "simple"},
        {"idiom": "scatter_xy"},
        {"dataset_name": "weather.csv"},
        {"prompt_sha256": _ZERO_SHA256},
    )
    for mutation in mutations:
        record = msgspec.structs.replace(run.records[0], **mutation)
        failures = check_corpus_binding(
            msgspec.structs.replace(run, records=(record, *run.records[1:]))
        )
        assert failures
        assert record.prompt_id in "\n".join(failures)


def test_r5_run_scope(tmp_path: Path) -> None:
    """R5: check_run_scope returns [] for a design run holding design plus sentinel rows, and
    fails for a heldout row inside a design run."""
    run = _sound_run(tmp_path)
    assert check_run_scope(run) == []

    heldout = next(
        prompt
        for kind, prompt in load_corpus().rows()
        if kind == "heldout" and prompt.id == "heldout-simple-01"
    )
    heldout_record = _record(run=_RUN_ID, kind="heldout", prompt=heldout)
    mutant = msgspec.structs.replace(run, records=(heldout_record, *run.records[1:]))
    failures = check_run_scope(mutant)
    assert failures
    assert heldout.id in "\n".join(failures)


def test_r6_outcome_shape(tmp_path: Path) -> None:
    """R6: check_outcome_shape returns [] for a 200 record with all five reply fields present and
    error None, and for a fault record with all five absent and a non-empty error. Each half-shape
    fails: a 200 missing any of the five, a 200 carrying an error, a fault carrying content, a
    fault whose error is None or empty."""
    run = _sound_run(tmp_path)
    assert check_outcome_shape(run) == []

    missing_reply_fields = (
        _with_record(run, content=None),
        _with_record(run, content_sha256=None),
        _with_record(run, content_bytes=None),
        _with_record(run, finish_reason=None),
        _with_record(run, usage=None),
    )
    for mutant in missing_reply_fields:
        assert check_outcome_shape(mutant)
    assert check_outcome_shape(_with_record(run, error="impossible mixed outcome"))
    assert check_outcome_shape(_with_record(run, 2, content="unexpected body"))
    assert check_outcome_shape(_with_record(run, 2, error=None))
    assert check_outcome_shape(_with_record(run, 2, error=""))


def test_r7_content_integrity(tmp_path: Path) -> None:
    """R7: check_content_integrity returns [] when content_sha256 and content_bytes describe
    content exactly; a wrong digest and a wrong byte count each fail. Include one non-ASCII reply
    so byte length is proved to be UTF-8 bytes, never character count."""
    run = _sound_run(tmp_path)
    content = "print('café ☕')\n"
    raw = content.encode()
    unicode_run = _with_record(
        run,
        content=content,
        content_sha256=_sha256(raw),
        content_bytes=len(raw),
    )
    assert len(raw) != len(content)
    assert check_content_integrity(unicode_run) == []
    assert check_content_integrity(_with_record(unicode_run, content_sha256=_ZERO_SHA256))
    assert check_content_integrity(_with_record(unicode_run, content_bytes=len(raw) - 1))


def test_r8_usage(tmp_path: Path) -> None:
    """R8: check_usage returns [] on coherent usage; a total that is not prompt + completion, a
    negative count and a finish_reason outside FINISH_REASONS each fail."""
    run = _sound_run(tmp_path)
    assert FINISH_REASONS == ("length", "stop")
    assert check_usage(run) == []
    assert (
        check_usage(
            _with_record(run, usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0))
        )
        == []
    )

    bad_usage = (
        Usage(prompt_tokens=11, completion_tokens=7, total_tokens=17),
        Usage(prompt_tokens=-1, completion_tokens=7, total_tokens=6),
        Usage(prompt_tokens=11, completion_tokens=-1, total_tokens=10),
        Usage(prompt_tokens=0, completion_tokens=0, total_tokens=-1),
    )
    for usage in bad_usage:
        assert check_usage(_with_record(run, usage=usage))
    for finish_reason in ("Stop", "stop ", "eos", "__stop__"):
        assert check_usage(_with_record(run, finish_reason=finish_reason))


def test_r9_canonical_bytes(tmp_path: Path) -> None:
    """R9: check_canonical_bytes returns [] for a run written by write_run; it fails when
    records.ndjson is re-ordered, re-indented, given a blank trailing line, or when run.json is
    re-encoded in any non-canonical form, even though every decode still succeeds."""
    seed = _sound_run(tmp_path)
    write_run(seed.directory, seed.manifest, seed.records)
    run = load_run(seed.directory)
    assert check_canonical_bytes(run) == []

    record_lines = run.records_bytes.splitlines(keepends=True)
    reordered = msgspec.structs.replace(run, records_bytes=b"".join(reversed(record_lines)))
    respaced = msgspec.structs.replace(
        run,
        records_bytes=b"".join(
            json.dumps(json.loads(line), ensure_ascii=False).encode() + b"\n"
            for line in record_lines
        ),
    )
    extra_blank = msgspec.structs.replace(run, records_bytes=run.records_bytes + b"\n")
    compact_manifest = msgspec.structs.replace(
        run,
        run_bytes=json.dumps(
            json.loads(run.run_bytes), ensure_ascii=False, separators=(",", ":")
        ).encode()
        + b"\n",
    )
    for mutant in (reordered, respaced, extra_blank, compact_manifest):
        assert check_canonical_bytes(mutant)


def test_r10_provenance(tmp_path: Path) -> None:
    """R10: check_provenance returns [] on a run stamped from the live tree; a non-40-hex
    git_commit, a non-64-hex lock or prompt digest, a capture_prompt_sha256 other than
    CAPTURE_PROMPT_SHA256, and a model_repo_id / model_revision / engine_dtype that disagrees with
    the live pin each fail. A None git_commit is admitted."""
    run = _sound_run(tmp_path)
    assert CAPTURE_PROMPT_SHA256 == _CAPTURE_PROMPT_SHA256
    assert check_provenance(run) == []
    assert check_provenance(_with_repo(run, git_commit="0" * 40)) == []

    for git_commit in ("0" * 39, "0" * 41, "A" * 40, "g" * 40, ""):
        assert check_provenance(_with_repo(run, git_commit=git_commit))
    for field in ("runtime_lock_sha256", "capture_prompt_sha256"):
        for digest in ("0" * 63, "0" * 65, "A" * 64, "g" * 64):
            assert check_provenance(_with_repo(run, **{field: digest}))
    for mutation in (
        {"capture_prompt_sha256": _ZERO_SHA256},
        {"model_repo_id": "Qwen/Qwen2.5-Coder-0.5B-Instruct-near-miss"},
        {"model_revision": "0" * 40},
        {"engine_dtype": "float32"},
    ):
        assert check_provenance(_with_repo(run, **mutation))


def test_r11_request_reproduces(tmp_path: Path) -> None:
    """R11: check_request_reproduces returns [] when every record's request_sha256 equals the sha
    of build_request_body over the re-rendered prompt and the manifest's model, max_tokens and
    temperature; changing any of those four inputs in the manifest or the record fails."""
    run = _sound_run(tmp_path)
    assert check_request_reproduces(run) == []

    for changes in (
        {"model": f"{_MODEL}-near-miss"},
        {"max_tokens": run.manifest.max_tokens + 1},
        {"temperature": 0.2},
    ):
        manifest = msgspec.structs.replace(run.manifest, **changes)
        assert check_request_reproduces(msgspec.structs.replace(run, manifest=manifest))

    other = next(
        prompt
        for kind, prompt in load_corpus().rows()
        if kind == "design" and prompt.id == "design-simple-02"
    )
    rendered = render_capture_prompt(other)
    changed_prompt = _with_record(
        run,
        prompt_id=other.id,
        category=other.category,
        idiom=other.idiom,
        dataset_name=other.dataset_name,
        prompt_sha256=_sha256(rendered.encode()),
    )
    assert check_request_reproduces(changed_prompt)
    assert check_request_reproduces(_with_record(run, request_sha256=_ZERO_SHA256))


def test_i1_closed_predicate_set(tmp_path: Path) -> None:
    """I1: PREDICATES keys equal the hand-stated literal ("R1".."R11") and every value is the
    module-level function of the matching name. Hand-state the tuple; never derive it from the
    dict under test."""
    expected = (
        ("R1", check_versions),
        ("R2", check_unguided),
        ("R3", check_run_identity),
        ("R4", check_corpus_binding),
        ("R5", check_run_scope),
        ("R6", check_outcome_shape),
        ("R7", check_content_integrity),
        ("R8", check_usage),
        ("R9", check_canonical_bytes),
        ("R10", check_provenance),
        ("R11", check_request_reproduces),
    )
    assert tuple(PREDICATES.items()) == expected
    assert PREDICATES["R1"](_sound_run(tmp_path)) == []


def test_i2_strict_decode() -> None:
    """I2: decode_run and decode_records refuse near-miss inputs of the same family -- an unknown
    field, an absent required field, a wrong version, a wrong mode, a float where an int is
    declared, an NDJSON line that is not an object, and a blank line beyond the canonical trailing
    newline. Each raises rather than returning a partial value."""
    manifest = _golden_manifest()
    valid_run = msgspec.json.encode(manifest) + b"\n"
    assert decode_run(valid_run) == manifest

    manifest_doc: dict[str, Any] = json.loads(valid_run)
    invalid_manifests = [
        {**manifest_doc, **mutation}
        for mutation in (
            {"unknown": "field"},
            {"version": "python-capture-0"},
            {"mode": "python_raw_unconstrained-near-miss"},
            {"max_tokens": 64.0},
        )
    ]
    missing_manifest_field = dict(manifest_doc)
    del missing_manifest_field["model"]
    invalid_manifests.append(missing_manifest_field)
    for doc in invalid_manifests:
        with pytest.raises(ValueError):
            decode_run(json.dumps(doc, ensure_ascii=False).encode())

    record = _golden_records()[0]
    valid_record = msgspec.json.encode(record) + b"\n"
    assert decode_records(valid_record) == (record,)
    record_doc: dict[str, Any] = json.loads(valid_record)
    invalid_records = [
        {**record_doc, **mutation}
        for mutation in (
            {"unknown": "field"},
            {"version": "python-capture-0"},
            {"mode": "python_raw_unconstrained-near-miss"},
            {"http_status": 200.0},
        )
    ]
    missing_record_field = dict(record_doc)
    del missing_record_field["prompt_id"]
    invalid_records.append(missing_record_field)
    for doc in invalid_records:
        with pytest.raises(ValueError):
            decode_records(json.dumps(doc, ensure_ascii=False).encode() + b"\n")
    for raw in (b"[]\n", valid_record + b"\n"):
        with pytest.raises(ValueError):
            decode_records(raw)


def test_i3_golden_run() -> None:
    """I3: the hand-authored golden at tests/golden/capture-golden-v1/ re-encodes byte-identically
    from structs built by hand in this test (encode_run and encode_records both), decodes back to
    equal structs, and validate() returns [] on it -- the positive control for every predicate."""
    run_raw = (_GOLDEN_ROOT / "run.json").read_bytes()
    records_raw = (_GOLDEN_ROOT / "records.ndjson").read_bytes()
    manifest = _golden_manifest()
    records = _golden_records()

    assert encode_run(manifest) == run_raw
    assert encode_records(records) == records_raw
    assert decode_run(run_raw) == manifest
    assert decode_records(records_raw) == records
    assert validate(_GOLDEN_ROOT) == []


def test_i4_near_miss_refusal() -> None:
    """I4: for each of R1-R11, one field mutation of the golden run makes that predicate fail; a
    mutation kills its own predicate and the run stays otherwise loadable. Drive this from a
    hand-stated table of (predicate id, mutation) so a new predicate cannot enter uncovered."""
    run = load_run(_GOLDEN_ROOT)
    mutations: tuple[tuple[str, Callable[[Run], Run]], ...] = (
        (
            "R1",
            lambda value: _canonicalized(
                _with_manifest(value, mode="python_raw_unconstrained-near-miss")
            ),
        ),
        (
            "R2",
            lambda value: _canonicalized(
                _with_record(
                    value,
                    request_keys=("messages", "max_tokens", "model", "temperature"),
                )
            ),
        ),
        (
            "R3",
            lambda value: _canonicalized(
                _with_manifest(value, record_count=value.manifest.record_count + 1)
            ),
        ),
        (
            "R4",
            lambda value: _canonicalized(_with_record(value, idiom="twin_axis")),
        ),
        (
            "R5",
            lambda value: _canonicalized(_with_manifest(value, kind="heldout")),
        ),
        (
            "R6",
            lambda value: _canonicalized(_with_record(value, error="mixed outcome")),
        ),
        (
            "R7",
            lambda value: _canonicalized(_with_record(value, content_sha256=_ZERO_SHA256)),
        ),
        (
            "R8",
            lambda value: _canonicalized(
                _with_record(
                    value,
                    usage=Usage(prompt_tokens=120, completion_tokens=64, total_tokens=183),
                )
            ),
        ),
        ("R9", lambda value: msgspec.structs.replace(value, run_bytes=value.run_bytes + b" ")),
        ("R10", lambda value: _canonicalized(_with_repo(value, git_commit="not-a-commit"))),
        (
            "R11",
            lambda value: _canonicalized(_with_record(value, request_sha256=_ZERO_SHA256)),
        ),
    )
    assert tuple(predicate_id for predicate_id, _ in mutations) == (
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "R6",
        "R7",
        "R8",
        "R9",
        "R10",
        "R11",
    )
    for expected_id, mutate in mutations:
        failures = {
            predicate_id for predicate_id, check in PREDICATES.items() if check(mutate(run))
        }
        assert failures == {expected_id}


def test_i5_no_wall_clock() -> None:
    """I5: __struct_fields__ of CaptureRecord, RunManifest, Provenance, RepoProvenance,
    ServiceProvenance, HostProvenance and Usage equal hand-stated exact tuples, and no field name
    or encoded byte of the golden carries a timestamp. A new field cannot enter unnoticed."""
    assert CaptureRecord.__struct_fields__ == (
        "version",
        "mode",
        "run",
        "prompt_id",
        "kind",
        "category",
        "idiom",
        "dataset_name",
        "prompt_sha256",
        "request_sha256",
        "request_keys",
        "http_status",
        "content",
        "content_sha256",
        "content_bytes",
        "finish_reason",
        "usage",
        "error",
    )
    assert RunManifest.__struct_fields__ == (
        "version",
        "mode",
        "run",
        "kind",
        "model",
        "model_base_url",
        "max_tokens",
        "temperature",
        "record_count",
        "provenance",
    )
    assert Provenance.__struct_fields__ == ("repo", "service", "host")
    assert RepoProvenance.__struct_fields__ == (
        "git_commit",
        "git_dirty",
        "model_repo_id",
        "model_revision",
        "engine_dtype",
        "runtime_lock_sha256",
        "capture_prompt_sha256",
    )
    assert ServiceProvenance.__struct_fields__ == (
        "model_name",
        "device",
        "structured_output",
    )
    assert HostProvenance.__struct_fields__ == (
        "driver_version",
        "compute_cap",
        "gpu_name",
        "memory_total_mib",
    )
    assert Usage.__struct_fields__ == ("prompt_tokens", "completion_tokens", "total_tokens")

    raw = encode_run(_golden_manifest()) + encode_records(_golden_records())
    for field in (
        b'"timestamp":',
        b'"created_at":',
        b'"captured_at":',
        b'"started_at":',
        b'"finished_at":',
    ):
        assert field not in raw


def test_i6_request_body_shape() -> None:
    """I6: build_request_body emits exactly REQUEST_KEYS at the top level, one user message whose
    content is the rendered prompt verbatim, and identical bytes across repeated calls. No
    guidance key appears for any input, including a prompt that spells one."""
    prompt = 'Keep "guided_schema" as ordinary prompt text: café ☕.'
    first = build_request_body(
        prompt=prompt, model="fixture-model", max_tokens=257, temperature=0.2
    )
    second = build_request_body(
        prompt=prompt, model="fixture-model", max_tokens=257, temperature=0.2
    )
    payload: dict[str, Any] = json.loads(first)

    assert REQUEST_KEYS == ("max_tokens", "messages", "model", "temperature")
    assert payload == {
        "max_tokens": 257,
        "messages": [{"content": prompt, "role": "user"}],
        "model": "fixture-model",
        "temperature": 0.2,
    }
    assert tuple(sorted(payload)) == ("max_tokens", "messages", "model", "temperature")
    assert first == second


def test_i7_subprocess_seam() -> None:
    """I7: collect_repo_provenance and collect_host_provenance take an injected runner. A missing
    tool, a non-zero return code and unparseable output each degrade as contracted -- git to
    (None, False), nvidia-smi to None -- and never raise. A well-formed nvidia-smi line parses
    into HostProvenance with memory as an int."""

    def missing_runner(_argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    def failing_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(argv), 2, stdout="", stderr="failed")

    def unparseable_git_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        clean_query = "status" in argv or "diff" in argv
        return subprocess.CompletedProcess(
            list(argv), 0, stdout="" if clean_query else "not-a-commit\n", stderr=""
        )

    def unparseable_host_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(argv), 0, stdout="not,csv\n", stderr="")

    def valid_host_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            list(argv),
            0,
            stdout="580.178.04, 6.1, NVIDIA GeForce MX150, 2002\n",
            stderr="",
        )

    for runner in (missing_runner, failing_runner, unparseable_git_runner):
        repo = collect_repo_provenance(runner=runner)
        assert (repo.git_commit, repo.git_dirty) == (None, False)
    for runner in (missing_runner, failing_runner, unparseable_host_runner):
        assert collect_host_provenance(runner=runner) is None
    assert collect_host_provenance(runner=valid_host_runner) == HostProvenance(
        driver_version="580.178.04",
        compute_cap="6.1",
        gpu_name="NVIDIA GeForce MX150",
        memory_total_mib=2002,
    )


def test_i8_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """I8: main() returns 0 on the golden run and 1 with id-prefixed failure lines on stderr for a
    broken one, and with no argument it grades every directory under CAPTURES_ROOT."""
    assert record_module.main([str(_GOLDEN_ROOT)]) == 0
    assert capsys.readouterr().err == ""

    bad = tmp_path / "bad" / "capture-golden-v1"
    shutil.copytree(_GOLDEN_ROOT, bad)
    run_path = bad / "run.json"
    run_doc: dict[str, Any] = json.loads(run_path.read_bytes())
    run_path.write_text(
        json.dumps(run_doc, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert record_module.main([str(bad)]) == 1
    assert "R9:" in capsys.readouterr().err

    captures = tmp_path / "captures"
    alpha = captures / "alpha"
    beta = captures / "beta"
    alpha.mkdir(parents=True)
    beta.mkdir()
    (captures / "not-a-run.txt").write_text("ignored", encoding="utf-8")
    calls: list[Path] = []

    def fake_validate(directory: Path) -> list[str]:
        calls.append(directory)
        return ["R1: synthetic failure"] if directory == beta else []

    monkeypatch.setattr(record_module, "CAPTURES_ROOT", captures)
    monkeypatch.setattr(record_module, "validate", fake_validate)
    assert record_module.main([]) == 1
    assert set(calls) == {alpha, beta}
    assert "R1: synthetic failure" in capsys.readouterr().err
