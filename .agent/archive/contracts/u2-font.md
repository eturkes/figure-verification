# U2 — the Japanese font from the server, not from Open WebUI

Tier **kernel** for the read surface: which server bytes leave for the user's browser has no downstream re-check. Everything after the read keeps its existing re-check: a missing glyph is counted by the reader ⇒ `glyph_missing` (Q44 F3).

## Row

Open WebUI 0.12.3 dropped `static/fonts` + `open_webui.env.FONTS_DIR` (verified at the v0.12.3 tag + wheel) ⇒ `owui_files.py::cjk_font` returns `None` and every figure drawing Japanese text blocks. Red witness (0.12.3, `webui/launch.sh --stub`, `m10u3_demo.mjs … data/clinic_ja.csv ja-clinic-simple 1`): `fail`, status `… (glyph_missing)`. User ruling (session 12, `.agent/spec.md` Upgrade rulings 2): server-side discovery — an admin Valve path, then known CJK font files in the container's system font dirs; sent whole when the server lacks fontTools; none ⇒ Japanese text blocks.

## Predicates

- **D1 order** — `Filter.Valves.cjk_font_path` non-empty ⇒ that file first; then discovery; the first candidate D3 admits wins; none ⇒ `None`.
- **D2 discovery** — walk `/usr/share/fonts` + `/usr/local/share/fonts` (symlinked dirs not followed, symlinked files resolved), at most `_WALK_LIMIT` entries in total; a file counts only when its basename, casefolded, is in the closed ordered `CJK_FONT_FILES` (Japanese-only faces first, then pan-CJK collections whose face 0 is Japanese); order = list rank, then path.
- **D3 admission** — a candidate passes only when `os.stat` shows a regular file of at most `MAX_FONT_BYTES` and its first 4 bytes are an sfnt tag (`00 01 00 00`, `OTTO`, `true`) or a collection tag (`ttcf`); a non-regular file is never opened (a FIFO would block the read thread). Anything else ⇒ next candidate. No non-font byte leaves the server.
- **D4 degrade** — every fault ⇒ next candidate, then `None`; nothing on the degrade path can raise (no log call); the walk + read run off the event loop; `CancelledError` propagates.
- **D5 cut unchanged** — the admitted bytes go through `fonts.py::cut_for` (fontTools importable ⇒ cut; absent, or a collection it cannot load ⇒ whole); trigger `_needs_font` unchanged; reader registration unchanged (a collection draws face 0).
- **D6 envelope** — the filter gains a pydantic `Valves` (admitted root, as the tool's) + `self.valves` in `__init__` (0.12.3 `utils/filter.py::apply_filter_valves` sets valves only on an instance holding both); stdlib otherwise.
- **D7 live** — 0.12.3 + host `NotoSansCJK-Regular.ttc` (19,484,784 B, face 0 = Noto Sans CJK JP) found by discovery: `ja-clinic-simple` passes (red above), `ja-clinic-misleading` blocks `axis_inverted`; PNG inspected; RPC size + wall time recorded.

## Invariants

- Verdicts unchanged wherever a font is found; no new reason; `glyph_missing` stays the only outcome of a missing glyph.
- Admin text (Valve description) = human-facing register (`.claude/rules/human-facing.md`).

## Gate identity

`bash tools/gate.sh`; catalogue `owui_files` rewritten for D1-D4 + `filter` rerun whole (kill names pinned in `tests/test_mutation_catalogues.py`); paste-in pairs regenerated; `.claude/rules/owui.md` Japanese bullet, `.claude/rules/claims.md` trusted list, `docs/admin/README{,.ja}.md`, `docs/verification{,.ja}.md` limits.

## Close (MAIN review; security-flavored read surface ⇒ MAIN alone)

| id | check | verdict | evidence |
|---|---|---|---|
| D1 | Valve first; walk only when unset or no font; fallback | pass | `test_u2_d1_*` (walk spy empty on a usable Valve file; missing, directory, non-font, oversize → discovered font); mutants `u2-configured-ignored`, `u2-walk-always`, `u2-no-fallback` killed |
| D2 | closed ordered list; casefold; rank then path; symlinked dirs unwalked; entry limit | pass | literal `CJK_FONT_FILES` + `_WALK_LIMIT` pinned; `u2-rank-ignored`, `u2-case-sensitive`, `u2-dir-links-followed`, `u2-walk-limit-inclusive` killed |
| D3 | regular file ≤ 32 MiB with an sfnt/`ttcf` tag; FIFO never opened; read cap decides | pass | 10 tag cases (4 admit, 6 near-miss refuse), cap at/past, grow-after-stat, FIFO open spy; `u2-tag-unchecked`, `u2-read-cap-unchecked`, `u2-fifo-opened`, `u2-cap-literal` killed |
| D4 | off-loop; faults → next candidate then `None`; cancellation propagates; no log on degrade | pass | thread spy on `os.walk`; per-family faults on the admin file fall through to discovery; `u2-read-on-loop`, `u2-fault-uncaught` (survived once: the first test faulted every path — rewritten to fault the admin file alone), `u2-cancellation-swallowed`, `u2-outer-fault-uncaught`, `u2-fault-logged-unguarded` killed; catalogue `owui_files` 31/31 |
| D5 | cut unchanged; collection → whole, face 0 | pass | Q44 suite green; live Valve = `NotoSansCJK-Regular.ttc` drew Japanese (PNG inspected, differs from the OTF run) |
| D6 | envelope: pydantic `Valves` + `self.valves`; filter Valves admin-only | pass | B6 widened to `{fontTools, pydantic}` for both filters; measurement Image: all four artifacts import in `ghcr.io/open-webui/open-webui:v0.12.3`; `routers/functions.py:527-532` `get_admin_user`; Valve title `Japanese Font Path` read back over REST |
| D7 | live on 0.12.3 | pass | red: `ja-clinic-simple` `glyph_missing` before; green: pass (discovered `SourceHanSansJP-Regular.otf`) + pass (Valve TTC), `ja-clinic-misleading` `axis_inverted`; F7 on the 0.12.3 bundle: `ja-font` 77,545 B cut, `ja-whole` 6,141,697 B, every glyph leg as expected |
