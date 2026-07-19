# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""ArtifactStore chart-LRU count, byte-accounting, and recency witnesses.

Only verified chart HTML remains process-local. These tests pin the store-owned positive-cap
preconditions, independent count and exact logical-payload ceilings, pre-mutation oversize
rejection, replacement accounting in both directions, and read/re-put recency refreshes.
"""

import pytest

from verifier.service.store import ArtifactStore

_A, _B, _C = ("a" * 64, "b" * 64, "c" * 64)
_LARGE_BUDGET = 1_000_000


def _store(
    *,
    html_cap: int = 8,
    chart_cache_bytes: int = _LARGE_BUDGET,
) -> ArtifactStore:
    return ArtifactStore(html_cap=html_cap, chart_cache_bytes=chart_cache_bytes)


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_nonpositive_html_cap(bad: int) -> None:
    with pytest.raises(ValueError, match="html_cap must"):
        ArtifactStore(html_cap=bad, chart_cache_bytes=1)


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_nonpositive_chart_cache_bytes(bad: int) -> None:
    with pytest.raises(ValueError, match="chart_cache_bytes"):
        ArtifactStore(html_cap=1, chart_cache_bytes=bad)


def test_chart_count_cap_evicts_oldest() -> None:
    store = _store(html_cap=1)
    store.put_chart(_A, b"<html>A</html>")
    assert store.chart(_A) == b"<html>A</html>"

    store.put_chart(_B, b"<html>B</html>")
    assert store.chart(_A) is None
    assert store.chart(_B) == b"<html>B</html>"

    store.put_chart(_A, b"<html>A</html>")
    assert store.chart(_B) is None
    assert store.chart(_A) == b"<html>A</html>"


def test_put_chart_refreshes_recency_of_present_key() -> None:
    store = _store(html_cap=2)
    store.put_chart(_A, b"<html>A</html>")
    store.put_chart(_B, b"<html>B</html>")
    store.put_chart(_A, b"<html>A</html>")
    store.put_chart(_C, b"<html>C</html>")
    assert store.chart(_B) is None
    assert store.chart(_A) == b"<html>A</html>"
    assert store.chart(_C) == b"<html>C</html>"


def test_chart_read_refreshes_recency() -> None:
    store = _store(html_cap=2)
    store.put_chart(_A, b"<html>A</html>")
    store.put_chart(_B, b"<html>B</html>")
    assert store.chart(_A) == b"<html>A</html>"
    store.put_chart(_C, b"<html>C</html>")
    assert store.chart(_B) is None
    assert store.chart(_A) == b"<html>A</html>"
    assert store.chart(_C) == b"<html>C</html>"


def test_chart_byte_boundary_and_oversize_replacement_are_atomic() -> None:
    store = _store(html_cap=2, chart_cache_bytes=5)
    store.put_chart(_A, b"A")
    store.put_chart(_B, b"B")
    with pytest.raises(ValueError, match="chart payload bytes 6 exceed cache budget 5"):
        store.put_chart(_A, b"A" * 6)
    store.put_chart(_C, b"C" * 5)
    assert store.chart(_A) is None
    assert store.chart(_B) is None
    assert store.chart(_C) == b"C" * 5


def test_chart_replacement_adjusts_both_accounting_directions() -> None:
    store = _store(html_cap=3, chart_cache_bytes=8)
    store.put_chart(_A, b"AAA")
    store.put_chart(_B, b"BBB")
    store.put_chart(_A, b"A")
    store.put_chart(_C, b"CCCC")
    assert store.chart(_B) == b"BBB"

    store.put_chart(_A, b"AAAAA")
    assert store.chart(_C) is None
    assert store.chart(_B) == b"BBB"
    assert store.chart(_A) == b"AAAAA"


def test_chart_count_and_byte_caps_evict_independently() -> None:
    count_store = _store(html_cap=2)
    count_store.put_chart(_A, b"A")
    count_store.put_chart(_B, b"B")
    count_store.put_chart(_C, b"C")
    assert count_store.chart(_A) is None
    assert count_store.chart(_B) == b"B"
    assert count_store.chart(_C) == b"C"

    byte_store = _store(html_cap=8, chart_cache_bytes=8)
    byte_store.put_chart(_A, b"AA")
    byte_store.put_chart(_B, b"BB")
    byte_store.put_chart(_C, b"CCCCCC")
    assert byte_store.chart(_A) is None
    assert byte_store.chart(_B) == b"BB"
    assert byte_store.chart(_C) == b"CCCCCC"
