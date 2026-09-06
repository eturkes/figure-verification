---
paths:
  - "corpus/**"
  - "capture/**"
---

# Python corpus

- **`corpus/` holds NO Python.** `tests/corpus.py` owns the top-level module name under pytest's
  `pythonpath = ["tests", "."]` (tests FIRST) and a `corpus` package additionally raises a duplicate
  module under mypy. Code lives in the repo-root package `capture/`; `corpus/python/` is pure data.
- Layout (fixed at M12.5): `corpus/python/design/manifest.json` 24+24 · `heldout/manifest.json`
  20+20 (ruling 7: never generated against until the M13 config is frozen; subset design + tuning
  read the design set + its captures alone) · `sentinels.json` (2 public demo prompts, outside both
  sets + both denominators) · `capture_prompt_v1.txt` · `captures/<run>/` records, TRACKED.
- `capture/corpus.py` is the SOLE implementation of predicates C1–C10 (`.agent/contracts/m12u5.md`),
  the strict schema, the loader, `render_capture_prompt` and the closed idiom vocabulary.
  `python -m capture.corpus` grades the committed corpus, rc 1 on any failure;
  `tests/test_python_corpus.py` calls the predicates and restates none of them.
- The capture prompt is byte-pinned by a hand-stated sha256 literal in `capture/corpus.py`; every
  capture record carries it, so editing the template invalidates every capture taken before it.
  ONE user message, zero few-shots, `/mnt/uploads/<dataset>` path, matplotlib named as the output
  MEDIUM, CSV-reading library deliberately unnamed so captures observe the model's own idiom choice.
- Extending the corpus: seed rows with `unknown-<id>` in `prompt` alone, add the affected predicate
  ids to `_SEED_PENDING` in `tests/test_python_corpus.py` so the seed commit gates green, and empty
  it again at the fill. `id`/`category`/`idiom`/`dataset_name` are assigned by script before
  dispatch, which is what makes idiom coverage and dataset balance hold before authoring starts.
- Crypto seal/escrow/contamination batteries = REJECTED over-engineering (ruling 7) — do not
  re-propose. Held-out discipline is instruction-level and binds GENERATION plus SUBSET DESIGN, not
  structural review at authoring time.
- M13 static guard: no prompt text, prompt hash, sample-specific field list or raw model reply may
  appear in production code — one committed search test; admission is justified by AST idiom class.
