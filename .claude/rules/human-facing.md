---
paths:
  - "**/README.md"
  - "docs/**"
  - "webui/launch.sh"
  - "webui/paste_in/filter.py"
  - "webui/paste_in/reasons.py"
  - "webui/paste_in/checks.py"
  - "webui/settings.py"
  - "src/verifier/figure/interpret.py"
  - "capture/__main__.py"
  - "capture/harness.py"
  - "capture/record.py"
  - "capture/corpus.py"
  - "model_backend/__main__.py"
  - "webui/__main__.py"
---

# Human-facing surface list + authoring pins

- Authoring audience split (`CLAUDE.md` Authoring). HUMAN-FACING ⇒ ASD-STE100 binds: the shipped READMEs (`README.md` + `webui`/`model_backend/runtime` operator recipes) + the admin guide `docs/admin/README.md` + the reference `docs/verification.md` (each "Show checks" row links its `check-<id>` section; sentence budget + passive ban = `tests/test_readme_register.py`; coverage of checks, reasons + limits = `tests/test_verification_docs.py`) with its Japanese twin `docs/verification.ja.md` (natural polite Japanese, same facts in the same order); `docs/admin/README.ja.md` = natural polite Japanese (です/ます), one instruction per step, parity pinned by `tests/test_admin_docs.py`; MODEL-facing (ruling 8: may state the integrity rules, no system prompt ships) = `webui/paste_in/templates.py` + the `draw_figure` docstring. Product/operator strings: `webui/launch.sh` `usage()` + READY banner, `webui/paste_in/filter.py` `FILTER_NAME`/`FILTER_DESCRIPTION` + the two verdict strings `PASS_TEXT`/`FAIL_TEXT` (bytes fixed by `Intent` ⇒ never re-registered), `webui/paste_in/reasons.py` `REASONS` (the status line a chat user reads: EN = this register, one cause sentence + at most one fix sentence; JA = natural polite Japanese, the admin guide's terms `検証器`/`ブラウザ`/`受け入れる`; the ` (<reason>)` suffix = code, verbatim; anchors byte-pinned by `tests/test_paste_in_reasons.py`), `webui/paste_in/checks.py` row texts (≤ 25 words per sentence; the "Show checks" embed a chat user reads: EN = label register, title ≤ 10 words, covers ≤ 25; JA = natural UI Japanese, same terms; no full-width punctuation that ruff `RUF001` flags; a covers line names only what its check enforces; the 9 check ids + their order pinned by `tests/test_paste_in_checks.py`), `webui/settings.py` `_TOOL_NAME`/`_TOOL_DESCRIPTION` (the workspace labels an ADMIN reads beside the provisioned tool — NOT the artifact's `draw_figure` docstring, which the MODEL reads), CLI `description=`/`help=` literals, `src/verifier/figure/interpret.py::interpretation` (the published interpretation a clinician reads, EN + natural polite Japanese on a kana request, the same facts in the same order, quoted strings verbatim). `--help` is human-facing, a docstring is not ⇒ give `ArgumentParser` an explicit register-conformant `description=` + leave the docstring agent-optimized.
- AGENT-OPTIMIZED as a CLASS (never re-litigate string by string): `.agent/*`, `.claude/*`, module/function docstrings, settings/identity exception text, `_LOGGER` key=value records.
