# Closing review — follow-up request (Q65 `2f0f741..c1ec361`, Q66 `c1ec361..6456965`, Q67 `564501b`)

One reviewer covering every lens (MAINTAIN; Q66 tier kernel). Check set C1-C10 fixed before the diff was read; deliverable copied whole below. F1, F2 + register Rg1 reproduced by MAIN, fixed inside Q66 (`6456965`), re-review round: all accepted ⇒ ledger R221-R223 closed. Q67 (a lock override) carries its acceptance in its commit (audit rc 0, `uv pip check` = the 15 lifted pins) and sat outside the check set.

## reviewer-1 — Q65 + Q66 closing review

Root = `/home/eturkes/Projects/figure-verification`. Target = Q65 `2f0f741..c1ec361` (`model_backend/app.py`) + Q66 working tree against `c1ec361`. Check set = C1–C10, fixed before target reads. Read-only target; this file alone written. `OWUI/` below = `.venv-webui/lib/python3.11/site-packages/open_webui/`.

**Verdict: 10/10 rows adjudicated; 8 pass, 2 finding (both minor).** R1–R6 source + wiring generally hold; null-text fallback + public branch wording need correction. Register = one test-fixture isolation issue outside the fixed checks.

| id | check | verdict | evidence (file:line / command + rc) |
|---|---|---|---|
| C1 | R1: stored branch's `user`/`str` contents, oldest first, blank-line joined; upstream walk + map keys + metadata ids | pass | `webui/paste_in/owui_files.py:127-137`; `OWUI/utils/misc.py:182-214`, `OWUI/models/chat_messages.py:377-401`, `OWUI/main.py:1247-1249`. P1: 69 passed, rc 0, incl R6 strict-column + typed-data effects. |
| C2 | R2: latest-only fallback; store exceptions contained; cancellation propagates | finding F1 | `webui/paste_in/owui_files.py:128`: absent/null current text + absent/null stored tail admits earlier text. F1 red rc 1. Committed exception/cancellation cases pass in P1. |
| C3 | R3: requesting user's ownership checked before map read | pass | `webui/paste_in/owui_files.py:125-127`, `webui/paste_in/tool.py:80`; upstream `OWUI/models/chats.py:1791-1801`, `OWUI/utils/tools.py:311-344`. P1 foreign-chat no-read + owner-specific receipt cases pass. |
| C4 | R4: stored user rows only; no model-facing rewrite or summary | pass | `webui/paste_in/owui_files.py:121-134`; `OWUI/main.py:1500-1507` persists current message; `OWUI/utils/middleware.py:2162-2176,2417-2487` reads branch then rewrites/compacts model-facing copies. Helper accepts neither `body` nor `__messages__`. |
| C5 | R5: receipt + signature; reserved `__user__` absent from model schema | pass | `webui/paste_in/tool.py:55-84`; `webui/paste_in/filter.py:152-161` still selects language from latest metadata. P2: 29 passed, rc 0. P3: both generated tools under CPython 3.11 + extracted installed OWUI schema helper → properties/required exactly `[program]`, rc 0. |
| C6 | Fake chat API signatures/return shapes + upstream walk semantics | pass | `tests/paste_in_support.py:718-804` vs `OWUI/models/chats.py:1053-1104,1791-1801` + `OWUI/utils/misc.py:182-214`. P4: 10,369 differential map/tail cases, rc 0. API used by helper matches; fake's empty-map `None` and upstream legacy `{}` share the same empty-branch result. Nested fixture restoration is separate Rg1. |
| C7 | EN/JA docs + rules/spec state one request rule within claim scope | finding F2 | Four public definitions say every message in the chat; R1 excludes sibling branches and falls back beyond temporary chats. `docs/verification.md:37`, `docs/verification.ja.md:35`, `docs/admin/README.md:140`, `docs/admin/README.ja.md:140`. Rules/spec + latest-language edits otherwise consistent. |
| C8 | Generated pairs current; new helper + tool signature embedded | pass | P5: generator `--check` → `4 artifact(s) current`, rc 0. P6: all four embed byte-identical current `owui_files`; both tools embed byte-identical `tool` with `__user__`, rc 0. |
| C9 | Q65 parser survivor equivalence + class ruling for other survivors | pass | Full 437-trial JSON read, no trial errors/timeouts: 109 killed / 328 survived. Parser = 30 trials, 29 killed; sole survivor ordinal 53, `app.py:98:15`, Number `-1`, equivalent. Remaining 327 outside parser predicate; ruling below. P7: 3,106 parser comparisons, rc 0. |
| C10 | Q65 history serialization + retry drops oldest and terminates | pass | `model_backend/app.py:48-49,91-147` vs `OWUI/utils/middleware.py:1297-1320`; last ≤4 entries, USER/ASSISTANT only, malformed history → query only. Retry removes exactly one oldest turn; query-alone or other error re-raises. P1 runs 35 adapter cases incl retry floor/other error; rc 0. |

## F1 — minor — no-text latest can become earlier text (C2)

Location = `webui/paste_in/owui_files.py:128` (reviewed blob `3b1e210e4dd0dcd71f91740e150aa18aa1f322ae`). R2 preserves latest-only `None` when current text is unavailable. `_latest` returns `None`; a stored current row with missing/null `content` also returns `None` through `.get`, so the tail test accepts it and returns earlier user strings. All ids + ownership can be valid. This differs from the existing no-text test, whose stored tail is still a string and therefore falls back.

Scope: ordinary normalized OWUI rows default null content to `''` (`OWUI/models/chat_messages.py:389-397`); the legacy fallback returns raw history (`OWUI/models/chats.py:1094-1104`). This is the malformed/legacy-row edge of R2, not a claim that the ordinary text follow-up fails.

Red on reviewed working tree:

```bash
(cd /home/eturkes/Projects/figure-verification && PYTHONDONTWRITEBYTECODE=1 /home/eturkes/Projects/figure-verification/.venv/bin/python - <<'PY'
import asyncio
import sys
sys.path.insert(0, '/home/eturkes/Projects/figure-verification/tests')
from paste_in_support import StoredChat, fake_chats
from webui.paste_in.owui_files import request_text
rows = {
    'u1': {'role': 'user', 'content': 'Draw bars for A 3, B 5.'},
    'u2': {'role': 'user', 'parentId': 'u1', 'content': None},
}
metadata = {'chat_id': 'chat', 'user_message_id': 'u2', 'user_message': {'content': None}}
with fake_chats({'chat': StoredChat('owner', rows)}):
    result = asyncio.run(request_text(metadata, 'owner'))
print(f'actual={result!r}; expected=None (R2 latest has no text)', flush=True)
assert result is None
PY
)
```

Output / captured rc:

```text
actual='Draw bars for A 3, B 5.'; expected=None (R2 latest has no text)
Traceback (most recent call last):
  File "<stdin>", line 14, in <module>
AssertionError
null_latest_red_rc=1
```

Accept fix = no-text latest returns `None` even when stored current content is null/missing; valid empty string remains text. Add that witness beside the existing non-text-current test; regenerated artifacts current.

## F2 — minor — public request definition includes discarded branches (C7)

R1 names the selected `parentId` branch. New public definitions instead name all earlier user messages in the chat. An edited sibling remains stored in the chat but never reaches this request; the new `u2`/`u2b` fixture explicitly exercises this. The same paragraphs name temporary chats as the fallback but omit other unreadable/mismatched/non-owned branches. State the current branch, then latest-only when that stored branch cannot be used; temporary chats can remain the example.

Exact distinctive bytes matched by `/usr/bin/rg -Fn` (all four rc 0):

| path:line | exact bytes |
|---|---|
| `docs/verification.md:37` | `Your request is every message that you wrote in this chat` |
| `docs/verification.ja.md:35` | `依頼文とは、このチャットであなたが書いたすべてのメッセージです。` |
| `docs/admin/README.md:140` | `The request is every message that the user wrote in the chat` |
| `docs/admin/README.ja.md:140` | `依頼文とは、利用者がそのチャットで書いたすべてのメッセージです。` |

Reviewed blobs in table order = `66aa0bf4fb999ed441eff60440c47477fc13762d`, `eb143ac776071e015aa22a92e916d5865e00175f`, `5e9bd634027511297a89404531b63730bc5bc284`, `445811c9a1204c7d39fc1031b1e738169cd7be28`.

Accept fix = all four definitions describe only the current stored branch and the general latest-only fallback; EN/JA facts agree. The existing modest verification claim + old-column/typed-number chance costs stay intact.

## C9 — non-author mutation ruling

Input = `.scratch/followup/credit-q65.json`; 369,627 bytes; 437 entries; summary 109 found / 328 not found / 0 timeouts / 0 errors. Every entry classified; no sample or truncated-output assumption.

- Parser surface = `model_backend/app.py:48-49,91-106`; 30 trials, sole survivor ordinal 53 (`98:15`, Number, `position = 0` → `-1`). **Equivalent.** For any nonempty string, Python's pattern matching clamps a negative start to zero, so the first match is identical; its end sets the same positive next position. For empty input, the original returns `[]` without entering the loop; the mutant's first match fails because this pattern requires a nonempty uppercase role, then also returns `[]`. P7 compares 3,106 empty, malformed, quoted, multiline, Japanese + two-entry/trailing-text examples without a mismatch.
- Other **327 = outside this credited node's parser predicate**, not equivalent and not claimed harmless globally. Counts: adapter.py 17; app.py 74; engine.py 127; models.py 52; settings.py 57. The app subset includes routing, reply envelope, casts, other selector shapes + retry logic; the credited node asserts only history-to-generation turns. Thus these survivors do not invalidate credit for its already-passing malformed-history cases. Other behavior remains owned by its existing suites/catalogues; P1 separately runs selector near misses, fixed parameters/reply bytes and retry cases. This is not a claim that this one node kills all Q65 mutants, nor an independent rerun of all catalogues.

## Executed checks + limits

- **P1** `(cd /home/eturkes/Projects/figure-verification && PYTHONDONTWRITEBYTECODE=1 /home/eturkes/Projects/figure-verification/.venv/bin/python -m pytest -q --no-cov -p no:cacheprovider tests/test_paste_in_request_text.py tests/test_model_backend_adapter.py tests/test_model_backend_adapter_internal.py)` → **69 passed in 2.22s; rc 0**.
- **P2** same interpreter/flags, targets `tests/test_paste_in_tool.py tests/test_paste_in_aliases.py::test_q43_v2_the_model_supplies_no_alias tests/test_verification_docs.py tests/test_admin_docs.py tests/test_readme_register.py` → **29 passed in 1.05s; rc 0**.
- **P3** fileless CPython 3.11 probe: AST-extract installed OWUI `parse_description`, `parse_docstring`, `convert_function_to_pydantic_model`, `get_functions_from_tool`; execute each generated tool with `runpy.run_path`; one operation `draw_figure`, schema properties/required `[program]` → **rc 0**. Initial probe omitted namespace `__name__`, causing pydantic `KeyError: '__name__'` (rc 1); corrected harness passed. No target failure or target edit there. Full loader/database lifecycle not exercised by this probe.
- **P4** AST-extracted actual `OWUI/utils/misc.py::get_message_list` vs fixture `_message_list`; all subsets of 3 keys × 6 parent choices per key × 6 requested tails + `None` map; 10,369 cases incl missing links and cycles → **rc 0**.
- **P5** `(cd /home/eturkes/Projects/figure-verification && PYTHONDONTWRITEBYTECODE=1 /home/eturkes/Projects/figure-verification/.venv/bin/python /home/eturkes/Projects/figure-verification/tools/generate_paste_in.py --check)` → **4 artifact(s) current; rc 0**.
- **P6** fileless `embedded_sources` walk over every `ARTIFACTS` entry; new helper equals tracked source plus generator's one newline; both embedded tool signatures contain `__user__` → **rc 0**.
- **P7** original/parser-mutated ASTs executed in isolated namespaces, 3,106 histories compared; full mutation JSON classified → **rc 0**.
- Primary `.venv/lib/python3.13/site-packages/verifier.pth` read before/after checks → primary `/home/eturkes/Projects/figure-verification/src` throughout. No uv invocation, sync, mutation run, server, browser or GPU use.
- **Not run by reviewer:** full gate, mutation catalogues, live OWUI follow-up, real model, real chat-store transactions. MAIN owns those. Upstream storage/metadata behavior = direct installed-source comparison, not a DB integration claim. Tests run without coverage. No claim that selector history is lossless for arbitrary delimiter-containing content: its documented `"""` + entry-opening ambiguity remains accepted input-format loss, outside this contract.

## Register

- **Rg1 — nested fake restoration (non-blocking, outside C6's API/branch-walk check).** `tests/paste_in_support.py:785-804` reuses existing module objects, overwrites `Chats`/`get_message_list`, then restores only `sys.modules` object references. A nested `fake_chats({})` therefore leaves the outer fixture bound to the empty inner store. Inline probe: outer owned two-user branch returns `earlier\n\nlatest`; inner empty store returns `latest`; after inner exit it still returns `latest`. `assert result == 'earlier\n\nlatest'` → **AssertionError, rc 1**. Existing nested test checks call logs but never reads the outer store again; normal teardown removes the modules, so no cross-test leak demonstrated. Suggested queue acceptance = nested exit restores outer API attributes + returns the outer thread; exceptional exits included.

reviewer-1-DONE-1

## Re-review

Round = one; scope = F1, F2, Rg1 acceptance checks alone; no new rows. **All three accepted; no initial finding remains open.** Earlier verdict table preserves the reviewed pre-fix state; this section supersedes its F1/F2 disposition.

| id | verdict | evidence |
|---|---|---|
| F1 | accepted | `webui/paste_in/owui_files.py:119-122` returns latest when it is `None`, ahead of imports/lookups. Original §F1 red command rerun unchanged → `actual=None; expected=None (R2 latest has no text)`, rc 0. New null/absent-tail cases pass in RR1. Separate empty-string probe still returns `'earlier\n\n'` and records one owner check + one map read, rc 0. Generator `--check` → four current artifacts, rc 0. |
| F2 | accepted | All four definitions now exclude sibling branches and describe general latest-only fallback. Exact `rg -Fn` matches below, every command rc 0. EN/JA facts agree; old-column caveat + modest claim remain unchanged. Documentation suites pass in RR1. |
| Rg1 | accepted | `tests/paste_in_support.py:782-813` uses fresh leaf modules and restores parent attributes in `finally`. RR2: after normal AND exceptional nested exits, outer request returns `'earlier\n\nlatest'`; parent attributes reference the original outer leaf modules, rc 0. Updated committed nested-store cases pass in RR1. |

RR1 command (cwd explicitly set):

```bash
(cd /home/eturkes/Projects/figure-verification && PYTHONDONTWRITEBYTECODE=1 /home/eturkes/Projects/figure-verification/.venv/bin/python -m pytest -q --no-cov -p no:cacheprovider tests/test_paste_in_request_text.py::test_q66_r2_no_text_reads_none_even_over_a_textless_stored_tail tests/test_paste_in_request_text.py::test_q66_r2_r3_a_chat_the_user_does_not_own_is_never_read tests/test_verification_docs.py tests/test_admin_docs.py tests/test_readme_register.py)
```

Result = **28 passed in 0.31s; rc 0**.

F2 exact matched bytes (two positive anchors per file; each `rg -Fn -e <branch> -e <fallback> <absolute file>` returned rc 0):

| path:line | exact bytes |
|---|---|
| `docs/verification.md:40` | `and the messages of the other branch do not count.` |
| `docs/verification.md:41` | `conversation, your request is your last message alone.` |
| `docs/verification.ja.md:37` | `他の分岐のメッセージは数えません。` |
| `docs/verification.ja.md:38` | `検証器が保存された会話を読み取れない場合、依頼文は最後のメッセージだけです。` |
| `docs/admin/README.md:140` | `The request is every message that the user wrote in the current branch of the chat` |
| `docs/admin/README.md:144` | `the last message alone. Examples are a temporary chat and a chat that another user owns.` |
| `docs/admin/README.ja.md:140` | `依頼文とは、利用者がチャットの現在の分岐で書いたすべてのメッセージです。` |
| `docs/admin/README.ja.md:143` | `保存された分岐を読み取れない場合、依頼文は最後のメッセージだけです。` |

RR2 command (original register witness, extended only to its stated exceptional-exit acceptance):

```bash
(cd /home/eturkes/Projects/figure-verification && PYTHONDONTWRITEBYTECODE=1 /home/eturkes/Projects/figure-verification/.venv/bin/python - <<'PY'
import asyncio
import sys
sys.path.insert(0, '/home/eturkes/Projects/figure-verification/tests')
from paste_in_support import StoredChat, fake_chats
from webui.paste_in.owui_files import request_text
rows = {'a': {'role': 'user', 'content': 'earlier'}, 'b': {'role': 'user', 'content': 'latest', 'parentId': 'a'}}
meta = {'chat_id': 'outer', 'user_message_id': 'b', 'user_message': {'content': 'latest'}}
for exceptional in (False, True):
    with fake_chats({'outer': StoredChat('owner', rows)}):
        outer_modules = {name: sys.modules[name] for name in ('open_webui.models.chats', 'open_webui.utils.misc')}
        assert asyncio.run(request_text(meta, 'owner')) == 'earlier\n\nlatest'
        try:
            with fake_chats({}):
                assert asyncio.run(request_text(meta, 'owner')) == 'latest'
                if exceptional:
                    raise RuntimeError('exercise finally')
        except RuntimeError:
            assert exceptional
        result = asyncio.run(request_text(meta, 'owner'))
        print(f'exceptional={exceptional}: nested fake after exit={result!r}', flush=True)
        assert result == 'earlier\n\nlatest'
        assert sys.modules['open_webui.models'].chats is outer_modules['open_webui.models.chats']
        assert sys.modules['open_webui.utils'].misc is outer_modules['open_webui.utils.misc']
PY
)
```

Output = `exceptional=False: nested fake after exit='earlier\n\nlatest'` + `exceptional=True: nested fake after exit='earlier\n\nlatest'`; **rc 0**.

Scope limits unchanged: no full gate, catalogue rerun, live browser/model or real DB transaction by reviewer. MAIN's reported 20/20 catalogue result not independently re-executed. Primary `verifier.pth` remained `/home/eturkes/Projects/figure-verification/src` before/after. Target edits = none; deliverable append only.

reviewer-1-DONE-2
