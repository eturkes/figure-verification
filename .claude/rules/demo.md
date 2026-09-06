---
paths:
  - "demo/**"
---

# Demo + walkthrough mechanics

- **The shared `run_walkthrough`-shaped loop reports PASS over an EMPTY scenario tuple.** An emptied registry exits 0 with a 0/0 report while every gate stays green ⇒ every scenario registry needs its exact NAME set AND its cardinality pinned as hand-stated literals. Current registries: `demo/walkthrough.py` `_SCENARIOS` (13 dataset) + `demo/formula_walkthrough.py` `_FORMULA_SCENARIOS` (5: direct flow · proposed flow · certificate check shape · failed attempt audit cli · archive integrity guards).
- **A BY-CONSTRUCTION row deletion must be applied consistently or not at all.** Deleting a mode twin because "the guard reads no source column, so the dataset pin covers both" also deletes any SIBLING guard that faults ahead of mode dispatch — for M9.13b's aggregate, schema damage (`_replay_lowest` calls `lowest_verified_attempt_id` BEFORE mode dispatch) fell to the same argument as tampered publication, leaving one guard and dissolving the named gap, which was the THREE guards JOINED. Ruling: where the assured property is the JOIN, mode-neutrality of an individual leg is NOT grounds to delete it; record the residual instead (M9.13b's formula carrier is incidental to the publication guard it exercises).
- **The socket driver must never import `demo/formula_walkthrough.py`** — that module imports `litestar`, `TestClient`, `unittest.mock.patch` and `create_app` at MODULE scope, contradicting `demo/e2e.py`'s loopback-TCP-only claim at import level, called or not. Socket-transport formula logic is hand-written against `verifier.attestation`/`canon`/`vcert` plus the `demo.walkthrough` seam, and that twin is STRICTER than the in-process helper, which reaches into `app.state["identity"]` and passes neither `require_canonical_envelope` nor `expected_keyid_hint`. Binds M10.
