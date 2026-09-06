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

Predicates R1-R11 of .agent/contracts/m12u6.md are implemented HERE and nowhere else;
tests/test_python_capture_record.py calls them and restates none of them.
"""

import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, Literal

import msgspec

from capture.corpus import CORPUS_ROOT, REPO_ROOT, Category, DatasetName, Kind, Prompt

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

RUNTIME_LOCK_PATH: Final[Path] = REPO_ROOT / "model_backend" / "runtime" / "uv.lock"
ENGINE_PATH: Final[Path] = REPO_ROOT / "model_backend" / "engine.py"
# The dtype is a module constant in the engine, not a setting: it is NOT env-overridable, so the
# source literal is authoritative for any run at a known commit. Scanned rather than imported --
# importing the engine would pull transformers into the py3.13 gate venv.
_ENGINE_DTYPE_RE: Final = re.compile(r'^_DTYPE\s*=\s*"([^"]+)"', re.MULTILINE)

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
_NVIDIA_SMI_QUERY: Final = "driver_version,compute_cap,name,memory.total"

CommandRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


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
    """Backend facts OBSERVED over GET /health -- what the server says it is serving."""

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


def build_request_body(*, prompt: str, model: str, max_tokens: int, temperature: float) -> bytes:
    """Encode the ONE outbound chat-completion body shape a capture may send."""
    raise NotImplementedError


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
    """Assemble one record, deriving every digest from the bytes that were actually exchanged."""
    raise NotImplementedError


def collect_repo_provenance(
    root: Path = REPO_ROOT, *, runner: CommandRunner | None = None
) -> RepoProvenance:
    """Read one tree's committed-state facts. A missing or failing git degrades, never raises."""
    raise NotImplementedError


def collect_host_provenance(*, runner: CommandRunner | None = None) -> HostProvenance | None:
    """Read accelerator facts from nvidia-smi; None when it is absent, fails or is unparseable."""
    raise NotImplementedError


def encode_run(manifest: RunManifest) -> bytes:
    """Serialize one manifest to its canonical committed form."""
    raise NotImplementedError


def encode_records(records: Sequence[CaptureRecord]) -> bytes:
    """Serialize records to canonical NDJSON: sorted by prompt_id, one object per line."""
    raise NotImplementedError


def decode_run(raw: bytes) -> RunManifest:
    """Strictly decode one manifest; raise on any malformed or unknown field."""
    raise NotImplementedError


def decode_records(raw: bytes) -> tuple[CaptureRecord, ...]:
    """Strictly decode canonical NDJSON; raise on any malformed line."""
    raise NotImplementedError


def write_run(directory: Path, manifest: RunManifest, records: Sequence[CaptureRecord]) -> None:
    """Write one run directory in canonical form."""
    raise NotImplementedError


def load_run(directory: Path) -> Run:
    """Load one run directory, keeping the exact bytes so canonical form stays checkable."""
    raise NotImplementedError


def check_versions(run: Run) -> list[str]:
    """R1 -- the manifest and every record declare this version and this capture mode."""
    raise NotImplementedError


def check_unguided(run: Run) -> list[str]:
    """R2 -- every record's outbound key set is exactly REQUEST_KEYS and names no guidance key."""
    raise NotImplementedError


def check_run_identity(run: Run) -> list[str]:
    """R3 -- run id agrees with the directory and every record; counts and ids are consistent."""
    raise NotImplementedError


def check_corpus_binding(run: Run) -> list[str]:
    """R4 -- every record resolves in the committed corpus and re-renders to its prompt digest."""
    raise NotImplementedError


def check_run_scope(run: Run) -> list[str]:
    """R5 -- a run holds its own corpus set plus the sentinels, and nothing else."""
    raise NotImplementedError


def check_outcome_shape(run: Run) -> list[str]:
    """R6 -- the 200 shape and the fault shape are disjoint and complete."""
    raise NotImplementedError


def check_content_integrity(run: Run) -> list[str]:
    """R7 -- the stored digest and byte count describe the stored reply exactly."""
    raise NotImplementedError


def check_usage(run: Run) -> list[str]:
    """R8 -- token counts add up and are non-negative; the finish reason is a known one."""
    raise NotImplementedError


def check_canonical_bytes(run: Run) -> list[str]:
    """R9 -- both committed files already ARE the canonical encoding of their contents."""
    raise NotImplementedError


def check_provenance(run: Run) -> list[str]:
    """R10 -- digests are well-formed and the model, revision and dtype match the live pins."""
    raise NotImplementedError


def check_request_reproduces(run: Run) -> list[str]:
    """R11 -- rebuilding each outbound body from the corpus and the manifest reproduces its sha."""
    raise NotImplementedError


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
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """Grade the named run directories, or every run under CAPTURES_ROOT when given none."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
