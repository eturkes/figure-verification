---
paths:
  - "**/README.md"
  - "docs/**"
  - "POC_SCOPE.md"
  - "webui/launch.sh"
  - "webui/paste_in/filter.py"
  - "webui/paste_in/reasons.py"
  - "webui/settings.py"
  - "src/verifier/render.py"
  - "src/verifier/service/app.py"
  - "src/verifier/service/openapi.py"
  - "src/verifier/service/audit.py"
  - "src/verifier/service/__main__.py"
  - "bench/__main__.py"
  - "capture/__main__.py"
  - "capture/harness.py"
  - "capture/record.py"
  - "capture/corpus.py"
  - "demo/__main__.py"
  - "model_backend/__main__.py"
  - "model_backend/verified_chart.py"
  - "webui/__main__.py"
---

# Human-facing surface list + authoring pins

- Authoring audience split (`CLAUDE.md` Authoring). HUMAN-FACING ⇒ ASD-STE100 binds: the shipped READMEs (`README.md` + `webui`/`bench`/`demo`/`model_backend/runtime` operator recipes) + the admin guide `docs/admin/README.md` + `docs/json-spec.md`; `docs/admin/README.ja.md` = natural polite Japanese (です/ます), one instruction per step, parity pinned by `tests/test_admin_docs.py`; `docs/admin/system_prompt.*.txt` are MODEL-facing (ruling 6 banned stems, EN + a JA rendering, pinned there) + product/operator strings. `examples/README.md` stays OFF this list (agent-optimized CLASS below) — `webui/launch.sh` `usage()` + READY banner, `webui/paste_in/filter.py` `FILTER_NAME`/`FILTER_DESCRIPTION` + the two verdict strings `PASS_TEXT`/`FAIL_TEXT` (bytes fixed by `Intent` ⇒ never re-registered), `webui/paste_in/reasons.py` `REASONS` (the status line a chat user reads: EN = this register, one cause sentence + at most one fix sentence; JA = natural polite Japanese, the admin guide's terms `検証器`/`ブラウザ`/`受け入れる`; the ` (<reason>)` suffix = code, verbatim; four anchors byte-pinned by `tests/test_paste_in_filter_reasons.py` D2), `webui/settings.py` `_TOOL_NAME`/`_TOOL_DESCRIPTION` (the workspace labels an ADMIN reads beside the provisioned tool — NOT the artifact's `draw_figure` docstring, which the MODEL reads and which ruling 6's banned-stem check owns instead), `render.badge_html`/`signed_chart_html` labels + `<title>`, `VERIFIED_CHART_REPLY`, `app.py` OpenAPI `summary=` + chat success summary, CLI `description=`/`help=` literals, `audit._CLI_FAILURE`, `pysrc` `CoreCertificate.interpretation` (the one core string a clinician reads; grammar + per-arm byte pins = `.agent/archive/contracts/m13u5.md` § The K ruling). `--help` is human-facing, a docstring is not ⇒ give `ArgumentParser` an explicit register-conformant `description=` + leave the docstring agent-optimized. A block quote of an internal doc in `docs/json-spec.md` (formerly the root `README.md`) is a QUOTATION first: quoted claim/TCB lines stay byte-identical to the cited `POC_SCOPE.md` lines, so the register binds the README's OWN prose alone — re-diff the quoted substring after editing either file. Re-registering is free EXCEPT three pins: `audit._CLI_FAILURE` byte-pinned; `app.py`'s success summary regex-pinned by `verified_chart._SUMMARY_RE`; each OpenAPI `summary=` triplicated across `app.py` + `service/openapi.py` + the `schema/openapi.json` golden. `tests/test_webui_client.py` `_CHAT_TEXT` mirrors `VERIFIED_CHART_REPLY` as an INDEPENDENT fake-server fixture, not a pin.
- AGENT-OPTIMIZED as a CLASS (never re-litigate string by string): `POC_SCOPE.md`, `VPlot_SEMANTICS.md`, `examples/README.md`, `.agent/*`, `.claude/*`, module/function docstrings, `CheckResult`/`Verdict` messages, HTTP problem `detail`, settings/identity exception text, `_LOGGER` key=value records, the `schema/openapi.json` component `description`s fed by msgspec struct docstrings — editing one of those docstrings changes the published document ⇒ regenerate the golden in the same edit. Check messages are byte-pinned by canonical-report identity: wording drift breaks that identity while every suite stays green.
