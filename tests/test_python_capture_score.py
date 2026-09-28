# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.9 scorer contract S1-S8: independent fixtures, literal boundaries, no model calls.

Contract: `.agent/contracts/m10u9.md`. Held-out TEXT is never inspected: synthetic prompts copy
only the corpus metadata. Lazy import keeps every predicate independently red before score.py
exists, rather than aborting collection at the first import.
"""

import importlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Protocol, cast

import msgspec
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from capture.corpus import Category, DatasetName, Kind, Prompt, load_corpus
from capture.harness import CaptureConfig, build_manifest, main
from capture.record import (
    CaptureRecord,
    Run,
    Usage,
    build_record,
    build_request_body,
    encode_records,
    encode_run,
    load_run,
    write_run,
)

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "corpus/python/captures/m10-design"
type Outcome = Literal["verified", "refused", "transport_error"]
type Document = dict[str, Any]

REFUSED = "import matplotlib.pyplot as plt\nplt.subplots(2, 2)\n"


class Scorer(Protocol):
    SCORE_FILE: str
    ScoreError: type[ValueError]

    def score_run(self, run: Run, data: Mapping[str, bytes]) -> object: ...

    def encode_score(self, score: object) -> bytes: ...

    def decode_score(self, raw: bytes) -> object: ...

    def heldout_guard(self, root: Path) -> list[str]: ...


def scorer() -> Scorer:
    return cast(Scorer, importlib.import_module("capture.score"))


def datasets() -> dict[str, bytes]:
    return {name: (ROOT / "data" / name).read_bytes() for name in ("sales.csv", "weather.csv")}


def verified_program(dataset: str, *, raw: bool = False) -> str:
    if dataset == "sales.csv":
        key, value = "region", "revenue"
        raw_x, raw_y = "orders", "revenue"
    else:
        assert dataset == "weather.csv"
        key, value = "city", "temp_c"
        raw_x, raw_y = "precip_mm", "temp_c"
    prefix = (
        "import pandas as pd\nimport matplotlib.pyplot as plt\n"
        f"df = pd.read_csv('/mnt/uploads/{dataset}')\n"
    )
    if raw:
        return prefix + f"plt.scatter(df['{raw_x}'], df['{raw_y}'])\nplt.show()\n"
    return (
        prefix
        + f"g = df.groupby('{key}')['{value}'].sum()\n"
        + "plt.bar(g.index, g.values)\nplt.show()\n"
    )


def metadata(kind: Kind = "heldout") -> tuple[tuple[Kind, Prompt], ...]:
    """Copy only id/category/idiom/dataset; replace text before record builders see it."""
    corpus = load_corpus()
    own = {"heldout": corpus.heldout, "design": corpus.design, "sentinels": corpus.sentinels}[kind]
    selected = (own,) if kind == "sentinels" else (own, corpus.sentinels)
    return tuple(
        (
            prompt_set.kind,
            Prompt(
                id=prompt.id,
                category=prompt.category,
                idiom=prompt.idiom,
                dataset_name=prompt.dataset_name,
                prompt="Synthetic scorer fixture.",
            ),
        )
        for prompt_set in selected
        for prompt in prompt_set.prompts
    )


def record(  # noqa: PLR0913 — independent input coordinates of S1-S5
    prompt_id: str,
    outcome: Outcome,
    *,
    category: Category = "simple",
    kind: Kind = "heldout",
    dataset: DatasetName = "sales.csv",
    idiom: str = "bar_category_sum",
    content: str | None = None,
    name: str = "m10-heldout",
) -> CaptureRecord:
    prompt = Prompt(
        id=prompt_id,
        category=category,
        idiom=idiom,
        dataset_name=dataset,
        prompt="Synthetic scorer fixture.",
    )
    body = build_request_body(
        prompt=prompt.prompt, model="Qwen2.5-Coder-0.5B-Instruct", max_tokens=512, temperature=0.0
    )
    transported = outcome == "transport_error"
    program = verified_program(dataset) if outcome == "verified" else REFUSED
    return build_record(
        run=name,
        prompt=prompt,
        kind=kind,
        request_body=body,
        http_status=0 if transported else 200,
        content=None if transported else (program if content is None else content),
        finish_reason=None if transported else "stop",
        usage=None
        if transported
        else Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        error="synthetic transport fault" if transported else None,
    )


def make_run(
    records: Sequence[CaptureRecord],
    directory: Path = Path("m10-heldout"),
    *,
    kind: Kind = "heldout",
) -> Run:
    provenance = load_run(DESIGN).manifest.provenance
    manifest = build_manifest(
        directory.name,
        kind=kind,
        config=CaptureConfig(
            base_url="http://backend.test",
            model="Qwen2.5-Coder-0.5B-Instruct",
            max_tokens=512,
            temperature=0.0,
        ),
        provenance=provenance,
        record_count=len(records),
    )
    renamed = tuple(msgspec.structs.replace(row, run=directory.name) for row in records)
    return Run(
        directory=directory,
        manifest=manifest,
        records=renamed,
        run_bytes=encode_run(manifest),
        records_bytes=encode_records(renamed),
    )


def full_run(
    simple: int = 20,
    complicated: int = 20,
    *,
    changes: Mapping[str, Outcome | None] | None = None,
    directory: Path = Path("m10-heldout"),
    kind: Kind = "heldout",
) -> Run:
    limits = {"simple": simple, "complicated": complicated}
    seen = {"simple": 0, "complicated": 0}
    records = []
    for row_kind, prompt in metadata(kind):
        if row_kind == "sentinels":
            outcome: Outcome | None = "verified" if prompt.category == "simple" else "refused"
        else:
            seen[prompt.category] += 1
            good = seen[prompt.category] <= limits[prompt.category]
            outcome = "verified" if good == (prompt.category == "simple") else "refused"
        if changes is not None:
            outcome = changes.get(prompt.id, outcome)
        if outcome is not None:
            records.append(
                record(
                    prompt.id,
                    outcome,
                    category=prompt.category,
                    kind=row_kind,
                    dataset=prompt.dataset_name,
                    idiom=prompt.idiom,
                )
            )
    return make_run(records, directory, kind=kind)


def document(run: Run, data: Mapping[str, bytes] | None = None) -> Document:
    api = scorer()
    return cast(
        Document,
        json.loads(api.encode_score(api.score_run(run, datasets() if data is None else data))),
    )


def save_run(run: Run) -> None:
    write_run(run.directory, run.manifest, run.records)


@pytest.mark.parametrize("status", [0, 199, 201, 400, 429, 500, 599])
def test_s1_three_outcomes_and_no_verifier_call_on_transport(
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S1: every non-200 outcome bypasses the verifier; the downstream bomb counts calls."""
    api = scorer()
    module = cast(ModuleType, api)
    calls = []

    def bomb(source: str, *, declared_target: object) -> object:
        calls.append((source, declared_target))
        pytest.fail("transport row reached verify_python_source")

    monkeypatch.setattr(module, "verify_python_source", bomb)
    row = msgspec.structs.replace(
        record("heldout-complicated-01", "transport_error", category="complicated"),
        http_status=status,
    )
    result = document(make_run([row]))
    assert calls == []
    assert result["rows"][0]["outcome"] == "transport_error"
    assert result["rows"][0]["code"] is None
    assert result["summary"]["transport_errors"] == 1
    assert result["summary"]["complicated"] == {"total": 20, "blocked": 0}


@pytest.mark.parametrize(
    "wrapper", ["{}", "```python\n{}```", "A chart:\n```python\n{}```\nDone.", "```python\n{}"]
)
def test_s1_verifier_scores_the_defenced_source(wrapper: str) -> None:
    """S1: successful replies use the shared de-fencer; refusal keeps the verifier's code."""
    run = make_run(
        [
            record(
                "heldout-simple-01",
                "verified",
                content=wrapper.format(verified_program("sales.csv")),
            ),
            record("heldout-complicated-01", "refused", category="complicated"),
            record("heldout-complicated-02", "transport_error", category="complicated"),
        ]
    )
    rows = {row["prompt_id"]: row for row in document(run)["rows"]}
    assert rows["heldout-simple-01"]["outcome"] == "verified"
    assert rows["heldout-complicated-01"]["outcome"] == "refused"
    assert rows["heldout-complicated-01"]["code"] == "call_target_not_admitted"
    assert rows["heldout-complicated-02"]["outcome"] == "transport_error"


@pytest.mark.parametrize("content", ["", "   ", "not valid python", "\u0000"])
def test_s1_invalid_successful_reply_is_refused_not_transport(content: str) -> None:
    """S1: HTTP 200 with unusable source is still a verifier outcome, never a transport fault."""
    run = make_run(
        [record("heldout-complicated-01", "refused", category="complicated", content=content)]
    )
    result = document(run)
    assert result["rows"][0]["outcome"] == "refused"
    assert result["rows"][0]["code"] is not None
    assert result["summary"]["transport_errors"] == 0
    assert result["summary"]["complicated"] == {"total": 20, "blocked": 1}


def test_s2_the_declared_target_comes_from_the_record() -> None:
    """S2: a weather program verifies for weather, but refuses on a sales record."""
    program = verified_program("weather.csv")
    control = record("weather-control", "verified", dataset="weather.csv", content=program)
    wrong = record("sales-record", "verified", dataset="sales.csv", content=program)
    rows = {row["prompt_id"]: row for row in document(make_run([control, wrong]))["rows"]}
    assert rows["weather-control"]["outcome"] == "verified"
    assert rows["sales-record"]["outcome"] == "refused"
    assert rows["sales-record"]["code"] == "target_mismatch"


def test_s2_target_uses_the_supplied_dataset_bytes() -> None:
    """S2: same filename and program, different target bytes; no hidden disk reload."""
    run = make_run([record("sales-record", "verified")])
    assert document(run)["rows"][0]["outcome"] == "verified"
    data = datasets()
    data["sales.csv"] = data["sales.csv"].replace(b"12000", b"NA")
    row = document(run, data)["rows"][0]
    assert row["outcome"] == "refused"
    assert row["code"] == "value_not_in_profile"


@pytest.mark.parametrize("category", ["simple", "complicated"])
@pytest.mark.parametrize("outcome", ["verified", "refused", "transport_error"])
def test_s3_denominators_exclude_sentinels_and_keep_transport_rows(
    category: Category,
    outcome: Outcome,
) -> None:
    """S3: a third sentinel contributes no category count, including on transport failure."""
    run = full_run(
        changes={
            "heldout-simple-01": "transport_error",
            "heldout-complicated-01": "transport_error",
        }
    )
    extra = record("sentinel-extra", outcome, category=category, kind="sentinels")
    summary = document(make_run([*run.records, extra]))["summary"]
    assert summary["simple"] == {"total": 20, "verified": 19}
    assert summary["complicated"] == {"total": 20, "blocked": 19}
    assert summary["transport_errors"] == (3 if outcome == "transport_error" else 2)
    assert summary["sentinels"]["sentinel-extra"] == outcome
    assert summary["complete"] is False


def test_s3_sentinel_only_run_is_rejected() -> None:
    """S3 A1: sentinel-only manifests have no category denominator and raise ScoreError."""
    api = scorer()
    assert issubclass(api.ScoreError, ValueError)
    with pytest.raises(api.ScoreError):
        api.score_run(full_run(kind="sentinels"), datasets())


@pytest.mark.parametrize(("kind", "total"), [("heldout", 20), ("design", 24)])
@pytest.mark.parametrize("category", ["simple", "complicated"])
def test_s3_missing_rows_stay_in_the_corpus_denominator(
    kind: Kind,
    total: int,
    category: Category,
) -> None:
    """S3 clarification: the corpus defines totals even when one expected record is absent."""
    run = full_run(total, total, kind=kind, changes={f"{kind}-{category}-01": None})
    summary = document(run)["summary"]
    assert summary["simple"] == {"total": total, "verified": total - (category == "simple")}
    assert summary["complicated"] == {
        "total": total,
        "blocked": total - (category == "complicated"),
    }
    assert summary["complete"] is False
    assert summary["acceptance_met"] is False


@pytest.mark.parametrize(
    ("simple", "complicated", "accepted"),
    [
        (17, 17, True),
        (16, 17, False),
        (17, 16, False),
    ],
)
def test_s4_design_acceptance_uses_its_own_corpus(
    simple: int,
    complicated: int,
    *,
    accepted: bool,
) -> None:
    """S4 clarification: a complete design run uses 24/24; 17 passes and 16 misses 70%."""
    summary = document(full_run(simple, complicated, kind="design"))["summary"]
    assert summary["simple"] == {"total": 24, "verified": simple}
    assert summary["complicated"] == {"total": 24, "blocked": complicated}
    assert summary["complete"] is True
    assert summary["acceptance_met"] is accepted


@pytest.mark.parametrize(
    ("simple", "complicated", "accepted"),
    [
        (14, 14, True),
        (13, 14, False),
        (14, 13, False),
        (13, 13, False),
        (20, 20, True),
        (0, 20, False),
        (20, 0, False),
        (0, 0, False),
    ],
)
def test_s4_acceptance_boundaries(simple: int, complicated: int, *, accepted: bool) -> None:
    """S4: the joint 14/20 corner passes; either category alone at 13/20 fails."""
    summary = document(full_run(simple, complicated))["summary"]
    assert summary["simple"] == {"total": 20, "verified": simple}
    assert summary["complicated"] == {"total": 20, "blocked": complicated}
    assert summary["complete"] is True
    assert summary["acceptance_met"] is accepted


@pytest.mark.parametrize(
    ("prompt_id", "outcome", "complete", "transport"),
    [
        ("sentinel-simple", "refused", True, 0),
        ("sentinel-complicated", "verified", True, 0),
        ("sentinel-simple", "transport_error", True, 1),
        ("sentinel-complicated", "transport_error", True, 1),
        ("heldout-simple-20", "transport_error", True, 1),
        ("heldout-complicated-20", "transport_error", True, 1),
        ("heldout-simple-20", None, False, 0),
        ("heldout-complicated-20", None, False, 0),
        ("sentinel-simple", None, False, 0),
        ("sentinel-complicated", None, False, 0),
    ],
)
def test_s4_each_conjunct_can_withhold(
    prompt_id: str,
    outcome: Outcome | None,
    *,
    complete: bool,
    transport: int,
) -> None:
    """S4: each sentinel, missing id, and transport condition independently blocks acceptance."""
    summary = document(full_run(changes={prompt_id: outcome}))["summary"]
    assert summary["complete"] is complete
    assert summary["transport_errors"] == transport
    assert summary["acceptance_met"] is False


@given(simple=st.integers(0, 20), complicated=st.integers(0, 20))
@example(simple=14, complicated=14)
@example(simple=13, complicated=20)
@example(simple=20, complicated=13)
@settings(max_examples=60)
def test_s4_acceptance_iff_property(simple: int, complicated: int) -> None:
    """S4's iff across the entire integer count domain, not only the threshold anchors."""
    summary = document(full_run(simple, complicated))["summary"]
    assert summary["acceptance_met"] is (simple >= 14 and complicated >= 14)


@pytest.mark.parametrize(("kind", "total"), [("heldout", 20), ("design", 24)])
def test_s4_empty_run_is_incomplete_not_vacuously_accepted(kind: Kind, total: int) -> None:
    summary = document(make_run([], kind=kind))["summary"]
    assert summary == {
        "simple": {"total": total, "verified": 0},
        "complicated": {"total": total, "blocked": 0},
        "transport_errors": 0,
        "sentinels": {},
        "complete": False,
        "acceptance_met": False,
    }


def test_s5_per_row_table_shape() -> None:
    """S5: exact fields, sorted ids, metadata and real projected meanings over all outcomes."""
    run = make_run(
        [
            record("z-verified", "verified"),
            record("m-refused", "refused", category="complicated", idiom="dashboard"),
            record("a-transport", "transport_error", category="complicated"),
        ]
    )
    rows = document(run)["rows"]
    assert [row["prompt_id"] for row in rows] == ["a-transport", "m-refused", "z-verified"]
    keys = {
        "prompt_id",
        "kind",
        "category",
        "idiom",
        "dataset_name",
        "outcome",
        "code",
        "mark",
        "x",
        "y",
        "reduction",
    }
    for row in rows:
        assert set(row) == keys
        assert (row["code"] is not None) is (row["outcome"] == "refused")
        for name in ("mark", "x", "y", "reduction"):
            assert (row[name] is not None) is (row["outcome"] == "verified")
    assert rows[2] == {
        "prompt_id": "z-verified",
        "kind": "heldout",
        "category": "simple",
        "idiom": "bar_category_sum",
        "dataset_name": "sales.csv",
        "outcome": "verified",
        "code": None,
        "mark": "bar",
        "x": "region",
        "y": "revenue",
        "reduction": "sum",
    }
    assert rows[1]["idiom"] == "dashboard"


@pytest.mark.parametrize(
    ("dataset", "x", "y"),
    [
        ("sales.csv", "orders", "revenue"),
        ("weather.csv", "precip_mm", "temp_c"),
    ],
)
def test_s5_verified_raw_column_pair_has_no_reduction(dataset: DatasetName, x: str, y: str) -> None:
    """S5 A1: mark/x/y exist on every VERIFIED row; reduction exists only on an aggregate."""
    source = verified_program(dataset, raw=True)
    row = document(make_run([record("raw-pair", "verified", dataset=dataset, content=source)]))[
        "rows"
    ][0]
    assert row["outcome"] == "verified"
    assert row["code"] is None
    assert (row["mark"], row["x"], row["y"], row["reduction"]) == ("scatter", x, y, None)


@pytest.mark.parametrize(
    ("mark", "call"), [("bar", "bar"), ("barh", "barh"), ("line", "plot"), ("scatter", "scatter")]
)
@pytest.mark.parametrize("reduction", ["sum", "mean", "min", "max"])
def test_s5_publishes_each_mark_and_reduction(mark: str, call: str, reduction: str) -> None:
    """S5: projected meaning is copied, never hard-coded to the common bar/sum fixture."""
    program = (
        "import pandas as pd\nimport matplotlib.pyplot as plt\n"
        "df = pd.read_csv('/mnt/uploads/sales.csv')\n"
        f"g = df.groupby('orders')['revenue'].{reduction}()\n"
        f"plt.{call}(g.index, g.values)\nplt.show()\n"
    )
    row = document(make_run([record("meaning-probe", "verified", content=program)]))["rows"][0]
    assert (row["outcome"], row["code"]) == ("verified", None)
    assert (row["mark"], row["x"], row["y"], row["reduction"]) == (
        mark,
        "orders",
        "revenue",
        reduction,
    )


@given(order=st.permutations((0, 1, 2)))
def test_s5_record_permutation_preserves_score_bytes(order: Sequence[int]) -> None:
    """S5/S6: sorting is an output invariant even for an unsorted in-memory Run."""
    rows = (
        record("z-verified", "verified"),
        record("m-refused", "refused"),
        record("a-transport", "transport_error"),
    )
    api = scorer()
    baseline = api.encode_score(api.score_run(make_run(rows), datasets()))
    shuffled = api.encode_score(
        api.score_run(make_run([rows[index] for index in order]), datasets())
    )
    assert shuffled == baseline


def test_s6_score_bytes_are_deterministic_and_strict() -> None:
    """S6: literal JSON document, key declaration order, indent two, final newline, round trip."""
    run = make_run([record("heldout-simple-probe", "verified")])
    api = scorer()
    first = api.encode_score(api.score_run(run, datasets()))
    assert first == api.encode_score(api.score_run(run, datasets()))
    expected = {
        "version": "python-score-1",
        "run": "m10-heldout",
        "summary": {
            # The probe id is outside the corpus set, so it enters no numerator (lead A1).
            "simple": {"total": 20, "verified": 0},
            "complicated": {"total": 20, "blocked": 0},
            "transport_errors": 0,
            "sentinels": {},
            "complete": False,
            "acceptance_met": False,
        },
        "rows": [
            {
                "prompt_id": "heldout-simple-probe",
                "kind": "heldout",
                "category": "simple",
                "idiom": "bar_category_sum",
                "dataset_name": "sales.csv",
                "outcome": "verified",
                "code": None,
                "mark": "bar",
                "x": "region",
                "y": "revenue",
                "reduction": "sum",
            }
        ],
    }
    assert first == (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode()
    assert api.encode_score(api.decode_score(first)) == first
    assert api.SCORE_FILE == "score.json"


@pytest.mark.parametrize("location", ["root", "summary", "simple", "complicated", "row"])
def test_s6_unknown_fields_refuse_at_every_struct_level(location: str) -> None:
    """S6: forbid_unknown_fields binds nested structs too, not only the envelope."""
    api = scorer()
    value = document(make_run([record("heldout-simple-01", "verified")]))
    targets = {
        "root": value,
        "summary": value["summary"],
        "simple": value["summary"]["simple"],
        "complicated": value["summary"]["complicated"],
        "row": value["rows"][0],
    }
    targets[location]["unexpected_field"] = 1
    with pytest.raises(ValueError):
        api.decode_score(json.dumps(value).encode())


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("version", "python-score-2"),
        ("run", 1),
        ("rows", {}),
        ("total", "20"),
        ("total", 20.0),
        ("total", True),
        ("acceptance_met", 1),
        ("outcome", "blocked"),
    ],
)
def test_s6_strict_decode_rejects_wrong_types_and_closed_values(field: str, bad: object) -> None:
    api = scorer()
    value = document(make_run([record("heldout-simple-01", "verified")]))
    target = value
    if field == "total":
        target = value["summary"]["simple"]
    elif field == "acceptance_met":
        target = value["summary"]
    elif field == "outcome":
        target = value["rows"][0]
    target[field] = bad
    with pytest.raises(ValueError):
        api.decode_score(json.dumps(value).encode())


@pytest.mark.parametrize("raw", [b"", b"{", b"[]", b"null"])
def test_s6_malformed_score_refuses(raw: bytes) -> None:
    api = scorer()
    with pytest.raises(ValueError):
        api.decode_score(raw)


@pytest.mark.parametrize(("simple", "accepted"), [(14, True), (13, False)])
def test_s7_cli_rc_tracks_drift_never_acceptance(
    tmp_path: Path, simple: int, *, accepted: bool
) -> None:
    """S7: writing and validating both a met score and a recorded miss return zero."""
    directory = tmp_path / "m10-heldout"
    run = full_run(simple, 14, directory=directory)
    save_run(run)
    assert main(["score", "--write", str(directory)]) == 0
    raw = (directory / "score.json").read_bytes()
    assert json.loads(raw)["summary"]["acceptance_met"] is accepted
    assert raw == scorer().encode_score(scorer().score_run(load_run(directory), datasets()))
    assert main(["score", str(directory)]) == 0
    assert (directory / "score.json").read_bytes() == raw


def test_s7_cli_requires_an_explicit_run_directory(capsys: pytest.CaptureFixture[str]) -> None:
    """S7 clarification: score is recognized, but nargs='+' refuses a missing directory."""
    with pytest.raises(SystemExit) as caught:
        main(["score"])
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert "required" in captured.err
    assert "invalid choice" not in captured.err


@pytest.mark.parametrize("fault", ["absent", "bytes", "count"])
def test_s7_cli_names_each_missing_or_drifted_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fault: str,
) -> None:
    """S7: a multi-directory check visits and names every drift, never repairs bare-mode files."""
    directories = [tmp_path / "first", tmp_path / "second"]
    for directory in directories:
        save_run(full_run(directory=directory))
    if fault != "absent":
        assert main(["score", "--write", *(str(path) for path in directories)]) == 0
        for directory in directories:
            path = directory / "score.json"
            raw = path.read_bytes()
            if fault == "bytes":
                path.write_bytes(raw + b"\n")
            else:
                value = json.loads(raw)
                value["summary"]["simple"]["verified"] = 0
                path.write_text(json.dumps(value), encoding="utf-8")
    before = {
        path: (path / "score.json").read_bytes() if (path / "score.json").exists() else None
        for path in directories
    }
    capsys.readouterr()
    assert main(["score", *(str(path) for path in directories)]) == 1
    captured = capsys.readouterr()
    for directory in directories:
        assert str(directory) in captured.out + captured.err
        path = directory / "score.json"
        assert (path.read_bytes() if path.exists() else None) == before[directory]


@pytest.mark.parametrize(
    ("case", "failures"),
    [
        ("zero", 1),
        ("one", 0),
        ("two", 1),
        ("wrong-name", 1),
        ("missing-row", 1),
        ("missing-sentinel", 1),
        ("extra-row", 1),
        ("absent-score", 1),
        ("design-only", 1),
        ("one-plus-design", 0),
        ("transport-miss", 0),
    ],
)
def test_s8_exactly_once_guard(tmp_path: Path, case: str, failures: int) -> None:
    """S8: one complete named heldout run and score existence; acceptance is not a guard input."""
    api = scorer()
    if case != "zero":
        directory = tmp_path / ("wrong" if case == "wrong-name" else "m10-heldout")
        changes: dict[str, Outcome | None] = {}
        if case == "missing-row":
            changes["heldout-simple-01"] = None
        if case == "missing-sentinel":
            changes["sentinel-simple"] = None
        if case == "transport-miss":
            changes["heldout-simple-01"] = "transport_error"
        run = full_run(changes=changes, directory=directory)
        if case == "extra-row":
            run = make_run(
                [*run.records, record("sentinel-extra", "refused", kind="sentinels")], directory
            )
        if case == "design-only":
            run = make_run(run.records, directory, kind="design")
        save_run(run)
        if case != "absent-score":
            (directory / "score.json").write_bytes(api.encode_score(api.score_run(run, datasets())))
        if case in {"two", "one-plus-design"}:
            second = make_run(
                run.records, tmp_path / "another", kind="heldout" if case == "two" else "design"
            )
            save_run(second)
            (second.directory / "score.json").write_bytes(
                api.encode_score(api.score_run(second, datasets()))
            )
    found = api.heldout_guard(tmp_path)
    assert isinstance(found, list)
    assert all(isinstance(failure, str) for failure in found)
    assert all(found)
    assert len(found) == failures
    # A count alone passes a guard that fails a second run for its NAME instead (lead amendment A1):
    # the zero- and two-run failures must state the held-out run count they found.
    if case in {"zero", "two"}:
        assert f"found {0 if case == 'zero' else 2}" in found[0], found
