"""
services/paper_trading_db.py
=============================
Persistence layer for Paper Trading.

Tables:
  account       – single-row balance / starting_balance
  transactions  – deposit / withdrawal / reset / trade_pnl audit trail
  trades        – one row per paper trade (OPEN or CLOSED)

New in this version:
  - signal_id column links every trade back to the signal that generated it
  - WAL mode for safe concurrent reads from multiple threads
  - Safe migrations so existing DBs upgrade without data loss
"""

from __future__ import annotations

import csv
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

try:
    from utils.path_manager import get_data_path as _get_data_path
    DB_PATH = _get_data_path("paper_trading.db")
except Exception:
    DB_PATH = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "paper_trading.db")
    )

_lock = threading.Lock()


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(default_starting_balance: float = 10_000.0):
    with _lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS account (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                balance         REAL    NOT NULL,
                starting_balance REAL   NOT NULL,
                created_at      REAL    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                type         TEXT    NOT NULL,
                amount       REAL    NOT NULL,
                balance_after REAL   NOT NULL,
                note         TEXT,
                created_at   REAL    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id       INTEGER,            -- FK → signals.db signals.id
                symbol          TEXT    NOT NULL,
                timeframe       TEXT,
                signal_type     TEXT    NOT NULL,   -- BUY / SELL
                entry_price     REAL    NOT NULL,
                exit_price      REAL,
                stop_loss       REAL    NOT NULL,
                take_profit     REAL    NOT NULL,
                size            REAL    NOT NULL,
                size_label      TEXT,
                leverage        INTEGER DEFAULT 1,
                asset_class     TEXT,
                opened_at       REAL    NOT NULL,
                closed_at       REAL,
                duration_seconds REAL,
                pnl             REAL,
                pnl_pct         REAL,
                status          TEXT    NOT NULL,   -- OPEN / CLOSED
                result          TEXT,               -- WIN / LOSS / BREAKEVEN
                exit_reason     TEXT,               -- TAKE_PROFIT / STOP_LOSS / EXPIRED
                confidence      INTEGER,
                strategy        TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_status "
            "ON trades (status, opened_at DESC)"
        )
        # Safe migrations for pre-existing DBs
        _safe_add(conn, "trades", [
            ("signal_id",   "INTEGER"),
            ("leverage",    "INTEGER DEFAULT 1"),
            ("asset_class", "TEXT"),
        ])
        row = conn.execute("SELECT id FROM account WHERE id=1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO account (id, balance, starting_balance, created_at) "
                "VALUES (1, ?, ?, ?)",
                (default_starting_balance, default_starting_balance, time.time()),
            )


_SAFE_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz_0123456789")


def _validate_sql_id(name: str) -> str:
    """Prevent SQL injection in identifier positions."""
    if not name or not all(c in _SAFE_ID_CHARS for c in name.lower()):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name.lower()


def _safe_sql_type(defn: str) -> str:
    """Allowlist SQL type definitions."""
    _ALLOWED = {
        "TEXT", "INTEGER", "REAL", "BLOB",
        "INTEGER DEFAULT 1", "INTEGER DEFAULT 0",
        "TEXT DEFAULT ''",
    }
    upper = defn.strip().upper()
    for a in _ALLOWED:
        if upper == a or upper.startswith(a.split()[0] + " "):
            return defn.strip()
    raise ValueError(f"Disallowed SQL type: {defn!r}")


def _safe_add(conn, table: str, cols: list):
    safe_table = _validate_sql_id(table)
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({safe_table})")}
    for col, defn in cols:
        safe_col = _validate_sql_id(col)
        if safe_col not in existing:
            safe_defn = _safe_sql_type(defn)
            try:
                conn.execute(f"ALTER TABLE {safe_table} ADD COLUMN {safe_col} {safe_defn}")
            except Exception:
                pass


# ─── Account ───────────────────────────────────────────────────────────────
def get_account() -> dict:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
        return dict(row) if row else {}


def apply_balance_delta(amount: float, tx_type: str, note: str = "") -> float:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT balance FROM account WHERE id=1").fetchone()
        new_bal = (row["balance"] if row else 0.0) + amount
        conn.execute("UPDATE account SET balance=? WHERE id=1", (new_bal,))
        conn.execute(
            "INSERT INTO transactions (type, amount, balance_after, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (tx_type, amount, new_bal, note, time.time()),
        )
        return new_bal


def reset_account(starting_balance: float):
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM transactions")
        conn.execute(
            "UPDATE account SET balance=?, starting_balance=?, created_at=? WHERE id=1",
            (starting_balance, starting_balance, time.time()),
        )
        conn.execute(
            "INSERT INTO transactions (type, amount, balance_after, note, created_at) "
            "VALUES ('RESET', ?, ?, 'Account reset', ?)",
            (starting_balance, starting_balance, time.time()),
        )


def get_transactions(limit: int = 200) -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── Trades ────────────────────────────────────────────────────────────────
def open_trade(trade: dict) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (signal_id, symbol, timeframe, signal_type, entry_price,
                stop_loss, take_profit, size, size_label, leverage, asset_class,
                opened_at, status, confidence, strategy)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?)""",
            (
                trade.get("signal_id"),
                trade["symbol"],
                trade.get("timeframe", ""),
                trade["signal_type"],
                trade["entry_price"],
                trade["stop_loss"],
                trade["take_profit"],
                trade["size"],
                trade.get("size_label", ""),
                trade.get("leverage", 1),
                trade.get("asset_class", ""),
                trade["opened_at"],
                trade.get("confidence"),
                trade.get("strategy", ""),
            ),
        )
        return cur.lastrowid


def close_trade(trade_id: int, exit_price: float, closed_at: float,
                pnl: float, pnl_pct: float, result: str,
                exit_reason: str, opened_at: float):
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE trades SET
               exit_price=?, closed_at=?, duration_seconds=?,
               pnl=?, pnl_pct=?, status='CLOSED', result=?, exit_reason=?
               WHERE id=?""",
            (exit_price, closed_at, closed_at - opened_at,
             pnl, pnl_pct, result, exit_reason, trade_id),
        )


def get_open_trades() -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='OPEN' ORDER BY opened_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_trades(
    symbol: str = None,
    timeframe: str = None,
    date_from: float = None,
    date_to: float = None,
    status: str = None,
    result: str = None,
    strategy: str = None,
    search: str = None,
    limit: int = 5000,
) -> list:
    query = "SELECT * FROM trades WHERE 1=1"
    params: list = []
    if symbol and symbol != "All":
        query += " AND symbol=?"
        params.append(symbol)
    if timeframe and timeframe != "All":
        query += " AND timeframe=?"
        params.append(timeframe)
    if date_from:
        query += " AND opened_at>=?"
        params.append(date_from)
    if date_to:
        query += " AND opened_at<=?"
        params.append(date_to)
    if status and status != "All":
        query += " AND status=?"
        params.append(status)
    if result and result != "All":
        query += " AND result=?"
        params.append(result)
    if strategy and strategy != "All":
        query += " AND strategy=?"
        params.append(strategy)
    if search:
        like = f"%{search}%"
        query += " AND (symbol LIKE ? OR strategy LIKE ?)"
        params.extend([like, like])
    query += " ORDER BY opened_at DESC LIMIT ?"
    params.append(limit)
    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_distinct_symbols() -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM trades ORDER BY symbol"
        ).fetchall()
        return [r["symbol"] for r in rows]


def get_distinct_timeframes() -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT timeframe FROM trades "
            "WHERE timeframe!='' ORDER BY timeframe"
        ).fetchall()
        return [r["timeframe"] for r in rows]


# ─── Export ────────────────────────────────────────────────────────────────
_EXPORT_COLUMNS = [
    "id", "signal_id", "symbol", "timeframe", "signal_type",
    "entry_price", "exit_price", "stop_loss", "take_profit",
    "size", "size_label", "leverage", "asset_class",
    "opened_at", "closed_at", "duration_seconds",
    "pnl", "pnl_pct", "status", "result", "exit_reason",
    "confidence", "strategy",
]


def export_csv(filepath: str, trades: list):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_EXPORT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for t in trades:
            w.writerow(t)


def export_xlsx(filepath: str, trades: list) -> bool:
    try:
        import pandas as pd
        df = pd.DataFrame(trades, columns=_EXPORT_COLUMNS)
        df.to_excel(filepath, index=False, engine="openpyxl")
        return True
    except ImportError:
        return False


def close():
    """No-op: this module uses per-call connections (not a persistent pool).
    Called during graceful shutdown for forward compatibility."""
    pass
