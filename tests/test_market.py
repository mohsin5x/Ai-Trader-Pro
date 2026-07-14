"""
tests/test_market.py
=====================
MarketAnalyzer indicator calculation tests.
"""

import pandas as pd
import numpy as np
import pytest
from services.market_analyzer import MarketAnalyzer


def _make_candles(n=200, seed=1, with_timestamps=False):
    rng = np.random.default_rng(seed)
    price = 100.0
    rows = []
    base_ts = 1700000000  # Unix timestamp base
    for i in range(n):
        change = rng.uniform(-1, 1)
        open_p = price
        close_p = max(0.01, price + change)
        high_p = max(open_p, close_p) + rng.uniform(0, 0.5)
        low_p = min(open_p, close_p) - rng.uniform(0, 0.5)
        vol = rng.uniform(100, 1000)
        row = {"open": open_p, "high": high_p, "low": low_p,
               "close": close_p, "volume": vol}
        if with_timestamps:
            row["timestamp"] = base_ts + i * 900  # 15m candles
        rows.append(row)
        price = close_p
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def analyzer():
    return MarketAnalyzer()


@pytest.fixture(scope="module")
def df_standard(analyzer):
    return analyzer.calculate_indicators(_make_candles())


@pytest.fixture(scope="module")
def df_with_ts(analyzer):
    return analyzer.calculate_indicators(_make_candles(with_timestamps=True))


class TestIndicatorColumns:
    EXPECTED_COLS = {
        "EMA20", "EMA50", "SMA200",
        "RSI",
        "MACD", "MACD_Signal", "MACD_Hist",
        "BB_Upper", "BB_Middle", "BB_Lower",
        "ATR",
        "ADX", "PLUS_DI", "MINUS_DI",
        "VWAP",
        "MOMENTUM", "VOLUME_MA20",
        "STOCH_K", "STOCH_D",
    }

    def test_all_indicator_columns_present(self, df_standard):
        missing = self.EXPECTED_COLS - set(df_standard.columns)
        assert not missing, f"Missing indicator columns: {missing}"

    def test_no_nans_in_usable_range(self, df_standard):
        """After ffill/bfill, no NaN should remain in the indicator columns."""
        for col in self.EXPECTED_COLS:
            assert not df_standard[col].isna().any(), f"NaN found in column {col}"

    def test_rsi_bounded(self, df_standard):
        assert (df_standard["RSI"] >= 0).all()
        assert (df_standard["RSI"] <= 100).all()

    def test_atr_positive(self, df_standard):
        assert (df_standard["ATR"] > 0).all(), "ATR must be positive"

    def test_bb_ordering(self, df_standard):
        assert (df_standard["BB_Upper"] >= df_standard["BB_Middle"]).all()
        assert (df_standard["BB_Middle"] >= df_standard["BB_Lower"]).all()

    def test_adx_non_negative(self, df_standard):
        assert (df_standard["ADX"] >= 0).all()

    def test_stoch_bounded(self, df_standard):
        assert (df_standard["STOCH_K"] >= 0).all()
        assert (df_standard["STOCH_K"] <= 100).all()

    def test_vwap_with_timestamps(self, df_with_ts):
        """VWAP with session-reset timestamps should be valid and not cumulative trend."""
        vwap = df_with_ts["VWAP"]
        assert not vwap.isna().any()
        assert (vwap > 0).all()

    def test_handles_empty_frame(self, analyzer):
        result = analyzer.calculate_indicators(pd.DataFrame())
        assert result.empty

    def test_handles_single_row(self, analyzer):
        df = pd.DataFrame([{"open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}])
        result = analyzer.calculate_indicators(df)
        assert not result.empty
        assert "RSI" in result.columns

    def test_original_columns_preserved(self, df_standard):
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in df_standard.columns

    def test_ema20_faster_than_ema50(self, df_standard):
        """EMA20 should react faster — higher variance than EMA50."""
        assert df_standard["EMA20"].std() >= df_standard["EMA50"].std() * 0.9


class TestEdgeCases:
    def test_zero_volume(self, analyzer):
        df = _make_candles(50)
        df["volume"] = 0
        result = analyzer.calculate_indicators(df)
        assert not result["VWAP"].isna().any(), "VWAP must not be NaN on zero volume"

    def test_flat_price(self, analyzer):
        """Flat price (constant close) should not cause division-by-zero."""
        df = pd.DataFrame([
            {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 100}
            for _ in range(50)
        ])
        result = analyzer.calculate_indicators(df)
        assert not result.empty
        assert (result["ATR"] >= 0).all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
