"""
tests/test_signal_storage.py
=============================
Signal storage database tests — CRUD, filtering, thread safety.
"""

import time
import threading
import pytest

import services.signal_storage as ss


class _FakeSignal:
    def __init__(self, symbol="EURUSD", direction="BUY", entry=1.085, confidence=80):
        self.symbol         = symbol
        self.direction      = direction
        self.entry_price    = entry
        self.stop_loss      = entry - 0.005
        self.take_profit_1  = entry + 0.010
        self.take_profit_2  = entry + 0.020
        self.take_profit_3  = entry + 0.030
        self.confidence     = confidence
        self.strength       = "Strong"
        self.trend          = "Bullish"
        self.trade_type     = "Intraday"
        self.setup_timeframe = "15M"
        self.data_source    = "TestProvider"
        self.session        = "London session"
        self.reasons        = ["EMA aligned", "VWAP support"]
        self.created_at     = time.time()


@pytest.fixture(autouse=True)
def isolated_signals_db(tmp_path, monkeypatch):
    """Each test gets its own signal DB."""
    test_db = str(tmp_path / "signals.db")
    monkeypatch.setattr(ss, "DB_PATH", test_db)
    ss.init_db()
    yield test_db


class TestUpsertSignal:
    def test_insert_new_signal(self):
        sig = _FakeSignal()
        sid, is_new = ss.upsert_signal(sig)
        assert sid > 0
        assert is_new is True

    def test_refresh_existing_signal(self):
        sig = _FakeSignal()
        sid1, _ = ss.upsert_signal(sig)
        # Same symbol/direction/entry → refresh existing row
        sid2, is_new = ss.upsert_signal(sig)
        assert sid1 == sid2
        assert is_new is False

    def test_distinct_entry_creates_new_row(self):
        sig1 = _FakeSignal(entry=1.085)
        sig2 = _FakeSignal(entry=1.090)  # >0.05% different
        sid1, new1 = ss.upsert_signal(sig1)
        sid2, new2 = ss.upsert_signal(sig2)
        assert sid1 != sid2
        assert new1 is True and new2 is True


class TestSignalLifecycle:
    def test_mark_triggered(self):
        sig = _FakeSignal()
        sid, _ = ss.upsert_signal(sig)
        ss.mark_triggered(sid, paper_trade_id=42)
        signals = ss.get_signals(status="TRIGGERED")
        assert len(signals) == 1
        assert signals[0]["paper_trade_id"] == 42

    def test_close_signal(self):
        sig = _FakeSignal()
        sid, _ = ss.upsert_signal(sig)
        ss.close_signal(sid, exit_price=1.095, result="WIN")
        signals = ss.get_signals(status="CLOSED")
        assert len(signals) == 1
        assert signals[0]["result"] == "WIN"

    def test_cancel_signal(self):
        sig = _FakeSignal()
        sid, _ = ss.upsert_signal(sig)
        ss.cancel_signal(sid, "Test cancel")
        signals = ss.get_signals(status="CANCELLED")
        assert len(signals) == 1

    def test_expire_old_signals(self):
        sig = _FakeSignal()
        sig.created_at = time.time() - ss.SIGNAL_TTL_SECONDS - 1
        sid, _ = ss.upsert_signal(sig)
        ss.expire_old_signals()
        signals = ss.get_signals(status="EXPIRED")
        assert len(signals) == 1


class TestSignalFilters:
    def test_filter_by_symbol(self):
        ss.upsert_signal(_FakeSignal("EURUSD"))
        ss.upsert_signal(_FakeSignal("GBPUSD"))
        results = ss.get_signals(symbol="EURUSD")
        assert all(r["symbol"] == "EURUSD" for r in results)

    def test_filter_by_direction(self):
        ss.upsert_signal(_FakeSignal(direction="BUY"))
        ss.upsert_signal(_FakeSignal("GBPUSD", direction="SELL"))
        results = ss.get_signals(direction="BUY")
        assert all(r["direction"] == "BUY" for r in results)

    def test_filter_by_min_confidence(self):
        ss.upsert_signal(_FakeSignal(confidence=60))
        ss.upsert_signal(_FakeSignal("GBPUSD", confidence=90))
        results = ss.get_signals(min_confidence=80)
        assert all(r["confidence"] >= 80 for r in results)

    def test_get_active_signals(self):
        ss.upsert_signal(_FakeSignal())
        active = ss.get_active_signals()
        assert len(active) == 1

    def test_get_performance_stats(self):
        sig = _FakeSignal()
        sid, _ = ss.upsert_signal(sig)
        ss.close_signal(sid, 1.095, "WIN")
        stats = ss.get_performance_stats()
        assert stats["total"] >= 1
        assert stats["wins"] >= 1


class TestSQLInjectionPrevention:
    def test_validate_identifier_rejects_injection(self):
        from services.signal_storage import _validate_identifier
        with pytest.raises(ValueError):
            _validate_identifier("signals; DROP TABLE signals--")

    def test_validate_identifier_accepts_valid(self):
        from services.signal_storage import _validate_identifier
        assert _validate_identifier("signals") == "signals"
        assert _validate_identifier("take_profit_1") == "take_profit_1"


class TestThreadSafety:
    def test_concurrent_upserts(self):
        errors = []

        def worker(i):
            try:
                sig = _FakeSignal(
                    symbol=f"SYM{i}", entry=float(i),
                    confidence=50 + (i % 50),
                )
                ss.upsert_signal(sig)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        all_sigs = ss.get_signals(limit=100)
        assert len(all_sigs) == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
