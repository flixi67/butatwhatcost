---
name: butatwhatcost
description: Use when Felix asks how much a session/task/model cost on DeepInfra, or types /butatwhatcost. Reports live DeepInfra pricing plus the cost of the CURRENT session only.
version: 1.1.0
platforms: [linux, macos, windows]
---

# butatwhatcost — how much did THIS session cost on DeepInfra?

Trigger: Felix types `/butatwhatcost` (or asks "what did this session cost?").

## Session identity (authoritative)
This session's id is: `${HERMES_SESSION_ID}`
(That placeholder is substituted with the real id when this skill loads. It is
the ONLY trustworthy session id in this conversation — see the edge-case rule.)

## Mandatory edge-case rule (two parallel sessions, same model)
NEVER guess "the most recent session" — Felix can run two sessions on the same
model in parallel, and "most recent" picks the wrong one. Attribute by session
id ONLY:

1. Pass the substituted id explicitly:
   `python "C:/Users/felix/AppData/Local/hermes/skills/butatwhatcost/scripts/butatwhatcost.py" --session-id ${HERMES_SESSION_ID}`
2. If running that fails with "session ... not found in state.db", the id was
   stale: fall back to running the script with NO flags (it then reads
   `$HERMES_SESSION_ID` from the shell env), and if that also fails, ask Felix
   which session he means.
3. Only pass a different `--session-id` when Felix explicitly names another
   session.
Never trust the shell env var over the substituted id above: the env value in a
terminal subprocess can be stale (a rolled-back id with no DB row). The script
refuses to run against an id that is not in state.db (exit 3 + a hint), so a
wrong id never silently reports $0.

## Procedure
1. Run the command from the session-identity section. stdout is the report; a
   trailing `(account usage unavailable: ...)` line on stderr is non-fatal.
2. Report back in chat, compactly, one line per model: model, tokens
   (in/out/cache/reas), live rates, cost. Then the session TOTAL and the
   DeepInfra account-month total (the dashboard cross-check). Use a table or
   short bullets — Felix wants short, compact output.
3. If a model shows "(rate unavailable; used Hermes estimate)", say so and note
   the number is Hermes's `estimated_cost_usd`, not a live-rate recompute.
4. Live pricing comes from the DeepInfra backend `GET /v1/models` →
   `metadata.pricing` (in/out/cache_read $ per M tokens). Tokens come from this
   session's rows in `state.db` `session_model_usage` (lineage-aware: compressed
   sessions are summed across their parent chain). Do not re-derive either.

## Assumptions worth knowing
- `cache_write_tokens` are billed at the input rate and `reasoning_tokens` at
  the output rate (DeepInfra exposes only input/output/cache_read rates).
- The account-month total covers ALL DeepInfra traffic under this API key
  (every Hermes session plus anything else) — it is a dashboard cross-check,
  never "this session".

## Optional flags
- `--json` for machine-readable output.
- `--months N` to widen the account cross-check window.
- `--no-account` to skip the `/payment/usage` call (e.g. offline).
- `--session-id <id>` to cost an explicitly named session instead of this one.

All math lives in the script; do not compute costs yourself.
