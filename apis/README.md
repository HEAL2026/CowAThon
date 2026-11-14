# APIs

Owner: @uiobio (Lei)

Owns the **integration layer**: the API functions that connect the dashboard to
external farm monitoring and management systems, and the mocks that stand in
for them.

> Run this folder from a **separate agent session** from `frontend/`. One
> session per folder keeps the two tracks parallel and keeps the board posts
> readable. Lei sets that session up when he picks this up — see
> [AGENTS.md](../AGENTS.md) for the per-session checklist (`gh auth login`,
> `BOARD_ISSUE`, `tools/board unread`, a background `tools/board wait`).

## Why this folder exists

Small farms cannot afford every monitoring system on the market, and the ones
they can afford differ farm to farm. So the dashboard has to let an operator
**attach or detach an integration** without a rebuild: enable the two systems
the farm actually pays for, leave the rest off, and still get a coherent
dashboard. That means every system sits behind one common interface, with its
own adapter in this folder.

## Boundary

In scope here:

- One **adapter per external system** (herd management, milk metering, feed,
  weather, wearables/collars, barn environment, …), each behind the same
  interface.
- A **registry** the dashboard reads to know which integrations exist, which
  are attached, and what each one provides.
- **Mock adapters** that serve realistic fixture data for any system we cannot
  hit live, so the whole dashboard is demoable offline.
- Auth, retry, rate-limit, and pagination handling per adapter; its own config
  and secrets handling (secrets never committed).
- **Capability and cost metadata** per adapter — what signals it provides, at
  what cadence, and the rough cost/feasibility note that lets the dashboard
  tell a small farmer whether it is worth attaching.

Not in scope, and owned elsewhere:

- Rendering, dashboard layout, and which integrations a given user has toggled
  on — `frontend/`.
- Ingestion, validation, normalization, time alignment, and missing-value
  policy — `backend-cleaning/`
  ([CONTRACT.md](../backend-cleaning/CONTRACT.md)). Adapters here fetch and
  shape payloads; they do not become a second cleaning pipeline.
- Statistical analysis and documented metrics — `backend-analysis/`.
- Visualization-ready payload shaping — `backend-visualization/`.
- Model training and inference — `model/`.

## Shape of an adapter (proposal, Lei's call)

The two things the rest of the repo needs to rely on are that every adapter
looks the same, and that a detached adapter degrades gracefully instead of
breaking a view:

- **Describe itself** — id, display name, the signals it provides, cadence,
  and a cost/feasibility note.
- **Report health** — configured, reachable, authenticated, or unavailable,
  so the dashboard can show a detached or failing integration as missing data
  rather than an error.
- **Fetch a window** — given a time range (and `cow_id` where the system is
  per-animal), return records keyed the way `backend-cleaning/` expects:
  `cow_id` + `ts_utc`.

Everything else — language, file layout, async or sync, how the registry is
declared — is Lei's design decision. Fill it in here, and post on the board
when the interface is settled, because `frontend/` and `backend-cleaning/`
both consume it.

## Mocks

Mock adapters are first-class, not throwaway: they are what the demo runs on.
Keep fixtures small, committed, and obviously synthetic, and keep a mock
behind the same interface as the real adapter so swapping one for the other
changes no caller. Never present mock output as real farm data in the UI —
label it.
