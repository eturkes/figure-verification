# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""VCert schemas and builders: fixed-TCB canonical vectors, live provenance wiring, v0.2 compat.

Canonical FORM and provenance WIRING are decided separately. Every byte-pinned vector builds under
the injected fixed TCB from ``vector_tcb``, so it stays reproducible on any interpreter the
``>=3.13,<3.14`` floor admits; the tests that pin each collected field to its live source load no
vector, so a mis-sourced field cannot hide behind a co-derived one.
"""

import hashlib
import importlib.metadata
import itertools
import os
import platform
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext
from pathlib import Path
from typing import Any, NoReturn, cast, get_args

import msgspec
import pytest

from vector_tcb import DATASET_TCB, FORMULA_TCB
from verifier import (
    __version__,
    canon,
    checks,
    expr,
    formal,
    formula_prepare,
    matplotlib_script,
    render,
    vcert,
)
from verifier.schema import NumericProfile, VPlotSpec, decode_formula_spec, decode_spec

_ROOT = Path(__file__).resolve().parent.parent
_FORMULA_GOOD = _ROOT / "examples" / "formula_good_specs"
_DATASET_GOOD = _ROOT / "examples" / "good_specs"
_DATA = _ROOT / "data"
_SCHEMAS = _DATA / "schemas"
_VECTOR_PATH = Path(__file__).with_name("vcert_v03_vectors.json")
_VECTORS = cast(
    "dict[str, dict[str, int | str]]",
    msgspec.json.decode(_VECTOR_PATH.read_bytes()),
)
_FORMULA_VECTORS = {name: _VECTORS[name] for name in ("f02_linear.json", "f06_quadratic.json")}
_FIXED_V03_VECTOR_NAMES = ("synthetic_formula_v03", "synthetic_dataset_v03")

_VCERT_STRUCTS: tuple[type[msgspec.Struct], ...] = (
    vcert.Tcb,
    vcert.DatasetTcb,
    vcert.FormulaTcb,
    vcert.DisclosedFilter,
    vcert.DisclosedSort,
    vcert.CertifiedCheck,
    vcert.VCert,
    vcert.DatasetSourceCert,
    vcert.FormulaSourceCert,
    vcert.VegaArtifactCert,
    vcert.MatplotlibScriptArtifactCert,
    vcert.VCertV03,
)

_DETERMINISM_PROGRAM = r"""
import hashlib
import sys
from decimal import ROUND_UP, Inexact, Rounded, getcontext
from pathlib import Path
from verifier import checks, formula_prepare, matplotlib_script, vcert
from verifier.schema import decode_formula_spec

sys.path.insert(0, str(Path.cwd() / "tests"))
from vector_tcb import FORMULA_TCB

context = getcontext()
context.prec = 2
context.rounding = ROUND_UP
context.traps[Inexact] = True
context.traps[Rounded] = True
root = Path.cwd()
spec = decode_formula_spec(
    (root / "examples" / "formula_good_specs" / "f02_linear.json").read_bytes()
)
verification = checks.verify_formula_run(spec)
evidence = verification.require_evidence()
preparation = formula_prepare.prepare_formula(spec, evidence)
prepared = preparation.prepared
if prepared is None:
    raise RuntimeError("formula preparation unexpectedly failed")
emission = matplotlib_script.emit_matplotlib_script(prepared)
artifact = emission.artifact
if artifact is None:
    raise RuntimeError("matplotlib-script emission unexpectedly failed")
payload = vcert.vcert_v03_bytes(vcert.build_formula_certificate(artifact, tcb=FORMULA_TCB))
print(payload.hex())
print(hashlib.sha256(payload).hexdigest())
"""


def _artifact(name: str) -> matplotlib_script.MatplotlibScriptArtifact:
    spec = decode_formula_spec((_FORMULA_GOOD / name).read_bytes())
    verification = checks.verify_formula_run(spec)
    evidence = verification.require_evidence()
    preparation = formula_prepare.prepare_formula(spec, evidence)
    assert preparation.report.passed
    prepared = cast("formula_prepare.PreparedFormula", preparation.prepared)
    emission = matplotlib_script.emit_matplotlib_script(prepared)
    assert emission.report.passed
    return cast("matplotlib_script.MatplotlibScriptArtifact", emission.artifact)


def _dataset_spec_and_evidence() -> tuple[VPlotSpec, checks.DatasetEvidence]:
    spec = decode_spec((_DATASET_GOOD / "g01_total_revenue_by_month.json").read_bytes())
    manifest = (_SCHEMAS / f"{Path(spec.dataset.name).stem}.json").read_bytes()
    return spec, checks.verify_run(spec, manifest, data_dir=_DATA).require_evidence()


def _wire(payload: bytes) -> dict[str, Any]:
    return cast("dict[str, Any]", msgspec.json.decode(payload))


def _payload(artifact: matplotlib_script.MatplotlibScriptArtifact) -> bytes:
    """Canonical bytes under the fixed vector TCB, i.e. the interpreter-portable form."""
    return vcert.vcert_v03_bytes(vcert.build_formula_certificate(artifact, tcb=FORMULA_TCB))


def _different_hash(value: str) -> str:
    replacement = "0" if value[-1] != "0" else "1"
    return value[:-1] + replacement


def _dataset_source() -> vcert.DatasetSourceCert:
    return vcert.DatasetSourceCert(
        dataset_hash="sha256:" + "0" * 64,
        manifest_hash="sha256:" + "3" * 64,
        filters=(vcert.DisclosedFilter(field="region", cmp="eq", value="West"),),
        sorts=(vcert.DisclosedSort(field="month", order="ascending"),),
    )


def _dataset_v03_tcb() -> vcert.DatasetTcb:
    current = vcert.dataset_tcb()
    return vcert.DatasetTcb(
        verifier_version=current.verifier_version,
        z3_version=current.z3_version,
        canon_version=current.canon_version,
        python=current.python,
        msgspec=current.msgspec,
        unidata=current.unidata,
        vl_convert_python=current.vl_convert_python,
        vl_version=current.vl_version,
        font_family=current.font_family,
        vendored_font_sha256=current.vendored_font_sha256,
    )


def _v03(
    source: vcert.DatasetSourceCert | vcert.FormulaSourceCert,
    artifact: vcert.VegaArtifactCert | vcert.MatplotlibScriptArtifactCert,
    tcb: vcert.DatasetTcb | vcert.FormulaTcb,
) -> vcert.VCertV03:
    return vcert.VCertV03(
        version="vcert-0.3",
        source=source,
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        artifact=artifact,
        checks=(),
        tcb=tcb,
    )


def _dataset_v03_certificate() -> vcert.VCertV03:
    return _v03(
        _dataset_source(),
        vcert.VegaArtifactCert(vega_lite_hash="sha256:" + "4" * 64),
        _dataset_v03_tcb(),
    )


def _fixed_formula_v03_certificate() -> vcert.VCertV03:
    return vcert.VCertV03(
        version="vcert-0.3",
        source=vcert.FormulaSourceCert(formula_hash="sha256:" + "0" * 64),
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        artifact=vcert.MatplotlibScriptArtifactCert(matplotlib_script_hash="sha256:" + "3" * 64),
        checks=(
            vcert.CertifiedCheck(
                id="formula.source_parses",
                method="schema_validation",
                status="pass",
            ),
        ),
        tcb=vcert.FormulaTcb(
            verifier_version="fixed-verifier",
            z3_version="fixed-z3",
            canon_version="fixed-canon",
            python="fixed-python",
            msgspec="fixed-msgspec",
            unidata="fixed-unidata",
            grammar_version="fixed-grammar",
            numeric_profile="rational-half-even-v1",
            script_template_version="fixed-template",
        ),
    )


def _fixed_dataset_v03_certificate() -> vcert.VCertV03:
    return vcert.VCertV03(
        version="vcert-0.3",
        source=_dataset_source(),
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        artifact=vcert.VegaArtifactCert(vega_lite_hash="sha256:" + "4" * 64),
        checks=(
            vcert.CertifiedCheck(
                id="dataset.hash_matches_source",
                method="deterministic_recompute",
                status="pass",
            ),
        ),
        tcb=vcert.DatasetTcb(
            verifier_version="fixed-verifier",
            z3_version="fixed-z3",
            canon_version="fixed-canon",
            python="fixed-python",
            msgspec="fixed-msgspec",
            unidata="fixed-unidata",
            vl_convert_python="fixed-vl-convert",
            vl_version="5.21",
            font_family="DejaVu Sans",
            vendored_font_sha256="sha256:" + "5" * 64,
        ),
    )


def _replace_certificate_hash(  # noqa: PLR0911
    certificate: vcert.VCertV03,
    slot: str,
    value: object,
) -> vcert.VCertV03:
    digest = cast("str", value)
    if slot == "spec_hash":
        return msgspec.structs.replace(certificate, spec_hash=digest)
    if slot == "plotted_table_hash":
        return msgspec.structs.replace(certificate, plotted_table_hash=digest)
    if slot == "formula_hash":
        formula_source = cast("vcert.FormulaSourceCert", certificate.source)
        return msgspec.structs.replace(
            certificate,
            source=msgspec.structs.replace(formula_source, formula_hash=digest),
        )
    if slot == "dataset_hash":
        dataset_source = cast("vcert.DatasetSourceCert", certificate.source)
        return msgspec.structs.replace(
            certificate,
            source=msgspec.structs.replace(dataset_source, dataset_hash=digest),
        )
    if slot == "manifest_hash":
        dataset_source = cast("vcert.DatasetSourceCert", certificate.source)
        return msgspec.structs.replace(
            certificate,
            source=msgspec.structs.replace(dataset_source, manifest_hash=digest),
        )
    if slot == "matplotlib_script_hash":
        script_artifact = cast("vcert.MatplotlibScriptArtifactCert", certificate.artifact)
        return msgspec.structs.replace(
            certificate,
            artifact=msgspec.structs.replace(
                script_artifact,
                matplotlib_script_hash=digest,
            ),
        )
    if slot == "vega_lite_hash":
        vega_artifact = cast("vcert.VegaArtifactCert", certificate.artifact)
        return msgspec.structs.replace(
            certificate,
            artifact=msgspec.structs.replace(vega_artifact, vega_lite_hash=digest),
        )
    if slot == "vendored_font_sha256":
        tcb = cast("vcert.DatasetTcb", certificate.tcb)
        return msgspec.structs.replace(
            certificate,
            tcb=msgspec.structs.replace(tcb, vendored_font_sha256=digest),
        )
    message = f"unknown test hash slot: {slot}"
    raise AssertionError(message)


def _set_wire_hash(wire: dict[str, Any], slot: str, value: object) -> None:
    if slot in {"spec_hash", "plotted_table_hash"}:
        wire[slot] = value
        return
    if slot in {"formula_hash", "dataset_hash", "manifest_hash"}:
        cast("dict[str, Any]", wire["source"])[slot] = value
        return
    if slot in {"matplotlib_script_hash", "vega_lite_hash"}:
        cast("dict[str, Any]", wire["artifact"])[slot] = value
        return
    if slot == "vendored_font_sha256":
        cast("dict[str, Any]", wire["tcb"])[slot] = value
        return
    message = f"unknown test hash slot: {slot}"
    raise AssertionError(message)


def _duplicate_member(
    payload: bytes,
    key: str,
    value: object,
    duplicate_value: object,
) -> bytes:
    encoded_key = msgspec.json.encode(key)
    member = encoded_key + b":" + msgspec.json.encode(value)
    assert payload.count(member) >= 1
    duplicate = member + b"," + encoded_key + b":" + msgspec.json.encode(duplicate_value)
    return payload.replace(member, duplicate, 1)


def _assert_one_byte_changed(before: bytes, after: bytes) -> None:
    assert len(before) == len(after)
    assert sum(left != right for left, right in zip(before, after, strict=True)) == 1


@pytest.mark.parametrize(("name", "expected"), tuple(_FORMULA_VECTORS.items()))
def test_formula_certificate_real_pipeline_canonical_vector(
    name: str,
    expected: dict[str, int | str],
) -> None:
    artifact = _artifact(name)
    certificate = vcert.build_formula_certificate(artifact, tcb=FORMULA_TCB)
    payload = vcert.vcert_v03_bytes(certificate)
    expected_payload = bytes.fromhex(cast("str", expected["canonical_hex"]))
    wire = _wire(payload)
    source = cast("dict[str, Any]", wire["source"])
    artifact_wire = cast("dict[str, Any]", wire["artifact"])
    checks_wire = cast("list[dict[str, Any]]", wire["checks"])
    tcb_wire = cast("dict[str, Any]", wire["tcb"])

    assert payload == expected_payload
    assert len(payload) == cast("int", expected["length"])
    assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    assert tuple(wire) == (
        "version",
        "source",
        "spec_hash",
        "plotted_table_hash",
        "artifact",
        "checks",
        "tcb",
    )
    assert source == {"kind": "formula", "formula_hash": artifact.evidence.formula_hash}
    assert wire["spec_hash"] == artifact.evidence.spec_hash
    assert wire["plotted_table_hash"] == artifact.evidence.plotted_table_hash
    assert artifact_wire == {
        "kind": "matplotlib-script",
        "matplotlib_script_hash": artifact.matplotlib_script_hash,
    }
    assert {
        key for mapping in (wire, source, artifact_wire) for key in mapping if key.endswith("_hash")
    } == {"formula_hash", "spec_hash", "plotted_table_hash", "matplotlib_script_hash"}
    assert checks_wire == [
        {"id": result.check, "method": result.method, "status": "pass"}
        for result in artifact.results
    ]
    assert "formula.points_match_recomputation" not in {check.id for check in certificate.checks}

    assert certificate.tcb is FORMULA_TCB
    assert tcb_wire == {"kind": "formula"} | {
        field: getattr(FORMULA_TCB, field) for field in FORMULA_TCB.__struct_fields__
    }
    assert tuple(tcb_wire) == (
        "kind",
        "verifier_version",
        "z3_version",
        "canon_version",
        "python",
        "msgspec",
        "unidata",
        "grammar_version",
        "numeric_profile",
        "script_template_version",
    )
    assert {
        "vl_convert_python",
        "vl_version",
        "font_family",
        "vendored_font_sha256",
        "matplotlib",
        "pyodide",
        "browser",
        "pixels",
    }.isdisjoint(tcb_wire)
    assert vcert.decode_vcert_v03(payload) == certificate
    assert vcert.vcert_v03_bytes(vcert.decode_vcert_v03(payload)) == payload


def test_formula_tcb_fields_equal_their_live_sources() -> None:
    """Provenance WIRING, the twin of the canonical-form vector above.

    This test loads no vector, so an interpreter bump cannot move it; the vector test injects a
    fixed TCB, so a mis-sourced field cannot move that one. Each field is compared against its
    ORIGINAL source rather than against ``canon.runtime_versions()``, which is the production
    collector and would make the comparison circular.
    """
    artifact = _artifact("f02_linear.json")
    tcb = vcert.build_formula_certificate(artifact).tcb

    assert type(tcb) is vcert.FormulaTcb
    assert tcb.verifier_version == __version__
    assert tcb.z3_version == formal.solver_version()
    assert tcb.canon_version == canon.CANON_VERSION
    assert tcb.python == platform.python_version()
    assert tcb.msgspec == msgspec.__version__
    assert tcb.unidata == unicodedata.unidata_version
    assert tcb.grammar_version == expr.GRAMMAR_VERSION
    assert tcb.numeric_profile == artifact.spec.numeric_profile
    assert tcb.script_template_version == matplotlib_script.SCRIPT_TEMPLATE_VERSION
    assert set(tcb.__struct_fields__) == {
        "verifier_version",
        "z3_version",
        "canon_version",
        "python",
        "msgspec",
        "unidata",
        "grammar_version",
        "numeric_profile",
        "script_template_version",
    }


def test_dataset_tcb_fields_equal_their_live_sources() -> None:
    """The v0.2 twin of the formula wiring test, on the same non-circular terms."""
    tcb = vcert.dataset_tcb()

    assert type(tcb) is vcert.Tcb
    assert tcb.verifier_version == __version__
    assert tcb.z3_version == formal.solver_version()
    assert tcb.canon_version == canon.CANON_VERSION
    assert tcb.python == platform.python_version()
    assert tcb.msgspec == msgspec.__version__
    assert tcb.unidata == unicodedata.unidata_version
    assert tcb.vl_convert_python == importlib.metadata.version("vl-convert-python")
    assert tcb.vl_version == "5.21"
    assert tcb.font_family == "DejaVu Sans"
    font = _ROOT / "src" / "verifier" / "assets" / "fonts" / "DejaVuSans.ttf"
    assert tcb.vendored_font_sha256 == "sha256:" + hashlib.sha256(font.read_bytes()).hexdigest()
    assert set(tcb.__struct_fields__) == {
        "verifier_version",
        "z3_version",
        "canon_version",
        "python",
        "msgspec",
        "unidata",
        "vl_convert_python",
        "vl_version",
        "font_family",
        "vendored_font_sha256",
    }


def test_formula_tcb_forwards_each_source_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wiring's second half: equal-to-live cannot separate a right source from a same-valued one.

    Driving every seam to a DISTINCT sentinel decides which source each field actually reads, which
    a live-value comparison cannot: a hardcoded constant and a mis-sourced field that happens to
    agree both survive it.
    """
    versions = canon.Versions(
        canon_version="seam-canon",
        python="seam-python",
        msgspec="seam-msgspec",
        unidata="seam-unidata",
    )
    monkeypatch.setattr(vcert, "__version__", "seam-verifier")
    monkeypatch.setattr(canon, "runtime_versions", lambda: versions)
    monkeypatch.setattr(formal, "solver_version", lambda: "seam-z3")
    monkeypatch.setattr(expr, "GRAMMAR_VERSION", "seam-grammar")
    monkeypatch.setattr(matplotlib_script, "SCRIPT_TEMPLATE_VERSION", "seam-script-template")
    tcb = vcert._formula_tcb("rational-half-even-v1")

    assert tcb == vcert.FormulaTcb(
        verifier_version="seam-verifier",
        z3_version="seam-z3",
        canon_version="seam-canon",
        python="seam-python",
        msgspec="seam-msgspec",
        unidata="seam-unidata",
        grammar_version="seam-grammar",
        numeric_profile="rational-half-even-v1",
        script_template_version="seam-script-template",
    )


def test_dataset_tcb_forwards_each_source_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """The v0.2 twin. ``verifier_version`` is passed rather than patched: it is a parameter default
    bound at definition, so the module attribute no longer reaches it."""
    versions = canon.Versions(
        canon_version="seam-canon",
        python="seam-python",
        msgspec="seam-msgspec",
        unidata="seam-unidata",
    )
    font = "sha256:" + "7" * 64
    monkeypatch.setattr(canon, "runtime_versions", lambda: versions)
    monkeypatch.setattr(formal, "solver_version", lambda: "seam-z3")
    monkeypatch.setattr(importlib.metadata, "version", lambda name: f"seam-{name}")
    monkeypatch.setattr(vcert, "_VL_VERSION", "seam-vl")
    monkeypatch.setattr(vcert, "_FONT_FAMILY", "seam-font-family")
    monkeypatch.setattr(vcert, "_font_sha256", lambda: font)
    tcb = vcert.dataset_tcb(verifier_version="seam-verifier")

    assert tcb == vcert.Tcb(
        verifier_version="seam-verifier",
        z3_version="seam-z3",
        canon_version="seam-canon",
        python="seam-python",
        msgspec="seam-msgspec",
        unidata="seam-unidata",
        vl_convert_python="seam-vl-convert-python",
        vl_version="seam-vl",
        font_family="seam-font-family",
        vendored_font_sha256=font,
    )


def test_injected_tcb_skips_live_collection_entirely() -> None:
    """Identity alone permits an eager collect-then-discard; a bomb decides the side effect.

    The un-injected call is asserted to detonate as the positive control, so the pin cannot pass
    vacuously against a builder that stopped collecting at all.
    """

    def _bomb(*args: object, **kwargs: object) -> NoReturn:
        message = f"live collection ran despite an injected TCB: {args} {kwargs}"
        raise AssertionError(message)

    artifact = _artifact("f02_linear.json")
    spec, evidence = _dataset_spec_and_evidence()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(vcert, "_formula_tcb", _bomb)
        assert vcert.build_formula_certificate(artifact, tcb=FORMULA_TCB).tcb is FORMULA_TCB
        with pytest.raises(AssertionError, match=r"live collection ran"):
            vcert.build_formula_certificate(artifact)

        patch.setattr(vcert, "dataset_tcb", _bomb)
        certificate = vcert.build_dataset_certificate(spec, evidence, (), b"{}", tcb=DATASET_TCB)
        assert certificate.tcb is DATASET_TCB
        with pytest.raises(AssertionError, match=r"live collection ran"):
            vcert.build_dataset_certificate(spec, evidence, (), b"{}")


def test_formula_builder_threads_its_injected_tcb() -> None:
    """Threading pin with a DISAGREEMENT witness; a sibling builder's pin is not this one's."""
    artifact = _artifact("f02_linear.json")
    live = vcert.build_formula_certificate(artifact).tcb
    injected = vcert.build_formula_certificate(artifact, tcb=FORMULA_TCB).tcb

    assert injected is FORMULA_TCB
    assert type(live) is vcert.FormulaTcb
    # numeric_profile is excluded: FormulaTcb admits exactly one value, so it cannot disagree.
    differing = {
        field
        for field in FORMULA_TCB.__struct_fields__
        if getattr(FORMULA_TCB, field) != getattr(live, field)
    }
    assert differing == set(FORMULA_TCB.__struct_fields__) - {"numeric_profile"}


def test_dataset_builder_refuses_a_wrong_family_or_subclass_tcb() -> None:
    """v0.2 has no ``__post_init__`` and ``vcert_bytes`` is a raw encoder, so the builder guards.

    Without it a ``FormulaTcb`` encodes ``"kind":"formula"`` into a ``vcert-0.2`` payload and a
    ``Tcb`` subclass encodes its own tag -- the silent dataset-identity drift ``DatasetTcb``
    deliberately avoids by not being a ``Tcb`` subclass.
    """

    class _TcbSubclass(vcert.Tcb, frozen=True, kw_only=True):
        pass

    subclass = _TcbSubclass(
        **{field: getattr(DATASET_TCB, field) for field in DATASET_TCB.__struct_fields__}
    )
    spec = decode_spec((_DATASET_GOOD / "g01_total_revenue_by_month.json").read_bytes())
    # DatasetTcb is the likeliest mistake by name alone: it is v0.3's dataset TCB, not v0.2's.
    for wrong in (FORMULA_TCB, _dataset_v03_tcb(), subclass, object()):
        with pytest.raises(msgspec.ValidationError, match=r"expected exact Tcb at tcb"):
            vcert.build_dataset_certificate(
                spec,
                cast("checks.DatasetEvidence", None),
                (),
                b"{}",
                tcb=cast("vcert.Tcb", wrong),
            )


def test_formula_numeric_profile_stays_single_valued() -> None:
    """Scope guard: the day a second profile lands, an injected TCB can disagree with its spec.

    ``build_formula_certificate`` carries no profile-correlation guard precisely because that
    disagreement is unconstructible today. This test fails at exactly the moment that stops being
    true, forcing the decision then instead of shipping an unreachable branch now.
    """
    assert get_args(NumericProfile) == ("rational-half-even-v1",)


def test_encode_seam_refuses_a_forged_numeric_profile() -> None:
    """The refusal that makes the missing builder guard a duplicate rather than a gap."""
    artifact = _artifact("f02_linear.json")
    forged = msgspec.structs.replace(FORMULA_TCB)
    msgspec.structs.force_setattr(forged, "numeric_profile", "bogus")
    certificate = vcert.build_formula_certificate(artifact, tcb=forged)

    with pytest.raises(msgspec.ValidationError, match=r"\$\.tcb\.numeric_profile"):
        vcert.vcert_v03_bytes(certificate)


@pytest.mark.parametrize("name", _FIXED_V03_VECTOR_NAMES)
def test_hand_authored_v03_payload_vectors(name: str) -> None:
    expected = _VECTORS[name]
    payload = bytes.fromhex(cast("str", expected["canonical_hex"]))
    certificates = {
        "synthetic_formula_v03": _fixed_formula_v03_certificate(),
        "synthetic_dataset_v03": _fixed_dataset_v03_certificate(),
    }
    certificate = certificates[name]

    assert len(payload) == expected["length"]
    assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    assert vcert.vcert_v03_bytes(certificate) == payload
    assert vcert.decode_vcert_v03(payload) == certificate


def test_v03_synthetic_formula_wire_vector_is_independently_fixed() -> None:
    certificate = vcert.VCertV03(
        version="vcert-0.3",
        source=vcert.FormulaSourceCert(formula_hash="sha256:" + "a" * 64),
        spec_hash="sha256:" + "b" * 64,
        plotted_table_hash="sha256:" + "c" * 64,
        artifact=vcert.MatplotlibScriptArtifactCert(matplotlib_script_hash="sha256:" + "d" * 64),
        checks=(
            vcert.CertifiedCheck(id="check.construct", method="construction", status="pass"),
            vcert.CertifiedCheck(
                id="check.recompute", method="deterministic_recompute", status="pass"
            ),
            vcert.CertifiedCheck(id="check.solver", method="z3_smt", status="pass"),
        ),
        tcb=vcert.FormulaTcb(
            verifier_version="v",
            z3_version="z",
            canon_version="c",
            python="p",
            msgspec="m",
            unidata="u",
            grammar_version="g",
            numeric_profile="rational-half-even-v1",
            script_template_version="s",
        ),
    )
    expected = (
        b'{"version":"vcert-0.3","source":{"kind":"formula","formula_hash":"sha256:'
        b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},'
        b'"spec_hash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        b'"plotted_table_hash":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",'
        b'"artifact":{"kind":"matplotlib-script","matplotlib_script_hash":"sha256:'
        b'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},'
        b'"checks":[{"id":"check.construct","method":"construction","status":"pass"},'
        b'{"id":"check.recompute","method":"deterministic_recompute","status":"pass"},'
        b'{"id":"check.solver","method":"z3_smt","status":"pass"}],'
        b'"tcb":{"kind":"formula","verifier_version":"v","z3_version":"z",'
        b'"canon_version":"c","python":"p","msgspec":"m","unidata":"u",'
        b'"grammar_version":"g","numeric_profile":"rational-half-even-v1",'
        b'"script_template_version":"s"}}'
    )

    payload = vcert.vcert_v03_bytes(certificate)
    assert payload == expected
    assert len(payload) == 888
    assert hashlib.sha256(payload).hexdigest() == (
        "3f55c78aeb4bada6843e4a32eefc31ca882927081fa199c528998b0de7fbb71f"
    )
    assert vcert.decode_vcert_v03(payload) == certificate


def test_v03_synthetic_dataset_wire_vector_is_independently_fixed() -> None:
    certificate = vcert.VCertV03(
        version="vcert-0.3",
        source=vcert.DatasetSourceCert(
            dataset_hash="sha256:" + "0" * 64,
            manifest_hash="sha256:" + "3" * 64,
            filters=(vcert.DisclosedFilter(field="region", cmp="eq", value="West"),),
            sorts=(vcert.DisclosedSort(field="month", order="ascending"),),
        ),
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        artifact=vcert.VegaArtifactCert(vega_lite_hash="sha256:" + "4" * 64),
        checks=(
            vcert.CertifiedCheck(
                id="dataset.hash_matches_source",
                method="deterministic_recompute",
                status="pass",
            ),
        ),
        tcb=vcert.DatasetTcb(
            verifier_version="v",
            z3_version="z",
            canon_version="c",
            python="p",
            msgspec="m",
            unidata="u",
            vl_convert_python="vlc",
            vl_version="vl",
            font_family="Font",
            vendored_font_sha256="sha256:" + "5" * 64,
        ),
    )
    expected = (
        b'{"version":"vcert-0.3","source":{"kind":"dataset","dataset_hash":"sha256:'
        b'0000000000000000000000000000000000000000000000000000000000000000",'
        b'"manifest_hash":"sha256:3333333333333333333333333333333333333333333333333333333333333333",'
        b'"filters":[{"field":"region","cmp":"eq","value":"West"}],'
        b'"sorts":[{"field":"month","order":"ascending"}]},'
        b'"spec_hash":"sha256:1111111111111111111111111111111111111111111111111111111111111111",'
        b'"plotted_table_hash":"sha256:2222222222222222222222222222222222222222222222222222222222222222",'
        b'"artifact":{"kind":"vega-lite","vega_lite_hash":"sha256:'
        b'4444444444444444444444444444444444444444444444444444444444444444"},'
        b'"checks":[{"id":"dataset.hash_matches_source",'
        b'"method":"deterministic_recompute","status":"pass"}],'
        b'"tcb":{"kind":"dataset","verifier_version":"v","z3_version":"z",'
        b'"canon_version":"c","python":"p","msgspec":"m","unidata":"u",'
        b'"vl_convert_python":"vlc","vl_version":"vl","font_family":"Font",'
        b'"vendored_font_sha256":"sha256:'
        b'5555555555555555555555555555555555555555555555555555555555555555"}}'
    )

    payload = vcert.vcert_v03_bytes(certificate)
    assert payload == expected
    assert len(payload) == 1026
    assert hashlib.sha256(payload).hexdigest() == (
        "bcb8bcc5fb4a9d1ccdd737b0c726650f3138c07b19e722744b28404969d244ac"
    )
    assert vcert.decode_vcert_v03(payload) == certificate


def test_v03_source_artifact_tcb_full_correlation_matrix() -> None:
    formula_certificate = vcert.build_formula_certificate(_artifact("f02_linear.json"))
    assert isinstance(formula_certificate.source, vcert.FormulaSourceCert)
    assert isinstance(formula_certificate.artifact, vcert.MatplotlibScriptArtifactCert)
    assert isinstance(formula_certificate.tcb, vcert.FormulaTcb)

    dataset_source = _dataset_source()
    vega = vcert.VegaArtifactCert(vega_lite_hash="sha256:" + "4" * 64)
    dataset_tcb = _dataset_v03_tcb()
    dataset_certificate = _v03(dataset_source, vega, dataset_tcb)

    sources: tuple[tuple[str, vcert.DatasetSourceCert | vcert.FormulaSourceCert], ...] = (
        ("dataset", dataset_source),
        ("formula", formula_certificate.source),
    )
    artifacts: tuple[
        tuple[str, vcert.VegaArtifactCert | vcert.MatplotlibScriptArtifactCert], ...
    ] = (("dataset", vega), ("formula", formula_certificate.artifact))
    tcbs: tuple[tuple[str, vcert.DatasetTcb | vcert.FormulaTcb], ...] = (
        ("dataset", dataset_tcb),
        ("formula", formula_certificate.tcb),
    )
    dataset_wire = _wire(vcert.vcert_v03_bytes(dataset_certificate))
    formula_wire = _wire(vcert.vcert_v03_bytes(formula_certificate))
    source_wires = {"dataset": dataset_wire["source"], "formula": formula_wire["source"]}
    artifact_wires = {
        "dataset": dataset_wire["artifact"],
        "formula": formula_wire["artifact"],
    }
    tcb_wires = {"dataset": dataset_wire["tcb"], "formula": formula_wire["tcb"]}
    valid_count = 0
    invalid_count = 0

    for source_item, artifact_item, tcb_item in itertools.product(sources, artifacts, tcbs):
        source_family, source = source_item
        artifact_family, artifact = artifact_item
        tcb_family, tcb = tcb_item
        correlated = source_family == artifact_family == tcb_family
        if correlated:
            certificate = _v03(source, artifact, tcb)
            assert vcert.decode_vcert_v03(vcert.vcert_v03_bytes(certificate)) == certificate
            valid_count += 1
            continue

        with pytest.raises(
            ValueError,
            match=r"VCert v0\.3 source, artifact, and TCB variants do not correlate",
        ):
            _v03(source, artifact, tcb)

        crossed_wire = {
            "version": "vcert-0.3",
            "source": source_wires[source_family],
            "spec_hash": "sha256:" + "1" * 64,
            "plotted_table_hash": "sha256:" + "2" * 64,
            "artifact": artifact_wires[artifact_family],
            "checks": [],
            "tcb": tcb_wires[tcb_family],
        }
        with pytest.raises(
            msgspec.ValidationError,
            match=r"VCert v0\.3 source, artifact, and TCB variants do not correlate",
        ):
            vcert.decode_vcert_v03(msgspec.json.encode(crossed_wire))
        invalid_count += 1

    assert valid_count == 2
    assert invalid_count == 6
    assert dataset_wire["source"] == {
        "kind": "dataset",
        "dataset_hash": dataset_source.dataset_hash,
        "manifest_hash": dataset_source.manifest_hash,
        "filters": [{"field": "region", "cmp": "eq", "value": "West"}],
        "sorts": [{"field": "month", "order": "ascending"}],
    }
    assert cast("dict[str, Any]", dataset_wire["artifact"])["kind"] == "vega-lite"


def test_v03_decoder_rejects_near_miss_tags_versions_and_numeric_profile() -> None:
    formula_payload = _payload(_artifact("f02_linear.json"))
    dataset_payload = vcert.vcert_v03_bytes(
        _v03(
            _dataset_source(),
            vcert.VegaArtifactCert(vega_lite_hash="sha256:" + "4" * 64),
            _dataset_v03_tcb(),
        )
    )

    mutants: list[tuple[dict[str, Any], str]] = []
    wire = _wire(formula_payload)
    wire["version"] = "vcert-0.30"
    mutants.append((wire, "vcert-0.30"))
    wire = _wire(formula_payload)
    cast("dict[str, Any]", wire["source"])["kind"] = "formula "
    mutants.append((wire, "formula "))
    wire = _wire(formula_payload)
    cast("dict[str, Any]", wire["artifact"])["kind"] = "matplotlib_script"
    mutants.append((wire, "matplotlib_script"))
    wire = _wire(formula_payload)
    cast("dict[str, Any]", wire["tcb"])["kind"] = "Formula"
    mutants.append((wire, "Formula"))
    wire = _wire(formula_payload)
    cast("dict[str, Any]", wire["tcb"])["numeric_profile"] = "rational-half-even-v2"
    mutants.append((wire, "rational-half-even-v2"))
    wire = _wire(dataset_payload)
    cast("dict[str, Any]", wire["artifact"])["kind"] = "vega"
    mutants.append((wire, "vega"))

    for mutant, refused_literal in mutants:
        with pytest.raises(msgspec.ValidationError) as caught:
            vcert.decode_vcert_v03(msgspec.json.encode(mutant))
        assert refused_literal in str(caught.value)


def test_v03_decoder_rejects_unknown_duplicate_and_strict_type_mismatch() -> None:
    payload = _payload(_artifact("f02_linear.json"))
    wire = _wire(payload)
    wire["unexpected"] = True
    with pytest.raises(msgspec.ValidationError, match="Object contains unknown field"):
        vcert.decode_vcert_v03(msgspec.json.encode(wire))

    wire = _wire(payload)
    wire["spec_hash"] = 1.0
    with pytest.raises(msgspec.ValidationError, match="Expected `str`, got `float`"):
        vcert.decode_vcert_v03(msgspec.json.encode(wire))

    dataset_payload = vcert.vcert_v03_bytes(
        _v03(
            _dataset_source(),
            vcert.VegaArtifactCert(vega_lite_hash="sha256:" + "4" * 64),
            _dataset_v03_tcb(),
        )
    )
    wire = _wire(dataset_payload)
    filters = cast("list[dict[str, Any]]", cast("dict[str, Any]", wire["source"])["filters"])
    filters[0]["value"] = 1.0
    with pytest.raises(msgspec.ValidationError, match=r"Expected `int \| str`, got `float`"):
        vcert.decode_vcert_v03(msgspec.json.encode(wire))

    duplicate = payload.replace(
        b'{"version":"vcert-0.3",',
        b'{"version":"vcert-0.3","version":"vcert-0.3",',
        1,
    )
    with pytest.raises(
        msgspec.ValidationError,
        match=r"duplicate (?:object )?key: 'version'",
    ):
        vcert.decode_vcert_v03(duplicate)


def test_v03_encoder_rejects_direct_construction_bypasses_before_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    formula = vcert.build_formula_certificate(_artifact("f02_linear.json"))
    dataset = _dataset_v03_certificate()
    formula_source = cast("vcert.FormulaSourceCert", formula.source)
    formula_tcb = cast("vcert.FormulaTcb", formula.tcb)
    dataset_source = cast("vcert.DatasetSourceCert", dataset.source)

    for version in ("vcert-0.2", "vcert-0.30", "VCERT-0.3", "vcert-0.3 "):
        with pytest.raises(ValueError, match=r"unsupported VCert v0.3 version"):
            vcert.VCertV03(
                version=cast("Any", version),
                source=formula.source,
                spec_hash=formula.spec_hash,
                plotted_table_hash=formula.plotted_table_hash,
                artifact=formula.artifact,
                checks=formula.checks,
                tcb=formula.tcb,
            )

    source_near_misses: tuple[object, ...] = (
        "formula",
        {"kind": "formula", "formula_hash": formula_source.formula_hash},
        object(),
    )
    for source in source_near_misses:
        with pytest.raises(ValueError, match=r"unsupported VCert v0.3 source variant"):
            vcert.VCertV03(
                version="vcert-0.3",
                source=cast("Any", source),
                spec_hash=formula.spec_hash,
                plotted_table_hash=formula.plotted_table_hash,
                artifact=formula.artifact,
                checks=formula.checks,
                tcb=formula.tcb,
            )

    for profile in (
        "rational-half-even-v2",
        "RATIONAL-HALF-EVEN-V1",
        "rational-half-even-v1 ",
        "",
    ):
        with pytest.raises(ValueError, match=r"unsupported VCert v0.3 numeric profile"):
            msgspec.structs.replace(
                formula_tcb,
                numeric_profile=cast("Any", profile),
            )

    legacy = vcert.VCert(
        version="vcert-0.2",
        dataset_hash="legacy-dataset",
        spec_hash="legacy-spec",
        plotted_table_hash="legacy-table",
        manifest_hash="legacy-manifest",
        vega_lite_hash="legacy-vega",
        checks=(),
        filters=(),
        sorts=(),
        tcb=vcert.dataset_tcb(),
    )
    wrong_version = msgspec.structs.replace(formula)
    msgspec.structs.force_setattr(wrong_version, "version", "vcert-0.2")
    dict_source = msgspec.structs.replace(formula)
    msgspec.structs.force_setattr(
        dict_source,
        "source",
        {"kind": "formula", "formula_hash": formula_source.formula_hash},
    )
    list_checks = msgspec.structs.replace(
        formula,
        checks=cast("Any", list(formula.checks)),
    )
    dict_check = msgspec.structs.replace(
        formula,
        checks=cast(
            "Any",
            ({"id": "security.no_arbitrary_code", "method": "construction", "status": "pass"},),
        ),
    )
    list_filters_source = msgspec.structs.replace(
        dataset_source,
        filters=cast("Any", list(dataset_source.filters)),
    )
    list_filters = msgspec.structs.replace(dataset, source=list_filters_source)
    list_sorts_source = msgspec.structs.replace(
        dataset_source,
        sorts=cast("Any", list(dataset_source.sorts)),
    )
    list_sorts = msgspec.structs.replace(dataset, source=list_sorts_source)
    invalid_profile_tcb = msgspec.structs.replace(formula_tcb)
    msgspec.structs.force_setattr(invalid_profile_tcb, "numeric_profile", "future-profile")
    invalid_profile = msgspec.structs.replace(formula, tcb=invalid_profile_tcb)

    class EncoderBomb:
        def encode(self, _value: object) -> bytes:
            message = "invalid VCert reached the JSON encoder"
            raise AssertionError(message)

    monkeypatch.setattr(vcert, "_VCERT_V03_ENCODER", EncoderBomb())
    invalid: tuple[tuple[object, str], ...] = (
        (legacy, "expected exact VCertV03 at $; got VCert"),
        (wrong_version, "$.version"),
        (dict_source, "expected exact DatasetSourceCert | FormulaSourceCert at $.source"),
        (list_checks, "expected exact tuple at $.checks"),
        (dict_check, "expected exact CertifiedCheck at $.checks[0]"),
        (list_filters, "expected exact tuple at $.source.filters"),
        (list_sorts, "expected exact tuple at $.source.sorts"),
        (invalid_profile, "$.tcb.numeric_profile"),
    )
    for candidate, message_fragment in invalid:
        with pytest.raises(msgspec.ValidationError) as caught:
            vcert.vcert_v03_bytes(cast("vcert.VCertV03", candidate))
        assert message_fragment in str(caught.value)


def test_v03_hash_fields_are_canonical_on_direct_encode_and_decode() -> None:
    formula = vcert.build_formula_certificate(_artifact("f02_linear.json"))
    dataset = _dataset_v03_certificate()
    formula_slots = (
        "formula_hash",
        "spec_hash",
        "plotted_table_hash",
        "matplotlib_script_hash",
    )
    dataset_slots = (
        "dataset_hash",
        "manifest_hash",
        "spec_hash",
        "plotted_table_hash",
        "vega_lite_hash",
        "vendored_font_sha256",
    )
    unsupported = object()
    malformed: tuple[object, ...] = (
        "",
        "x",
        "sha256:" + "0" * 63,
        "sha256:" + "0" * 65,
        "sha256:" + "A" * 64,
        "sha256:" + "g" * 64,
        "sha512:" + "0" * 64,
        "0" * 64,
        "sha256:" + "0" * 64 + "\n",
        1.0,
        unsupported,
    )

    for certificate, slots in ((formula, formula_slots), (dataset, dataset_slots)):
        canonical_payload = vcert.vcert_v03_bytes(certificate)
        for slot in slots:
            for invalid in malformed:
                direct = _replace_certificate_hash(certificate, slot, invalid)
                with pytest.raises(msgspec.ValidationError):
                    vcert.vcert_v03_bytes(direct)

                if invalid is not unsupported:
                    wire = _wire(canonical_payload)
                    _set_wire_hash(wire, slot, invalid)
                    with pytest.raises(msgspec.ValidationError):
                        vcert.decode_vcert_v03(msgspec.json.encode(wire))

            for valid in ("sha256:" + "0" * 64, "sha256:" + "f" * 64):
                direct = _replace_certificate_hash(certificate, slot, valid)
                payload = vcert.vcert_v03_bytes(direct)
                assert vcert.decode_vcert_v03(payload) == direct


def test_v03_decoder_normalizes_malformed_text_to_validation_error() -> None:
    certificate = vcert.build_formula_certificate(_artifact("f02_linear.json"))
    payload = vcert.vcert_v03_bytes(certificate)
    assert vcert.decode_vcert_v03(payload.decode("utf-8")) == certificate

    source = cast("vcert.FormulaSourceCert", certificate.source)
    invalid_utf8 = payload.replace(
        source.formula_hash.encode(),
        b"\xff" + source.formula_hash.encode()[1:],
        1,
    )
    lone_surrogate = payload.decode().replace(
        certificate.spec_hash,
        "\ud800" + certificate.spec_hash[1:],
        1,
    )
    malformed: tuple[tuple[bytes | str, str], ...] = (
        (invalid_utf8, "UnicodeDecodeError"),
        (lone_surrogate, "UnicodeEncodeError"),
        (b"[]", "Expected `object`"),
        (b"{}", "Object missing required field"),
        (b"[" * 5000 + b"]" * 5000, "Expected `object`, got `array`"),
    )
    for invalid, message_fragment in malformed:
        with pytest.raises(msgspec.ValidationError) as caught:
            vcert.decode_vcert_v03(invalid)
        assert message_fragment.lower() in str(caught.value).lower()


@pytest.mark.parametrize("duplicate_kind", ["identical", "conflicting"])
def test_v03_decoder_rejects_same_and_conflicting_duplicates_at_every_depth(
    duplicate_kind: str,
) -> None:
    payload = _payload(_artifact("f02_linear.json"))
    wire = _wire(payload)
    source = cast("dict[str, Any]", wire["source"])
    artifact = cast("dict[str, Any]", wire["artifact"])
    check = cast("list[dict[str, Any]]", wire["checks"])[0]
    tcb = cast("dict[str, Any]", wire["tcb"])
    cases: tuple[tuple[str, object, object], ...] = (
        ("formula_hash", source["formula_hash"], "sha256:" + "f" * 64),
        (
            "matplotlib_script_hash",
            artifact["matplotlib_script_hash"],
            "sha256:" + "f" * 64,
        ),
        ("id", check["id"], "formula.source_parses.near-miss"),
        ("verifier_version", tcb["verifier_version"], "fixed-conflict"),
    )

    for key, value, conflict in cases:
        duplicate_value = conflict if duplicate_kind == "conflicting" else value
        duplicate = _duplicate_member(payload, key, value, duplicate_value)
        with pytest.raises(msgspec.ValidationError) as caught:
            vcert.decode_vcert_v03(duplicate)
        assert f"duplicate object key: {key!r}" in str(caught.value)


@pytest.mark.parametrize("struct", _VCERT_STRUCTS, ids=lambda struct: struct.__name__)
def test_every_vcert_struct_is_frozen_fail_closed_and_keyword_only(
    struct: type[msgspec.Struct],
) -> None:
    config = struct.__struct_config__
    assert config.frozen
    assert config.forbid_unknown_fields
    constructor = cast("Callable[..., object]", struct)
    positional_values = [None] * len(struct.__struct_fields__)
    with pytest.raises(TypeError):
        constructor(*positional_values)


def test_formula_builder_rebinds_formula_source_hash() -> None:
    artifact = _artifact("f02_linear.json")
    bad_hash = _different_hash(artifact.evidence.formula_hash)
    forged = replace(artifact, evidence=replace(artifact.evidence, formula_hash=bad_hash))
    with pytest.raises(ValueError) as caught:
        vcert.build_formula_certificate(forged)
    assert str(caught.value) == (
        f"formula source hash {artifact.evidence.formula_hash} does not match evidence {bad_hash}"
    )


def test_formula_builder_rebinds_spec_hash() -> None:
    artifact = _artifact("f02_linear.json")
    bad_hash = _different_hash(artifact.evidence.spec_hash)
    forged = replace(artifact, evidence=replace(artifact.evidence, spec_hash=bad_hash))
    with pytest.raises(ValueError) as caught:
        vcert.build_formula_certificate(forged)
    assert str(caught.value) == (
        f"spec hash {artifact.evidence.spec_hash} does not match evidence {bad_hash}"
    )


def test_formula_builder_rebinds_plotted_table_hash() -> None:
    artifact = _artifact("f02_linear.json")
    bad_hash = _different_hash(artifact.evidence.plotted_table_hash)
    forged = replace(
        artifact,
        evidence=replace(artifact.evidence, plotted_table_hash=bad_hash),
    )
    with pytest.raises(ValueError) as caught:
        vcert.build_formula_certificate(forged)
    assert str(caught.value) == (
        f"plotted table hash {artifact.evidence.plotted_table_hash} does not match evidence "
        f"{bad_hash}"
    )


def test_formula_builder_rebinds_matplotlib_script_hash() -> None:
    artifact = _artifact("f02_linear.json")
    bad_hash = _different_hash(artifact.matplotlib_script_hash)
    forged = replace(artifact, matplotlib_script_hash=bad_hash)
    with pytest.raises(ValueError) as caught:
        vcert.build_formula_certificate(forged)
    assert str(caught.value) == (
        f"matplotlib script hash {artifact.matplotlib_script_hash} does not match artifact "
        f"{bad_hash}"
    )


def test_formula_builder_refuses_nonpassing_unregistered_or_method_drift() -> None:
    artifact = _artifact("f02_linear.json")
    failed = checks.make_result(
        "render.float64_fidelity",
        status="fail",
        message="forged failure",
    )
    with pytest.raises(
        ValueError,
        match="formula certificate requires an all-passing matplotlib-script artifact",
    ):
        vcert.build_formula_certificate(replace(artifact, results=(failed,)))

    unregistered = checks.CheckResult(
        check="formula.values_bounded.v2",
        method="deterministic_recompute",
        status="pass",
        severity="blocking",
        message="forged near-miss",
    )
    with pytest.raises(
        ValueError,
        match=r"check 'formula\.values_bounded\.v2' has no registered verification method",
    ):
        vcert.build_formula_certificate(replace(artifact, results=(unregistered,)))

    original = next(
        result for result in artifact.results if result.check == "formula.values_bounded"
    )
    wrong_method = msgspec.structs.replace(original, method="construction")
    with pytest.raises(ValueError) as caught:
        vcert.build_formula_certificate(replace(artifact, results=(wrong_method,)))
    assert str(caught.value) == (
        "check 'formula.values_bounded' method 'construction' does not match registry "
        "'deterministic_recompute'"
    )


def test_formula_builder_refuses_mixed_status_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact("f02_linear.json")
    failed = checks.make_result(
        artifact.results[0].check,
        status="fail",
        message="mixed-status sentinel",
    )
    mixed = replace(artifact, results=(*artifact.results, failed))
    calls = 0

    def hash_bomb(_source: bytes) -> str:
        nonlocal calls
        calls += 1
        message = "mixed-status artifact reached carrier hashing"
        raise AssertionError(message)

    monkeypatch.setattr(canon, "hash_formula_source", hash_bomb)
    with pytest.raises(ValueError, match="all-passing matplotlib-script artifact"):
        vcert.build_formula_certificate(mixed)
    assert calls == 0


def test_each_one_byte_binding_mutation_moves_payload_and_digest() -> None:
    artifact = _artifact("f02_linear.json")
    base_certificate = vcert.build_formula_certificate(artifact)
    base_payload = vcert.vcert_v03_bytes(base_certificate)
    base_digest = hashlib.sha256(base_payload).digest()

    source_bytes = artifact.evidence.formula_source_bytes
    mutated_source_bytes = source_bytes.replace(b"2", b"3", 1)
    _assert_one_byte_changed(source_bytes, mutated_source_bytes)
    source_evidence = replace(
        artifact.evidence,
        formula_source_bytes=mutated_source_bytes,
        formula_hash=canon.hash_formula_source(mutated_source_bytes),
    )
    source_artifact = replace(artifact, evidence=source_evidence)

    assert artifact.spec.formula == "2*x + 1"
    mutated_spec = msgspec.structs.replace(artifact.spec, formula="3*x + 1")
    _assert_one_byte_changed(canon.spec_bytes(artifact.spec), canon.spec_bytes(mutated_spec))
    spec_evidence = replace(artifact.evidence, spec_hash=canon.hash_spec(mutated_spec))
    spec_artifact = replace(artifact, spec=mutated_spec, evidence=spec_evidence)

    table = artifact.evidence.plotted_table
    first_row = list(table.rows[0])
    assert first_row[1] == Decimal("1.00")
    first_row[1] = Decimal("2.00")
    mutated_table = msgspec.structs.replace(
        table,
        rows=(tuple(first_row), *table.rows[1:]),
    )
    _assert_one_byte_changed(
        canon.serialize_table(table).encode(),
        canon.serialize_table(mutated_table).encode(),
    )
    table_evidence = replace(
        artifact.evidence,
        plotted_table=mutated_table,
        plotted_table_hash=canon.hash_table(mutated_table),
    )
    table_artifact = replace(artifact, evidence=table_evidence)

    mutated_script = artifact.matplotlib_script.replace(
        b'ax.set_xlabel("x")',
        b'ax.set_xlabel("X")',
        1,
    )
    _assert_one_byte_changed(artifact.matplotlib_script, mutated_script)
    script_artifact = replace(
        artifact,
        matplotlib_script=mutated_script,
        matplotlib_script_hash=canon.hash_matplotlib_script(mutated_script),
    )

    mutated_certificates = (
        vcert.build_formula_certificate(source_artifact),
        vcert.build_formula_certificate(spec_artifact),
        vcert.build_formula_certificate(table_artifact),
        vcert.build_formula_certificate(script_artifact),
    )
    mutated_payloads = tuple(vcert.vcert_v03_bytes(item) for item in mutated_certificates)
    assert all(payload != base_payload for payload in mutated_payloads)
    assert all(hashlib.sha256(payload).digest() != base_digest for payload in mutated_payloads)
    assert len(set(mutated_payloads)) == 4

    formula, spec, table_cert, script = mutated_certificates
    assert isinstance(base_certificate.source, vcert.FormulaSourceCert)
    assert isinstance(formula.source, vcert.FormulaSourceCert)
    assert formula.source.formula_hash != base_certificate.source.formula_hash
    assert formula.spec_hash == base_certificate.spec_hash
    assert spec.spec_hash != base_certificate.spec_hash
    assert table_cert.plotted_table_hash != base_certificate.plotted_table_hash
    assert isinstance(base_certificate.artifact, vcert.MatplotlibScriptArtifactCert)
    assert isinstance(script.artifact, vcert.MatplotlibScriptArtifactCert)
    assert (
        script.artifact.matplotlib_script_hash != base_certificate.artifact.matplotlib_script_hash
    )


def test_formula_certificate_is_process_hashseed_and_decimal_context_deterministic() -> None:
    expected = _FORMULA_VECTORS["f02_linear.json"]
    expected_payload = bytes.fromhex(cast("str", expected["canonical_hex"]))
    first = _payload(_artifact("f02_linear.json"))
    second = _payload(_artifact("f02_linear.json"))
    assert first == second == expected_payload

    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        hostile = _payload(_artifact("f02_linear.json"))
    assert hostile == expected_payload

    outputs: set[str] = set()
    for seed in ("0", "1", "4294967295"):
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", _DETERMINISM_PROGRAM],
            cwd=_ROOT,
            env=os.environ | {"PYTHONHASHSEED": seed, "LC_ALL": "C"},
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stderr == ""
        outputs.add(completed.stdout)
    assert outputs == {expected_payload.hex() + "\n" + cast("str", expected["sha256"]) + "\n"}


def test_v02_legacy_wire_vector_remains_exact() -> None:
    certificate = render.VCert(
        version="vcert-0.2",
        dataset_hash="sha256:" + "0" * 64,
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        manifest_hash="sha256:" + "3" * 64,
        vega_lite_hash="sha256:" + "4" * 64,
        checks=(
            render.CertifiedCheck(
                id="dataset.hash_matches_source",
                method="deterministic_recompute",
                status="pass",
            ),
        ),
        filters=(render.DisclosedFilter(field="region", cmp="eq", value="West"),),
        sorts=(render.DisclosedSort(field="month", order="ascending"),),
        tcb=render.Tcb(
            verifier_version="0.2.0",
            z3_version="4.16.0",
            canon_version="canon-0.1",
            python="3.13.0",
            msgspec="0.21.0",
            unidata="16.0.0",
            vl_convert_python="1.9.0",
            vl_version="5.21",
            font_family="DejaVu Sans",
            vendored_font_sha256="sha256:" + "5" * 64,
        ),
    )
    expected = (
        b'{"version":"vcert-0.2","dataset_hash":"sha256:'
        b'0000000000000000000000000000000000000000000000000000000000000000",'
        b'"spec_hash":"sha256:1111111111111111111111111111111111111111111111111111111111111111",'
        b'"plotted_table_hash":"sha256:2222222222222222222222222222222222222222222222222222222222222222",'
        b'"manifest_hash":"sha256:3333333333333333333333333333333333333333333333333333333333333333",'
        b'"vega_lite_hash":"sha256:4444444444444444444444444444444444444444444444444444444444444444",'
        b'"checks":[{"id":"dataset.hash_matches_source",'
        b'"method":"deterministic_recompute","status":"pass"}],'
        b'"filters":[{"field":"region","cmp":"eq","value":"West"}],'
        b'"sorts":[{"field":"month","order":"ascending"}],'
        b'"tcb":{"verifier_version":"0.2.0","z3_version":"4.16.0",'
        b'"canon_version":"canon-0.1","python":"3.13.0","msgspec":"0.21.0",'
        b'"unidata":"16.0.0","vl_convert_python":"1.9.0","vl_version":"5.21",'
        b'"font_family":"DejaVu Sans","vendored_font_sha256":"sha256:'
        b'5555555555555555555555555555555555555555555555555555555555555555"}}'
    )

    payload = render.vcert_bytes(certificate)
    assert payload == expected
    assert len(payload) == 992
    assert hashlib.sha256(payload).hexdigest() == (
        "2e762d4be4955357c9721d44f160267f89d64c55aa6ceb16eb1545e462d9a25f"
    )
    assert vcert.decode_vcert(payload) == certificate


def test_v02_fixed_payload_vector_and_strict_no_coercion() -> None:
    certificate = vcert.VCert(
        version="vcert-0.2",
        dataset_hash="sha256:" + "0" * 64,
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        manifest_hash="sha256:" + "3" * 64,
        vega_lite_hash="sha256:" + "4" * 64,
        checks=(
            vcert.CertifiedCheck(
                id="dataset.hash_matches_source",
                method="deterministic_recompute",
                status="pass",
            ),
        ),
        filters=(vcert.DisclosedFilter(field="region", cmp="eq", value="West"),),
        sorts=(vcert.DisclosedSort(field="month", order="ascending"),),
        tcb=vcert.Tcb(
            verifier_version="0.2.0",
            z3_version="4.16.0",
            canon_version="canon-0.1",
            python="3.13.0",
            msgspec="0.21.0",
            unidata="16.0.0",
            vl_convert_python="1.9.0",
            vl_version="5.21",
            font_family="DejaVu Sans",
            vendored_font_sha256="sha256:" + "5" * 64,
        ),
    )
    expected = (
        b'{"version":"vcert-0.2","dataset_hash":"sha256:'
        + b"0" * 64
        + b'","spec_hash":"sha256:'
        + b"1" * 64
        + b'","plotted_table_hash":"sha256:'
        + b"2" * 64
        + b'","manifest_hash":"sha256:'
        + b"3" * 64
        + b'","vega_lite_hash":"sha256:'
        + b"4" * 64
        + b'","checks":[{"id":"dataset.hash_matches_source","method":'
        b'"deterministic_recompute","status":"pass"}],"filters":[{"field":"region",'
        b'"cmp":"eq","value":"West"}],"sorts":[{"field":"month","order":"ascending"}],'
        b'"tcb":{"verifier_version":"0.2.0","z3_version":"4.16.0","canon_version":'
        b'"canon-0.1","python":"3.13.0","msgspec":"0.21.0","unidata":"16.0.0",'
        b'"vl_convert_python":"1.9.0","vl_version":"5.21","font_family":"DejaVu Sans",'
        b'"vendored_font_sha256":"sha256:' + b"5" * 64 + b'"}}'
    )

    assert len(expected) == 992
    assert hashlib.sha256(expected).hexdigest() == (
        "2e762d4be4955357c9721d44f160267f89d64c55aa6ceb16eb1545e462d9a25f"
    )
    assert vcert.vcert_bytes(certificate) == expected
    assert render.vcert_bytes(certificate) == expected
    assert vcert.decode_vcert(expected) == certificate

    float_spelled_filter = expected.replace(b'"value":"West"', b'"value":1.0', 1)
    with pytest.raises(msgspec.ValidationError):
        vcert.decode_vcert(float_spelled_filter)


def test_v02_real_dataset_payload_and_render_exports_remain_byte_identical() -> None:
    assert render.VCert is vcert.VCert
    assert render.Tcb is vcert.Tcb
    assert render.vcert_bytes is vcert.vcert_bytes
    assert render._VCERT_VERSION == "vcert-0.2"
    assert not issubclass(vcert.DatasetTcb, vcert.Tcb)

    spec = decode_spec((_DATASET_GOOD / "g01_total_revenue_by_month.json").read_bytes())
    manifest = (_SCHEMAS / f"{Path(spec.dataset.name).stem}.json").read_bytes()
    result = cast("render.RenderResult", render.render(spec, manifest, data_dir=_DATA))
    payload = render.vcert_bytes(result.certificate)
    assert b'"kind":' not in payload
    assert vcert.decode_vcert(payload) == result.certificate
    assert type(result.certificate.tcb) is vcert.Tcb


def test_v02_dataset_certificate_canonical_form_under_a_fixed_tcb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The v0.2 byte pin, driven through the whole render path on an injected TCB.

    Patching the collector rather than the built certificate keeps the pinned bytes a product of
    ``build_dataset_certificate(tcb=...)`` on the real pipeline, and makes the pin double as the
    render-level threading gate: a renderer that dropped ``tcb=`` would fall back to live
    collection and move every byte.

    ``_tcb`` is the patched seam and ``_dataset_tcb`` is armed to explode, because patching the
    collector alone would let a ``_build_certificate`` that reached past ``_tcb()`` straight to
    ``_dataset_tcb(...)`` return the same sentinel and keep this test green while the renderer's
    monkeypatch-visible version seam quietly died.
    """

    def _seam() -> vcert.Tcb:
        return DATASET_TCB

    def _explode(*, verifier_version: str) -> vcert.Tcb:
        message = f"render bypassed _tcb() and collected live for {verifier_version}"
        raise AssertionError(message)

    monkeypatch.setattr(render, "_tcb", _seam)
    monkeypatch.setattr(render, "_dataset_tcb", _explode)
    spec = decode_spec((_DATASET_GOOD / "g01_total_revenue_by_month.json").read_bytes())
    manifest = (_SCHEMAS / f"{Path(spec.dataset.name).stem}.json").read_bytes()
    result = cast("render.RenderResult", render.render(spec, manifest, data_dir=_DATA))
    payload = render.vcert_bytes(result.certificate)

    assert result.certificate.tcb is DATASET_TCB
    assert len(payload) == 1746
    assert hashlib.sha256(payload).hexdigest() == (
        "609a075efa2e0c5e4bcfeef8d92c5ad3d40879e4826d15eed92efcc59f6960ab"
    )
    assert b'"kind":' not in payload
    assert vcert.decode_vcert(payload) == result.certificate


def test_render_tcb_forwards_monkeypatched_verifier_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier_version = "monkeypatched-verifier-version"
    monkeypatch.setattr(render, "__version__", verifier_version)
    assert render._tcb().verifier_version == verifier_version


def test_certificate_leaf_and_attestation_import_without_display_stack() -> None:
    program = """
import sys
import verifier.vcert
assert "verifier.render" not in sys.modules
assert "vl_convert" not in sys.modules
import verifier.attestation
assert "verifier.render" not in sys.modules
assert "vl_convert" not in sys.modules
"""
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", program],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == ""
    assert completed.stderr == ""
