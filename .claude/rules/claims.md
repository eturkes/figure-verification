---
paths:
  - "**/README.md"
  - "docs/**"
  - "webui/paste_in/**"
  - "webui/banner.json"
---

# Claim scope — what the project may say (a loose restatement is a regression)

- Verified = the drawn figure obeys every integrity check (`docs/verification.md`, law `.claude/rules/figure.md`) AND, where data was supplied, every drawn value is that data: an attached CSV's raw values or one group-and-reduce of them, or the numbers typed in the request (ranges expanded). Nothing stronger: never "the chart is correct", "the chart answers the question" or "every misleading chart blocks".
- Trusted, NOT verified: the renderer, browser, pixels, the Pyodide sandbox + its bundled packages (matplotlib, pandas, numpy), the interpreter, the Open WebUI-bundled Noto Sans JP font the wrapper registers. The program is assumed NON-ADVERSARIAL: it runs before any check, in the interpreter the reader shares, and can reach the browser's network (the stock Open WebUI code-interpreter posture) ⇒ a stated limit wherever verification is described, never a guarantee.
- Fidelity to INTENT (the right quantity for the question) is never claimed beyond column anchoring: a CSV figure must draw columns the request names (production strict, demo substitution). On-chart text (annotations, value labels, free text) is LISTED, never judged. No data source ⇒ integrity alone, and the reply says so.
- Model guidance (filter inlet template, `draw_figure` description) MAY state the rules; it never moves the boundary — the verifier alone decides. Nothing from this repo enters the production system prompt.
- Corpus claims are scoped: the rule corpus's both-ways 100% = the committed cases on host matplotlib 3.9.4 + measurement C1 (the same cases through the production wrapper in the installed Open WebUI bundle, matplotlib 3.8.4). A live arm = an observation on one `(device, config)` with its run count + host tuple; a misleading-arm run whose figure lacks the requested distortion counts as such, never as a block.
- Human-facing text at a demo boundary inherits claim discipline: stub outcomes stated flatly, real-model arms conditional (`Expect …`) until measured; an STE rewrite must not upgrade a hedge into an assertion — re-check every rewritten behavioural sentence against this file.
