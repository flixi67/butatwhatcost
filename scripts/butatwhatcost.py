#!/usr/bin/env python3
"""butatwhatcost — DeepInfra live pricing + this Hermes session's cost.

Fetches live pricing from the DeepInfra backend (/v1/models), reads the token
ledger for the CURRENT session from Hermes's state.db (session_model_usage,
lineage-aware), and recomputes cost from raw tokens x live rates.
"""


def cost_for(tokens: int, rate_per_million: float) -> float:
    """USD cost = tokens * ($/M tokens) / 1e6."""
    return (tokens or 0) * float(rate_per_million or 0.0) / 1_000_000.0


def model_cost(tokens: dict, price: dict) -> float:
    """Sum input/output/cache_read at their live rates; cache_write is billed at
    the input rate and reasoning tokens at the output rate (DeepInfra's pricing
    metadata exposes only input/output/cache_read)."""
    return (
        cost_for(tokens.get("input_tokens", 0), price["input_tokens"])
        + cost_for(tokens.get("output_tokens", 0), price["output_tokens"])
        + cost_for(tokens.get("cache_read_tokens", 0), price["cache_read_tokens"])
        + cost_for(tokens.get("cache_write_tokens", 0), price["input_tokens"])
        + cost_for(tokens.get("reasoning_tokens", 0), price["output_tokens"])
    )


def parse_pricing(payload: dict) -> dict:
    """Map model_id -> {input_tokens, output_tokens, cache_read_tokens, discount}
    from a /v1/models payload. A model with no pricing metadata gets {} so the
    report can fall back to Hermes's estimate for it."""
    out = {}
    for m in payload.get("data", []):
        md = m.get("metadata") or {}
        p = md.get("pricing") or {}
        if not p:
            out[m["id"]] = {}
            continue
        out[m["id"]] = {
            "input_tokens": p.get("input_tokens") or 0.0,
            "output_tokens": p.get("output_tokens") or 0.0,
            "cache_read_tokens": p.get("cache_read_tokens") or 0.0,
            "discount": md.get("discount"),
        }
    return out


def lineage_ids(con, session_id: str) -> list:
    """Current-first chain of session ids up to the root. Compression mints
    child session ids, so a faithful session total must include every ancestor."""
    chain, cur, seen = [], session_id, set()
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        row = con.execute(
            "SELECT parent_session_id FROM sessions WHERE id=?", (cur,)
        ).fetchone()
        cur = row[0] if row else None
    return chain


def session_usage(con, session_ids: list) -> list:
    """All session_model_usage rows for the given session ids.
    Columns: model, task, api_call_count, input_tokens, output_tokens,
    cache_read_tokens, cache_write_tokens, reasoning_tokens, estimated_cost_usd."""
    q = ("SELECT model, task, api_call_count, input_tokens, output_tokens, "
         "cache_read_tokens, cache_write_tokens, reasoning_tokens, "
         "estimated_cost_usd FROM session_model_usage "
         f"WHERE session_id IN ({','.join('?' * len(session_ids))})")
    return con.execute(q, session_ids).fetchall()
