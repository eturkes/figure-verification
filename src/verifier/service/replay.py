# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Archive-backed replay orchestration under independently configured operator trust.

Archive reads authenticate signed attempt and plot bytes under their embedded archived key only to
establish internal self-consistency. That archived key never grants trust. The caller's explicit
current-signer plus historical-pin mapping is passed unchanged to the pure replay engine, which
re-authenticates the graph under that policy. Recomputation consumes archived bytes only; this
adapter has no data-directory or model-client dependency.
"""

from collections.abc import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.replay import (
    ReplayAttemptArtifacts,
    ReplayPlotSnapshot,
    ReplaySnapshot,
    ReplayVerdict,
    replay_snapshot,
)
from verifier.service.archive import (
    Archive,
    ArchiveIntegrityError,
    ArchiveNotFoundError,
    AttemptBundle,
    open_archive,
)
from verifier.service.identity import load_identity
from verifier.service.settings import Settings

__all__ = ["replay_plot", "replay_plot_from_settings"]

_HEX_DIGITS = frozenset("0123456789abcdef")
_ADDRESS_LENGTH = 64
_MAX_SQLITE_INTEGER = 2**63 - 1


def _require_plot_id(value: object) -> str:
    if not isinstance(value, str):
        msg = f"plot_id must be str, got {type(value).__name__}"
        raise TypeError(msg)
    if len(value) != _ADDRESS_LENGTH or any(character not in _HEX_DIGITS for character in value):
        msg = "plot_id must contain exactly 64 lowercase hexadecimal characters"
        raise ValueError(msg)
    return value


def _require_replay_inputs(
    archive: object,
    trusted_keys: object,
    plot_id: object,
    max_bytes: object,
    limits: object,
) -> tuple[Archive, Mapping[str, Ed25519PublicKey], str, int, VerificationLimits]:
    if not isinstance(archive, Archive):
        msg = f"archive must be Archive, got {type(archive).__name__}"
        raise TypeError(msg)
    if not isinstance(trusted_keys, Mapping):
        msg = f"trusted_keys must be a mapping, got {type(trusted_keys).__name__}"
        raise TypeError(msg)
    checked_plot_id = _require_plot_id(plot_id)
    if type(max_bytes) is not int or not 0 <= max_bytes <= _MAX_SQLITE_INTEGER:
        msg = f"max_bytes must be an integer in 0..{_MAX_SQLITE_INTEGER}, got {max_bytes!r}"
        raise ValueError(msg)
    if not isinstance(limits, VerificationLimits):
        msg = f"limits must be VerificationLimits, got {type(limits).__name__}"
        raise TypeError(msg)
    return archive, trusted_keys, checked_plot_id, max_bytes, limits


def _snapshot_from_bundle(bundle: AttemptBundle) -> ReplaySnapshot:
    plot = bundle.plot
    if plot is None:
        msg = "archived verified attempt does not carry its required plot"
        raise ArchiveIntegrityError(msg)
    artifacts = bundle.artifacts
    return ReplaySnapshot(
        attempt_id=bundle.attempt_id,
        keyid=bundle.keyid,
        artifacts=ReplayAttemptArtifacts(
            raw_csv=artifacts.raw_csv,
            raw_manifest=artifacts.raw_manifest,
            raw_spec=artifacts.raw_spec,
            verdict=artifacts.verdict,
            model_request=artifacts.model_request,
            model_response=artifacts.model_response,
            model_reply=artifacts.model_reply,
        ),
        attempt_payload=bundle.attempt_payload,
        attempt_envelope=bundle.attempt_envelope,
        public_key=bundle.public_key,
        plot=ReplayPlotSnapshot(
            plot_id=plot.plot_id,
            keyid=plot.keyid,
            raw_csv=plot.raw_csv,
            raw_manifest=plot.raw_manifest,
            canonical_spec=plot.canonical_spec,
            plotted_table=plot.plotted_table,
            verdict=plot.verdict,
            vega_lite=plot.vega_lite,
            svg=plot.svg,
            vcert_payload=plot.vcert_payload,
            vcert_envelope=plot.vcert_envelope,
            tool_versions=plot.tool_versions,
            public_key=plot.public_key,
        ),
    )


def replay_plot(
    archive: Archive,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    plot_id: str,
    *,
    max_bytes: int,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> ReplayVerdict:
    """Replay the lowest signed successful attempt associated with one archived plot."""
    archive, trusted_keys, plot_id, max_bytes, limits = _require_replay_inputs(
        archive,
        trusted_keys,
        plot_id,
        max_bytes,
        limits,
    )
    attempt_id = archive.lowest_verified_attempt_id(plot_id)
    if attempt_id is None:
        msg = "archive plot has no replayable signed verified attempt"
        raise ArchiveNotFoundError(msg)
    bundle = archive.read_attempt(attempt_id, max_bytes=max_bytes, limits=limits)
    return replay_snapshot(_snapshot_from_bundle(bundle), trusted_keys, limits=limits)


def replay_plot_from_settings(settings: Settings, plot_id: str) -> ReplayVerdict:
    """Open one operator archive/identity snapshot and replay a plot under configured trust."""
    settings_object: object = settings
    if not isinstance(settings_object, Settings):
        msg = "settings must be a validated service Settings instance"
        raise TypeError(msg)
    archive = open_archive(settings)
    identity = load_identity(settings)
    return replay_plot(
        archive,
        identity.trusted_keys,
        plot_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
