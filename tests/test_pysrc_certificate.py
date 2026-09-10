# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Core certificate — K1-K6 of `.agent/contracts/m13u5.md`.

The certificate is the surface a reader ACTS on, so what it does not establish is as load-bearing
as what it does. `checks` is all-pass by construction, matching v0.3's
`CertifiedCheck.status: Literal["pass"]`; everything unestablished lives in `declared_open`.

Skeleton: each body is `pytest.skip` and its docstring carries the predicate's acceptance check.
"""

import pytest


def test_k1_certificate_field_set() -> None:
    """Exactly `version, source_sha256, spec_sha256, table_sha256, provenance, artifact_sha256,
    numeric_profile, checks, declared_open, interpretation`.

    Accept: `__dataclass_fields__` pinned as an exact hand-stated set; adding a field without
    updating the pin goes red.
    """
    pytest.skip("M13.5 skeleton")


def test_k2_source_digest_is_the_submitted_bytes() -> None:
    """`source_sha256` digests the EXACT submitted bytes under a new domain tag; no canonical
    re-emission (M13 binding rule -- canonicalizing would make the executed bytes no longer the
    model's).

    Accept: byte-identical round trip; a whitespace-only edit changes the digest.
    """
    pytest.skip("M13.5 skeleton")


def test_k3_checks_are_all_pass_by_construction() -> None:
    """No failure ever enters `checks`; anything unestablished goes to `declared_open`.

    Accept: exact-set pin on the check ids; a variant introducing a non-pass status fails
    `mypy --strict`.
    """
    pytest.skip("M13.5 skeleton")


def test_k4_declared_open_always_names_the_artifact_gap() -> None:
    """The PNG is never compared against this table -- M10 observation owns that -- and the
    formula arm without a `FormulaTarget` also carries the intent gap.

    Accept: both strings byte-pinned; the artifact gap present in BOTH arms, the intent gap
    present exactly when no `FormulaTarget` was consumed.
    """
    pytest.skip("M13.5 skeleton")


def test_k5_provenance_matrix() -> None:
    """`provenance = "artifact"` only when every plotted number derives from user-supplied bytes:
    the dataset arm with a matched target, or the formula arm with a `FormulaTarget`. Otherwise
    `"internal"`.

    Accept: the full arm x target matrix, each cell pinned.
    """
    pytest.skip("M13.5 skeleton")


def test_k6_interpretation_is_plain_words_and_model_free() -> None:
    """Arm, mark, what x and y are, sample or row count, labels, numeric profile, and -- formula
    arm -- the expression and grid printed back for the reader to check against their own request.

    Accept: byte-pinned strings for one witness per arm; a scan for submitted identifiers finds
    only the label strings the projection already carries.
    """
    pytest.skip("M13.5 skeleton")
