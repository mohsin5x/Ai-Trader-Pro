"""
tests/test_market_data_provider.py
====================================
Market data provider unit tests — rate limiter, TTL cache, provider base.
"""

import time
import threading
import pytest
from services.market_data_provider import RateLimiter, TTLCache


class TestRateLimiter:
    def test_allows_within_budget(self):
        rl = RateLimiter(max_credits=10, period_seconds=60)
        for _ in range(10):
            assert rl.allow(cost=1) is True

    def test_blocks_when_over_budget(self):
        rl = RateLimiter(max_credits=5, period_seconds=60)
        for _ in range(5):
            rl.allow(cost=1)
        assert rl.allow(cost=1) is False

    def test_multi_credit_cost(self):
        rl = RateLimiter(max_credits=8, period_seconds=60)
        assert rl.allow(cost=5) is True
        assert rl.allow(cost=4) is False   # only 3 left
        assert rl.allow(cost=3) is True

    def test_remaining_credits(self):
        rl = RateLimiter(max_credits=10, period_seconds=60)
        rl.allow(cost=3)
        assert rl.remaining() == 7

    def test_window_resets_over_time(self):
        rl = RateLimiter(max_credits=2, period_seconds=0.2)
        assert rl.allow() is True
        assert rl.allow() is True
        assert rl.allow() is False
        time.sleep(0.3)
        # Window expired — should allow again
        assert rl.allow() is True

    def test_thread_safe_concurrency(self):
        rl = RateLimiter(max_credits=100, period_seconds=60)
        allowed = []
        lock = threading.Lock()

        def try_allow():
            result = rl.allow(cost=1)
            with lock:
                allowed.append(result)

        threads = [threading.Thread(target=try_allow) for _ in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 100 should be allowed
        assert sum(1 for r in allowed if r) == 100
        assert sum(1 for r in allowed if not r) == 100


class TestTTLCache:
    def test_set_and_get_fresh(self):
        cache = TTLCache()
        cache.set("key1", "value1")
        assert cache.get_fresh("key1", ttl=10.0) == "value1"

    def test_expired_fresh_returns_none(self):
        cache = TTLCache()
        cache.set("key1", "stale")
        time.sleep(0.1)
        assert cache.get_fresh("key1", ttl=0.05) is None

    def test_get_stale_within_max_age(self):
        cache = TTLCache()
        cache.set("key1", "value1")
        time.sleep(0.1)
        # Past TTL but within max_age
        assert cache.get_stale("key1", max_age=10.0) == "value1"

    def test_get_stale_beyond_max_age(self):
        cache = TTLCache()
        cache.set("key1", "old")
        time.sleep(0.2)
        assert cache.get_stale("key1", max_age=0.1) is None

    def test_missing_key_returns_none(self):
        cache = TTLCache()
        assert cache.get_fresh("nonexistent", ttl=10.0) is None
        assert cache.get_stale("nonexistent", max_age=10.0) is None

    def test_clear_wipes_all(self):
        cache = TTLCache()
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear()
        assert cache.get_fresh("k1", ttl=60) is None
        assert cache.get_fresh("k2", ttl=60) is None

    def test_size_method(self):
        cache = TTLCache()
        assert cache.size() == 0
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        assert cache.size() == 2

    def test_bounded_at_max_entries(self):
        """Cache must evict oldest entries when cap is reached."""
        cache = TTLCache(max_entries=10)
        for i in range(20):
            cache.set(f"key{i}", f"value{i}")
        assert cache.size() <= 10

    def test_evicts_oldest_first(self):
        """After filling cap, the first inserted keys should be gone."""
        cache = TTLCache(max_entries=5)
        for i in range(5):
            cache.set(f"early{i}", f"val{i}")
            time.sleep(0.01)
        for i in range(5):
            cache.set(f"late{i}", f"val{i}")
        # Late keys should still be present
        for i in range(5):
            assert cache.get_fresh(f"late{i}", ttl=60) == f"val{i}"

    def test_thread_safe_concurrent_writes(self):
        cache = TTLCache(max_entries=100)
        errors = []

        def writer(i):
            try:
                cache.set(f"key{i}", f"value{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cache.size() <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
