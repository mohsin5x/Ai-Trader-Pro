"""
services/market_scanner.py
=============================
Background AI Market Scanner — continuously scans every supported asset.

Improvements:
  • Smarter deduplication: new signal only stored & notified when direction
    changes or a cooldown has elapsed since the last notification.
  • Per-symbol scan interval spread evenly across SIGNAL_SCAN_INTERVAL_SECONDS.
  • expire_old_signals() called once per full cycle.
  • register_new_signal_callback() for UI badge updates.
  • Thread-safe reads via get_signals() / get_active_signal_count().
  • Pause / Resume support.
  • Progress reporting (symbol index, total, ETA).
  • Robust error handling with automatic recovery.
"""

from __future__ import annotations

import threading
import time

from config import settings
from utils.logger import logger
from services import signal_storage
from services.notification_center import nc, HIGH_CONFIDENCE_THRESHOLD

# Minimum seconds between notifications for the same symbol+direction.
# Loaded from environment / config at import time; can be overridden at runtime
# via set_notify_cooldown() without restarting the app.
_NOTIFY_COOLDOWN_SECONDS: int = int(
    __import__("os").environ.get("SCANNER_NOTIFY_COOLDOWN_SECONDS", "300")
)


def set_notify_cooldown(seconds: int) -> None:
    """Override the notification cooldown at runtime (e.g. from Settings panel)."""
    global _NOTIFY_COOLDOWN_SECONDS
    _NOTIFY_COOLDOWN_SECONDS = max(30, int(seconds))


class MarketScanner:
    def __init__(self, crypto_service, signal_engine, symbols=None):
        self.crypto_service = crypto_service
        self.signal_engine  = signal_engine
        self.symbols        = symbols or list(crypto_service.ASSETS)

        self._lock = threading.Lock()
        self._signals:            dict  = {}   # symbol → Signal
        self._last_scan_at:       dict  = {}   # symbol → epoch
        self._last_direction:     dict  = {}   # symbol → "BUY"/"SELL"/None
        self._last_notify_at:     dict  = {}   # symbol → epoch (for cooldown)
        self._last_full_cycle_at: float | None = None
        self._stop   = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._new_signal_callbacks: list = []

        # Progress tracking
        self._scan_current_symbol: str   = ""
        self._scan_current_index:  int   = 0
        self._scan_total:          int   = len(self.symbols)
        self._scan_eta_seconds:    float = 0.0

    # ─── Lifecycle ────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop   = False
        self._paused = False
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ai-market-scanner"
        )
        self._thread.start()
        # Classify symbols so the log clearly separates forex and crypto
        _forex_keywords = {"/", "US30", "NAS100", "SPX500"}
        _crypto_only = {"BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","MATIC",
                        "DOT","LINK","LTC","UNI","ATOM","TRX","BCH","TON","APT","ARB",
                        "OP","INJ","SUI","SEI","NEAR","FTM","ALGO","VET","AAVE","MKR",
                        "LDO","RUNE","HBAR","ENJ","CHZ","BAT","SAND","MANA","AXS",
                        "GALA","CRV","SNX","COMP","USDT","BNB"}
        forex_syms  = [s for s in self.symbols
                       if "/" in s or s in ("US30", "NAS100", "SPX500")]
        crypto_syms = [s for s in self.symbols
                       if s.upper() in _crypto_only or
                          ("/" in s and s.split("/")[0].upper() in _crypto_only)]
        other_syms  = [s for s in self.symbols
                       if s not in forex_syms and s not in crypto_syms]
        logger.info(
            f"[MarketScanner] Started — scanning {len(self.symbols)} symbols total: "
            f"{len(forex_syms)} Forex/Indices ({', '.join(forex_syms[:6])}"
            f"{'…' if len(forex_syms) > 6 else ''}), "
            f"{len(crypto_syms)} Crypto ({', '.join(crypto_syms[:6])}"
            f"{'…' if len(crypto_syms) > 6 else ''})"
            + (f", {len(other_syms)} Other" if other_syms else "") + "."
        )

    def stop(self):
        self._stop = True

    def pause(self):
        """Pause the scanner between symbols."""
        with self._lock:
            self._paused = True
        logger.info("[MarketScanner] Paused.")

    def resume(self):
        """Resume a paused scanner."""
        with self._lock:
            self._paused = False
        logger.info("[MarketScanner] Resumed.")

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    # ─── Callback registration ────────────────────────────────────────
    def register_new_signal_callback(self, cb):
        with self._lock:
            if cb not in self._new_signal_callbacks:
                self._new_signal_callbacks.append(cb)

    # ─── Scan loop ────────────────────────────────────────────────────
    def _run_loop(self):
        signal_storage.init_db()
        n = max(1, len(self.symbols))

        while not self._stop:
            cycle_start = time.time()

            per_symbol_sleep = max(
                0.5,
                settings.SIGNAL_SCAN_INTERVAL_SECONDS / n
            )

            for idx, symbol in enumerate(self.symbols):
                if self._stop:
                    return

                # Pause support
                while self._paused and not self._stop:
                    time.sleep(0.3)

                with self._lock:
                    self._scan_current_symbol = symbol
                    self._scan_current_index  = idx + 1
                    elapsed = time.time() - cycle_start
                    if idx > 0:
                        remaining = (elapsed / idx) * (n - idx)
                        self._scan_eta_seconds = remaining
                    else:
                        self._scan_eta_seconds = 0.0

                try:
                    self._scan_one(symbol)
                except Exception as exc:
                    logger.warning(f"[MarketScanner] unhandled error for {symbol}: {exc}")

                time.sleep(per_symbol_sleep)

            try:
                signal_storage.expire_old_signals()
            except Exception:
                pass

            with self._lock:
                self._last_full_cycle_at = time.time()
                self._scan_current_symbol = ""
                self._scan_eta_seconds    = 0.0

            elapsed = time.time() - cycle_start
            leftover = settings.SIGNAL_SCAN_INTERVAL_SECONDS - elapsed
            if leftover > 1.0:
                time.sleep(leftover)

    @staticmethod
    def _is_forex_market_open(symbol: str) -> bool:
        """Return True if the forex/index market for this symbol is currently open.
        Crypto symbols (no '/' or special index names) trade 24/7 and always return True.
        Forex is closed Saturday UTC + Sunday UTC until 22:00 (Sydney open).
        """
        from datetime import datetime, timezone as _tz
        # Crypto trades 24/7
        crypto_only = not ('/' in symbol or symbol in ('US30', 'NAS100', 'SPX500', 'XAU/USD', 'XAG/USD'))
        if crypto_only and '/' not in symbol:
            return True
        now_utc = datetime.now(_tz.utc)
        weekday = now_utc.weekday()   # 0=Mon … 5=Sat, 6=Sun
        hour    = now_utc.hour
        # Saturday is always closed for forex
        if weekday == 5:
            return False
        # Sunday: market opens at 22:00 UTC (Sydney session)
        if weekday == 6 and hour < 22:
            return False
        return True

    def _scan_one(self, symbol: str):
        # Skip forex/index signals when the market is closed (weekend)
        if not self._is_forex_market_open(symbol):
            with self._lock:
                # Remove any stale signal for this symbol while market is closed
                self._signals.pop(symbol, None)
                self._last_direction[symbol] = None
            return

        signal = None
        try:
            signal = self.signal_engine.analyze(symbol)
        except Exception as exc:
            logger.warning(f"[MarketScanner] {symbol}: {exc}")

        is_new = False
        now = time.time()
        with self._lock:
            self._last_scan_at[symbol] = now
            prev_dir     = self._last_direction.get(symbol)
            last_notif   = self._last_notify_at.get(symbol, 0)
            cooldown_ok  = (now - last_notif) > _NOTIFY_COOLDOWN_SECONDS

            if signal is not None:
                self._signals[symbol] = signal
                new_dir = signal.direction
                is_new  = (new_dir != prev_dir) or cooldown_ok
                self._last_direction[symbol] = new_dir
                if is_new:
                    self._last_notify_at[symbol] = now
            else:
                self._signals.pop(symbol, None)
                self._last_direction[symbol] = None

        if signal is not None:
            self._persist_and_notify(signal, is_new=is_new)

    def _persist_and_notify(self, signal, is_new: bool):
        try:
            sig_id, created_new = signal_storage.upsert_signal(signal)

            if is_new or created_new:
                nc.push(
                    "ai_signal",
                    f"🤖 AI Signal: {signal.symbol}",
                    f"{signal.direction} @ {signal.entry_price:.5f}  "
                    f"Conf: {signal.confidence}%  {signal.strength}",
                    data=signal.to_dict(),
                )
                if signal.confidence >= HIGH_CONFIDENCE_THRESHOLD:
                    nc.push(
                        "high_confidence",
                        f"🔥 High-Confidence: {signal.symbol}",
                        f"{signal.direction}  {signal.confidence}%  "
                        f"SL {signal.stop_loss:.5f}  TP {signal.take_profit_1:.5f}",
                        data=signal.to_dict(),
                    )
                with self._lock:
                    cbs = list(self._new_signal_callbacks)
                for cb in cbs:
                    try:
                        cb(signal)
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning(f"[MarketScanner] persist/notify failed: {exc}")

    # ─── Read API (UI thread safe) ────────────────────────────────────
    def get_signals(self) -> list:
        with self._lock:
            signals = list(self._signals.values())
        return sorted(signals, key=lambda s: s.confidence, reverse=True)

    def get_active_signal_count(self) -> int:
        with self._lock:
            return len(self._signals)

    def get_progress(self) -> dict:
        """Returns current scan progress for UI display."""
        with self._lock:
            return {
                "current":  self._scan_current_symbol,
                "index":    self._scan_current_index,
                "total":    self._scan_total,
                "eta":      self._scan_eta_seconds,
                "paused":   self._paused,
            }

    def get_status_text(self) -> str:
        with self._lock:
            scanned  = len(self._last_scan_at)
            active   = len(self._signals)
            last_cyc = self._last_full_cycle_at
            paused   = self._paused
            current  = self._scan_current_symbol
            idx      = self._scan_current_index
            total    = self._scan_total

        if paused:
            return f"⏸ Paused — {active} active signal(s)"
        if current:
            return f"Scanning {current} ({idx}/{total}) — {active} active signal(s)"
        if not scanned:
            return "Scanning markets..."
        ts = time.strftime("%H:%M:%S", time.localtime(last_cyc)) if last_cyc else "--"
        return f"Scanning {len(self.symbols)} markets — {active} active signal(s) — last pass {ts}"
