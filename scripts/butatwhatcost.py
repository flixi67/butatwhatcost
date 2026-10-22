#!/usr/bin/env python3
"""butatwhatcost — DeepInfra live pricing + this Hermes session's cost.

Fetches live pricing from the DeepInfra backend (/v1/models), reads the token
ledger for the CURRENT session from Hermes's state.db (session_model_usage,
lineage-aware), and recomputes cost from raw tokens x live rates.
"""
