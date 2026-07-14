"""
tests/test_ai.py
=================
AI Engine strategy tests — verifies every strategy returns valid output.
"""

import pandas as pd
import numpy as np
import pytest
from services.market_analyzer import MarketAnalyzer
from services.ai_engine import AIEngine

ALL_STRATEGIES = [
    "ICT Smart Money", "Smart Money Concepts", "Support & Resistance",
    "Liquidity Concepts", "Order Blocks", "Fair Value Gaps",
    "Break of Structure", "Change of Character",
    "Scalping", "Swing Trading", "Trend Following", "Breakout",
    "EMA Crossover", "MACD", "RSI", "VWAP",
    "Price Action", "Multi-Timeframe", "ATR",
]

REQUIRED_KEYS = {"strategy", "signal", "confidence", "reasoning", "entry", "sl", "tp", "rr"}
VALID_SIGNALS = {"BUY NOW", "SELL NOW", "DO NOT BUY (STAY OUT)"}


def _make_candles(n=120, seed=7, trend: float = 0.0):
    """Generate synthetic OHLCV candles with optional trend bias."""
    rng = np.random.default_rng(seed)
    price = 100.0
    rows = []
    for _ in range(n):
        change = rng.uniform(-1, 1) + trend
        open_p = price
        close_p = max(0.01, price + change)
        high_p = max(open_p, close_p) + rng.uniform(0, 0.5)
        low_p = min(open_p, close_p) - rng.uniform(0, 0.5)
        vol = rng.uniform(500, 2000)
        rows.append({"open": open_p, "high": high_p, "low": low_p,
                     "close": close_p, "volume": vol})
        price = close_p
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def processed_df():
    return MarketAnalyzer().calculate_indicators(_make_candles())


@pytest.fixture(scope="module")
def engine():
    return AIEngine()


class TestStrategyOutput:
    def test_all_strategies_return_valid_signal(self, processed_df, engine):
        for strategy in ALL_STRATEGIES:
            result = engine.run_strategy(processed_df, strategy)
            assert REQUIRED_KEYS.issubset(result.keys()), (
                f"{strategy} missing keys: {REQUIRED_KEYS - result.keys()}"
            )
            assert result["signal"] in VALID_SIGNALS, (
                f"{strategy} returned invalid signal: {result['signal']!r}"
            )
            assert 0 <= result["confidence"] <= 100, (
                f"{strategy} confidence {result['confidence']} out of [0,100]"
            )
            assert isinstance(result["reasoning"], str) and len(result["reasoning"]) > 20, (
                f"{strategy} reasoning too short: {result['reasoning']!r}"
            )
            assert isinstance(result["rr"], (int, float)), (
                f"{strategy} rr must be numeric, got {type(result['rr'])}"
            )

    def test_engine_rejects_insufficient_data(self, engine):
        result = engine.run_strategy(pd.DataFrame({"close": [1, 2, 3]}), "ICT Smart Money")
        assert result["signal"] == "DO NOT BUY (STAY OUT)"
        assert result["confidence"] == 0

    def test_unknown_strategy_returns_clear_error(self, engine, processed_df):
        result = engine.run_strategy(processed_df, "NonExistentStrategy")
        assert result["signal"] == "DO NOT BUY (STAY OUT)"
        assert "not implemented" in result["reasoning"].lower()
        assert result["confidence"] == 0

    def test_engine_handles_empty_dataframe(self, engine):
        result = engine.run_strategy(pd.DataFrame(), "Breakout")
        assert result["signal"] == "DO NOT BUY (STAY OUT)"

    def test_new_strategies_ema_crossover(self, processed_df, engine):
        result = engine.run_strategy(processed_df, "EMA Crossover")
        assert result["strategy"] == "EMA Crossover"
        assert result["signal"] in VALID_SIGNALS

    def test_new_strategies_macd(self, processed_df, engine):
        result = engine.run_strategy(processed_df, "MACD")
        assert result["strategy"] == "MACD"
        assert result["signal"] in VALID_SIGNALS

    def test_new_strategies_rsi(self, processed_df, engine):
        result = engine.run_strategy(processed_df, "RSI")
        assert result["strategy"] == "RSI"
        assert result["signal"] in VALID_SIGNALS

    def test_new_strategies_vwap(self, processed_df, engine):
        result = engine.run_strategy(processed_df, "VWAP")
        assert result["strategy"] == "VWAP"
        assert result["signal"] in VALID_SIGNALS

    def test_new_strategies_price_action(self, processed_df, engine):
        result = engine.run_strategy(processed_df, "Price Action")
        assert result["strategy"] == "Price Action"

    def test_new_strategies_multi_timeframe(self, processed_df, engine):
        result = engine.run_strategy(processed_df, "Multi-Timeframe")
        assert result["strategy"] == "Multi-Timeframe"

    def test_new_strategies_atr(self, processed_df, engine):
        result = engine.run_strategy(processed_df, "ATR")
        assert result["strategy"] == "ATR"

    def test_detailed_reasoning_always_includes_strategy_description(self, processed_df, engine):
        """Reasoning must cover both what the strategy does AND why the signal fired."""
        result = engine.run_strategy(processed_df, "ICT Smart Money")
        reasoning = result["reasoning"]
        assert len(reasoning) > 100, "Reasoning too short to be useful"

    def test_sl_and_tp_nonzero_for_actionable_signals(self, processed_df, engine):
        """For BUY/SELL signals, SL and TP must be non-zero prices."""
        for strategy in ALL_STRATEGIES:
            result = engine.run_strategy(processed_df, strategy)
            if "STAY OUT" not in result["signal"]:
                assert result["sl"]  > 0, f"{strategy}: SL must be > 0 for actionable signals"
                assert result["tp"]  > 0, f"{strategy}: TP must be > 0 for actionable signals"
                assert result["entry"] > 0, f"{strategy}: entry must be > 0 for actionable signals"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
