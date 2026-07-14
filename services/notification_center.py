"""
services/notification_center.py
================================
Production-grade, thread-safe notification center for AI Trader Pro.

Fixes applied:
  - Bounded dedup_cache (max 200 entries — was unbounded, causing memory leak).
  - Bounded _history (max 500 entries, LRU-trimmed).
  - Proper shutdown() method for graceful teardown.
  - remove_listener() prevents stale callback references (memory leak).
  - Worker thread exits cleanly on shutdown() instead of running forever.
  - Listener errors never kill the worker thread.
  - Category mapping extended with all valid types used by callers.
"""

from __future__ import annotations

import time
import queue
import threading
import logging
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

HIGH_CONFIDENCE_THRESHOLD = 0.80

# Maximum entries kept in the bounded history list
_MAX_HISTORY = 500

# Maximum entries in the dedup cache before oldest entries are pruned
_MAX_DEDUP_CACHE = 200

# Seconds within which identical title+message are de-duplicated
_DEDUP_WINDOW = 60.0

# ── Notification type mapping ──────────────────────────────────────────────
_CATEGORY_TO_NTYPE: dict[str, str] = {
    "ai_signal":       "ai_signal",
    "signal":          "ai_signal",
    "high_confidence": "high_confidence",
    "paper_trade":     "paper_trade",
    "market_news":     "market_news",
    "news":            "market_news",
    "buy":             "buy",
    "sell":            "sell",
    "warning":         "warning",
    "error":           "error",
    "success":         "success",
    "info":            "info",
    "system":          "system",
    "connection":      "connection",
    "api":             "api",
    "market_alert":    "market_alert",
    "scanner":         "market_alert",
}

_LEVEL_TO_NTYPE: dict[str, str] = {
    "buy":     "buy",
    "sell":    "sell",
    "warning": "warning",
    "error":   "error",
    "success": "success",
    "info":    "info",
}


class Notification:
    """Full notification model consumed by the bell panel and popup system."""

    _id_counter: int = 0
    _id_lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        title: str,
        message: str,
        ntype: str = "info",
        level: str = "info",
        category: Optional[str] = None,
        data=None,
    ):
        with Notification._id_lock:
            Notification._id_counter += 1
            self.nid = Notification._id_counter

        self.title      = title
        self.message    = message
        self.ntype      = ntype
        self.level      = level
        self.category   = category
        self.data       = data
        self.created_at = time.time()
        self.read       = False

    def __repr__(self) -> str:
        return f"<Notification #{self.nid} [{self.ntype}] {self.title!r}>"


class NotificationCenter:
    """
    Thread-safe singleton notification center.

    All mutations go through the internal queue so the UI thread is never
    blocked by listener callbacks.
    """

    _instance: Optional["NotificationCenter"] = None
    _init_lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._init_lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._initialized = False
                cls._instance = obj
        return cls._instance

    def __init__(self, master=None):
        if self._initialized:
            return
        self._initialized = True

        self._lock:         threading.Lock   = threading.Lock()
        self._history:      List[Notification] = []
        self._listeners:    List[Callable]   = []
        self._queue:        queue.Queue      = queue.Queue(maxsize=1000)
        self._dedup_cache:  dict             = {}   # (title, message) → last_ts
        self._shutdown_evt: threading.Event  = threading.Event()

        self._worker = threading.Thread(
            target=self._process_queue,
            daemon=True,
            name="NC-Worker",
        )
        self._worker.start()
        logger.info("[NotificationCenter] Started.")

    # ── Public API ─────────────────────────────────────────────────────────

    def push(
        self,
        category: str,
        title: str,
        message: str,
        data=None,
        level: str = "info",
    ) -> None:
        """Primary push method — safe to call from any thread."""
        ntype = _CATEGORY_TO_NTYPE.get(category) or _LEVEL_TO_NTYPE.get(level) or "info"
        try:
            self._queue.put_nowait({
                "title":    title,
                "message":  message,
                "ntype":    ntype,
                "level":    level,
                "category": category,
                "data":     data,
            })
        except queue.Full:
            logger.warning("[NotificationCenter] Queue full — notification dropped.")

    def enqueue(self, title: str, message: str, level: str = "info") -> None:
        """Legacy compatibility wrapper."""
        ntype = _LEVEL_TO_NTYPE.get(level, "info")
        try:
            self._queue.put_nowait({
                "title":    title,
                "message":  message,
                "ntype":    ntype,
                "level":    level,
                "category": None,
                "data":     None,
            })
        except queue.Full:
            logger.warning("[NotificationCenter] Queue full — legacy notification dropped.")

    def add_listener(self, callback: Callable) -> None:
        """Register a callback that receives Notification objects."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable) -> None:
        """Unregister a callback to prevent stale reference leaks."""
        with self._lock:
            self._listeners = [cb for cb in self._listeners if cb is not callback]

    def get_all(self) -> List[Notification]:
        with self._lock:
            return list(self._history)

    def unread_count(self) -> int:
        with self._lock:
            return sum(1 for n in self._history if not n.read)

    def mark_read(self, nid: int) -> None:
        with self._lock:
            for n in self._history:
                if n.nid == nid:
                    n.read = True
                    break

    def mark_all_read(self) -> None:
        with self._lock:
            for n in self._history:
                n.read = True

    def clear_all(self) -> None:
        with self._lock:
            self._history.clear()
            self._dedup_cache.clear()

    def shutdown(self, timeout: float = 3.0) -> None:
        """
        Gracefully stop the worker thread.
        Call this during application teardown to avoid zombie threads.
        """
        self._shutdown_evt.set()
        # Unblock the queue.get() call in the worker
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._worker.join(timeout=timeout)
        logger.info("[NotificationCenter] Shutdown complete.")

    # ── Internal ───────────────────────────────────────────────────────────

    def _process_queue(self) -> None:
        while not self._shutdown_evt.is_set():
            try:
                item = self._queue.get(timeout=0.5)
                if item is None:   # sentinel for shutdown
                    self._queue.task_done()
                    break
                self._handle(item)
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as exc:
                logger.error(f"[NotificationCenter] Worker error: {exc}")

    def _handle(self, item: dict) -> None:
        title   = str(item.get("title", ""))
        message = str(item.get("message", ""))

        # Deduplication: collapse identical title+message within _DEDUP_WINDOW
        key = (title, message)
        now = time.time()
        with self._lock:
            last = self._dedup_cache.get(key, 0.0)
            if now - last < _DEDUP_WINDOW:
                return
            self._dedup_cache[key] = now
            # Prune dedup cache if it grows too large (LRU by removal order)
            if len(self._dedup_cache) > _MAX_DEDUP_CACHE:
                oldest_keys = sorted(self._dedup_cache, key=self._dedup_cache.__getitem__)
                for old_key in oldest_keys[: len(self._dedup_cache) - _MAX_DEDUP_CACHE]:
                    del self._dedup_cache[old_key]

        n = Notification(
            title=title,
            message=message,
            ntype=item.get("ntype", "info"),
            level=item.get("level", "info"),
            category=item.get("category"),
            data=item.get("data"),
        )

        with self._lock:
            self._history.append(n)
            # Trim history to bounded size (remove oldest first)
            if len(self._history) > _MAX_HISTORY:
                self._history = self._history[-_MAX_HISTORY:]
            listeners = list(self._listeners)

        logger.debug(f"[NC] [{n.ntype.upper()}] {n.title}: {n.message[:80]}")

        for cb in listeners:
            try:
                cb(n)
            except Exception as exc:
                logger.warning(f"[NotificationCenter] Listener error: {exc}")


# ── Global singleton ───────────────────────────────────────────────────────
nc = NotificationCenter()
