# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Bounded in-memory artifact store for verified renders (M2.3).

A verify-and-render success stores two canonical byte blobs — the certificate (keyed by
its content-addressed plot_id) and the canonical spec (keyed by spec_id) — so the
retrieval GETs can serve them verbatim. In-memory only: provenance/replay to disk is M5.

Bounded LRU over RENDERS: the OrderedDict is keyed by plot_id and capped at store_cap; the
oldest render evicts on overflow. plot_id <-> spec_id is 1:1 under stable trusted config — a
fixed spec under a fixed data_dir + manifest + TCB determines every certificate field, hence
a single plot_id. Two plot_ids share one spec_id only when an operator mutates the trusted
manifest between two renders of the same spec (the certificate's manifest_hash changes, its
spec_hash does not), so the spec bytes are held once under a live-reference count and drop
only when the LAST render referencing them evicts. A stored render's spec GET thus always
resolves — retrieval consistency holds unconditionally, not merely under the 1:1 precondition
checks.py rests on.

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
    """A thread-safe, store_cap-bounded LRU over verified renders. See the module docstring."""

    def __init__(self, cap: int) -> None:
        if cap < 1:
            # The store's own precondition (Settings guards store_cap too): a non-positive
            # cap would drop every render at once or crash on the first eviction.
            msg = f"cap must be >= 1, got {cap}"
            raise ValueError(msg)
        self._cap = cap
        self._lock = threading.Lock()
        self._renders: OrderedDict[str, _Entry] = OrderedDict()
        # spec_id -> canonical spec bytes, held once; _spec_refs counts the live renders
        # referencing each spec_id so a spec drops only when the last of them evicts.
        self._specs: dict[str, bytes] = {}
        self._spec_refs: dict[str, int] = {}

    def put(self, *, plot_id: str, cert_bytes: bytes, spec_id: str, spec_bytes: bytes) -> None:
        """Store a verified render's artifacts, evicting the oldest render past store_cap.

        Idempotent: a repeat plot_id (the render is content-addressed, so the bytes are
        identical) only refreshes LRU recency. On a fresh insert the spec mapping is added and a
        spec reference taken; while over cap, the oldest render pops and its spec mapping drops
        once no live render still references it.
        """
        with self._lock:
            if plot_id in self._renders:
                self._renders.move_to_end(plot_id)
                return
            self._renders[plot_id] = _Entry(cert_bytes=cert_bytes, spec_id=spec_id)
            self._specs[spec_id] = spec_bytes
            self._spec_refs[spec_id] = self._spec_refs.get(spec_id, 0) + 1
            while len(self._renders) > self._cap:
                _, evicted = self._renders.popitem(last=False)
                sid = evicted.spec_id
                if self._spec_refs[sid] > 1:
                    self._spec_refs[sid] -= 1  # another live render still needs this spec
                else:
                    del self._spec_refs[sid]
                    del self._specs[sid]

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
