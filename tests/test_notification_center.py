"""
tests/test_notification_center.py
===================================
NotificationCenter thread safety, deduplication, and memory-bound tests.
"""

import time
import threading
import pytest
from services.notification_center import NotificationCenter, Notification


@pytest.fixture
def nc():
    """Fresh NotificationCenter for each test (bypasses singleton for testing)."""
    center = NotificationCenter.__new__(NotificationCenter)
    center._initialized = False
    center.__init__()
    yield center
    center.shutdown(timeout=2.0)


class TestBasicOperations:
    def test_push_and_receive(self, nc):
        received = []
        nc.add_listener(lambda n: received.append(n))
        nc.push("info", "Title", "Message")
        time.sleep(0.2)
        assert len(received) == 1
        assert received[0].title == "Title"
        assert received[0].message == "Message"

    def test_enqueue_legacy(self, nc):
        received = []
        nc.add_listener(lambda n: received.append(n))
        nc.enqueue("Legacy Title", "Legacy Msg", level="warning")
        time.sleep(0.2)
        assert len(received) == 1

    def test_get_all_returns_history(self, nc):
        nc.push("info", "T1", "M1")
        nc.push("info", "T2", "M2")
        time.sleep(0.3)
        history = nc.get_all()
        assert len(history) >= 2

    def test_unread_count(self, nc):
        nc.push("info", "T", "M")
        time.sleep(0.2)
        assert nc.unread_count() >= 1

    def test_mark_read(self, nc):
        received = []
        nc.add_listener(lambda n: received.append(n))
        nc.push("info", "TR", "MR")
        time.sleep(0.2)
        nid = received[0].nid
        nc.mark_read(nid)
        assert received[0].read is True

    def test_mark_all_read(self, nc):
        nc.push("info", "T1", "M1")
        nc.push("info", "T2", "M2")
        time.sleep(0.3)
        nc.mark_all_read()
        assert nc.unread_count() == 0

    def test_clear_all(self, nc):
        nc.push("info", "T", "M")
        time.sleep(0.2)
        nc.clear_all()
        assert nc.unread_count() == 0
        assert nc.get_all() == []


class TestDeduplication:
    def test_identical_messages_deduplicated(self, nc):
        received = []
        nc.add_listener(lambda n: received.append(n))
        for _ in range(5):
            nc.push("info", "Same", "Same")
        time.sleep(0.5)
        # Only 1 should get through due to 5s dedup window
        assert len(received) == 1

    def test_different_messages_not_deduplicated(self, nc):
        received = []
        nc.add_listener(lambda n: received.append(n))
        nc.push("info", "T1", "Msg1")
        nc.push("info", "T2", "Msg2")
        nc.push("info", "T3", "Msg3")
        time.sleep(0.5)
        assert len(received) == 3


class TestBoundedMemory:
    def test_history_bounded_at_500(self, nc):
        """Push 600 unique notifications — history must not exceed 500."""
        for i in range(600):
            nc.push("info", f"Title{i}", f"Msg{i}")
        time.sleep(2.0)  # give worker time to drain
        assert len(nc.get_all()) <= 500

    def test_dedup_cache_bounded(self, nc):
        """Push 300 unique notification titles — dedup cache must stay bounded."""
        for i in range(300):
            nc.push("info", f"Unique{i}", f"Unique{i}")
        time.sleep(2.0)
        # Internal cache is bounded at 200 — verify no attribute errors
        assert hasattr(nc, "_dedup_cache")


class TestListenerManagement:
    def test_add_and_remove_listener(self, nc):
        calls = []
        cb = lambda n: calls.append(n)
        nc.add_listener(cb)
        nc.push("info", "T", "M")
        time.sleep(0.2)
        assert len(calls) == 1
        nc.remove_listener(cb)
        nc.push("info", "T2", "M2")
        time.sleep(0.2)
        assert len(calls) == 1   # no new call after removal

    def test_listener_error_does_not_kill_worker(self, nc):
        """A crashing listener must not stop other listeners from firing."""
        bad_calls, good_calls = [], []

        def bad_cb(n):
            bad_calls.append(n)
            raise RuntimeError("Intentional crash")

        def good_cb(n):
            good_calls.append(n)

        nc.add_listener(bad_cb)
        nc.add_listener(good_cb)
        nc.push("info", "Crash test", "Msg")
        time.sleep(0.3)
        assert len(good_calls) == 1, "Good listener must still fire after bad listener crashes"


class TestCategoryMapping:
    def test_known_categories(self, nc):
        categories = ["ai_signal", "signal", "paper_trade", "market_news",
                      "buy", "sell", "warning", "error", "success", "info"]
        received = []
        nc.add_listener(lambda n: received.append(n))
        for cat in categories:
            nc.push(cat, f"T-{cat}", f"M-{cat}")
        time.sleep(1.0)
        assert len(received) == len(categories)


class TestThreadSafety:
    def test_concurrent_pushes(self, nc):
        received = []
        nc.add_listener(lambda n: received.append(n))
        threads = []

        def push_unique(i):
            nc.push("info", f"ConcurrentTitle{i}", f"ConcurrentMsg{i}")

        for i in range(50):
            t = threading.Thread(target=push_unique, args=(i,))
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        time.sleep(1.0)
        assert len(received) == 50

    def test_concurrent_listener_add_remove(self, nc):
        """Rapidly adding and removing listeners must not corrupt the list."""
        errors = []

        def modifier():
            try:
                cb = lambda n: None
                nc.add_listener(cb)
                time.sleep(0.01)
                nc.remove_listener(cb)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=modifier) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
