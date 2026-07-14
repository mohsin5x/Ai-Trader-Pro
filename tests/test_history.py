"""
tests/test_history.py
======================
Trade journal (history_service) tests — thread safety, file locking, accuracy.
"""

import os
import tempfile
import threading
import pytest
from services import history_service


@pytest.fixture(autouse=True)
def isolated_journal(tmp_path, monkeypatch):
    """Each test gets its own isolated journal file."""
    journal_path = str(tmp_path / "trade_journal.csv")
    monkeypatch.setattr(history_service, "FILE_NAME", journal_path)
    yield journal_path


class TestLogAndLoad:
    def test_log_and_load_single_trade(self):
        history_service.log_trade({
            "asset": "EUR/USD", "side": "BUY", "strategy": "ICT Smart Money",
            "entry": 1.0865, "exit": 1.0910, "size": "1.00 LOTS", "pnl": 450.0,
        })
        trades = history_service.load_trades(limit=10)
        assert len(trades) == 1
        assert trades[0]["asset"] == "EUR/USD"
        assert trades[0]["result"] == "WIN"

    def test_log_loss_trade(self):
        history_service.log_trade({
            "asset": "GBP/USD", "side": "BUY", "strategy": "Order Blocks",
            "entry": 1.2742, "exit": 1.2700, "size": "0.50 LOTS", "pnl": -210.0,
        })
        trades = history_service.load_trades()
        assert trades[0]["result"] == "LOSS"

    def test_breakeven_trade(self):
        history_service.log_trade({"asset": "BTC", "side": "BUY", "pnl": 0.0})
        trades = history_service.load_trades()
        assert trades[0]["result"] == "BREAKEVEN"

    def test_newest_first_ordering(self):
        history_service.log_trade({"asset": "EUR/USD", "pnl": 100.0})
        history_service.log_trade({"asset": "GBP/USD", "pnl": -50.0})
        trades = history_service.load_trades(limit=10)
        assert trades[0]["asset"] == "GBP/USD"   # most recent first
        assert trades[1]["asset"] == "EUR/USD"

    def test_limit_respected(self):
        for i in range(5):
            history_service.log_trade({"asset": f"ASSET{i}", "pnl": float(i)})
        trades = history_service.load_trades(limit=3)
        assert len(trades) == 3

    def test_load_from_missing_file(self):
        # No trades logged — file doesn't exist
        trades = history_service.load_trades()
        assert trades == []

    def test_summary_with_no_trades(self):
        summary = history_service.get_summary()
        assert summary == {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "net_pnl": 0.0}


class TestSummaryCalculations:
    def test_summary_accuracy(self):
        history_service.log_trade({"asset": "A", "pnl": 450.0})
        history_service.log_trade({"asset": "B", "pnl": -210.0})
        summary = history_service.get_summary()
        assert summary["total"] == 2
        assert summary["wins"] == 1
        assert summary["losses"] == 1
        assert abs(summary["win_rate"] - 50.0) < 0.01
        assert abs(summary["net_pnl"] - 240.0) < 0.01

    def test_all_wins(self):
        for p in [100.0, 200.0, 50.0]:
            history_service.log_trade({"asset": "X", "pnl": p})
        summary = history_service.get_summary()
        assert summary["wins"] == 3
        assert summary["losses"] == 0
        assert abs(summary["win_rate"] - 100.0) < 0.01
        assert abs(summary["net_pnl"] - 350.0) < 0.01


class TestThreadSafety:
    def test_concurrent_writes(self):
        """50 threads write simultaneously — no corruption, all 50 trades readable."""
        errors = []

        def writer(i):
            try:
                history_service.log_trade({
                    "asset": f"ASSET{i}", "pnl": float(i), "side": "BUY",
                })
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent write errors: {errors}"
        trades = history_service.load_trades(limit=100)
        assert len(trades) == 50, f"Expected 50 trades, got {len(trades)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
