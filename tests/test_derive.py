# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q3: the vplot-0.2 `derive` transform -- decode, recompute, checks, labels and certificate.

Contract `.agent/archive/contracts/q3.md`. Expected tables are hand-computed literals; the DuckDB
differential over a derive corpus lives in tests/test_oracle_parity.py.
"""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import msgspec
import pytest

from verifier import attestation, canon, checks, ingest, render, vcert
from verifier.errors import VerificationError
from verifier.eval import evaluate, evaluate_run
from verifier.expr import Abs, Binary, Neg, Number, Pow, Variable, variables
from verifier.limits import DEFAULT_LIMITS
from verifier.schema import Derive, VPlotSpec, VPlotSpecV02, decode_spec
from verifier.service import pipeline
from verifier.service import replay as service_replay
from verifier.service.archive import (
    AttemptArtifacts,
    AttemptDraft,
    AttemptOutcome,
    AttemptRoute,
    materialize_plot_bundle,
    open_archive,
)
from verifier.service.identity import load_identity
from verifier.service.settings import Settings

_MANIFEST: dict[str, Any] = {
    "dataset": "d.csv",
    "columns": [
        {"name": "site", "type": "string", "label": "Site"},
        {"name": "revenue", "type": "numeric", "scale": 2, "unit": "USD", "label": "Revenue"},
        {"name": "orders", "type": "numeric", "scale": 0, "unit": "orders", "label": "Orders"},
    ],
}
_MANIFEST_BYTES = msgspec.json.encode(_MANIFEST)
# west 10.00/3 = 3.333.. -> 3.33; east 7.50/2 = 3.75; south 1.00/8 = 0.125 -> 0.12 under
# HALF_EVEN (HALF_UP would give 0.13); north's revenue is NULL.
_CSV = b"site,revenue,orders\nwest,10.00,3\neast,7.50,2\nsouth,1.00,8\nnorth,,4\n"
_DERIVE: dict[str, object] = {"op": "derive", "expr": "revenue / orders", "as": "ratio", "scale": 2}


def _raw(
    transform: list[dict[str, object]],
    *,
    version: str = "vplot-0.2",
    y: str = "ratio",
    content: bytes = _CSV,
) -> bytes:
    return msgspec.json.encode(
        {
            "version": version,
            "dataset": {"name": "d.csv", "hash": canon.hash_dataset(content)},
            "transform": transform,
            "mark": "bar",
            "encoding": {
                "x": {"field": "site", "type": "nominal"},
                "y": {"field": y, "type": "quantitative"},
            },
        }
    )


def _table(transform: list[dict[str, object]], content: bytes = _CSV) -> canon.Table:
    spec = decode_spec(_raw(transform, content=content))
    return evaluate(spec, ingest.load_manifest(_MANIFEST_BYTES), content)


def _failure(transform: list[dict[str, object]], content: bytes = _CSV) -> str:
    with pytest.raises(VerificationError) as caught:
        _table(transform, content)
    return caught.value.check


def _run(
    tmp_path: Path, transform: list[dict[str, object]], y: str = "ratio"
) -> checks.VerificationRun:
    (tmp_path / "d.csv").write_bytes(_CSV)
    spec = decode_spec(_raw(transform, y=y))
    return checks.verify_run(spec, _MANIFEST_BYTES, data_dir=tmp_path)


# --- decode -------------------------------------------------------------------------------
def test_q3_a_v02_spec_decodes_its_derive() -> None:
    spec = decode_spec(_raw([_DERIVE]))
    assert isinstance(spec, VPlotSpecV02)
    assert spec.transform == (Derive(expr="revenue / orders", output="ratio", scale=2),)


def test_q3_a_v01_spec_cannot_carry_a_derive() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(_raw([_DERIVE], version="vplot-0.1"))
    assert isinstance(decode_spec(_raw([], version="vplot-0.1", y="revenue")), VPlotSpec)


@pytest.mark.parametrize(
    "bad",
    [
        _DERIVE | {"scale": 13},
        _DERIVE | {"scale": -1},
        _DERIVE | {"as": "1ratio"},
        _DERIVE | {"expr": "revenue; orders"},
        {key: value for key, value in _DERIVE.items() if key != "scale"},
    ],
    ids=["scale-13", "scale-negative", "bad-name", "bad-expr-char", "no-scale"],
)
def test_q3_derive_shape_is_closed(bad: dict[str, object]) -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(_raw([bad]))


@pytest.mark.parametrize("member", ["version", "elsewhere"])
def test_q3_a_deeply_nested_body_keeps_its_decode_error(member: str) -> None:
    """Closing review S17: the version probe recursed through 10,000 nested arrays and escaped as
    RecursionError, where vplot-0.1's strict decode refuses at once."""
    nested = b"[" * 10_000 + b"0" + b"]" * 10_000
    with pytest.raises((msgspec.ValidationError, msgspec.DecodeError)):
        decode_spec(b'{"' + member.encode() + b'":' + nested + b"}")


def test_q3_an_unknown_version_still_refuses_at_decode() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode_spec(_raw([], version="vplot-0.3", y="revenue"))


# --- recomputation --------------------------------------------------------------------------
def test_q3_derive_appends_one_exact_half_even_column_with_null_in_null_out() -> None:
    table = _table([_DERIVE])
    assert table.columns[-1] == canon.NumericColumn(name="ratio", scale=2)
    ratios = {row[0]: row[-1] for row in table.rows}
    assert ratios == {
        "west": Decimal("3.33"),
        "east": Decimal("3.75"),
        "south": Decimal("0.12"),
        "north": None,
    }


def test_q3_a_failing_row_refuses_the_whole_plot() -> None:
    zero = _CSV.replace(b"east,7.50,2", b"east,7.50,0")
    assert _failure([_DERIVE], zero) == "derive.values_defined"


def test_q3_an_out_of_domain_value_refuses() -> None:
    huge = _DERIVE | {"expr": "revenue * 10 ** 30", "scale": 12}
    assert _failure([huge]) == "derive.values_bounded"


@pytest.mark.parametrize("expr", ["site / orders", "missing + 1", "revenue +", "abs"], ids=str)
def test_q3_an_expression_outside_the_numeric_columns_refuses(expr: str) -> None:
    assert _failure([_DERIVE | {"expr": expr}]) == "derive.expr_valid"


def test_q3_a_derive_without_any_numeric_column_refuses() -> None:
    assert _failure([{"op": "select", "fields": ["site"]}, _DERIVE | {"expr": "1 + 1"}]) == (
        "derive.expr_valid"
    )


@pytest.mark.parametrize("name", ["abs", "a" * 33], ids=["function-name", "over-32-bytes"])
def test_q3_a_numeric_column_the_engine_cannot_bind_is_no_variable(name: str) -> None:
    """A name reserved as a function, or past the engine's identifier ceiling, would be a caller
    error inside the expr engine; it stays out of the variables, so the derive refuses cleanly."""
    manifest = msgspec.json.encode(
        {
            "dataset": "d.csv",
            "columns": [
                {"name": "site", "type": "string", "label": "Site"},
                {"name": name, "type": "numeric", "scale": 0, "unit": "u", "label": "N"},
            ],
        }
    )
    content = f"site,{name}\nwest,1\n".encode()
    spec = decode_spec(_raw([_DERIVE | {"expr": "1 + 1"}], content=content))
    with pytest.raises(VerificationError) as caught:
        evaluate(spec, ingest.load_manifest(manifest), content)
    assert caught.value.check == "derive.expr_valid"


def test_q3_the_output_must_be_a_new_column() -> None:
    assert _failure([_DERIVE | {"as": "orders"}]) == "derive.output_unique"


def test_q3_a_derive_between_group_by_and_aggregate_refuses() -> None:
    transform: list[dict[str, object]] = [
        {"op": "group_by", "keys": ["site"]},
        _DERIVE,
        {"op": "aggregate", "measures": [{"field": "ratio", "fn": "sum", "as": "total"}]},
    ]
    assert _failure(transform) == "transform.group_by_placement"


def test_q3_later_transforms_see_the_derived_column() -> None:
    table = _table(
        [
            _DERIVE,
            {"op": "filter", "field": "ratio", "cmp": "gt", "value": "1"},
            {"op": "select", "fields": ["site", "ratio"]},
        ]
    )
    assert table.rows == (("east", Decimal("3.75")), ("west", Decimal("3.33")))


def test_q3_a_derive_after_an_aggregate_reads_the_aggregated_columns() -> None:
    table = _table(
        [
            {
                "op": "aggregate",
                "measures": [
                    {"field": "revenue", "fn": "sum", "as": "total"},
                    {"field": "orders", "fn": "sum", "as": "count_sum"},
                ],
            },
            {"op": "derive", "expr": "total / count_sum", "as": "ratio", "scale": 3},
        ]
    )
    assert table.rows == ((Decimal("18.50"), Decimal(17), Decimal("1.088")),)


def test_q3_the_derive_charges_rows_times_nodes_before_it_runs() -> None:
    """P6: rows x (AST nodes + 1) -- 4 x (3 + 1) = 16 -- before the derive runs; the closure then
    charges 4 rows x 2 x 4 columns = 32. An empty table charges nothing for either."""
    manifest = ingest.load_manifest(_MANIFEST_BYTES)
    spec = decode_spec(_raw([_DERIVE]))
    assert evaluate_run(spec, manifest, _CSV).work_units == 48
    tight = msgspec.structs.replace(DEFAULT_LIMITS, max_eval_work_units=15)
    with pytest.raises(VerificationError) as caught:
        evaluate(spec, manifest, _CSV, limits=tight)
    assert caught.value.check == "resource.eval_work"
    assert "before derive: 0 consumed + 16 required" in str(caught.value)
    empty = b"site,revenue,orders\n"
    minimal = msgspec.structs.replace(DEFAULT_LIMITS, max_eval_work_units=1)
    run = evaluate_run(decode_spec(_raw([_DERIVE], content=empty)), manifest, empty, limits=minimal)
    assert run.work_units == 0


# --- checks, labels, certificate -------------------------------------------------------------
def test_q3_a_derived_quantitative_axis_is_unit_exempt_and_titled_derived_value(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, [_DERIVE])
    assert run.report.passed, [r for r in run.report.results if r.status == "fail"]
    spec = decode_spec(_raw([_DERIVE]))
    assert run.evidence is not None
    built = render.build_vega_lite(
        spec, run.evidence.plotted_table, ingest.load_manifest(_MANIFEST_BYTES)
    )
    assert built["encoding"]["y"]["title"] == "Derived value"
    assert built["encoding"]["x"]["title"] == "Site"


def test_q3_unit_lineage_runs_through_a_derive_into_an_aggregate() -> None:
    derive = Derive(expr="revenue / orders", output="ratio", scale=2)
    assert checks.unit_source("ratio", (derive,)) == checks.DERIVED_SOURCE
    assert checks.unit_source("revenue", (derive,)) == "revenue"


def test_q3_a_v02_report_discloses_its_derive_checks_and_its_expression_path(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, [_DERIVE])
    by_id = {result.check: result for result in run.report.results}
    for check in (
        "derive.expr_valid",
        "derive.output_unique",
        "derive.values_defined",
        "derive.values_bounded",
    ):
        assert by_id[check].status == "pass"
    assert "expr-0.1 interpreter" in by_id["security.no_arbitrary_code"].message
    assert "/derive" in by_id["transform.ops_allowed"].message
    assert by_id["label.quantitative_units_present"].message == (
        "every quantitative channel resolves to a unit, a count, or a derive"
    )


def test_q3_a_v01_report_carries_no_derive_check(tmp_path: Path) -> None:
    (tmp_path / "d.csv").write_bytes(_CSV)
    spec = decode_spec(_raw([], version="vplot-0.1", y="revenue"))
    run = checks.verify_run(spec, _MANIFEST_BYTES, data_dir=tmp_path)
    assert not [r for r in run.report.results if r.check.startswith("derive.")]
    messages = {r.check: r.message for r in run.report.results}
    assert messages["security.no_arbitrary_code"] == (
        "spec is pure data (frozen msgspec structs, no expr/script/url field), "
        "so it carries no executable path"
    )
    assert messages["label.quantitative_units_present"] == (
        "every quantitative channel resolves to a unit or a count"
    )


def test_q3_the_certificate_discloses_each_derive_and_v01_bytes_omit_the_field() -> None:
    spec = decode_spec(_raw([_DERIVE, _DERIVE | {"as": "twice", "expr": "ratio * 2"}]))
    assert vcert.disclosed_derives(spec) == (
        vcert.DisclosedDerive(output="ratio", expr="revenue / orders", scale=2),
        vcert.DisclosedDerive(output="twice", expr="ratio * 2", scale=2),
    )
    tcb = vcert.dataset_tcb()
    fields: dict[str, Any] = {
        "version": "vcert-0.2",
        "dataset_hash": "a",
        "spec_hash": "b",
        "plotted_table_hash": "c",
        "manifest_hash": "d",
        "vega_lite_hash": "e",
        "checks": (),
        "filters": (),
        "sorts": (),
        "tcb": tcb,
    }
    plain = vcert.vcert_bytes(vcert.VCert(**fields))
    assert b"derives" not in plain
    disclosed = vcert.vcert_bytes(vcert.VCert(**fields, derives=vcert.disclosed_derives(spec)))
    payload = json.loads(disclosed)
    assert payload["derives"] == [
        {"output": "ratio", "expr": "revenue / orders", "scale": 2},
        {"output": "twice", "expr": "ratio * 2", "scale": 2},
    ]
    assert vcert.decode_vcert(disclosed).derives == vcert.disclosed_derives(spec)
    assert vcert.vcert_bytes(vcert.decode_vcert(plain)) == plain


def test_q3_the_proposer_schema_pin_stays_v01() -> None:
    """Verifier-only first: the proposer's guided-JSON pin names no derive and no v0.2."""
    pinned = (Path(__file__).resolve().parents[1] / "schema/vplot-0.1.schema.json").read_bytes()
    assert b"derive" not in pinned
    assert b"vplot-0.2" not in pinned
    assert hashlib.sha256(pinned).hexdigest() == (
        "2bab7c6ef3f749ba6cc975781e03f41d463707c6db451ef6acc864801edc9177"
    )


def test_q3_expr_variables_reads_every_name_once() -> None:
    inner = Binary(op="mul", left=Variable(name="b"), right=Variable(name="a"))
    node = Binary(op="add", left=Variable(name="a"), right=inner)
    assert variables(node) == frozenset({"a", "b"})
    assert variables(Number(value=Fraction(1))) == frozenset()
    assert variables(Neg(operand=Abs(operand=Variable(name="c")))) == frozenset({"c"})
    assert variables(Pow(base=Variable(name="d"), exponent=2)) == frozenset({"d"})


# --- P7: archive + replay round trip ------------------------------------------------------
def test_q3_a_v02_plot_archives_reads_back_and_replays_exact(tmp_path: Path) -> None:
    """The verified v0.2 plot's canonical spec decodes back as v0.2 from the archive, its signed
    certificate discloses the derive, and replay reparses + recomputes it to an exact verdict."""
    root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"
    (data_dir / "schemas").mkdir(parents=True)
    shutil.copyfile(root / "data/sales.csv", data_dir / "sales.csv")
    shutil.copyfile(root / "data/schemas/sales.json", data_dir / "schemas/sales.json")
    raw = msgspec.json.encode(
        {
            "version": "vplot-0.2",
            "dataset": {
                "name": "sales.csv",
                "hash": canon.hash_dataset((root / "data/sales.csv").read_bytes()),
            },
            "transform": [
                {"op": "derive", "expr": "revenue / orders", "as": "per_order", "scale": 2},
                {"op": "group_by", "keys": ["region"]},
                {
                    "op": "aggregate",
                    "measures": [{"field": "per_order", "fn": "mean", "as": "avg"}],
                },
            ],
            "mark": "bar",
            "encoding": {
                "x": {"field": "region", "type": "nominal"},
                "y": {"field": "avg", "type": "quantitative"},
            },
        }
    )
    settings = Settings(data_dir=data_dir, state_dir=tmp_path / "state")
    identity = load_identity(settings)
    outcome = pipeline.verify_only(raw, settings)
    prepared = cast("render.PreparedArtifact", outcome.prepared)
    rendered = render.render_prepared(prepared, limits=settings.limits)
    assert rendered.certificate.derives == (
        vcert.DisclosedDerive(output="per_order", expr="revenue / orders", scale=2),
    )
    envelope = attestation.sign_vcert(
        rendered.certificate,
        identity.signer.private_key,
        keyid=identity.signer.keyid,
        limits=settings.limits,
    )
    plot = materialize_plot_bundle(
        prepared, rendered, envelope, identity.signer, limits=settings.limits
    )
    archive = open_archive(settings)
    draft = AttemptDraft(
        occurred_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        route=AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=AttemptArtifacts(
            raw_csv=plot.raw_csv, raw_manifest=plot.raw_manifest, raw_spec=raw, verdict=plot.verdict
        ),
        plot=plot,
    )
    bundle = archive.record_attempt(draft, identity.signer, limits=settings.limits)
    stored = archive.read_spec(
        canon.hash_spec(prepared.spec).removeprefix("sha256:"), max_bytes=10_000
    )
    assert isinstance(decode_spec(stored), VPlotSpecV02)
    verdict = service_replay.replay_plot(
        archive,
        {identity.signer.keyid: identity.signer.public_key},
        plot.plot_id,
        max_bytes=10_000_000,
        limits=settings.limits,
    )
    assert verdict.status == "exact"
    assert verdict.exact
    assert bundle.plot is not None
