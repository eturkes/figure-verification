# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Source/artifact-aware provenance certificates without display-stack imports.

VCert v0.2 remains the dataset wire contract. VCert v0.3 makes source, artifact, and TCB
variants explicit; this unit emits v0.3 only for formula plots while retaining a structurally
complete dataset branch for a future opt-in migration. Formula certification checks exactly four
domain-separated carrier/digest agreements. Cross-carrier derivation and result completeness remain
trusted properties of the admitted matplotlib-script producer. Rebinding never parses, evaluates,
samples, emits, solves, executes, or compares pixels.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata
import importlib.resources
import json
from typing import TYPE_CHECKING, Annotated, Literal, cast

import msgspec

from verifier import __version__, canon, checks, expr
from verifier.eval import active_sort
from verifier.schema import Filter, NumericProfile, VPlotSpec, _reject_duplicate_keys

if TYPE_CHECKING:
    from verifier.matplotlib_script import MatplotlibScriptArtifact

__all__ = [
    "CertifiedCheck",
    "DatasetSourceCert",
    "DatasetTcb",
    "DisclosedFilter",
    "DisclosedSort",
    "FormulaSourceCert",
    "FormulaTcb",
    "MatplotlibScriptArtifactCert",
    "Tcb",
    "VCert",
    "VCertV03",
    "VegaArtifactCert",
    "build_dataset_certificate",
    "build_formula_certificate",
    "dataset_tcb",
    "decode_vcert",
    "decode_vcert_v03",
    "disclosed_transforms",
    "hash_vega_lite",
    "vcert_bytes",
    "vcert_v03_bytes",
]

_VCERT_VERSION: Literal["vcert-0.2"] = "vcert-0.2"
_VCERT_V03_VERSION: Literal["vcert-0.3"] = "vcert-0.3"
# v5.21 matches the renderer's Vega-Lite v5 `$schema` constant; the exact minor is the
# certificate/display determinism lever.
_VL_VERSION = "5.21"
# Naming this family in every rendered spec REQUESTS it. The vendored file under this directory
# plus renderer registration guarantees the family RESOLVES; byte SELECTION over a same-named
# system DejaVu Sans remains unproven.
_FONT_FAMILY = "DejaVu Sans"
_FONT_DIR = importlib.resources.files("verifier") / "assets" / "fonts"
_NUMERIC_PROFILE: NumericProfile = "rational-half-even-v1"
_SHA256_PATTERN = r"^(?!.*[\r\n])sha256:[0-9a-f]{64}$"
_Sha256Digest = Annotated[
    str,
    msgspec.Meta(min_length=71, max_length=71, pattern=_SHA256_PATTERN),
]


class Tcb(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """The verifier/formal/display TCB stamped into VCert.

    ``verifier_version`` identifies the package implementing the checks; ``z3_version`` the
    solver behind ``z3_smt`` results. The remaining fields identify canonicalization and the
    native display stack trusted to render verified data faithfully, NOT proven to do so. SVG is
    not hashed by the VCert, and cross-machine byte identity is unclaimed.
    ``vendored_font_sha256`` identifies
    the registered font asset, not proof that vl-convert selected it over a same-named system
    font (``render_svg`` documents the same scope).
    """

    verifier_version: str
    z3_version: str
    canon_version: str
    python: str
    msgspec: str
    unidata: str
    vl_convert_python: str
    vl_version: str
    font_family: str
    vendored_font_sha256: str


class DatasetTcb(
    msgspec.Struct,
    frozen=True,
    forbid_unknown_fields=True,
    kw_only=True,
    tag_field="kind",
    tag="dataset",
):
    """Dataset branch of the source-aware VCert v0.3 TCB union."""

    verifier_version: str
    z3_version: str
    canon_version: str
    python: str
    msgspec: str
    unidata: str
    vl_convert_python: str
    vl_version: str
    font_family: str
    vendored_font_sha256: _Sha256Digest


class FormulaTcb(
    msgspec.Struct,
    frozen=True,
    forbid_unknown_fields=True,
    kw_only=True,
    tag_field="kind",
    tag="formula",
):
    """Formula verifier TCB; downstream matplotlib/browser display stays outside it."""

    verifier_version: str
    z3_version: str
    canon_version: str
    python: str
    msgspec: str
    unidata: str
    grammar_version: str
    numeric_profile: NumericProfile
    script_template_version: str

    def __post_init__(self) -> None:
        if cast("object", self.numeric_profile) != _NUMERIC_PROFILE:
            message = f"unsupported VCert v0.3 numeric profile: {self.numeric_profile!r}"
            raise ValueError(message)


class DisclosedFilter(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """One applied filter op, disclosed in the cert. `value` is model-controlled (arbitrary
    text within FilterValue bounds) -> badge_html HTML-escapes it."""

    field: str
    cmp: str
    value: int | str


class DisclosedSort(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """One active-sort key, disclosed in the certificate in that transform's declared order."""

    field: str
    order: str


class CertifiedCheck(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """One passing final result recorded with the method that established it."""

    id: str
    method: checks.CheckMethod
    status: Literal["pass"]


class VCert(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """A VCert v0.2 provenance certificate: five bound artifact hashes, method-bearing passing
    checks, disclosed applied filters and active-sort keys, and the verifier/formal/display TCB.
    Core render produces a deterministic payload; the service signs its exact bytes into DSSE.
    Attestation verification decodes an external copy only after its signature and application
    type verify under an independently trusted public key. Durable archive/replay consumers use
    that same authenticated payload.
    """

    version: Literal["vcert-0.2"]
    dataset_hash: str
    spec_hash: str
    plotted_table_hash: str
    manifest_hash: str
    vega_lite_hash: str
    checks: tuple[CertifiedCheck, ...]
    filters: tuple[DisclosedFilter, ...]
    sorts: tuple[DisclosedSort, ...]
    tcb: Tcb


class DatasetSourceCert(
    msgspec.Struct,
    frozen=True,
    forbid_unknown_fields=True,
    kw_only=True,
    tag_field="kind",
    tag="dataset",
):
    """Dataset-specific source identities and disclosures for v0.3 representability."""

    dataset_hash: _Sha256Digest
    manifest_hash: _Sha256Digest
    filters: tuple[DisclosedFilter, ...]
    sorts: tuple[DisclosedSort, ...]


class FormulaSourceCert(
    msgspec.Struct,
    frozen=True,
    forbid_unknown_fields=True,
    kw_only=True,
    tag_field="kind",
    tag="formula",
):
    """Resolved canonical formula-source identity."""

    formula_hash: _Sha256Digest


class VegaArtifactCert(
    msgspec.Struct,
    frozen=True,
    forbid_unknown_fields=True,
    kw_only=True,
    tag_field="kind",
    tag="vega-lite",
):
    """Exact verifier-authored Vega-Lite artifact identity."""

    vega_lite_hash: _Sha256Digest


class MatplotlibScriptArtifactCert(
    msgspec.Struct,
    frozen=True,
    forbid_unknown_fields=True,
    kw_only=True,
    tag_field="kind",
    tag="matplotlib-script",
):
    """Exact verifier-authored matplotlib-script artifact identity."""

    matplotlib_script_hash: _Sha256Digest


class VCertV03(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """Source/artifact-aware VCert v0.3 with correlated source, artifact, and TCB variants."""

    version: Literal["vcert-0.3"]
    source: DatasetSourceCert | FormulaSourceCert
    spec_hash: _Sha256Digest
    plotted_table_hash: _Sha256Digest
    artifact: VegaArtifactCert | MatplotlibScriptArtifactCert
    checks: tuple[CertifiedCheck, ...]
    tcb: DatasetTcb | FormulaTcb

    def __post_init__(self) -> None:
        if cast("object", self.version) != _VCERT_V03_VERSION:
            message = f"unsupported VCert v0.3 version: {self.version!r}"
            raise ValueError(message)

        source_type = type(self.source)
        if source_type is DatasetSourceCert:
            correlated = type(self.artifact) is VegaArtifactCert and type(self.tcb) is DatasetTcb
        elif source_type is FormulaSourceCert:
            correlated = (
                type(self.artifact) is MatplotlibScriptArtifactCert and type(self.tcb) is FormulaTcb
            )
        else:
            message = f"unsupported VCert v0.3 source variant: {source_type.__name__}"
            raise ValueError(message)

        if not correlated:
            message = "VCert v0.3 source, artifact, and TCB variants do not correlate"
            raise ValueError(message)


# canon's determinism family: definition-order struct fields, sorted dict/set keys (neither
# certificate contains either container), and no Unicode normalization. VCert v0.2 contains only
# str/int, tuples, and nested structs (filter values are int | str, never float), so encoding is
# total and deterministic in-process for the pinned build.
_VCERT_ENCODER = msgspec.json.Encoder(order="deterministic")
# VCert v0.3 keeps the same total domain and adds only tagged-union structs plus string-valued
# NumericProfile/digest literals; its validated algebra therefore has the same total,
# definition-order deterministic encoding argument.
_VCERT_V03_ENCODER = msgspec.json.Encoder(order="deterministic")
_VCERT_DECODER = msgspec.json.Decoder(VCert, strict=True)
_VCERT_V03_DECODER = msgspec.json.Decoder(VCertV03, strict=True)


def _require_exact_type(
    value: object,
    expected: tuple[type[object], ...],
    *,
    path: str,
) -> None:
    if type(value) not in expected:
        expected_names = " | ".join(item.__name__ for item in expected)
        message = f"expected exact {expected_names} at {path}; got {type(value).__name__}"
        raise msgspec.ValidationError(message)


def _validate_v03_for_encode(certificate: object) -> VCertV03:
    """Reject direct-construction bypasses before canonical JSON emission."""
    _require_exact_type(certificate, (VCertV03,), path="$")
    typed = cast("VCertV03", certificate)
    _require_exact_type(
        typed.source,
        (DatasetSourceCert, FormulaSourceCert),
        path="$.source",
    )
    _require_exact_type(
        typed.artifact,
        (VegaArtifactCert, MatplotlibScriptArtifactCert),
        path="$.artifact",
    )
    _require_exact_type(typed.tcb, (DatasetTcb, FormulaTcb), path="$.tcb")
    _require_exact_type(typed.checks, (tuple,), path="$.checks")
    for index, check in enumerate(typed.checks):
        _require_exact_type(check, (CertifiedCheck,), path=f"$.checks[{index}]")

    if isinstance(typed.source, DatasetSourceCert):
        _require_exact_type(typed.source.filters, (tuple,), path="$.source.filters")
        for index, disclosed_filter in enumerate(typed.source.filters):
            _require_exact_type(
                disclosed_filter,
                (DisclosedFilter,),
                path=f"$.source.filters[{index}]",
            )
        _require_exact_type(typed.source.sorts, (tuple,), path="$.source.sorts")
        for index, disclosed_sort in enumerate(typed.source.sorts):
            _require_exact_type(
                disclosed_sort,
                (DisclosedSort,),
                path=f"$.source.sorts[{index}]",
            )

    try:
        return msgspec.convert(
            msgspec.to_builtins(typed),
            type=VCertV03,
            strict=True,
        )
    except msgspec.ValidationError:
        raise
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
        message = f"{type(exc).__name__}: {exc}"
        raise msgspec.ValidationError(message) from None


def vcert_bytes(certificate: VCert) -> bytes:
    """Canonical VCert v0.2 JSON bytes."""
    return _VCERT_ENCODER.encode(certificate)


def vcert_v03_bytes(certificate: VCertV03) -> bytes:
    """Validate then emit canonical VCert v0.3 JSON bytes."""
    return _VCERT_V03_ENCODER.encode(_validate_v03_for_encode(certificate))


def decode_vcert(payload: bytes) -> VCert:
    """Strictly decode one v0.2 payload and reject duplicate object keys."""
    certificate = _VCERT_DECODER.decode(payload)
    json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    return certificate


def decode_vcert_v03(payload: bytes | str) -> VCertV03:
    """Strictly decode v0.3, rejecting duplicates through one validation-error family."""
    try:
        certificate = _VCERT_V03_DECODER.decode(payload)
        json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except msgspec.ValidationError:
        raise
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
        message = f"{type(exc).__name__}: {exc}"
        raise msgspec.ValidationError(message) from None
    return certificate


def hash_vega_lite(vega_lite: bytes) -> str:
    """SHA-256 content address of exact emitted Vega-Lite bytes."""
    return "sha256:" + hashlib.sha256(vega_lite).hexdigest()


@functools.cache
def _font_sha256() -> str:
    return "sha256:" + hashlib.sha256((_FONT_DIR / "DejaVuSans.ttf").read_bytes()).hexdigest()


def dataset_tcb(*, verifier_version: str = __version__) -> Tcb:
    """Current dataset verifier/formal/Vega display TCB."""
    # Lazy solver-version import preserves the renderer-free leaf; formal has no vcert edge.
    from verifier import formal  # noqa: PLC0415

    versions = canon.runtime_versions()
    return Tcb(
        verifier_version=verifier_version,
        z3_version=formal.solver_version(),
        canon_version=versions.canon_version,
        python=versions.python,
        msgspec=versions.msgspec,
        unidata=versions.unidata,
        vl_convert_python=importlib.metadata.version("vl-convert-python"),
        vl_version=_VL_VERSION,
        font_family=_FONT_FAMILY,
        vendored_font_sha256=_font_sha256(),
    )


def _formula_tcb(numeric_profile: NumericProfile) -> FormulaTcb:
    # Lazy solver-version import preserves the renderer-free leaf; formal has no vcert edge.
    from verifier import formal  # noqa: PLC0415

    # Lazy template-version import preserves the same leaf; matplotlib_script has no vcert edge.
    from verifier.matplotlib_script import SCRIPT_TEMPLATE_VERSION  # noqa: PLC0415

    versions = canon.runtime_versions()
    return FormulaTcb(
        verifier_version=__version__,
        z3_version=formal.solver_version(),
        canon_version=versions.canon_version,
        python=versions.python,
        msgspec=versions.msgspec,
        unidata=versions.unidata,
        grammar_version=expr.GRAMMAR_VERSION,
        numeric_profile=numeric_profile,
        script_template_version=SCRIPT_TEMPLATE_VERSION,
    )


def disclosed_transforms(
    spec: VPlotSpec,
) -> tuple[tuple[DisclosedFilter, ...], tuple[DisclosedSort, ...]]:
    """Derive deterministic dataset filter and active-sort disclosures."""
    filters = tuple(
        DisclosedFilter(field=transform.field, cmp=transform.cmp, value=transform.value)
        for transform in spec.transform
        if isinstance(transform, Filter)
    )
    active = active_sort(spec.transform)
    sorts = (
        tuple(DisclosedSort(field=key.field, order=key.order) for key in active.by)
        if active is not None
        else ()
    )
    return filters, sorts


def _certified_checks(results: tuple[checks.CheckResult, ...]) -> tuple[CertifiedCheck, ...]:
    return tuple(
        CertifiedCheck(id=result.check, method=result.method, status="pass")
        for result in results
        if result.status == "pass"
    )


def _formula_certified_checks(
    results: tuple[checks.CheckResult, ...],
) -> tuple[CertifiedCheck, ...]:
    """Rebind each passing result to the closed check/method registry without re-running it."""
    certified: list[CertifiedCheck] = []
    for result in results:
        registered = checks.make_result(result.check, status="pass", message=result.message)
        if result.method != registered.method:
            message = (
                f"check {result.check!r} method {result.method!r} does not match "
                f"registry {registered.method!r}"
            )
            raise ValueError(message)
        certified.append(CertifiedCheck(id=result.check, method=result.method, status="pass"))
    return tuple(certified)


def build_dataset_certificate(
    spec: VPlotSpec,
    evidence: checks.DatasetEvidence,
    results: tuple[checks.CheckResult, ...],
    vega_lite: bytes,
    *,
    verifier_version: str = __version__,
) -> VCert:
    """Mint v0.2 from one prepared dataset artifact without rebuilding it."""
    filters, sorts = disclosed_transforms(spec)
    return VCert(
        version=_VCERT_VERSION,
        dataset_hash=evidence.dataset_hash,
        spec_hash=evidence.spec_hash,
        plotted_table_hash=evidence.plotted_table_hash,
        manifest_hash=evidence.manifest_hash,
        vega_lite_hash=hash_vega_lite(vega_lite),
        checks=_certified_checks(results),
        filters=filters,
        sorts=sorts,
        tcb=dataset_tcb(verifier_version=verifier_version),
    )


def build_formula_certificate(artifact: MatplotlibScriptArtifact) -> VCertV03:
    """Rebind four carrier/digest pairs and mint formula v0.3.

    The admitted producer remains authoritative for cross-carrier derivation and complete results.
    This builder never parses, evaluates, samples, emits, solves, executes, or compares pixels.
    """
    if any(result.status != "pass" for result in artifact.results):
        message = "formula certificate requires an all-passing matplotlib-script artifact"
        raise ValueError(message)

    evidence = artifact.evidence
    formula_hash = canon.hash_formula_source(evidence.formula_source_bytes)
    if formula_hash != evidence.formula_hash:
        message = (
            f"formula source hash {formula_hash} does not match evidence {evidence.formula_hash}"
        )
        raise ValueError(message)

    spec_hash = canon.hash_spec(artifact.spec)
    if spec_hash != evidence.spec_hash:
        message = f"spec hash {spec_hash} does not match evidence {evidence.spec_hash}"
        raise ValueError(message)

    plotted_table_hash = canon.hash_table(evidence.plotted_table)
    if plotted_table_hash != evidence.plotted_table_hash:
        message = (
            f"plotted table hash {plotted_table_hash} does not match evidence "
            f"{evidence.plotted_table_hash}"
        )
        raise ValueError(message)

    matplotlib_script_hash = canon.hash_matplotlib_script(artifact.matplotlib_script)
    if matplotlib_script_hash != artifact.matplotlib_script_hash:
        message = (
            f"matplotlib script hash {matplotlib_script_hash} does not match artifact "
            f"{artifact.matplotlib_script_hash}"
        )
        raise ValueError(message)

    return VCertV03(
        version=_VCERT_V03_VERSION,
        source=FormulaSourceCert(formula_hash=formula_hash),
        spec_hash=spec_hash,
        plotted_table_hash=plotted_table_hash,
        artifact=MatplotlibScriptArtifactCert(matplotlib_script_hash=matplotlib_script_hash),
        checks=_formula_certified_checks(artifact.results),
        tcb=_formula_tcb(artifact.spec.numeric_profile),
    )
