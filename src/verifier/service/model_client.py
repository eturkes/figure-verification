# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Model proposer client: bounded (user request, dataset context) -> raw model reply bytes.

The untrusted local proposer's ONLY entry into the verifier. propose_spec builds the VPlot
v0.1 proposer prompt (the trusted grammar + rules as system, the dataset binding + column
schema + sample rows + the user request as user), POSTs it to the local backend's OpenAI
/v1/chat/completions, and returns choices[0].message.content as raw UTF-8 bytes. It NEVER
decodes that content as VPlot: the bytes flow on to schema.decode_spec downstream, so a
malformed-but-extracted spec still reaches a 200 verdict (the model-failure mode M3.4
meters), exactly mirroring the pipeline's raw-body discipline.

Dataset binding (removes a guaranteed-fail noise mode from the eval): the prompt hands the
model json.dumps({"name", "hash"}) with hash = canon.hash_dataset(csv_bytes) to copy
VERBATIM into spec.dataset. The verifier re-checks that hash against the real bytes, so a
copy that corrupts the hash fails closed. The re-check binds faithfulness to the spec's OWN
declared dataset, NOT to the request -- pinning spec.dataset.name to the requested name is
M3.3's endpoint check. The model controls only the dataset NAME, never the trusted files.
The name resolves under settings.data_dir with the checks.py confinement (resolve() +
is_relative_to), authoritative here because the whole name builds the CSV path (unlike
the manifest path, which .stem collapses to a flat component, safe by construction).

Error split (POC_SCOPE service boundary), each branch a distinct fault the caller (M3.3)
maps without a 200:
  - DatasetNotFoundError: the named CSV+manifest is not a readable file (absent, or the name
    denotes a directory / a path through one) OR the name escapes data_dir (the same answer
    either way -> M3.3 404, no store-probe leak).
  - ProposerPolicyError: caller text or bounded dataset/prompt context exceeded policy before
    the backend call (M5.1g 422; no verification outcome exists).
  - ModelUpstreamError(status=503): httpx.RequestError -- the backend is unreachable, or
    connect/read timed out (the wedged-backend hang model_timeout bounds).
  - ModelUpstreamError(status=502): the backend answered but unusably -- a non-2xx status,
    unsupported content coding, an oversized body, a body that is not a chat-completion envelope
    (decode/validation failure), no choices, or empty content. An envelope-decode failure is an
    UPSTREAM fault, never a 200.
A malformed trusted manifest (load_manifest raises), or a permission/OS fault reading a
present file, is operator misconfiguration: the error PROPAGATES (M3.3 500), the model
cannot provoke it (it names only the dataset).

M5.1g bounds every proposer allocation boundary. The request text and sum of system/user
message-content UTF-8 bytes are admitted before the model call; the latter is a byte/memory
bound, not a token or post-chat-template claim. Dataset files reuse the core's limit+1 bounded
reader. The client requests and enforces identity encoding, then streams raw HTTP body bytes into
an exact limit+1 accumulator before status or envelope decode. Oversized success and error bodies
alike become typed 502 faults and never reach the raw-reply/verdict path.
"""

import csv
import json
from io import StringIO
from itertools import chain, islice
from pathlib import Path

import httpx
import msgspec

from verifier import canon, ingest
from verifier.errors import VerificationError
from verifier.limits import read_bounded
from verifier.service.settings import Settings

__all__ = ["DatasetNotFoundError", "ModelUpstreamError", "ProposerPolicyError", "propose_spec"]


class DatasetNotFoundError(Exception):
    """The named dataset has no readable CSV + manifest under data_dir, or the name escapes
    it. M3.3 maps this to 404 -- the same answer whether absent or out-of-root, so probing a
    name reveals nothing about what the store holds. dataset_name carries the offending name
    for logging (never echoed to the untrusted caller)."""

    def __init__(self, dataset_name: str) -> None:
        super().__init__(f"no dataset {dataset_name!r} under the data directory")
        self.dataset_name = dataset_name


class ModelUpstreamError(Exception):
    """The model backend failed as an upstream dependency: unreachable (503) or an unusable
    response (502). M3.3 maps `status` onto a problem+json; the cause is logged and withheld.
    Never a 200 verdict -- no content reached decode_spec, so there is nothing to verify."""

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


class ProposerPolicyError(Exception):
    """Pre-model proposer input/context exceeded trusted operator resource policy.

    The service maps this to a dedicated 422 problem, never a verification verdict: no model
    content exists to verify. ``resource`` is an operator-log classifier and is never echoed to
    the caller.
    """

    def __init__(self, message: str, *, resource: str) -> None:
        super().__init__(message)
        self.resource = resource


# --- OpenAI chat-completion envelope (decode-only; tolerate unknown fields) ---
# The proposer is untrusted, so these pick out only the path to the content and IGNORE every
# other field a real /v1 reply carries (id/model/usage/finish_reason/...): msgspec structs
# tolerate unknown fields by default. content re-decodes strictly downstream, so tolerance
# here is not a trust weakening. A missing/null content -> ValidationError -> a 502 upstream
# fault (not a 200), same as an empty-string content the not-content guard rejects.
class _Message(msgspec.Struct, frozen=True, kw_only=True):
    content: str


class _Choice(msgspec.Struct, frozen=True, kw_only=True):
    message: _Message


class _ChatResponse(msgspec.Struct, frozen=True, kw_only=True):
    choices: tuple[_Choice, ...]


_ENVELOPE_DECODER = msgspec.json.Decoder(_ChatResponse)


# --- proposer prompt ----------------------------------------------------------
# System = the VPlot v0.1 grammar + the proposer rules, one short line per join item (E501
# applies inside the string). Enum options are spelled "one of a, b, c", NEVER "a|b|c": the
# pipe form is exactly the placeholder the weak model echoes back ("mark": "bar|line"), so
# teaching it would manufacture the failure the eval is meant to observe organically.
_SYSTEM_PROMPT = "\n".join(
    [
        "You are proposing a VPlot v0.1 chart specification.",
        "Return exactly one JSON object and nothing else.",
        "Top-level keys: version, dataset, transform, mark, encoding.",
        'version is the string "vplot-0.1".',
        "dataset is an object with keys name and hash; copy it verbatim from the binding below.",
        "mark is one of: bar, line, scatter.",
        "encoding is an object with keys x and y, plus an optional color.",
        "Each of x, y, and color is an object with keys field and type.",
        "A channel type is one of: quantitative, temporal, ordinal, nominal.",
        "transform is an ordered list, possibly empty, of step objects; each has an op key.",
        'select step: {"op": "select", "fields": [column names]}.',
        'filter step: {"op": "filter", "field": column, "cmp": comparison, "value": literal}.',
        "A comparison is one of: eq, ne, lt, le, gt, ge; a value is an integer or a string.",
        "Write a fractional or very large filter value as a string, not a bare number.",
        'group_by step: {"op": "group_by", "keys": [column names]}.',
        'aggregate step: {"op": "aggregate", "measures": [measure objects]}.',
        'A measure is {"field": column, "fn": function, "as": output name}.',
        "A function is one of: sum, mean, count, min, max.",
        'sort step: {"op": "sort", "by": [{"field": column, "order": direction}]}.',
        "A direction is one of: ascending, descending.",
        "Rules you must follow:",
        "Use only the columns listed in the schema below, spelled exactly.",
        "Output only JSON: no prose, Markdown, fences, SQL, Python, JavaScript, or Vega-Lite.",
        'Write concrete values, never placeholders such as "bar or line" or "<column>".',
        "Give every filter an explicit value.",
        "Aggregate a unit-bearing column only with sum, mean, min, or max; count is unitless.",
    ]
)


def _utf8_size_at_most(text: str, max_bytes: int) -> int | None:
    """Exact UTF-8 size when <= ``max_bytes``; stop without encoding the over-limit suffix.

    Encoding one Unicode scalar at a time allocates at most four temporary bytes and lets a huge
    sampled CSV field fail as soon as the remaining prompt budget is crossed.
    """
    size = 0
    for character in text:
        size += len(character.encode("utf-8"))
        if size > max_bytes:
            return None
    return size


class _PromptAssembler:
    """Incremental user-message builder sharing one budget with the fixed system message."""

    __slots__ = ("_item_count", "_limit", "_parts", "_size")

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._size = 0
        self._parts: list[str] = []
        self._item_count = 0
        self._account(_SYSTEM_PROMPT)

    def _account(self, text: str) -> None:
        size = _utf8_size_at_most(text, self._limit - self._size)
        if size is None:
            msg = f"assembled proposer prompt exceeds UTF-8 byte limit of {self._limit}"
            raise ProposerPolicyError(msg, resource="resource.prompt_bytes")
        self._size += size

    def append(self, text: str) -> None:
        """Admit one fragment before retaining it for the final join."""
        self._account(text)
        self._parts.append(text)

    def start_item(self) -> None:
        """Start one of the old newline-joined user-prompt items without joining it yet."""
        if self._item_count:
            self.append("\n")
        self._item_count += 1

    def finish(self) -> str:
        """Join only after every dynamic fragment has passed the shared byte budget."""
        return "".join(self._parts)


def _describe_column(column: ingest.ManifestColumn) -> str:
    """One manifest column -> a one-line schema description for the prompt. Numeric carries
    its scale and, when present, its unit; temporal its granularity; a string column just its
    kind. The weather fixture exercises every arm (temp_c/precip_mm with unit, aqi without,
    date temporal, city string)."""
    if isinstance(column, ingest.NumericColumnSpec):
        if column.unit is not None:
            return f"{column.name}: numeric (scale {column.scale}, unit {column.unit})"
        return f"{column.name}: numeric (scale {column.scale})"
    if isinstance(column, ingest.TemporalColumnSpec):
        return f"{column.name}: temporal ({column.granularity})"
    return f"{column.name}: string"


def _append_sample_rows(builder: _PromptAssembler, csv_bytes: bytes, count: int) -> None:
    """Append header + ``count`` logical rows one cell at a time under the prompt budget.

    UTF-8-SIG drops a leading BOM for display only. ``csv.reader`` keeps a quoted newline in one
    logical row. Cell-wise assembly preserves the former comma/newline output while rejecting a
    huge field before any full sample string is concatenated.
    """
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.reader(StringIO(text, newline=""))
    # Two slices avoid ``count + 1`` overflowing islice's sys.maxsize domain at Settings' valid
    # signed-64-bit maximum. The first consumes at most the header; the second starts after it.
    for row_index, row in enumerate(chain(islice(reader, 1), islice(reader, count))):
        if row_index:
            builder.append("\n")
        for field_index, field in enumerate(row):
            if field_index:
                builder.append(",")
            builder.append(field)


def _build_messages(
    user_request: str,
    dataset_name: str,
    manifest: ingest.Manifest,
    csv_bytes: bytes,
    settings: Settings,
) -> list[dict[str, str]]:
    """Assemble the chat messages: the fixed grammar/rules system prompt, then a user prompt
    carrying the dataset name, the verbatim binding to copy, the column schema, the sample
    rows, and the request. The binding's hash is canon.hash_dataset over the real bytes, so a
    faithful copy passes the verifier's re-check and a corrupted one fails closed."""
    builder = _PromptAssembler(settings.max_prompt_bytes)

    def item(text: str) -> None:
        builder.start_item()
        builder.append(text)

    item(f"Dataset name: {dataset_name}")
    item("Copy this dataset binding verbatim into the spec's dataset field:")
    item(json.dumps({"name": dataset_name, "hash": canon.hash_dataset(csv_bytes)}))
    item("Columns (use these exact names):")
    builder.start_item()
    for index, column in enumerate(manifest.columns):
        if index:
            builder.append("\n")
        builder.append(_describe_column(column))
    item(f"Sample rows (CSV with header, up to {settings.model_sample_rows} data row(s)):")
    builder.start_item()
    _append_sample_rows(builder, csv_bytes, settings.model_sample_rows)
    item(f"User request: {user_request}")
    item("Reply with only the VPlot JSON spec.")
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": builder.finish()},
    ]


def _load_dataset_context(dataset_name: str, settings: Settings) -> tuple[ingest.Manifest, bytes]:
    """Resolve and read the named dataset's CSV bytes + parsed manifest under data_dir, or
    raise DatasetNotFoundError (a 404). The CSV path is built from the whole name, so resolve() +
    is_relative_to is the authoritative confinement (a traversal name that slipped past M3.3's
    DatasetName guard resolves outside the root -> not found). The manifest path uses Path.stem,
    which collapses any directory to a flat component, so it needs no runtime confinement branch
    (the pipeline precedent). The CSV name is wholly caller-picked, so a name denoting no readable
    CSV -- absent (FileNotFoundError), a directory (IsADirectoryError), or a path through a
    non-directory (NotADirectoryError) -- is not-found. The manifest instead lives under the
    trusted schemas/ dir, so it mirrors the pipeline's verify_only: a genuine absence
    (FileNotFoundError) is the not-provisioned 404, but any OTHER OS read fault (a directory or
    regular-file collision, a permission or symlink-loop error) -- like a malformed manifest
    (load_manifest raises) -- is operator misconfiguration and propagates -> the app's 500, which
    the untrusted caller (naming only the dataset) cannot provoke."""
    root = settings.data_dir.resolve()
    csv_path = (root / dataset_name).resolve()
    if not csv_path.is_relative_to(root):
        raise DatasetNotFoundError(dataset_name)
    manifest_path = root / "schemas" / f"{Path(dataset_name).stem}.json"
    try:
        csv_bytes = read_bounded(csv_path, settings.max_csv_bytes)
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
        raise DatasetNotFoundError(dataset_name) from exc
    except VerificationError as exc:
        msg = f"proposer CSV context exceeds policy: {exc}"
        raise ProposerPolicyError(msg, resource="resource.csv_bytes") from exc
    try:
        manifest_bytes = read_bounded(manifest_path, settings.max_manifest_bytes)
    except FileNotFoundError as exc:
        raise DatasetNotFoundError(dataset_name) from exc
    except VerificationError as exc:
        msg = f"proposer manifest context exceeds policy: {exc}"
        raise ProposerPolicyError(msg, resource="resource.manifest_bytes") from exc
    try:
        manifest = ingest.load_manifest(manifest_bytes, limits=settings.limits)
    except VerificationError as exc:
        msg = f"proposer manifest context exceeds policy: {exc}"
        raise ProposerPolicyError(msg, resource=exc.check) from exc
    return manifest, csv_bytes


def _build_async_client(settings: Settings) -> httpx.AsyncClient:
    """The async client for one proposer call, timed out by settings.model_timeout (finite and
    > 0, fail-closed in Settings). A module-level factory so a test injects a MockTransport."""
    return httpx.AsyncClient(timeout=settings.model_timeout)


async def _read_response_bounded(response: httpx.Response, max_bytes: int) -> bytes:
    """Stream at most ``max_bytes + 1`` raw body bytes, then fail 502 and close early."""
    stop = max_bytes + 1
    payload = bytearray()
    async for chunk in response.aiter_raw():
        payload.extend(chunk[: stop - len(payload)])
        if len(payload) == stop:
            msg = f"model backend response exceeds byte limit of {max_bytes}"
            raise ModelUpstreamError(msg, status=502)
    return bytes(payload)


def _extract_content(response_bytes: bytes) -> bytes:
    """The chat-completion reply -> choices[0].message.content as raw UTF-8 bytes, or raise
    ModelUpstreamError(502). A body that is not valid UTF-8 (msgspec raises the builtin
    UnicodeDecodeError, not its own DecodeError) or not a valid envelope, no choices, or empty
    content are all unusable upstream responses -- a 502, never the operator-config 500. NEVER
    decodes the content as VPlot -- that stays downstream, so a malformed-but-present spec flows
    to a 200 verdict."""
    try:
        envelope = _ENVELOPE_DECODER.decode(response_bytes)
    except (msgspec.DecodeError, msgspec.ValidationError, UnicodeDecodeError) as exc:
        msg = f"model reply is not a chat-completion envelope: {exc}"
        raise ModelUpstreamError(msg, status=502) from exc
    if not envelope.choices:
        msg = "model reply carries no choices"
        raise ModelUpstreamError(msg, status=502)
    content = envelope.choices[0].message.content
    if not content:
        msg = "model reply content is empty"
        raise ModelUpstreamError(msg, status=502)
    return content.encode("utf-8")


async def propose_spec(user_request: str, dataset_name: str, settings: Settings) -> bytes:
    """Propose a VPlot spec for `user_request` over `dataset_name`, returning the model's raw
    reply content as bytes (never decoded here). Raises DatasetNotFoundError (unknown/escaping
    name), ProposerPolicyError (pre-model 422), or ModelUpstreamError (503 unreachable / 502
    unusable reply). See the module docstring for the trust and error-split contract."""
    if _utf8_size_at_most(user_request, settings.max_user_request_bytes) is None:
        msg = f"proposer user request exceeds UTF-8 byte limit of {settings.max_user_request_bytes}"
        raise ProposerPolicyError(msg, resource="resource.user_request_bytes")

    manifest, csv_bytes = _load_dataset_context(dataset_name, settings)
    messages = _build_messages(user_request, dataset_name, manifest, csv_bytes, settings)
    payload: dict[str, object] = {
        "model": settings.model_name,
        "messages": messages,
        "temperature": 0,
        "max_tokens": settings.model_max_tokens,
    }
    url = f"{settings.model_base_url.rstrip('/')}/chat/completions"
    async with _build_async_client(settings) as client:
        try:
            async with client.stream(
                "POST", url, json=payload, headers={"accept-encoding": "identity"}
            ) as response:
                content_encoding = response.headers.get("content-encoding")
                if content_encoding is not None and content_encoding.lower() != "identity":
                    msg = (
                        f"model backend returned unsupported content encoding {content_encoding!r}"
                    )
                    raise ModelUpstreamError(msg, status=502)
                response_bytes = await _read_response_bounded(
                    response, settings.max_model_response_bytes
                )
                if not response.is_success:
                    msg = f"model backend returned HTTP {response.status_code}"
                    raise ModelUpstreamError(msg, status=502)
                return _extract_content(response_bytes)
        except httpx.RequestError as exc:
            msg = f"model backend is unreachable: {exc}"
            raise ModelUpstreamError(msg, status=503) from exc
