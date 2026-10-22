"""Unit tests for butatwhatcost. Run: python -m pytest test_butatwhatcost.py -q"""

from butatwhatcost import cost_for, model_cost


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
