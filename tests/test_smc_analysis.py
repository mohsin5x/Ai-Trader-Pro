"""
tests/test_smc_analysis.py
===========================
Smart Money Concepts analysis tests.
"""

import numpy as np
import pandas as pd
import pytest
from services.smc_analysis import analyze_smc
from services.market_analyzer import MarketAnalyzer


def _make_trending_candles(n=100, direction="up", seed=42):
    """Generate candles with a clear directional trend."""
    rng = np.random.default_rng(seed)
    price = 1000.0
    rows = []
    trend = 0.5 if direction == "up" else -0.5
    for _ in range(n):
        change = rng.uniform(-0.3, 0.7) + trend
        open_p = price
        close_p = max(0.01, price + change)
        high_p = max(open_p, close_p) + rng.uniform(0, 0.2)
        low_p = min(open_p, close_p) - rng.uniform(0, 0.2)
        rows.append({"open": open_p, "high": high_p, "low": low_p,
                     "close": close_p, "volume": rng.uniform(100, 500)})
        price = close_p
    return MarketAnalyzer().calculate_indicators(pd.DataFrame(rows))


class TestAnalyzeSMC:
    def test_returns_dict_with_required_keys(self):
        df = _make_trending_candles()
        result = analyze_smc(df)
        required = {"valid", "trend_bias", "bos", "choch", "liquidity_sweep",
                    "order_block", "fvg", "zone", "notes"}
        assert required.issubset(result.keys())

    def test_valid_on_sufficient_data(self):
        df = _make_trending_candles(100)
        result = analyze_smc(df)
        assert result["valid"] is True

    def test_invalid_on_insufficient_data(self):
        df = pd.DataFrame([
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
            for _ in range(5)
        ])
        result = analyze_smc(df)
        assert result["valid"] is False

    def test_bullish_trend_bias(self):
        df = _make_trending_candles(100, direction="up")
        result = analyze_smc(df)
        # Strong up trend should show bullish EMA bias
        assert result["trend_bias"] in ("bullish", "neutral")

    def test_bearish_trend_bias(self):
        df = _make_trending_candles(100, direction="down")
        result = analyze_smc(df)
        assert result["trend_bias"] in ("bearish", "neutral")

    def test_zone_classification(self):
        df = _make_trending_candles()
        result = analyze_smc(df)
        assert result["zone"] in ("premium", "discount", "equilibrium")

    def test_notes_is_list(self):
        df = _make_trending_candles()
        result = analyze_smc(df)
        assert isinstance(result["notes"], list)

    def test_handles_empty_dataframe(self):
        result = analyze_smc(pd.DataFrame())
        assert result["valid"] is False

    def test_handles_none(self):
        result = analyze_smc(None)
        assert result["valid"] is False

    def test_bos_or_choch_is_string_or_none(self):
        df = _make_trending_candles()
        result = analyze_smc(df)
        assert result["bos"] in (None, "bullish", "bearish")
        assert result["choch"] in (None, "bullish", "bearish")

    def test_liquidity_sweep_valid_values(self):
        df = _make_trending_candles()
        result = analyze_smc(df)
        assert result["liquidity_sweep"] in (None, "bullish", "bearish")

    def test_order_block_valid_values(self):
        df = _make_trending_candles()
        result = analyze_smc(df)
        assert result["order_block"] in (None, "bullish", "bearish")

    def test_fvg_valid_values(self):
        df = _make_trending_candles()
        result = analyze_smc(df)
        assert result["fvg"] in (None, "bullish", "bearish")


class TestSMCEdgeCases:
    def test_flat_price_does_not_crash(self):
        df = pd.DataFrame([
            {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 100}
            for _ in range(60)
        ])
        df = MarketAnalyzer().calculate_indicators(df)
        result = analyze_smc(df)
        assert isinstance(result, dict)

    def test_zero_volume_does_not_crash(self):
        df = _make_trending_candles()
        df["volume"] = 0
        result = analyze_smc(df)
        assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
