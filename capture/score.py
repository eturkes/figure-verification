# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Held-out acceptance scorer + its EXACTLY-ONCE guard (contract .agent/contracts/m10u9.md, S1-S8).

A pure function of one committed run, the committed corpus manifests (denominators + sentinel ids)
and the tracked CSV bytes under the committed verifier, so the gate re-derives the committed
`score.json` byte for byte and a later verifier change that moves a verdict shows up as
drift rather than as a silent rewrite of the recorded claim.

Three outcomes, never two: a record the backend never answered is a TRANSPORT fault, and scoring
its absent content as an empty program would hand the complicated arm a refusal it never earned
(`w1_width.py` does exactly that, which is why this is not that script).

Denominators come from the CORPUS, not from the records present: a missing row stays in its
category and counts in no numerator. Sentinels sit outside both denominators and are judged alone.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

import msgspec

from capture.corpus import REPO_ROOT, Category, DatasetName, Kind, load_corpus
from capture.harness import defence
from capture.record import CaptureRecord, Run, decode_run, load_run
from verifier.pysrc import Verified, verify_python_source
from verifier.pysrc.spec import DatasetPlot, DatasetTarget

SCORE_FILE: Final = "score.json"
SCORE_VERSION: Final = "python-score-1"
HELDOUT_RUN: Final = "m10-heldout"
DATA_ROOT: Final[Path] = REPO_ROOT / "data"
_UPLOADS: Final = "/mnt/uploads/"
_OK: Final = 200
# Intent's bar, as integers so the boundary is exact: 10·count ≥ 7·total.
_BAR_NUMERATOR: Final = 7
_BAR_DENOMINATOR: Final = 10

Outcome = Literal["verified", "refused", "transport_error"]


class ScoreError(ValueError):
    """The inputs cannot be scored as the contract states them."""


class ScoreRow(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One record's outcome; the projected channels publish WHAT verified, never whether it
    answered the request (held-out fidelity is not measured)."""

    prompt_id: str
    kind: Kind
    category: Category
    idiom: str
    dataset_name: DatasetName
    outcome: Outcome
    code: str | None
    mark: str | None
    x: str | None
    y: str | None
    reduction: str | None


class SimpleScore(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    total: int
    verified: int


class ComplicatedScore(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    total: int
    blocked: int


class Summary(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    simple: SimpleScore
    complicated: ComplicatedScore
    transport_errors: int
    sentinels: dict[str, Outcome]
    complete: bool
    acceptance_met: bool


class Score(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    version: Literal["python-score-1"]
    run: str
    summary: Summary
    rows: tuple[ScoreRow, ...]


_DECODER: Final = msgspec.json.Decoder(Score)


def load_data(root: Path = DATA_ROOT) -> dict[str, bytes]:
    """The tracked CSV bytes every record's declared target is built from."""
    return {name: (root / name).read_bytes() for name in ("sales.csv", "weather.csv")}


def _scored(
    record: CaptureRecord, outcome: Outcome, code: str | None, plot: DatasetPlot | None
) -> ScoreRow:
    return ScoreRow(
        prompt_id=record.prompt_id,
        kind=record.kind,
        category=record.category,
        idiom=record.idiom,
        dataset_name=record.dataset_name,
        outcome=outcome,
        code=code,
        mark=None if plot is None else plot.mark,
        x=None if plot is None else plot.x.name,
        y=None if plot is None else plot.y.name,
        reduction=None if plot is None else plot.group,
    )


def _row(record: CaptureRecord, data: Mapping[str, bytes]) -> ScoreRow:
    if record.http_status != _OK or record.content is None:
        return _scored(record, "transport_error", None, None)
    target = DatasetTarget(path=_UPLOADS + record.dataset_name, content=data[record.dataset_name])
    verdict = verify_python_source(defence(record.content)[1], declared_target=target)
    if not isinstance(verdict, Verified):
        return _scored(record, "refused", verdict.code, None)
    if not isinstance(verdict.spec, DatasetPlot):
        # A formula program against a CSV target refuses `target_mismatch`; reaching here would be
        # a verifier defect, and a score row cannot state a figure it has no channels for.
        message = f"{record.prompt_id}: a formula plot verified against a dataset target"
        raise ScoreError(message)
    return _scored(record, "verified", None, verdict.spec)


def _meets(count: int, total: int) -> bool:
    return total > 0 and _BAR_DENOMINATOR * count >= _BAR_NUMERATOR * total


def score_run(run: Run, data: Mapping[str, bytes]) -> Score:
    """Score every record of one run against the committed verifier (S1-S5)."""
    corpus = load_corpus()
    kind = run.manifest.kind
    if kind == "sentinels":
        # A sentinel-only run has no category set to score; `capture run` cannot produce one.
        message = f"{run.manifest.run}: a sentinel-only run has no category denominators"
        raise ScoreError(message)
    own = {prompt.id: prompt for set_kind, prompt in corpus.rows() if set_kind == kind}
    sentinel_ids = {prompt.id: prompt for prompt in corpus.sentinels.prompts}
    rows = tuple(
        sorted((_row(record, data) for record in run.records), key=lambda row: row.prompt_id)
    )

    # Numerators count DISTINCT prompt ids of the run's own set, by CORPUS category: a duplicated
    # record or a row from another set must not move a number (reviewer-3 S-C2).
    def credited(category: Category, outcome: Outcome) -> int:
        return len(
            {
                row.prompt_id
                for row in rows
                if row.prompt_id in own
                and own[row.prompt_id].category == category
                and row.outcome == outcome
            }
        )

    simple = SimpleScore(
        total=sum(prompt.category == "simple" for prompt in own.values()),
        verified=credited("simple", "verified"),
    )
    complicated = ComplicatedScore(
        total=sum(prompt.category == "complicated" for prompt in own.values()),
        blocked=credited("complicated", "refused"),
    )
    sentinels = {row.prompt_id: row.outcome for row in rows if row.kind == "sentinels"}
    expected = set(own) | set(sentinel_ids)
    # A multiset match: an id set alone hides a duplicated record.
    complete = len(rows) == len(expected) and {row.prompt_id for row in rows} == expected
    sentinels_pass = all(
        sentinels.get(prompt_id) == ("verified" if prompt.category == "simple" else "refused")
        for prompt_id, prompt in sentinel_ids.items()
    )
    transport = sum(row.outcome == "transport_error" for row in rows)
    return Score(
        version=SCORE_VERSION,
        run=run.manifest.run,
        summary=Summary(
            simple=simple,
            complicated=complicated,
            transport_errors=transport,
            sentinels=dict(sorted(sentinels.items())),
            complete=complete,
            acceptance_met=complete
            and transport == 0
            and _meets(simple.verified, simple.total)
            and _meets(complicated.blocked, complicated.total)
            and sentinels_pass,
        ),
        rows=rows,
    )


def encode_score(score: Score) -> bytes:
    """Canonical bytes: indent 2 + trailing newline, declaration order (S6)."""
    return msgspec.json.format(msgspec.json.encode(score), indent=2) + b"\n"


def decode_score(raw: bytes) -> Score:
    """Strict decode: an unknown or missing field is an error."""
    return _DECODER.decode(raw)


def score_directory(directory: Path) -> bytes:
    """The bytes `score.json` must hold for one run directory."""
    return encode_score(score_run(load_run(directory), load_data()))


def heldout_guard(root: Path) -> list[str]:
    """EXACTLY-ONCE (S8): one complete held-out run, named `m10-heldout`, carrying its score."""
    runs = sorted(path for path in root.iterdir() if (path / "run.json").is_file())
    held = [path for path in runs if decode_run((path / "run.json").read_bytes()).kind == "heldout"]
    if len(held) != 1:
        names = ", ".join(path.name for path in held) or "none"
        return [f"expected exactly one held-out run under {root}, found {len(held)}: {names}"]
    (directory,) = held
    failures: list[str] = []
    if directory.name != HELDOUT_RUN:
        failures.append(f"the held-out run is named {directory.name}, expected {HELDOUT_RUN}")
    if not score_run(load_run(directory), load_data()).summary.complete:
        failures.append(f"{directory.name} does not hold every held-out and sentinel row")
    if not (directory / SCORE_FILE).is_file():
        failures.append(f"{directory.name} carries no {SCORE_FILE}")
    return failures
