# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic real-socket three-case verifier demo: ``python -m demo.e2e``.

The driver owns a disposable verifier service, talks to it only over loopback TCP, and uses no
model backend, Open WebUI instance, or accelerator. It proves a verified render and authenticated
certificate survive restart/replay, while two intentionally bad specs fail closed for specific
reasons.
"""

import json
import logging
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, BinaryIO, NoReturn, cast

import httpx
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


def _verify_certificate(
    service: _VerifierService, plot_id: str, rendered: dict[str, Any]
) -> tuple[dict[str, str], tuple[str, ...], str]:
    response = _get(service, f"/certificate/{plot_id}")
    _expect_status(response, _HTTP_OK, "certificate fetch")
    envelope = _response_object(response, "certificate DSSE envelope")
    _require(
        envelope.get("payloadType") == attestation.VCERT_PAYLOAD_TYPE,
        "certificate DSSE payload type drifted",
    )
    signatures = _object_list(envelope.get("signatures"), "certificate signatures")
    _require(len(signatures) == 1, "certificate did not carry exactly one signature")
    keyid_value = signatures[0].get("keyid")
    _require(isinstance(keyid_value, str) and keyid_value, "certificate keyid was missing")
    keyid = cast("str", keyid_value)

    key_response = _get(service, f"/key/{keyid}")
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
    for field, value in hashes.items():
        _require(rendered.get(field) == value, f"certificate {field} did not match the render")
        _LOGGER.info("  %s=%s", field, value)

    check_lines = tuple(f"{check.id} | {check.method}" for check in certificate.checks)
    _require(
        "scale.bar_zero | z3_smt" in check_lines,
        "certificate lost the scale.bar_zero SMT obligation",
    )
    _require(
        "sort.canonical_order | z3_smt" in check_lines,
        "certificate lost the sort.canonical_order SMT obligation",
    )
    _LOGGER.info("  certificate checks:")
    for line in check_lines:
        _LOGGER.info("    %s", line)
    _LOGGER.info(
        "  signature verified: holder of server-advertised key %s (no external PKI claim)",
        keyid,
    )
    return hashes, check_lines, keyid


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


def main() -> int:
    """Run the cases, write their JSON report, and fail unless all expectations matched."""
    _configure_logging()
    report = run_e2e()
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_bytes(encode_report(report))
    _LOGGER.info("wrote report=%s", _REPORT_PATH.relative_to(_ROOT))
    _LOGGER.info("e2e demo: %d/%d cases PASS", report.passed, report.total)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
