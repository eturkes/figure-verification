# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M1.5a verifier-spine tests: structured report + binding + eval-surface + affirmations.

verify() recomputes the plotted data and emits a VerificationReport; M1.6 renders only
when report.passed. This suite drives it from the M1.3 corpus (examples/index.json):
decode-layer specs never reach verify; the a-handled decodes=true bad specs (binding +
eval-surfaced) each fail with exactly their indexed check; good specs pass and inline the
recomputation. Encoding/label specs (b11-b13) are M1.5b territory, excluded here. A
Hypothesis property pins the spine invariant: verify inlines exactly what eval recomputes.
"""

import csv
import io
import json
import tempfile
from pathlib import Path
from typing import Any

import msgspec
import pytest
from hypothesis import given
from hypothesis import strategies as st
from msgspec import DecodeError, ValidationError

from verifier import canon, ingest
from verifier.checks import verify
from verifier.eval import evaluate
from verifier.schema import decode_spec

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "good_specs"
_BAD_DIR = _EXAMPLES / "bad_specs"
_DATA = _ROOT / "data"
_SCHEMAS = _DATA / "schemas"

_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["good_specs"]
_BAD: list[dict[str, Any]] = _INDEX["bad_specs"]

# M1.5b territory (encoding/label); the M1.5a spine does not yet catch these.
_ENCODING_CHECKS = frozenset(
    {
        "encoding.fields_exist_in_plotted_table",
        "encoding.axis_types_match_fields",
        "label.quantitative_units_present",
    }
)
# decodes=false -> rejected at decode_spec; verify is never reached.
_BAD_DECODE = [b for b in _BAD if not b["decodes"]]
# a-handled: decodes=true bad specs the spine catches now (binding + eval-surface).
_A_BAD = [b for b in _BAD if b["decodes"] and b["check"] not in _ENCODING_CHECKS]


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(e["file"]).stem for e in entries]


def _manifest_for(name: str) -> ingest.Manifest:
    return ingest.load_manifest((_SCHEMAS / f"{Path(name).stem}.json").read_bytes())


# --- corpus split guards (no silent vacuous parametrization) ------------------
def test_a_handled_covers_binding_and_eval_surface() -> None:
    checks = {b["check"] for b in _A_BAD}
    assert "dataset.hash_matches_source" in checks  # binding gate
    assert len(_A_BAD) >= 7  # b08 binding + b07/b09/b10/b14/b15/b16 eval-surfaced
    assert _BAD_DECODE  # decode-layer specs exist to assert verify is unreached


# --- decode layer: verify is never reached -----------------------------------
@pytest.mark.parametrize("entry", _BAD_DECODE, ids=_ids(_BAD_DECODE))
def test_decode_layer_specs_never_reach_verify(entry: dict[str, Any]) -> None:
    # decode_spec is the sole VPlotSpec constructor, so a decode-layer rejection means no
    # VPlotSpec ever reaches verify() — the trust gate's first line is the decoder.
    raw = (_BAD_DIR / entry["file"]).read_bytes()
    with pytest.raises((ValidationError, DecodeError)):
        decode_spec(raw)


# --- a-handled bad specs: each fails with exactly its indexed check -----------
@pytest.mark.parametrize("entry", _A_BAD, ids=_ids(_A_BAD))
def test_a_handled_bad_spec_fails_its_check(entry: dict[str, Any]) -> None:
    spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=_DATA)
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {entry["check"]}  # a non-empty fail set also means not passed


def test_no_false_accepts_over_a_handled_bad_specs() -> None:
    accepted = 0
    for entry in _A_BAD:
        spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
        manifest = _manifest_for(spec.dataset.name)
        if verify(spec, manifest, data_dir=_DATA).passed:
            accepted += 1
    assert accepted == 0


# --- good specs: pass and inline the recomputation ---------------------------
@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_good_spec_passes_and_inlines_recomputation(entry: dict[str, Any]) -> None:
    spec = decode_spec((_GOOD_DIR / entry["file"]).read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=_DATA)
    assert report.passed
    assert report.plotted_table is not None  # narrow Table | None for the hash compare
    csv_bytes = (_DATA / spec.dataset.name).read_bytes()
    expected = evaluate(spec, manifest, csv_bytes)
    assert canon.hash_table(report.plotted_table) == canon.hash_table(expected)


# --- dataset-binding gate: escape + missing (mismatch is covered by b08) ------
def test_binding_rejects_symlink_escape(tmp_path: Path) -> None:
    # A decoded DatasetName forbids '/', so the only path escape is a symlink inside
    # data_dir pointing out; resolve() exposes the target as a non-relative path.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.csv").write_bytes(b"month,revenue\n2024-01,1.00\n")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sales.csv").symlink_to(outside / "secret.csv")
    spec = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    manifest = _manifest_for(spec.dataset.name)  # both bind sales.csv -> pairing OK
    report = verify(spec, manifest, data_dir=data_dir)
    assert not report.passed
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {"dataset.hash_matches_source"}


def test_binding_rejects_missing_source(tmp_path: Path) -> None:
    # An empty data_dir: the bound name resolves inside it (no escape) but cannot be read.
    spec = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=tmp_path)
    assert not report.passed
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {"dataset.hash_matches_source"}


# --- pairing precondition: a caller bug, not a verification outcome -----------
def test_pairing_mismatch_raises_value_error() -> None:
    spec = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    paired = _manifest_for(spec.dataset.name)
    mispaired = msgspec.structs.replace(paired, dataset="other.csv")
    with pytest.raises(ValueError):
        verify(spec, mispaired, data_dir=_DATA)


# --- spine property: verify inlines exactly what eval recomputes --------------
# A fixed string-key + scale-2-numeric manifest with a group_by/sum/sort pipeline;
# Hypothesis varies only the rows (so no valid-spec generation is needed).
_PROP_HEADER = ["k", "v"]
_PROP_MANIFEST = ingest.load_manifest(
    msgspec.json.encode(
        {
            "dataset": "t.csv",
            "columns": [
                {"type": "string", "name": "k"},
                {"type": "numeric", "name": "v", "scale": 2},
            ],
        }
    )
)
_PROP_SPEC = decode_spec(
    msgspec.json.encode(
        {
            "version": "vplot-0.1",
            "dataset": {"name": "t.csv", "hash": "sha256:" + "0" * 64},
            "transform": [
                {"op": "group_by", "keys": ["k"]},
                {"op": "aggregate", "measures": [{"field": "v", "fn": "sum", "as": "total"}]},
                {"op": "sort", "by": [{"field": "total", "order": "descending"}]},
            ],
            "mark": "bar",
            "encoding": {
                "x": {"field": "k", "type": "nominal"},
                "y": {"field": "total", "type": "quantitative"},
            },
        }
    )
)


def _scale2(units: int) -> str:
    # Exact scale-2 decimal text via integer arithmetic (no float); ingest coerces cleanly.
    sign = "-" if units < 0 else ""
    mag = abs(units)
    return f"{sign}{mag // 100}.{mag % 100:02d}"


_NUMERIC_OR_NULL = st.integers(min_value=-(10**10), max_value=10**10).map(_scale2) | st.just("")
_PROP_ROWS = st.lists(
    st.tuples(st.text(st.characters(codec="utf-8"), max_size=4), _NUMERIC_OR_NULL),
    max_size=6,
)


def _prop_csv(rows: list[tuple[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_PROP_HEADER)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


@given(rows=_PROP_ROWS)
def test_verify_inlines_exactly_the_recomputation(rows: list[tuple[str, str]]) -> None:
    csv_bytes = _prop_csv(rows)
    live_hash = canon.hash_dataset(csv_bytes)
    spec = msgspec.structs.replace(
        _PROP_SPEC, dataset=msgspec.structs.replace(_PROP_SPEC.dataset, hash=live_hash)
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "t.csv").write_bytes(csv_bytes)
        report = verify(spec, _PROP_MANIFEST, data_dir=data_dir)
    assert report.passed
    assert report.plotted_table is not None
    expected = evaluate(spec, _PROP_MANIFEST, csv_bytes)
    assert canon.hash_table(report.plotted_table) == canon.hash_table(expected)
