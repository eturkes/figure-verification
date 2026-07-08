# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""ArtifactStore unit tests — store guarantees the service path can't reach here.

The service builds the store from Settings-validated caps and content-addresses every render, so
these guarantees need direct exercise: non-positive store_cap and html_cap are rejected at
construction (Settings guards them too, but the store owns the preconditions); a spec_id shared by
two distinct plot_ids — what an operator manifest change between two renders of one spec produces
(the certificate's manifest_hash differs, its spec_hash does not) — survives under a live-reference
count until its LAST referencing render evicts; and the chart LRU (html_cap, M4.1b — its GET route
lands M4.1c) evicts independently of the render LRU in BOTH directions, so a chart can 404 while its
certificate lives and a certificate can 404 while its chart lives. put_chart and chart each
refresh chart-LRU recency (a re-put of a PRESENT key, or a read, moves its entry to newest) —
pinned here against silent removal of that refresh, which count-only eviction tests miss.
Retrieval stays consistent without resting on the 1:1 plot<->spec precondition.
"""

import pytest

from verifier.service.store import ArtifactStore

_A, _B, _C = ("a" * 64, "b" * 64, "c" * 64)  # distinct plot_ids
_S, _T = ("5" * 64, "7" * 64)  # distinct spec_ids


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_nonpositive_cap(bad: int) -> None:
    # cap 0 would drop every render immediately; cap < 0 would raise on the first eviction. Match
    # "cap must" (not bare "cap") so this stays distinct from the html_cap guard's message.
    with pytest.raises(ValueError, match="cap must"):
        ArtifactStore(bad, html_cap=1)


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_nonpositive_html_cap(bad: int) -> None:
    # The chart LRU has the same non-positive failure modes as the render LRU; cap=1 is valid so
    # the html_cap guard is what fires.
    with pytest.raises(ValueError, match="html_cap must"):
        ArtifactStore(1, html_cap=bad)


def test_shared_spec_survives_until_last_referencing_render_evicts() -> None:
    store = ArtifactStore(cap=1, html_cap=1)
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


def test_chart_lru_evicts_independently_of_render_lru() -> None:
    # Chart LRU tighter than the render LRU (html_cap 1 << store_cap 8): the common mixed state,
    # a chart 404s while its certificate lives, plus the re-put recency cycle.
    store = ArtifactStore(cap=8, html_cap=1)
    store.put(plot_id=_A, cert_bytes=b"CA", spec_id=_S, spec_bytes=b"SPEC")
    store.put_chart(_A, b"<html>A</html>")  # html_cap 1, no eviction yet (while-loop skipped)
    store.put(plot_id=_B, cert_bytes=b"CB", spec_id=_T, spec_bytes=b"SPEC2")
    store.put_chart(_B, b"<html>B</html>")  # evicts A's chart (while-loop taken)
    assert store.chart(_A) is None  # chart evicted...
    assert store.certificate(_A) == b"CA"  # ...while its certificate still lives (render cap 8)
    assert store.chart(_B) == b"<html>B</html>"
    # Re-putting A's chart restores it (refreshing recency) and makes B's the oldest, so B evicts.
    store.put_chart(_A, b"<html>A</html>")
    assert store.chart(_A) == b"<html>A</html>"
    assert store.chart(_B) is None


def test_cert_lru_evicts_independently_of_chart_lru() -> None:
    # The symmetric mixed state: render LRU tighter than the chart LRU (store_cap 1 << html_cap 8),
    # so a certificate 404s while its chart still lives.
    store = ArtifactStore(cap=1, html_cap=8)
    store.put(plot_id=_A, cert_bytes=b"CA", spec_id=_S, spec_bytes=b"SPEC")
    store.put_chart(_A, b"<html>A</html>")
    store.put(plot_id=_B, cert_bytes=b"CB", spec_id=_T, spec_bytes=b"SPEC2")  # evicts A's render
    store.put_chart(_B, b"<html>B</html>")
    assert store.certificate(_A) is None  # certificate evicted...
    assert store.chart(_A) == b"<html>A</html>"  # ...while its chart still lives (html_cap 8)
    assert store.certificate(_B) == b"CB"


def test_put_chart_refreshes_recency_of_present_key() -> None:
    # Re-putting a chart already in the LRU moves it to newest; without put_chart's move_to_end the
    # stale A would evict before B. The independent-eviction tests only ever re-put an ALREADY
    # EVICTED key (a fresh insert), so they leave this refresh unpinned -- deleting the move_to_end
    # would still pass them. html_cap 2 lets A and B coexist before the recency-deciding insert.
    store = ArtifactStore(cap=8, html_cap=2)
    store.put_chart(_A, b"<html>A</html>")
    store.put_chart(_B, b"<html>B</html>")
    store.put_chart(_A, b"<html>A</html>")  # A PRESENT -> refresh recency (A now newest, B oldest)
    store.put_chart(_C, b"<html>C</html>")  # evicts the oldest, B -- not the refreshed A
    assert store.chart(_B) is None  # fails if put_chart skips move_to_end (A would evict instead)
    assert store.chart(_A) == b"<html>A</html>"
    assert store.chart(_C) == b"<html>C</html>"


def test_chart_read_refreshes_recency() -> None:
    # A chart() hit moves its entry to newest; without chart's move_to_end the read leaves A oldest
    # and the next insert evicts it. No other test asserts a READ reorders eviction, so this pins
    # chart()'s recency refresh against silent removal. html_cap 2.
    store = ArtifactStore(cap=8, html_cap=2)
    store.put_chart(_A, b"<html>A</html>")
    store.put_chart(_B, b"<html>B</html>")
    assert store.chart(_A) == b"<html>A</html>"  # READ refreshes A -> B is now oldest
    store.put_chart(_C, b"<html>C</html>")  # evicts the oldest, B -- not the just-read A
    assert store.chart(_B) is None  # fails if chart() skips move_to_end (A would evict instead)
    assert store.chart(_A) == b"<html>A</html>"
    assert store.chart(_C) == b"<html>C</html>"
