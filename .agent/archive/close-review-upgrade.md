# Closing review — dependency-upgrade request (`7ba4047..`, U1-U4)

One reviewer covering every lens (MAINTAIN), docs + rules + queue (code = gate + catalogues). Check set fixed before the diff was read; verdict table + re-review copied from reviewer-1's deliverable; findings → `.agent/review.md` R227-R230.


Target = `7ba4047..dc83118e5749b0ffcab0b9955c0856671531114e` + index. Target reads = `git show :<path>`; working-tree mutations excluded. C1–C6 fixed from the seed before target reads. **6/6 adjudicated; one minor finding, C5.1.** Three additional text observations → register, outside the enumerated checks. Validator: seed pending-token count 6 (rc 0) → closing count 0 (rc 1, expected); verdict-row count 6 (rc 0).

| id | check × target | verdict | findings |
|---|---|---|---|
| C1 | Claim scope: changed sentences in README, admin EN/JA, reference EN/JA, runtime README, webui README, launcher banner + filter Valve text; outcomes carry run count + host tuple | pass | — |
| C2 | EN/JA parity: changed admin/reference facts + order, font section, troubleshooting + package/font sentences | pass | — |
| C3 | Enumerated cross-file facts: versions, package lists, font filename list + order, 32 MiB, 67 bundle entries, 364 package records, 17 detector entries vs indexed docs/rules/pins/code | pass | — |
| C4 | Changed EN human-facing register: short/direct sentences, active voice, condition before command, one instruction per step, no filler | pass | — |
| C5 | Current doc/rule stale facts outside archive + closed review rows: old OWUI/font source, root/runtime Python, torch + transformers | finding | C5.1 |
| C6 | Seven added queue rows: measured blocker + tool/rerun-decidable `Accept:` | pass | — |

## C5.1 — minor — bundled-font/subset claims survive in five current documents

Exact indexed anchors (each rematched with `rg -Fn`, rc 0):

| path:line | distinctive verbatim bytes |
|---|---|
| `README.md:46` | `the Japanese font that Open WebUI` |
| `README.md:47` | `contains and the pixels.` |
| `docs/checks.md:79` | `the filter sends the part of Open WebUI's Japanese font` |
| `docs/checks.ja.md:79` | `Open WebUI の日本語フォントの一部を送る` |
| `docs/gallery.md:20` | `Open WebUI's Japanese font reaches ordinary text, not mathtext.` |
| `docs/gallery.ja.md:20` | `Open WebUI の日本語フォントは通常のテキストには届きますが、mathtext には届きません。` |

Why wrong: these describe the retired source and unconditional subsetting as current behavior. MAIN's supplied 0.12.3 image facts = no Japanese font + no fontTools. Indexed admin guide `docs/admin/README.md:36–42` correctly states server-provided font + whole-font transmission on that image. Indexed `.claude/rules/claims.md:12` trusts the font found on the server, not one Open WebUI contains. The short guide is the destination of every Show-checks link, so the stale account is a shipped explanation, not archival prose.

Minimal fix:
- README: name the Japanese font from the Open WebUI server.
- Both short-guide rows: name the server's font; subset when possible, otherwise whole. Alternatively omit the transport aside and keep the glyph-check mechanism alone.
- Gallery: change the source captions `docs/gallery/entries.toml:10–11` to the server-provided font, then regenerate both pages with the recorded gallery generator. The mathtext limit itself remains correct.

Reproduction shape (no worktree read):

```sh
git show :docs/checks.md \
  | /usr/bin/rg -Fn "the filter sends the part of Open WebUI's Japanese font" /dev/stdin
# 79:| every character in an available font | ...
# rc=0
```

Reviewed blob IDs: README `fb730cb3b17cf0a8c832d019906902f1b1ea4bae`; short guide EN `31c9f3dce7e251704c7ec2668778d1910e24636a`, JA `d669c6a2d978bb34475c8fc3757401b09cc6d674`; gallery EN `1af037ea322c636c2598bb166a9763c4a5ddf95d`, JA `9354a8c0b1c15bf9ce8fecd11cac64a6f88041ed`; gallery input `e2efacc44ea86c2993247bd05b0528988dd42bbb`.

## Pass evidence + coverage

- C1: changed verifier assurances stay within the figure/data claim. Real-model README names MX150, fp16 Qwen2.5-Coder-0.5B-Instruct, greedy decoding, torch 2.14.1, transformers 5.20.2, OWUI 0.12.3, Chromium 151 + five attempts per arm; banner retains `Expect` + recorded 5/5 on MX150/0.12.3. MAIN supplied 15/15 honest pass + 15/15 misleading block. Static `cmp` of every indexed deps-u3 `before.program` against its Q70 counterpart: 30 matched, 0 mismatched, comparison rc 0. No live behavior inferred from this byte comparison.
- C2: both pairs carry the same changed facts in the same order. Font filenames: 11/11 present in both admin guides, exact code order; both state 32 MiB + face 0 + admin-only function valves.
- C3: root 3.14, model runtime 3.15, image/tests 3.11; model direct pins match README/rules. Runtime lock = 69 entries, including project, matching its README. Bundle/detector counts + no-font/no-fontTools image facts accepted from MAIN's supplied measurements; no competing current values found. C3's enumerated version/list/count/size facts pass; transfer policy + file-screening wording are register R1/R2, not added checks.
- C5: all 34 tracked text docs/rules outside `.agent/archive/` searched; five matched ledger rows confirmed closed and excluded. Expanded bare-version + multiline font-source searches; six additional diagram/gallery source files searched. All hits adjudicated; long-line discovery excerpts were bounded, followed by full relevant source/context reads. Diagram numeric-coordinate matches are not version claims. Historical Q46/M19/Q68/Q70 records, supersession notes + valid 3.11/3.12 compatibility statements remain historical/compatible, not stale-current findings. No image/visual review performed.
- C6: all seven rows have concrete blockers + decidable closure: missing cp315 wheels; sandbox-exact numerical pins; image-exact pydantic; official-image interpreter line; measured mcp 2.x boot import failure; seaborn present but not explicitly loaded; measured whole-font RPC size. U1/U2 commit bodies record the wheel refusal, image measurement, mcp boot failure + F7 sizes. Closure clauses specify sync/gate, named measurement replays, named tests, stub/banner behavior or byte-size/verdict comparisons.
- Read-and-conform set read from index: claims, human-facing, OWUI laws; related spec/pins/rules read for consistency. Upstream API line citations are not independently rematched: outside this check set. External latest-release status **(unconfirmed here)**: no fresh web/package-index census; this review checks indexed pins and the documented blocker evidence.
- Not run: pytest, fast/full gate, mutation catalogues, browser/model runs, measurement replays. MAIN's supplied 28/28 replay and live outcomes are cited evidence, not reviewer reruns. Target left read-only; only this deliverable written.

## Register — outside the enumerated check set

- **R1 — conditional subset/whole-font policy.** `docs/admin/README.md:241–242`: `The filter sends the whole font with each chart` / `that has non-ASCII text` is unconditional; requirements at lines 39–41 and reference at `docs/verification.md:216–218` describe subsetting when fontTools exists. JA counterpart = admin lines 227–228. Recommend qualify the new whole-font sentence with “On the official image”. Conversely, fontTools presence alone does not guarantee a cut: indexed `webui/paste_in/fonts.py:44,51–52` returns the original on a load/subset fault. “When fontTools can cut the font” states the actual condition. No behavioral probe run.
- **R2 — file-screening wording.** `docs/admin/README.md:239–240`: `The filter never sends a file` / `that is not a font.`; JA `docs/admin/README.ja.md:226`: `フィルターは、フォントでないファイルを送りません。` Indexed `webui/paste_in/owui_files.py:189` checks size + `content[:4] in _FONT_TAGS`, not the complete font format; `fonts.py` returns original bytes on a parsing fault. Recommend describe regular-file/size/font-header screening rather than promise full format validation. Text/code inspection only; no behavioral probe run.
- **R3 — override-policy prose.** `webui/README.md:53`: `dependency that has a published advisory to its first fixed release.` conflicts with the current latest-release override policy in `webui/runtime/pyproject.toml:17–18` and spec Upgrade ruling 4. Recommend “latest compatible release”, with the recorded mcp 1.x hold. The sentence was unchanged; this policy phrasing is outside C1's changed-sentence scope and C5's enumerated stale version/font facts.

reviewer-1-DONE-1

## Re-review round (MAIN fixes, staged) — one round, acceptance checks alone

| id | acceptance check | verdict | evidence |
|---|---|---|---|
| RR-C5.1 | README.md + docs/checks{,.ja}.md + docs/gallery{,.ja}.md (generated from docs/gallery/entries.toml) name the Japanese font from the Open WebUI server, the cut conditional on fontTools; no current text names Open WebUI's own Japanese font | pass | `README.md:47`: `finds on the Open WebUI server`; `docs/checks.md:79`: `the Japanese font from the Open WebUI server` + `where the server has fontTools`; `docs/checks.ja.md:79`: `Open WebUI サーバーの日本語フォント` + `サーバーに fontTools がある場合は`. Gallery source `docs/gallery/entries.toml:10–11` + pages `docs/gallery.md:20` / `docs/gallery.ja.md:20`: `The Japanese font from the Open WebUI server reaches ordinary text, not mathtext.` / `Open WebUI サーバーの日本語フォントは通常のテキストには届きますが、mathtext には届きません。`; source→page caption `cmp` rc 0 each. Retired-source wording absent in all five pages. |
| RR-R1 | docs/admin/README{,.ja}.md: the whole-font sentence carries its "without fontTools on the server" condition | pass | `docs/admin/README.md:242`: `Without ` + `fontTools` + `on the server, the filter sends the whole font with each`; exact markup-bearing phrase = `Without \`fontTools\` on the server`. `docs/admin/README.ja.md:228–229`: `サーバーに \`fontTools\` がない場合` → `フォント全体を送るため`. |
| RR-R2 | docs/admin/README{,.ja}.md: the screening sentence claims only what the code checks (a TrueType / OpenType / collection header + the 32 MiB cap), no "never sends a file that is not a font" | pass | `docs/admin/README.md:239–240`: `most 32 MiB.` + `when it starts with a TrueType, OpenType or collection header.`; `docs/admin/README.ja.md:224,226`: `32 MiB 以下` + `TrueType、OpenType、またはコレクションのヘッダーで始まる場合だけです。`. Both former complete-font promises absent. |
| RR-R3 | webui/README.md: overrides = latest release, `mcp` on its latest 1.x with the measured reason | pass | `webui/README.md:53–54`: `dependency that has a published advisory to its latest release.` + `on its latest 1.x release, because Open WebUI 0.12.3 does not start with` + the literal package/version `mcp` 2. Former `to its first fixed release` absent. |

Re-review outcome: **4/4 pass; C5.1 + R1–R3 closed against MAIN's acceptance checks above.** Original table/findings remain the original snapshot, not unresolved re-review verdicts. Scope fixed before re-reading the staged fixes; no new lens or broader re-review added.

Evidence: indexed state over HEAD `dc83118e5749b0ffcab0b9955c0856671531114e`; positive controls = one distinctive new line per page (8/8, `rg -Fn` rc 0), retired-wording searches = no matches in those eight pages (8/8, rc 1 expected), gallery caption equality = EN/JA `cmp` rc 0. Generation/tests/app/measurement runs not performed. Read-only target; deliverable alone changed.

Re-review blob IDs: README `da17c88bb7df62f636da57ff4563839c9057180c`; admin EN `24554bb7e982ca678606608d9cee7a53527760f9`, JA `55bb1a232873372fd68f1e60ead75f5a5a100cf3`; short guide EN `0674396c13dac625d51cbb7c5c86d0258140fa9e`, JA `8e552c322db435ba4bf974ba0625ba850643405e`; gallery EN `54ec6330dd2b45d1f192ded17a3da2efd6264153`, JA `c98eaa58421445789ec7575124d8d0ec0a7b9d28`; gallery source `764f27a8c8969973fe05773d07ab489ca17e3f30`; webui README `946f3ed6cb309260d8384d59fa26188e3824b9cb`.

reviewer-1-DONE-2
