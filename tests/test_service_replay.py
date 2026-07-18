# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Archive-backed replay selection, trust, durability, and corruption boundaries."""

import ast
import hashlib
import inspect
import shutil
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from verifier import attestation, render
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.replay import ReplaySnapshot, ReplayVerdict, replay_snapshot
from verifier.service import archive as archive_module
from verifier.service import pipeline
from verifier.service import replay as service_replay
from verifier.service.archive import (
    Archive,
    ArchiveError,
    ArchiveIntegrityError,
    ArchiveNotFoundError,
    ArchiveReadLimitError,
    AttemptArtifacts,
    AttemptBundle,
    AttemptDraft,
    AttemptOutcome,
    AttemptRoute,
    BlobKind,
    materialize_attempt_bundle,
    materialize_plot_bundle,
    open_archive,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_DATA = _ROOT / "data"
_RAW_SPEC = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
_TIME = datetime(2026, 7, 18, 12, 34, 56, 789012, tzinfo=UTC)
_BOOL_AS_INT = cast("int", bool(1))


@dataclass(frozen=True, slots=True)
class _Fixture:
    settings: Settings
    signer: Signer
    archive: Archive
    bundle: AttemptBundle
    csv_path: Path
    manifest_path: Path


def _draft(plot: archive_module.PlotBundle) -> AttemptDraft:
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


def _fixture(tmp_path: Path) -> _Fixture:
    data_dir = tmp_path / "data"
    schemas_dir = data_dir / "schemas"
    schemas_dir.mkdir(parents=True)
    csv_path = data_dir / "sales.csv"
    manifest_path = schemas_dir / "sales.json"
    shutil.copyfile(_SOURCE_DATA / "sales.csv", csv_path)
    shutil.copyfile(_SOURCE_DATA / "schemas/sales.json", manifest_path)

    settings = Settings(data_dir=data_dir, state_dir=tmp_path / "state")
    identity = load_identity(settings)
    outcome = pipeline.verify_only(_RAW_SPEC, settings)
    prepared = cast("render.PreparedArtifact", outcome.prepared)
    rendered = render.render_prepared(prepared, limits=settings.limits)
    envelope = attestation.sign_vcert(
        rendered.certificate,
        identity.signer.private_key,
        keyid=identity.signer.keyid,
        limits=settings.limits,
    )
    plot = materialize_plot_bundle(
        prepared,
        rendered,
        envelope,
        identity.signer,
        limits=settings.limits,
    )
    archive = open_archive(settings)
    bundle = archive.record_attempt(_draft(plot), identity.signer, limits=settings.limits)
    return _Fixture(settings, identity.signer, archive, bundle, csv_path, manifest_path)


def _trusted(fixture: _Fixture) -> dict[str, Ed25519PublicKey]:
    return {fixture.signer.keyid: fixture.signer.public_key}


def _bundle_size(bundle: AttemptBundle) -> int:
    batch = archive_module._attempt_bundle_batch(bundle)
    return sum(len(blob.payload) for blob in archive_module._unique_blob_writes(batch.blobs))


def test_exact_replay_uses_archived_bytes_after_live_mutation_and_deletion(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.csv_path.write_bytes(b"month,revenue\nJan,999999\n")
    fixture.manifest_path.unlink()

    verdict = service_replay.replay_plot(
        fixture.archive,
        _trusted(fixture),
        cast("archive_module.PlotBundle", fixture.bundle.plot).plot_id,
        max_bytes=_bundle_size(fixture.bundle),
        limits=fixture.settings.limits,
    )

    assert verdict.status == "exact"
    assert verdict.integrity_ok
    assert verdict.exact


def test_replay_is_independent_of_render_and_chart_lru_state(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plot = cast("archive_module.PlotBundle", fixture.bundle.plot)

    verdict = service_replay.replay_plot(
        fixture.archive,
        _trusted(fixture),
        plot.plot_id,
        max_bytes=fixture.settings.max_archive_bytes,
        limits=fixture.settings.limits,
    )

    assert verdict.status == "exact"
    assert verdict.exact


def test_replay_survives_process_restart_and_foreign_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    plot = cast("archive_module.PlotBundle", fixture.bundle.plot)
    reopened = open_archive(fixture.settings)
    assert (
        service_replay.replay_plot(
            reopened,
            _trusted(fixture),
            plot.plot_id,
            max_bytes=fixture.settings.max_archive_bytes,
            limits=fixture.settings.limits,
        ).status
        == "exact"
    )

    foreign = tmp_path / "foreign-cwd"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    verdict = service_replay.replay_plot_from_settings(fixture.settings, plot.plot_id)
    assert verdict.status == "exact"
    assert verdict.exact


def test_replay_selects_lowest_attempt_and_passes_trust_mapping_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    plot = cast("archive_module.PlotBundle", fixture.bundle.plot)
    extra = tuple(
        materialize_attempt_bundle(
            _draft(plot),
            fixture.signer,
            nonce=nonce * 32,
            limits=fixture.settings.limits,
        )
        for nonce in ("2", "3")
    )
    for bundle in extra:
        fixture.archive.publish_attempt(bundle, limits=fixture.settings.limits)
    expected = min(fixture.bundle.attempt_id, *(bundle.attempt_id for bundle in extra))
    assert fixture.archive.lowest_verified_attempt_id(plot.plot_id) == expected

    trusted = _trusted(fixture)
    observed: dict[str, object] = {}
    real_replay_snapshot = replay_snapshot

    def observe(
        snapshot: ReplaySnapshot,
        trusted_keys: Mapping[str, Ed25519PublicKey],
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> ReplayVerdict:
        observed["attempt_id"] = snapshot.attempt_id
        observed["trusted_keys"] = trusted_keys
        return real_replay_snapshot(snapshot, trusted_keys, limits=limits)

    monkeypatch.setattr(service_replay, "replay_snapshot", observe)
    verdict = service_replay.replay_plot(
        fixture.archive,
        trusted,
        plot.plot_id,
        max_bytes=fixture.settings.max_archive_bytes,
        limits=fixture.settings.limits,
    )

    assert observed == {"attempt_id": expected, "trusted_keys": trusted}
    assert verdict.status == "exact"


def test_unpinned_archived_signer_returns_untrusted_verdict(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plot = cast("archive_module.PlotBundle", fixture.bundle.plot)
    untrusted: dict[str, Ed25519PublicKey] = {}

    verdict = service_replay.replay_plot(
        fixture.archive,
        untrusted,
        plot.plot_id,
        max_bytes=fixture.settings.max_archive_bytes,
        limits=fixture.settings.limits,
    )

    assert verdict.status == "untrusted_key"
    assert not verdict.integrity_ok
    assert not verdict.exact


def test_missing_blob_and_corrupt_plot_association_raise_archive_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = _fixture(tmp_path / "missing")
    missing_plot = cast("archive_module.PlotBundle", missing.bundle.plot)
    connection = sqlite3.connect(missing.archive.database_path, autocommit=True)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DROP TRIGGER blobs_reject_delete")
        digest = "sha256:" + hashlib.sha256(missing_plot.raw_csv).hexdigest()
        cursor = connection.execute(
            "DELETE FROM blobs WHERE digest = ? AND kind = ?",
            (digest, BlobKind.RAW_CSV.value),
        )
        assert cursor.rowcount == 1
    finally:
        connection.close()

    def selected_attempt(_archive: Archive, _plot_id: str) -> str:
        return missing.bundle.attempt_id

    monkeypatch.setattr(Archive, "lowest_verified_attempt_id", selected_attempt)
    with pytest.raises(ArchiveError):
        service_replay.replay_plot(
            missing.archive,
            _trusted(missing),
            missing_plot.plot_id,
            max_bytes=missing.settings.max_archive_bytes,
            limits=missing.settings.limits,
        )
    monkeypatch.undo()

    associated = _fixture(tmp_path / "association")
    associated_plot = cast("archive_module.PlotBundle", associated.bundle.plot)
    corrupt_plot_id = "f" * 64 if associated_plot.plot_id != "f" * 64 else "e" * 64
    connection = sqlite3.connect(associated.archive.database_path, autocommit=True)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        cursor = connection.execute(
            "UPDATE attempts SET plot_id = ? WHERE attempt_id = ?",
            (corrupt_plot_id, associated.bundle.attempt_id),
        )
        assert cursor.rowcount == 1
    finally:
        connection.close()
    with pytest.raises(ArchiveIntegrityError, match="linked plot record is absent"):
        service_replay.replay_plot(
            associated.archive,
            _trusted(associated),
            corrupt_plot_id,
            max_bytes=associated.settings.max_archive_bytes,
            limits=associated.settings.limits,
        )


def test_archive_read_cap_and_unknown_plot_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plot = cast("archive_module.PlotBundle", fixture.bundle.plot)
    with pytest.raises(ArchiveReadLimitError, match="aggregate read limit"):
        service_replay.replay_plot(
            fixture.archive,
            _trusted(fixture),
            plot.plot_id,
            max_bytes=0,
            limits=fixture.settings.limits,
        )

    absent_plot_id = "0" * 64 if plot.plot_id != "0" * 64 else "1" * 64
    with pytest.raises(ArchiveNotFoundError, match="no replayable"):
        service_replay.replay_plot(
            fixture.archive,
            _trusted(fixture),
            absent_plot_id,
            max_bytes=fixture.settings.max_archive_bytes,
            limits=fixture.settings.limits,
        )


def test_adapter_runtime_guards_and_verified_plot_defense(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plot = cast("archive_module.PlotBundle", fixture.bundle.plot)
    trusted = _trusted(fixture)

    with pytest.raises(TypeError, match="archive must be Archive"):
        service_replay.replay_plot(
            cast("Archive", object()),
            trusted,
            plot.plot_id,
            max_bytes=1,
        )
    with pytest.raises(TypeError, match="trusted_keys must be a mapping"):
        service_replay.replay_plot(
            fixture.archive,
            cast("Mapping[str, Ed25519PublicKey]", object()),
            plot.plot_id,
            max_bytes=1,
        )
    with pytest.raises(TypeError, match="plot_id must be str"):
        service_replay.replay_plot(
            fixture.archive,
            trusted,
            cast("str", 1),
            max_bytes=1,
        )
    for bad_plot_id in ("bad", "A" * 64):
        with pytest.raises(ValueError, match="64 lowercase"):
            service_replay.replay_plot(
                fixture.archive,
                trusted,
                bad_plot_id,
                max_bytes=1,
            )
    for bad_max_bytes in (_BOOL_AS_INT, -1, 2**63):
        with pytest.raises(ValueError, match="max_bytes"):
            service_replay.replay_plot(
                fixture.archive,
                trusted,
                plot.plot_id,
                max_bytes=bad_max_bytes,
            )
    with pytest.raises(TypeError, match="limits must be VerificationLimits"):
        service_replay.replay_plot(
            fixture.archive,
            trusted,
            plot.plot_id,
            max_bytes=1,
            limits=cast("VerificationLimits", object()),
        )
    with pytest.raises(TypeError, match="validated service Settings"):
        service_replay.replay_plot_from_settings(cast("Settings", object()), plot.plot_id)
    with pytest.raises(ArchiveIntegrityError, match="does not carry"):
        service_replay._snapshot_from_bundle(replace(fixture.bundle, plot=None))


def test_service_replay_has_no_model_client_or_data_dir_dependency() -> None:
    tree = ast.parse(inspect.getsource(service_replay))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "verifier.service"
        for alias in node.names
    }
    argument_names = {
        argument.arg
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    }

    assert "verifier.service.model_client" not in imported_modules
    assert "model_client" not in imported_names
    assert "data_dir" not in argument_names
