"""Unit tests for butatwhatcost. Run: python -m pytest test_butatwhatcost.py -q"""

import sqlite3

from butatwhatcost import (cost_for, model_cost, lineage_ids, session_usage,
                           parse_pricing, account_total, build_report, session_exists)


def test_cost_for_per_million():
    assert cost_for(1_000_000, 0.06) == 0.06
    assert cost_for(500_000, 0.18) == 0.09
    assert cost_for(0, 0.06) == 0.0
    assert cost_for(12345, 0.0) == 0.0


def test_model_cost_mixes_all_token_types():
    price = {"input_tokens": 0.06, "output_tokens": 0.18, "cache_read_tokens": 0.015}
    tokens = {"input_tokens": 1_000_000, "output_tokens": 500_000,
              "cache_read_tokens": 2_000_000, "cache_write_tokens": 1_000_000,
              "reasoning_tokens": 100_000}
    # 0.06 + 0.09 + 0.03 + (cache_write at input rate: 0.06) + (reasoning at output rate: 0.018)
    assert abs(model_cost(tokens, price) - (0.06 + 0.09 + 0.03 + 0.06 + 0.018)) < 1e-9


def _make_db(tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)")
    con.execute("""CREATE TABLE session_model_usage (
        session_id TEXT, model TEXT, task TEXT, api_call_count INTEGER,
        input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
        cache_write_tokens INTEGER, reasoning_tokens INTEGER,
        estimated_cost_usd REAL)""")
    # root <- child (compression) <- grandchild (current)
    con.executemany("INSERT INTO sessions VALUES (?,?)", [
        ("root", None), ("child", "root"), ("gcur", "child")])
    con.executemany("INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("root",  "deepseek-ai/DeepSeek-V4-Flash-0731", "",  1, 100, 10, 200, 0, 0, 0.001),
        ("child", "deepseek-ai/DeepSeek-V4-Flash-0731", "",  1, 200, 20, 400, 0, 0, 0.002),
        ("gcur",  "deepseek-ai/DeepSeek-V4-Flash-0731", "",  1, 300, 30, 600, 0, 0, 0.003),
        ("gcur",  "deepseek-ai/DeepSeek-V4-Flash-0731", "approval", 1, 5, 1, 0, 0, 0, 0.0)])
    con.commit()
    return con


def test_lineage_walks_to_root(tmp_path):
    con = _make_db(tmp_path)
    assert lineage_ids(con, "gcur") == ["gcur", "child", "root"]
    assert lineage_ids(con, "root") == ["root"]


def test_session_usage_covers_lineage_and_tasks(tmp_path):
    con = _make_db(tmp_path)
    rows = session_usage(con, lineage_ids(con, "gcur"))
    # SELECT order: model=0, task=1, api_call_count=2, input_tokens=3,
    # output_tokens=4, cache_read_tokens=5, cache_write_tokens=6, reasoning=7, estimated=8
    assert sum(r[3] for r in rows) == 605       # input_tokens: 100+200+300+5(approval row)
    assert sum(r[5] for r in rows) == 1200      # cache_read: 200+400+600
    assert len([r for r in rows if r[1] == "approval"]) == 1


def test_parse_pricing_handles_missing_and_null():
    payload = {"data": [
        {"id": "a/b", "metadata": {"pricing": {"input_tokens": 0.06,
          "output_tokens": 0.18, "cache_read_tokens": 0.015}, "discount": None}},
        {"id": "c/d", "metadata": {"pricing": None}}]}
    p = parse_pricing(payload)
    assert p["a/b"]["input_tokens"] == 0.06
    assert p["c/d"] == {}          # no crash; cost falls back to estimate


def test_session_exists(tmp_path):
    con = _make_db(tmp_path)
    assert session_exists(con, "gcur")
    assert session_exists(con, "root")
    assert not session_exists(con, "nope")   # phantom/stale id must be caught


def test_account_total_recomputes_from_raw():
    # DeepInfra's `cost` field is rounded to whole dollars (units*rate -> int);
    # we rebuild from raw units*rate so nothing is lost to rounding.
    months = [{"period": "2026.10", "items": [
        {"model_name": "x", "pricing_type": "input_tokens", "units": 1_000_000, "rate": 6e-05, "cost": 60},
        {"model_name": "x", "pricing_type": "output_tokens", "units": 500_000, "rate": 1.8e-04, "cost": 90}]}]
    assert abs(account_total(months) - 150.0) < 1e-6


def test_build_report_shape():
    price = {"deepseek-ai/DeepSeek-V4-Flash-0731": {"input_tokens": 0.06,
             "output_tokens": 0.18, "cache_read_tokens": 0.015, "discount": None}}
    rows = [("deepseek-ai/DeepSeek-V4-Flash-0731", "", 2, 1_000_000, 500_000,
             2_000_000, 0, 100_000, 0.03)]
    r = build_report(rows, price)
    assert r["models"]["deepseek-ai/DeepSeek-V4-Flash-0731"]["cost"] == 0.06 + 0.09 + 0.03 + 0.018
    assert r["totals"]["cost"] > 0
    assert r["totals"]["input_tokens"] == 1_000_000
    assert r["totals"]["api_calls"] == 2
