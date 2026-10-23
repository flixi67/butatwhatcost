# butatwhatcost ◡

> *"I have AI'ed... but at what cost?"*

![Wario meme](assets/wario-but-at-what-cost.png)

A [Hermes Agent](https://hermes-agent.nousresearch.com/docs) skill that answers the
eternal question — **how much did THIS session cost on DeepInfra?**

Type `/butatwhatcost` in any chat, or just ask *"what did this session cost?"*.

## What it does

- Pulls **live pricing** from the DeepInfra backend (`GET /v1/models` →
  `metadata.pricing`), so the numbers are always the current per-million rates.
- Reads the **token ledger** for the current session from Hermes's
  `state.db` → `session_model_usage` (per model, per task).
- Is **lineage-aware**: compressed sessions are summed across their whole
  parent chain, so a long, compacted conversation reports its true total.
- **Recomputes cost from raw tokens × live rates** — never from Hermes's
  possibly-stale `estimated_cost_usd` snapshot (that's only the fallback when
  a model has no public rate).
- Cross-checks against the **DeepInfra account dashboard** (`/payment/usage`)
  so you can sanity-check the month-to-date spend under your key.

```
butatwhatcost — session 20261022_001801_025bf129
  deepseek-ai/DeepSeek-V4-Flash-0731  calls=272 in=5,670,588 out=304,208 cache=32,102,832 reas=199,890  cost=$0.9125
      live rates: in $0.06/M out $0.18/M cache_read $0.015/M
  TOTAL calls=288 in=5,720,587 out=321,785 cache=32,830,848 reas=214,167 cost=$0.9125
  DeepInfra account (month): $2292.96
```

## Install

1. Clone (or copy) this skill into your Hermes skills directory:

   ```bash
   git clone https://github.com/flixi67/butatwhatcost.git \
     "$HOME/AppData/Local/hermes/skills/butatwhatcost"   # Windows
   # or ~/.hermes/skills/butatwhatcost on Linux/macOS
   ```

2. Make sure `DEEPINFRA_API_KEY` is set in your Hermes `.env` (the script reads
   it itself; it is never printed).

3. `/reload-skills` if your session predates the install, then type
   `/butatwhatcost`.

## Requirements

- Hermes Agent
- Python 3 (stdlib only — no third-party dependencies)
- A `state.db` with a `session_model_usage` table (Hermes keeps this for you)
- `DEEPINFRA_API_KEY` in `.env`

## Options

| Flag | Meaning |
| --- | --- |
| `--session-id <id>` | Cost an explicitly named session instead of this one |
| `--months N` | Widen the account cross-check window |
| `--no-account` | Skip the `/payment/usage` call (e.g. offline) |
| `--json` | Machine-readable output |

## Notes

- All arithmetic lives in `scripts/butatwhatcost.py` — the agent never does
  the math in its head.
- `cache_write_tokens` are billed at the input rate and `reasoning_tokens` at
  the output rate (DeepInfra exposes only input/output/cache_read rates).
- The account-month total covers **all** traffic under your API key (every
  session, anything else) — it is a dashboard cross-check, never "this session".

## License

[MIT](LICENSE)
