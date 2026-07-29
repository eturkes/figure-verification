# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic tests for canonical forms + provenance hashing (M1.4a).

Asserts: the dataset hash is a tag-free raw-byte identity sensitive to row order /
CRLF / BOM; serialize_table emits stable typed-NDJSON (HALF_EVEN numerics, negative
zero folded, null distinct from "null", cells byte-faithful + control-escaped); the
table/spec/manifest hashes are domain-tagged; the spec hash is byte-faithful (NFC-
equivalent filter values hash apart) and flips on an edit; fixed golden vectors pin
the canonical bytes; and all six hashes are byte-identical across two PYTHONHASHSEED
subprocesses.
"""

import decimal
import hashlib
import os
import platform
import subprocess
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any

import msgspec
import pytest

from verifier import canon
from verifier.canon import (
    FormulaSource,
    NumericColumn,
    StringColumn,
    Table,
    TemporalColumn,
    formula_source_bytes,
    hash_dataset,
    hash_formula,
    hash_formula_source,
    hash_manifest,
    hash_matplotlib_script,
    hash_spec,
    hash_table,
    runtime_versions,
    serialize_table,
    spec_bytes,
)
from verifier.schema import FormulaPlotSpec, VPlotSpec, decode_formula_spec, decode_spec

ZERO_HASH = "sha256:" + "0" * 64
# "cafe" in two NFC-equivalent but byte-different forms: precomposed e-acute (U+00E9) vs
# e + combining acute (U+0301). Built via chr() so this source stays pure ASCII.
_CAFE_COMPOSED = "caf" + chr(0x00E9)
_CAFE_DECOMPOSED = "cafe" + chr(0x0301)
_FORMULA_SCRIPT = b"import matplotlib.pyplot as plt\nplt.plot([0.0, 1.0], [0.0, 1.0])\nplt.show()\n"


def _spec(value: object = "West", *, mark: str = "bar") -> VPlotSpec:
    """A valid spec whose single filter carries `value` (the lone non-ASCII-capable site —
    field/dataset names are ASCII by pattern) and whose mark is editable for hash flips."""
    raw: dict[str, Any] = {
        "version": "vplot-0.1",
        "dataset": {"name": "sales.csv", "hash": ZERO_HASH},
        "transform": [{"op": "filter", "field": "region", "cmp": "eq", "value": value}],
        "mark": mark,
        "encoding": {
            "x": {"field": "region", "type": "nominal"},
            "y": {"field": "revenue", "type": "quantitative"},
        },
    }
    return decode_spec(msgspec.json.encode(raw))


def _table() -> Table:
    """A two-column table exercising a string column, a scale-2 numeric, and a null."""
    return Table(
        columns=(StringColumn(name="region"), NumericColumn(name="revenue", scale=2)),
        rows=(("West", Decimal("10.50")), ("East", Decimal("20.00")), (None, None)),
    )


def _formula_source() -> FormulaSource:
    return FormulaSource(
        grammar_version="vplot-expr-0.1",
        numeric_profile="rational-half-even-v1",
        rounding="ROUND_HALF_EVEN",
        ast="(+ (** x 2) 1)",
        start=Decimal("-1.25"),
        stop=Decimal("2.50"),
        samples=16,
        x_scale=2,
        y_scale=3,
    )


def _formula_spec() -> FormulaPlotSpec:
    raw: dict[str, Any] = {
        "version": "vplot-formula-0.1",
        "formula": "x**2",
        "domain": {"start": "-3", "stop": "3", "samples": 13, "x_scale": 1, "y_scale": 2},
        "numeric_profile": "rational-half-even-v1",
        "mark": "line",
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
    return decode_formula_spec(msgspec.json.encode(raw))


# --- dataset hash: tag-free raw-byte source identity -------------------------
def test_hash_dataset_is_tag_free_sha256_of_raw_bytes() -> None:
    raw = b"region,revenue\nWest,10\n"
    assert hash_dataset(raw) == "sha256:" + hashlib.sha256(raw).hexdigest()  # no domain tag


def test_hash_dataset_sensitive_to_order_crlf_and_bom() -> None:
    base = b"region,revenue\nWest,10\nEast,20\n"
    assert hash_dataset(base) == hash_dataset(base)  # identity is stable
    reordered = b"region,revenue\nEast,20\nWest,10\n"
    crlf = base.replace(b"\n", b"\r\n")
    bom = b"\xef\xbb\xbf" + base
    assert len({hash_dataset(x) for x in (base, reordered, crlf, bom)}) == 4  # all distinct


# --- serialize_table: the typed-NDJSON canonical form ------------------------
def test_serialize_table_shape() -> None:
    assert serialize_table(_table()) == (
        '["region:string","revenue:numeric:2"]\n["West",10.50]\n["East",20.00]\n[null,null]\n'
    )


def test_serialize_temporal_descriptor_and_scale_zero() -> None:
    table = Table(
        columns=(TemporalColumn(name="date", granularity="date"), NumericColumn(name="v", scale=0)),
        rows=(("2024-01-01", Decimal(5)),),
    )
    assert serialize_table(table) == '["date:temporal:date","v:numeric:0"]\n["2024-01-01",5]\n'


def test_serialize_escapes_string_cells() -> None:
    """A newline inside a cell is JSON-escaped, so it cannot break the NDJSON line layout."""
    table = Table(columns=(StringColumn(name="s"),), rows=(("a\nb",),))
    assert serialize_table(table) == '["s:string"]\n["a\\nb"]\n'


def test_serialize_emits_raw_utf8_and_escapes_control_and_meta() -> None:
    """Non-ASCII + the JS separators U+2028/U+2029 (raw in JSON) emit as RAW UTF-8 — msgspec
    runs no \\uXXXX pass — while quote, backslash, and NUL are JSON-escaped, so no cell can
    break the NDJSON line structure."""
    raw = _CAFE_COMPOSED + chr(0x2028) + chr(0x2029)
    raw_table = Table(columns=(StringColumn(name="s"),), rows=((raw,),))
    out = serialize_table(raw_table)
    assert out == '["s:string"]\n["' + raw + '"]\n'  # verbatim, unescaped
    out_bytes = out.encode("utf-8")  # assert on the actual hash input, at the byte level
    backslash = chr(0x5C)
    for ch in (chr(0x00E9), chr(0x2028), chr(0x2029)):  # e-acute, line sep, paragraph sep
        assert ch.encode("utf-8") in out_bytes  # present as raw multi-byte UTF-8
        assert (backslash + f"u{ord(ch):04x}").encode("utf-8") not in out_bytes  # never escaped
    quote = chr(0x22)
    hazards = "a" + quote + backslash + chr(0x00)
    token = quote + "a" + backslash + quote + backslash + backslash + backslash + "u0000" + quote
    haz_table = Table(columns=(StringColumn(name="s"),), rows=((hazards,),))
    assert serialize_table(haz_table) == '["s:string"]\n[' + token + "]\n"  # JSON-escaped cell


@pytest.mark.parametrize(
    ("value", "scale", "rendered"),
    [
        (Decimal("1.005"), 2, "1.00"),  # HALF_EVEN: ties to the even (0) digit
        (Decimal("1.015"), 2, "1.02"),  # HALF_EVEN: ties to the even (2) digit
        (Decimal("9.9999"), 2, "10.00"),  # rounding carry within the computed precision
        (Decimal("0.004"), 2, "0.00"),  # magnitude below scale -> precision floor of 1
        (Decimal("12345678901234567890123456789012.5"), 0, "12345678901234567890123456789012"),
    ],
)
def test_format_decimal_half_even_and_precision(value: Decimal, scale: int, rendered: str) -> None:
    table = Table(columns=(NumericColumn(name="v", scale=scale),), rows=((value,),))
    assert serialize_table(table).splitlines()[1] == f"[{rendered}]"


def test_format_decimal_total_over_extreme_finite_magnitude() -> None:
    """canon formats any finite Decimal whose needed precision fits decimal.MAX_PREC: an
    astronomical magnitude formats without raising InvalidOperation (the per-value context
    widens the exponent range past the default ~1e6 Emax); past MAX_PREC it raises LOUDLY
    (the companion test below). Magnitude-bounding the trusted dataset is M1.4b's job."""
    table = Table(columns=(NumericColumn(name="v", scale=0),), rows=((Decimal("1e1000000"),),))
    rendered = serialize_table(table).splitlines()[1]
    assert rendered.startswith("[1") and rendered.endswith("0]")
    assert len(rendered) == 1_000_003  # "[" + "1" + 1e6 zeros + "]"
    assert set(rendered[2:-1]) == {"0"}  # the body is exactly 1e6 zeros
    # A huge-exponent zero (whose adjusted() is the exponent, not 0) is the case that would
    # else push the per-value precision past MAX_PREC; it folds to the canonical at-scale zero.
    huge_zero = Table(
        columns=(NumericColumn(name="v", scale=2),),
        rows=((Decimal("0E+999999999999999999"),),),
    )
    assert serialize_table(huge_zero).splitlines()[1] == "[0.00]"


def test_format_decimal_raises_loudly_past_max_prec() -> None:
    """The totality bound: a NONZERO magnitude whose needed precision (adjusted + scale + 2)
    exceeds decimal.MAX_PREC (~1e18 on 64-bit) raises ValueError at Context construction —
    LOUD, never a silent wrong render. Unreachable through ingest/eval, whose cells are
    DECIMAL(38)-bounded; only a hand-built Table reaches it."""
    table = Table(
        columns=(NumericColumn(name="v", scale=0),),
        rows=((Decimal(f"1E+{decimal.MAX_PREC}"),),),
    )
    with pytest.raises(ValueError, match="prec"):
        serialize_table(table)


def test_negative_zero_is_folded() -> None:
    pos = Table(columns=(NumericColumn(name="v", scale=2),), rows=((Decimal("0.00"),),))
    neg = Table(columns=(NumericColumn(name="v", scale=2),), rows=((Decimal("-0.00"),),))
    assert serialize_table(pos) == serialize_table(neg) == '["v:numeric:2"]\n[0.00]\n'
    assert hash_table(pos) == hash_table(neg)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_serialize_rejects_non_finite_numeric(bad: Decimal) -> None:
    table = Table(columns=(NumericColumn(name="v", scale=2),), rows=((bad,),))
    with pytest.raises(ValueError, match="non-finite"):
        serialize_table(table)


def test_serialize_rejects_type_mismatched_cells() -> None:
    num_got_str = Table(columns=(NumericColumn(name="v", scale=2),), rows=(("x",),))
    with pytest.raises(TypeError, match="non-Decimal"):
        serialize_table(num_got_str)
    text_got_decimal = Table(columns=(StringColumn(name="s"),), rows=((Decimal(1),),))
    with pytest.raises(TypeError, match="non-str"):
        serialize_table(text_got_decimal)


def test_serialize_rejects_row_width_mismatch() -> None:
    table = Table(columns=(StringColumn(name="a"), StringColumn(name="b")), rows=(("x",),))
    with pytest.raises(ValueError, match="shorter"):  # zip(strict=True): row shorter than columns
        serialize_table(table)


def test_serialize_rejects_row_too_long() -> None:
    table = Table(columns=(StringColumn(name="a"),), rows=(("x", "y"),))
    with pytest.raises(ValueError, match="longer"):  # zip(strict=True): the opposite direction
        serialize_table(table)


def test_serialize_handles_empty_rows_and_columns() -> None:
    assert serialize_table(Table(columns=(StringColumn(name="a"),), rows=())) == '["a:string"]\n'
    assert serialize_table(Table(columns=(), rows=((),))) == "[]\n[]\n"


def test_column_kind_discriminator() -> None:
    assert NumericColumn(name="v", scale=2).kind == "numeric"
    assert TemporalColumn(name="d", granularity="datetime").kind == "temporal"
    assert StringColumn(name="s").kind == "string"


def test_table_cells_are_byte_faithful() -> None:
    """Cells are hashed byte-faithfully (NO Unicode normalization): a precomposed vs a
    decomposed "cafe" — NFC-equivalent yet byte-different — must serialize and hash APART,
    locking against a future encoder that normalizes cells (the M1.4d/M1.6 trap)."""
    assert unicodedata.normalize("NFC", _CAFE_DECOMPOSED) == _CAFE_COMPOSED  # same NFC class
    assert _CAFE_COMPOSED != _CAFE_DECOMPOSED  # different code points
    composed = Table(columns=(StringColumn(name="s"),), rows=((_CAFE_COMPOSED,),))
    decomposed = Table(columns=(StringColumn(name="s"),), rows=((_CAFE_DECOMPOSED,),))
    assert serialize_table(composed) != serialize_table(decomposed)
    assert hash_table(composed) != hash_table(decomposed)


# --- resolved formula source + hash domains ---------------------------------
def test_formula_source_bytes_shape() -> None:
    expected = (
        b'grammar="vplot-expr-0.1"\n'
        b'profile="rational-half-even-v1"\n'
        b'rounding="ROUND_HALF_EVEN"\n'
        b"x_scale=2\n"
        b"y_scale=3\n"
        b"samples=16\n"
        b"start=-1.25\n"
        b"stop=2.50\n"
        b'ast="(+ (** x 2) 1)"\n'
    )
    assert formula_source_bytes(_formula_source()) == expected
    assert expected.count(b"\n") == 9


def test_formula_source_bytes_shape_at_a_second_scale() -> None:
    """Pin a full vector at a DIFFERENT x_scale. Whole-payload inequality alone cannot
    catch a serializer that hard-codes the `x_scale=` line, because changing x_scale also
    changes how the endpoints render — so only a second exact form fixes that line."""
    expected = (
        b'grammar="vplot-expr-0.1"\n'
        b'profile="rational-half-even-v1"\n'
        b'rounding="ROUND_HALF_EVEN"\n'
        b"x_scale=3\n"
        b"y_scale=3\n"
        b"samples=16\n"
        b"start=-1.250\n"
        b"stop=2.500\n"
        b'ast="(+ (** x 2) 1)"\n'
    )
    source = msgspec.structs.replace(_formula_source(), x_scale=3)
    assert formula_source_bytes(source) == expected
    assert hash_formula(source) == (
        "sha256:c9a6a1659e5630d59717f5f87f8148c765d8bf0c9e3dec86cf64311e17f82bb8"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("grammar_version", "vplot-expr-0.2"),
        ("numeric_profile", "rational-other-v1"),
        ("rounding", "ROUND_DOWN"),
        ("ast", "(+ (** x 3) 1)"),
        ("start", Decimal("-1.24")),
        ("stop", Decimal("2.51")),
        ("samples", 17),
        ("x_scale", 3),
        ("y_scale", 4),
    ],
)
def test_formula_source_bytes_change_on_every_component(field: str, value: object) -> None:
    source = _formula_source()
    changed = msgspec.structs.replace(source, **{field: value})
    assert formula_source_bytes(changed) != formula_source_bytes(source)


def test_formula_source_bytes_fold_negative_zero_endpoints() -> None:
    source = msgspec.structs.replace(
        _formula_source(),
        start=Decimal("-0"),
        stop=Decimal("-0.00"),
    )
    lines = formula_source_bytes(source).splitlines()
    assert lines[6:8] == [b"start=0.00", b"stop=0.00"]


def test_formula_and_script_hashes_use_separate_domains() -> None:
    payload = b"identical canonical bytes\n"
    expected = {
        domain: "sha256:"
        + hashlib.sha256(f"vplot-{domain}/{canon.CANON_VERSION}\n".encode() + payload).hexdigest()
        for domain in ("table", "spec", "manifest", "formula", "matplotlib-script")
    }
    assert len(set(expected.values())) == 5
    assert hash_formula_source(payload) == expected["formula"]
    assert hash_matplotlib_script(payload) == expected["matplotlib-script"]


def test_hash_formula_composes_over_the_canonical_bytes() -> None:
    source = _formula_source()
    assert hash_formula(source) == hash_formula_source(formula_source_bytes(source))


# --- table hash: domain-tagged over the canonical form -----------------------
def test_hash_table_is_domain_tagged() -> None:
    table = _table()
    tag = f"vplot-table/{canon.CANON_VERSION}\n".encode()
    expected = "sha256:" + hashlib.sha256(tag + serialize_table(table).encode()).hexdigest()
    assert hash_table(table) == expected


def test_hash_table_flips_on_cell_column_or_scale() -> None:
    base = hash_table(_table())
    other_cell = Table(
        columns=(StringColumn(name="region"), NumericColumn(name="revenue", scale=2)),
        rows=(("West", Decimal("10.51")), ("East", Decimal("20.00")), (None, None)),
    )
    other_name = Table(
        columns=(StringColumn(name="area"), NumericColumn(name="revenue", scale=2)),
        rows=(("West", Decimal("10.50")), ("East", Decimal("20.00")), (None, None)),
    )
    other_scale = Table(
        columns=(StringColumn(name="region"), NumericColumn(name="revenue", scale=3)),
        rows=(("West", Decimal("10.50")), ("East", Decimal("20.00")), (None, None)),
    )
    assert len({base, *(hash_table(t) for t in (other_cell, other_name, other_scale))}) == 4


def test_hash_table_equal_for_independently_built_identical_tables() -> None:
    assert hash_table(_table()) == hash_table(_table())


# --- spec hash: deterministic re-encode, byte-faithful -----------------------
def test_hash_spec_is_sha256_prefixed_and_stable_across_reencode() -> None:
    digest = hash_spec(_spec())
    assert digest.startswith("sha256:") and len(digest) == len("sha256:") + 64
    assert hash_spec(_spec()) == digest  # a fresh decode of the same spec hashes alike


def test_hash_spec_flips_on_edit() -> None:
    assert hash_spec(_spec(mark="bar")) != hash_spec(_spec(mark="line"))


def test_spec_bytes_is_deterministic_and_backs_hash_spec() -> None:
    """spec_bytes is the public seam the service serves + hash_spec digests: byte-stable, a
    lossless round-trip, and exactly what hash_spec tags-and-hashes (non-circular restatement)."""
    encoded = spec_bytes(_spec())
    assert spec_bytes(_spec()) == encoded  # byte-stable across a fresh decode+encode
    assert decode_spec(encoded) == _spec()  # canonical bytes round-trip to an equal spec
    tag = f"vplot-spec/{canon.CANON_VERSION}\n".encode()
    assert hash_spec(_spec()) == "sha256:" + hashlib.sha256(tag + encoded).hexdigest()


def test_dataset_spec_bytes_and_hash_stay_unchanged_under_plot_union() -> None:
    expected = (
        b'{"version":"vplot-0.1","dataset":{"name":"sales.csv","hash":"sha256:'
        + b"0" * 64
        + b'"},"transform":[{"op":"filter","field":"region","cmp":"eq","value":"West"}]'
        b',"mark":"bar","encoding":{"x":{"field":"region","type":"nominal"},'
        b'"y":{"field":"revenue","type":"quantitative"},"color":null}}'
    )
    assert spec_bytes(_spec()) == expected
    assert hash_spec(_spec()) == (
        "sha256:990615ee353d3f4c534c141cf3ff993cbee0b15a9453806d9f8fd3b31c6cbe67"
    )


def test_formula_spec_flows_through_shared_spec_canonicalization() -> None:
    expected = (
        b'{"version":"vplot-formula-0.1","formula":"x**2","domain":{"start":"-3",'
        b'"stop":"3","samples":13,"x_scale":1,"y_scale":2},'
        b'"numeric_profile":"rational-half-even-v1","mark":"line","encoding":{'
        b'"x":{"field":"x","type":"quantitative"},'
        b'"y":{"field":"y","type":"quantitative"}}}'
    )
    spec = _formula_spec()
    assert spec_bytes(spec) == expected
    assert decode_formula_spec(expected) == spec
    assert hash_spec(spec) == (
        "sha256:634e8a9bdf628b0f8b0cf99ef6cb45167ec882450dff4e77a1492860d8472160"
    )


def test_hash_spec_distinguishes_nfc_variants() -> None:
    """The spec hash is byte-faithful: NFC-equivalent but byte-different filter values hash
    APART, since the evaluator compares string filters verbatim (VPlot_SEMANTICS sections 3/4)."""
    assert unicodedata.normalize("NFC", _CAFE_DECOMPOSED) == _CAFE_COMPOSED  # same NFC class
    assert hash_spec(_spec(_CAFE_COMPOSED)) != hash_spec(_spec(_CAFE_DECOMPOSED))


# --- manifest hash: domain-tagged over raw bytes -----------------------------
def test_hash_manifest_is_domain_tagged_and_flips_on_bytes() -> None:
    raw = (Path(__file__).resolve().parent.parent / "data" / "schemas" / "sales.json").read_bytes()
    tag = f"vplot-manifest/{canon.CANON_VERSION}\n".encode()
    assert hash_manifest(raw) == "sha256:" + hashlib.sha256(tag + raw).hexdigest()
    assert hash_manifest(raw) != hash_manifest(raw + b"\n")


# --- runtime versions --------------------------------------------------------
def test_runtime_versions_reports_the_running_environment() -> None:
    versions = runtime_versions()
    assert versions.canon_version == canon.CANON_VERSION
    assert versions.python == platform.python_version()
    assert versions.msgspec == msgspec.__version__
    assert versions.unidata == unicodedata.unidata_version


# --- golden hash vectors: pin the canonical bytes against any drift -----------
def test_golden_hash_vectors() -> None:
    """Fixed digests for fixed inputs. Unlike the domain-tag tests (which recompute from
    serialize_table/tags), these pin the canonical FORM itself: any change to serialize_table,
    the tags, msgspec escaping, Decimal rendering, or CANON_VERSION flips a vector — catching
    drift (msgspec / Python / locale) that the self-referential checks would pass. The last two
    carry a non-ASCII filter and cell, so a msgspec switch from raw UTF-8 to escaped non-ASCII
    would also flip a vector (finding B)."""
    assert hash_dataset(b"region,revenue\nWest,10\n") == (
        "sha256:4f8e01a5645ff7807c62c71cadc220a21a3f7641cdd48cd700cbcfb9036208b9"
    )
    assert hash_table(_table()) == (
        "sha256:d31b9cba88803946e945969c0b1d01acc8011af7af678f8fbfb80a1b193c606d"
    )
    assert hash_spec(_spec()) == (
        "sha256:990615ee353d3f4c534c141cf3ff993cbee0b15a9453806d9f8fd3b31c6cbe67"
    )
    assert hash_manifest(b"manifest-bytes") == (
        "sha256:6b9268d3f0f95dd8ce488d3bc2dce35469ea29b9674d67d5c4b9ff3cc6376ad8"
    )
    assert hash_spec(_spec(_CAFE_COMPOSED)) == (
        "sha256:e36a4396d094f0bb92d48d9a72ad8c51902953e06573baeefaff829fce85d29c"
    )
    cafe_table = Table(
        columns=(StringColumn(name="city"), NumericColumn(name="rev", scale=2)),
        rows=((_CAFE_COMPOSED, Decimal("10.50")),),
    )
    assert hash_table(cafe_table) == (
        "sha256:72bbc5136f489b7201c3903aed10feac1764f370b9869bdfe78992e75eb9d025"
    )


def test_formula_golden_hash_vectors() -> None:
    assert hash_formula(_formula_source()) == (
        "sha256:9dfeb1d5e76632ef38f20fe2a630e49ea5a3ac2ab4d9780b4fb127db8740810e"
    )
    assert hash_matplotlib_script(_FORMULA_SCRIPT) == (
        "sha256:05053f5c55599b847c3fdb3c738931372706cdc33f08ebf6cd337c7713fe8533"
    )


# --- cross-process determinism (PYTHONHASHSEED) ------------------------------
_DETERMINISM_PROG = """
from decimal import Decimal
import msgspec
from verifier import canon
from verifier.schema import decode_spec

spec = decode_spec(
    msgspec.json.encode(
        {
            "version": "vplot-0.1",
            "dataset": {"name": "sales.csv", "hash": "sha256:" + "0" * 64},
            "transform": [
                {"op": "filter", "field": "region", "cmp": "eq", "value": "caf" + chr(0x00E9)}
            ],
            "mark": "line",
            "encoding": {
                "x": {"field": "a", "type": "temporal"},
                "y": {"field": "b", "type": "quantitative"},
            },
        }
    )
)
table = canon.Table(
    columns=(canon.StringColumn(name="r"), canon.NumericColumn(name="v", scale=2)),
    rows=(("West", Decimal("10.50")), (None, None)),
)
formula = canon.FormulaSource(
    grammar_version="vplot-expr-0.1",
    numeric_profile="rational-half-even-v1",
    rounding="ROUND_HALF_EVEN",
    ast="(+ (** x 2) 1)",
    start=Decimal("-1.25"),
    stop=Decimal("2.50"),
    samples=16,
    x_scale=2,
    y_scale=3,
)
print(canon.hash_dataset(b"region,rev,West,10.50"))
print(canon.hash_table(table))
print(canon.hash_spec(spec))
print(canon.hash_manifest(b"manifest-bytes"))
print(canon.hash_formula(formula))
print(canon.hash_matplotlib_script(b"matplotlib-script-bytes\\n"))
"""


def _hashes_under_seed(seed: str) -> str:
    result = subprocess.run(  # noqa: S603 — fixed interpreter + constant program
        [sys.executable, "-c", _DETERMINISM_PROG],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )
    return result.stdout


def test_all_six_hashes_are_stable_across_pythonhashseed() -> None:
    out = _hashes_under_seed("0")
    assert out == _hashes_under_seed("1")
    assert out.count("sha256:") == 6  # dataset, table, spec, manifest, formula, script
