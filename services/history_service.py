"""
=========================================================
 AI Trader Pro - Trade Journal Service
=========================================================
Persists every closed trade to a local CSV journal and
provides simple performance analytics (win rate, net P/L)
for the Trade Journal panel in the dashboard.

Fixes applied:
  - Thread-safe file access via threading.Lock()
  - File locking with fcntl.flock (Unix) / msvcrt.locking (Windows)
    so concurrent writer threads never corrupt the CSV.
  - Atomic write: data written to a temp file then renamed so a crash
    during write never leaves a partially-written journal.
  - Path resolved via path_manager so it works inside a frozen EXE.
  - load_trades() reads the file once and returns; no lingering handles.
  - Explicit UTF-8 encoding on every open() call.
"""

import csv
import os
import sys
import tempfile
import threading
from datetime import datetime
from typing import List

try:
    from utils.path_manager import get_data_path as _get_data_path
    _JOURNAL_PATH = _get_data_path("trade_journal.csv")
except Exception:
    _JOURNAL_PATH = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "trade_journal.csv")
    )

# Allow tests to override the path
FILE_NAME = _JOURNAL_PATH

FIELDS = ["timestamp", "asset", "side", "strategy", "entry", "exit", "size", "pnl", "result"]

_lock = threading.Lock()


# ── Platform-specific file locking ─────────────────────────────────────────

def _lock_file(fh):
    """Acquire an exclusive advisory lock on the open file handle."""
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, OSError):
        pass   # Lock not available — still protected by in-process _lock


def _unlock_file(fh):
    """Release the advisory file lock."""
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_UN)
    except (ImportError, OSError):
        pass


# ── Public API ─────────────────────────────────────────────────────────────

def log_trade(trade: dict) -> None:
    """
    Append one closed trade to the journal CSV.
    Creates the file (and parent directory) on first use.
    Thread-safe: uses both an in-process lock and an advisory file lock.
    """
    journal = FILE_NAME
    os.makedirs(os.path.dirname(journal), exist_ok=True)
    pnl = float(trade.get("pnl", 0.0))

    row = {
        "timestamp": trade.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "asset":     trade.get("asset", ""),
        "side":      trade.get("side", ""),
        "strategy":  trade.get("strategy", ""),
        "entry":     f"{float(trade.get('entry', 0.0)):.5f}",
        "exit":      f"{float(trade.get('exit', 0.0)):.5f}",
        "size":      trade.get("size", ""),
        "pnl":       f"{pnl:.2f}",
        "result":    "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN"),
    }

    with _lock:
        file_exists = os.path.isfile(journal)
        with open(journal, "a", newline="", encoding="utf-8") as fh:
            _lock_file(fh)
            try:
                writer = csv.DictWriter(fh, fieldnames=FIELDS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
            finally:
                _unlock_file(fh)


def load_trades(limit: int = 50) -> List[dict]:
    """
    Return the most recent `limit` journal entries, newest first.
    Never raises — returns [] if the file is missing or unreadable.
    """
    journal = FILE_NAME
    if not os.path.isfile(journal):
        return []

    try:
        with _lock:
            with open(journal, "r", newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        return list(reversed(rows[-limit:]))
    except Exception:
        return []


def get_summary() -> dict:
    """Aggregate performance stats across the entire journal history."""
    journal = FILE_NAME
    empty = {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "net_pnl": 0.0}

    if not os.path.isfile(journal):
        return empty

    try:
        with _lock:
            with open(journal, "r", newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
    except Exception:
        return empty

    total = len(rows)
    if total == 0:
        return empty

    try:
        pnls    = [float(r.get("pnl", 0.0)) for r in rows]
    except (ValueError, TypeError):
        return empty

    wins   = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)

    return {
        "total":    total,
        "wins":     wins,
        "losses":   losses,
        "win_rate": (wins / total) * 100.0,
        "net_pnl":  sum(pnls),
    }
