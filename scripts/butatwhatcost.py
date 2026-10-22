#!/usr/bin/env python3
"""butatwhatcost — DeepInfra live pricing + this Hermes session's cost.

Fetches live pricing from the DeepInfra backend (/v1/models), reads the token
ledger for the CURRENT session from Hermes's state.db (session_model_usage,
lineage-aware), and recomputes cost from raw tokens x live rates.
"""

import json
import os
import sqlite3
import sys
import urllib.request


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


def account_total(months: list) -> float:
    """Rebuild account cost from raw units*rate (DeepInfra's `cost` field is
    rounded). `months` = response['months'] from /payment/usage."""
    return sum(item.get("units", 0) * item.get("rate", 0.0)
               for month in months for item in month.get("items", []))


def build_report(rows: list, price: dict) -> dict:
    """Aggregate session_model_usage rows into a per-model + totals report.
    Cost is recomputed from raw tokens x live rates when the model has a price;
    otherwise the row's estimated_cost_usd is used and rate_missing is set."""
    models = {}
    totals = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0,
              "cache_read_tokens": 0, "cache_write_tokens": 0,
              "reasoning_tokens": 0, "cost": 0.0, "estimated": 0.0}
    for model, task, calls, inp, out, cr, cw, reas, est in rows:
        m = models.setdefault(model, {
            "tasks": {}, "api_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0, "reasoning_tokens": 0,
            "cost": 0.0, "rate_missing": False})
        t = m["tasks"].setdefault(task or "main", {"calls": 0, "input_tokens": 0,
                                                   "output_tokens": 0, "cache_read_tokens": 0})
        m["api_calls"] += calls
        m["input_tokens"] += inp
        m["output_tokens"] += out
        m["cache_read_tokens"] += cr
        m["cache_write_tokens"] += cw
        m["reasoning_tokens"] += reas
        t["calls"] += calls
        t["input_tokens"] += inp
        t["output_tokens"] += out
        t["cache_read_tokens"] += cr
        pr = price.get(model)
        if pr:
            m["cost"] += model_cost({"input_tokens": inp, "output_tokens": out,
                                     "cache_read_tokens": cr, "cache_write_tokens": cw,
                                     "reasoning_tokens": reas}, pr)
        else:
            m["rate_missing"] = True
            m["cost"] += est
        totals["api_calls"] += calls
        totals["input_tokens"] += inp
        totals["output_tokens"] += out
        totals["cache_read_tokens"] += cr
        totals["cache_write_tokens"] += cw
        totals["reasoning_tokens"] += reas
        totals["estimated"] += est
    totals["cost"] = sum(m["cost"] for m in models.values())
    return {"models": models, "totals": totals}


def fetch_json(url: str, headers=None, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def hermes_home():
    from pathlib import Path
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    return Path.home() / (".hermes" if os.name != "nt" else "AppData/Local/hermes")


def load_api_key(home) -> str:
    from pathlib import Path
    p = Path(home) / ".env"
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPINFRA_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"DEEPINFRA_API_KEY not found in {p}")


def render_human(report: dict, session_id: str, account_cost, pricing: dict) -> str:
    def counts(m):
        parts = [f"calls={m['api_calls']}", f"in={m['input_tokens']:,}",
                 f"out={m['output_tokens']:,}", f"cache={m['cache_read_tokens']:,}"]
        if m["reasoning_tokens"]:
            parts.append(f"reas={m['reasoning_tokens']:,}")
        if m["cache_write_tokens"]:
            parts.append(f"cacheW={m['cache_write_tokens']:,}")
        return " ".join(parts)

    lines = [f"butatwhatcost — session {session_id}"]
    for model, m in report["models"].items():
        lines.append(
            f"  {model}  {counts(m)}  cost=${m['cost']:.4f}"
            + ("  (rate unavailable; used Hermes estimate)" if m["rate_missing"] else ""))
        pr = pricing.get(model)
        if pr:
            lines.append(f"      live rates: in ${pr['input_tokens']}/M "
                         f"out ${pr['output_tokens']}/M cache_read ${pr['cache_read_tokens']}/M")
    t = report["totals"]
    lines.append(f"  TOTAL {counts(t)} cost=${t['cost']:.4f}")
    if account_cost is not None:
        lines.append(f"  DeepInfra account (month): ${account_cost:.2f}")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    import datetime

    ap = argparse.ArgumentParser(description="DeepInfra live pricing + current session cost")
    ap.add_argument("--session-id", default=os.environ.get("HERMES_SESSION_ID"),
                    help="session to cost (default: $HERMES_SESSION_ID)")
    ap.add_argument("--months", type=int, default=1, help="account usage months back")
    ap.add_argument("--no-account", action="store_true", help="skip /payment/usage cross-check")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    home = hermes_home()
    api_key = load_api_key(home)
    pricing = parse_pricing(fetch_json("https://api.deepinfra.com/v1/models"))

    if not args.session_id:
        print("no HERMES_SESSION_ID set and --session-id not given; cannot attribute", file=sys.stderr)
        return 2
    con = sqlite3.connect(str(home / "state.db"))
    rows = session_usage(con, lineage_ids(con, args.session_id))
    report = build_report(rows, pricing)
    con.close()

    account_cost = None
    if not args.no_account:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            resp = fetch_json(
                "https://api.deepinfra.com/payment/usage?from=%04d.%02d" % (now.year, now.month),
                headers={"Authorization": "Bearer " + api_key})
            account_cost = account_total(resp.get("months", []))
        except Exception as e:  # account cross-check is best-effort
            print(f"(account usage unavailable: {e})", file=sys.stderr)

    if args.json:
        print(json.dumps({"session_id": args.session_id, "report": report,
                          "pricing": pricing, "account_cost": account_cost}, indent=2))
    else:
        print(render_human(report, args.session_id, account_cost, pricing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
