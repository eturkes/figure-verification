# Deferral queue

One line + acceptance check each. The spine — the unfinished units, and any blocker inside one — lives in `.agent/spec.md` `Tasks`, whose last line points here; a row here is off-spine until a unit adopts it.

- Subset the CJK font per figure (M17.1 U2): the filter sends the whole 5,732,824 B `NotoSansJP-Regular.ttf` (7.64 MB RPC source) on every Japanese-text render; fontTools 4.63.0 ships in the Open WebUI 0.10.2 image via `fpdf2==2.8.7` and subsets a typical chart's glyphs in 0.50 s to 11,572 B. Accept: a Japanese-label + Japanese-tick figure's RPC source < 100 KB, F7 `ja-font` stays clean with every glyph drawn (PNG inspected), a glyph-collection miss can only FAIL (witness), and the fontTools import degrades to the whole font when absent.
