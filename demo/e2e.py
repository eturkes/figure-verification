# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic real-socket three-case verifier demo: ``python -m demo.e2e``.

The driver always owns a disposable verifier service, talks to it only over loopback TCP, and uses
no model backend, Open WebUI instance, or accelerator for its three deterministic cases. Optional
flags add observations against a separately running production stack without weakening those cases.
"""

import argparse
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, BinaryIO, NoReturn, cast
from urllib.parse import urlsplit

import httpx
import msgspec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from demo.walkthrough import (
    DemoError,
    ScenarioResult,
    ScenarioStatus,
    WalkthroughReport,
    _attempt_id,
    _expect_status,
    _object,
    _object_list,
    _require,
    _response_object,
    encode_report,
)
from verifier import attestation
from webui.client import WebUIClient, WebUIProvisionError
from webui.settings import Settings as WebUISettings

_LOGGER = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD_SPEC = _ROOT / "examples" / "good_specs" / "g01_total_revenue_by_month.json"
_BAD_FIELD_SPEC = _ROOT / "examples" / "bad_specs" / "b07_nonexistent_field.json"
_MISSING_UNIT_SPEC = _ROOT / "examples" / "bad_specs" / "b13_missing_y_unit.json"
_REPORT_PATH = _ROOT / "demo" / "reports" / "e2e_report.json"
_JSON = {"content-type": "application/json"}
_HTTP_OK = 200
_STARTUP_DEADLINE_S = 20.0
_POLL_INTERVAL_S = 0.1
_REQUEST_TIMEOUT_S = 20.0
_SHUTDOWN_TIMEOUT_S = 10.0
_HASH_FIELDS = (
    "dataset_hash",
    "spec_hash",
    "plotted_table_hash",
    "manifest_hash",
    "vega_lite_hash",
)
_B07_REASON = "field 'profit' does not exist in the table"
_B13_REASON = "quantitative channel 'aqi' traces to manifest column 'aqi', which declares no unit"
_DEFAULT_VERIFIER_URL = "http://127.0.0.1:8000"
_WEBUI_PROMPT = "Show total revenue by month."
_MODEL_PROMPTS = (
    (_WEBUI_PROMPT, "sales.csv"),
    ("Show profit by month.", "sales.csv"),
    ("Show revenue by month as bar chart but exaggerate differences.", "sales.csv"),
)
_ATTEMPT_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_AUDIT_TIMEOUT_S = 20.0
# Live NPU greedy decode per propose can take many seconds (cold-shape recompile plus
# per-token latency), far exceeding the hardware-free hang-guard used for local GETs.
_MODEL_REQUEST_TIMEOUT_S = 180.0


class CertInfo(msgspec.Struct, frozen=True, kw_only=True):
    """Authenticated certificate identity and its five artifact hashes."""

    verified: bool
    keyid: str
    hashes: dict[str, str]


class WebuiObservation(msgspec.Struct, frozen=True, kw_only=True):
    """One persisted Open WebUI chat and its optional certified chart."""

    status: ScenarioStatus
    prompt: str
    final_text: str | None
    chart_url: str | None
    certificate: CertInfo | None
    detail: str


class ModelPromptObservation(msgspec.Struct, frozen=True, kw_only=True):
    """One live proposer prompt's public verifier outcome."""

    prompt: str
    dataset_name: str
    http_status: int
    verified: bool
    failing_check: str | None
    reason: str | None
    attempt_id: str | None
    detail: str


class ModelObservation(msgspec.Struct, frozen=True, kw_only=True):
    """The three seed prompts plus one privacy-preserving attempt audit."""

    status: ScenarioStatus
    prompts: tuple[ModelPromptObservation, ...]
    audited_attempt_id: str | None
    audit_ok: bool | None
    detail: str


class E2EReport(msgspec.Struct, frozen=True, kw_only=True):
    """Deterministic case report extended only when an observation leg is enabled."""

    generated_at: str
    status: ScenarioStatus
    passed: int
    failed: int
    total: int
    results: tuple[ScenarioResult, ...]
    webui: WebuiObservation | None = None
    model: ModelObservation | None = None


class _VerifierService:
    """Own one verifier subprocess and restart it against the same disposable state directory."""

    def __init__(self, *, state_dir: Path, work_dir: Path) -> None:
        self._state_dir = state_dir
        self._work_dir = work_dir
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_file: BinaryIO | None = None
        self._stderr_paths: list[Path] = []
        self._base_url: str | None = None
        self._launches = 0

    @property
    def base_url(self) -> str:
        """Return the current socket origin, failing explicitly when no child is running."""
        _require(self._base_url is not None, "verifier service is not running")
        return cast("str", self._base_url)

    def start(self) -> None:
        """Launch a fresh child on a fresh loopback port and wait for its health endpoint."""
        _require(self._proc is None, "verifier service was already running")
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        self._launches += 1
        stderr_path = self._work_dir / f"verifier-{self._launches}.stderr"
        stderr_file = stderr_path.open("wb")
        env = {
            **os.environ,
            "VERIFIER_DATA_DIR": str(_DATA),
            "VERIFIER_HOST": "127.0.0.1",
            "VERIFIER_PORT": str(port),
            "VERIFIER_STATE_DIR": str(self._state_dir),
            "VERIFIER_WORK_RATE_PER_MINUTE": "1000",
            "VERIFIER_WORK_BURST": "1000",
        }
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "verifier.service"],
                env=env,
                cwd=self._work_dir,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
            )
        except OSError as exc:
            stderr_file.close()
            msg = "could not launch verifier service"
            raise DemoError(msg) from exc

        self._proc = proc
        self._stderr_file = stderr_file
        self._stderr_paths.append(stderr_path)
        self._base_url = base_url
        try:
            _wait_for_health(base_url, proc, stderr_path)
        except DemoError:
            self.stop()
            raise

    def stop(self) -> None:
        """Terminate the current child, escalating to kill after a bounded wait."""
        proc = self._proc
        stderr_file = self._stderr_file
        self._proc = None
        self._stderr_file = None
        self._base_url = None
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)
            else:
                proc.wait()
        if stderr_file is not None:
            stderr_file.close()

    def restart(self) -> None:
        """Replace the child while retaining the same durable state directory."""
        self.stop()
        self.start()

    def diagnostics(self) -> str:
        """Return every child stderr capture for failure diagnosis."""
        captures = [
            path.read_text(encoding="utf-8", errors="replace") for path in self._stderr_paths
        ]
        return "\n".join(captures).strip()


type Case = Callable[[_VerifierService], str]


def _free_port() -> int:
    """Reserve then release an ephemeral IPv4 loopback port for the next service launch."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fail_with_stderr(message: str, stderr_path: Path) -> NoReturn:
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    detail = f"{message}\n--- verifier stderr ---\n{stderr}"
    raise DemoError(detail)


def _wait_for_health(base_url: str, proc: subprocess.Popen[bytes], stderr_path: Path) -> None:
    """Poll health until 200, failing fast if the child exits before binding."""
    deadline = time.monotonic() + _STARTUP_DEADLINE_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            message = f"verifier exited early with code {proc.returncode}"
            _fail_with_stderr(message, stderr_path)
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
        except httpx.TransportError:
            time.sleep(_POLL_INTERVAL_S)
            continue
        if response.status_code == _HTTP_OK:
            return
        time.sleep(_POLL_INTERVAL_S)
    message = "verifier did not become healthy before the deadline"
    _fail_with_stderr(message, stderr_path)


def _get(
    service: _VerifierService, path: str, *, timeout: float = _REQUEST_TIMEOUT_S
) -> httpx.Response:
    try:
        return httpx.get(f"{service.base_url}{path}", timeout=timeout)
    except httpx.HTTPError as exc:
        msg = f"GET {path} failed: {exc}"
        raise DemoError(msg) from exc


def _post_spec(
    service: _VerifierService,
    path: str,
    spec: bytes,
    *,
    context: str,
    timeout: float = _REQUEST_TIMEOUT_S,
) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{service.base_url}{path}",
            content=spec,
            headers=_JSON,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        msg = f"POST {path} failed: {exc}"
        raise DemoError(msg) from exc
    _expect_status(response, _HTTP_OK, context)
    return _response_object(response, f"{context} response")


def _string_field(body: dict[str, Any], field: str, context: str) -> str:
    value = body.get(field)
    _require(isinstance(value, str), f"{context} {field} was missing or non-string")
    return cast("str", value)


def _failed_result_message(body: dict[str, Any], check: str, context: str) -> str:
    results = _object_list(body.get("results"), f"{context} results")
    matches = [
        result
        for result in results
        if result.get("check") == check and result.get("status") == "fail"
    ]
    _require(len(matches) == 1, f"{context} did not contain one failing {check} result")
    message = matches[0].get("message")
    _require(isinstance(message, str), f"{context} {check} message was missing or non-string")
    return cast("str", message)


def _assert_chart(service: _VerifierService, plot_id: str, context: str) -> None:
    response = _get(service, f"/chart/{plot_id}")
    _expect_status(response, _HTTP_OK, context)
    _require(
        response.headers.get("content-type", "").startswith("text/html"),
        f"{context} did not return text/html",
    )
    _require(
        response.headers.get("content-security-policy") == "sandbox allow-scripts",
        f"{context} sandbox policy drifted",
    )
    _require(plot_id in response.text, f"{context} did not bind the requested plot_id")


def _origin_get(origin: str, path: str, *, timeout: float = _REQUEST_TIMEOUT_S) -> httpx.Response:
    try:
        return httpx.get(f"{origin}{path}", timeout=timeout)
    except httpx.HTTPError as exc:
        msg = f"GET {path} failed: {exc}"
        raise DemoError(msg) from exc


def _fetch_and_verify_certificate(
    origin: str,
    plot_id: str,
    *,
    check_lines_out: list[str] | None = None,
) -> CertInfo:
    """Fetch one DSSE certificate and advertised key, then authenticate the VCert."""
    response = _origin_get(origin, f"/certificate/{plot_id}")
    _expect_status(response, _HTTP_OK, "certificate fetch")
    try:
        envelope = _response_object(response, "certificate DSSE envelope")
    except (ValueError, RecursionError) as exc:
        msg = "certificate endpoint did not return a JSON object"
        raise DemoError(msg) from exc
    _require(
        envelope.get("payloadType") == attestation.VCERT_PAYLOAD_TYPE,
        "certificate DSSE payload type drifted",
    )
    signatures = _object_list(envelope.get("signatures"), "certificate signatures")
    _require(len(signatures) == 1, "certificate did not carry exactly one signature")
    keyid_value = signatures[0].get("keyid")
    _require(isinstance(keyid_value, str) and keyid_value, "certificate keyid was missing")
    keyid = cast("str", keyid_value)

    key_response = _origin_get(origin, f"/key/{keyid}")
    _expect_status(key_response, _HTTP_OK, "public-key fetch")
    _require(
        key_response.headers.get("content-type", "").startswith("application/octet-stream"),
        "public-key endpoint did not return application/octet-stream",
    )
    try:
        public_key = Ed25519PublicKey.from_public_bytes(key_response.content)
    except ValueError as exc:
        msg = "public-key endpoint did not return one raw Ed25519 key"
        raise DemoError(msg) from exc
    try:
        verified = attestation.verify_vcert(
            response.content,
            {keyid: public_key},
            require_canonical_envelope=True,
            expected_keyid_hint=keyid,
        )
    except attestation.AttestationError as exc:
        msg = "certificate did not verify under the server-advertised key"
        raise DemoError(msg) from exc

    certificate = verified.certificate
    _require(certificate.version == "vcert-0.2", "certificate version drifted")
    hashes = {
        "dataset_hash": certificate.dataset_hash,
        "spec_hash": certificate.spec_hash,
        "plotted_table_hash": certificate.plotted_table_hash,
        "manifest_hash": certificate.manifest_hash,
        "vega_lite_hash": certificate.vega_lite_hash,
    }
    check_lines = tuple(f"{check.id} | {check.method}" for check in certificate.checks)
    _require(
        "scale.bar_zero | z3_smt" in check_lines,
        "certificate lost the scale.bar_zero SMT obligation",
    )
    _require(
        "sort.canonical_order | z3_smt" in check_lines,
        "certificate lost the sort.canonical_order SMT obligation",
    )
    if check_lines_out is not None:
        check_lines_out.extend(check_lines)
    return CertInfo(verified=True, keyid=keyid, hashes=hashes)


def _verify_certificate(
    service: _VerifierService, plot_id: str, rendered: dict[str, Any]
) -> tuple[dict[str, str], tuple[str, ...], str]:
    check_lines_buffer: list[str] = []
    certificate = _fetch_and_verify_certificate(
        service.base_url,
        plot_id,
        check_lines_out=check_lines_buffer,
    )
    hashes = certificate.hashes
    for field, value in hashes.items():
        _require(rendered.get(field) == value, f"certificate {field} did not match the render")
        _LOGGER.info("  %s=%s", field, value)

    check_lines = tuple(check_lines_buffer)
    _LOGGER.info("  certificate checks:")
    for line in check_lines:
        _LOGGER.info("    %s", line)
    _LOGGER.info(
        "  signature verified: holder of server-advertised key %s (no external PKI claim)",
        certificate.keyid,
    )
    return hashes, check_lines, certificate.keyid


def _case_g01_verified(service: _VerifierService) -> str:
    _LOGGER.info("CASE 1 g01 -> VERIFIED + certificate + restart/replay")
    rendered = _post_spec(
        service,
        "/verify-and-render",
        _GOOD_SPEC.read_bytes(),
        context="g01 verify-and-render",
    )
    _require(rendered.get("verified") is True, "g01 did not verify")
    _require(rendered.get("layer") == "verify", "g01 did not reach the verify layer")
    _attempt_id(rendered)
    plot_id = _string_field(rendered, "plot_id", "g01 render")
    spec_id = _string_field(rendered, "spec_id", "g01 render")
    _LOGGER.info("  verified plot_id=%s spec_id=%s", plot_id, spec_id)

    hashes, check_lines, keyid = _verify_certificate(service, plot_id, rendered)
    _assert_chart(service, plot_id, "g01 chart")
    _LOGGER.info("  chart served under CSP sandbox allow-scripts")

    service.restart()
    replay_response = _get(service, f"/replay/{plot_id}")
    _expect_status(replay_response, _HTTP_OK, "g01 replay")
    replay = _response_object(replay_response, "g01 replay response")
    _require(replay.get("status") == "exact", "g01 replay was not exact")
    _require(replay.get("exact") is True, "g01 replay exact flag was not true")
    _assert_chart(service, plot_id, "g01 replayed chart")
    _LOGGER.info("  replay: exact; chart repopulated")

    hash_detail = "; ".join(f"{field}={hashes[field]}" for field in _HASH_FIELDS)
    checks_detail = ", ".join(check_lines)
    return (
        f"verified plot_id={plot_id}; spec_id={spec_id}; {hash_detail}; "
        f"certificate checks: {checks_detail}; signature verified against advertised key "
        f"{keyid}; replay: exact; chart repopulated"
    )


def _case_b07_blocked(service: _VerifierService) -> str:
    _LOGGER.info("CASE 2 b07 -> BLOCKED nonexistent field")
    verdict = _post_spec(
        service,
        "/verify-only",
        _BAD_FIELD_SPEC.read_bytes(),
        context="b07 verify-only",
    )
    _require(verdict.get("verified") is False, "b07 unexpectedly verified")
    message = _failed_result_message(verdict, "schema.fields_exist", "b07 verdict")
    _require(message == _B07_REASON, "b07 failure reason drifted")
    _LOGGER.info("  schema.fields_exist: %s", message)
    return f"blocked; schema.fields_exist: {message}"


def _case_b13_and_scale_blocked(service: _VerifierService) -> str:
    _LOGGER.info("CASE 3 b13 -> BLOCKED; scale.zero=false -> UNREPRESENTABLE")
    verdict = _post_spec(
        service,
        "/verify-only",
        _MISSING_UNIT_SPEC.read_bytes(),
        context="b13 verify-only",
    )
    _require(verdict.get("verified") is False, "b13 unexpectedly verified")
    unit_message = _failed_result_message(
        verdict,
        "label.quantitative_units_present",
        "b13 verdict",
    )
    _require(unit_message == _B13_REASON, "b13 failure reason drifted")
    _LOGGER.info("  label.quantitative_units_present: %s", unit_message)

    crafted = _object(json.loads(_GOOD_SPEC.read_bytes()), "g01 source spec")
    encoding = _object(crafted.get("encoding"), "g01 encoding")
    y_channel = _object(encoding.get("y"), "g01 y channel")
    y_channel["scale"] = {"zero": False}
    crafted_bytes = json.dumps(
        crafted,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    decode_verdict = _post_spec(
        service,
        "/verify-only",
        crafted_bytes,
        context="scale.zero=false verify-only",
    )
    _require(
        decode_verdict.get("verified") is False,
        "the unrepresentable scale.zero=false spec unexpectedly verified",
    )
    _require(
        decode_verdict.get("layer") == "decode",
        "scale.zero=false was not refused at the decode layer",
    )
    decode_message = _failed_result_message(
        decode_verdict,
        "spec.decode",
        "scale.zero=false verdict",
    )
    _require("scale" in decode_message.casefold(), "spec.decode reason did not reference scale")
    _LOGGER.info("  spec.decode: %s", decode_message)
    _LOGGER.info(
        "  misleading baseline is unrepresentable and verified charts retain "
        "scale.bar_zero | z3_smt"
    )
    return (
        f"blocked; label.quantitative_units_present: {unit_message}; "
        f"decode-refused spec.decode for scale.zero=false: {decode_message}; "
        "misleading baseline unrepresentable and guarded by scale.bar_zero | z3_smt"
    )


_CASES: tuple[tuple[str, Case], ...] = (
    ("g01_verified_certificate_replay", _case_g01_verified),
    ("b07_nonexistent_field_blocked", _case_b07_blocked),
    ("b13_units_and_scale_guarded", _case_b13_and_scale_blocked),
)


def run_e2e() -> WalkthroughReport:
    """Run all three cases against one owned service, retaining explicit case failures."""
    results: list[ScenarioResult] = []
    with TemporaryDirectory(prefix="figure-verification-e2e-") as temp_dir:
        work_dir = Path(temp_dir)
        service = _VerifierService(state_dir=work_dir / "state", work_dir=work_dir)
        try:
            service.start()
            for name, case in _CASES:
                try:
                    detail = case(service)
                except DemoError as exc:
                    result = ScenarioResult(
                        name=name,
                        status="FAIL",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                    diagnostics = service.diagnostics()
                    if diagnostics:
                        _LOGGER.warning("verifier diagnostics for %s:\n%s", name, diagnostics)
                else:
                    result = ScenarioResult(name=name, status="PASS", detail=detail)
                results.append(result)
                _LOGGER.info("%s %s: %s", result.status, result.name, result.detail)
        finally:
            service.stop()

    passed = sum(result.status == "PASS" for result in results)
    failed = len(results) - passed
    status: ScenarioStatus = "PASS" if failed == 0 else "FAIL"
    return WalkthroughReport(
        generated_at=datetime.now(UTC).isoformat(),
        status=status,
        passed=passed,
        failed=failed,
        total=len(results),
        results=tuple(results),
    )


def _chart_target(chart_url: str) -> tuple[str, str]:
    """Split an exact ``{origin}/chart/{plot_id}`` URL into its certificate target."""
    try:
        parsed = urlsplit(chart_url)
    except ValueError as exc:
        msg = "Open WebUI chart URL was malformed"
        raise DemoError(msg) from exc
    prefix = "/chart/"
    _require(
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.path.startswith(prefix)
        and not parsed.query
        and not parsed.fragment,
        "Open WebUI chart URL did not have the expected origin/chart/plot_id shape",
    )
    plot_id = parsed.path.removeprefix(prefix)
    _require(
        _ATTEMPT_ID_RE.fullmatch(plot_id) is not None,
        "Open WebUI chart URL plot_id was not a SHA-256 hex digest",
    )
    return f"{parsed.scheme}://{parsed.netloc}", plot_id


def _run_webui_leg() -> WebuiObservation:
    """Observe one persisted chat and authenticate its chart certificate when present."""
    final_text: str | None = None
    chart_url: str | None = None
    certificate: CertInfo | None = None
    try:
        settings = WebUISettings.from_env()
        with httpx.Client(
            base_url=settings.base_url,
            timeout=settings.request_timeout,
        ) as http:
            client = WebUIClient(http, settings)
            client.authenticate()
            result = client.run_persisted_chat(_WEBUI_PROMPT)
        final_text = result.final_text
        chart_url = result.chart_url
        if chart_url is not None:
            origin, plot_id = _chart_target(chart_url)
            certificate = _fetch_and_verify_certificate(origin, plot_id)
    except (WebUIProvisionError, httpx.HTTPError, DemoError, ValueError) as exc:
        return WebuiObservation(
            status="FAIL",
            prompt=_WEBUI_PROMPT,
            final_text=final_text,
            chart_url=chart_url,
            certificate=certificate,
            detail=f"{type(exc).__name__}: {exc}",
        )

    detail = (
        "persisted chat completed without a chart"
        if chart_url is None
        else "persisted chat chart certificate verified"
    )
    return WebuiObservation(
        status="PASS",
        prompt=_WEBUI_PROMPT,
        final_text=final_text,
        chart_url=chart_url,
        certificate=certificate,
        detail=detail,
    )


def _response_json(response: httpx.Response, context: str) -> object:
    try:
        return response.json()
    except (ValueError, RecursionError) as exc:
        msg = f"{context} was not valid JSON"
        raise DemoError(msg) from exc


def _propose_once(
    client: httpx.Client,
    verifier_url: str,
    prompt: str,
    dataset: str,
) -> ModelPromptObservation:
    """Post one seed prompt and reduce the public response to operator-safe fields."""
    response = client.post(
        f"{verifier_url}/propose-spec",
        json={"user_request": prompt, "dataset_name": dataset},
    )
    http_status = response.status_code
    payload = _response_json(response, "propose-spec response")
    if http_status == _HTTP_OK:
        if isinstance(payload, list):
            values = cast("list[object]", payload)
            _require(bool(values), "verified propose-spec response was an empty JSON array")
            body = _object(values[0], "verified propose-spec result")
        else:
            body = _object(payload, "propose-spec result")
        verdict = _object(body["verdict"], "propose-spec verdict") if "verdict" in body else body
        results = _object_list(verdict.get("results"), "propose-spec verdict results")
        failed = next((result for result in results if result.get("status") == "fail"), None)
        failing_check_value = None if failed is None else failed.get("check")
        reason_value = None if failed is None else failed.get("message")
        attempt_id_value = verdict.get("attempt_id")
        return ModelPromptObservation(
            prompt=prompt,
            dataset_name=dataset,
            http_status=http_status,
            verified=bool(verdict.get("verified")),
            failing_check=(failing_check_value if isinstance(failing_check_value, str) else None),
            reason=reason_value if isinstance(reason_value, str) else None,
            attempt_id=attempt_id_value if isinstance(attempt_id_value, str) else None,
            detail="",
        )

    problem = _object(payload, "propose-spec problem")
    detail_value = problem.get("detail")
    attempt_id_value = problem.get("attempt_id")
    return ModelPromptObservation(
        prompt=prompt,
        dataset_name=dataset,
        http_status=http_status,
        verified=False,
        failing_check=None,
        reason=None,
        attempt_id=attempt_id_value if isinstance(attempt_id_value, str) else None,
        detail=(
            detail_value
            if isinstance(detail_value, str)
            else f"HTTP {http_status} problem omitted a string detail"
        ),
    )


def _run_audit(attempt_id: str) -> tuple[int, str]:
    """Run the safe-by-default audit CLI for one format-validated attempt id."""
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "verifier.service", "audit", attempt_id],
        capture_output=True,
        text=True,
        check=False,
        timeout=_AUDIT_TIMEOUT_S,
    )
    return completed.returncode, completed.stdout


def _run_model_leg(verifier_url: str) -> ModelObservation:
    """Observe the three seed prompts and audit one blocked attempt without revealing payloads."""
    observations: list[ModelPromptObservation] = []
    audited_attempt_id: str | None = None
    audit_ok: bool | None = None
    try:
        with httpx.Client(timeout=_MODEL_REQUEST_TIMEOUT_S) as client:
            for prompt, dataset in _MODEL_PROMPTS:
                observations.append(_propose_once(client, verifier_url, prompt, dataset))

        audit_target = next(
            (
                observation
                for observation in observations
                if not observation.verified and observation.attempt_id is not None
            ),
            None,
        )
        _require(audit_target is not None, "no blocked proposer outcome had an attempt_id to audit")
        attempt_id_value = cast("ModelPromptObservation", audit_target).attempt_id
        _require(attempt_id_value is not None, "selected audit outcome lost its attempt_id")
        attempt_id = cast("str", attempt_id_value)
        _require(
            _ATTEMPT_ID_RE.fullmatch(attempt_id) is not None,
            "audited attempt_id was not a SHA-256 hex digest",
        )
        audited_attempt_id = attempt_id
        audit_code, _audit_stdout = _run_audit(attempt_id)
        audit_ok = audit_code == 0

        non_ok = sum(item.http_status != _HTTP_OK for item in observations)
        failures: list[str] = []
        if non_ok:
            failures.append(f"{non_ok} prompt(s) returned non-200")
        if not audit_ok:
            failures.append(f"audit exited with code {audit_code}")
        status: ScenarioStatus = "FAIL" if failures else "PASS"
        detail = (
            "; ".join(failures) if failures else "observed 3 prompts; blocked attempt audit passed"
        )
        return ModelObservation(
            status=status,
            prompts=tuple(observations),
            audited_attempt_id=audited_attempt_id,
            audit_ok=audit_ok,
            detail=detail,
        )
    except (httpx.HTTPError, DemoError, OSError, subprocess.SubprocessError) as exc:
        return ModelObservation(
            status="FAIL",
            prompts=tuple(observations),
            audited_attempt_id=audited_attempt_id,
            audit_ok=audit_ok,
            detail=f"{type(exc).__name__}: {exc}",
        )


def _configure_logging() -> None:
    """Keep the socket demo's human-readable narrative on stdout."""
    logging.basicConfig(level=logging.CRITICAL, force=True)
    formatter = logging.Formatter("%(levelname)s %(message)s")
    for logger in (logging.getLogger("demo"), _LOGGER):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-webui", action="store_true")
    parser.add_argument("--with-model", action="store_true")
    parser.add_argument("--verifier-url", default=_DEFAULT_VERIFIER_URL)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run deterministic cases plus any explicitly requested production observations."""
    args = _parse_args(argv)
    with_webui = cast("bool", args.with_webui)
    with_model = cast("bool", args.with_model)
    verifier_url = cast("str", args.verifier_url)
    _configure_logging()
    report = run_e2e()
    if not with_webui and not with_model:
        _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REPORT_PATH.write_bytes(encode_report(report))
        _LOGGER.info("wrote report=%s", _REPORT_PATH.relative_to(_ROOT))
        _LOGGER.info("e2e demo: %d/%d cases PASS", report.passed, report.total)
        return 1 if report.failed else 0

    webui = _run_webui_leg() if with_webui else None
    model = _run_model_leg(verifier_url) if with_model else None
    leg_failed = (webui is not None and webui.status == "FAIL") or (
        model is not None and model.status == "FAIL"
    )
    status: ScenarioStatus = "PASS" if report.failed == 0 and not leg_failed else "FAIL"
    e2e = E2EReport(
        generated_at=report.generated_at,
        status=status,
        passed=report.passed,
        failed=report.failed,
        total=report.total,
        results=report.results,
        webui=webui,
        model=model,
    )
    encoded = msgspec.json.format(msgspec.json.encode(e2e), indent=2) + b"\n"
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_bytes(encoded)
    _LOGGER.info("wrote report=%s", _REPORT_PATH.relative_to(_ROOT))
    if webui is not None:
        _LOGGER.info("webui observation: %s (%s)", webui.status, webui.detail)
    if model is not None:
        _LOGGER.info(
            "model observation: %s; prompts=%d; audit_ok=%s",
            model.status,
            len(model.prompts),
            model.audit_ok,
        )
    _LOGGER.info(
        "e2e demo: %d/%d cases PASS; optional status=%s", report.passed, report.total, status
    )
    return 1 if report.failed or leg_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
