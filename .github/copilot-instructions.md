# Copilot instructions

Before making changes, read `AGENTS.md` and the relevant role README:

- `frontend/` for the user-facing application
- `backend-cleaning/` for ingestion and reproducible data cleaning
- `backend-analysis/` for statistical analysis and documented metrics
- `backend-visualization/` for visualization-ready backend payloads

Use the pinned GitHub issue as the team message board. Run `tools/board unread`
at the start of work and before committing; post concise updates with the
required `[<human>'s <agent>]` prefix. Do not edit another teammate's owned
folder without a handoff on the board.

Keep role boundaries explicit, document interfaces at their source, and use
the repository's existing tooling and tests before adding dependencies.
