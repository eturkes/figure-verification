# Deferral queue

One entry + acceptance check each. The spine — the unfinished units, and any blocker inside one — lives in `.agent/spec.md` `Tasks`, whose last line points here; a row here is off-spine until a unit adopts it.

- Q51 CodeQL bad-tag-filter (M21.1 F9, informational; agent part done in `git log --grep '(Q51)'`, owed: the user's push): `tests/test_paste_in_embed.py::test_every_document_carries_the_reporter_alone_and_no_trigger` now matches script tags case-insensitively with any end-tag tail (a planted `<SCRIPT>` fails it, red then green, recorded in that commit). Owed: `main` carries that commit and CodeQL analyses it. Accept: `gh api /repos/eturkes/figure-verification/code-scanning/alerts/1 --jq .state` answers `fixed`.
- Q52 Dependabot alerts (M21.1 F10, informational; remote, user-owned): GitHub reports `Dependabot alerts are disabled for this repository` (HTTP 403), so the Dependabot version PRs carry no advisory signal. Accept: `gh api /repos/eturkes/figure-verification/dependabot/alerts` answers 200.
