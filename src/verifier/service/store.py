# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Count- and payload-byte-bounded chart artifact store (M4.1b, M5.1j).

Only offline chart HTML pages keyed by ``plot_id`` live in this process-local store. Verified
certificate, spec, and key artifacts are committed to the SQLite archive before cache publication;
their public GETs use that archive as authority. Chart liveness deliberately remains ephemeral
across eviction and process restart.

The single LRU has an entry-count ceiling (``html_cap``) and an exact logical-payload ceiling
(``chart_cache_bytes``). Replacement and reads refresh recency, and replacement adjusts the
resident byte total before eviction. A chart larger than the entire byte ceiling is rejected before
mutation; service ``Settings`` makes that branch unreachable for policy-conforming pipeline
outputs. The total covers resident ``bytes`` payloads, not Python-container or process memory.

A chart may therefore 404 after eviction or restart while its archive-durable certificate, spec,
and key continue to resolve. A served chart was verified at render time and is immutable;
certificate liveness is not a gate for the chart cache.

Thread-safe: render and replay workers publish chart pages while chart GET workers read them. Every
access holds the lock only for O(1) ordered-dict operations, never across rendering or archive I/O.
"""

import threading
from collections import OrderedDict


class ArtifactStore:
    """Thread-safe count- and logical-payload-bounded chart LRU."""

    def __init__(self, *, html_cap: int, chart_cache_bytes: int) -> None:
        if html_cap < 1:
            # Settings guards html_cap too, but the store owns this precondition.
            msg = f"html_cap must be >= 1, got {html_cap}"
            raise ValueError(msg)
        if chart_cache_bytes < 1:
            msg = f"chart_cache_bytes must be >= 1, got {chart_cache_bytes}"
            raise ValueError(msg)
        self._html_cap = html_cap
        self._chart_cache_bytes = chart_cache_bytes
        self._chart_bytes = 0
        self._lock = threading.Lock()
        self._charts: OrderedDict[str, bytes] = OrderedDict()

    def put_chart(self, plot_id: str, chart_html: bytes) -> None:
        """Store/replace a chart; evict oldest entries until both ceilings hold.

        The caller verifies and archives the render before publication, so this process-local cache
        does not require a companion certificate entry. A repeat ``plot_id`` refreshes recency and
        replaces its immutable content-addressed bytes.
        """
        item_bytes = len(chart_html)
        if item_bytes > self._chart_cache_bytes:
            msg = f"chart payload bytes {item_bytes} exceed cache budget {self._chart_cache_bytes}"
            raise ValueError(msg)
        with self._lock:
            replaced = self._charts.pop(plot_id, None)
            if replaced is not None:
                self._chart_bytes -= len(replaced)
            self._charts[plot_id] = chart_html
            self._chart_bytes += item_bytes
            while len(self._charts) > self._html_cap or self._chart_bytes > self._chart_cache_bytes:
                _, evicted = self._charts.popitem(last=False)
                self._chart_bytes -= len(evicted)

    def chart(self, plot_id: str) -> bytes | None:
        """Return chart HTML for ``plot_id`` and refresh recency, or ``None`` on a miss."""
        with self._lock:
            chart_html = self._charts.get(plot_id)
            if chart_html is None:
                return None
            self._charts.move_to_end(plot_id)
            return chart_html
