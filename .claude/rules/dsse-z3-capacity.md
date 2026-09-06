---
paths:
  - "src/verifier/attestation.py"
  - "src/verifier/vcert.py"
  - "src/verifier/formal.py"
  - "src/verifier/service/admission.py"
---

# DSSE · z3 · capacity

- Z3 contexts are NOT thread-safe ⇒ every worker invocation owns an explicit `Context`.
- DSSE: verify signature + payload type, then parse the SAME verified payload byte buffer; never re-parse the envelope.
- A cancelled request keeps its admission permit until the uncancellable worker exits ⇒ it still occupies capacity. Canonical `workers=1` = one gate; extra processes multiply the policy instead of sharing it.
- Envelope ceilings carry base64+JSON headroom — `envelope_byte_limit(x, payload_type=…)` ≈ 1.88·x ⇒ a probe wanting the ceiling to bite cannot use `len(payload) - 1`. Both certificate MIMEs are 51 bytes ⇒ the two ceilings are NUMERICALLY EQUAL and only an argument spy proves which MIME was selected.
