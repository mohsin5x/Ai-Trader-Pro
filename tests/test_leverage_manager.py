"""
tests/test_leverage_manager.py
================================
Leverage manager and position sizing tests.
"""

import pytest
from services import leverage_manager as lm


class TestAssetClassDetection:
    def test_forex_majors(self):
        for sym in ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]:
            assert lm.get_asset_class(sym) == "forex_major", f"Failed for {sym}"

    def test_forex_crosses(self):
        for sym in ["EUR/GBP", "GBP/JPY", "AUD/JPY"]:
            assert lm.get_asset_class(sym) == "forex_cross", f"Failed for {sym}"

    def test_metals(self):
        assert lm.get_asset_class("XAU/USD") == "gold"
        assert lm.get_asset_class("XAG/USD") == "silver"

    def test_crypto(self):
        for sym in ["BTC", "ETH", "SOL", "BTC/USD", "BTCUSDT"]:
            assert lm.get_asset_class(sym) == "crypto", f"Failed for {sym}"

    def test_indices(self):
        for sym in ["US30", "NAS100", "SPX500"]:
            assert lm.get_asset_class(sym) == "indices", f"Failed for {sym}"


class TestLeverageRetrieval:
    def test_forex_major_leverage(self):
        assert lm.get_leverage("EUR/USD") == 100

    def test_crypto_leverage(self):
        assert lm.get_leverage("BTC") == 2

    def test_default_leverage_fallback(self):
        lev = lm.get_leverage("UNKNOWN_SYMBOL_XYZ")
        assert lev == lm._LEVERAGE_MAP["default"]


class TestPositionSizing:
    def test_forex_position_size(self):
        result = lm.compute_position(
            "EUR/USD", account_balance=10_000.0,
            risk_pct=0.01, entry_price=1.0850, stop_loss=1.0800,
        )
        assert result["units"] > 0
        assert result["lots"] > 0
        assert "LOTS" in result["size_label"]
        assert result["leverage"] == 100
        assert result["risk_cash"] == pytest.approx(100.0, rel=1e-4)

    def test_crypto_position_size(self):
        result = lm.compute_position(
            "BTC", account_balance=10_000.0,
            risk_pct=0.01, entry_price=50_000.0, stop_loss=49_000.0,
        )
        assert result["units"] > 0
        assert result["risk_cash"] == pytest.approx(100.0, rel=1e-4)

    def test_zero_risk_returns_empty(self):
        result = lm.compute_position(
            "EUR/USD", account_balance=0.0,
            risk_pct=0.01, entry_price=1.0850, stop_loss=1.0800,
        )
        assert result["units"] == 0.0

    def test_tight_sl_at_entry(self):
        """Stop loss equal to entry should return zero units safely."""
        result = lm.compute_position(
            "EUR/USD", account_balance=10_000.0,
            risk_pct=0.01, entry_price=1.0850, stop_loss=1.0850,
        )
        assert result["units"] == 0.0

    def test_gold_position_returns_oz(self):
        result = lm.compute_position(
            "XAU/USD", account_balance=10_000.0,
            risk_pct=0.01, entry_price=1900.0, stop_loss=1880.0,
        )
        assert "oz" in result["size_label"]
        assert result["leverage"] == 50


class TestPnLCalculation:
    def test_buy_profit(self):
        pnl = lm.compute_pnl("EUR/USD", "BUY", 1.0850, 1.0900, 10_000.0)
        assert pnl == pytest.approx(50.0, rel=1e-4)

    def test_buy_loss(self):
        pnl = lm.compute_pnl("EUR/USD", "BUY", 1.0850, 1.0800, 10_000.0)
        assert pnl == pytest.approx(-50.0, rel=1e-4)

    def test_sell_profit(self):
        pnl = lm.compute_pnl("EUR/USD", "SELL", 1.0850, 1.0800, 10_000.0)
        assert pnl == pytest.approx(50.0, rel=1e-4)

    def test_sell_loss(self):
        pnl = lm.compute_pnl("EUR/USD", "SELL", 1.0850, 1.0900, 10_000.0)
        assert pnl == pytest.approx(-50.0, rel=1e-4)

    def test_crypto_pnl(self):
        pnl = lm.compute_pnl("BTC", "BUY", 50_000.0, 51_000.0, 0.1)
        assert pnl == pytest.approx(100.0, rel=1e-4)


class TestLeveragePersistence:
    def test_get_all_leverages_returns_dict(self):
        leverages = lm.get_all_leverages()
        assert isinstance(leverages, dict)
        assert "forex_major" in leverages
        assert "crypto" in leverages

    def test_save_and_reload_override(self, tmp_path, monkeypatch):
        """Override saved to file and reloaded correctly."""
        import json
        override_path = str(tmp_path / "leverage_overrides.json")

        # Patch the path function
        monkeypatch.setattr(
            "services.leverage_manager._get_override_path",
            lambda: override_path,
        )
        original = lm._LEVERAGE_MAP.get("crypto", 2)
        try:
            ok = lm.save_leverage_override("crypto", 5)
            assert ok
            assert lm._LEVERAGE_MAP["crypto"] == 5
            # Verify it was written to disk
            with open(override_path) as f:
                saved = json.load(f)
            assert saved["crypto"] == 5
        finally:
            # Restore original
            lm._LEVERAGE_MAP["crypto"] = original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
