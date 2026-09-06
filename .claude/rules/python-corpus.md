---
paths:
  - "corpus/**"
---

# Python corpus

- Layout (M12.5 fixes it): `corpus/python/` — `design/` manifest+prompts (24+24; ids, category+idiom labels, dataset binding) · `heldout/` 20+20 PLAINTEXT (ruling 7: read only at the frozen-config acceptance run; subset design + tuning read the design set + its captures alone) · `sentinels.json` (2 public demo prompts, outside both sets + both denominators) · `captures/<run>/` records. Capture prompt = ruling 6 (task/format/dataset-binding only, zero few-shots, byte-pinned, sha in every record).
- ONE structural validator: counts · unique ids · category balance · design↔held-out prompt disjointness · zero admission vocabulary in any prompt (ruling 6). Crypto seal/escrow/contamination batteries = REJECTED over-engineering (ruling 7) — do not re-propose.
- M13 static guard: no prompt text, prompt hash, sample-specific field list or raw model reply may appear in production code — one committed search test; admission is justified by AST idiom class.
