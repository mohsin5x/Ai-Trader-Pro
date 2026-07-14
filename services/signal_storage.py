"""
services/signal_storage.py
============================
Permanent, searchable AI signal history for AI Trader Pro.

Statuses:
  ACTIVE     - Signal confirmed, awaiting execution / price action
  TRIGGERED  - Price reached entry; paper trade opened from this signal
  EXPIRED    - TTL elapsed with no TP/SL hit
  CLOSED     - TP or SL hit; result known (WIN / LOSS / BREAKEVEN)
  CANCELLED  - Invalidated before price reached entry

Every row stores: Symbol, Strategy, Timeframe, Direction, Entry, SL, TP1/2/3,
Confidence, Strength, created_at, expires_at, closed_at, result, exit_price,
paper_trade_id (FK to paper_trading.db trades), reasons (JSON).

Thread-safety: single write-lock around all mutations.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

try:
    from utils.path_manager import get_data_path as _get_data_path
    DB_PATH = _get_data_path("signals.db")
except Exception:
    DB_PATH = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "signals.db")
    )

_lock = threading.Lock()

# How long a signal stays ACTIVE before auto-expiring (seconds)
SIGNAL_TTL_SECONDS = 4 * 3600   # 4 hours


# ─────────────────────────────────────────────────────────────
# Connection helper
# ─────────────────────────────────────────────────────────────
@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # writer doesn't block readers
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────
def init_db():
    with _lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                direction       TEXT    NOT NULL,   -- BUY / SELL
                strategy        TEXT,               -- e.g. ICT Smart Money / Intraday
                timeframe       TEXT,               -- setup timeframe e.g. 15M
                entry_price     REAL    NOT NULL,
                stop_loss       REAL    NOT NULL,
                take_profit_1   REAL    NOT NULL,
                take_profit_2   REAL,
                take_profit_3   REAL,
                confidence      INTEGER NOT NULL,
                strength        TEXT,
                trend           TEXT,
                trade_type      TEXT,
                data_source     TEXT,
                session         TEXT,
                status          TEXT    NOT NULL DEFAULT 'ACTIVE',
                result          TEXT,               -- WIN / LOSS / BREAKEVEN
                created_at      REAL    NOT NULL,
                expires_at      REAL    NOT NULL,
                triggered_at    REAL,               -- when paper trade opened
                closed_at       REAL,
                exit_price      REAL,
                paper_trade_id  INTEGER,            -- FK → paper_trading.db trades.id
                reasons         TEXT,               -- JSON list
                notified        INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sig_status "
            "ON signals (status, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sig_symbol "
            "ON signals (symbol, created_at DESC)"
        )
        # Safe migration for older schemas — add ANY column that may be
        # missing from a database created by an earlier version of the app.
        _safe_add_columns(conn, "signals", [
            ("strategy",       "TEXT"),
            ("timeframe",      "TEXT"),
            ("strength",       "TEXT"),
            ("trend",          "TEXT"),
            ("trade_type",     "TEXT"),
            ("data_source",    "TEXT"),
            ("session",        "TEXT"),
            ("triggered_at",   "REAL"),
            ("closed_at",      "REAL"),
            ("exit_price",     "REAL"),
            ("paper_trade_id", "INTEGER"),
            ("result",         "TEXT"),
            ("notified",       "INTEGER DEFAULT 0"),
            ("take_profit_2",  "REAL"),
            ("take_profit_3",  "REAL"),
        ])


_SAFE_IDENTIFIER = set("abcdefghijklmnopqrstuvwxyz_0123456789")


def _validate_identifier(name: str) -> str:
    """Validate a SQL identifier (table/column name) to prevent injection.
    Only lowercase letters, digits, and underscores are allowed.
    Raises ValueError on invalid input."""
    if not name or not all(c in _SAFE_IDENTIFIER for c in name.lower()):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name.lower()


def _safe_add_columns(conn, table: str, cols: list):
    """Safely add columns to a table, validating all identifiers first."""
    safe_table = _validate_identifier(table)
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({safe_table})")}
    for col, defn in cols:
        safe_col = _validate_identifier(col)
        if safe_col not in existing:
            # defn is a data type string from our internal constants list —
            # validate it too against a safe allowlist.
            safe_defn = _safe_sql_type(defn)
            try:
                conn.execute(f"ALTER TABLE {safe_table} ADD COLUMN {safe_col} {safe_defn}")
            except Exception:
                pass


def _safe_sql_type(defn: str) -> str:
    """Validate a SQLite type definition against an allowlist."""
    _ALLOWED_TYPES = {
        "TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC",
        "INTEGER DEFAULT 0", "INTEGER DEFAULT 1",
        "REAL DEFAULT 0.0", "TEXT DEFAULT ''",
    }
    defn_upper = defn.strip().upper()
    # Check exact match or prefix match
    for allowed in _ALLOWED_TYPES:
        if defn_upper == allowed or defn_upper.startswith(allowed.split()[0] + " "):
            return defn.strip()
    raise ValueError(f"Disallowed SQL type definition: {defn!r}")


# ─────────────────────────────────────────────────────────────
# Write operations
# ─────────────────────────────────────────────────────────────
def upsert_signal(signal) -> tuple[int, bool]:
    """
    Insert a new signal or refresh an existing ACTIVE one for the same
    symbol+direction+entry_price within the TTL window.  Returns (id, is_new).

    FIX: Only merge into an existing row if the entry_price is within 0.05%
    of the stored entry — otherwise create a fresh row so each distinct setup
    appears as its own history entry instead of silently overwriting the old one.
    """
    reasons_json = json.dumps(list(signal.reasons)) if signal.reasons else "[]"
    strategy = getattr(signal, "trade_type", "") or ""
    timeframe = getattr(signal, "setup_timeframe", "") or ""

    with _lock, _connect() as conn:
        existing = conn.execute(
            """SELECT id, entry_price FROM signals
               WHERE symbol=? AND direction=? AND status='ACTIVE'
                 AND created_at >= ?
               ORDER BY created_at DESC LIMIT 1""",
            (signal.symbol, signal.direction, time.time() - SIGNAL_TTL_SECONDS),
        ).fetchone()

        expires_at = signal.created_at + SIGNAL_TTL_SECONDS

        # Only treat it as the same signal if the entry price is within 0.05%
        if existing:
            stored_entry = existing["entry_price"] or 0.0
            new_entry    = signal.entry_price or 0.0
            price_close  = (stored_entry == 0.0 or new_entry == 0.0 or
                            abs(new_entry - stored_entry) / max(abs(stored_entry), 1e-10) < 0.0005)
            if price_close:
                conn.execute(
                    """UPDATE signals SET
                       entry_price=?, stop_loss=?, take_profit_1=?, take_profit_2=?,
                       take_profit_3=?, confidence=?, strength=?, trend=?, trade_type=?,
                       strategy=?, timeframe=?, data_source=?, session=?,
                       expires_at=?, reasons=?
                       WHERE id=?""",
                    (signal.entry_price, signal.stop_loss, signal.take_profit_1,
                     signal.take_profit_2, signal.take_profit_3,
                     signal.confidence, signal.strength, signal.trend,
                     strategy, strategy, timeframe,
                     signal.data_source, signal.session, expires_at,
                     reasons_json, existing["id"]),
                )
                return existing["id"], False
            # Entry moved enough — fall through to insert a fresh row

        cur = conn.execute(
            """INSERT INTO signals
               (symbol, direction, strategy, timeframe, entry_price, stop_loss,
                take_profit_1, take_profit_2, take_profit_3,
                confidence, strength, trend, trade_type,
                data_source, session, created_at, expires_at, reasons, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE')""",
            (signal.symbol, signal.direction, strategy, timeframe,
             signal.entry_price, signal.stop_loss,
             signal.take_profit_1, signal.take_profit_2, signal.take_profit_3,
             signal.confidence, signal.strength, signal.trend, strategy,
             signal.data_source, signal.session,
             signal.created_at, expires_at, reasons_json),
        )
        return cur.lastrowid, True


def mark_triggered(signal_id: int, paper_trade_id: int):
    """Signal became TRIGGERED when a paper trade was opened from it."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE signals
               SET status='TRIGGERED', triggered_at=?, paper_trade_id=?
               WHERE id=? AND status='ACTIVE'""",
            (time.time(), paper_trade_id, signal_id),
        )


def close_signal(signal_id: int, exit_price: float, result: str):
    """Signal resolved: TP/SL hit. result = WIN / LOSS / BREAKEVEN."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE signals
               SET status='CLOSED', result=?, exit_price=?, closed_at=?
               WHERE id=?""",
            (result, exit_price, time.time(), signal_id),
        )


def cancel_signal(signal_id: int, reason: str = ""):
    """Explicitly invalidate a signal before expiry."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE signals SET status='CANCELLED', result=?
               WHERE id=? AND status='ACTIVE'""",
            (reason or "CANCELLED", signal_id),
        )


def expire_old_signals():
    """Auto-expire all ACTIVE signals whose TTL has passed."""
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE signals SET status='EXPIRED' "
            "WHERE status='ACTIVE' AND expires_at < ?",
            (time.time(),),
        )


def mark_notified(signal_id: int):
    with _lock, _connect() as conn:
        conn.execute("UPDATE signals SET notified=1 WHERE id=?", (signal_id,))


# ─────────────────────────────────────────────────────────────
# Read operations
# ─────────────────────────────────────────────────────────────
def get_signals(
    status: str = None,
    symbol: str = None,
    direction: str = None,
    strategy: str = None,
    search: str = None,
    date_from: float = None,
    date_to: float = None,
    min_confidence: int = None,
    limit: int = 1000,
) -> list:
    """Flexible query for signal history with all supported filters."""
    query = "SELECT * FROM signals WHERE 1=1"
    params: list = []

    if status and status != "All":
        query += " AND status=?"
        params.append(status)
    if symbol and symbol != "All":
        query += " AND symbol=?"
        params.append(symbol)
    if direction and direction != "All":
        query += " AND direction=?"
        params.append(direction)
    if strategy and strategy != "All":
        query += " AND (strategy=? OR trade_type=?)"
        params.extend([strategy, strategy])
    if search:
        like = f"%{search}%"
        query += " AND (symbol LIKE ? OR strategy LIKE ? OR direction LIKE ? OR strength LIKE ?)"
        params.extend([like, like, like, like])
    if date_from:
        query += " AND created_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND created_at <= ?"
        params.append(date_to)
    if min_confidence is not None:
        query += " AND confidence >= ?"
        params.append(min_confidence)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_active_signals() -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE status='ACTIVE' ORDER BY confidence DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_active_count() -> int:
    expire_old_signals()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM signals WHERE status='ACTIVE'"
        ).fetchone()
        return row["c"] if row else 0


def get_distinct_symbols() -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM signals ORDER BY symbol"
        ).fetchall()
        return [r["symbol"] for r in rows]


def get_distinct_strategies() -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT strategy FROM signals WHERE strategy IS NOT NULL AND strategy != '' ORDER BY strategy"
        ).fetchall()
        return [r["strategy"] for r in rows]


def get_performance_stats() -> dict:
    """Aggregate stats across all closed signals for the Signal History page."""
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM signals").fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status='ACTIVE'").fetchone()["c"]
        triggered = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status='TRIGGERED'").fetchone()["c"]
        closed = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status='CLOSED'").fetchone()["c"]
        expired = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status='EXPIRED'").fetchone()["c"]
        cancelled = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status='CANCELLED'").fetchone()["c"]
        wins = conn.execute("SELECT COUNT(*) as c FROM signals WHERE result='WIN'").fetchone()["c"]
        losses = conn.execute("SELECT COUNT(*) as c FROM signals WHERE result='LOSS'").fetchone()["c"]
        avg_conf = conn.execute("SELECT AVG(confidence) as a FROM signals").fetchone()["a"] or 0.0

    win_rate = (wins / closed * 100.0) if closed else 0.0
    return {
        "total": total, "active": active, "triggered": triggered,
        "closed": closed, "expired": expired, "cancelled": cancelled,
        "wins": wins, "losses": losses,
        "win_rate": win_rate, "avg_confidence": avg_conf,
    }


def get_unnotified_new_signals() -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE status='ACTIVE' AND notified=0 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# Initialise on import
init_db()

def close():
    """No-op: per-call connections only. Called during graceful shutdown."""
    pass
