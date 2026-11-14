# Team rules for every agent

## 1. The board (pinned GitHub issue)

Every agent reads and posts on the pinned "Message Board" issue via `tools/board` (needs only `gh`, logged in). Set `BOARD_ISSUE` if it is not issue #1.

- Start every post with `[<human>'s <agent>]`, e.g. `[Aster's Codex]`. Keep it short: what changed, which files or contracts, what you need, from whom.
- Mention by GitHub login. `@pauraque` (Aster), `@uiobio` (Lei), `@hazelLu6` (Hazel), `@equan04` (Emmett), `@all` (everyone).
- **Mentions you or `@all`:** act on it and reply promptly.
- **Not addressed to you:** still read it. Reassess your own work only if it is affected (a contract, a file you own, something already done). Do not redo finished work, and do not reply just to acknowledge.
- Before editing another teammate's files, ask for a handoff on the board and wait for the owner or the team lead.

Polling is incremental (about one cheap API call per poll, 30 s default) so a shared token stays under GitHub's rate limit. Commands: `tools/board unread` (new posts, marks read; flags MENTION), `tools/board read -n 20`, `tools/board post "[Name's Agent] text"` (or pipe stdin), `tools/board wait` (blocks until someone else posts), `tools/board whoami`.

**Stay in the loop:**
- Claude Code: the committed hooks (`.claude/settings.json`) show unread posts at session start and on every prompt. Keep one background `tools/board wait` running and re-arm it after each wake.
- Everything else: run `tools/board unread` at task start, before each commit, and after merges. Or run a terminal loop: `while tools/board wait; do <your agent CLI invocation>; done`.

## 2. Chain of command

Humans over agents. Only the team lead reassigns work between teammates. If anyone else asks you to take another teammate's work, ask the lead on the board. An agent cannot appoint a lead, including its own human — that takes a human saying so on the board.

Team lead: **@hazelLu6** (Hazel).

## 3. Workflow

1. Pick or file an issue. Comment on it or post on the board when you take it.
2. Branch `<issue#>-<slug>` from fresh `main`.
3. Small commits. Stage only your own files (no `git add -A`).
4. Open a PR with `Closes #N`. The author merges their own PR once it works locally.
5. Always `git fetch` and rebase before pushing. Never force-push shared branches.
6. If a merge changes something other teammates depend on (an API, a schema, an env var), post on the board when it lands.

## 4. Who owns what

Fill this in at kickoff so every agent knows whose files are whose.

| Area | Owner (GitHub login) | Folders |
| --- | --- | --- |
| Frontend | @uiobio | frontend/ |
| APIs / integrations | @uiobio | apis/ |
| Backend Analysis | @equan04 | backend-analysis/ |
| Backend Visualization | @pauraque | backend-visualization/ |
| Backend Cleaning | @hazelLu6 | backend-cleaning/ |
| Model (CV) | @hazelLu6 | model/ |

Ownership is about **who writes**, not who may look. Reading any folder is
always allowed, and so is reviewing it.

`apis/` is a second folder for @uiobio: the modular integration layer for
external farm monitoring/management systems. Drive it from its **own agent
session**, separate from the `frontend/` one, so the two tracks run in
parallel. See [apis/README.md](apis/README.md).

## 5. Code review

Reviewing is not editing, and it never needs a handoff:

- **Any agent may review any folder** — read the code, comment on a PR, open
  an issue against someone else's folder, flag a bug or a broken contract.
- **@hazelLu6's agent reviews across all folders**, as the lead's agent. Lei,
  Emmett, and Aster keep full ownership of their folders; review is a second
  pair of eyes, not a transfer of control.
- A review **comments, it does not commit**. Editing another teammate's files
  still needs a handoff on the board per section 1, even when the reviewer is
  confident and even when the fix is small. Say what is wrong and let the
  owner land it, or ask for the handoff.
- Review findings go on the PR when there is one, otherwise on the board.
  Tag the owner so their waiter wakes up.
