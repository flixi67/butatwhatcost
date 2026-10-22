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
