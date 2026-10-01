# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Replay red witnesses retained at `archive/m9-rev-4` (`e18bcfb`), plus the dataset-engine twin.

A certified digest authenticates archived table bytes, never their form: both replay engines must
refuse digest-authentic non-canonical typed NDJSON at `plot_contents`, as archive does at
publication, rather than reach recomputation and report `recomputation_failed` with
`integrity_ok=True`.
"""

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

import msgspec
import pytest

import test_replay as dataset_replay
from test_replay_formula import (
    _arm_downstream_bombs,
    _fixture,
    _rebind,
    _run,
    _signed_certificate_plot,
)
from verifier import attestation, canon, checks, replay, vcert


def test_formula_replay_rejects_digest_authentic_noncanonical_table(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    malformed_table = b"not-typed-ndjson"
    certificate = msgspec.structs.replace(
        fixture.parts.certificate,
        plotted_table_hash=canon.hash_table_bytes(malformed_table),
    )
    plot = _signed_certificate_plot(
        fixture,
        certificate,
        plotted_table=malformed_table,
    )
    snapshot = _rebind(fixture, plot)

    verdict = _run(fixture, snapshot)

    assert verdict.status == "integrity_failed"
    assert verdict.failure_stage == "plot_contents"
    assert verdict.integrity_ok is False


def test_formula_replay_rejects_noncanonical_attempt_envelope(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    padded_envelope = fixture.snapshot.attempt_envelope + b" "
    snapshot = replace(
        fixture.snapshot,
        attempt_id=hashlib.sha256(padded_envelope).hexdigest(),
        attempt_envelope=padded_envelope,
    )

    verdict = _run(fixture, snapshot)

    assert verdict.status == "integrity_failed"
    assert verdict.failure_stage == "attempt_signature"
    assert verdict.integrity_ok is False


# The retained witnesses use undecodable bytes alone. Each table below decodes or not, and the
# downstream bombs prove the refusal lands BEFORE any recomputation work in either engine.
_NONCANONICAL = ("undecodable", "padded")


def _noncanonical(kind: str, table: bytes) -> bytes:
    return b"not-typed-ndjson" if kind == "undecodable" else table.replace(b"[", b"[ ", 1)


@pytest.mark.parametrize("kind", _NONCANONICAL)
def test_formula_replay_refuses_a_noncanonical_table_before_recomputation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    fixture = _fixture(tmp_path)
    table = _noncanonical(kind, fixture.snapshot.plot.plotted_table)
    certificate = msgspec.structs.replace(
        fixture.parts.certificate,
        plotted_table_hash=canon.hash_table_bytes(table),
    )
    snapshot = _rebind(fixture, _signed_certificate_plot(fixture, certificate, plotted_table=table))
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)

    verdict = _run(fixture, snapshot)

    assert (verdict.status, verdict.failure_stage, verdict.integrity_ok) == (
        "integrity_failed",
        "plot_contents",
        False,
    )
    assert set(calls.values()) == {0}


@pytest.mark.parametrize("kind", _NONCANONICAL)
def test_dataset_replay_refuses_a_noncanonical_table_before_recomputation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    fixture = dataset_replay._fixture(tmp_path)
    archived = fixture.snapshot.plot
    table = _noncanonical(kind, archived.plotted_table)
    certificate = msgspec.structs.replace(
        msgspec.json.decode(archived.vcert_payload, type=vcert.VCert, strict=True),
        plotted_table_hash=canon.hash_table_bytes(table),
    )
    envelope = attestation.sign_vcert(
        certificate,
        fixture.signer.private_key,
        keyid=fixture.signer.keyid,
        limits=fixture.settings.limits,
    )
    plot = replace(
        archived,
        plot_id=hashlib.sha256(envelope).hexdigest(),
        plotted_table=table,
        vcert_payload=vcert.vcert_bytes(certificate),
        vcert_envelope=envelope,
    )
    snapshot = dataset_replay._rebind_plot(fixture, plot)
    recomputed: list[object] = []

    def bomb(*args: object, **_kwargs: object) -> NoReturn:
        recomputed.append(args)
        msg = "a non-canonical table reached recomputation"
        raise AssertionError(msg)

    monkeypatch.setattr(checks, "verify_snapshot", bomb)

    verdict = replay.replay_snapshot(snapshot, dataset_replay._trusted(fixture))

    assert (verdict.status, verdict.failure_stage, verdict.integrity_ok) == (
        "integrity_failed",
        "plot_contents",
        False,
    )
    assert recomputed == []
