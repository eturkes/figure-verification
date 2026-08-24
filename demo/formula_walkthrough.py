# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Self-contained formula-mode capstone used by ``python -m demo.formula_walkthrough``.

Each scenario owns a temporary service state directory, drives the Litestar app in process, and
joins one full formula chain: an empty state directory, a verified occurrence, a restart onto a
NEW app instance over that SAME directory, and the archived retrieval routes. No socket, model,
accelerator, or external service is used; the one model arm drives a deterministic stub.

The mode-neutral scenario frame is imported from ``demo.walkthrough`` rather than re-authored, so
both capstones report through one shape. The formula claim boundary is unmoved here: the verifier
owns every plotted point and AUTHORS the matplotlib script bytes, and this walkthrough never
executes them. ``/chart`` therefore stays 404 in formula mode, and ``/table`` plus ``/script``
serve typed-relation, digest-addressed bytes that are not certificate-graph authenticated.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import patch

import msgspec
from litestar import Litestar
from litestar.testing import TestClient

from demo.walkthrough import (
    _HTTP_NOT_FOUND,
    _HTTP_OK,
    _JSON,
    _ROOT,
    Scenario,
    ScenarioResult,
    ScenarioStatus,
    WalkthroughReport,
    _attempt_id,
    _expect_problem,
    _expect_status,
    _model_client_builder,
    _object,
    _read_attempt,
    _require,
    _response_object,
    encode_report,
)
from verifier import attestation, canon, vcert
from verifier.service import model_client
from verifier.service.app import create_app
from verifier.service.archive import AttemptBundle, AttemptOutcome, AttemptRoute
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
_ARTIFACT_MATCHES = {
    "formula": True,
    "spec": True,
    "plotted_table": True,
    "matplotlib_script": True,
}

type _Hashes = tuple[str, str, str, str]


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


def _check_archived_artifacts(client: TestClient[Litestar], plot_id: str, hashes: _Hashes) -> None:
    """Each route serves the exact archived bytes whose certified digest the verdict published."""
    _, _, table_hash, script_hash = hashes
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
    """Drive a NEW app instance over the SAME state directory the first instance wrote."""
    with TestClient(app=create_app(settings)) as restarted:
        _expect_no_chart(restarted, plot_id)
        _check_exact_replay(restarted, plot_id)
        _check_archived_artifacts(restarted, plot_id, hashes)
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
    return "direct formula verify, restart, exact replay, and digest-matched table and script"


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
    _require(bool(triples), "fetched formula VCert carried no checks")
    _require(
        {method for _check_id, method, _status in triples} == _CERTIFIED_METHODS,
        "fetched formula VCert method labels drifted",
    )
    _require(
        all(check_id and status == "pass" for check_id, _method, status in triples),
        "fetched formula VCert carried an empty check id or a non-passing status",
    )
    return "fetched VCert v0.3 exposed non-empty {id, method, status} triples across three methods"


_FORMULA_SCENARIOS: tuple[tuple[str, Scenario], ...] = (
    ("formula direct flow", _scenario_formula_direct_flow),
    ("formula proposed flow", _scenario_formula_proposed_flow),
    ("formula certificate check shape", _scenario_formula_certificate_check_shape),
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
