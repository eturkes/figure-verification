# Memory — figure-verification

Cross-session live context + lessons. Trajectory: `roadmap.md` + git. Process: `AGENTS.md`, `CLAUDE.md`. Earn each entry; delete when obsolete.

## State
- Initial session = boilerplate only: git (`main` branch), `LICENSE`, `.gitignore`, this file, `.claude/settings.json`; committed `roadmap.md` as-is. No project code yet — `roadmap.md` milestones drive it. User manually steers the next few sessions; slash commands left as-is by request.

## Conventions
- License id: `Apache-2.0 WITH LLVM-exception`. Source files carry header `SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception` (language-appropriate comment). `LICENSE` = project-neutral Apache 2.0 body + LLVM exception only (LLVM banner / NCSA / third-party sections stripped from upstream LLVM LICENSE.TXT).
- Do-not-read enforcement lives in `.claude/settings.json` `permissions.deny` `Read()` (committed; needed because Read/Bash bypass `.gitignore`). Keep synced as files land. `LICENSE` (+ future `uv.lock`) are in it. Serena's parallel = `.serena/project.yml` `ignored_paths`, non-gitignored entries only.
- Git identity from global gitconfig (`Emir Turkes <eturkes@bu.edu>`); user drives remote.

## Deferred
- `.serena/project.yml` not created (Serena unused this session). On first Serena activation let it scaffold, then add `ignored_paths: [LICENSE]`.
