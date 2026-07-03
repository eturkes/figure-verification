# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Bounded in-memory artifact store for verified renders (M2.3).

A verify-and-render success stores two canonical byte blobs — the certificate (keyed by
its content-addressed plot_id) and the canonical spec (keyed by spec_id) — so the
retrieval GETs can serve them verbatim. In-memory only: provenance/replay to disk is M5.

Bounded LRU over RENDERS: the OrderedDict is keyed by plot_id and capped at store_cap;
the oldest render evicts on overflow, dropping its spec mapping with it. plot_id <-> spec_id
is 1:1 under stable trusted config — a fixed spec under a fixed data_dir + manifest + TCB
determines every certificate field, hence a single plot_id — so evicting a render can drop
its spec_id with no refcount. (The lone exception is an operator mutating the trusted
manifest between two renders of one spec: two plot_ids would then share a spec_id, and
evicting one could 404 the other's spec GET while its certificate still resolves. That is
the same trusted-config-stable precondition checks.py rests on, out of the model's reach.)

Thread-safe: the CPU-bound verify-and-render runs in a worker thread (sync_to_thread) and
the retrieval GETs read on the event loop, so every access takes the lock. The lock is held
only for O(1) dict operations, never across a render.
"""

import threading
from collections import OrderedDict

import msgspec


class _Entry(msgspec.Struct, frozen=True, kw_only=True):
    """One stored render: the certificate bytes plus the spec_id whose spec bytes evict with it."""

    cert_bytes: bytes
    spec_id: str


class ArtifactStore:
    """A thread-safe, store_cap-bounded LRU over verified renders. See the module docstring."""

    def __init__(self, cap: int) -> None:
        self._cap = cap
        self._lock = threading.Lock()
        self._renders: OrderedDict[str, _Entry] = OrderedDict()
        self._specs: dict[str, bytes] = {}

    def put(self, *, plot_id: str, cert_bytes: bytes, spec_id: str, spec_bytes: bytes) -> None:
        """Store a verified render's artifacts, evicting the oldest render past store_cap.

        Idempotent: a repeat plot_id (the render is content-addressed, so the bytes are
        identical) only refreshes LRU recency. On a fresh insert the spec mapping is added and,
        while over cap, the oldest render pops and its spec mapping drops with it.
        """
        with self._lock:
            if plot_id in self._renders:
                self._renders.move_to_end(plot_id)
                return
            self._renders[plot_id] = _Entry(cert_bytes=cert_bytes, spec_id=spec_id)
            self._specs[spec_id] = spec_bytes
            while len(self._renders) > self._cap:
                _, evicted = self._renders.popitem(last=False)
                self._specs.pop(evicted.spec_id, None)

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
