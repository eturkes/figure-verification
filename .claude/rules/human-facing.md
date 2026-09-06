---
paths:
  - "**/README.md"
  - "POC_SCOPE.md"
  - "webui/launch.sh"
  - "webui/enforcement_filter.py"
  - "src/verifier/render.py"
  - "src/verifier/service/app.py"
  - "src/verifier/service/openapi.py"
  - "src/verifier/service/audit.py"
  - "src/verifier/service/__main__.py"
  - "bench/__main__.py"
  - "demo/__main__.py"
  - "model_backend/__main__.py"
  - "model_backend/verified_chart.py"
  - "webui/__main__.py"
---

# Human-facing surface list + authoring pins

- Authoring audience split (`CLAUDE.md` Authoring). HUMAN-FACING ⇒ ASD-STE100 binds: the five shipped READMEs (`README.md` + `webui`/`bench`/`demo`/`model_backend/runtime` operator recipes) + product/operator strings. `examples/README.md` stays OFF this list — `memory.md` holds it in the agent-optimized CLASS, so audit it against `CLAUDE.md` Authoring alone and keep its rows dense — `webui/launch.sh` `usage()` + READY banner, `enforcement_filter` `FILTER_NAME`/`FILTER_DESCRIPTION`/`BLOCKED_NOTICE`, `render.badge_html`/`signed_chart_html` labels + `<title>`, `VERIFIED_CHART_REPLY`, `app.py` OpenAPI `summary=` + chat success summary, CLI `description=`/`help=` literals, `audit._CLI_FAILURE`. `--help` is human-facing, a docstring is not ⇒ give `ArgumentParser` an explicit register-conformant `description=` + leave the docstring agent-optimized. A `README.md` block quote of an internal doc is a QUOTATION first: quoted claim/TCB lines stay byte-identical to the cited `POC_SCOPE.md` lines, so the register binds the README's OWN prose alone — re-diff the quoted substring after editing either file. Re-registering is free EXCEPT three pins: `audit._CLI_FAILURE` byte-pinned; `app.py`'s success summary regex-pinned by `verified_chart._SUMMARY_RE`; each OpenAPI `summary=` triplicated across `app.py` + `service/openapi.py` + the `schema/openapi.json` golden. `tests/test_webui_client.py` `_CHAT_TEXT` mirrors `VERIFIED_CHART_REPLY` as an INDEPENDENT fake-server fixture, not a pin.
