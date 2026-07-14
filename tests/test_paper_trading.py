"""
tests/test_paper_trading.py
============================
Paper trading database and engine tests.
"""

import os
import time
import threading
import tempfile
import pytest
import sys

# Redirect DB_PATH to a temp location before any import
_tmp = tempfile.mkdtemp()
_test_db = os.path.join(_tmp, "test_paper_trading.db")

# Patch the DB_PATH before importing the module
import importlib
import services.paper_trading_db as db_module


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a fresh DB for every test."""
    test_db = str(tmp_path / "test_pt.db")
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db(default_starting_balance=10_000.0)
    yield test_db


class TestAccountOperations:
    def test_init_creates_account_with_balance(self):
        account = db_module.get_account()
        assert account["balance"] == 10_000.0
        assert account["starting_balance"] == 10_000.0

    def test_apply_balance_delta_positive(self):
        new_bal = db_module.apply_balance_delta(500.0, "TRADE_PNL", "test win")
        assert abs(new_bal - 10_500.0) < 0.01
        account = db_module.get_account()
        assert abs(account["balance"] - 10_500.0) < 0.01

    def test_apply_balance_delta_negative(self):
        new_bal = db_module.apply_balance_delta(-300.0, "TRADE_PNL", "test loss")
        assert abs(new_bal - 9_700.0) < 0.01

    def test_reset_account(self):
        db_module.apply_balance_delta(5000.0, "TRADE_PNL")
        db_module.reset_account(20_000.0)
        account = db_module.get_account()
        assert abs(account["balance"] - 20_000.0) < 0.01
        assert abs(account["starting_balance"] - 20_000.0) < 0.01

    def test_reset_clears_trades(self):
        trade = {
            "symbol": "BTC", "timeframe": "15m", "signal_type": "BUY",
            "entry_price": 50000.0, "stop_loss": 49000.0, "take_profit": 52000.0,
            "size": 0.1, "size_label": "0.1 UNITS", "leverage": 2,
            "asset_class": "Crypto", "opened_at": time.time(),
            "confidence": 85, "strategy": "ICT Smart Money",
        }
        db_module.open_trade(trade)
        db_module.reset_account(10_000.0)
        assert db_module.get_open_trades() == []

    def test_get_transactions(self):
        db_module.apply_balance_delta(100.0, "DEPOSIT")
        db_module.apply_balance_delta(-50.0, "WITHDRAWAL")
        txns = db_module.get_transactions(limit=10)
        # reset transaction + 2 new ones
        assert len(txns) >= 2


class TestTradeOperations:
    def _sample_trade(self, symbol="EURUSD", direction="BUY"):
        return {
            "symbol": symbol, "timeframe": "15m", "signal_type": direction,
            "entry_price": 1.0850, "stop_loss": 1.0800, "take_profit": 1.0950,
            "size": 10000.0, "size_label": "0.10 LOTS", "leverage": 100,
            "asset_class": "Forex Major", "opened_at": time.time(),
            "confidence": 78, "strategy": "Smart Money Concepts",
        }

    def test_open_trade_returns_id(self):
        tid = db_module.open_trade(self._sample_trade())
        assert isinstance(tid, int) and tid > 0

    def test_get_open_trades(self):
        db_module.open_trade(self._sample_trade("EURUSD"))
        db_module.open_trade(self._sample_trade("GBPUSD"))
        trades = db_module.get_open_trades()
        assert len(trades) == 2
        assert all(t["status"] == "OPEN" for t in trades)

    def test_close_trade(self):
        opened_at = time.time()
        trade = self._sample_trade()
        trade["opened_at"] = opened_at
        tid = db_module.open_trade(trade)
        closed_at = time.time()
        db_module.close_trade(
            tid, exit_price=1.0950, closed_at=closed_at,
            pnl=100.0, pnl_pct=0.92, result="WIN",
            exit_reason="TAKE_PROFIT", opened_at=opened_at,
        )
        trades = db_module.get_trades(status="CLOSED")
        assert len(trades) == 1
        assert trades[0]["result"] == "WIN"
        assert trades[0]["exit_reason"] == "TAKE_PROFIT"

    def test_get_trades_filters(self):
        db_module.open_trade(self._sample_trade("EURUSD", "BUY"))
        db_module.open_trade(self._sample_trade("GBPUSD", "SELL"))
        buy_trades = db_module.get_trades(symbol="EURUSD")
        assert len(buy_trades) == 1
        assert buy_trades[0]["symbol"] == "EURUSD"

    def test_get_distinct_symbols(self):
        db_module.open_trade(self._sample_trade("EURUSD"))
        db_module.open_trade(self._sample_trade("GBPUSD"))
        symbols = db_module.get_distinct_symbols()
        assert "EURUSD" in symbols
        assert "GBPUSD" in symbols

    def test_export_csv(self, tmp_path):
        db_module.open_trade(self._sample_trade())
        trades = db_module.get_trades()
        csv_path = str(tmp_path / "export.csv")
        db_module.export_csv(csv_path, trades)
        assert os.path.isfile(csv_path)
        assert os.path.getsize(csv_path) > 0


class TestSQLIdentifierValidation:
    def test_valid_identifier(self):
        from services.paper_trading_db import _validate_sql_id
        assert _validate_sql_id("trades") == "trades"
        assert _validate_sql_id("signal_id") == "signal_id"

    def test_invalid_identifier_raises(self):
        from services.paper_trading_db import _validate_sql_id
        with pytest.raises(ValueError):
            _validate_sql_id("trades; DROP TABLE trades--")
        with pytest.raises(ValueError):
            _validate_sql_id("")

    def test_safe_sql_type_allowlist(self):
        from services.paper_trading_db import _safe_sql_type
        assert _safe_sql_type("TEXT") == "TEXT"
        assert _safe_sql_type("INTEGER DEFAULT 1") == "INTEGER DEFAULT 1"

    def test_sql_injection_blocked(self):
        from services.paper_trading_db import _validate_sql_id
        with pytest.raises(ValueError):
            _validate_sql_id("id; DROP TABLE trades")


class TestConcurrentAccess:
    def test_concurrent_open_trades(self):
        """Many threads can open trades concurrently without corruption."""
        errors = []

        def open_one(i):
            try:
                t = {
                    "symbol": f"SYM{i}", "timeframe": "1m", "signal_type": "BUY",
                    "entry_price": float(i), "stop_loss": float(i) - 1,
                    "take_profit": float(i) + 2, "size": 1.0,
                    "size_label": "1.0 UNITS", "leverage": 1,
                    "asset_class": "Crypto", "opened_at": time.time(),
                }
                db_module.open_trade(t)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=open_one, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        trades = db_module.get_open_trades()
        assert len(trades) == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
