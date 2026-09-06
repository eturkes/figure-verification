---
paths:
  - "src/verifier/schema.py"
  - "src/verifier/ingest.py"
  - "src/verifier/canon.py"
  - "src/verifier/service/models.py"
  - "schema/*.json"
---

# msgspec pinned behaviours

Transcribe, never re-derive; `schema.py` cites these BY NUMBER.

1. `frozen`/`forbid_unknown_fields` propagate to subclasses at RUNTIME but `kw_only` does NOT, and mypy reads each class's own kwargs ⇒ EVERY concrete struct repeats `frozen=True` AND `kw_only=True`. `__struct_config__` does not expose `kw_only` ⇒ a separate test asserts positional construction raises.
2. A tagged union needs explicit `tag_field` + per-member `tag`, else msgspec defaults to the class name under field `type`.
3. Strict mode rejects float→int and bool→int but ACCEPTS JSON float→`Decimal` ⇒ model spec numerics as `int | str`, decimals as strings, ints bounded to signed int64.
4. Duplicate object keys silently LAST-WIN with no switch ⇒ reject via a stdlib `json.loads(raw, object_pairs_hook=…)` pre-scan.
5. `msgspec.json.schema()` emits NO `$schema`, is deterministic cross-process, sorts `Literal` enums alphabetically, renders a tagged union as `anyOf` + discriminator, maps `forbid_unknown_fields` → `additionalProperties:false`. The exported golden is ADVISORY, not the gate — JSON Schema `integer` admits `1.0`/`1e3` that strict decode rejects.
6. `msgspec.field(name=…)` renames in decode + encode + schema; when the attribute is itself named `field`, call `msgspec.field(…)` via the module or mypy reads the annotation as shadowing.
7. A frozen struct holding a `list` is only SHALLOWLY immutable and unhashable ⇒ model every JSON array as a bounded `tuple[T, ...]`.
8. `Encoder(order="deterministic")` keeps struct field order while sorting dict/set keys, renders Decimal→string, does NO Unicode normalization.
9. `Decoder.decode` raises the BUILTIN `UnicodeDecodeError` on invalid UTF-8 inside a JSON string ⇒ any guard over UNTRUSTED bytes must catch it alongside `DecodeError`/`ValidationError`, or the fault escapes its intended mapping.
