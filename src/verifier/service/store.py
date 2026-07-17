# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Count- and payload-byte-bounded artifact store (M2.3, M4.1b, M5.1j).

A verified render contributes three canonical byte blobs: the signed DSSE VCert envelope (keyed
by its content-addressed plot_id) and the canonical spec (keyed by spec_id) are each served
verbatim by a retrieval GET, as is the signed-provenance chart HTML page (keyed by plot_id) at
GET /chart/{plot_id}. These caches are in-memory only; the independent archive already retains
durable signed attempts + plot bundles, while durable HTTP retrieval/replay follows later.

TWO independent bounded LRUs, each with count + exact logical-payload ceilings:

- RENDERS (store_cap + render_cache_bytes), keyed by plot_id, holds the certificate bytes + the
  spec_id each render references. Its payload total is every certificate plus each live canonical
  spec blob ONCE, regardless of reference count; the oldest render evicts until both ceilings hold.
  plot_id <-> spec_id is 1:1 under stable trusted config + signer — a fixed spec under a fixed
  data_dir + manifest + TCB + signing key determines one envelope and plot_id. Two plot_ids can
  share one spec_id when an operator rotates the signer or mutates the trusted manifest (the
  envelope/certificate changes, its spec_hash does not), so the spec bytes are held once under a
  live-reference count and drop only when the LAST render referencing them evicts. A stored
  render's spec GET thus always resolves — retrieval consistency holds unconditionally, not
  merely under the 1:1 precondition checks.py rests on.
- CHARTS (html_cap + chart_cache_bytes), keyed by plot_id, holds the offline chart HTML pages.
  Each inlines the whole Vega bundle (~MB), so this LRU is count-bounded far tighter than the
  render LRU (html_cap << store_cap by default) and evicts on its OWN recency.

Replacement refreshes recency and adjusts payload totals before eviction. A single render pair
(certificate + spec) or chart larger than its entire byte ceiling is rejected before mutation;
service ``Settings`` makes those branches unreachable for policy-conforming pipeline outputs.
These are exact resident ``bytes`` payload totals, not Python-container/process-memory bounds.

The two LRUs evict independently, so BOTH mixed states are reachable and accepted: a chart 404s
while its certificate still lives (the common case, html_cap << store_cap), and — under
chart-only access, since chart() refreshes only the chart LRU — a certificate 404s while its
chart still lives. Intended: a served chart was verified at render time and is immutable, so it
needs no live certificate; the certificate stays the canonical provenance artifact, NOT a
liveness gate for the chart.

Thread-safe: the CPU-bound verify-and-render runs in a worker thread (sync_to_thread) and
the retrieval GETs read on the event loop, so every access takes the lock. The lock is held
only for O(1) dict operations, never across a render.
"""

import threading
from collections import OrderedDict

import msgspec


class _Entry(msgspec.Struct, frozen=True, kw_only=True):
    """One stored render: its certificate bytes and the spec_id it references in _specs."""

    cert_bytes: bytes
    spec_id: str


class ArtifactStore:
    """Thread-safe count + logical-payload-bounded verified-artifact LRUs."""

    def __init__(
        self,
        cap: int,
        *,
        html_cap: int,
        render_cache_bytes: int,
        chart_cache_bytes: int,
    ) -> None:
        if cap < 1:
            # The store's own precondition (Settings guards store_cap too): a non-positive
            # cap would drop every render at once or crash on the first eviction.
            msg = f"cap must be >= 1, got {cap}"
            raise ValueError(msg)
        if html_cap < 1:
            # Same failure modes for the chart LRU (Settings guards html_cap too).
            msg = f"html_cap must be >= 1, got {html_cap}"
            raise ValueError(msg)
        if render_cache_bytes < 1:
            msg = f"render_cache_bytes must be >= 1, got {render_cache_bytes}"
            raise ValueError(msg)
        if chart_cache_bytes < 1:
            msg = f"chart_cache_bytes must be >= 1, got {chart_cache_bytes}"
            raise ValueError(msg)
        self._cap = cap
        self._html_cap = html_cap
        self._render_cache_bytes = render_cache_bytes
        self._chart_cache_bytes = chart_cache_bytes
        self._render_bytes = 0
        self._chart_bytes = 0
        self._lock = threading.Lock()
        self._renders: OrderedDict[str, _Entry] = OrderedDict()
        # plot_id -> offline chart HTML bytes, on its own LRU (html_cap) that evicts
        # independently of the render LRU (see the module docstring's mixed-state note).
        self._charts: OrderedDict[str, bytes] = OrderedDict()
        # spec_id -> canonical spec bytes, held once; _spec_refs counts the live renders
        # referencing each spec_id so a spec drops only when the last of them evicts.
        self._specs: dict[str, bytes] = {}
        self._spec_refs: dict[str, int] = {}

    def put(self, *, plot_id: str, cert_bytes: bytes, spec_id: str, spec_bytes: bytes) -> None:
        """Store/replace a render; evict oldest entries until both render ceilings hold.

        A repeat ``plot_id`` replaces its payload and refreshes recency (content-addressed service
        calls are byte-identical). ``spec_id`` remains the canonical secondary identity: if a
        caller bends that precondition and supplies new bytes for a live ID, the one shared blob is
        replaced and its size delta is accounted once.
        """
        item_bytes = len(cert_bytes) + len(spec_bytes)
        if item_bytes > self._render_cache_bytes:
            msg = (
                f"render payload bytes {item_bytes} exceed cache budget {self._render_cache_bytes}"
            )
            raise ValueError(msg)
        with self._lock:
            replaced = self._renders.pop(plot_id, None)
            if replaced is not None:
                self._release_render(replaced)

            old_spec = self._specs.get(spec_id)
            if old_spec is None:
                self._render_bytes += len(spec_bytes)
            else:
                self._render_bytes += len(spec_bytes) - len(old_spec)
            self._renders[plot_id] = _Entry(cert_bytes=cert_bytes, spec_id=spec_id)
            self._specs[spec_id] = spec_bytes
            self._spec_refs[spec_id] = self._spec_refs.get(spec_id, 0) + 1
            self._render_bytes += len(cert_bytes)
            while len(self._renders) > self._cap or self._render_bytes > self._render_cache_bytes:
                _, evicted = self._renders.popitem(last=False)
                self._release_render(evicted)

    def _release_render(self, entry: _Entry) -> None:
        """Release one already-removed render and its last-reference spec payload."""
        self._render_bytes -= len(entry.cert_bytes)
        sid = entry.spec_id
        if self._spec_refs[sid] > 1:
            self._spec_refs[sid] -= 1
        else:
            del self._spec_refs[sid]
            self._render_bytes -= len(self._specs.pop(sid))

    def certificate(self, plot_id: str) -> bytes | None:
        """The stored certificate bytes for plot_id (refreshing its LRU recency), or None."""
        with self._lock:
            entry = self._renders.get(plot_id)
            if entry is None:
                return None
            self._renders.move_to_end(plot_id)
            return entry.cert_bytes

    def spec(self, spec_id: str) -> bytes | None:
        """The stored canonical spec bytes for spec_id, or None. Subordinate to its render's LRU
        recency (a spec read does not itself refresh the owning render)."""
        with self._lock:
            return self._specs.get(spec_id)

    def put_chart(self, plot_id: str, chart_html: bytes) -> None:
        """Store/replace a chart; evict oldest entries until both chart ceilings hold.

        Chart LRU only — never touches the render/spec maps. Like put(), the store trusts its
        caller: the render pipeline verifies before calling, so put_chart does not itself require
        a live render/certificate for plot_id (a chart may outlive its certificate — see the
        module docstring's mixed-state note). A repeat plot_id refreshes its recency and replaces
        the (content-addressed, identical) bytes; while over html_cap, the oldest chart page pops.
        Wired into the render pipeline (render_outcome) at M4.1c, and exercised directly here.
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
        """The stored offline chart HTML bytes for plot_id (refreshing its chart-LRU recency),
        or None. Reads the chart LRU ONLY — a chart hit does not refresh the owning render, so a
        certificate can evict while its chart lives (see the module docstring's mixed-state note).
        """
        with self._lock:
            chart_html = self._charts.get(plot_id)
            if chart_html is None:
                return None
            self._charts.move_to_end(plot_id)
            return chart_html
