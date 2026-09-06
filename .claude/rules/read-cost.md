---
paths:
  - ".serena/project.yml"
  - ".gitignore"
  - ".agent/*_design.md"
---

# Read cost control + blueprint-recipe discharge

- Mechanism → `CLAUDE.md`. The project ships NO `permissions.deny` rule and `.claude/settings.json` is DELETED, not emptied: `permissions.deny` is Bash-only upstream, and a path-keyed `Read()` rule gates `Bash` by static command text — existence alone escalates every command whose cwd it cannot resolve into a halting prompt. `.serena/project.yml` `ignored_paths` narrows Serena ALONE (never `Read`/`Bash`) and holds the heavy tracked non-source trio: `LICENSE`, `uv.lock` (slash-free ⇒ catches `model_backend/runtime/uv.lock` too), `**/*.ttf` (759,720 B `DejaVuSans.ttf`). `schema/openapi.json` stays INDEXED — units cite it as a golden. No LSP-hostile-but-readable path exists here: every served format answers `documentSymbol`, and an unserved extension (`data/*.csv`) errors instantly rather than stalling. Heavy GITIGNORED state stays out of `rg`/Serena/`git` through `.gitignore` and is reached by bounded query (`wc -c`, `rg -c`, `jq '.<path>|length'`), never a whole-file `Read`: `.verifier-state/` (Ed25519 `signing.key` + `archive.sqlite3` — the key has no read use; never echo it), `.webui-data/` binaries, `bench/reports/details.jsonl` (verbatim prompts/replies; `report.json` = the aggregate), `.launch-logs/`, `.tokensave/`, `**/.serena/cache/`. Sync `ignored_paths` as new heavy tracked data lands; no project gate names an ignored path.
- Persisted blueprint recipes drift silently from their source spec ⇒ cross-check each recipe against its spec section verbatim before implementing, never from memory. DISCHARGE: a recipe stamped "source-VERIFIED, drift-check DISCHARGED" carries the baseline commit OID of its certified consumed surface ⇒ confirm those files byte-UNCHANGED (`git diff --exit-code <baseline-OID> -- <files>`), then transcribe. Trust boundary: the discharge propagates the one-time stamp unchecked, so a transcription error made while stamping survives every later no-drift check.
