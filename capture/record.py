# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Capture-record format for python-mode model captures: schema, canonical bytes, validator.

One committed capture run is a directory under corpus/python/captures/:

    <run>/run.json        RunManifest -- mode, corpus kind, request parameters, provenance
    <run>/records.ndjson  one CaptureRecord per line, sorted by prompt_id

The RAW model bytes are the artifact. A record stores the model's exact reply string plus its
UTF-8 sha256 and byte length; nothing here de-fences, normalizes or re-emits it (de-fencing is a
DERIVED statistic and lives in the capture harness).

Captures are UNGUIDED: build_request_body emits exactly REQUEST_KEYS and NEVER a guided_schema
key -- absent, not null. The backend keeps structured_output enabled, and an absent key attaches
zero logits processors, so a capture needs no operator action to stay unconstrained. Every
committed record is graded against that one builder (R2 + R11), so no caller can spell a body the
builder would not have produced.

Provenance is three blocks that never merge: repo (committed-state facts, authoritative given
git_commit + git_dirty), service (observed over GET /health) and host (observed via nvidia-smi,
best-effort). Merging them would report an observed fact for a declared one.

A capture set is evidence for ONE model at ONE dtype: model_repo_id, model_revision and
engine_dtype are graded against the live pins, so changing either invalidates every committed run
and forces a re-capture instead of silently re-labelling old bytes. The lock digest is
format-graded only -- a dependency bump moves neither the model nor the calibration lever.

No field anywhere carries a wall clock: a run must re-encode byte-identically from its own decoded
contents (R9), and a timestamp would make every committed run undiffable.

Predicates R1-R11 of .agent/archive/contracts/m12u6.md are implemented HERE and nowhere else;
tests/test_python_capture_record.py calls them and restates none of them.
"""

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Final, Literal

import msgspec

from capture.corpus import (
    CAPTURE_PROMPT_NAME,
    CAPTURE_PROMPT_SHA256,
    CORPUS_ROOT,
    REPO_ROOT,
    Category,
    DatasetName,
    Kind,
    Prompt,
    load_corpus,
    render_capture_prompt,
)
from model_backend.snapshot import SNAPSHOT_REPO_ID, SNAPSHOT_REVISION

RECORD_VERSION: Final = "python-capture-1"
CAPTURE_MODE: Final = "python_raw_unconstrained"

# The exact top-level key set of every outbound body, sorted. Hand-stated: the pin is worthless if
# it re-derives from the builder it guards.
REQUEST_KEYS: Final[tuple[str, ...]] = ("max_tokens", "messages", "model", "temperature")
# Guidance selectors across the OpenAI-compatible dialects the backend or a proxy might honour.
# Ruling 5: the grammar may constrain FORMAT, never ADMISSION, so a capture carries none of them.
BANNED_REQUEST_KEYS: Final[frozenset[str]] = frozenset(
    {"grammar", "guided_json", "guided_schema", "response_format"}
)
# model_backend derives these two from the terminal token; no other value is reachable.
FINISH_REASONS: Final[tuple[str, ...]] = ("length", "stop")

CAPTURES_ROOT: Final[Path] = CORPUS_ROOT / "captures"
RUN_NAME: Final = "run.json"
RECORDS_NAME: Final = "records.ndjson"

# Repo-relative so collect_repo_provenance can stamp a tree other than this one.
_RUNTIME_LOCK_RELATIVE: Final[Path] = Path("model_backend/runtime/uv.lock")
_ENGINE_RELATIVE: Final[Path] = Path("model_backend/engine.py")
_TEMPLATE_RELATIVE: Final[Path] = Path("corpus/python") / CAPTURE_PROMPT_NAME
RUNTIME_LOCK_PATH: Final[Path] = REPO_ROOT / _RUNTIME_LOCK_RELATIVE
ENGINE_PATH: Final[Path] = REPO_ROOT / _ENGINE_RELATIVE
# The dtype is a module constant in the engine, not a setting: it is NOT env-overridable, so the
# source literal is authoritative for any run at a known commit. Scanned rather than imported --
# importing the engine would pull transformers into the py3.13 gate venv.
_ENGINE_DTYPE_RE: Final = re.compile(r'^_DTYPE\s*=\s*"([^"]+)"', re.MULTILINE)

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
_NVIDIA_SMI: Final = "nvidia-smi"
_NVIDIA_SMI_QUERY: Final = "driver_version,compute_cap,name,memory.total"
_NVIDIA_SMI_FIELDS: Final = 4
_HTTP_OK: Final = 200
_JSON_INDENT: Final = 2

CommandRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class CaptureFormatError(ValueError):
    """A run file is framed wrongly, so no record set can be reported against it."""


class Usage(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Token accounting for one completion, decoded straight from the backend's usage object."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class HostProvenance(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Accelerator facts OBSERVED via nvidia-smi. Absent whenever the tool cannot answer."""

    driver_version: str
    compute_cap: str
    gpu_name: str
    memory_total_mib: int


class ServiceProvenance(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Backend facts OBSERVED over GET /health -- what the server says it is serving.

    Strict by design: a caller decodes /health into its OWN loose struct (that payload carries
    status and two schema digests this format does not archive) and constructs this block from the
    three fields, so an added health field can never enter a committed record unreviewed.
    """

    model_name: str
    device: str
    structured_output: bool


class RepoProvenance(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Committed-state facts DECLARED by the tree the run was taken from.

    Authoritative for the model, its revision and the dtype given git_commit + git_dirty: none of
    the three is env-overridable. The token caps ARE env-overridable and so are deliberately not
    declared here -- the manifest records the max_tokens actually sent, and finish_reason plus
    usage report what the backend did with it.
    """

    git_commit: str | None
    git_dirty: bool
    model_repo_id: str
    model_revision: str
    engine_dtype: str
    runtime_lock_sha256: str
    capture_prompt_sha256: str


class Provenance(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Declared, observed-from-the-service and observed-from-the-host facts, never merged."""

    repo: RepoProvenance
    service: ServiceProvenance | None
    host: HostProvenance | None


class CaptureRecord(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One prompt, one outbound body, one backend outcome.

    The corpus fields (kind/category/idiom/dataset_name) are copied rather than looked up so a
    record reads standalone; R4 grades every copy against the committed corpus. content is the
    model's verbatim reply for a 200 and absent otherwise, with error carrying the fault text --
    the two shapes are disjoint (R6), never one nullable field doing both jobs.
    """

    version: Literal["python-capture-1"]
    mode: Literal["python_raw_unconstrained"]
    run: str
    prompt_id: str
    kind: Kind
    category: Category
    idiom: str
    dataset_name: DatasetName
    prompt_sha256: str
    request_sha256: str
    request_keys: tuple[str, ...]
    http_status: int
    content: str | None
    content_sha256: str | None
    content_bytes: int | None
    finish_reason: str | None
    usage: Usage | None
    error: str | None


class RunManifest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One capture run: what was asked, of which model, over which corpus set, from which tree."""

    version: Literal["python-capture-1"]
    mode: Literal["python_raw_unconstrained"]
    run: str
    kind: Kind
    model: str
    model_base_url: str
    max_tokens: int
    temperature: float
    record_count: int
    provenance: Provenance


class Run(msgspec.Struct, frozen=True, kw_only=True):
    """One loaded run directory: its decoded contents plus the exact bytes they came from."""

    directory: Path
    manifest: RunManifest
    records: tuple[CaptureRecord, ...]
    run_bytes: bytes
    records_bytes: bytes


class _RequestMessage(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """The single user turn of a capture request. The corpus rule fixes it at one message."""

    role: Literal["user"]
    content: str


class _RequestBody(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """The ONE outbound body shape. Field order IS the canonical key order (= REQUEST_KEYS), and
    the absent guidance key is the whole unguided guarantee: no field here can name one."""

    max_tokens: int
    messages: tuple[_RequestMessage, ...]
    model: str
    temperature: float


_MANIFEST_DECODER: Final = msgspec.json.Decoder(RunManifest)
_RECORD_DECODER: Final = msgspec.json.Decoder(CaptureRecord)


def _sha256_bytes(raw: bytes) -> str:
    """Digest one byte string."""
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(text: str) -> str:
    """Digest one string over its UTF-8 encoding, which is what the record's byte count counts."""
    return _sha256_bytes(text.encode("utf-8"))


def build_request_body(*, prompt: str, model: str, max_tokens: int, temperature: float) -> bytes:
    """Encode the ONE outbound chat-completion body shape a capture may send."""
    return msgspec.json.encode(
        _RequestBody(
            max_tokens=max_tokens,
            messages=(_RequestMessage(role="user", content=prompt),),
            model=model,
            temperature=temperature,
        )
    )


def build_record(  # noqa: PLR0913 — one keyword per exchanged fact; a bundle would hide a missing one
    *,
    run: str,
    prompt: Prompt,
    kind: Kind,
    request_body: bytes,
    http_status: int,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: Usage | None = None,
    error: str | None = None,
) -> CaptureRecord:
    """Assemble one record, deriving every digest from the bytes that were actually exchanged.

    request_keys is read back OUT of the encoded body rather than copied from REQUEST_KEYS, so R2
    grades what was sent instead of what the builder intended to send.
    """
    sent: dict[str, msgspec.Raw] = msgspec.json.decode(request_body, type=dict[str, msgspec.Raw])
    return CaptureRecord(
        version=RECORD_VERSION,
        mode=CAPTURE_MODE,
        run=run,
        prompt_id=prompt.id,
        kind=kind,
        category=prompt.category,
        idiom=prompt.idiom,
        dataset_name=prompt.dataset_name,
        prompt_sha256=_sha256_text(render_capture_prompt(prompt)),
        request_sha256=hashlib.sha256(request_body).hexdigest(),
        request_keys=tuple(sorted(sent)),
        http_status=http_status,
        content=content,
        content_sha256=None if content is None else _sha256_text(content),
        content_bytes=None if content is None else len(content.encode("utf-8")),
        finish_reason=finish_reason,
        usage=usage,
        error=error,
    )


def _run_command(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    """Run one fixed-argv command, capturing both streams and never raising on a non-zero rc."""
    return subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603


def _tool_path(name: str, runner: CommandRunner | None) -> str | None:
    """Resolve a tool for argv, or None when the host lacks it.

    An INJECTED runner is authoritative and never consults the host. Resolving first made both
    collectors depend on the machine even under injection, so the seam tests passed only where
    `git` and `nvidia-smi` happen to exist and went red on a CI runner with no GPU.
    """
    return name if runner is not None else shutil.which(name)


def _git_facts(root: Path, runner: CommandRunner | None) -> tuple[str | None, bool]:
    """Return (HEAD commit, dirty). An absent or failing git degrades to (None, False)."""
    git = _tool_path("git", runner)
    if git is None:
        return (None, False)
    run = runner or _run_command
    try:
        commit = run([git, "-C", str(root), "rev-parse", "HEAD"])
        status = run([git, "-C", str(root), "status", "--porcelain", "--untracked-files=normal"])
    except OSError:
        return (None, False)
    # Shape-check here, not only in R10: a collector that stamps garbage builds a manifest the
    # validator then rejects, which reads as a corrupt run rather than an absent git.
    head = commit.stdout.strip() if commit.returncode == 0 else ""
    if _COMMIT_RE.fullmatch(head) is None:
        return (None, False)
    dirty = status.returncode == 0 and bool(status.stdout.strip())
    return (head, dirty)


def live_engine_dtype(path: Path = ENGINE_PATH) -> str | None:
    """Read the engine's dtype literal from its source, or None when the pin cannot be found."""
    try:
        match = _ENGINE_DTYPE_RE.search(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return None if match is None else match[1]


def collect_repo_provenance(
    root: Path = REPO_ROOT, *, runner: CommandRunner | None = None
) -> RepoProvenance:
    """Read one tree's committed-state facts. A missing or failing git degrades, never raises."""
    commit, dirty = _git_facts(root, runner)
    return RepoProvenance(
        git_commit=commit,
        git_dirty=dirty,
        model_repo_id=SNAPSHOT_REPO_ID,
        model_revision=SNAPSHOT_REVISION,
        # An unreadable dtype pin stamps "" so R10 refuses the run loudly rather than raising here.
        engine_dtype=live_engine_dtype(root / _ENGINE_RELATIVE) or "",
        runtime_lock_sha256=_sha256_bytes((root / _RUNTIME_LOCK_RELATIVE).read_bytes()),
        capture_prompt_sha256=hashlib.sha256((root / _TEMPLATE_RELATIVE).read_bytes()).hexdigest(),
    )


def _parse_smi_line(line: str) -> HostProvenance | None:
    """Parse one nounits CSV row into host facts; None whenever any field is unusable."""
    fields = [field.strip() for field in line.split(",")]
    if len(fields) != _NVIDIA_SMI_FIELDS or not all(fields[:3]):
        return None
    try:
        memory = int(fields[3])
    except ValueError:
        return None
    if memory < 0:
        return None
    return HostProvenance(
        driver_version=fields[0], compute_cap=fields[1], gpu_name=fields[2], memory_total_mib=memory
    )


def collect_host_provenance(*, runner: CommandRunner | None = None) -> HostProvenance | None:
    """Read accelerator facts from nvidia-smi; None when it is absent, fails or is unparseable."""
    smi = _tool_path(_NVIDIA_SMI, runner)
    if smi is None:
        return None
    try:
        probe = (runner or _run_command)(
            [smi, f"--query-gpu={_NVIDIA_SMI_QUERY}", "--format=csv,noheader,nounits"]
        )
    except OSError:
        return None
    lines = probe.stdout.strip().splitlines()
    if probe.returncode != 0 or not lines:
        return None
    return _parse_smi_line(lines[0])


def encode_run(manifest: RunManifest) -> bytes:
    """Serialize one manifest to its canonical committed form: indented, one trailing newline."""
    return msgspec.json.format(msgspec.json.encode(manifest), indent=_JSON_INDENT) + b"\n"


def encode_records(records: Sequence[CaptureRecord]) -> bytes:
    """Serialize records to canonical NDJSON: sorted by prompt_id, one compact object per line."""
    ordered = sorted(records, key=lambda record: record.prompt_id)
    return b"".join(msgspec.json.encode(record) + b"\n" for record in ordered)


def decode_run(raw: bytes) -> RunManifest:
    """Strictly decode one manifest; raise on any malformed or unknown field."""
    return _MANIFEST_DECODER.decode(raw)


def decode_records(raw: bytes) -> tuple[CaptureRecord, ...]:
    """Strictly decode canonical NDJSON; raise on any malformed or blank line."""
    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        message = f"{RECORDS_NAME} does not end with a newline"
        raise CaptureFormatError(message)
    lines = raw.split(b"\n")[:-1]
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            message = f"{RECORDS_NAME} line {number} is blank"
            raise CaptureFormatError(message)
    return tuple(_RECORD_DECODER.decode(line) for line in lines)


def write_run(directory: Path, manifest: RunManifest, records: Sequence[CaptureRecord]) -> None:
    """Write one run directory in canonical form.

    Writes exactly what it is handed and re-derives nothing: the validator is the authority on a
    coherent run, so a caller can stage a deliberately broken one for a refusal test.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RUN_NAME).write_bytes(encode_run(manifest))
    (directory / RECORDS_NAME).write_bytes(encode_records(records))


def load_run(directory: Path) -> Run:
    """Load one run directory, keeping the exact bytes so canonical form stays checkable."""
    run_bytes = (directory / RUN_NAME).read_bytes()
    records_bytes = (directory / RECORDS_NAME).read_bytes()
    return Run(
        directory=directory,
        manifest=decode_run(run_bytes),
        records=decode_records(records_bytes),
        run_bytes=run_bytes,
        records_bytes=records_bytes,
    )


def _corpus_index() -> dict[str, tuple[Kind, Prompt]]:
    """Index every committed corpus prompt by id, tagged with the set it came from."""
    return {prompt.id: (kind, prompt) for kind, prompt in load_corpus().rows()}


def check_versions(run: Run) -> list[str]:
    """R1 -- the manifest and every record declare this version and this capture mode."""
    failures: list[str] = []
    for field, actual, expected in (
        ("version", run.manifest.version, RECORD_VERSION),
        ("mode", run.manifest.mode, CAPTURE_MODE),
    ):
        if actual != expected:
            failures.append(f"{RUN_NAME}: {field} is {actual!r}, expected {expected!r}")
    failures.extend(
        f"{record.prompt_id}: {field} is {actual!r}, expected {expected!r}"
        for record in run.records
        for field, actual, expected in (
            ("version", record.version, RECORD_VERSION),
            ("mode", record.mode, CAPTURE_MODE),
        )
        if actual != expected
    )
    return failures


def check_unguided(run: Run) -> list[str]:
    """R2 -- every record's outbound key set is exactly REQUEST_KEYS and names no guidance key."""
    failures: list[str] = []
    for record in run.records:
        if record.request_keys != REQUEST_KEYS:
            failures.append(
                f"{record.prompt_id}: request keys {record.request_keys} != {REQUEST_KEYS}"
            )
        failures.extend(
            f"{record.prompt_id}: request names guidance key {key!r}"
            for key in sorted(set(record.request_keys) & BANNED_REQUEST_KEYS)
        )
    return failures


def check_run_identity(run: Run) -> list[str]:
    """R3 -- run id agrees with the directory and every record; counts and ids are consistent."""
    failures: list[str] = []
    if run.manifest.run != run.directory.name:
        failures.append(f"{RUN_NAME}: run {run.manifest.run!r} != directory {run.directory.name!r}")
    if run.manifest.record_count != len(run.records):
        failures.append(
            f"{RUN_NAME}: record_count {run.manifest.record_count} != {len(run.records)} records"
        )
    failures.extend(
        f"{record.prompt_id}: run {record.run!r} != manifest run {run.manifest.run!r}"
        for record in run.records
        if record.run != run.manifest.run
    )
    seen: set[str] = set()
    for record in run.records:
        if record.prompt_id in seen:
            failures.append(f"{record.prompt_id}: prompt_id appears more than once")
        seen.add(record.prompt_id)
    return failures


def check_corpus_binding(run: Run) -> list[str]:
    """R4 -- every record resolves in the committed corpus and re-renders to its prompt digest."""
    index = _corpus_index()
    failures: list[str] = []
    for record in run.records:
        found = index.get(record.prompt_id)
        if found is None:
            failures.append(f"{record.prompt_id}: not a committed corpus prompt")
            continue
        kind, prompt = found
        failures.extend(
            f"{record.prompt_id}: {field} is {actual!r}, corpus says {expected!r}"
            for field, actual, expected in (
                ("kind", record.kind, kind),
                ("category", record.category, prompt.category),
                ("idiom", record.idiom, prompt.idiom),
                ("dataset_name", record.dataset_name, prompt.dataset_name),
            )
            if actual != expected
        )
        rendered = _sha256_text(render_capture_prompt(prompt))
        if record.prompt_sha256 != rendered:
            failures.append(
                f"{record.prompt_id}: prompt_sha256 {record.prompt_sha256} != rendered {rendered}"
            )
    return failures


def check_run_scope(run: Run) -> list[str]:
    """R5 -- a run holds its own corpus set plus the sentinels, and nothing else."""
    admitted = {run.manifest.kind, "sentinels"}
    return [
        f"{record.prompt_id}: kind {record.kind!r} outside {sorted(admitted)}"
        for record in run.records
        if record.kind not in admitted
    ]


def check_outcome_shape(run: Run) -> list[str]:
    """R6 -- the 200 shape and the fault shape are disjoint and complete."""
    failures: list[str] = []
    for record in run.records:
        reply: tuple[tuple[str, object | None], ...] = (
            ("content", record.content),
            ("content_sha256", record.content_sha256),
            ("content_bytes", record.content_bytes),
            ("finish_reason", record.finish_reason),
            ("usage", record.usage),
        )
        if record.http_status == _HTTP_OK:
            failures.extend(
                f"{record.prompt_id}: 200 record is missing {name}"
                for name, value in reply
                if value is None
            )
            if record.error is not None:
                failures.append(f"{record.prompt_id}: 200 record carries error {record.error!r}")
            continue
        failures.extend(
            f"{record.prompt_id}: {record.http_status} record carries {name}"
            for name, value in reply
            if value is not None
        )
        if not record.error:
            failures.append(f"{record.prompt_id}: {record.http_status} record has no error text")
    return failures


def check_content_integrity(run: Run) -> list[str]:
    """R7 -- the stored digest and byte count describe the stored reply exactly."""
    failures: list[str] = []
    for record in run.records:
        if record.content is None:
            continue
        encoded = record.content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if record.content_sha256 != digest:
            failures.append(
                f"{record.prompt_id}: content_sha256 {record.content_sha256} != {digest}"
            )
        if record.content_bytes != len(encoded):
            failures.append(
                f"{record.prompt_id}: content_bytes {record.content_bytes} != {len(encoded)}"
            )
    return failures


def check_usage(run: Run) -> list[str]:
    """R8 -- token counts add up and are non-negative; the finish reason is a known one."""
    failures: list[str] = []
    for record in run.records:
        if record.finish_reason is not None and record.finish_reason not in FINISH_REASONS:
            failures.append(
                f"{record.prompt_id}: finish_reason {record.finish_reason!r} not in "
                f"{FINISH_REASONS}"
            )
        usage = record.usage
        if usage is None:
            continue
        counts = (
            ("prompt_tokens", usage.prompt_tokens),
            ("completion_tokens", usage.completion_tokens),
            ("total_tokens", usage.total_tokens),
        )
        failures.extend(
            f"{record.prompt_id}: {name} is negative ({value})"
            for name, value in counts
            if value < 0
        )
        if usage.total_tokens != usage.prompt_tokens + usage.completion_tokens:
            failures.append(
                f"{record.prompt_id}: total_tokens {usage.total_tokens} != "
                f"{usage.prompt_tokens} + {usage.completion_tokens}"
            )
    return failures


def check_canonical_bytes(run: Run) -> list[str]:
    """R9 -- both committed files already ARE the canonical encoding of their contents."""
    return [
        f"{name}: bytes are not the canonical encoding of their contents"
        for name, actual, expected in (
            (RUN_NAME, run.run_bytes, encode_run(run.manifest)),
            (RECORDS_NAME, run.records_bytes, encode_records(run.records)),
        )
        if actual != expected
    ]


def check_provenance(run: Run) -> list[str]:
    """R10 -- digests are well-formed and the model, revision and dtype match the live pins."""
    repo = run.manifest.provenance.repo
    failures: list[str] = []
    if repo.git_commit is not None and _COMMIT_RE.fullmatch(repo.git_commit) is None:
        failures.append(f"{RUN_NAME}: git_commit {repo.git_commit!r} is not 40 lowercase hex")
    failures.extend(
        f"{RUN_NAME}: {name} {value!r} is not 64 lowercase hex"
        for name, value in (
            ("runtime_lock_sha256", repo.runtime_lock_sha256),
            ("capture_prompt_sha256", repo.capture_prompt_sha256),
        )
        if _SHA256_RE.fullmatch(value) is None
    )
    failures.extend(
        f"{RUN_NAME}: {name} {actual!r} != live pin {expected!r}"
        for name, actual, expected in (
            ("capture_prompt_sha256", repo.capture_prompt_sha256, CAPTURE_PROMPT_SHA256),
            ("model_repo_id", repo.model_repo_id, SNAPSHOT_REPO_ID),
            ("model_revision", repo.model_revision, SNAPSHOT_REVISION),
            ("engine_dtype", repo.engine_dtype, live_engine_dtype()),
        )
        if actual != expected
    )
    return failures


def check_request_reproduces(run: Run) -> list[str]:
    """R11 -- rebuilding each outbound body from the corpus and the manifest reproduces its sha."""
    index = _corpus_index()
    manifest = run.manifest
    failures: list[str] = []
    for record in run.records:
        found = index.get(record.prompt_id)
        if found is None:  # R4 reports the unknown id; there is nothing to rebuild from
            continue
        body = build_request_body(
            prompt=render_capture_prompt(found[1]),
            model=manifest.model,
            max_tokens=manifest.max_tokens,
            temperature=manifest.temperature,
        )
        digest = hashlib.sha256(body).hexdigest()
        if record.request_sha256 != digest:
            failures.append(
                f"{record.prompt_id}: request_sha256 {record.request_sha256} != rebuilt {digest}"
            )
    return failures


PREDICATES: dict[str, Callable[[Run], list[str]]] = {
    "R1": check_versions,
    "R2": check_unguided,
    "R3": check_run_identity,
    "R4": check_corpus_binding,
    "R5": check_run_scope,
    "R6": check_outcome_shape,
    "R7": check_content_integrity,
    "R8": check_usage,
    "R9": check_canonical_bytes,
    "R10": check_provenance,
    "R11": check_request_reproduces,
}


def validate(directory: Path) -> list[str]:
    """Run every predicate over one run; return id-prefixed failure lines, empty when sound."""
    run = load_run(directory)
    return [f"{pid}: {line}" for pid, check in PREDICATES.items() for line in check(run)]


def _discover_runs(root: Path | None = None) -> list[Path]:
    """List every capture run directory under one captures root, in name order.

    The default resolves CAPTURES_ROOT at CALL time: a default argument would freeze the
    import-time value and make the module constant unpatchable for tests and alternate roots.
    """
    root = CAPTURES_ROOT if root is None else root
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


def _grade(directories: Iterable[Path]) -> int:
    """Grade each run, writing failures to stderr; return 1 when any run is unsound."""
    failed = False
    for directory in directories:
        try:
            failures = validate(directory)
        except (CaptureFormatError, msgspec.DecodeError, OSError) as exc:
            sys.stderr.write(f"{directory}: {exc}\n")
            failed = True
            continue
        for line in failures:
            sys.stderr.write(f"{directory}: {line}\n")
        failed = failed or bool(failures)
        if not failures:
            sys.stdout.write(f"{directory}: sound\n")
    return 1 if failed else 0


def _parse_args(argv: Sequence[str] | None) -> list[Path]:
    parser = argparse.ArgumentParser(
        prog="python -m capture.record",
        description="Grade committed python-mode capture runs against predicates R1-R11.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "run_dir",
        type=Path,
        nargs="*",
        metavar="PATH",
        help=f"capture run directories (default: every run under {CAPTURES_ROOT})",
    )
    parsed = parser.parse_args(argv)
    directories: list[Path] = parsed.run_dir
    return directories


def main(argv: Sequence[str] | None = None) -> int:
    """Grade the named run directories, or every run under CAPTURES_ROOT when given none."""
    directories = _parse_args(argv)
    if not directories:
        directories = _discover_runs()
        if not directories:
            sys.stdout.write(f"no capture runs under {CAPTURES_ROOT}\n")
            return 0
    return _grade(directories)


if __name__ == "__main__":
    raise SystemExit(main())
