# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Model proposer client (M3.2b): (user request, dataset name) -> raw model reply bytes.

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
corrupted copy fails closed. The model controls only the dataset NAME, never the trusted
files. The name resolves under settings.data_dir with the checks.py confinement (resolve()
+ is_relative_to), authoritative here because the whole name builds the CSV path (unlike
the manifest path, which .stem collapses to a flat component, safe by construction).

Error split (POC_SCOPE service boundary), each branch a distinct fault the caller (M3.3)
maps without a 200:
  - DatasetNotFoundError: the named CSV+manifest is absent OR the name escapes data_dir
    (the same answer either way -> M3.3 404, no store-probe leak).
  - ModelUpstreamError(status=503): httpx.RequestError -- the backend is unreachable, or
    connect/read timed out (the wedged-backend hang model_timeout bounds).
  - ModelUpstreamError(status=502): the backend answered but unusably -- a non-2xx status,
    a response body that is not a chat-completion envelope (decode/validation failure), no
    choices, or empty content. An envelope-decode failure is an UPSTREAM fault, never a 200.
A malformed trusted manifest is operator misconfiguration: load_manifest raises and the
error PROPAGATES (M3.3 500), the model cannot provoke it (it names only the dataset).
"""

import csv
import json
from io import StringIO
from itertools import islice
from pathlib import Path

import httpx
import msgspec

from verifier import canon, ingest
from verifier.service.settings import Settings

__all__ = ["DatasetNotFoundError", "ModelUpstreamError", "propose_spec"]


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
        "A comparison is one of: eq, ne, lt, le, gt, ge; a value is a number or a string.",
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


def _sample_rows(csv_bytes: bytes, count: int) -> str:
    """Header + up to `count` data rows of the CSV as a display sample (never hashed). Decodes
    utf-8-sig so a leading BOM is dropped for display only, parses with csv so a quoted newline
    keeps its logical row, and re-joins with commas -- a readable example of the values, not a
    byte-faithful echo (the trusted fixtures carry no embedded commas or quotes)."""
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.reader(StringIO(text, newline=""))
    return "\n".join(",".join(row) for row in islice(reader, count + 1))


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
    binding = json.dumps({"name": dataset_name, "hash": canon.hash_dataset(csv_bytes)})
    columns = "\n".join(_describe_column(column) for column in manifest.columns)
    sample = _sample_rows(csv_bytes, settings.model_sample_rows)
    user = "\n".join(
        [
            f"Dataset name: {dataset_name}",
            "Copy this dataset binding verbatim into the spec's dataset field:",
            binding,
            "Columns (use these exact names):",
            columns,
            f"Sample rows (CSV with header, up to {settings.model_sample_rows} data row(s)):",
            sample,
            f"User request: {user_request}",
            "Reply with only the VPlot JSON spec.",
        ]
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _load_dataset_context(dataset_name: str, settings: Settings) -> tuple[ingest.Manifest, bytes]:
    """Resolve and read the named dataset's CSV bytes + parsed manifest under data_dir, or
    raise DatasetNotFoundError. The CSV path is built from the whole name, so resolve() +
    is_relative_to is the authoritative confinement (a traversal name that slipped past M3.3's
    DatasetName guard resolves outside the root -> not found). The manifest path uses Path.stem,
    which collapses any directory to a flat component, so it needs no runtime confinement branch
    (the pipeline precedent). A genuinely absent file (FileNotFoundError) is not-found; a
    malformed manifest propagates from load_manifest as operator misconfiguration."""
    root = settings.data_dir.resolve()
    csv_path = (root / dataset_name).resolve()
    if not csv_path.is_relative_to(root):
        raise DatasetNotFoundError(dataset_name)
    manifest_path = root / "schemas" / f"{Path(dataset_name).stem}.json"
    try:
        csv_bytes = csv_path.read_bytes()
        manifest_bytes = manifest_path.read_bytes()
    except FileNotFoundError as exc:
        raise DatasetNotFoundError(dataset_name) from exc
    return ingest.load_manifest(manifest_bytes), csv_bytes


def _build_async_client(settings: Settings) -> httpx.AsyncClient:
    """The async client for one proposer call, timed out by settings.model_timeout (finite and
    > 0, fail-closed in Settings). A module-level factory so a test injects a MockTransport."""
    return httpx.AsyncClient(timeout=settings.model_timeout)


def _extract_content(response: httpx.Response) -> bytes:
    """The chat-completion reply -> choices[0].message.content as raw UTF-8 bytes, or raise
    ModelUpstreamError(502). A body that is not a valid envelope, no choices, or empty content
    are all unusable upstream responses. NEVER decodes the content as VPlot -- that stays
    downstream, so a malformed-but-present spec flows to a 200 verdict."""
    try:
        envelope = _ENVELOPE_DECODER.decode(response.content)
    except (msgspec.DecodeError, msgspec.ValidationError) as exc:
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
    name) or ModelUpstreamError (503 unreachable / 502 unusable reply). See the module
    docstring for the trust and error-split contract."""
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
            response = await client.post(url, json=payload)
        except httpx.RequestError as exc:
            msg = f"model backend is unreachable: {exc}"
            raise ModelUpstreamError(msg, status=503) from exc
        if not response.is_success:
            msg = f"model backend returned HTTP {response.status_code}"
            raise ModelUpstreamError(msg, status=502)
        return _extract_content(response)
