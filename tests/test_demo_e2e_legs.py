# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hardware-free unit coverage for the optional demo E2E observation legs."""

import json
from pathlib import Path

import httpx
import msgspec
import pytest

from demo import e2e
from demo.walkthrough import ScenarioResult, WalkthroughReport, encode_report
from webui.client import PersistedChatResult, WebUIClient, WebUIProvisionError
from webui.settings import Settings

_ATTEMPT_VERIFIED = "1" * 64
_ATTEMPT_BLOCKED = "2" * 64
_ATTEMPT_POLICY = "3" * 64
_ATTEMPT_PROBLEM = "4" * 64
_PLOT_ID = "a" * 64
_KEY_ID = f"sha256:{'b' * 64}"
_CHART_URL = f"http://127.0.0.1:8000/chart/{_PLOT_ID}"
_HASHES = {
    "dataset_hash": f"sha256:{'1' * 64}",
    "spec_hash": f"sha256:{'2' * 64}",
    "plotted_table_hash": f"sha256:{'3' * 64}",
    "manifest_hash": f"sha256:{'4' * 64}",
    "vega_lite_hash": f"sha256:{'5' * 64}",
}


def _passing_report() -> WalkthroughReport:
    results = tuple(
        ScenarioResult(name=f"case-{index}", status="PASS", detail="ok") for index in range(1, 4)
    )
    return WalkthroughReport(
        generated_at="2026-07-20T00:00:00+00:00",
        status="PASS",
        passed=3,
        failed=0,
        total=3,
        results=results,
    )


def _prepare_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    report_path = root / "demo" / "reports" / "e2e_report.json"
    monkeypatch.setattr(e2e, "_ROOT", root)
    monkeypatch.setattr(e2e, "_REPORT_PATH", report_path)
    monkeypatch.setattr(e2e, "run_e2e", _passing_report)
    return report_path


def _decode_e2e(path: Path) -> e2e.E2EReport:
    return msgspec.json.decode(path.read_bytes(), type=e2e.E2EReport)


def _patch_webui_settings_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    def from_env() -> Settings:
        return Settings()

    def authenticate(_client: WebUIClient) -> str:
        return "token"

    monkeypatch.setattr(Settings, "from_env", staticmethod(from_env))
    monkeypatch.setattr(WebUIClient, "authenticate", authenticate)


def test_main_without_flags_keeps_walkthrough_report_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = _prepare_main(monkeypatch, tmp_path)

    assert e2e.main([]) == 0
    assert report_path.read_bytes() == encode_report(_passing_report())
    body = msgspec.json.decode(report_path.read_bytes(), type=dict[str, object])
    assert list(body) == ["generated_at", "status", "passed", "failed", "total", "results"]


def test_main_with_webui_verifies_chart_certificate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = _prepare_main(monkeypatch, tmp_path)
    _patch_webui_settings_and_auth(monkeypatch)

    def run_persisted_chat(_client: WebUIClient, prompt: str) -> PersistedChatResult:
        assert prompt == e2e._WEBUI_PROMPT
        return PersistedChatResult("summary", _CHART_URL)

    def fetch_certificate(origin: str, plot_id: str) -> e2e.CertInfo:
        assert origin == "http://127.0.0.1:8000"
        assert plot_id == _PLOT_ID
        return e2e.CertInfo(verified=True, keyid=_KEY_ID, hashes=_HASHES)

    monkeypatch.setattr(WebUIClient, "run_persisted_chat", run_persisted_chat)
    monkeypatch.setattr(e2e, "_fetch_and_verify_certificate", fetch_certificate)

    assert e2e.main(["--with-webui"]) == 0
    report = _decode_e2e(report_path)
    assert report.status == "PASS"
    assert report.model is None
    assert report.webui is not None
    assert report.webui.status == "PASS"
    assert report.webui.prompt == e2e._WEBUI_PROMPT
    assert report.webui.final_text == "summary"
    assert report.webui.chart_url == _CHART_URL
    assert report.webui.certificate == e2e.CertInfo(
        verified=True,
        keyid=_KEY_ID,
        hashes=_HASHES,
    )


def test_main_with_webui_accepts_chat_without_chart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = _prepare_main(monkeypatch, tmp_path)
    _patch_webui_settings_and_auth(monkeypatch)

    def run_persisted_chat(_client: WebUIClient, prompt: str) -> PersistedChatResult:
        assert prompt == e2e._WEBUI_PROMPT
        return PersistedChatResult("summary", None)

    def unexpected_fetch(_origin: str, _plot_id: str) -> e2e.CertInfo:
        pytest.fail("certificate fetch should not run without a chart URL")

    monkeypatch.setattr(WebUIClient, "run_persisted_chat", run_persisted_chat)
    monkeypatch.setattr(e2e, "_fetch_and_verify_certificate", unexpected_fetch)

    assert e2e.main(["--with-webui"]) == 0
    report = _decode_e2e(report_path)
    assert report.status == "PASS"
    assert report.webui is not None
    assert report.webui.status == "PASS"
    assert report.webui.chart_url is None
    assert report.webui.certificate is None


def test_main_with_webui_records_provisioning_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = _prepare_main(monkeypatch, tmp_path)
    _patch_webui_settings_and_auth(monkeypatch)

    def run_persisted_chat(_client: WebUIClient, _prompt: str) -> PersistedChatResult:
        message = "not ready"
        raise WebUIProvisionError(message)

    monkeypatch.setattr(WebUIClient, "run_persisted_chat", run_persisted_chat)

    assert e2e.main(["--with-webui"]) == 1
    report = _decode_e2e(report_path)
    assert report.status == "FAIL"
    assert report.webui is not None
    assert report.webui.status == "FAIL"
    assert report.webui.detail == "WebUIProvisionError: not ready"


def _check_result(*, check: str, status: str, message: str) -> dict[str, object]:
    return {
        "check": check,
        "method": "deterministic_recompute",
        "status": status,
        "severity": "blocking",
        "message": message,
    }


def test_propose_once_parses_real_verdict_and_problem_shapes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = json.loads(request.content)
        prompt = body["user_request"]
        if prompt == "verified":
            verdict = {
                "verified": True,
                "layer": "verify",
                "results": [
                    _check_result(check="schema.fields_exist", status="pass", message="ok")
                ],
                "attempt_id": _ATTEMPT_VERIFIED,
                "plot_id": _PLOT_ID,
                "spec_id": "c" * 64,
                **_HASHES,
                "svg": "<svg></svg>",
            }
            return httpx.Response(
                200,
                headers={"location": _CHART_URL},
                json=[{"model_reply": "{}", "verdict": verdict}, "summary"],
            )
        if prompt == "blocked":
            return httpx.Response(
                200,
                json={
                    "model_reply": "{}",
                    "verdict": {
                        "verified": False,
                        "layer": "verify",
                        "results": [
                            _check_result(
                                check="schema.fields_exist",
                                status="fail",
                                message="field 'profit' does not exist in the table",
                            )
                        ],
                        "attempt_id": _ATTEMPT_BLOCKED,
                    },
                },
            )
        return httpx.Response(
            502,
            json={
                "title": "Bad Gateway",
                "status": 502,
                "detail": "the model backend did not return a usable proposal",
                "attempt_id": _ATTEMPT_PROBLEM,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        verified = e2e._propose_once(client, "http://verifier.test", "verified", "sales.csv")
        blocked = e2e._propose_once(client, "http://verifier.test", "blocked", "sales.csv")
        problem = e2e._propose_once(client, "http://verifier.test", "problem", "sales.csv")

    assert verified.verified is True
    assert verified.failing_check is None
    assert verified.reason is None
    assert verified.attempt_id == _ATTEMPT_VERIFIED
    assert blocked.verified is False
    assert blocked.failing_check == "schema.fields_exist"
    assert blocked.reason == "field 'profit' does not exist in the table"
    assert blocked.attempt_id == _ATTEMPT_BLOCKED
    assert problem.http_status == 502
    assert problem.verified is False
    assert problem.detail == "the model backend did not return a usable proposal"
    assert problem.attempt_id == _ATTEMPT_PROBLEM


def test_main_with_model_records_prompts_and_audits_blocked_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = _prepare_main(monkeypatch, tmp_path)
    calls: list[tuple[str, str]] = []
    audited: list[str] = []

    def propose_once(
        _client: httpx.Client,
        verifier_url: str,
        prompt: str,
        dataset: str,
    ) -> e2e.ModelPromptObservation:
        calls.append((verifier_url, prompt))
        index = tuple(item[0] for item in e2e._MODEL_PROMPTS).index(prompt)
        verified = index == 0
        attempts = (_ATTEMPT_VERIFIED, _ATTEMPT_BLOCKED, _ATTEMPT_POLICY)
        return e2e.ModelPromptObservation(
            prompt=prompt,
            dataset_name=dataset,
            http_status=200,
            verified=verified,
            failing_check=None if verified else f"check.{index}",
            reason=None if verified else f"reason {index}",
            attempt_id=attempts[index],
            detail="",
        )

    def run_audit(attempt_id: str) -> tuple[int, str]:
        audited.append(attempt_id)
        return 0, "{}"

    monkeypatch.setattr(e2e, "_propose_once", propose_once)
    monkeypatch.setattr(e2e, "_run_audit", run_audit)

    verifier_url = "http://verifier.test"
    assert e2e.main(["--with-model", "--verifier-url", verifier_url]) == 0
    report = _decode_e2e(report_path)
    assert report.status == "PASS"
    assert report.webui is None
    assert report.model is not None
    assert report.model.status == "PASS"
    assert len(report.model.prompts) == 3
    assert report.model.audited_attempt_id == _ATTEMPT_BLOCKED
    assert report.model.audit_ok is True
    assert audited == [_ATTEMPT_BLOCKED]
    assert calls == [(verifier_url, prompt) for prompt, _dataset in e2e._MODEL_PROMPTS]


def test_main_with_model_records_transport_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = _prepare_main(monkeypatch, tmp_path)
    calls = 0

    def propose_once(
        _client: httpx.Client,
        verifier_url: str,
        prompt: str,
        dataset: str,
    ) -> e2e.ModelPromptObservation:
        nonlocal calls
        calls += 1
        if calls == 1:
            return e2e.ModelPromptObservation(
                prompt=prompt,
                dataset_name=dataset,
                http_status=200,
                verified=True,
                failing_check=None,
                reason=None,
                attempt_id=_ATTEMPT_VERIFIED,
                detail="",
            )
        request = httpx.Request("POST", f"{verifier_url}/propose-spec")
        message = "offline"
        raise httpx.ConnectError(message, request=request)

    def unexpected_audit(_attempt_id: str) -> tuple[int, str]:
        pytest.fail("audit should not run after a transport error")

    monkeypatch.setattr(e2e, "_propose_once", propose_once)
    monkeypatch.setattr(e2e, "_run_audit", unexpected_audit)

    assert e2e.main(["--with-model"]) == 1
    report = _decode_e2e(report_path)
    assert report.status == "FAIL"
    assert report.model is not None
    assert report.model.status == "FAIL"
    assert len(report.model.prompts) == 1
    assert report.model.audited_attempt_id is None
    assert report.model.audit_ok is None
    assert report.model.detail == "ConnectError: offline"
