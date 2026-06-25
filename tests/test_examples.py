# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M1.3 golden corpus checks (decode layer + dataset binding only).

The corpus lives in examples/ (good_specs/, bad_specs/, index.json) over the synthetic
data/ CSVs + their trusted manifests (data/schemas/). This suite asserts each spec
decodes — or fails to — exactly as index.json annotates, that the file set and the
index agree (no drift), that good specs bind to their source bytes by hash, and that
the manifests are well-formed for the M1.4 evaluator.

Syntax only. Semantic rejection of the decodes=true bad specs is the job of M1.4 eval /
M1.5 checks; here we assert they DO decode (their badness is meaning, not shape), so the
layer attribution in index.json stays honest. See VPlot_SEMANTICS.md for the taxonomy.
"""

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from msgspec import DecodeError, ValidationError

from verifier.schema import VPlotSpec, decode_spec

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "good_specs"
_BAD_DIR = _EXAMPLES / "bad_specs"
_DATA = _ROOT / "data"
_SCHEMAS = _DATA / "schemas"

_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["good_specs"]
_BAD: list[dict[str, Any]] = _INDEX["bad_specs"]
_BAD_DECODE: list[dict[str, Any]] = [b for b in _BAD if not b["decodes"]]
_BAD_SEMANTIC: list[dict[str, Any]] = [b for b in _BAD if b["decodes"]]


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(e["file"]).stem for e in entries]


def _source_hash(name: str) -> str:
    return "sha256:" + hashlib.sha256((_DATA / name).read_bytes()).hexdigest()


# --- corpus floor (roadmap M1.3: >=5 good, >=10 bad, 10 intents) -------------
def test_corpus_meets_floor() -> None:
    assert len(_GOOD) >= 5
    assert len(_BAD) >= 10
    assert len({g["intent"] for g in _GOOD}) >= 10  # 10 distinct NL chart intents


# --- index <-> filesystem agree (no orphan files, no dangling entries) -------
@pytest.mark.parametrize(("subdir", "entries"), [("good_specs", _GOOD), ("bad_specs", _BAD)])
def test_index_matches_filesystem(subdir: str, entries: list[dict[str, Any]]) -> None:
    on_disk = {p.name for p in (_EXAMPLES / subdir).glob("*.json")}
    in_index = {e["file"] for e in entries}
    assert on_disk == in_index


# --- good specs: decode + bind to source bytes -------------------------------
@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_good_spec_decodes_and_binds(entry: dict[str, Any]) -> None:
    spec = decode_spec((_GOOD_DIR / entry["file"]).read_bytes())
    assert isinstance(spec, VPlotSpec)
    # the file's referenced dataset matches the index, and the declared hash is the live
    # source hash -> M1.5 dataset.hash_matches_source will pass; hashes are reproducible.
    assert spec.dataset.name == entry["dataset"]
    assert spec.dataset.hash == _source_hash(spec.dataset.name)
    assert spec.mark == entry["mark"]


# --- bad specs: decode-layer rejected now ------------------------------------
@pytest.mark.parametrize("entry", _BAD_DECODE, ids=_ids(_BAD_DECODE))
def test_bad_spec_decode_layer_rejected(entry: dict[str, Any]) -> None:
    raw = (_BAD_DIR / entry["file"]).read_bytes()
    with pytest.raises((ValidationError, DecodeError)):
        decode_spec(raw)


# --- bad specs: semantic-layer still decode (badness deferred to M1.4/M1.5) --
@pytest.mark.parametrize("entry", _BAD_SEMANTIC, ids=_ids(_BAD_SEMANTIC))
def test_bad_spec_semantic_layer_decodes(entry: dict[str, Any]) -> None:
    spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
    assert isinstance(spec, VPlotSpec)


def test_hash_mismatch_fixture_is_genuinely_wrong() -> None:
    # The one dataset-binding bad spec must declare a hash that truly differs from source,
    # else M1.5 would wrongly accept it. (Every other spec declares the live source hash.)
    [entry] = [b for b in _BAD if b["check"] == "dataset.hash_matches_source"]
    spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
    assert spec.dataset.hash != _source_hash(spec.dataset.name)


@pytest.mark.parametrize("entry", _BAD, ids=_ids(_BAD))
def test_bad_spec_declares_source_hash(entry: dict[str, Any]) -> None:
    # Every bad spec pins the LIVE source hash, so the ONLY hash-divergent fixture is the dedicated
    # mismatch one; a silent hash drift in any other fixture (or an over-precise float defect that
    # also corrupted its dataset block) surfaces here. Reads raw JSON, so it covers the decode-fail
    # specs too. Manifest-canonicality test guarantees the source bytes are stable.
    raw: dict[str, Any] = json.loads((_BAD_DIR / entry["file"]).read_text(encoding="utf-8"))
    declared, live = raw["dataset"]["hash"], _source_hash(raw["dataset"]["name"])
    if entry["check"] == "dataset.hash_matches_source":
        assert declared != live
    else:
        assert declared == live


def test_missing_unit_fixture_targets_a_unitless_column() -> None:
    # b13's premise: its quantitative channel plots a field the manifest leaves unit-less. Lock it
    # so a unit added to that column can't silently make the missing-unit fixture pass.
    [entry] = [b for b in _BAD if b["check"] == "label.quantitative_units_present"]
    raw: dict[str, Any] = json.loads((_BAD_DIR / entry["file"]).read_text(encoding="utf-8"))
    stem = Path(raw["dataset"]["name"]).stem
    manifest: dict[str, Any] = json.loads((_SCHEMAS / f"{stem}.json").read_text(encoding="utf-8"))
    units = {c["name"]: c.get("unit") for c in manifest["columns"]}
    quant = [ch["field"] for ch in raw["encoding"].values() if ch["type"] == "quantitative"]
    assert any(units.get(field) is None for field in quant)


# --- datasets + manifests ----------------------------------------------------
_NUMERIC, _TEMPORAL, _STRING = "numeric", "temporal", "string"


def test_index_dataset_hashes_are_live() -> None:
    for d in _INDEX["datasets"]:
        assert d["hash"] == _source_hash(d["name"])


@pytest.mark.parametrize("dataset", _INDEX["datasets"], ids=lambda d: d["name"])
def test_manifest_well_formed(dataset: dict[str, Any]) -> None:
    manifest_path = _ROOT / dataset["manifest"]
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset"] == dataset["name"]

    # column order matches the CSV header; every column is typed per the semantics model.
    header = (_DATA / dataset["name"]).read_text(encoding="utf-8").splitlines()[0].split(",")
    columns: list[dict[str, Any]] = manifest["columns"]
    assert [c["name"] for c in columns] == header

    for col in columns:
        assert col["type"] in {_NUMERIC, _TEMPORAL, _STRING}
        if col["type"] == _NUMERIC:
            assert isinstance(col["scale"], int)
            assert col["scale"] >= 0
        if col["type"] == _TEMPORAL:
            assert col["granularity"] in {"date", "datetime"}


def _max_decimals(values: list[str]) -> int:
    out = 0
    for v in values:
        if v and "." in v:
            out = max(out, len(v.split(".", 1)[1]))
    return out


@pytest.mark.parametrize("dataset", _INDEX["datasets"], ids=lambda d: d["name"])
def test_manifest_numeric_scale_matches_data(dataset: dict[str, Any]) -> None:
    # Declared numeric scale == the actual decimal precision in the CSV column, so the manifest
    # can't silently over/under-state the precision the M1.4 evaluator quantizes to.
    manifest: dict[str, Any] = json.loads((_ROOT / dataset["manifest"]).read_text(encoding="utf-8"))
    with (_DATA / dataset["name"]).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for col in manifest["columns"]:
        if col["type"] == _NUMERIC:
            assert col["scale"] == _max_decimals([row[col["name"]] for row in rows])


_TEMPORAL_RE = {
    "date": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "datetime": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?"),
}


@pytest.mark.parametrize("dataset", _INDEX["datasets"], ids=lambda d: d["name"])
def test_temporal_columns_are_canonical(dataset: dict[str, Any]) -> None:
    # §2: temporal cells are zero-padded ISO-8601 (date YYYY-MM-DD / datetime ...Thh:mm:ss). Locks
    # the synthetic data so the M1.4 evaluator's date parsing receives canonical input only.
    manifest: dict[str, Any] = json.loads((_ROOT / dataset["manifest"]).read_text(encoding="utf-8"))
    with (_DATA / dataset["name"]).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for col in manifest["columns"]:
        if col["type"] == _TEMPORAL:
            pattern = _TEMPORAL_RE[col["granularity"]]
            for row in rows:
                cell = row[col["name"]]
                if cell:
                    assert pattern.fullmatch(cell), f"{dataset['name']}.{col['name']}={cell!r}"


def test_manifests_are_canonical_json() -> None:
    # hash-stable provenance input (M1.4 hashes the manifest): bytes already equal the
    # canonical re-serialization, so the committed file is the stable canonical form.
    for p in _SCHEMAS.glob("*.json"):
        loaded: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        canonical = json.dumps(loaded, indent=2, ensure_ascii=False) + "\n"
        assert p.read_text(encoding="utf-8") == canonical
