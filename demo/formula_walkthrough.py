# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Self-contained formula-mode capstone used by ``python -m demo.formula_walkthrough``.

Each scenario owns a temporary service state directory, drives the Litestar app in process, and
joins one full formula chain: an empty state directory, a verified occurrence, a restart onto a
NEW app instance over that SAME directory, and the archived retrieval routes. No socket, model,
accelerator, or external service is used; the one model arm drives a deterministic stub.

Two scenarios drive the failure side. A REJECTED formula occurrence still archives durably, and
the real ``audit`` CLI explains it after a restart while staying redacted by default. A rotated
signer, a damaged archive schema, and a tampered attempt signature each fail closed, publishing
nothing and disclosing neither the damaged object nor the underlying cause.

The mode-neutral scenario frame is imported from ``demo.walkthrough`` rather than re-authored, so
both capstones report through one shape. The formula claim boundary is unmoved here: the verifier
owns every plotted point and AUTHORS the matplotlib script bytes, and this walkthrough never
executes them. ``/chart`` therefore stays 404 in formula mode, and ``/table`` plus ``/script``
serve typed-relation, digest-addressed bytes that are not certificate-graph authenticated.
"""

import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import patch

import msgspec
from litestar import Litestar
from litestar.testing import TestClient

from demo.walkthrough import (
    _HTTP_INTERNAL_SERVER_ERROR,
    _HTTP_NOT_FOUND,
    _HTTP_OK,
    _JSON,
    _ROOT,
    DemoError,
    Scenario,
    ScenarioResult,
    ScenarioStatus,
    WalkthroughReport,
    _attempt_id,
    _expect_problem,
    _expect_status,
    _ListHandler,
    _model_client_builder,
    _object,
    _object_list,
    _read_attempt,
    _require,
    _response_object,
    _run_audit_cli,
    encode_report,
)
from verifier import attestation, canon, vcert
from verifier.service import model_client
from verifier.service.app import create_app
from verifier.service.archive import (
    Archive,
    ArchiveIntegrityError,
    ArchiveSchemaError,
    ArchiveStats,
    AttemptBundle,
    AttemptOutcome,
    AttemptRoute,
    open_archive,
)
from verifier.service.identity import SigningIdentity
from verifier.service.settings import Settings

_LOGGER = logging.getLogger(__name__)

_DATA = _ROOT / "data"
_FORMULA_SPEC = _ROOT / "examples" / "formula_good_specs" / "f02_linear.json"
_REPORT_PATH = _ROOT / "demo" / "reports" / "formula_report.json"
_NO_ARTIFACT = "no such artifact"
_USER_REQUEST = "Plot the line 2x + 1 from 0 to 10"

# Hand-stated rather than read from the check registry: a test or demo that derives its own
# expectation from the production constant pins nothing about that constant.
_CERTIFIED_METHODS = frozenset({"construction", "deterministic_recompute", "z3_smt"})
# Hand-stated beside the method labels: dropping one construction check preserves all three
# methods, so the method set alone cannot detect an under-reported certificate.
_CERTIFIED_CHECK_COUNT = 13
_ARTIFACT_MATCHES = {
    "formula": True,
    "spec": True,
    "plotted_table": True,
    "matplotlib_script": True,
}
# The same four keys carry None once trust fails ahead of any recomputation. Their presence is
# what makes an untrusted-key verdict FORMULA-shaped rather than a mode-neutral failure.
_UNMATCHED_ARTIFACTS = {
    "formula": None,
    "spec": None,
    "plotted_table": None,
    "matplotlib_script": None,
}
# A rejected formula occurrence carries exactly these two carriers, in this order. The redaction
# list is one SHARED attempt list, so this exercises a mode-neutral guarantee on a formula
# occurrence rather than asserting a formula-specific redaction rule.
_FORMULA_AUDIT_ROLES = ("raw_spec", "verdict")
_DATASET_AUDIT_ROLES = frozenset({"raw_csv", "raw_manifest", "vega_lite", "svg"})
_MALFORMED_SPEC = b"{"
_REJECTED_VERDICT_KEYS = {"attempt_id", "layer", "results", "verified"}
_REJECTED_RESULT = ("spec.decode", "schema_validation", "blocking")
_DAMAGED_INDEX = "attempts_by_plot"
_SIGNATURE_MARKER = b'"sig":"'

type _Hashes = tuple[str, str, str, str]
type _CertifiedArtifacts = tuple[str, str]


def _verify_formula(client: TestClient[Litestar], spec: bytes) -> dict[str, Any]:
    response = client.post("/verify-formula", content=spec, headers=_JSON)
    _expect_status(response, _HTTP_OK, "verify-formula")
    body = _response_object(response, "verify-formula response")
    _require(body.get("verified") is True, "verify-formula did not verify the valid formula spec")
    return body


def _hashes(body: dict[str, Any]) -> _Hashes:
    """Read the four certified digests a formula verdict carries. There is no fifth."""
    names = ("formula_hash", "spec_hash", "plotted_table_hash", "matplotlib_script_hash")
    _require(
        tuple(name for name in body if name.endswith("_hash")) == names,
        "formula verdict did not carry exactly the four certified hashes",
    )
    values = tuple(body[name] for name in names)
    _require(
        all(isinstance(value, str) and value.startswith("sha256:") for value in values),
        "a certified formula hash was missing its sha256 prefix",
    )
    return cast("_Hashes", values)


def _plot_id(body: dict[str, Any]) -> str:
    plot_id = body.get("plot_id")
    _require(isinstance(plot_id, str), "verified formula verdict omitted plot_id")
    return cast("str", plot_id)


def _expect_no_chart(client: TestClient[Litestar], plot_id: str) -> None:
    """A formula replay builds no chart page, so this route stays 404 on both sides of a restart."""
    _expect_problem(client.get(f"/chart/{plot_id}"), _HTTP_NOT_FOUND, _NO_ARTIFACT)


def _certificate(client: TestClient[Litestar], app: Litestar, plot_id: str) -> vcert.VCertV03:
    response = client.get(f"/certificate/{plot_id}")
    _expect_status(response, _HTTP_OK, "formula certificate fetch")
    identity = cast("SigningIdentity", app.state["identity"])
    return attestation.verify_vcert_v03(response.content, identity.trusted_keys).certificate


def _certified_artifact_hashes(certificate: vcert.VCertV03) -> _CertifiedArtifacts:
    """Take the table and script digests from the AUTHENTICATED certificate, never the verdict."""
    artifact = certificate.artifact
    _require(
        isinstance(artifact, vcert.MatplotlibScriptArtifactCert),
        "the formula certificate did not carry a matplotlib-script artifact",
    )
    return (
        certificate.plotted_table_hash,
        cast("vcert.MatplotlibScriptArtifactCert", artifact).matplotlib_script_hash,
    )


def _check_exact_replay(client: TestClient[Litestar], plot_id: str) -> None:
    """Replay reports the recomputation only: no artifact bytes and no signature are reproduced."""
    response = client.get(f"/replay/{plot_id}")
    _expect_status(response, _HTTP_OK, "post-restart formula replay")
    body = _response_object(response, "post-restart formula replay")
    _require(body.get("status") == "exact", "post-restart formula replay was not exact")
    _require(body.get("integrity_ok") is True, "post-restart formula integrity failed")
    _require(
        body.get("artifact_matches") == _ARTIFACT_MATCHES,
        "formula replay artifact matches drifted",
    )
    _require(body.get("payload_match") is True, "replayed VCert payload did not re-encode equal")
    _require(body.get("version_match") is True, "formula replay reported a TCB version mismatch")
    _require(body.get("drift") == [], "formula replay reported live TCB drift")
    _require(body.get("exact") is True, "formula replay did not recompute exactly")


def _check_archived_artifacts(
    client: TestClient[Litestar], plot_id: str, certified: _CertifiedArtifacts
) -> None:
    """Each route serves the exact archived bytes the AUTHENTICATED certificate binds.

    The comparison authority is the fetched VCert v0.3, never the POST verdict, whose digest
    fields carry no signature. The digests are domain-tagged, so a raw ``sha256`` of the body
    would fail on correct bytes.
    """
    table_hash, script_hash = certified
    table = client.get(f"/table/{plot_id}")
    _expect_status(table, _HTTP_OK, "post-restart plotted table")
    _require(canon.hash_table_bytes(table.content) == table_hash, "archived table bytes drifted")
    script = client.get(f"/script/{plot_id}")
    _expect_status(script, _HTTP_OK, "post-restart matplotlib script")
    _require(
        canon.hash_matplotlib_script(script.content) == script_hash,
        "archived matplotlib script bytes drifted",
    )


def _check_restart_retrieval(settings: Settings, plot_id: str, hashes: _Hashes) -> None:
    """Drive a NEW app instance over the SAME state directory the first instance wrote.

    The chain closes here: the restarted instance authenticates the certificate, that certificate
    settles the two artifact digests, and the archived bytes are matched against those. The POST
    verdict's own digest fields are checked to AGREE with the authenticated ones rather than
    standing in for them.
    """
    app = create_app(settings)
    with TestClient(app=app) as restarted:
        _expect_no_chart(restarted, plot_id)
        _check_exact_replay(restarted, plot_id)
        certified = _certified_artifact_hashes(_certificate(restarted, app, plot_id))
        _require(
            certified == hashes[2:],
            "the verdict's artifact digests disagreed with the authenticated certificate",
        )
        _check_archived_artifacts(restarted, plot_id, certified)
        _expect_no_chart(restarted, plot_id)


def _empty_state(tmp_path: Path, name: str) -> Settings:
    state_dir = tmp_path / name
    _require(not state_dir.exists(), "the scenario state directory was not empty at the start")
    return Settings(data_dir=_DATA, state_dir=state_dir)


def _verified_attempt(
    settings: Settings, body: dict[str, Any], route: AttemptRoute
) -> AttemptBundle:
    attempt = _read_attempt(settings, _attempt_id(body))
    _require(attempt.manifest.route is route, "archived occurrence recorded the wrong route")
    _require(
        attempt.manifest.outcome is AttemptOutcome.VERIFIED,
        "archived occurrence did not record a verified outcome",
    )
    return attempt


def _scenario_formula_direct_flow(tmp_path: Path) -> str:
    settings = _empty_state(tmp_path, "direct-state")
    with TestClient(app=create_app(settings)) as client:
        body = _verify_formula(client, _FORMULA_SPEC.read_bytes())
        plot_id = _plot_id(body)
        hashes = _hashes(body)
        _expect_no_chart(client, plot_id)

    _check_restart_retrieval(settings, plot_id, hashes)
    _verified_attempt(settings, body, AttemptRoute.VERIFY_FORMULA)
    return "direct formula verify, restart, exact replay, certificate-matched table and script"


def _scenario_formula_proposed_flow(tmp_path: Path) -> str:
    reply = _FORMULA_SPEC.read_bytes()
    settings = _empty_state(tmp_path, "proposed-state")
    request = msgspec.json.encode({"user_request": _USER_REQUEST})

    with (
        patch.object(model_client, "_build_async_client", _model_client_builder(reply)),
        TestClient(app=create_app(settings)) as client,
    ):
        response = client.post("/propose-formula", content=request, headers=_JSON)
        _expect_status(response, _HTTP_OK, "stubbed formula proposal")
        result = _response_object(response, "stubbed formula proposal")
        _require(result.get("model_reply") == reply.decode(), "model reply was not preserved")
        body = _object(result.get("verdict"), "stubbed formula proposal verdict")
        _require(body.get("verified") is True, "the stubbed formula proposal did not verify")
        plot_id = _plot_id(body)
        hashes = _hashes(body)
        _expect_no_chart(client, plot_id)

    _check_restart_retrieval(settings, plot_id, hashes)
    attempt = _verified_attempt(settings, body, AttemptRoute.PROPOSE_FORMULA)
    _require(attempt.artifacts.model_reply == reply, "archived model reply drifted")
    return "stubbed formula proposal verified, archived, and replayed exactly after a restart"


def _scenario_formula_certificate_check_shape(tmp_path: Path) -> str:
    settings = _empty_state(tmp_path, "certificate-state")
    app = create_app(settings)
    with TestClient(app=app) as client:
        body = _verify_formula(client, _FORMULA_SPEC.read_bytes())
        certificate = _certificate(client, app, _plot_id(body))

    triples = {(check.id, check.method, check.status) for check in certificate.checks}
    _require(
        len(certificate.checks) == _CERTIFIED_CHECK_COUNT == len(triples),
        f"fetched formula VCert carried {len(certificate.checks)} checks "
        f"({len(triples)} distinct), not {_CERTIFIED_CHECK_COUNT}",
    )
    _require(
        {method for _check_id, method, _status in triples} == _CERTIFIED_METHODS,
        "fetched formula VCert method labels drifted",
    )
    _require(
        all(check_id and status == "pass" for check_id, _method, status in triples),
        "fetched formula VCert carried an empty check id or a non-passing status",
    )
    return (
        f"fetched VCert v0.3 exposed {_CERTIFIED_CHECK_COUNT} distinct non-empty "
        "{id, method, status} triples across three methods"
    )


def _rejected_formula_attempt(client: TestClient[Litestar]) -> dict[str, Any]:
    """A malformed body is refused at the decode layer, yet the occurrence still archives."""
    response = client.post("/verify-formula", content=_MALFORMED_SPEC, headers=_JSON)
    _expect_status(response, _HTTP_OK, "malformed formula spec")
    body = _response_object(response, "malformed formula spec")
    # The plot keys are OMITTED, not nulled, so membership is the check a null cannot satisfy.
    _require(set(body) == _REJECTED_VERDICT_KEYS, "the rejected formula verdict shape drifted")
    _require(body.get("verified") is False, "the malformed formula spec unexpectedly verified")
    _require(body.get("layer") == "decode", "the malformed formula spec failed outside decode")
    result = _object_list(body.get("results"), "rejected formula results")[0]
    _require(_result_triple(result) == _REJECTED_RESULT, "the rejected formula result drifted")
    _require(result.get("message"), "the rejected formula result carried no reason")
    return body


def _result_triple(result: dict[str, Any]) -> tuple[str, str, str]:
    return (
        cast("str", result.get("check")),
        cast("str", result.get("method")),
        cast("str", result.get("severity")),
    )


def _audit_artifacts(output: str, context: str) -> list[dict[str, Any]]:
    """Read one audit arm's carriers, checking the roles it disclosed and the ones it must not."""
    document = _object(json.loads(output), context)
    _require(document.get("plot") is None, f"{context} audited a plot for a rejected occurrence")
    attempt = _object(document.get("attempt"), f"{context} attempt")
    _require(attempt.get("id"), f"{context} omitted the attempt id")
    artifacts = _object_list(attempt.get("artifacts"), f"{context} artifacts")
    roles = tuple(cast("str", item.get("role")) for item in artifacts)
    _require(roles == _FORMULA_AUDIT_ROLES, f"{context} carriers drifted")
    _require(
        not set(roles) & _DATASET_AUDIT_ROLES,
        f"{context} disclosed a dataset carrier on a formula occurrence",
    )
    # Carriers are named in `role` values, so no slot could hold a dataset carrier as JSON null.
    _require(
        not [name for name in _DATASET_AUDIT_ROLES if name in output],
        f"{context} named a dataset carrier in its emitted bytes",
    )
    return artifacts


def _revealed_verdict(output: str, context: str) -> dict[str, Any]:
    """Decode the verdict the revealed arm discloses, so it can be compared with the POST."""
    artifacts = _audit_artifacts(output, context)
    verdict = next(item for item in artifacts if item.get("role") == "verdict")
    content = _object(verdict.get("content"), f"{context} verdict content")
    _require(content.get("encoding") == "utf-8", f"{context} verdict encoding drifted")
    return _object(json.loads(cast("str", content["value"])), f"{context} verdict")


def _scenario_formula_failed_attempt_audit_cli(tmp_path: Path) -> str:
    """A rejected formula occurrence survives a restart and the REAL audit CLI explains it."""
    settings = _empty_state(tmp_path, "audit-state")
    with TestClient(app=create_app(settings)) as client:
        verified = _verify_formula(client, _FORMULA_SPEC.read_bytes())
        rejected = _rejected_formula_attempt(client)

    failure_reason = _object_list(rejected["results"], "rejected formula results")[0]["message"]
    rejected_id = _attempt_id(rejected)
    _require(rejected_id != _attempt_id(verified), "the two formula attempts shared an id")
    attempt = _read_attempt(settings, rejected_id)
    _require(
        attempt.manifest.route is AttemptRoute.VERIFY_FORMULA,
        "the rejected occurrence recorded the wrong route",
    )
    _require(
        attempt.manifest.outcome is AttemptOutcome.REJECTED,
        "the rejected occurrence did not record a rejection",
    )

    # The audit must read a DURABLE archive, so the first app is closed and a new one is built
    # over the same state directory before the CLI runs.
    with TestClient(app=create_app(settings)) as restarted:
        _expect_status(
            restarted.get(f"/certificate/{_plot_id(verified)}"),
            _HTTP_OK,
            "post-restart formula certificate",
        )

    default_code, default_output = _run_audit_cli(settings, ("audit", rejected_id))
    _require(default_code == 0, "the default formula audit CLI failed")
    _require('"content"' not in default_output, "the default formula audit disclosed content")
    default_document = _object(json.loads(default_output), "default formula audit")
    _require(
        default_document.get("disclosure") == "redacted",
        "the default formula audit was not redacted",
    )
    audited = _object(default_document.get("attempt"), "default formula audit attempt")
    _require(audited.get("id") == rejected_id, "the default formula audit read the wrong attempt")
    _audit_artifacts(default_output, "default formula audit")

    reveal_code, reveal_output = _run_audit_cli(
        settings,
        ("audit", rejected_id, "--reveal-sensitive"),
    )
    _require(reveal_code == 0, "the revealed formula audit CLI failed")
    _require(
        reveal_output == _run_audit_cli(settings, ("audit", rejected_id, "--reveal-sensitive"))[1],
        "the revealed formula audit was unstable",
    )
    _require(
        len(reveal_output) > len(default_output),
        "revealing sensitive bytes returned no more than the redacted arm",
    )
    _require('"content"' in reveal_output, "the revealed formula audit disclosed no content")

    # Close the loop: the durable verdict must explain the SAME failure the caller was shown.
    verdict = _revealed_verdict(reveal_output, "revealed formula audit")
    audited_result = _object_list(verdict.get("results"), "audited formula results")[0]
    _require(_result_triple(audited_result) == _REJECTED_RESULT, "the audited result drifted")
    _require(audited_result.get("message") == failure_reason, "the audit lost the failure reason")
    return "real audit CLI explained a durable rejected formula attempt, redacted by default"


def _check_formula_rotated_signer_guard(tmp_path: Path) -> None:
    """A signer the caller does not pin cannot certify an archived formula occurrence."""
    state_dir = tmp_path / "rotated-state"
    with TestClient(app=create_app(Settings(data_dir=_DATA, state_dir=state_dir))) as first:
        plot_id = _plot_id(_verify_formula(first, _FORMULA_SPEC.read_bytes()))

    rotated = Settings(
        data_dir=_DATA,
        state_dir=state_dir,
        signing_key_file=state_dir / "rotated.key",
    )
    with TestClient(app=create_app(rotated)) as client:
        replay = client.get(f"/replay/{plot_id}")
        _expect_status(replay, _HTTP_OK, "rotated-key formula replay")
        body = _response_object(replay, "rotated-key formula replay")
        _require(body.get("status") == "untrusted_key", "a rotated unpinned key was trusted")
        _require(body.get("integrity_ok") is False, "an untrusted key claimed formula integrity")
        _require(body.get("exact") is False, "an untrusted key claimed an exact formula replay")
        _require(
            body.get("failure_stage") == "trust", "the untrusted-key failure left the trust stage"
        )
        _require(
            body.get("artifact_matches") == _UNMATCHED_ARTIFACTS,
            "the untrusted-key verdict was not formula-shaped",
        )


def _check_formula_schema_corruption_guard(tmp_path: Path) -> None:
    """Damaged archive schema answers a generic 500 and names neither object nor cause."""
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "schema-state"))
    archive = cast("Archive", app.state["archive"])
    handler = _ListHandler()
    logger = logging.getLogger("verifier.service.app")
    propagate = logger.propagate

    with TestClient(app=app) as client:
        plot_id = _plot_id(_verify_formula(client, _FORMULA_SPEC.read_bytes()))
        with closing(sqlite3.connect(archive.database_path)) as connection:
            connection.execute(f"DROP INDEX {_DAMAGED_INDEX}")
            connection.commit()

        # The outer runner disables logging, so the capture window re-enables it and restores
        # every mutated logging control. Capturing without this yields an empty record list.
        logger.addHandler(handler)
        logger.propagate = False
        previous_disable = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        try:
            with patch.object(logging.getLogger("httpx"), "disabled", new=True):
                response = client.get(f"/replay/{plot_id}")
        finally:
            logging.disable(previous_disable)
            logger.propagate = propagate
            logger.removeHandler(handler)

    _expect_problem(
        response, _HTTP_INTERNAL_SERVER_ERROR, "the verifier encountered an internal error"
    )
    _require(_DAMAGED_INDEX not in response.text, "the damaged index leaked through HTTP")
    _require(bool(handler.records), "formula schema corruption was not logged")
    record = handler.records[-1]
    _require(record.levelno == logging.ERROR, "formula schema corruption did not log at ERROR")
    _require(record.exc_info is not None, "the schema corruption log omitted exception info")
    cause = cast("tuple[type[BaseException], BaseException, object]", record.exc_info)[1]
    _require(isinstance(cause, ArchiveSchemaError), "the logged schema cause had the wrong type")
    _require(str(cause) not in response.text, "the schema cause leaked through the problem body")


def _check_formula_attempt_signature_guard(tmp_path: Path) -> None:
    """A tampered DSSE signature is refused, and the target archive stays empty."""
    source_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "signature-source")
    with TestClient(app=create_app(source_settings)) as client:
        body = _verify_formula(client, _FORMULA_SPEC.read_bytes())
    bundle = _read_attempt(source_settings, _attempt_id(body))

    index = bundle.attempt_envelope.index(_SIGNATURE_MARKER) + len(_SIGNATURE_MARKER)
    original_byte = bundle.attempt_envelope[index : index + 1]
    replacement_byte = b"A" if original_byte != b"A" else b"B"
    tampered_envelope = (
        bundle.attempt_envelope[:index] + replacement_byte + bundle.attempt_envelope[index + 1 :]
    )
    # An occurrence address is a raw digest of the envelope, NOT a domain-tagged artifact digest,
    # so hashing the bytes directly is correct here and only here.
    tampered = replace(
        bundle,
        attempt_id=hashlib.sha256(tampered_envelope).hexdigest(),
        attempt_envelope=tampered_envelope,
    )

    target_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "signature-target")
    target = open_archive(target_settings)
    try:
        target.publish_attempt(tampered, limits=target_settings.limits)
    except ArchiveIntegrityError:
        pass
    else:
        detail = "a tampered formula attempt signature was published"
        raise DemoError(detail)
    _require(
        target.stats() == ArchiveStats(0, 0, 0, 0, 0),
        "the refused publication mutated the target archive",
    )


def _scenario_formula_archive_integrity_guards(tmp_path: Path) -> str:
    """Aggregate three guards. The first failure stops the rest, so the tests own the diagnosis."""
    _check_formula_rotated_signer_guard(tmp_path)
    _check_formula_schema_corruption_guard(tmp_path)
    _check_formula_attempt_signature_guard(tmp_path)
    return "rotated signer, schema damage, and formula signature tampering all failed closed"


_FORMULA_SCENARIOS: tuple[tuple[str, Scenario], ...] = (
    ("formula direct flow", _scenario_formula_direct_flow),
    ("formula proposed flow", _scenario_formula_proposed_flow),
    ("formula certificate check shape", _scenario_formula_certificate_check_shape),
    ("formula failed attempt audit cli", _scenario_formula_failed_attempt_audit_cli),
    ("formula archive integrity guards", _scenario_formula_archive_integrity_guards),
)


def run_formula_walkthrough() -> WalkthroughReport:
    """Run every scenario independently and retain failures instead of aborting the walkthrough."""
    results: list[ScenarioResult] = []
    for name, scenario in _FORMULA_SCENARIOS:
        logging.disable(logging.CRITICAL)
        try:
            with TemporaryDirectory(prefix="figure-verification-formula-") as temp_dir:
                detail = scenario(Path(temp_dir))
        except Exception as exc:  # one failed scenario must never suppress the remaining evidence
            result = ScenarioResult(name=name, status="FAIL", detail=f"{type(exc).__name__}: {exc}")
        else:
            result = ScenarioResult(name=name, status="PASS", detail=detail)
        finally:
            logging.disable(logging.NOTSET)
        results.append(result)
        _LOGGER.info("%s %s: %s", result.status, result.name, result.detail)

    passed = sum(result.status == "PASS" for result in results)
    failed = len(results) - passed
    status: ScenarioStatus = "PASS" if failed == 0 else "FAIL"
    return WalkthroughReport(
        generated_at=datetime.now(tz=UTC).isoformat(),
        status=status,
        passed=passed,
        failed=failed,
        total=len(results),
        results=tuple(results),
    )


def _configure_logging() -> None:
    """Keep the walkthrough readable even when Litestar configures process-wide logging."""
    logging.basicConfig(level=logging.CRITICAL, force=True)
    formatter = logging.Formatter("%(levelname)s %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    _LOGGER.handlers.clear()
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False


def main() -> int:
    """Run all formula scenarios, write the JSON report, and fail if any scenario failed."""
    _configure_logging()
    report = run_formula_walkthrough()
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_bytes(encode_report(report))
    _LOGGER.info("wrote report=%s", _REPORT_PATH.relative_to(_ROOT))
    _LOGGER.info("formula walkthrough: %d/%d scenarios PASS", report.passed, report.total)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
