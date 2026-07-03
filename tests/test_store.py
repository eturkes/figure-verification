# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""ArtifactStore unit tests (M2.3 codex-review) — the two invariants the service path can't reach.

The service builds the store from a Settings-validated store_cap and content-addresses every
render, so two store guarantees need direct exercise here: a non-positive cap is rejected at
construction (Settings guards it too, but the store owns the precondition), and a spec_id shared
by two distinct plot_ids — what an operator manifest change between two renders of one spec
produces (the certificate's manifest_hash differs, its spec_hash does not) — survives under a
live-reference count until its LAST referencing render evicts. Retrieval stays consistent without
resting on the 1:1 plot<->spec precondition.
"""

import pytest

from verifier.service.store import ArtifactStore

_A, _B, _C = ("a" * 64, "b" * 64, "c" * 64)  # distinct plot_ids
_S, _T = ("5" * 64, "7" * 64)  # distinct spec_ids


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_nonpositive_cap(bad: int) -> None:
    # cap 0 would drop every render immediately; cap < 0 would raise on the first eviction.
    with pytest.raises(ValueError, match="cap"):
        ArtifactStore(bad)


def test_shared_spec_survives_until_last_referencing_render_evicts() -> None:
    store = ArtifactStore(cap=1)
    # Two DISTINCT renders sharing ONE spec_id (the operator-manifest-mutation case).
    store.put(plot_id=_A, cert_bytes=b"CA", spec_id=_S, spec_bytes=b"SPEC")
    store.put(plot_id=_B, cert_bytes=b"CB", spec_id=_S, spec_bytes=b"SPEC")
    # A evicts at cap 1, but B still references S -> the spec is retained (refcount > 1 branch).
    assert store.certificate(_A) is None
    assert store.certificate(_B) == b"CB"
    assert store.spec(_S) == b"SPEC"
    # A third, unrelated render evicts B -> S's last reference drops, and its spec bytes with it.
    store.put(plot_id=_C, cert_bytes=b"CC", spec_id=_T, spec_bytes=b"SPEC2")
    assert store.certificate(_B) is None
    assert store.spec(_S) is None  # dropped: no live render references S (refcount -> 0 branch)
    assert store.spec(_T) == b"SPEC2"
