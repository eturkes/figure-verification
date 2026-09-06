---
paths:
  - "src/verifier/service/archive.py"
  - "src/verifier/replay.py"
  - "src/verifier/service/replay.py"
---

# Attempt-route totality

- **A new `AttemptRoute` member must reach all NINE route surfaces**, each with hand-stated exact-set literals + its own dedicated mutant: enum widening alone type-checks while a map silently goes missing. The nine = `service/archive.py` `AttemptRoute` enum · its three route-keyed maps `_ROUTE_PLOT_SOURCES`, `_ROUTE_READS_DATASET_INPUTS`, `_ROUTE_MODEL_ROLES` · the pre-sign reply↔raw-spec identity guard `_validate_attempt_outcome` · the import-pure `replay.py` mirror's four, route literal `type _AttemptRoute`, `_EXPECTED_MODEL_ROLES`, `_ROUTE_ATTACHES_DATASET_PLOT`, `_ROUTE_ATTACHES_FORMULA_PLOT`. Every route-keyed map is pinned total by `set(<map>) == set(AttemptRoute)`, which kills a missing entry even where no behavioural test reaches the route. `_ROUTE_ATTACHES_PLOT` was SPLIT into the two attach maps and no longer exists — the archived M9.8a body still names it, so never copy it forward. Outcome-keyed maps stay source-neutral; `_PLOT_SOURCE_KIND_BY_BINDING_ROLES` derives the source from signed binding-role TOPOLOGY.
- **REJECTED — a second `_ROUTE_ALLOWED_OUTCOMES` map for the proposer.** The formula proposer keeps its OWN narrowing selector that refuses dataset-only outcomes then delegates. Strict schema decode admits grammar-shaped invalid expressions ON PURPOSE; parser `formula.names_allowed` owns those refusals.
