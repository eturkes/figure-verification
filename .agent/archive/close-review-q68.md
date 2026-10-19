# Closing review — Q68 (`bf52d39` → the Q68 commit)

One reviewer covering every lens (MAINTAIN; Q68 tier data). Check set C1-C9 fixed by MAIN before dispatch; deliverable copied whole below. F1-F3 reproduced by MAIN, fixed inside Q68, re-review round: all accepted ⇒ ledger R224-R226 closed. Register: Q70 (the clinic misleading arm's changed reason) is queued, outside Q68's change.

## reviewer-1 — Q68 closing review

Target = working tree against `bf52d39`. C1–C9 fixed before target reads. Tracked + untracked targets read-only; evidence scripts/logs = `/tmp/q68-rev/`. Initial template SHA-256 = `e956797ccb7db07c25e67cad7cc7d08fbdfd315f965693605fa3a3abe5a1da06`; tests = `292546cbdff3657f78b9a77a269ddc87e6194ae91996eed93f8311aec611670f`; contract = `9f14438f7a7ac0149a89575cb34d7e8c0fb685bfd7ca7af9347df3c4416a527c`.

| id | check × target | verdict | evidence / ruling |
|---|---|---|---|
| C1 | T1 red/green; T2 baseline hashes | pass | Current 2 tests pass. T1 invoked on an imported `/tmp` copy of `git show bf52d39:webui/paste_in/templates.py` fails at original test line 15. `/tmp/q68-rev/project.py` independently reproduces both baseline/current T2 hashes. |
| C2 | file bytes; no CSV; selected bytes; suffix split | pass | Projection assertions: `_FILE + RULES` equals base, both no-file strings omit `csv` casefolded, demo no-file equals `.scratch/q68/tpl-g00000.txt`, both production/demo prefixes equal after removing their unchanged final paragraphs. |
| C3 | generated artifacts | pass | `uv run --no-sync --locked python tools/generate_paste_in.py --check`: rc 0, `4 artifact(s) current`. Each filter equals its base with exactly one old embedded templates source replaced by the new source; all other bytes equal. |
| C4 | S1 `frozen=False` vs T1–T3 | pass | T1–T3 constrain rendered text, not instance immutability. False leaves those strings unchanged; acceptable survivor. |
| C5 | S2 `slots=False` vs T1–T3 | pass | T1–T3 constrain rendered text, not instance layout. False leaves those strings unchanged; acceptable survivor. |
| C6 | S3 `_NO_FILE` wrapper + abnormal-credit ruling | finding F1, F3 | T3 owns selected bytes; S3 changes them while T1/T2 pass. Missing selected-no-file byte pin. rc 2 = correctly uncredited, but 9 abnormalities comprise 8 string operators + 1 decorator replacement, not 9 string operators. |
| C7 | every Q68 numerical/observation claim | finding F2 | All 42 JSONs projected; 30 retained PNGs hash-match. Live counts + file hashes + baseline program equality pass. Held-out K = 3/11, not contract’s 4/11. Counts/provenance detail and explicit limits below. |
| C8 | harness extraction + driving invariance | pass | `CHECKS[0] == "program"`; `_program` lists all of that row’s source; both harnesses select the first `li details.row .listing`, then its `.src` children. Across all 48 recorded turns, first-listing round-trip equals source for pass + run/axes failures (144 generated embeds). `m10u3_demo.mjs` diff adds program extraction/recording + its comment alone; driving untouched. |
| C9 | docs/law/queue/citation | pass | EN/JA add the same no-file instruction, matching `_NO_FILE`; 12 register/admin checks pass. Updated demo-transport law matches `_render` + templates; banner law faithfully distinguishes Q70’s runtime error from inversion. Q69/Q70 each state a measurable `Accept:`. Test’s archived-contract citation resolves. |

## F1 — selected no-file bytes lack the test required by survivor ruling

Severity: minor. Location: `tests/test_paste_in_templates.py:10–28`; contract `T3` at `.agent/archive/contracts/q68.md:19` owns the selected bytes. S3 inserts `XX` before/after `_NO_FILE`; it preserves T1’s no-CSV condition and never reaches T2’s file hashes. Neither test notices a change to the measured model prompt.

Missing check: pin the selected no-file bytes using a hand-stated expected digest/text, for production and demo (not an expectation derived from the live constant).

Red evidence: from `/home/eturkes/Projects/figure-verification`, `UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 uv run --no-sync --locked pytest --no-cov -p no:cacheprovider /tmp/q68-rev/test_review.py::test_s3_is_detected_by_q68_structural_suite` → rc 1, `Failed: DID NOT RAISE AssertionError`. The detector loads current source separately, rebuilds the two templates with the exact S3-wrapped `_NO_FILE`, invokes the unchanged T1/T2 functions, and demands rejection. Positive control = T1 rejects the baseline source in the same script. Target files never changed.

## F2 — held-out K numerator disagrees with the retained panel

Severity: minor. Location: `.agent/archive/contracts/q68.md:23`. Exact matched bytes: `K 4/11`. `jq -r '[.tag,.turn,.verdict,.reason]|@tsv' .scratch/q68/heldout-K.jsonl` has 11 turns; only `green` turns 1/2 + `years` turn 1 pass ⇒ 3/11. Remaining 8 = `value_not_found` 1, `x_not_ordered` 1, `label_not_in_request` 1, `program_error` 5. Independent projection = `/tmp/q68-rev/project.py`. Correct the numerator; winner’s 6/11 and baseline’s 2/11 match.

## F3 — abnormal-trial inventory misstates its ninth entry

Severity: minor. Location: `.agent/archive/contracts/q68.md:33`. Exact matched bytes: `9 abnormal = string`. `.scratch/q68/credit-t2b.log` has eight `BinOp` abnormalities at the two `Templates(...)` lines + one `FuncCall` at line 48 changing `@dataclass(frozen=True, slots=True)` to `@None` (`TypeError: 'NoneType' object is not callable`). All nine fail at import. rc 2/uncredited is correct under assurance law; only the categorization needs correction.

## Evidence — passing rows + limits

- C1 baseline hashes: production `94815a5137bdf36a00c37fde710784b1584644b119f9f3d7ea92393185940877`; demo `9050adc064664392b2d0f0874e82d1412b0e15efd8a5e143449e3f8fe2a18d33`. Source loaded from `/tmp/q68-rev/templates_base.py`, created with `git show bf52d39:webui/paste_in/templates.py`; tracked source never overwritten.
- C7 selection: A–K = 11 full panels × 8 chains/11 turns; only K meets both acceptance prompts + red follow-up. Grid = 16 rows, 10 accepted. Full grid panels: `g00000` 11/11, `g00011` 11/11, `g01000` 10/11; `g01001` part-scored 5/6; six other accepted cells lack panel records. Baseline panels together = 14 failures; ten programs contain `read_csv` or `open`. Held-out = 8 chains/11 turns per template: baseline 2 pass, K 3, winner 6 (two `glyph_missing`). `probe.py` calls the host reader without font registration; grid’s independently recomputed acceptance follows pass/pass/pass + second red-turn colour. The two panels contain disjoint prompts. Temporal assertion “rule fixed before scoring” / “never used to select” = unconfirmed from retained data alone; scripts declare that posture, but the record cannot independently prove its timing.
- C7 live: 5 single attempts → 5 passes; 5 red chains → 10 passes; 3 honest banner arms × 5 → 15 passes; 2 sales misleading arms × 5 → 10 `zero_not_in_limits`; clinic misleading × 5 → 5 `program_error`. Every verdict/PNG count/hash/status is stable across reload. Every banner program equals its M19.9 program byte-for-byte. Two base records match the probe programs byte-for-byte: `e5513c73…` single; `dca18afc…` → `90783d67…` chain. All 30 new passing PNGs hash-match their records. Inspected `red-1-t2-figure.png`: A/B/C = 3/5/9, bars red; all five second-turn PNG hashes equal.
- C7 artifact IDs: demo tool hash begins `f5ba9e175040d501`, demo filter `70a5b691127b6da8`, as README states. Launch log confirms MX150 + Qwen model. Locks confirm torch 2.13.0+cu126, transformers 5.16.1, OWUI 0.11.3; adapter constants = 512 / 0.0. The JSONs carry no runtime-environment snapshot: historical driver 580.178.04, Chromium 151, fp16 + installed-runtime equality to locks = unconfirmed by reviewer (looked in Q68 JSONs, launch/chrome/live logs, runtime locks; no GPU/browser access taken). README scopes observations to the stated device/config + run counts rather than generalizing.
- C7 cause: actual clinic grouped series raises `ValueError: Must supply freq for datetime value` with host pandas 3.0.2; converting its index to strings draws successfully (positive control). First attempted two-row example did **not** raise: the broad “any DatetimeIndex” explanation is insufficient; the actual three-month clinic input reproduces it. The text describes that concrete program, not all datetime bars. Historical host pandas 2.3.3 success = unconfirmed here (no historical environment rerun).
- C8 round-trip and pandas witness: `/tmp/q68-rev/test_structure.py` → 2 passed. Extraction is confirmed for every retained program; arbitrary over-budget/control-character programs are outside that byte-equivalence claim because the embed intentionally truncates/normalizes display.
- C9 anchors: admin EN `docs/admin/README.md:78–80`, JA `docs/admin/README.ja.md:79–80`; `webui/paste_in/filter.py:298–311` and templates source support the changed law. Both queue entries carry observable five-run acceptance checks; Q70 offers a user-ruling alternative. `.claude/rules/ops.md` change only adds Q68 record/test digests to the documented baseline inventory.

## Register — outside new findings

- Existing Q70: the upgraded stack does not demonstrate the historical `axis_inverted` outcome for the clinic arm; it blocks earlier. The new README/law correctly disclose that limit. If “keep their recorded outcomes” in T4 means the identical failure reason (not merely pass/fail), that leg remains unmet; the queue row does not turn it into a verified inversion block.
- Full `.secrets.baseline` content adjudication is outside fixed C1–C9; no all-clear beyond the actual checks is claimed.

## Verification

- Projection: `UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 uv run --no-sync --locked python /tmp/q68-rev/project.py` → rc 0. Complete 42-record sweep; 40 new live records + 2 baseline records. The baseline red turn 1 PNG is not retained in `q68/`; its JSON hash remains, and no PNG-content verification is claimed for it.
- Targeted suite: template tests + register + admin docs + inlet suffix-invariant node + demo-pair suite → rc 0, 22 passed. `.venv` editable binding before/after = primary `src`.
- First external red-test run failed due to its setup (`webui` not importable); corrected the temporary detector’s import path, reran, and obtained the intended failures above. The setup failure earns no evidence.
- Full gate, mutation driver, hosted CI, live model/browser reruns: not run by reviewer (MAIN owns environment/live stack). No target writes, no staging.
- Final source/test/contract SHA-256 values equal the initial snapshot. Deliverable validator: positive control 1 match / rc 0; table 0 remaining cells / grep rc 1 (the expected no-match status). All 9 rows adjudicated; 3 minor findings.

reviewer-1-DONE-1

## Re-review

Scope = F1–F3 acceptance alone; one round. Initial findings above remain the historical evidence; all three fixes accepted below. Target source unchanged (`templates.py` SHA-256 `e956797ccb7db07c25e67cad7cc7d08fbdfd315f965693605fa3a3abe5a1da06`); revised tests SHA-256 `ce29f7f80ab091a675e58da0df125b869b40c1c4be4e35c9d7d27f6ad0c41f05`.

| finding | verdict | evidence |
|---|---|---|
| F1 | accepted | `tests/test_paste_in_templates.py:32–42` hand-states both no-file SHA-256 digests. New node passes current source. Invoked on the imported bf52d39 template copy, it fails at line 39 (`AssertionError`, rc 1). Updated `/tmp/q68-rev/test_review.py::test_s3_is_detected_by_q68_structural_suite` includes the new node and now passes: the S3-wrapped `_NO_FILE` triggers its assertion. Current-node + S3-detector run = 2 passed, rc 0. |
| F2 | accepted | `rg -Fn 'K 3/11' .agent/archive/contracts/q68.md` matches line 23; equals the previously independently counted three passing turns out of eleven. |
| F3 | accepted | Contract line 33 now states `9 abnormal = 8 BinOp` + `1 FuncCall`, spells `@dataclass(...)` → `@None`, and keeps `rc 2, uncredited`. Matches the reviewed log’s 8/1 inventory. Recorded survivor rulings match this review: container flags open; no-file bytes specified by T3. |

Commands from `/home/eturkes/Projects/figure-verification`, prefix `UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 uv run --no-sync --locked pytest --no-cov -p no:cacheprovider`:
- Red: `/tmp/q68-rev/test_review.py::test_t3_on_base` → rc 1, `1 failed`, new hash assertion at `tests/test_paste_in_templates.py:39`. Log `/tmp/q68-rev/t3-base-red.log`.
- Green: `tests/test_paste_in_templates.py::test_q68_no_file_templates_keep_the_measured_bytes /tmp/q68-rev/test_review.py::test_s3_is_detected_by_q68_structural_suite` → rc 0, `2 passed in 0.25s`. Log `/tmp/q68-rev/rereview-green.log`.
- `.venv` editable binding remains primary `src`. No target writes; no full gate/mutation-driver/live rerun. Earlier coverage limits and Q70 register note remain unchanged.

reviewer-1-DONE-2
