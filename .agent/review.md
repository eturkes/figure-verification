# Review ledger — integrity redesign (M19)

A `finding` cell carries its evidence at the `CLAUDE.md` `Teammates` bar: a red test for behavior, or
the disputed bytes as a greppable anchor plus `file:line` for an artifact's text; an absence claim
carries its command, rc and positive control. A unit's FULL verdict table lands with its archived
contract, since an all-`pass` row still counts as review delivered; this ledger carries only the
rows that needed a ruling. Rows R1-R131 (IMPLEMENT close + the queue requests, all adjudicated) =
`.agent/archive/review-implement.md`; among them R7-R14 adjudicate the 8 non-`pass` rows of M13.6's
24 (`.agent/archive/contracts/m13u6.md` § Closing review).

The code-review check set (§ Code review) lives in this file by its request's terms and stays here through close; its findings join § Rows as unit `CR`.

Status vocabulary: `open` · `accepted` (fix required, named) · `rejected` (with reason) ·
`register` (outside contract, recorded not fixed) · `closed` (fix landed + re-reviewed).

## Lenses

| id | lens | what it asks |
|---|---|---|
| L-CORR | correctness / spec | does the code do what its contract's predicates say, on the inputs the contract admits? (+ the `CLAUDE.md` `Engineering` Correctness code diff lens) |
| L-CLEAN | cleanup | the `CLAUDE.md` `Engineering` Cleanup code diff lens: helpers reused, derivable state computed, near-duplicates merged, dead code gone, independent steps parallel, hot paths lean |
| L-ALT | altitude | does a special case on shared infrastructure signal a fix due in the mechanism? |
| L-CLAIM | claim soundness | is every sentence the project ships true at the strength it is stated? |
| L-GAP | guarantee vs. claim | does a shipped guarantee outrun the mechanism that backs it? |
| L-LAW | `CLAUDE.md` conformance | tiers, contracts, gate identity, claim discipline, authoring register |
| L-HARD | verification integrity | does an admitted path return a fixture's expected value, or grade against an expected-output table its contract does not own? |
| L-SEC | security | can a remote actor (chat user, CSV author, the model, another user) read, forge, exhaust or run beyond the stated trust boundary? |

## Rows

| id | unit | lens | finding | status | acceptance check |
|---|---|---|---|---|---|
| R132 | M19.2 | L-CORR | reviewer-1 F3: the hist/pie/fill_between recorders read caller arguments (no `data=` resolution, float casts of dates), so a call matplotlib draws became a program error attributed to the model. | closed | Recorders resolve `data=`, run under `contextlib.suppress`, and band arrays come from the final polygon: `tests/test_figure_reader.py::test_f3_recorders_keep_valid_calls_valid` (4 cases) + `test_f3_a_record_matplotlib_cannot_express_as_numbers_is_skipped` + `test_f3_band_arrays_read_back_converted_dates`; mutant `m19-recording-never-raises`. |
| R133 | M19.2 | L-CORR | reviewer-1 F4 + F5: a visible label2 tick (right/top) was dropped, and a legend entry carried its construction label instead of its displayed text — both facts the judge's tick + legend rules decide on. | closed | `test_f4_right_hand_tick_labels_are_reported`, `test_f5_legend_entries_read_their_displayed_text`; mutants `m19-tick-second-label`, `m19-legend-displayed-text`. |
| R134 | M19.2 | L-GAP | reviewer-1 F6 + F7 + F8: text over the cap was cut (U4: never a silent drop), the children cap applied per axes (U4: per figure), and reader/decoder measured different byte spans. | closed | `test_p5_text_cap`, `test_f7_the_children_cap_counts_the_whole_figure`, `test_f8_a_description_at_the_cap_decodes`; mutants `m19-children-per-figure`, `m19-cap-measures-the-body`. |
| R135 | M19.2 | L-CORR | reviewer-1 F9 + F10 + F11: the decoder admitted `1e999` (inf) and undeclared words in closed fields; U+2028 inside text split the tagged line. | closed | `tests/test_figure_description.py::test_f9_numeric_overflow_is_no_number`, `test_f10_closed_word_fields_refuse_other_words`, `tests/test_figure_reader.py::test_f11_line_separators_inside_text_survive_the_transport`; mutants `m19-float-finite`, `m19-closed-words`, `m19-ascii-transport`. |
| R136 | M19.2 | L-CLAIM | reviewer-1 F1 + F2 + F12: an identical reader exec'd again replaced the holder the docstring says is reused; one capture drew twice; the contract's geometry API named fields the code does not have. | closed | `test_f1_the_same_reader_exec_d_again_reuses_its_holder`, `test_f2_one_capture_draws_once`; contract `.agent/archive/contracts/m19u2.md` API line restated. |
| R137 | M19.3 | L-CORR | reviewer-2 F1 + F2 + F3: a linked colorbar exempted its whole axes (fabricated ticks, a user Circle passed); clipping read one reference coordinate and an unrotated rectangle; wedge clipping used the enclosing circle. | closed | Colorbar contents + ticks judged (`parts.py::_check_colorbar`), every reference coordinate clipped, rotated bars unjudged, pies exempt from clipping (wedges `clip_on=False`): `tests/figure_corpus/review.toml` `colorbar-lying-ticks` `colorbar-user-patch` `clipped-reference-end` `rotated-bar-clip` `diagonal-exploded-pie`; mutants `m19-colorbar-contents` `m19-rotated-bar` `m19-pie-unclipped`. |
| R138 | M19.3 | L-CORR | reviewer-2 F4 + F5: base-2 log labels and `$−300` false-refused; `1e999` raised OverflowError out of the verdict API. | closed | `ticks.py` powers any base exact, sign either side of the currency sign, `.5`, `\%`, exponents past 300 = no number: review cases `honest-log-base2` `honest-currency-negative-dollar` `honest-short-number-label` `huge-exponent-label`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[huge-power]`. |
| R139 | M19.3 | L-CORR | reviewer-2 F6 + F7 + F8 + F9: overlap compared bar and barh in incompatible coordinates with a value-scaled key tolerance; two floating bands justified each other; a NaN area input vanished. | closed | Overlap on drawn x/y with per-axis tolerance, grounded band stacks, band input count: review cases `mixed-bars-*` `large-bars-overlap` `floating-area-cycle` `missing-area-input`; mutants `m19-overlap-height-own-scale` `m19-band-base` `m19-band-inputs`. |
| R140 | M19.3 | L-CORR · L-CLAIM | reviewer-2 F10 + F11 + F12 + F13: pie/reference/figure-level size legends false-refused; a repeated setter marked the first call; transparent, no-ink, zero-size and hidden-axes charts passed; the law disagreed with the contract. | closed | Legends resolve handles figure-wide (`legends.py::read_legends`), last-call sites, ink-based `mark_hidden`, law updated: review cases `pie-legend` `reference-legend` `figure-size-legend` `repeated-limit-site` `transparent-line` `no-ink-line` `zero-size-scatter` `hidden-panel`; mutants `m19-ink-scatter` `m19-hidden-panel`. |
| R141 | M19.3 | L-GAP | reviewer-2 register: a `legend_elements` key's labels are not compared with the encoded values; a histogram's per-bin bar width is not checked. | register | Outside M19.3's contract. Accept when taken up: a relabelled size/colour key blocks, and a hist bar narrower than its bin blocks, each with an honest twin. |
| R142 | M19.4 | L-CLAIM · L-CORR | reviewer-3 F1 + F2: a reference value several columns hold read as zero/request in both languages; a span whose edges came from two columns drew neither (strict anchoring never saw them). | closed | Per-value holders (`explain.py::_explain_reference`): a value one column alone holds draws it, a shared one is published as such: `tests/test_figure_values.py::test_span_edges_from_two_columns_draw_both`, `test_a_shared_reference_value_says_so`; mutants `m19-reference-per-value`, `m19-reference-any-holder`, `m19-shared-unpublished`. |
| R143 | M19.4 | L-CORR | reviewer-3 F3 + F4: R6 removed the filter column from the keys (`bar(['US'], [40000], label='US')` blocked); two filters over the same drawn columns tied. | closed | The filter column may be the key; ties group by (file, drawn columns), first filter column wins: `test_r6_a_filtered_series_may_key_by_its_label`, `test_r6_two_filter_columns_with_one_reading_are_no_tie`; mutants `m19-filter-key-excluded`, `m19-filter-in-tie`. |
| R144 | M19.4 | L-CORR | reviewer-3 F5 + F9: greedy matching let a text point take the row a slot needed; a missing value was blamed on a CSV-backed point's untyped label. | closed | Slots bind first (keyed points match within interchangeable key classes); attribution reads only points no file explanation backs: `test_slots_bind_before_keyed_points`, `test_attribution_reads_only_unbacked_points`; mutants `m19-slots-not-first`, `m19-attribution-every-point`. |
| R145 | M19.4 | L-CORR | reviewer-3 F6: pie keys came from the call's labels, so a label changed after the call was never checked. | closed | The reader records each wedge's drawn label Text; keys = its final text (hidden, removed, blank = none), else the legend entry: `test_pie_keys_are_the_drawn_labels`; mutants `m19-pie-call-labels`, `m19-pie-texts-unrecorded`, `m19-pie-labels-as-text`, `m19-pie-labels-listed`. |
| R146 | M19.4 | L-CORR | reviewer-3 F7: a figure legend (and suptitle) was judged against each panel's reductions alone, so honest sum + mean panels blocked. | closed | Panel labels vs that panel's reductions, figure labels vs every panel's: `test_g10_figure_labels_read_every_panel`; mutants `m19-g10-figure-against-panel`, `m19-g10-panel-against-figure`. |
| R147 | M19.4 | L-GAP | reviewer-3 F8: a colour/size channel matched by x alone, so values swapped between two points under one key passed. | closed | MAIN ruling (R8 reading): a channel binds to its own point's row or group — channel explanations carry the main value per pair (`explain.py::_channel_explanations`): `test_r8_a_channel_stays_with_its_own_point`, `test_r8_grouped_channels_bind_to_their_group`; mutants `m19-partner-unchecked`, `m19-channel-groups-unbound`, `m19-channel-request-only`. |
| R148 | M19.4 | L-LAW | reviewer-3 register R1: contract U1 still said a series is named by its legend entry "or own label"; U8 + code say a label no legend shows names nothing. | closed | U1 restated in `.agent/archive/contracts/m19u4.md`. |
| R149 | M19.5 | L-CLAIM | reviewer-4 F1 + F4: the troubleshooting rows (EN + JA) still asked for a set system prompt after the System-prompt ruling retired it; the README cited a six-arm stub measurement with no committed record. | closed | Rows ask for the tool, tool calling and the filter; records committed at `.agent/measurements/m19u5/` and cited. |
| R150 | M19.5 | L-CLAIM | reviewer-4 F2: the reference, its Japanese twin and both admin guides said a computed value stops the chart; the judge reads values, so a computed value that equals a cell passes. | closed | Every copy narrowed: a computed value stops the chart unless the same number is in the data. |
| R151 | M19.5 | L-GAP | reviewer-4 F3: the static-path retirement dropped still-live UI pins — title/covers/sentence budgets (three texts over budget), the exact height reporter + trigger ban, PNG prose corners, the reply rewrite without an assistant message, the inlet's two header-refusal families. | closed | `tests/test_paste_in_texts.py` (budgets; red on the staged texts: axes covers 27, parts + values explanations 26), `tests/test_paste_in_embed.py` (reporter + triggers, every reason × language × anchoring), `tests/test_paste_in_filter_edges.py`; the three texts shortened. |
| R152 | M19.5 | L-CLAIM | reviewer-4 register R1 + R2: `bundle.py` (its docstring + the generated preamble) named `src/verifier/pysrc/` as the core; the reference did not say which packages the sandbox loads. | closed | Both name `src/verifier/`; the reference (EN + JA) states numpy, pandas, matplotlib + the standard library. |
| R153 | M19.6 | L-GAP | reviewer-5 F1 + R1: every multi-panel misleading case blocked at the parts stage, so a judge skipping all panels after the first passed the corpus; the `LineCollection|None` census witness blocked for another artist. | closed | `second-panel-truncated` (panel 2 truncated ⇒ `zero_not_in_limits`), misleading kinds counted only after the parts stage (`tests/test_figure_coverage.py`), `user-line-collection`; C1 = 187 cases, zero misses. |
| R154 | M19.6 | L-LAW | reviewer-5 F2 + isolation note: `Phase` claimed M19.6 CLOSED with its contract still open (S5); the corpus case `image-not-figure` wrote `/tmp/chart.png` on every run. | closed | Contract archived in the closing commit; the case saves to an in-memory buffer. |
| R155 | M19.7a | L-CLAIM | reviewer-6 K6 (in review): live law still described retired JSON-spec surfaces as current — `assurance.md` (the `replay.py`/`archive.py` mirror, HTTP routes + `examples/` claim surface, DuckDB/SVG probes, artifact-route `state_dir`), `pysrc.md` (the dataset-digest law paragraph; `expr.py` keeps its no-`ast` property), `python-corpus.md` (the same `expr.py` clause). | closed | Each clause removed; reviewer-6 re-ran the anchors absent (rc 1, positive control present). |
| R156 | M19.7b | L-GAP | MAIN (re-rooting the G10 suite): a group's `min`/`max` IS one of its cells, so the values are a raw subset (R2) and the canonical-raw rule picks raw ⇒ no reduction is drawn and G10 never reads a summary word over them (`Max revenue` over per-region minimums passes). | register | Outside M19.7b's contract (the canonical rule is M19.4 law). Pinned as current behavior by `tests/test_pysrc_labels.py::test_q16_a_group_min_or_max_reads_as_raw_cells`. Accept when taken up: a label naming another reduction over a min/max chart blocks when the program's own reduction call is recorded, with an honest twin. |
| R157 | M19.7b | L-GAP | reviewer-7 F1: re-rooting R3 onto `aggregate_series` bypassed the CSV profile, and C10's inside-profile fixture is a float64 column, so the inclusive int32 endpoint of an INTEGER column lost its only witness (`_INT32_MAX = 2**31 - 2` survived all 1,889 tests). | closed | `tests/test_pysrc_csv.py::test_c10_an_integer_column_admits_both_int32_endpoints`; mutants `c10-int32-max-exclusive` + `c10-int32-min-exclusive` killed (csvread 9/9). |
| R158 | M19.7b | L-CLAIM | reviewer-7 F2: `.claude/rules/owui.md` still called a text marker `admitted, discarded by projection`; spec ruling 13 named `position.py` spans. | closed | Both anchors absent (`rg -Fnc` rc 1), replacements present. |
| R159 | M19.9 | L-CLAIM · L-CORR | MAIN (the F7 re-key's `ja-mathtext` leg: glyphs 0 in the bundle): mathtext logs a glyph its font set lacks on `matplotlib.mathtext`, never `warnings`, so the reader drew tofu and the figure passed, while both admin guides (`docs/admin/README.md` troubleshooting table) said Japanese math text fails `glyph_missing`. | closed | The reader counts those log records: `tests/test_figure_reader.py::test_m19_9_a_mathtext_glyph_the_font_lacks_counts` (red on `0ce1797`), corpus `mathtext-missing-glyph` + `mathtext-honest`, mutants `m19-mathtext-glyph-unlogged` + `-uncounted` (reader 27/27); C1 189/189 + F7 PASS in the bundle. |
| R160 | M19 close | L-CORR · L-CLAIM | reviewer-8 F1: a figure with no data source skipped `explain`, the only caller of G8, so two points on one category passed (`plt.plot(['A', 'A'], [1, 1])`) while the same program with a typed request blocked. | closed | `judge.py::judge` runs `explain.py::duplicate_key` over every series before the integrity-only branch; corpus `source-free-duplicate-category` (red on `5128a03`) + `source-free-distinct-categories`; mutant `m19-g8-source-free-skipped` (figure_judge 6/6). |
| R161 | M19 close | L-CORR · L-CLAIM | reviewer-8 F2: scatter ink was collection-wide (`any(sizes)`), so one zero-size or faceless point among drawn ones vanished and passed. | closed | `mark_rules.py::_point_ink` per point (properties cycled); corpus `one-zero-size-point`, `one-faceless-point` (red on `5128a03`), `every-point-sized`; mutants `m19-scatter-ink-collection-wide`, `m19-scatter-face-collection-wide` (mark_rules 14/14). |
| R162 | M19 close | L-CORR | reviewer-8 F3 + its re-review residual: the marked line came from slot priority (first matching setter), then from the highest source line, neither the latest executed call (a helper defined above the main code). | closed | The reader stamps each recorded call with a per-run clock (`calls`: slot → [line, clock]); `axes_rules.py::call` returns the latest by clock; corpus `latest-inversion-site`, `helper-inversion-site` (the reviewer's witness); mutants `m19-site-slot-priority`, `m19-site-source-line` (judge 10/10). Residual fixed by MAIN and checked with the reviewer's own witness (`test_fix_acceptance.py::test_f3_…` passes), per the session-8 precedent for a residual inside its original acceptance. |
| R163 | M19 close | L-CORR · L-CLAIM | reviewer-8 F4 + its re-review residual: minor tick labels were unread while the reference says every visible tick label shows its position; then read under the MAJOR formatter's trust (a false minor date label passed under a major DateFormatter). | closed | The reader reports visible non-empty minor labels apart (`minor`) with their own formatter's module; the judge trusts a minor date label only under its own date formatter, else the label must denote its position with no offset/order; corpus `minor-tick-lie`, `minor-date-lie` (red), `minor-tick-honest`, `minor-date-honest`, `honest-months-pandas` (pandas' minor month names stay trusted); mutants `m19-minor-labels-unread`, `m19-minor-labels-skipped`, `m19-minor-date-trusted`, `m19-minor-date-untrusted` (reader 28/28, ticks 6/6). Residual checked with the reviewer's witness reading the `minor` field. |
| R164 | M19 close | L-CLAIM | reviewer-8 F5: the reference + both admin guides held a min/max chart's labels to the other summary words; the canonical-raw rule (R156) reads no summary word over min/max. | closed | All four docs qualified to total + mean, with the min/max reason stated. |
| R165 | M19 close | L-LAW | reviewer-8 F6 (A13): `134e082` retired the banned-stem check with no recorded firing. | rejected | Retired by user ruling (integrity-redesign ruling 8 retires every banned-stem check); the old check stayed green on the new tree and the record says so (`.scratch/m19u5/firings.txt`, the commit body); no firing exists to record, and no substitute control is cited. |
| R166 | M19 close | L-CLAIM | reviewer-8 F7 (A8 round): `.claude/rules/owui.md` said the demo model `ignored a plain-word distortion in 0/15 runs`, the reverse of the record (it carried one in 0/15). | closed | Reworded to `carried a plain-word distortion in 0/15 runs`, matching `.agent/measurements/README.md` § Live MX150 record + `.agent/archive/contracts/m19u9.md`. |
| R167 | M20 close | L-CORR | reviewer-1 F1: a colorbar axes made on its own line (`fig.add_axes` + `colorbar(cax=…)`) was missing from `marks`, while E1 names colorbar axes sites there. | closed | `excerpts.py::_recorded` adds a colorbar axes' site to `marks`: `tests/test_paste_in_excerpts.py::test_r1_f1_a_colorbar_axes_made_on_its_own_line_joins_marks` (red on `ff70f0e`); mutant `m20-colorbar-marks`. |
| R168 | M20 close | L-CORR | reviewer-1 F2: `_reads` subtracted every inner-scope binding from every read, so `[v for v in v]` and a lambda's parameter erased an outer read and the data line vanished. | closed | Scope-aware free names (`excerpts.py::_free`, `_locals`): `test_r1_f2_an_inner_scope_binds_only_its_own_reads` (2, red on `ff70f0e`), `test_r1_f2_a_def_reads_every_name_it_does_not_bind_itself`, `test_r1_f2_a_lambda_parameter_shadows_the_outer_name`; mutants `m20-comprehension-first-iter`, `m20-comprehension-names`, `m20-lambda-parameters`, `m20-def-locals`, `m20-global-declared`, `m20-local-imports`, `m20-local-handler-name`, `m20-local-defs`, `m20-class-free`. |
| R169 | M20 close | L-CORR | reviewer-1 F3: a failure inside a multi-line `except` header kept its raw line, since no statement owns a handler header. | closed | Handler + `case` headers widen to themselves + their enclosing headers; a `match` owns its own lines alone: `test_r1_f3_a_failure_in_an_except_header_widens_to_that_header` (red on `ff70f0e`), `test_r1_f3_a_case_header_widens_like_an_except_header` (red on `ff70f0e`); mutants `m20-header-lines`, `m20-case-header`, `m20-match-own`. |
| R170 | M20 close | L-CLAIM | reviewer-2 C1: admin guide EN/JA, both READMEs + `checks.py::_program` said every other check that ran shows program lines; run passed + attach show a note (X2). | closed | Each names the note rows (`A passed run check and the image check show a short note instead.`; README `its related program lines or a note`); register + parity tests green. |
| R171 | M20 close | L-CLAIM | reviewer-2 C2: the reference EN/JA said each listed line shows its whole statement, without the 65,536-character parse bound or the 60-line / 3,000-character / 400-character listing caps. | closed | Reference EN + JA state both bounds and the omitted-line count. |
| R172 | M20 close | L-GAP | reviewer-3 F1 (major): the trace showed lines that did not prepare the drawn data — a discarded `df.add(100)`, an unused `except` fallback, a global rebound before a helper ran, a zero-iteration loop — and in the `except` and loop cases dropped the real data line. | closed · rejected in part | Fixed: a binding the drawing line's path may skip no longer ends the search, so the real data line is listed; `add` leaves the in-place list; a helper's globals are read before its last call: `test_r3_f1_every_binding_that_may_reach_the_drawing_line` (4, red on `ff70f0e`); mutants `m20-branch-uncertain`, `m20-loop-may-not-run`, `m20-caller-resume`, `m20-add-copies`. Rejected: listing the `except` arm and the loop beside the real line — every binding that may reach the drawing line is related, and the user's option text admitted a wrong line (`can make it miss a line or add a wrong one`); the reference EN/JA, spec ruling (2) + `owui.md` now state that a listed line can be one that did not run. |
| R173 | M20 close | L-GAP | reviewer-3 F2 (major): one reverse walk per drawing line made a 58,046-character, 500-mark PASS program spend 50.7-72.0 s in `_evidence` on Open WebUI's event loop. | closed | A 100,000 statement-visit budget per program (caller scan included; a scan already begun completes one def body, reviewer-3 re-review REG1: 105,062 on a four-helper probe — claims reworded) + statement facts computed once: 0.42 / 0.42 / 0.52 s on Python 3.12.14 (`.scratch/latency.py`, same program); `test_r3_f2_the_trace_stops_at_its_work_budget`, `test_r3_f2_finding_a_helper_s_caller_spends_the_budget`; mutants `m20-work-budget`, `m20-caller-work`. |
| R174 | M20 close | L-LAW | reviewer-4 F1: M20.1 P3 + P4 had no named mutation credit. | closed · rejected in part | P3: `m20-label-site-in-draw` kills `tests/test_pysrc_labels.py::test_m20_1_a_refused_label_marks_the_line_that_set_it`. P4 rejected: an invariant (no site decides a verdict), held by the unchanged judge + the full suite + the C1 replay; no predicate exists to neuter. |
| R175 | M20 close | L-LAW | reviewer-4 F2: M20.1's contract was written after its reader fix; M20.2's scratch prototype preceded its contract (its tracked code did not). | register | Historical; the contracts record the found defect and the user rulings, and the red witnesses predate each fix. Accept when taken up: none (process record only). |
| R176 | M20 close | L-LAW | reviewer-4 R1: the X2 change to the attach row changed the O9 listing check; its original firing was not recorded. | closed | Original `test_o9_only_passed_program_and_failing_row_list_source` (from `e83878d`) against `ff70f0e`: `no_image` + `publish_failed` failed, 50 passed (reviewer-4 + reviewer-5 replays); recorded here and in the M20.3 commit body. |
| R177 | M20 close | L-CLAIM | reviewer-3 re-review REG1: `owui.md` said `≤ 100,000 statement visits`; a caller scan already begun finishes its def's body, so a 60,194-character four-helper probe spent 105,062. | closed | `owui.md`, the M20.3 contract + R173 state the budget as a stop point that one body scan can pass; the latency outcome stands (0.603 s on the original witness, reviewer-3). |
| R178 | M20.4 close | L-CORR · L-CLAIM · L-GAP | reviewer-6 F1 + reviewer-7 C1 + reviewer-8 F1: a direct `Axis.set_tick_params` recorded `style` before matplotlib refused it, so a caught refused call replaced the accepted line; `figure.md` said every style records once accepted. | closed | MAIN ruling (contract Y3; reviewers 6 + 8 proposed the style hook alone): every recorded call records once matplotlib accepts it (`reader.py::_called`; re-review R183 keeps the latest-started call), the older slots included — a caught `plt.ylim(0, nan)` took the `point_clipped` mark: `tests/test_figure_reader.py::test_r178_a_refused_call_keeps_the_last_accepted_line` (red on `beb9946`); mutant `m20-calls-after-accept`. |
| R179 | M20.4 close | L-CORR · L-GAP | reviewer-6 F2 + reviewer-8 F2 (major): the `plt.xticks` hook looked up `gca()` after the call — a formatter that switched the current axes moved the style to another panel, and a label callback that closed the figure made the lookup open a blank one, so a passing chart blocked `multiple_figures`. | closed | The hook looks up the axes before the call (pyplot's own first step), after Python accepts the arguments: `test_r179_pyplot_ticks_style_the_axes_they_read_first`, `test_r179_pyplot_ticks_open_no_figure` (`callback-closes-figure` red on `beb9946`; `refused-arguments` guards the added lookup); mutants `m20-style-recipient`, `m20-style-bind-first`. |
| R180 | M20.4 close | L-CLAIM | reviewer-7 C2: contract Y2, `excerpts.py` and the T5 docstring said a tick style changes no glyph; `plt.xticks(fontfamily='cmr10')` drops the minus glyph ⇒ `glyph_missing`, and the figure row left that line out. | closed | `style` joins the figure row (`excerpts.py::_TICK_SLOTS`); rationale restated in all three; reference EN + JA figure bullet: `tests/test_paste_in_excerpts.py::test_r180_a_tick_font_that_drops_a_glyph_shows_in_the_figure_row` + T5 (red on `beb9946`); mutant `m20-style-figure-row`. |
| R181 | M20.4 close | L-LAW | reviewer-9 F1: T4's slot isolation (style is no slot a mark reads) had no mutation credit. | closed | Mutant `m20-style-slot-isolated` (`_STYLE = "ticks"`) kills `test_m20_4_t4_a_tick_style_never_takes_the_mark`. |
| R182 | M20.4 close | L-LAW | reviewer-9 F2: passive `are not listed` in the new EN reference sentence. | closed | `The verifier does not list other calls that change tick labels, …` (JA aligned). |
| R183 | M20.4 close | L-CORR · L-CLAIM · L-GAP | re-review of R178 (reviewers 6 + 7 + 8): recording after return let the program's outer `set_ylim` replace a setter its `ylim_changed` callback ran inside the call, which decided the final limits — the mark moved to the outer line. | closed | A call's clock is taken as it starts and a slot keeps the accepted call that started last (`reader.py::_record`): `tests/test_figure_reader.py::test_r183_a_setter_a_callback_runs_keeps_the_slot` (x + y; red on the record-after tree, green on `beb9946`); mutants `m20-calls-latest-start`, `m20-calls-clock-at-start`; the reviewers' re-review reds green. |
| R184 | Q45 close | L-CORR · L-CLAIM | reviewer-2 CORR-1 + reviewer-3 L3-F1 (major): X1's CSV leg sampled `min(n, keys in the column)` keys, so every `n = 1..10` bin above 3-4 held 2-4 point series. | closed | CSV sizes with no key column holding n keys record `null`; contract + README state n = 1-4 measured; red suites `test_corr_x1.py` + `test_lclaim_q45.py` pass on the fix. |
| R185 | Q45 close | L-CORR · L-CLAIM | reviewer-2 CORR-2 + reviewer-3 L3-F2 (major): X1's request leg matched typed numbers injectively while the judge matches them by membership, so `[1, 1]` under `1 to 3` counted as an added `diff` match the judge already passes. | closed | Request leg = membership on both sides; contract table + reading restated from the rerun (range `diff` 0). |
| R186 | Q44 close | L-GAP | reviewer-4 F1 (major): a `TextPath` marker lays glyphs out through `_text_helpers.layout`, drawing `.notdef` with no warning, so a glyph outside the cut passed (host + installed bundle). | closed | `reader.py::_layout` counts each index-0 glyph laid out in a run; `test_q44_r_a_path_text_glyph_outside_the_cut_fails` red without the hook; F7 leg `ja-textpath` glyphs 1. |
| R187 | Q44 close | L-GAP | reviewer-4 F2: the outlet collected the cut's characters outside its fallback, so a collector fault escaped instead of sending the whole font. | closed | `fonts.py::cut_for` wraps collection + cut; `test_q44_r_a_fault_collecting_the_characters_sends_the_whole_font`; mutant `q44-collect-outside-fallback`. |
| R188 | Q47 close | L-GAP · L-LAW | reviewer-4 F3 + reviewer-5 L5-R1: G15 matched `^def <name>` alone, so a stale `[parameter-id]` suffix or a helper `def` passed. | closed | G15 resolves every node through `pytest --collect-only`; stale bracket + helper nodes fire, live bracket passes. |
| R189 | Q44-Q46 close | L-LAW | reviewer-5 L5-F1 + L5-F2: the catalogue-set check (`fonts` added), `test_u3_the_font_is_written_then_registered` and `test_a_holder_from_another_reader_is_unwound` lacked recorded original firings, Q46's lacked revision + command; `.agent/spec.md`'s catalogue inventory omitted `fonts`. | closed | Firings recorded in the review-fix commit body; inventory lists `fonts`. |
| R190 | Q45 close | L-HARD | reviewer-6 H3a: `.agent/measurements/README.md` called every expectation hand-stated; X1's is its first run's projection. | closed | README states X1's expectation is a seeded first-run projection reproducing the contract's rates. |
| R191 | Q44-Q47 close | L-CLAIM | re-review of R184-R190 (reviewer-2 RB1-RB4, reviewer-4 RB1-RB4: 7 pass): RR-CORR-1 `q45.md` bounded the one-point rate `≤ 1.1%` against a measured 111/10,000; reviewer-4 register: `fonts.py`'s docstring said matplotlib warns on every miss, while path text warns nothing. | closed | `≤ 1.11%`; the docstring names the three signals the reader counts. |
| R192 | Q45 | L-CORR | reviewer-q45-1 F1 (major): numpy reduces float64 through 8192-value buffers, so the pairwise replica split from `Series.sum` past 8192 values. | closed | `computed.py::pairwise_sum` sums per buffer; host 180/180; mutant `q45-pairwise-buffer`; re-review RB1. |
| R193 | Q45 | L-CORR | reviewer-q45-1 F2: a pass-2 tie on one series surfaced `column_not_requested` while a later series held invented values. | closed | `judge.py::_values` reports whether every series was explained; `test_a_second_pass_tie_never_hides_a_later_invented_series`; re-review RB2. |
| R194 | Q45 | L-GAP | reviewer-q45-1 F3 (blocker): a channel computation ran over the main series' kept rows, so a share took a shrunken denominator and passed under a whole-column sentence. | closed | `explain.py::_computed_of` + `_row_channels`/`_group_channels` compute over all rows/groups, then bind; `test_a_channel_computation_runs_over_the_whole_column`; re-review RB3. |
| R195 | Q45 | L-CORR | reviewer-q45-1 F4: a typed scatter's channel took no typed computation. | closed | `_explain_channel` typed fallback; `test_a_typed_scatter_s_channel_takes_a_typed_computation`; re-review RB4. |
| R196 | Q45 | L-CLAIM | reviewer-q45-1 F5: X1's request leg kept one typed variant per computation. | closed | X1 unions variants (one cell 22 → 25); re-review RB5. |
| R197 | Q45 | L-GAP | reviewer-q45-1 F6: typed computations charged no work; pass 2 ran 8 s on 100k rows before exhausting. | closed | `_typed` charges; generation skips disjoint computations, memoises, caches key forms; the outlet judges off the loop; re-review RB6. |
| R198 | Q45 | L-HARD | reviewer-q45-1 F7: contract C2 promised every legacy corpus verdict identical, and the one legacy change was hidden by a fixture edit. | closed | C2 restated (legacy PASS identical; a legacy block may pass through an admitted computation); `tied-columns` recorded; `running-count-dissolves-a-tie`; re-review RB7. |
| R199 | Q45 | L-CLAIM | reviewer-q45-1 F8 + F9: a computation over row counts omitted its counts; contract D1/D6 lagged the code. | closed | counts published; D1/D6 restated; re-review RB8 + RB9. |
| R200 | Q45 close | L-CORR · L-GAP | reviewer-7 F1 + reviewer-9 F2 (blocker): with colour AND size shown, the size channel took the colour's choice as its scatter's, so a computed colour let a size shuffled across rows pass (pre-existing lookup; Q45 made the wrong pass reachable). | closed | the channel main = the same mark's `value` choice; `test_each_channel_binds_to_the_scatter_not_the_other_channel`; mutant `q45-channel-main-is-the-scatter`. |
| R201 | Q45 close | L-CORR | reviewer-7 F2 + F3: a CSV scatter's channel never tried a typed computation; a grouped scatter's channel never took row counts or their computations. | closed | `_explain_channel` typed fallback for every main in pass 2; `_group_channels` adds `count` + its computations in pass 2; two witnesses + mutants. |
| R202 | Q45 close | L-CLAIM | reviewer-8 F1: docs + spec said a scaled value blocks unless the number is in the data; a scaled value equal to an admitted computation passes. | closed | EN + JA reference, admin guides, spec Decision: "… in your data or in one admitted computation of it". |
| R203 | Q45 close | L-GAP | reviewer-9 F1: X1's per-transform grids differ, so summing rates bounds no union (typed `1 to 3`: 19.2% sum < 23.1% on one grid). | closed | union/combined claims removed (X1 docstring, measurements README, contract C5). |
| R204 | Q45 + Q49 close | L-LAW · L-HARD | reviewer-10 F1: original firings of the I2 + X1 expectation changes and the catalogue-set test were unrecorded; reviewer-11 F1: tests read `computed.UNARY` + `MAX_RANGE`. | closed | firings recorded in the review-fix commit body; literals hand-stated. |
| R205 | M21.1 | L-SEC | F1 (medium): the pass reply interpolated legend names, chart text, columns, cells + file names into Open WebUI markdown; a line break opened an HTML block (`<iframe>`), `[a](url)` a link, `#`/`**` forged text under the verdict. | closed | `600cacb`: one inline code span each (`src/verifier/figure/inert.py::code`); markdown-it-py oracle tests red → green. |
| R206 | M21.1 | L-SEC | F2 (medium): an exception escaping the outlet failed open (Open WebUI swallows it and keeps the model's reply); `100^{300}` tick labels raised `OverflowError` in the judge. | closed | `129c80f`: tick parse bounded; decode + judge fail closed as `verifier_error`. |
| R207 | M21.1 | L-SEC | F3 (medium): ranges expanded 10,000 terms each with no cap on their count (15 KB request → 478 MB in the Open WebUI process). | closed | `351170a`: 10,000 terms per request in total. |
| R208 | M21.1 | L-SEC | F4 (low): inlet CSV parse on the event loop (1.02 s at 7.9 MB per request); owned files read whole at any size. | closed | `351170a`: parse in a worker thread; reads cut at `max_csv_bytes + 1`. |
| R209 | M21.1 | L-SEC | F5 (medium): with Pyodide file persistence on, the program runs in a same-origin worker carrying the session cookie; the outlet sent it anyway, the admin guide never required the setting off. | closed | `9215e7f`: `sandbox_not_isolated` before files + RPC; admin guide row. |
| R210 | M21.1 | L-SEC | F6 (medium): launcher bound any host with the published secret key + admin password (forged admin token ⇒ Functions ⇒ host code); backend bound any host without authentication. | closed | `8fb0acf`: fresh credentials off loopback; backend loopback alone. |
| R211 | M21.1 | L-SEC | F7 (high): the demo installs open-webui 0.10.2 (34 published advisories, fixed by 0.11.1), unlocked + unaudited; the admin guide names it as the measured version. | closed | M21.2 `070855d` … `f650868`: 0.11.3 locked under the audit stage, sandbox re-validated, 28/28 measurements replayed; T18 pass (`.agent/archive/contracts/m21u2.md`). |
| R212 | M21.1 | L-SEC | F8 (informational): the Node harness has no committed audit or update stream. | register | Q50. |
| R213 | M21.1 | L-SEC | F9 (informational): CodeQL `py/bad-tag-filter` on a case-sensitive test oracle. | closed | Q51: oracle case-insensitive (1c86464); CodeQL on `main` 7614b9d → alert 1 `fixed`. |
| R214 | M21.1 | L-SEC | F10 (informational): Dependabot alerts disabled on the remote. | closed | Q52: enabled by user ruling (`gh api -X PUT …/vulnerability-alerts` → 204); `GET …/dependabot/alerts` → 200. |
| R215 | M21.2 | L-CORR | F11 (high): the shipped pair execs PEP 695 syntax, and the official Open WebUI image runs CPython 3.11 (0.10.2 and 0.11.3): the product never loaded on its target. | closed | `163eabd`: 3.11 forms, ruff py311 globs + 3.11 mypy pass (G16), measurement `Image`. |
| R216 | M21.2 | L-CORR | F12 (high): matplotlib 3.10 (the 0.11.3 bundle) draws `fill_between` + `stackplot` as `FillBetweenPolyCollection`; every area chart blocked `artist_not_judged`. | closed | `7b180cc`: both classes judged bands; red test + 3 mutants. |
| R217 | M21.2 | L-CORR | F13 (medium): numpy 2.4 sums a whole contiguous array pairwise (2.2: per 8192 values); the share/percent total replica split past 8192 values. | closed | `7b180cc`: whole-array replica; mutant `m21-pairwise-whole`; bundle = host on 621 vectors. |
| R218 | M21.2 | L-LAW | F14 (low): three status lines (both `sandbox_not_isolated` texts from M21.1, the JA `column_not_requested`) overflow the one-line status on 0.11.3. | closed | `7695309`: shorter texts; M15 0/106 clamped. |
| R219 | M21.2 | L-CLAIM | F15 (informational): pandas 3 zeroes a non-finite group-sum compensation (GH#60303); `kahan_sum` did not (overflow only, outside the profile). | closed | Q59: `kahan_sum` resets as pandas 3.0.2 per reduction (R11 + `tools/mutants/aggregate.toml` r11-*); law `.claude/rules/pysrc.md`. |
| R220 | M21.2 | L-GAP | F16 (informational): the suite ran on 3.13 alone while production runs 3.11; two test oracles were 3.12-only. | closed | Q60: gate stage `tests311` runs the suite on CPython 3.11 (`tools/py311`); the oracles + `ast.TypeAlias` version-aware, tests in 3.11 syntax. |
| R221 | Q66 | L-CORR | F1 (minor): a latest message without text over a stored current row without text admitted the earlier messages (R2 says `None`). | closed | `6456965`: `latest is None` returns before any lookup; witness `test_q66_r2_no_text_reads_none_even_over_a_textless_stored_tail`, mutant `q66-no-text-thread`; re-review accepted. |
| R222 | Q66 | L-CLAIM | F2 (minor): the four public request definitions said every message in the chat; the rule reads the current branch and falls back beyond temporary chats. | closed | `6456965`: `docs/verification{,.ja}.md` + `docs/admin/README{,.ja}.md` name the current branch + the general fallback; re-review accepted. |
| R223 | Q66 | L-HARD | Rg1 (register → fixed): `fake_chats` restored no parent attribute, so a nested store rebound the outer one and a later read of the outer store saw the inner. | closed | `6456965`: fresh leaf modules + parent attributes restored; the nested-store test re-reads the outer store; re-review accepted. |
| R224 | Q68 | L-HARD | F1 (minor): poodle survivor S3 (`_NO_FILE` → `'XX…XX'`) passed T1 + T2 while contract T3 owns the measured no-file bytes. | closed | Q68: T3 `test_q68_no_file_templates_keep_the_measured_bytes` pins both no-file digests, red on bf52d39 + on the S3 mutant; re-review accepted. |
| R225 | Q68 | L-CLAIM | F2 (minor): contract § Selection read `K 4/11` held-out; the records hold 3/11. | closed | Q68: `K 3/11`; re-review accepted. |
| R226 | Q68 | L-CLAIM | F3 (minor): the 9 abnormal credit trials were called string operators; 8 are BinOp + 1 FuncCall (`@dataclass(...)` → `@None`). | closed | Q68: contract § Gate identity + commit body name 8 BinOp + 1 FuncCall; re-review accepted. |
| R227 | upgrade | L-CLAIM | C5.1 (minor): README, the short guide (EN + JA) and the gallery captions still named Open WebUI's own Japanese font and an unconditional subset. | closed | U4: each names the server's font, the cut conditional on fontTools; gallery regenerated; re-review RR-C5.1 pass. |
| R228 | upgrade | L-CLAIM | Register R1 → fixed: the admin guide (EN + JA) stated whole-font sending without its no-fontTools condition. | closed | U4: `Without fontTools on the server` in both; re-review RR-R1 pass. |
| R229 | upgrade | L-CLAIM | Register R2 → fixed: "the filter never sends a file that is not a font" overclaimed a 4-byte header + size check. | closed | U4: the sentence names the header + cap the code checks (EN + JA); re-review RR-R2 pass. |
| R230 | upgrade | L-CLAIM | Register R3 → fixed: `webui/README.md` kept the retired lowest-fix override policy. | closed | U4: latest release, `mcp` on its latest 1.x with the measured boot failure; re-review RR-R3 pass. |
| R231 | Q74 | L-CORR | reviewer-1 F1 (major): a CFF DICT repeating `CharStrings` — FreeType keeps the last value, the cut read the first — drew another `A` (host FreeType 2.6.1 + bundle 2.13.3). | closed | Q74: any repeated CFF DICT operator refuses (`sfnt.py::_dict`); `test_q74_c1_a_repeated_dict_operator_refuses`; mutant `sfnt-dict-repeat`; re-review RF1 pass. |
| R232 | Q74 | L-CORR | reviewer-1 F2 (major): subroutine fan-out inlined a 1,012 B font to 787,052 B in 1.42 s; nesting bounded depth alone. | closed | Q74: one read budget per cut = the font's length (tokens, calls, mask bytes) + TN5177's 65,535-byte charstring cap; three tests; mutants `sfnt-read-budget`, `sfnt-mask-budget`, `sfnt-charstring-length`; re-review RF2 failed once (mask bytes uncharged), then pass. |
| R233 | Q74 | L-LAW | reviewer-1 F3 (minor): contract C3 promised refusal of an interior `return` + a subroutine running off its end; the code inlined both. | closed | Q74: both refuse; `test_q74_c3_a_subroutine_ends_in_return_or_endchar`; mutants `sfnt-return-interior`, `sfnt-subroutine-falls-off`; re-review RF3 pass. |
| R234 | Q74 | L-HARD | reviewer-1 F4 (major): every `hdmx` witness kept glyph order, so a reindexing fault passed all 87 tests (native advance 3840 → 5632). | closed | Q74: B-only cut with distinct `hdmx` + `LTSH` values; mutants `sfnt-hdmx-reindex`, `sfnt-ltsh-reindex`; re-review RF4 pass. |
| R235 | Q74 | L-HARD | reviewer-1 F5 (major): the CFF-version and FDSelect-format refusals each survived their guard's removal. | closed | Q74: isolated twins (the FDSelect case keeps `、`, Font DICT 0); mutants `sfnt-cff-version`, `sfnt-fd-select-format`; re-review RF5 pass. |
| R236 | Q74 | L-CLAIM | reviewer-1 F6 (minor): a 31 ms cut time had no retained record. | closed | Q74: README + `owui.md` cite the final replay's retained 14 ms alone; re-review RF6 pass. |
| R237 | Q75 | L-HARD | reviewer-2 F1 (major): the uniqueness mutant left out as equivalent survives once the second same-colour series is named by its own handle. | closed | Q75: mutant `q75-proxied-unique` kept, killed by `test_q75_p2_a_proxy_shared_with_a_direct_handle_still_needs_one_match`; contract P2 corrected. |
| R238 | Q75 | L-CLAIM | reviewer-2 F2 (minor): the reference's closed-set tables lacked the legend-proxy row; the guides' wording admitted any ink-free key. | closed | Q75: exact rows (zero-size `Rectangle` / point-free `Line2D` the program adds, used by its own axes' legend) EN + JA. |
| R239 | Q75 | L-CORR | reviewer-2 F3 (major, pre-existing): a legend naming two bars of one container (or a proxy + a bar) named one series twice; the second name never reached R6, so `EU` labelled US bars and passed. | closed | Q75: `legends.py::_handle` keys every non-pie handle by its mark; `test_q75_p2_one_bar_series_takes_one_legend_name`; mutant `q75-member-named-once`. |
| R240 | M22.1 | L-SEC | F1 (medium): the language choice named every character of the body's `user_message` on Open WebUI's event loop, 0.17 s per MB (CPython 3.11), on every completion. | closed | `17d5a62`: one kana-letter character class (`webui/paste_in/filter.py::_KANA_LETTER`), equal to the name rule over every code point; tests + mutants in `.agent/archive/contracts/m22u1.md` § Fix record. |
| R241 | M22.1 | L-SEC | F2 (medium): the request text (Q66) has no length cap; ≈ 1.4 s CPU + 120 MB per MB of typed numbers, twice when pass 1 blocks. | register | User ruling: no length limit (`.agent/spec.md` Decisions, second security-review ruling 1); parsed once per judgment since `17d5a62`; admin guide states it; memory row queued in `.agent/deferred.md`. |
| R242 | M22.1 | L-SEC | F3 (medium): the body's `files` list was read as given — a repeat read again, every listed file read by the inlet, every file parsed per pass (one 8 MB upload ×50 ⇒ 493 MB). | closed | `17d5a62`: ids each once, the inlet's last owned file alone, one parse per judgment; distinct files unbounded by user ruling (second security-review ruling 2). |
| R243 | M22.1 | L-SEC | F4 (medium): Open WebUI 0.12.3 takes 16 MiB frames; the outlet decoded and scanned the reply on the event loop (1.5 s for 16 MiB of line breaks) and published a PNG line of any length; `owui.md` read 0.10.2's 1,000,000-byte frame. | closed | `17d5a62`: a reply past the reader's own bound refuses unread (`reply_malformed`), decode + judge + PNG check in worker threads, `MAX_PNG_CHARACTERS` enforced; law restated. |
| R244 | M22.1 | L-SEC | F5 (low): the program listing's syntax walk ran on the event loop, 0.26 s near the work budget (CPython 3.11). | closed | `17d5a62`: `_evidence` in a worker thread on both paths. |
| R245 | M22.1 | L-SEC | F6 (low): a fault before the browser answered escaped the outlet, and Open WebUI keeps the model's reply. | closed | `17d5a62`: one guard over the whole outlet ⇒ `verifier_error`. |
| R246 | M22.1 | L-SEC | F7 (informational): the remote dependency graph lists certifi 2026.7.22 for the runtime lock, so Dependabot alert 6 is stale. | register | Queued in `.agent/deferred.md` (remote, user-owned). |
| R247 | M22.1 | L-SEC | F8 (informational): a pass in a shared chat shows what the sharing user's browser reported; the admin guide does not say so. | register | Queued in `.agent/deferred.md`. |
| R248 | Q82.1 | L-CORR | consultant-1 T7 (fail): llens `large_file_gate` strips an oversize CSV from the request body, so the tool saw no source and an invented value passed on integrity alone. | closed | `7eedd3a`: request text + files from the human messages of the stored branch; live `ca3f326` (`oversize` 3/3 bound to `big_sales.csv` while the gate removed it). |
| R249 | Q82.1 | L-CORR | consultant-1 T8 (fail): nucllei stores a task-delivery notice as a `user` row quoting tool output, so its numbers would count as typed data. | closed | `7eedd3a`: `meta.system_notice` rows excluded (`q82-notice-is-human` killed). |
| R250 | Q82.1 | L-CORR | reviewer-1 F1 (minor): a reply whose `timed_out` is absent or not a bool entered judgment. | closed | Q82.1 close: anything but exact `False` ⇒ `reply_malformed` (`q82-timeout-state-unchecked`). |
| R251 | Q82.1 | L-CORR | reviewer-1 F2 (minor): a textless latest human message inherited an earlier message's language. | closed | Q82.1 close: `Branch.latest` = the last human message's text (`q82-latest-skips-textless`). |
| R252 | Q82.1 | L-CORR | reviewer-1 F3 (minor): a fault while building a pass reported `verifier_error` (T10 says `publish_failed`) and the failure path reran the renderer that failed. | closed | Q82.1 close: prepare fault ⇒ `publish_failed`, `listing_failed` skips the list (`q82-renderer-reentered`). |
| R253 | Q82.1 | L-GAP | reviewer-1 F4 (major): a display that refused the push still returned the "shown to the user" pass. | closed | Q82.1 close: a refused or missing push ⇒ `publish_failed`, no second push (`q82-refused-push-ignored`); `publish_failed` text = save or show. |
| R254 | Q82.1 | L-CLAIM | reviewer-1 F5 (minor): the skill said the verifier checks drawn values as the user's data without the supplied-data condition. | closed | Q82.1 close: the sentence names a file or typed numbers, else integrity alone. |
| R255 | Q82.1 | L-CORR | reviewer-1 R2 (register): a server cap below the model tail cannot hold the tail. | register | Docstring narrowed ("while the cap can hold them"); the default 65,536 holds every list measured. |
| R256 | Q82.1 | L-HARD | reviewer-1 R3 (register): the sandbox fake checks the wrapper but runs the reader directly. | closed | Q82.1 close: `test_q82_t6_the_wrapper_runs_the_exact_program_through_the_reader` executes the real wrapper + decodes the program literal; NS runs it in the real jail. |
| R257 | M23.1 | L-SEC | F1 (high, rated from the upstream code reading; impact not demonstrated): the nucllei tool sent attachments as `/exec` `imports`, which the sandbox writes following links, a path nucllei's own tools avoid. | closed | `e235e18`: each owned file through `/files/write` with `nofollow`, then `/exec` without `imports`; strict fake + 6 mutants; NS on the real image PASS (`.agent/archive/contracts/m23u1.md` § Fix record). |
| R258 | M23.1 | L-SEC | F2 (low): the codex bridge decoded a body of any content type and answered any Host, so a page in the operator's browser could spend the subscription and a DNS-rebound page read replies. | closed | `c76961b`: JSON bodies alone + `allowed_hosts` from `webui/codex_bridge.py::hosts`. |
| R259 | M23.1 | L-SEC | F3 (low): the live nucllei harness served its private stack on every interface with signup on, and kept its admin login at the umask. | closed | `62c2838`: loopback serve + `ENABLE_SIGNUP=false` + `stack.json` 0600; `tests/test_measurement_exposure.py`; CodeQL alert 2 = the user's. |
| R260 | M23.1 | L-SEC | F4 (informational): the model backend + stub share F2's request-origin class with no credential behind them. | register | Queued in `.agent/deferred.md`. |
| R261 | M23.1 | L-SEC | Register U1 + U2 (upstream, outside the contract): the nucllei sandbox's `/exec` imports write follows links; nucllei's frontend lock pins markdown-it 14.3.0 (quadratic-parse advisories). | register | Reported to the user; no repo action (the tool sends no `imports`; its own text cannot reach the inline-HTML parse, NR). |

## Code review — check set (MAINTAIN code-review request)

Fixed + committed before the first implementation read. Rows = lens × module: one row per tracked file (group = the reviewer dispatch unit), one verdict cell per lens; conformance = LAW × clause. Cell = `pending` (seed) → `pass` · `R<n>` (finding, § Rows, unit `CR`) · `n/a: <reason>`. Finding = severity + `file:line` + proof: behavior → a red test (command + failing output); text → anchor bytes `rg -Fn` matches. Root-cause fix + a sweep for the defect class, one scoped commit per class, gate green at each. Security = the `Security review` body: a security defect met here = a MAIN-only finding. Closed when `rg -c '\| pending' .agent/review.md` → 0.

| lens | asks |
|---|---|
| BASE | the full gate + each runnable `Artifacts` entry driven by its run command; a red step or a failed run = a finding |
| CORR | `CLAUDE.md` `Engineering` Correctness lens, each function read with its callers + callees |
| CLEAN | `Engineering` Cleanup lens |
| ALT | `Engineering` Altitude lens |
| CLAIM | claim soundness + guarantee-vs-claim gaps: README, `--help`, comments, docstrings + `Artifacts` vs behavior |
| HARD | verification integrity (`Engineering`): a test counts once seen red or mutation-credited; no admitted path returns a fixture's expected value; no grading against an expected-output table the contract does not own; no skipped, weakened or demoted case without its ledger row |
| SPEC | behavior vs `Intent` + `Decisions` (§ Spec index) |
| REG | docs: register (human-facing ASD-STE100, else agent-optimized) + EN/JA parity |
| LAW | each clause of `CLAUDE.md` + every `.claude/rules/` file that binds a tracked file: tool-decidable → its gate check runs + fires on a planted bad input; none → a finding fixed by wiring the check |

Groups: G1 reader · G2 judge structure + corpus · G3 values · G4 anchoring + CSV profile · G5 publication + receipt texts · G6 Open WebUI filter runtime · G7 embed + font cut · G8 nucllei + generation · G9 demo harness + model backend · G10 gate, tooling, config + meta tests · G11 measurement harnesses.

### Baseline

| id | `Artifacts` entry | run | verdict | evidence |
|---|---|---|---|---|
| B1 | Gate | `bash tools/gate.sh` — CI fan-out on the check-set commit | pending | — |
| B2 | Gate positive controls | `bash tools/gate-probe.sh` | pending | — |
| B3 | Fast gate | `bash tools/fast-gate.sh <node>` | pending | — |
| B4 | Mutation-tool credit | `uv run --locked python tools/mutation_credit.py <tests/…::node>` (one node) | pending | — |
| B5 | Mutation catalogues | `uv run --locked python tools/mutate.py tools/mutants/<module>.toml`, all 38 | pending | — |
| B6 | Paste-in + nucllei generation | `uv run --locked python tools/generate_paste_in.py --check` (`paste-in/`, `webui/demo-paste-in/`, `llens/nucllei/`) | pending | — |
| B7 | nucllei guide HTML | `uv run --locked python tools/render_nucllei_guide.py --check` | pending | — |
| B8 | Diagrams | `uv run --locked python tools/render_diagrams.py` → committed SVG bytes | pending | — |
| B9 | Gallery | `uv run --locked python tools/render_gallery.py` → committed pages + PNGs | pending | — |
| B10 | Test fonts | `uv run --locked python tools/subset_test_font.py` (TTF + `--cff`) → committed bytes | pending | — |
| B11 | NS (nucllei sandbox corpus) | `uv run --locked python .agent/measurements/ns_sandbox.py` | pending | — |
| B12 | nucllei live | `uv run --locked python .agent/measurements/nucllei_live.py <llens checkout> <out> [arm …]` | pending | — |
| B13 | Measurement replay | `uv run --locked python .agent/measurements/rerun_all.py` | pending | — |
| B14 | Demo stub | `webui/launch.sh --stub` + `node .agent/measurements/m10u3_demo.mjs …` per banner arm | pending | — |
| B15 | Demo real model | `webui/launch.sh` (MX150) + one banner arm | pending | — |
| B16 | Demo codex | `webui/launch.sh --codex` + one banner arm | pending | — |
| B17 | Model backend | `.venv-model/bin/python -m model_backend` (:8001) + one request | pending | — |
| B18 | CodeQL | `.github/workflows/codeql.yml` result on `main` | pending | — |
| B19 | CLI help | every `ArgumentParser` entry point `--help`: rc 0 | pending | — |

### Modules

| id | group | path | CORR | CLEAN | ALT | CLAIM | HARD | SPEC |
|---|---|---|---|---|---|---|---|---|
| M1 | G1 | `src/verifier/figure/reader.py` | pending | pending | pending | pending | pending | pending |
| M2 | G1 | `src/verifier/figure/description.py` | pending | pending | pending | pending | pending | pending |
| M3 | G1 | `tests/test_figure_reader.py` | pending | pending | pending | pending | pending | pending |
| M4 | G1 | `tests/test_figure_description.py` | pending | pending | pending | pending | pending | pending |
| M5 | G2 | `src/verifier/figure/judge.py` | pending | pending | pending | pending | pending | pending |
| M6 | G2 | `src/verifier/figure/parts.py` | pending | pending | pending | pending | pending | pending |
| M7 | G2 | `src/verifier/figure/shapes.py` | pending | pending | pending | pending | pending | pending |
| M8 | G2 | `src/verifier/figure/axes_rules.py` | pending | pending | pending | pending | pending | pending |
| M9 | G2 | `src/verifier/figure/ticks.py` | pending | pending | pending | pending | pending | pending |
| M10 | G2 | `src/verifier/figure/mark_rules.py` | pending | pending | pending | pending | pending | pending |
| M11 | G2 | `src/verifier/figure/legends.py` | pending | pending | pending | pending | pending | pending |
| M12 | G2 | `src/verifier/figure/series.py` | pending | pending | pending | pending | pending | pending |
| M13 | G2 | `src/verifier/figure/keys.py` | pending | pending | pending | pending | pending | pending |
| M14 | G2 | `src/verifier/figure/reasons.py` | pending | pending | pending | pending | pending | pending |
| M15 | G2 | `src/verifier/figure/__init__.py` | pending | pending | pending | pending | pending | pending |
| M16 | G2 | `src/verifier/__init__.py` | pending | pending | pending | pending | pending | pending |
| M17 | G2 | `tests/test_figure_judge.py` | pending | pending | pending | pending | pending | pending |
| M18 | G2 | `tests/test_figure_corpus.py` | pending | pending | pending | pending | pending | pending |
| M19 | G2 | `tests/test_figure_coverage.py` | pending | pending | pending | pending | pending | pending |
| M20 | G2 | `tests/figure_corpus/*` | pending | pending | pending | pending | pending | pending |
| M21 | G3 | `src/verifier/figure/explain.py` | pending | pending | pending | pending | pending | pending |
| M22 | G3 | `src/verifier/figure/computed.py` | pending | pending | pending | pending | pending | pending |
| M23 | G3 | `src/verifier/figure/sources.py` | pending | pending | pending | pending | pending | pending |
| M24 | G3 | `src/verifier/figure/request.py` | pending | pending | pending | pending | pending | pending |
| M25 | G3 | `tests/test_figure_values.py` | pending | pending | pending | pending | pending | pending |
| M26 | G3 | `tests/test_figure_computed.py` | pending | pending | pending | pending | pending | pending |
| M27 | G4 | `src/verifier/figure/anchoring.py` | pending | pending | pending | pending | pending | pending |
| M28 | G4 | `src/verifier/figure/columns.py` | pending | pending | pending | pending | pending | pending |
| M29 | G4 | `src/verifier/pysrc/__init__.py` | pending | pending | pending | pending | pending | pending |
| M30 | G4 | `src/verifier/pysrc/aggregate.py` | pending | pending | pending | pending | pending | pending |
| M31 | G4 | `src/verifier/pysrc/budget.py` | pending | pending | pending | pending | pending | pending |
| M32 | G4 | `src/verifier/pysrc/csvread.py` | pending | pending | pending | pending | pending | pending |
| M33 | G4 | `src/verifier/pysrc/errors.py` | pending | pending | pending | pending | pending | pending |
| M34 | G4 | `src/verifier/pysrc/limits.py` | pending | pending | pending | pending | pending | pending |
| M35 | G4 | `src/verifier/pysrc/table.py` | pending | pending | pending | pending | pending | pending |
| M36 | G4 | `tests/anchoring_support.py` | pending | pending | pending | pending | pending | pending |
| M37 | G4 | `tests/test_pysrc_aggregate.py` | pending | pending | pending | pending | pending | pending |
| M38 | G4 | `tests/test_pysrc_anchoring.py` | pending | pending | pending | pending | pending | pending |
| M39 | G4 | `tests/test_pysrc_anchoring_aliases.py` | pending | pending | pending | pending | pending | pending |
| M40 | G4 | `tests/test_pysrc_anchoring_short.py` | pending | pending | pending | pending | pending | pending |
| M41 | G4 | `tests/test_pysrc_anchoring_strict.py` | pending | pending | pending | pending | pending | pending |
| M42 | G4 | `tests/test_pysrc_anchoring_suffix.py` | pending | pending | pending | pending | pending | pending |
| M43 | G4 | `tests/test_pysrc_budget.py` | pending | pending | pending | pending | pending | pending |
| M44 | G4 | `tests/test_pysrc_csv.py` | pending | pending | pending | pending | pending | pending |
| M45 | G4 | `tests/test_pysrc_labels.py` | pending | pending | pending | pending | pending | pending |
| M46 | G5 | `src/verifier/figure/interpret.py` | pending | pending | pending | pending | pending | pending |
| M47 | G5 | `src/verifier/figure/inert.py` | pending | pending | pending | pending | pending | pending |
| M48 | G5 | `webui/paste_in/reply.py` | pending | pending | pending | pending | pending | pending |
| M49 | G5 | `webui/paste_in/reasons.py` | pending | pending | pending | pending | pending | pending |
| M50 | G5 | `webui/paste_in/verdicts.py` | pending | pending | pending | pending | pending | pending |
| M51 | G5 | `webui/paste_in/templates.py` | pending | pending | pending | pending | pending | pending |
| M52 | G5 | `webui/paste_in/tool.py` | pending | pending | pending | pending | pending | pending |
| M53 | G5 | `webui/paste_in/aliases.py` | pending | pending | pending | pending | pending | pending |
| M54 | G5 | `webui/paste_in/receipt.py` | pending | pending | pending | pending | pending | pending |
| M55 | G5 | `webui/paste_in/__init__.py` | pending | pending | pending | pending | pending | pending |
| M56 | G5 | `tests/test_figure_inert.py` | pending | pending | pending | pending | pending | pending |
| M57 | G5 | `tests/test_paste_in_reasons.py` | pending | pending | pending | pending | pending | pending |
| M58 | G5 | `tests/test_paste_in_receipt.py` | pending | pending | pending | pending | pending | pending |
| M59 | G5 | `tests/test_paste_in_templates.py` | pending | pending | pending | pending | pending | pending |
| M60 | G5 | `tests/test_paste_in_texts.py` | pending | pending | pending | pending | pending | pending |
| M61 | G5 | `tests/test_paste_in_tool.py` | pending | pending | pending | pending | pending | pending |
| M62 | G5 | `tests/test_paste_in_aliases.py` | pending | pending | pending | pending | pending | pending |
| M63 | G5 | `tests/test_paste_in_note.py` | pending | pending | pending | pending | pending | pending |
| M64 | G5 | `tests/test_guidance_claim_boundary.py` | pending | pending | pending | pending | pending | pending |
| M65 | G6 | `webui/paste_in/filter.py` | pending | pending | pending | pending | pending | pending |
| M66 | G6 | `webui/paste_in/owui_files.py` | pending | pending | pending | pending | pending | pending |
| M67 | G6 | `webui/paste_in/sandbox.py` | pending | pending | pending | pending | pending | pending |
| M68 | G6 | `webui/paste_in/fonts.py` | pending | pending | pending | pending | pending | pending |
| M69 | G6 | `webui/paste_in/reader_text.py` | pending | pending | pending | pending | pending | pending |
| M70 | G6 | `webui/paste_in/demo_filter.py` | pending | pending | pending | pending | pending | pending |
| M71 | G6 | `webui/paste_in/demo_tool.py` | pending | pending | pending | pending | pending | pending |
| M72 | G6 | `tests/paste_in_support.py` | pending | pending | pending | pending | pending | pending |
| M73 | G6 | `tests/outlet_support.py` | pending | pending | pending | pending | pending | pending |
| M74 | G6 | `tests/test_paste_in_outlet.py` | pending | pending | pending | pending | pending | pending |
| M75 | G6 | `tests/test_paste_in_inlet.py` | pending | pending | pending | pending | pending | pending |
| M76 | G6 | `tests/test_paste_in_request_text.py` | pending | pending | pending | pending | pending | pending |
| M77 | G6 | `tests/test_paste_in_sandbox.py` | pending | pending | pending | pending | pending | pending |
| M78 | G6 | `tests/test_paste_in_font.py` | pending | pending | pending | pending | pending | pending |
| M79 | G6 | `tests/test_paste_in_filter_edges.py` | pending | pending | pending | pending | pending | pending |
| M80 | G6 | `tests/test_paste_in_owui_files.py` | pending | pending | pending | pending | pending | pending |
| M81 | G6 | `tests/test_paste_in_demo_pair.py` | pending | pending | pending | pending | pending | pending |
| M82 | G6 | `tests/test_paste_in_filter_packaging.py` | pending | pending | pending | pending | pending | pending |
| M83 | G7 | `webui/paste_in/checks.py` | pending | pending | pending | pending | pending | pending |
| M84 | G7 | `webui/paste_in/excerpts.py` | pending | pending | pending | pending | pending | pending |
| M85 | G7 | `webui/paste_in/sfnt.py` | pending | pending | pending | pending | pending | pending |
| M86 | G7 | `tests/test_paste_in_checks.py` | pending | pending | pending | pending | pending | pending |
| M87 | G7 | `tests/test_paste_in_embed.py` | pending | pending | pending | pending | pending | pending |
| M88 | G7 | `tests/test_paste_in_excerpts.py` | pending | pending | pending | pending | pending | pending |
| M89 | G7 | `tests/test_paste_in_sfnt.py` | pending | pending | pending | pending | pending | pending |
| M90 | G7 | `tests/fonts/*` | pending | pending | pending | pending | pending | pending |
| M91 | G8 | `nucllei_skill/__init__.py` | pending | pending | pending | pending | pending | pending |
| M92 | G8 | `nucllei_skill/checks.py` | pending | pending | pending | pending | pending | pending |
| M93 | G8 | `nucllei_skill/host.py` | pending | pending | pending | pending | pending | pending |
| M94 | G8 | `nucllei_skill/reasons.py` | pending | pending | pending | pending | pending | pending |
| M95 | G8 | `nucllei_skill/run.py` | pending | pending | pending | pending | pending | pending |
| M96 | G8 | `nucllei_skill/skill.py` | pending | pending | pending | pending | pending | pending |
| M97 | G8 | `nucllei_skill/texts.py` | pending | pending | pending | pending | pending | pending |
| M98 | G8 | `nucllei_skill/tool.py` | pending | pending | pending | pending | pending | pending |
| M99 | G8 | `webui/paste_in/bundle.py` | pending | pending | pending | pending | pending | pending |
| M100 | G8 | `tools/generate_paste_in.py` | pending | pending | pending | pending | pending | pending |
| M101 | G8 | `tools/render_nucllei_guide.py` | pending | pending | pending | pending | pending | pending |
| M102 | G8 | `tests/nucllei_support.py` | pending | pending | pending | pending | pending | pending |
| M103 | G8 | `tests/test_nucllei_artifacts.py` | pending | pending | pending | pending | pending | pending |
| M104 | G8 | `tests/test_nucllei_checks.py` | pending | pending | pending | pending | pending | pending |
| M105 | G8 | `tests/test_nucllei_docs.py` | pending | pending | pending | pending | pending | pending |
| M106 | G8 | `tests/test_nucllei_tool.py` | pending | pending | pending | pending | pending | pending |
| M107 | G8 | `tests/test_paste_in_bundle.py` | pending | pending | pending | pending | pending | pending |
| M108 | G9 | `webui/__init__.py` | pending | pending | pending | pending | pending | pending |
| M109 | G9 | `webui/__main__.py` | pending | pending | pending | pending | pending | pending |
| M110 | G9 | `webui/banner.py` | pending | pending | pending | pending | pending | pending |
| M111 | G9 | `webui/banner.json` | pending | pending | pending | pending | pending | pending |
| M112 | G9 | `webui/bootstrap.py` | pending | pending | pending | pending | pending | pending |
| M113 | G9 | `webui/client.py` | pending | pending | pending | pending | pending | pending |
| M114 | G9 | `webui/settings.py` | pending | pending | pending | pending | pending | pending |
| M115 | G9 | `webui/model_stub.py` | pending | pending | pending | pending | pending | pending |
| M116 | G9 | `webui/codex_bridge.py` | pending | pending | pending | pending | pending | pending |
| M117 | G9 | `webui/launch.sh` | pending | pending | pending | pending | pending | pending |
| M118 | G9 | `model_backend/__init__.py` | pending | pending | pending | pending | pending | pending |
| M119 | G9 | `model_backend/__main__.py` | pending | pending | pending | pending | pending | pending |
| M120 | G9 | `model_backend/adapter.py` | pending | pending | pending | pending | pending | pending |
| M121 | G9 | `model_backend/app.py` | pending | pending | pending | pending | pending | pending |
| M122 | G9 | `model_backend/engine.py` | pending | pending | pending | pending | pending | pending |
| M123 | G9 | `model_backend/models.py` | pending | pending | pending | pending | pending | pending |
| M124 | G9 | `model_backend/origin.py` | pending | pending | pending | pending | pending | pending |
| M125 | G9 | `model_backend/runtime/pyproject.toml` | pending | pending | pending | pending | pending | pending |
| M126 | G9 | `model_backend/settings.py` | pending | pending | pending | pending | pending | pending |
| M127 | G9 | `model_backend/smoke.py` | pending | pending | pending | pending | pending | pending |
| M128 | G9 | `model_backend/snapshot.py` | pending | pending | pending | pending | pending | pending |
| M129 | G9 | `model_backend/runtime/snapshot.json` | pending | pending | pending | pending | pending | pending |
| M130 | G9 | `tests/test_webui_banner_prompts.py` | pending | pending | pending | pending | pending | pending |
| M131 | G9 | `tests/test_webui_cli.py` | pending | pending | pending | pending | pending | pending |
| M132 | G9 | `tests/test_webui_client.py` | pending | pending | pending | pending | pending | pending |
| M133 | G9 | `tests/test_webui_codex_bridge.py` | pending | pending | pending | pending | pending | pending |
| M134 | G9 | `tests/test_webui_launch.py` | pending | pending | pending | pending | pending | pending |
| M135 | G9 | `tests/test_webui_model_stub.py` | pending | pending | pending | pending | pending | pending |
| M136 | G9 | `tests/test_webui_python_exposure.py` | pending | pending | pending | pending | pending | pending |
| M137 | G9 | `tests/test_webui_settings.py` | pending | pending | pending | pending | pending | pending |
| M138 | G9 | `tests/test_model_backend_adapter.py` | pending | pending | pending | pending | pending | pending |
| M139 | G9 | `tests/test_model_backend_adapter_internal.py` | pending | pending | pending | pending | pending | pending |
| M140 | G9 | `tests/test_model_backend_runtime.py` | pending | pending | pending | pending | pending | pending |
| M141 | G9 | `tests/test_model_backend.py` | pending | pending | pending | pending | pending | pending |
| M142 | G10 | `tools/gate.sh` | pending | pending | pending | pending | pending | pending |
| M143 | G10 | `tools/fast-gate.sh` | pending | pending | pending | pending | pending | pending |
| M144 | G10 | `tools/gate-probe.sh` | pending | pending | pending | pending | pending | pending |
| M145 | G10 | `tools/mutate.py` | pending | pending | pending | pending | pending | pending |
| M146 | G10 | `tools/mutation_credit.py` | pending | pending | pending | pending | pending | pending |
| M147 | G10 | `tools/render_diagrams.py` | pending | pending | pending | pending | pending | pending |
| M148 | G10 | `tools/render_gallery.py` | pending | pending | pending | pending | pending | pending |
| M149 | G10 | `tools/subset_test_font.py` | pending | pending | pending | pending | pending | pending |
| M150 | G10 | `tools/mutants/*` | pending | pending | pending | pending | pending | pending |
| M151 | G10 | `tools/py311/pyproject.toml` | pending | pending | pending | pending | pending | pending |
| M152 | G10 | `webui/runtime/pyproject.toml` | pending | pending | pending | pending | pending | pending |
| M153 | G10 | `pyproject.toml` | pending | pending | pending | pending | pending | pending |
| M154 | G10 | `.python-version` | pending | pending | pending | pending | pending | pending |
| M155 | G10 | `.gitignore` | pending | pending | pending | pending | pending | pending |
| M156 | G10 | `.env.example` | pending | pending | pending | pending | pending | pending |
| M157 | G10 | `.github/dependabot.yml` | pending | pending | pending | pending | pending | pending |
| M158 | G10 | `.github/workflows/codeql.yml` | pending | pending | pending | pending | pending | pending |
| M159 | G10 | `.github/workflows/gate.yml` | pending | pending | pending | pending | pending | pending |
| M160 | G10 | `tests/conftest.py` | pending | pending | pending | pending | pending | pending |
| M161 | G10 | `tests/test_gate.py` | pending | pending | pending | pending | pending | pending |
| M162 | G10 | `tests/test_spec.py` | pending | pending | pending | pending | pending | pending |
| M163 | G10 | `tests/test_symbol_citations.py` | pending | pending | pending | pending | pending | pending |
| M164 | G10 | `tests/test_mutation_catalogues.py` | pending | pending | pending | pending | pending | pending |
| M165 | G10 | `tests/test_measurement_exposure.py` | pending | pending | pending | pending | pending | pending |
| M166 | G10 | `tests/test_readme_register.py` | pending | pending | pending | pending | pending | pending |
| M167 | G10 | `tests/test_verification_docs.py` | pending | pending | pending | pending | pending | pending |
| M168 | G10 | `tests/test_admin_docs.py` | pending | pending | pending | pending | pending | pending |
| M169 | G10 | `tests/test_gallery.py` | pending | pending | pending | pending | pending | pending |
| M170 | G10 | `.agent/spec-lint` | pending | pending | pending | pending | pending | pending |
| M171 | G10 | `.secrets.baseline` | pending | pending | pending | pending | pending | pending |
| M172 | G10 | `docs/gallery/entries.toml` | pending | pending | pending | pending | pending | pending |
| M173 | G10 | `docs/gallery/cases.toml` | pending | pending | pending | pending | pending | pending |
| M174 | G11 | `.agent/measurements/all_results.py` | pending | pending | pending | pending | pending | pending |
| M175 | G11 | `.agent/measurements/c1_export.py` | pending | pending | pending | pending | pending | pending |
| M176 | G11 | `.agent/measurements/c1_pyodide.mjs` | pending | pending | pending | pending | pending | pending |
| M177 | G11 | `.agent/measurements/chain_demo.mjs` | pending | pending | pending | pending | pending | pending |
| M178 | G11 | `.agent/measurements/check.py` | pending | pending | pending | pending | pending | pending |
| M179 | G11 | `.agent/measurements/codex_context.py` | pending | pending | pending | pending | pending | pending |
| M180 | G11 | `.agent/measurements/f7_export.py` | pending | pending | pending | pending | pending | pending |
| M181 | G11 | `.agent/measurements/f7_wrapper.mjs` | pending | pending | pending | pending | pending | pending |
| M182 | G11 | `.agent/measurements/i1_census.py` | pending | pending | pending | pending | pending | pending |
| M183 | G11 | `.agent/measurements/i1_pyodide.mjs` | pending | pending | pending | pending | pending | pending |
| M184 | G11 | `.agent/measurements/i2_ambiguity.py` | pending | pending | pending | pending | pending | pending |
| M185 | G11 | `.agent/measurements/i3_export.py` | pending | pending | pending | pending | pending | pending |
| M186 | G11 | `.agent/measurements/i3_pyodide.mjs` | pending | pending | pending | pending | pending | pending |
| M187 | G11 | `.agent/measurements/image_import.py` | pending | pending | pending | pending | pending | pending |
| M188 | G11 | `.agent/measurements/image_leg.py` | pending | pending | pending | pending | pending | pending |
| M189 | G11 | `.agent/measurements/luna_classify.py` | pending | pending | pending | pending | pending | pending |
| M190 | G11 | `.agent/measurements/luna_facts.py` | pending | pending | pending | pending | pending | pending |
| M191 | G11 | `.agent/measurements/luna_live.mjs` | pending | pending | pending | pending | pending | pending |
| M192 | G11 | `.agent/measurements/m10u3_demo.mjs` | pending | pending | pending | pending | pending | pending |
| M193 | G11 | `.agent/measurements/m10u3_readback.mjs` | pending | pending | pending | pending | pending | pending |
| M194 | G11 | `.agent/measurements/m15u1_status.mjs` | pending | pending | pending | pending | pending | pending |
| M195 | G11 | `.agent/measurements/m16u1_checks.mjs` | pending | pending | pending | pending | pending | pending |
| M196 | G11 | `.agent/measurements/m16u1_dump.py` | pending | pending | pending | pending | pending | pending |
| M197 | G11 | `.agent/measurements/make_r_inputs.py` | pending | pending | pending | pending | pending | pending |
| M198 | G11 | `.agent/measurements/make_s6_csv.py` | pending | pending | pending | pending | pending | pending |
| M199 | G11 | `.agent/measurements/make_t8_inputs.py` | pending | pending | pending | pending | pending | pending |
| M200 | G11 | `.agent/measurements/ns_sandbox.py` | pending | pending | pending | pending | pending | pending |
| M201 | G11 | `.agent/measurements/nucllei_live.py` | pending | pending | pending | pending | pending | pending |
| M202 | G11 | `.agent/measurements/nucllei_render.mjs` | pending | pending | pending | pending | pending | pending |
| M203 | G11 | `.agent/measurements/nucllei_render_corpus.py` | pending | pending | pending | pending | pending | pending |
| M204 | G11 | `.agent/measurements/o8_bundle.mjs` | pending | pending | pending | pending | pending | pending |
| M205 | G11 | `.agent/measurements/q46_mx150.sh` | pending | pending | pending | pending | pending | pending |
| M206 | G11 | `.agent/measurements/q78_summary.py` | pending | pending | pending | pending | pending | pending |
| M207 | G11 | `.agent/measurements/q79_corpus.py` | pending | pending | pending | pending | pending | pending |
| M208 | G11 | `.agent/measurements/q79_render.mjs` | pending | pending | pending | pending | pending | pending |
| M209 | G11 | `.agent/measurements/r_compare.py` | pending | pending | pending | pending | pending | pending |
| M210 | G11 | `.agent/measurements/r_probe.py` | pending | pending | pending | pending | pending | pending |
| M211 | G11 | `.agent/measurements/r_pyodide.mjs` | pending | pending | pending | pending | pending | pending |
| M212 | G11 | `.agent/measurements/r_results.py` | pending | pending | pending | pending | pending | pending |
| M213 | G11 | `.agent/measurements/r_run.sh` | pending | pending | pending | pending | pending | pending |
| M214 | G11 | `.agent/measurements/r_supplement.py` | pending | pending | pending | pending | pending | pending |
| M215 | G11 | `.agent/measurements/rerun_all.py` | pending | pending | pending | pending | pending | pending |
| M216 | G11 | `.agent/measurements/s6_pyodide.mjs` | pending | pending | pending | pending | pending | pending |
| M217 | G11 | `.agent/measurements/t3.py` | pending | pending | pending | pending | pending | pending |
| M218 | G11 | `.agent/measurements/t4.py` | pending | pending | pending | pending | pending | pending |
| M219 | G11 | `.agent/measurements/t5.py` | pending | pending | pending | pending | pending | pending |
| M220 | G11 | `.agent/measurements/t6_pyodide.mjs` | pending | pending | pending | pending | pending | pending |
| M221 | G11 | `.agent/measurements/t7_profile.py` | pending | pending | pending | pending | pending | pending |
| M222 | G11 | `.agent/measurements/t7_pyodide.mjs` | pending | pending | pending | pending | pending | pending |
| M223 | G11 | `.agent/measurements/t7_quoted.py` | pending | pending | pending | pending | pending | pending |
| M224 | G11 | `.agent/measurements/t8_profile.py` | pending | pending | pending | pending | pending | pending |
| M225 | G11 | `.agent/measurements/t8_pyodide.mjs` | pending | pending | pending | pending | pending | pending |
| M226 | G11 | `.agent/measurements/versions.mjs` | pending | pending | pending | pending | pending | pending |
| M227 | G11 | `.agent/measurements/x1_transforms.py` | pending | pending | pending | pending | pending | pending |

Generated artifacts (`paste-in/*`, `webui/demo-paste-in/*`, `llens/nucllei/**`, `llens/ext/public/**`, `docs/diagrams/*.svg`, `docs/gallery/*.png`) = B6-B9 + their source rows; `LICENSE` + `src/verifier/py.typed` = no lens applies.

### Docs

| id | path | CLAIM | SPEC | REG |
|---|---|---|---|---|
| P1 | `.agent/measurements/README.md` | pending | pending | pending |
| P2 | `.agent/measurements/luna/README.md` | pending | pending | pending |
| P3 | `.agent/measurements/nucllei/README.md` | pending | pending | pending |
| P4 | `README.md` | pending | pending | pending |
| P5 | `docs/admin/README.ja.md` | pending | pending | pending |
| P6 | `docs/admin/README.md` | pending | pending | pending |
| P7 | `docs/admin/nucllei.ja.md` | pending | pending | pending |
| P8 | `docs/admin/nucllei.md` | pending | pending | pending |
| P9 | `docs/checks.ja.md` | pending | pending | pending |
| P10 | `docs/checks.md` | pending | pending | pending |
| P11 | `docs/diagrams/verifier-nucllei.dot` | pending | pending | pending |
| P12 | `docs/diagrams/verifier-nucllei.ja.dot` | pending | pending | pending |
| P13 | `docs/diagrams/verifier.dot` | pending | pending | pending |
| P14 | `docs/diagrams/verifier.ja.dot` | pending | pending | pending |
| P15 | `docs/gallery.ja.md` | pending | pending | pending |
| P16 | `docs/gallery.md` | pending | pending | pending |
| P17 | `docs/nucllei/checks.ja.md` | pending | pending | pending |
| P18 | `docs/nucllei/checks.md` | pending | pending | pending |
| P19 | `docs/verification.ja.md` | pending | pending | pending |
| P20 | `docs/verification.md` | pending | pending | pending |
| P21 | `model_backend/runtime/README.md` | pending | pending | pending |
| P22 | `webui/README.md` | pending | pending | pending |

### Spec index

One row per `Intent` sentence (S) + `Decisions` bullet (D): the check that pins it; an unpinned behavioral sentence = a finding.

| id | text | pinning check | verdict |
|---|---|---|---|
| S1 | A chat assistant where a model writes the Python that draws a … | pending | pending |
| S2 | The model proposes only code, plus an optional note: when the request, … | pending | pending |
| S3 | The program runs unchanged in the host's code sandbox (the nucllei sandbox, … | pending | pending |
| S4 | The verifier inspects the finished matplotlib figure. | pending | pending |
| S5 | Every artist must belong to a closed set that the verifier judges. | pending | pending |
| S6 | A figure that matplotlib did not draw, or that holds an artist … | pending | pending |
| S7 | Every judged artist must obey a comprehensive, closed set of integrity rules: … | pending | pending |
| S8 | Where the user supplied data, the verifier also checks that the drawn … | pending | pending |
| S9 | The data is an attached CSV's raw values or one group-and-reduce of … | pending | pending |
| S10 | A value that the verifier cannot find blocks the figure. | pending | pending |
| S11 | A figure with no data source is checked for integrity alone, and … | pending | pending |
| S12 | For CSV figures, column anchoring stays: the request must name the drawn … | pending | pending |
| S13 | Text on the chart is listed, never judged. | pending | pending |
| S14 | Verification uses no inference: every decision is a deterministic rule. | pending | pending |
| S15 | Pass ⇒ inline PNG + `Figure verification passed` + the list of … | pending | pending |
| S16 | Fail ⇒ blocked + `Figure verification failed, no image produced` + the … | pending | pending |
| S17 | When the latest message holds a kana letter, the verifier writes its … | pending | pending |
| S18 | Acceptance: a committed rule corpus, with at least one misleading program per … | pending | pending |
| S19 | Live runs add to it: honest prompts pass, and prompts that ask … | pending | pending |
| S20 | The verifier alone decides. | pending | pending |
| S21 | Model guidance (on nucllei, the skill text and the tool description; on … | pending | pending |
| S22 | Production artifact: the nucllei skill, two generated files (the skill text and … | pending | pending |
| S23 | Open WebUI keeps its two generated files (a tool and a filter) … | pending | pending |
| S24 | The verifier is embedded and needs nothing beyond stdlib + what the … | pending | pending |
| S25 | The target instance has no outside network, so nothing may require a … | pending | pending |
| S26 | The repo's own stack is the demo harness, not the deliverable. | pending | pending |
| S27 | Demo-grade: correctness testing yes; crypto sealing, escrow and tamper-evidence ceremonies no. | pending | pending |
| S28 | The claim stays modest: verified = the drawn figure obeys every integrity … | pending | pending |
| S29 | The program is assumed non-adversarial: it runs before any check, in the … | pending | pending |
| S30 | The renderer, browser, code sandbox, matplotlib and pixels are trusted, not verified. | pending | pending |
| S31 | On nucllei, the verifier decides the figures that `draw_figure` shows; the model's … | pending | pending |
| S32 | Fidelity to intent (the right quantity for the question) is never claimed … | pending | pending |
| D1 | Trust spine: the model supplies a program, never data; the … | pending | pending |
| D2 | Program rulings (kept from python mode): (1) the model authors … | pending | pending |
| D3 | Demo shape: the launcher's OWUI runs the demo pair = … | pending | pending |
| D4 | **IMPLEMENT-close rulings (user; the kept four).** (4) G10 deferred, then … | pending | pending |
| D5 | M10 mechanism (M19.5 form): trusted outlet filter → backend-recorded receipt … | pending | pending |
| D6 | **M10 rulings (user, four).** (1) PASS transport = **tool call … | pending | pending |
| D7 | **M10 transport ruling (user).** Demo transport = a paste-in filter … | pending | pending |
| D8 | **Template ruling (user; L1 narrowed by Q40 + the System-prompt … | pending | pending |
| D9 | **Admin-docs ruling (user, phase close (4)).** The admin docs live … | pending | pending |
| D10 | Proposer: fp16 `Qwen2.5-Coder-0.5B-Instruct` on the MX150 (device record `model_backend/runtime/README.md` § … | pending | pending |
| D11 | **Codex-arm ruling (user, session 13).** A stronger live proposer = … | pending | pending |
| D12 | Stack: `uv` + py 3.14 cap · stdlib verifier core … | pending | pending |
| D13 | **Failure-reason rulings (user, M15).** (1) A FAIL reply = one … | pending | pending |
| D14 | **Check-breakdown rulings (user, M16).** (1) Surface = ONE OWUI message … | pending | pending |
| D15 | **Production-vs-demo rulings (user, session 6).** (1) "Strict rules in general … | pending | pending |
| D16 | **Japanese-demo rulings (user, M17).** (1) `data/clinic_ja.csv` = the Japanese-header CSV … | pending | pending |
| D17 | **Check-detail rulings (user, M18).** (1) Each "Show checks" row opens … | pending | pending |
| D18 | **Short-guide ruling (user, Q72).** `docs/verification.md` stays the complete reference; the … | pending | pending |
| D19 | **Row-excerpt rulings (user, session 9; M20).** (1) Every "Show checks" … | pending | pending |
| D20 | OWUI integration = the M10 units, all closed (records `.agent/archive/implement.md`, … | pending | pending |
| D21 | **Integrity-redesign rulings (user, thirteen; the shipped product since the M19 … | pending | pending |
| D22 | **Computed-values rulings (user, session 10; Q45, contract `.agent/archive/contracts/q45.md`).** (1) Admitted: … | pending | pending |
| D23 | **Security-review rulings (user, session 11; record `.agent/archive/contracts/m21u1.md`).** (1) A security … | pending | pending |
| D24 | **Second security-review rulings (user, session 12; record `.agent/archive/contracts/m22u1.md`).** (1) No … | pending | pending |
| D25 | **Model-note rulings (user, Q78; contract `.agent/archive/contracts/q78.md`).** (1) The chart rules … | pending | pending |
| D26 | **Verdict-language ruling (user, Q81; contract `.agent/archive/contracts/q81.md`).** A kana request (the … | pending | pending |
| D27 | **nucllei-skill rulings (user, session 14; Q82; contract `.agent/archive/contracts/q82.md`, law `.claude/rules/nucllei.md`).** … | pending | pending |
| D28 | **Request-scope ruling (user, Q66; contract `.agent/archive/contracts/q66.md`).** The request (anchoring, typed … | pending | pending |
| D29 | **System-prompt ruling (user, session 8).** Nothing from this repository enters … | pending | pending |
| D30 | **M19 readings (user, session 8; the integrity redesign's open forks; … | pending | pending |
| D31 | **Queue rulings (user, queue session question round).** (1) An inverted … | pending | pending |
| D32 | **Upgrade rulings (user, upgrade request).** (1) Open WebUI → latest … | pending | pending |

### Conformance map

`decidable` = a tool can decide the clause (`yes` · `no` · `n/a: binds no tracked file`); `check` = the gate check that decides it; `firing` = its red on a planted bad input (probe or plant).

| id | clause | text | decidable | check | firing | verdict |
|---|---|---|---|---|---|---|
| L1 | CLAUDE.md § Collaboration 1 | Uncertain / needs a decision / benefits from my … | pending | pending | pending | pending |
| L2 | CLAUDE.md § Collaboration 2 | When discussion may improve the work, open one proactively: … | pending | pending | pending | pending |
| L3 | CLAUDE.md § Collaboration 3 | Stay objective; push back on my ideas when warranted … | pending | pending | pending | pending |
| L4 | CLAUDE.md § Collaboration 4 | A failed attempt is a valid result: report it … | pending | pending | pending | pending |
| L5 | CLAUDE.md § Execution 1 | Install/configure project-local; work within the launch dir + children; … | pending | pending | pending | pending |
| L6 | CLAUDE.md § Execution 2 | Long horizon → orient, then execute: one session carries … | pending | pending | pending | pending |
| L7 | CLAUDE.md § Execution 3 | Finish line = a pasted body's `Met when`, else … | pending | pending | pending | pending |
| L8 | CLAUDE.md § Execution 4 | Research, whenever a tooling, method or design choice is … | pending | pending | pending | pending |
| L9 | CLAUDE.md § Execution 5 | Git: creds in the global gitconfig; standing permission for … | pending | pending | pending | pending |
| L10 | CLAUDE.md § Execution 6 | Gate command = the full check chain `.claude/rules/` records; … | pending | pending | pending | pending |
| L11 | CLAUDE.md § Execution 7 | CI gate: a public GitHub repo whose `main` CI … | pending | pending | pending | pending |
| L12 | CLAUDE.md § Execution 8 | Evidence: capture rc on the spot (`cmd; rc=$?`); an … | pending | pending | pending | pending |
| L13 | CLAUDE.md § Execution 9 | Command output rides the context → the quietest useful … | pending | pending | pending | pending |
| L14 | CLAUDE.md § Execution 10 | Task close → remove the temporary + stale artifacts … | pending | pending | pending | pending |
| L15 | CLAUDE.md § Execution 11 | UI design (artifact, variant or unit): the subject's domain, … | pending | pending | pending | pending |
| L16 | CLAUDE.md § Execution 12 | Charts + figures: the data's job picks the form, … | pending | pending | pending | pending |
| L17 | CLAUDE.md § Authoring 1 | AI agents = the sole developers ⇒ agent-optimized = … | pending | pending | pending | pending |
| L18 | CLAUDE.md § Authoring 2 | State rules, facts + warnings plainly; omit provenance — … | pending | pending | pending | pending |
| L19 | CLAUDE.md § Authoring 3 | Future-facing text, esp. prompts → state the desired action … | pending | pending | pending | pending |
| L20 | CLAUDE.md § Authoring 4 | Prompts + instruction files state task, finish line + … | pending | pending | pending | pending |
| L21 | CLAUDE.md § Authoring 5 | Guidance + checks on text = goals + reasons, … | pending | pending | pending | pending |
| L22 | CLAUDE.md § Authoring 6 | Instruction files = yours to maintain → update any … | pending | pending | pending | pending |
| L23 | CLAUDE.md § Authoring 7 | `.claude/rules/` reaches MAIN + every teammate of an interactive … | pending | pending | pending | pending |
| L24 | CLAUDE.md § Authoring 8 | `@path` imports (instruction files) + attaches (my messages) a … | pending | pending | pending | pending |
| L25 | CLAUDE.md § Authoring 9 | Human-facing = strictly user-facing surfaces a person reads at … | pending | pending | pending | pending |
| L26 | CLAUDE.md § Engineering 1 | Elegant, tightly-scoped modular components; deduplicate; KISS + UNIX where … | pending | pending | pending | pending |
| L27 | CLAUDE.md § Engineering 2 | Code = agent-read artifact → concise within three bounds: … | pending | pending | pending | pending |
| L28 | CLAUDE.md § Engineering 3 | Comments cost tokens → spend them on the `why` … | pending | pending | pending | pending |
| L29 | CLAUDE.md § Engineering 4 | Target sufficient scope, evidence-backed claims + real success criteria. | pending | pending | pending | pending |
| L30 | CLAUDE.md § Engineering 5 | Established methods (TDD red-green-refactor, differential oracles, adversarial review) + … | pending | pending | pending | pending |
| L31 | CLAUDE.md § Engineering 6 | Open tooling decisions (language/library/package…) → research (`Execution`) + select … | pending | pending | pending | pending |
| L32 | CLAUDE.md § Engineering 7 | Deterministic checks own every rule a tool can decide: … | pending | pending | pending | pending |
| L33 | CLAUDE.md § Engineering 8 | Tests/verification: derive scope from requested outcome + regression risk … | pending | pending | pending | pending |
| L34 | CLAUDE.md § Engineering 9 | Runnable change → run the real app by its … | pending | pending | pending | pending |
| L35 | CLAUDE.md § Engineering 10 | Verification integrity binds every check on the implementation; a … | pending | pending | pending | pending |
| L36 | CLAUDE.md § Engineering 11 | Assurance tier, declared per unit with its contract: `kernel` … | pending | pending | pending | pending |
| L37 | CLAUDE.md § Engineering 12 | Units = the shortest path to the consumable artifact, … | pending | pending | pending | pending |
| L38 | CLAUDE.md § Engineering 13 | A gate backing a durable claim must rerun from … | pending | pending | pending | pending |
| L39 | CLAUDE.md § Engineering 14 | Repairs to a generated artifact land as one idempotent … | pending | pending | pending | pending |
| L40 | CLAUDE.md § Engineering 15 | Adversarial review (code or session) → scrutinize correctness + … | pending | pending | pending | pending |
| L41 | CLAUDE.md § Engineering 16 | Code diff lenses = the author's self-review before each … | pending | pending | pending | pending |
| L42 | CLAUDE.md § Engineering 17 | Split assurance by what it costs the decider: mechanical … | pending | pending | pending | pending |
| L43 | CLAUDE.md § Engineering 18 | Review terminates on a check set fixed before the … | pending | pending | pending | pending |
| L44 | CLAUDE.md § Engineering 19 | Delegated reports are two-tier: a verdict table the decider … | pending | pending | pending | pending |
| L45 | CLAUDE.md § Engineering 20 | Remotely-exploitable code → highest security standard: periodically audit, update … | pending | pending | pending | pending |
| L46 | CLAUDE.md § Teammates 1 | MAIN does the work: a planned unit's code, docs … | pending | pending | pending | pending |
| L47 | CLAUDE.md § Teammates 2 | Offload economics: fresh-context + blindness fits pay at any … | pending | pending | pending | pending |
| L48 | CLAUDE.md § Teammates 3 | Briefs + prompts (teammates, `SendMessage`, `claude -p`) = broader … | pending | pending | pending | pending |
| L49 | CLAUDE.md § Teammates 4 | Names = role + gapless ordinal (`reviewer-2`), so `SendMessage` … | pending | pending | pending | pending |
| L50 | CLAUDE.md § Teammates 5 | Harvest: marker + turn end → read the deliverable … | pending | pending | pending | pending |
| L51 | CLAUDE.md § Teammates 6 | A code-writing teammate works in `git worktree add -b … | pending | pending | pending | pending |
| L52 | CLAUDE.md § Teammates 7 | Shared mutable resources (build stores, DBs, ports, work tree, … | pending | pending | pending | pending |
| L53 | CLAUDE.md § Teammates 8 | Advisor, where present = MAIN's call per case at … | pending | pending | pending | pending |
| L54 | CLAUDE.md § Session flow 1 | Phases, `Phase:` in `.agent/spec.md` = the phase + its … | pending | pending | pending | pending |
| L55 | CLAUDE.md § Session flow 2 | `.agent/spec.md` = the sole attached state, imported by the … | pending | pending | pending | pending |
| L56 | CLAUDE.md § Session flow 3 | PROTOTYPE = the fastest path to an artifact I … | pending | pending | pending | pending |
| L57 | CLAUDE.md § Session flow 4 | IMPLEMENT = the best version of the intended software, … | pending | pending | pending | pending |
| L58 | CLAUDE.md § Session flow 5 | Routing: phase per kind of work — an open … | pending | pending | pending | pending |
| L59 | CLAUDE.md § Session flow 6 | Routed state: `Phase` line 1 = `<PHASE> — <scope>`; … | pending | pending | pending | pending |
| L60 | CLAUDE.md § Session flow 7 | This file + `.claude/agents/` = copies of a shared … | pending | pending | pending | pending |
| L61 | CLAUDE.md § Session flow 8 | Rules upkeep rides the `Tasks` clearing: each phase close … | pending | pending | pending | pending |
| L62 | CLAUDE.md § Session flow 9 | Checkpointing: a phase session compacts many times ⇒ state … | pending | pending | pending | pending |
| L63 | CLAUDE.md § Session flow 10 | Teammates: fits, reasons + mechanics = `Teammates`; the phase … | pending | pending | pending | pending |
| L64 | CLAUDE.md § Session flow 10a | PROTOTYPE + ITERATE: teammates = cheap + shallow, artifacts … | pending | pending | pending | pending |
| L65 | CLAUDE.md § Session flow 10b | IMPLEMENT + MAINTAIN: teammates = deep; each unit's depth … | pending | pending | pending | pending |
| L66 | CLAUDE.md § Session flow 10c | IMPLEMENT phase fits, any depth: `researcher` = SOTA survey … | pending | pending | pending | pending |
| L67 | CLAUDE.md § Session flow 11 | Advisor (fits + rulings = `Teammates`; its bar follows … | pending | pending | pending | pending |
| L68 | CLAUDE.md § Session flow 12 | Read cost control = `.gitignore` kept current — content … | pending | pending | pending | pending |
| L69 | assurance.md 1 | 100% branch coverage answers "did the line execute", never … | pending | pending | pending | pending |
| L70 | assurance.md 2 | A test that reads a production constant to build … | pending | pending | pending | pending |
| L71 | assurance.md 3 | CLOSED dispatch enumerates every admitted variant: an `else:` tail … | pending | pending | pending | pending |
| L72 | assurance.md 4 | ORDERING needs call-counting bombs on the downstream work, one … | pending | pending | pending | pending |
| L73 | assurance.md 5 | A FAKE must match the real API's strictness: a … | pending | pending | pending | pending |
| L74 | assurance.md 6 | Module-level dispatch maps bind function objects at import ⇒ … | pending | pending | pending | pending |
| L75 | assurance.md 7 | A purity bomb on a global PYTEST ITSELF uses … | pending | pending | pending | pending |
| L76 | assurance.md 8 | Split canonical FORM (byte-exact under an injected fixed TCB, … | pending | pending | pending | pending |
| L77 | assurance.md 9 | Guard witnesses MIXED not uniform; independent bounds need their … | pending | pending | pending | pending |
| L78 | assurance.md 10 | A differential that sets no `PYTHONPATH` can compare a … | pending | pending | pending | pending |
| L79 | assurance.md 11 | Hypothesis: profiles in `tests/conftest.py` (`ci` derandomized default; `HYPOTHESIS_PROFILE=dev`); import … | pending | pending | pending | pending |
| L80 | assurance.md 12 | The gate runs the suite under pytest-xdist (`-n auto`, … | pending | pending | pending | pending |
| L81 | assurance.md 13 | Shipped sources spell an alias `X: TypeAlias = Literal[...]` … | pending | pending | pending | pending |
| L82 | assurance.md 14 | `cast`, not `assert`, narrows `X \| None` at a … | pending | pending | pending | pending |
| L83 | assurance.md 15 | A "no edit needed" list is an assertion ⇒ … | pending | pending | pending | pending |
| L84 | assurance.md 16 | A diff-blind suite states a contract READING: where a … | pending | pending | pending | pending |
| L85 | assurance.md 17 | Doc guarantee strings (READMEs, the reference, the short guide, … | pending | pending | pending | pending |
| L86 | assurance.md 18 | Verification integrity (`CLAUDE.md` `Engineering`), project bindings: a unit's grading … | pending | pending | pending | pending |
| L87 | assurance.md 19 | Claim discipline: cite only retained-log numbers; frame unproven root … | pending | pending | pending | pending |
| L88 | claims.md 1 | Verified = the drawn figure obeys every integrity check … | pending | pending | pending | pending |
| L89 | claims.md 2 | Trusted, NOT verified: the renderer, browser, pixels, the code … | pending | pending | pending | pending |
| L90 | claims.md 3 | Fidelity to INTENT (the right quantity for the question) … | pending | pending | pending | pending |
| L91 | claims.md 4 | Model guidance (filter inlet template, `draw_figure` description) MAY state … | pending | pending | pending | pending |
| L92 | claims.md 5 | nucllei scope (Q82): the verifier decides the figures `draw_figure` … | pending | pending | pending | pending |
| L93 | claims.md 6 | Corpus claims are scoped: the rule corpus's both-ways 100% … | pending | pending | pending | pending |
| L94 | claims.md 7 | Human-facing text at a demo boundary inherits claim discipline: … | pending | pending | pending | pending |
| L95 | codex-bridge.md 1 | Shape: OpenAI `/v1` (`GET /models`, `POST /chat/completions`, stream or … | pending | pending | pending | pending |
| L96 | codex-bridge.md 2 | Clean context is MEASURED, never assumed: `uv run --locked … | pending | pending | pending | pending |
| L97 | codex-bridge.md 3 | Isolation: own `CODEX_HOME` + `HOME` (`.codex-bridge/`, gitignored) ⇒ the … | pending | pending | pending | pending |
| L98 | codex-bridge.md 4 | Request origin (M23.1 F2; law shared with the backend … | pending | pending | pending | pending |
| L99 | codex-bridge.md 5 | Tool call: `item/tool/call` ⇒ `turn/interrupt` goes on the wire … | pending | pending | pending | pending |
| L100 | codex-bridge.md 6 | Provisioning: `--codex` = `WEBUI_PROVISION_MODEL_ID=gpt-6-luna` + `WEBUI_PROVISION_PASTE_IN=production` (`paste-in/` pair, strict … | pending | pending | pending | pending |
| L101 | codex-bridge.md 7 | Live record = `.agent/measurements/luna/` (`luna_live.mjs` drives, `luna_classify.py` re-judges each … | pending | pending | pending | pending |
| L102 | codex-bridge.md 8 | Live batches need the CPU: the browser's Pyodide run … | pending | pending | pending | pending |
| L103 | figure.md 1 | Program = model-authored bytes, run UNCHANGED in the host's … | pending | pending | pending | pending |
| L104 | figure.md 2 | `CLAUDE.md` `Execution` Charts + figures clause INAPPLICABLE to verification … | pending | pending | pending | pending |
| L105 | figure.md 3 | Wrapper (RPC code) = loader prelude → reader source … | pending | pending | pending | pending |
| L106 | figure.md 4 | Reader = trusted FACT reporter (`src/verifier/figure/reader.py`, matplotlib + pandas … | pending | pending | pending | pending |
| L107 | figure.md 5 | Hooks: `Text.set_text` → a text's `site` = the last … | pending | pending | pending | pending |
| L108 | figure.md 6 | Sandbox = Open WebUI 0.12.3's Pyodide 314.0.3 (CPython 3.14.2; … | pending | pending | pending | pending |
| L109 | figure.md 7 | table: \| check \| reasons \| | pending | pending | pending | pending |
| L110 | figure.md 8 | Figure: exactly one shown figure (`no_figure` / `multiple_figures`). Children: … | pending | pending | pending | pending |
| L111 | figure.md 9 | Axes: class exactly `Axes`, owned by the figure (`fig.axes`), … | pending | pending | pending | pending |
| L112 | figure.md 10 | Axes children = structural slots (patch, 4 spines, x/y … | pending | pending | pending | pending |
| L113 | figure.md 11 | table: \| family \| class \| origin … | pending | pending | pending | pending |
| L114 | figure.md 12 | `mark_not_in_data`: a data artist's data-bearing transform ≠ `transData` (line/area/pie: … | pending | pending | pending | pending |
| L115 | figure.md 13 | `scale_not_linear` (R3): a non-linear axis passes only when it … | pending | pending | pending | pending |
| L116 | figure.md 14 | `axis_inverted`: either axis inverted (ruling 3; both axes), except … | pending | pending | pending | pending |
| L117 | figure.md 15 | `tick_label_mismatch`: a visible non-empty tick label in view — … | pending | pending | pending | pending |
| L118 | figure.md 16 | `point_clipped`: any drawn data coordinate (points, bar base + … | pending | pending | pending | pending |
| L119 | figure.md 17 | `zero_not_in_limits` (R1): a magnitude mark (bar, hist, area) ⇒ … | pending | pending | pending | pending |
| L120 | figure.md 18 | `mark_hidden`: a hidden axes, or a data artist not … | pending | pending | pending | pending |
| L121 | figure.md 19 | `value_not_finite`: NaN / ±inf among drawn data or recorded … | pending | pending | pending | pending |
| L122 | figure.md 20 | `bar_not_from_zero` (G1, R1): every bar's base = 0, or … | pending | pending | pending | pending |
| L123 | figure.md 21 | `bars_overlap`: two bars' rectangles overlap with positive area (grouped … | pending | pending | pending | pending |
| L124 | figure.md 22 | `bar_width_varies` (user ruling, luna F6): every bar of one … | pending | pending | pending | pending |
| L125 | figure.md 23 | `category_not_unique`: two points of one series share a key … | pending | pending | pending | pending |
| L126 | figure.md 24 | `x_not_ordered` (G9): a line's key positions run both ways … | pending | pending | pending | pending |
| L127 | figure.md 25 | `hist_counts`: hist rects contiguous on the recorded bin edges, … | pending | pending | pending | pending |
| L128 | figure.md 26 | `pie_not_whole`: wedges share one radius + width (an exploded … | pending | pending | pending | pending |
| L129 | figure.md 27 | `area_not_from_zero`: each band GROUNDED: its base edge all zero, … | pending | pending | pending | pending |
| L130 | figure.md 28 | `marker_size_varies` / `marker_color_varies`: a scatter collection whose sizes / … | pending | pending | pending | pending |
| L131 | figure.md 29 | `legend_mismatch`: each legend entry names one judged mark (handle … | pending | pending | pending | pending |
| L132 | figure.md 30 | Reference marks: each value = zero, a request number, … | pending | pending | pending | pending |
| L133 | figure.md 31 | Pie keys = each wedge's drawn label Text (final … | pending | pending | pending | pending |
| L134 | figure.md 32 | Series = one line · scatter collection · bar … | pending | pending | pending | pending |
| L135 | figure.md 33 | Sources: each attached CSV (`csvread` profile; non-profile columns unusable) … | pending | pending | pending | pending |
| L136 | figure.md 34 | CSV explanations (closed): `raw(K,V)` (incl. `raw(K,K)`: a channel encoding … | pending | pending | pending | pending |
| L137 | figure.md 35 | Per value EITHER (ruling 4): one CSV explanation per … | pending | pending | pending | pending |
| L138 | figure.md 36 | Ties: ≥ 2 explanations with different column sets fully … | pending | pending | pending | pending |
| L139 | figure.md 37 | **Computed values (Q45, user, session 10; contract `.agent/archive/contracts/q45.md`).** The … | pending | pending | pending | pending |
| L140 | figure.md 38 | Drawn columns per CSV = every explanation's K and … | pending | pending | pending | pending |
| L141 | figure.md 39 | G10 (`label_not_consistent`): titles, axis labels, axes legend entries, the … | pending | pending | pending | pending |
| L142 | figure.md 40 | Publication (tier 3): per-group counts beside every reduction (G11), … | pending | pending | pending | pending |
| L143 | gate-checks.md 1 | Probe mechanics (`tools/gate-probe.sh`): each probe mutates ONE tracked file … | pending | pending | pending | pending |
| L144 | gate-checks.md 2 | Firing records — attribution rides the message, eleven tests … | pending | pending | pending | pending |
| L145 | gate-checks.md 3 | A widened sweep splits its probe with the widening: … | pending | pending | pending | pending |
| L146 | gate-checks.md 4 | Assemble every firing-input literal at run time (`shellcheck disable=`, … | pending | pending | pending | pending |
| L147 | gate-checks.md 5 | Three shapes to hold: YAML types a bare `run: … | pending | pending | pending | pending |
| L148 | gate-checks.md 6 | S4 reads `.agent/{spec,deferred,review}.md` + every `.claude/rules/*.md`, deciding only ROOTED … | pending | pending | pending | pending |
| L149 | gate-checks.md 7 | S6 reads PROSE, not headings: `_UNIT = re.compile(r"M(\d+)\.(\d+)([a-z]?)")` matches … | pending | pending | pending | pending |
| L150 | gate-checks.md 8 | S8 reads `tests/` rather than the state files, because … | pending | pending | pending | pending |
| L151 | gate-checks.md 9 | Measurement replay (`.agent/measurements/rerun_all.py`) positive control: plant R1's expected Kahan … | pending | pending | pending | pending |
| L152 | host-runtime.md 1 | Two tiers, incompatible hosts. ORIGIN (source of all M3–M8 … | pending | pending | pending | pending |
| L153 | host-runtime.md 2 | Runtime GO on CURRENT = FUNCTIONAL (user, upgrade request: … | pending | pending | pending | pending |
| L154 | host-runtime.md 3 | ORIGIN-tuple evidence (M3/M4/M6/M7/M8 live-stack gates) cannot be re-taken on … | pending | pending | pending | pending |
| L155 | host-runtime.md 4 | **The BROWSER tier runs on any host.** `.venv-webui` (uv-managed … | pending | pending | pending | pending |
| L156 | host-runtime.md 5 | **Request origin (M23.1 F2 + F4).** No model-tier server … | pending | pending | pending | pending |
| L157 | host-runtime.md 6 | **Browser automation + remote browsing = `.claude/rules/owui.md`** (direct CDP … | pending | pending | pending | pending |
| L158 | host-runtime.md 7 | **Port seam is small + isolated**: `app.py` touches only … | pending | pending | pending | pending |
| L159 | host-runtime.md 8 | **Any replacement engine must reproduce two contracts byte-exactly**: (1) … | pending | pending | pending | pending |
| L160 | host-runtime.md 9 | Model IDENTITY is duplicated beyond `model_backend/`: `webui/settings.py` + `webui/README.md`, … | pending | pending | pending | pending |
| L161 | host-runtime.md 10 | The demo proposer is deliberately small; its live arms … | pending | pending | pending | pending |
| L162 | human-facing.md 1 | Authoring audience split (`CLAUDE.md` `Authoring` `Human-facing`). HUMAN-FACING ⇒ ASD-STE100 … | pending | pending | pending | pending |
| L163 | human-facing.md 2 | Diagrams (Q72, user: Graphviz `dot`, no image generation; "elaborate … | pending | pending | pending | pending |
| L164 | human-facing.md 3 | Gallery (Q72, user: "a gallery that showcases all the … | pending | pending | pending | pending |
| L165 | human-facing.md 4 | Length = judgment under `L-LAW`, never a count (`CLAUDE.md` … | pending | pending | pending | pending |
| L166 | human-facing.md 5 | `CLAUDE.md` `Authoring` agent-optimized default ADAPTED (user ruling): its `prompts` … | pending | pending | pending | pending |
| L167 | human-facing.md 6 | `CLAUDE.md` `Authoring` UI-copy clause ADAPTED: the status line's ` … | pending | pending | pending | pending |
| L168 | human-facing.md 7 | nucllei surfaces (Q82): HUMAN-FACING = `docs/admin/nucllei{,.ja}.md`, `docs/nucllei/checks{,.ja}.md` + its … | pending | pending | pending | pending |
| L169 | human-facing.md 8 | AGENT-OPTIMIZED as a CLASS (never re-litigate string by string): … | pending | pending | pending | pending |
| L170 | nucllei.md 1 | Shape (rulings 1, 10): skill `figure-verification` (`llens/nucllei/skills/figure-verification.md`, from `nucllei_skill/skill.py`) … | pending | pending | pending | pending |
| L171 | nucllei.md 2 | llens `scripts/nucllei/sync.py` = the deployment path: tool id = … | pending | pending | pending | pending |
| L172 | nucllei.md 3 | Model-facing surfaces (Japanese, ruling 7): the skill body, the … | pending | pending | pending | pending |
| L173 | nucllei.md 4 | No outlet hook, no Pyodide: `draw_figure` = one `POST … | pending | pending | pending | pending |
| L174 | nucllei.md 5 | User data (consultant-1 T7, T8): request text + attachments … | pending | pending | pending | pending |
| L175 | nucllei.md 6 | Publication: the PNG → `Storage.upload_file` + `Files.insert_new_file` (a `None` … | pending | pending | pending | pending |
| L176 | nucllei.md 7 | Tests: `tests/nucllei_support.py` fakes keep the real signatures (`Files.get_file_by_id(id, include_deleted=False)`, … | pending | pending | pending | pending |
| L177 | nucllei.md 8 | Target stack = measurement NS (`ns_sandbox.py`, replay id `NS`): … | pending | pending | pending | pending |
| L178 | nucllei.md 9 | Images: `sudo podman build --network=host -t localhost/nucllei{,-sandbox}:v20261020-01` from the … | pending | pending | pending | pending |
| L179 | ops.md 1 | Env: `uv sync --locked` builds `.venv` (py 3.14, gitignored); … | pending | pending | pending | pending |
| L180 | ops.md 2 | **Gate = `bash tools/gate.sh`** — the ONE invocation; a … | pending | pending | pending | pending |
| L181 | ops.md 3 | **CI gate** (`CLAUDE.md` `CI gate`) = the full gate's … | pending | pending | pending | pending |
| L182 | ops.md 4 | **Fresh-host form** (a local full run with every stage … | pending | pending | pending | pending |
| L183 | ops.md 5 | **Fast gate (iteration) = `bash tools/fast-gate.sh [<pytest node\|path> …]`**: … | pending | pending | pending | pending |
| L184 | ops.md 6 | **Gate positive controls = `bash tools/gate-probe.sh`**: every PURPOSE-BUILT check … | pending | pending | pending | pending |
| L185 | ops.md 7 | **Measurement harnesses = `.agent/measurements/`**, NOT in the gate and … | pending | pending | pending | pending |
| L186 | ops.md 8 | Gate internals = `uv run --locked ruff format --check … | pending | pending | pending | pending |
| L187 | ops.md 9 | Shared live resources, one named holder per wave: ports … | pending | pending | pending | pending |
| L188 | ops.md 10 | Teammate worktrees: `.scratch/worktrees/<name>` on `wt/<name>`; from `<wt>` gate with … | pending | pending | pending | pending |
| L189 | ops.md 11 | Running the FULL `tools/gate.sh` from a worktree resyncs the … | pending | pending | pending | pending |
| L190 | ops.md 12 | Read-and-conform-to set for every brief: gate above · oracles … | pending | pending | pending | pending |
| L191 | ops.md 13 | Unit lifecycle (IMPLEMENT): contract `.agent/contracts/<unit>.md` (testable predicates + invariant … | pending | pending | pending | pending |
| L192 | ops.md 14 | License `Apache-2.0 WITH LLVM-exception`; SPDX header in every tracked … | pending | pending | pending | pending |
| L193 | ops.md 15 | Census the instruction surface off `git ls-files`, never bare … | pending | pending | pending | pending |
| L194 | ops.md 16 | Live law (`.claude/rules/*.md`) cites tracked code as `<file>.py::<name>` (`<file>.py::<Class>.<member>` … | pending | pending | pending | pending |
| L195 | ops.md 17 | Template drift (`CLAUDE.md`, `.claude/agents/`, `.agent/spec-lint`): a widened template rule … | pending | pending | pending | pending |
| L196 | owui.md 1 | Sandbox mechanism (shipped = `webui/paste_in/filter.py`, M19.5; measured on 0.10.2, … | pending | pending | pending | pending |
| L197 | owui.md 2 | Pyodide **`314.0.3`** (runtime CPython 3.14.2, wasm32; 0.10.2 shipped 0.28.3) … | pending | pending | pending | pending |
| L198 | owui.md 3 | `execute:python` needs a LIVE browser socket: the headless harness … | pending | pending | pending | pending |
| L199 | owui.md 4 | Current surface: `webui/settings.py` provisions the PASTE-IN tool (`tool_id=figure_verification`, operation … | pending | pending | pending | pending |
| L200 | owui.md 5 | **`function_name_filter_list` cannot narrow a tool server and must never … | pending | pending | pending | pending |
| L201 | owui.md 6 | **Paste-in law (M10.0 onward).** The pasted artifact is GENERATED … | pending | pending | pending | pending |
| L202 | owui.md 7 | **Demo transport (M10.6; Q40; ruling 8).** The paste-in filter's … | pending | pending | pending | pending |
| L203 | owui.md 8 | Tool provisioning REST shapes (settled on 0.10.2; the 0.12.3 … | pending | pending | pending | pending |
| L204 | owui.md 9 | CSV bytes in-process (CSV ruling): `await Files.get_file_by_id_and_user_id(id, user_id, db=None)` … | pending | pending | pending | pending |
| L205 | owui.md 10 | OWUI's OWN narration path cannot carry the verdict: under … | pending | pending | pending | pending |
| L206 | owui.md 11 | Verdict totality (F4): the filter rewrites the LAST assistant … | pending | pending | pending | pending |
| L207 | owui.md 12 | **Failure reasons (M15.1, `.agent/archive/contracts/m15u1.md`).** Every FAIL outlet call = … | pending | pending | pending | pending |
| L208 | owui.md 13 | **Check breakdown (M16.1, re-keyed by M19.5).** Every FAIL (after … | pending | pending | pending | pending |
| L209 | owui.md 14 | **Row disclosures (M18.2 + M20.2; ruling 13).** Each row … | pending | pending | pending | pending |
| L210 | owui.md 15 | The harness client reads a persisted reply's final text … | pending | pending | pending | pending |
| L211 | owui.md 16 | Browser automation = direct CDP over a scratch profile, … | pending | pending | pending | pending |
| L212 | owui.md 17 | **Signing key = one per instance** (`webui/settings.py::Settings.signing_key`: the operator's … | pending | pending | pending | pending |
| L213 | owui.md 18 | Remote browsing forwards 8080 ALONE: the python-mode PNG is … | pending | pending | pending | pending |
| L214 | owui.md 19 | **Japanese text = the server's Japanese font, cut per … | pending | pending | pending | pending |
| L215 | owui.md 20 | **Client content blockers kill the PASS arm silently.** `ENABLE_PYODIDE_FILE_PERSISTENCE` … | pending | pending | pending | pending |
| L216 | owui.md 21 | **A real-model `-m webui chat` needs `WEBUI_PROVISION_READY_TIMEOUT=600`.** The persisted-chat … | pending | pending | pending | pending |
| L217 | owui.md 22 | **Banner arms (M19.5).** `webui/banner.json` = six arms — `simple` … | pending | pending | pending | pending |
| L218 | pysrc.md 1 | Drawn columns = the columns whose explanation backs the … | pending | pending | pending | pending |
| L219 | pysrc.md 2 | **Substitution (the demo's rule, Q8):** refuse `column_not_requested` only on … | pending | pending | pending | pending |
| L220 | pysrc.md 3 | **Strict (production's rule, Q37):** the substitution check, then: a … | pending | pending | pending | pending |
| L221 | pysrc.md 4 | **Matcher.** Safe because the model gets no vote: the … | pending | pending | pending | pending |
| L222 | pysrc.md 5 | **Stops + negation (Q38).** Before naming, `anchoring.py::_unnamed_places` consumes the … | pending | pending | pending | pending |
| L223 | pysrc.md 6 | **Japanese short words (Q41, strict alone).** `anchoring.py::_short_names`: a whole … | pending | pending | pending | pending |
| L224 | pysrc.md 7 | **Admin aliases (Q43).** `Aliases` = (column, alias) pairs — … | pending | pending | pending | pending |
| L225 | pysrc.md 8 | A model-produced translation of the request may never become … | pending | pending | pending | pending |
| L226 | pysrc.md 9 | **G10 labels** (`columns.py::check_labels`, law `.claude/rules/figure.md` § Columns): a label … | pending | pending | pending | pending |
| L227 | pysrc.md 10 | **Restrict, never reimplement.** The sandbox calls plain `pd.read_csv`, whose … | pending | pending | pending | pending |
| L228 | pysrc.md 11 | A STRUCTURAL fault refuses the whole file (`Unreadable`: `csv_not_parsable` … | pending | pending | pending | pending |
| L229 | pysrc.md 12 | A demo dataset never spells a group key with … | pending | pending | pending | pending |
| L230 | pysrc.md 13 | pandas reduces a float64 group with ordered binary64 Kahan … | pending | pending | pending | pending |
| L231 | tooling.md 1 | ruff `S603` fires when argv is not visibly constant: … | pending | pending | pending | pending |
| L232 | tooling.md 2 | `httpx` imports directly in tests (transitive via Litestar's TestClient, … | pending | pending | pending | pending |
| L233 | tooling.md 3 | `requires-python = ">=3.14,<3.15"` + `.python-version` pin the line; the … | pending | pending | pending | pending |
| L234 | tooling.md 4 | Shipped sources (`src/verifier`, `webui/paste_in`, both generated pairs) = CPython … | pending | pending | pending | pending |
| L235 | tooling.md 5 | Second interpreter: `UV_PROJECT_ENVIRONMENT=.scratch/venv-py3142 UV_LINK_MODE=copy COVERAGE_FILE=.scratch/coverage-py3142 uv run --locked --python … | pending | pending | pending | pending |
| L236 | transformers.md 1 | **`dtype=` takes a STRING** (`getattr(torch, dtype)`, `modeling_utils.py:858`, documented `:3967`) | pending | pending | pending | pending |
| L237 | transformers.md 2 | **`generate` is already `@torch.no_grad()`** (`generation/utils.py:2568-2570`) and | pending | pending | pending | pending |
| L238 | transformers.md 3 | **`pad_token_id` is SCALAR-ONLY; `eos_token_id` accepts `int \| list[int]`** | pending | pending | pending | pending |
| L239 | transformers.md 4 | **No finish-reason exists in `generate`'s output or its stopping … | pending | pending | pending | pending |
| L240 | transformers.md 5 | **`do_sample=False` + a non-default `temperature` = logged warning, never … | pending | pending | pending | pending |
| L241 | transformers.md 6 | **`apply_chat_template(tokenize=True, return_dict=True)` returns a `BatchEncoding`** with exactly | pending | pending | pending | pending |
| L242 | transformers.md 7 | **`BatchEncoding.to(device)` returns `self` but REBUILDS `.data`** | pending | pending | pending | pending |
| L243 | transformers.md 8 | **Decoder-only `generate` returns prompt+suffix and does not mutate the … | pending | pending | pending | pending |
| L244 | transformers.md 9 | **`local_files_only=True` is NOT needed to resolve a valid local … | pending | pending | pending | pending |
| L245 | transformers.md 10 | **`device_map` requires accelerate** (`integrations/accelerate.py:96-141`); a device STRING | pending | pending | pending | pending |
| L246 | transformers.md 11 | **Concurrent `generate` on one model = UNSETTLED BY EVIDENCE, … | pending | pending | pending | pending |
| L247 | transformers.md 12 | **A single unpadded sequence needs no `attention_mask`** — `generate` … | pending | pending | pending | pending |
