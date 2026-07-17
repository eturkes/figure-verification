# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M5.4f operator-only attempt audit, configured trust, and terminal-safe disclosure."""

import base64
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import msgspec
import pytest

from verifier import attestation, render
from verifier.service import __main__ as service_main
from verifier.service import audit, pipeline
from verifier.service.archive import (
    AttemptArtifacts,
    AttemptBundle,
    AttemptDraft,
    AttemptOutcome,
    AttemptRoute,
    BlobKind,
    PlotBundle,
    materialize_attempt_bundle,
    materialize_plot_bundle,
    open_archive,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_RAW_SPEC = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
_TIME = datetime(2026, 7, 17, 3, 4, 5, 678901, tzinfo=UTC)
_ENCODER = msgspec.json.Encoder(order="deterministic")


def _parts(tmp_path: Path) -> tuple[Settings, Signer, PlotBundle]:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    outcome = pipeline.verify_only(_RAW_SPEC, settings)
    prepared = cast("render.PreparedArtifact", outcome.prepared)
    rendered = render.render_prepared(prepared, limits=settings.limits)
    envelope = attestation.sign_vcert(
        rendered.certificate,
        signer.private_key,
        keyid=signer.keyid,
        limits=settings.limits,
    )
    plot = materialize_plot_bundle(prepared, rendered, envelope, signer, limits=settings.limits)
    return settings, signer, plot


def _verified_draft(plot: PlotBundle) -> AttemptDraft:
    return AttemptDraft(
        occurred_at=_TIME,
        route=AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=AttemptArtifacts(
            raw_csv=plot.raw_csv,
            raw_manifest=plot.raw_manifest,
            raw_spec=_RAW_SPEC,
            verdict=plot.verdict,
        ),
        plot=plot,
    )


def _rejected_draft(settings: Settings) -> AttemptDraft:
    raw_spec = b"{"
    return AttemptDraft(
        occurred_at=_TIME,
        route=AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=AttemptOutcome.REJECTED,
        artifacts=AttemptArtifacts(
            raw_spec=raw_spec,
            verdict=_ENCODER.encode(pipeline.verify_only(raw_spec, settings).verdict),
        ),
    )


_PROBLEM_SHAPES = (
    (AttemptOutcome.DATASET_NOT_FOUND, 404, AttemptArtifacts()),
    (AttemptOutcome.PROPOSER_POLICY, 422, AttemptArtifacts()),
    (
        AttemptOutcome.DATASET_MISMATCH,
        502,
        AttemptArtifacts(
            raw_spec=b"private reply",
            model_request=b"private request",
            model_response=b"private response",
            model_reply=b"private reply",
        ),
    ),
    (AttemptOutcome.MODEL_TRANSPORT, 503, AttemptArtifacts(model_request=b"private request")),
    (
        AttemptOutcome.MODEL_CONTENT_ENCODING,
        502,
        AttemptArtifacts(model_request=b"private request"),
    ),
    (
        AttemptOutcome.MODEL_RESPONSE_TOO_LARGE,
        502,
        AttemptArtifacts(model_request=b"private request"),
    ),
    (
        AttemptOutcome.MODEL_HTTP_STATUS,
        502,
        AttemptArtifacts(model_request=b"private request", model_response=b"private response"),
    ),
    (
        AttemptOutcome.MODEL_PROMPT_TOKENS,
        422,
        AttemptArtifacts(model_request=b"private request", model_response=b"private response"),
    ),
    (
        AttemptOutcome.MODEL_INVALID_ENVELOPE,
        502,
        AttemptArtifacts(model_request=b"private request", model_response=b"private response"),
    ),
    (
        AttemptOutcome.MODEL_NO_CHOICES,
        502,
        AttemptArtifacts(model_request=b"private request", model_response=b"private response"),
    ),
    (
        AttemptOutcome.MODEL_EMPTY_CONTENT,
        502,
        AttemptArtifacts(model_request=b"private request", model_response=b"private response"),
    ),
)


def _problem_draft(
    outcome: AttemptOutcome, status: int, artifacts: AttemptArtifacts
) -> AttemptDraft:
    return AttemptDraft(
        occurred_at=_TIME,
        route=AttemptRoute.PROPOSE_SPEC,
        http_status=status,
        outcome=outcome,
        artifacts=artifacts,
    )


def _publish(
    settings: Settings,
    signer: Signer,
    draft: AttemptDraft,
    *,
    nonce: str,
) -> AttemptBundle:
    bundle = materialize_attempt_bundle(draft, signer, nonce=nonce, limits=settings.limits)
    open_archive(settings).publish_attempt(bundle, limits=settings.limits)
    return bundle


def _decoded(output: bytes) -> dict[str, Any]:
    assert output.isascii()
    return cast("dict[str, Any]", json.loads(output))


def test_every_closed_outcome_has_stable_authenticated_redacted_output(tmp_path: Path) -> None:
    settings, signer, plot = _parts(tmp_path)
    drafts = (
        _verified_draft(plot),
        _rejected_draft(settings),
        *(_problem_draft(*shape) for shape in _PROBLEM_SHAPES),
    )
    assert {draft.outcome for draft in drafts} == set(AttemptOutcome)

    for index, draft in enumerate(drafts, start=1):
        bundle = _publish(settings, signer, draft, nonce=f"{index:032x}")
        first = audit.audit_attempt(settings, bundle.attempt_id)
        second = audit.audit_attempt(settings, bundle.attempt_id)
        assert first == second
        assert b"private request" not in first
        assert b"private response" not in first
        assert b"private reply" not in first
        assert b'"content"' not in first

        document = _decoded(first)
        assert list(document) == [
            "audit_version",
            "disclosure",
            "authentication",
            "attempt",
            "plot",
        ]
        assert document["audit_version"] == "attempt-audit-0.1"
        assert document["disclosure"] == "redacted"
        assert document["authentication"] == {
            "key_policy": "current-or-explicitly-pinned",
            "attempt_dsse": "valid",
            "plot_vcert_dsse": "valid" if bundle.plot is not None else None,
        }
        occurrence = document["attempt"]
        assert occurrence["id"] == bundle.attempt_id
        assert occurrence["outcome"] == draft.outcome.value
        assert occurrence["http_status"] == draft.http_status
        assert occurrence["artifacts"] == [
            {
                "role": binding.role.value,
                "digest": binding.digest,
                "bytes": len(cast("bytes", getattr(bundle.artifacts, binding.role.value))),
            }
            for binding in bundle.manifest.artifacts
        ]
        if bundle.plot is None:
            assert document["plot"] is None
        else:
            plot_document = document["plot"]
            assert plot_document["id"] == bundle.plot.plot_id
            assert [item["role"] for item in plot_document["artifacts"]] == [
                binding.role.value for binding in bundle.manifest.plot_artifacts
            ]


def test_sensitive_disclosure_is_ascii_json_escaped_utf8_or_base64(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    unsafe_prompt = b'{"prompt":"\x1b[31mred\xe2\x80\xaehidden\n"}'
    unsafe_response = b'{"reply":"\x1b]8;;https://evil.invalid\x07label"}'
    invalid_reply = b'{"spec":"private-invalid"}\xff'
    draft = _problem_draft(
        AttemptOutcome.DATASET_MISMATCH,
        502,
        AttemptArtifacts(
            raw_spec=invalid_reply,
            model_request=unsafe_prompt,
            model_response=unsafe_response,
            model_reply=invalid_reply,
        ),
    )
    bundle = _publish(settings, signer, draft, nonce="a" * 32)

    redacted = audit.audit_attempt(settings, bundle.attempt_id)
    assert b"private-invalid" not in redacted
    assert b'"content"' not in redacted

    revealed = audit.audit_attempt(settings, bundle.attempt_id, reveal_sensitive=True)
    assert all(byte == 10 or 32 <= byte <= 126 for byte in revealed)
    assert b"\x1b" not in revealed
    assert b"\xe2\x80\xae" not in revealed
    assert b"\xff" not in revealed
    assert b"\\u001b" in revealed
    assert b"\\u202e" in revealed
    document = _decoded(revealed)
    assert document["disclosure"] == "sensitive-attempt-bytes"
    artifacts = {item["role"]: item for item in document["attempt"]["artifacts"]}
    assert artifacts[BlobKind.MODEL_REQUEST.value]["content"] == {
        "encoding": "utf-8",
        "value": unsafe_prompt.decode("utf-8"),
    }
    assert artifacts[BlobKind.MODEL_RESPONSE.value]["content"] == {
        "encoding": "utf-8",
        "value": unsafe_response.decode("utf-8"),
    }
    encoded = base64.b64encode(invalid_reply).decode("ascii")
    assert artifacts[BlobKind.RAW_SPEC.value]["content"] == {
        "encoding": "base64",
        "value": encoded,
    }
    assert artifacts[BlobKind.MODEL_REPLY.value]["content"] == {
        "encoding": "base64",
        "value": encoded,
    }


def test_audit_requires_current_or_explicitly_pinned_signing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    bundle = _publish(settings, signer, _rejected_draft(settings), nonce="b" * 32)
    rotated = Settings(
        data_dir=_DATA,
        state_dir=settings.state_dir,
        signing_key_file=settings.state_dir / "rotated.key",
    )

    with pytest.raises(audit.AuditError, match="configured-key authentication"):
        audit.audit_attempt(rotated, bundle.attempt_id)

    pinned = Settings(
        data_dir=_DATA,
        state_dir=settings.state_dir,
        signing_key_file=settings.state_dir / "rotated.key",
        trusted_keyids=(signer.keyid,),
    )
    assert _decoded(audit.audit_attempt(pinned, bundle.attempt_id))["attempt"]["id"] == (
        bundle.attempt_id
    )

    def reject_configured_key(*_args: object, **_kwargs: object) -> None:
        message = "injected configured-key rejection"
        raise attestation.AttestationError(message)

    monkeypatch.setattr(
        "verifier.service.audit._authenticate_configured_key", reject_configured_key
    )
    with pytest.raises(audit.AuditError, match="configured-key authentication"):
        audit.audit_attempt(pinned, bundle.attempt_id)


def test_corruption_and_cli_fail_closed_without_content_or_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    secret = b"private-terminal-secret"
    draft = _problem_draft(
        AttemptOutcome.DATASET_MISMATCH,
        502,
        AttemptArtifacts(
            raw_spec=secret,
            model_request=b"request",
            model_response=b"response",
            model_reply=secret,
        ),
    )
    bundle = _publish(settings, signer, draft, nonce="c" * 32)
    database = open_archive(settings).database_path
    connection = sqlite3.connect(database, autocommit=True)
    try:
        connection.execute("DROP TRIGGER blobs_reject_update")
        connection.execute(
            "UPDATE blobs SET content = ? WHERE kind = ?",
            (b"x" * len(secret), BlobKind.RAW_SPEC.value),
        )
    finally:
        connection.close()

    with pytest.raises(audit.AuditError, match="archive verification"):
        audit.audit_attempt(settings, bundle.attempt_id, reveal_sensitive=True)

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: settings))
    assert audit.main([bundle.attempt_id, "--reveal-sensitive"]) == 1
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == "attempt audit failed: archive or configured-key verification failed\n"
    assert secret.decode() not in captured.err
    assert secret.decode() not in caplog.text


def test_cli_dispatch_validation_and_real_module_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    bundle = _publish(settings, signer, _rejected_draft(settings), nonce="d" * 32)
    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: settings))

    assert audit.main([bundle.attempt_id]) == 0
    captured = capfd.readouterr()
    assert _decoded(captured.out.encode("ascii"))["attempt"]["id"] == bundle.attempt_id
    assert captured.err == ""

    seen: list[tuple[str, ...]] = []

    def fake_audit_main(argv: tuple[str, ...]) -> int:
        seen.append(argv)
        return 7

    monkeypatch.setattr(service_main, "audit_main", fake_audit_main)
    assert service_main.main(("audit", bundle.attempt_id)) == 7
    assert seen == [(bundle.attempt_id,)]
    with pytest.raises(SystemExit, match="usage"):
        service_main.main(("unknown",))
    with pytest.raises(SystemExit):
        audit.main(("bad-id",))

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    env = {
        **os.environ,
        "VERIFIER_DATA_DIR": str(_DATA),
        "VERIFIER_STATE_DIR": str(settings.state_dir),
        "VERIFIER_SIGNING_KEY_FILE": str(settings.signing_key_file),
        "VERIFIER_TRUSTED_KEYIDS": "",
    }
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(  # noqa: S603 - fixed interpreter/module + content-address arg
        [sys.executable, "-m", "verifier.service", "audit", bundle.attempt_id],
        cwd=foreign,
        env=env,
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0
    assert completed.stderr == b""
    assert _decoded(completed.stdout)["attempt"]["id"] == bundle.attempt_id
