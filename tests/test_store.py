# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""ArtifactStore count/byte-invariant and recency mutation witnesses.

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
Retrieval stays consistent without resting on the 1:1 plot<->spec precondition. M5.1j adds exact
logical payload ceilings: certificates + unique live specs for renders, and HTML bytes for charts.
Boundary, shared-spec, replacement, dual-cap eviction, recency, and pre-mutation oversize tests
pin both additions and releases; removing either accounting direction changes visible eviction.
"""

import pytest

from verifier.service.store import ArtifactStore

_A, _B, _C = ("a" * 64, "b" * 64, "c" * 64)  # distinct plot_ids
_S, _T = ("5" * 64, "7" * 64)  # distinct spec_ids
_LARGE_BUDGET = 1_000_000


def _store(
    *,
    cap: int = 8,
    html_cap: int = 8,
    render_cache_bytes: int = _LARGE_BUDGET,
    chart_cache_bytes: int = _LARGE_BUDGET,
) -> ArtifactStore:
    return ArtifactStore(
        cap,
        html_cap=html_cap,
        render_cache_bytes=render_cache_bytes,
        chart_cache_bytes=chart_cache_bytes,
    )


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_nonpositive_cap(bad: int) -> None:
    # cap 0 would drop every render immediately; cap < 0 would raise on the first eviction. Match
    # "cap must" (not bare "cap") so this stays distinct from the html_cap guard's message.
    with pytest.raises(ValueError, match="cap must"):
        ArtifactStore(
            bad,
            html_cap=1,
            render_cache_bytes=1,
            chart_cache_bytes=1,
        )


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_nonpositive_html_cap(bad: int) -> None:
    # The chart LRU has the same non-positive failure modes as the render LRU; cap=1 is valid so
    # the html_cap guard is what fires.
    with pytest.raises(ValueError, match="html_cap must"):
        ArtifactStore(
            1,
            html_cap=bad,
            render_cache_bytes=1,
            chart_cache_bytes=1,
        )


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("render_cache_bytes", {"render_cache_bytes": 0, "chart_cache_bytes": 1}),
        ("render_cache_bytes", {"render_cache_bytes": -1, "chart_cache_bytes": 1}),
        ("chart_cache_bytes", {"render_cache_bytes": 1, "chart_cache_bytes": 0}),
        ("chart_cache_bytes", {"render_cache_bytes": 1, "chart_cache_bytes": -1}),
    ],
)
def test_rejects_nonpositive_byte_caps(field: str, kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match=field):
        ArtifactStore(1, html_cap=1, **kwargs)


def test_shared_spec_survives_until_last_referencing_render_evicts() -> None:
    store = _store(cap=1, html_cap=1)
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
    store = _store(html_cap=1)
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
    store = _store(cap=1)
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
    store = _store(html_cap=2)
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
    store = _store(html_cap=2)
    store.put_chart(_A, b"<html>A</html>")
    store.put_chart(_B, b"<html>B</html>")
    assert store.chart(_A) == b"<html>A</html>"  # READ refreshes A -> B is now oldest
    store.put_chart(_C, b"<html>C</html>")  # evicts the oldest, B -- not the just-read A
    assert store.chart(_B) is None  # fails if chart() skips move_to_end (A would evict instead)
    assert store.chart(_A) == b"<html>A</html>"
    assert store.chart(_C) == b"<html>C</html>"


def test_render_byte_boundary_and_oversize_replacement_are_atomic() -> None:
    exact = _store(render_cache_bytes=5)
    exact.put(plot_id=_A, cert_bytes=b"AA", spec_id=_S, spec_bytes=b"SSS")
    assert exact.certificate(_A) == b"AA"

    store = _store(cap=2, render_cache_bytes=5)
    store.put(plot_id=_A, cert_bytes=b"A", spec_id=_S, spec_bytes=b"S")
    store.put(plot_id=_B, cert_bytes=b"B", spec_id=_T, spec_bytes=b"T")

    # This over-limit replacement of oldest A must neither replace nor refresh it; C then makes A
    # (not B) the sole count/byte eviction victim.
    with pytest.raises(ValueError, match="render payload bytes 6 exceed cache budget 5"):
        store.put(plot_id=_A, cert_bytes=b"A" * 5, spec_id=_S, spec_bytes=b"S")
    store.put(plot_id=_C, cert_bytes=b"C", spec_id="9" * 64, spec_bytes=b"X")
    assert store.certificate(_A) is None
    assert store.certificate(_B) == b"B"
    assert store.certificate(_C) == b"C"


def test_chart_byte_boundary_and_oversize_replacement_are_atomic() -> None:
    store = _store(html_cap=2, chart_cache_bytes=5)
    store.put_chart(_A, b"A")
    store.put_chart(_B, b"B")
    with pytest.raises(ValueError, match="chart payload bytes 6 exceed cache budget 5"):
        store.put_chart(_A, b"A" * 6)
    store.put_chart(_C, b"C" * 5)  # exact boundary; untouched oldest A evicts first
    assert store.chart(_A) is None
    assert store.chart(_B) is None  # byte ceiling then requires a second oldest eviction
    assert store.chart(_C) == b"C" * 5


def test_shared_spec_counts_once_under_render_byte_ceiling() -> None:
    # Unique payload = one 3-byte spec + two 2-byte certs = 7. Counting the shared spec twice
    # would evict A prematurely. A third cert crosses by 2 and releases only that evicted cert.
    store = _store(render_cache_bytes=7)
    store.put(plot_id=_A, cert_bytes=b"AA", spec_id=_S, spec_bytes=b"SSS")
    store.put(plot_id=_B, cert_bytes=b"BB", spec_id=_S, spec_bytes=b"SSS")
    assert store.certificate(_A) == b"AA"
    assert store.certificate(_B) == b"BB"
    store.put(plot_id=_C, cert_bytes=b"CC", spec_id=_S, spec_bytes=b"SSS")
    # The reads above made B newer than A; C therefore evicts A and leaves 3 + 2 + 2 = 7.
    assert store.certificate(_A) is None
    assert store.certificate(_B) == b"BB"
    assert store.certificate(_C) == b"CC"
    assert store.spec(_S) == b"SSS"


def test_render_replacement_adjusts_both_accounting_directions() -> None:
    store = _store(cap=3, render_cache_bytes=8)
    store.put(plot_id=_A, cert_bytes=b"AA", spec_id=_S, spec_bytes=b"SS")
    store.put(plot_id=_B, cert_bytes=b"BB", spec_id=_S, spec_bytes=b"SS")
    store.put(plot_id=_A, cert_bytes=b"A", spec_id=_S, spec_bytes=b"SS")  # total 5
    store.put(plot_id=_C, cert_bytes=b"CCC", spec_id=_S, spec_bytes=b"SS")  # exact total 8
    # Missing the replacement release overcounts and evicts B here. This read also makes B newest.
    assert store.certificate(_B) == b"BB"

    store.put(plot_id=_A, cert_bytes=b"AAAA", spec_id=_S, spec_bytes=b"SS")
    # Growth takes total 8 -> 11. A is newest; C is oldest after the B read, so C alone evicts and
    # releases 3 bytes. Missing the replacement addition leaves C resident.
    assert store.certificate(_C) is None
    assert store.certificate(_B) == b"BB"
    assert store.certificate(_A) == b"AAAA"


def test_live_shared_spec_replacement_adjusts_its_single_payload() -> None:
    store = _store(render_cache_bytes=9)
    store.put(plot_id=_A, cert_bytes=b"A", spec_id=_S, spec_bytes=b"SS")
    store.put(plot_id=_B, cert_bytes=b"B", spec_id=_S, spec_bytes=b"SS")
    # Latest bytes win for the one shared identity: 5-byte spec + two certs = 7.
    store.put(plot_id=_A, cert_bytes=b"A", spec_id=_S, spec_bytes=b"S" * 5)
    store.put(plot_id=_C, cert_bytes=b"CCC", spec_id=_S, spec_bytes=b"S" * 5)
    # Total 10 crosses by one, so oldest B evicts; failing to account the +3 spec delta keeps B.
    assert store.certificate(_B) is None
    assert store.certificate(_A) == b"A"
    assert store.certificate(_C) == b"CCC"
    assert store.spec(_S) == b"S" * 5


def test_chart_replacement_adjusts_both_accounting_directions() -> None:
    store = _store(html_cap=3, chart_cache_bytes=8)
    store.put_chart(_A, b"AAA")
    store.put_chart(_B, b"BBB")
    store.put_chart(_A, b"A")  # replacement shrinks total 6 -> 4
    store.put_chart(_C, b"CCCC")  # exact total 8; missing release evicts B
    assert store.chart(_B) == b"BBB"  # read refresh: order A,C,B
    store.put_chart(_A, b"AAAAA")  # total 8 -> 12; oldest C releases 4
    assert store.chart(_C) is None
    assert store.chart(_B) == b"BBB"
    assert store.chart(_A) == b"AAAAA"


def test_render_count_and_byte_caps_evict_independently() -> None:
    count_store = _store(cap=2)
    count_store.put(plot_id=_A, cert_bytes=b"A", spec_id=_S, spec_bytes=b"S")
    count_store.put(plot_id=_B, cert_bytes=b"B", spec_id=_T, spec_bytes=b"T")
    count_store.put(plot_id=_C, cert_bytes=b"C", spec_id="9" * 64, spec_bytes=b"X")
    assert count_store.certificate(_A) is None
    assert count_store.certificate(_B) == b"B"
    assert count_store.certificate(_C) == b"C"

    byte_store = _store(cap=8, render_cache_bytes=8)
    byte_store.put(plot_id=_A, cert_bytes=b"AA", spec_id=_S, spec_bytes=b"SS")
    byte_store.put(plot_id=_B, cert_bytes=b"BB", spec_id=_T, spec_bytes=b"TT")
    byte_store.put(plot_id=_C, cert_bytes=b"CCC", spec_id="9" * 64, spec_bytes=b"XXX")
    # 4 + 4 + 6 requires two oldest evictions even though count 3 is below cap 8.
    assert byte_store.certificate(_A) is None
    assert byte_store.certificate(_B) is None
    assert byte_store.certificate(_C) == b"CCC"


def test_render_reput_and_read_refresh_recency() -> None:
    reput = _store(cap=2)
    reput.put(plot_id=_A, cert_bytes=b"A", spec_id=_S, spec_bytes=b"S")
    reput.put(plot_id=_B, cert_bytes=b"B", spec_id=_T, spec_bytes=b"T")
    reput.put(plot_id=_A, cert_bytes=b"A", spec_id=_S, spec_bytes=b"S")
    reput.put(plot_id=_C, cert_bytes=b"C", spec_id="9" * 64, spec_bytes=b"X")
    assert reput.certificate(_B) is None
    assert reput.certificate(_A) == b"A"

    read = _store(cap=2)
    read.put(plot_id=_A, cert_bytes=b"A", spec_id=_S, spec_bytes=b"S")
    read.put(plot_id=_B, cert_bytes=b"B", spec_id=_T, spec_bytes=b"T")
    assert read.certificate(_A) == b"A"
    read.put(plot_id=_C, cert_bytes=b"C", spec_id="9" * 64, spec_bytes=b"X")
    assert read.certificate(_B) is None
    assert read.certificate(_A) == b"A"
