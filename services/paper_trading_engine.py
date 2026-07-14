"""
services/paper_trading_engine.py
===================================
Fully-automatic Paper Trading Engine.

Key design decisions
─────────────────────
• Always-on: the engine starts with the app and runs continuously.
  There is NO start/stop button. Trading is fully automatic.

• One trade per symbol at a time. Duplicate prevention is enforced both
  in-memory (self._open_trades keyed by symbol) and in the DB (no two
  OPEN rows for the same symbol may exist at once).

• Signal linkage: every trade stores the signal_id that triggered it.
  When the trade closes, the signal is updated to CLOSED/EXPIRED with
  result = WIN / LOSS / BREAKEVEN.

• Non-blocking UI: all DB writes happen on this background thread; the
  UI reads snapshots via get_open_trades_snapshot() / get_floating_pnl().

• Deduplication: _last_acted_signal tracks (direction, rounded_entry)
  per symbol so the same signal never opens a second trade even if the
  scan loop re-confirms it.

Architecture preserved from original:
  - reads MarketScanner.get_signals()  (read-only, never touches scanner)
  - reads CryptoService for live prices
  - writes paper_trading_db  (isolated SQLite file)
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from utils.logger import logger
from services import paper_trading_db as db
from services import signal_storage
from services import leverage_manager as lm
from services.notification_center import nc

POLL_INTERVAL_SECONDS = 5.0


class PaperTradingEngine:
    def __init__(self, crypto_service, market_scanner, get_risk_percentage=None):
        self.crypto_service  = crypto_service
        self.market_scanner  = market_scanner
        self._get_risk_pct   = get_risk_percentage or (lambda: 0.01)

        self._lock = threading.Lock()

        # symbol → open-trade dict with live_pnl injected
        self._open_trades:       dict[str, dict] = {}
        # symbol → (direction, rounded_entry) to prevent re-acting on same signal
        self._last_acted_signal: dict[str, tuple] = {}

        self._latest_prices: dict[str, float] = {}

        # Always-running background thread
        self._thread: Optional[threading.Thread] = None
        self._stop = False

    # ─── Lifecycle ─────────────────────────────────────────────────────────
    def start(self):
        """Start the engine (called once at app launch, not by UI button)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop = False

        # Re-hydrate open trades from DB in case of app restart
        rehydrated_syms = []
        with self._lock:
            self._open_trades.clear()
            for t in db.get_open_trades():
                t_copy = dict(t)
                t_copy["live_pnl"] = 0.0
                self._open_trades[t_copy["symbol"]] = t_copy
                rehydrated_syms.append(t_copy["symbol"])

        # Register rehydrated symbols for live pricing (deferred so crypto_service
        # background thread has already started)
        def _register_syms():
            for sym in rehydrated_syms:
                try:
                    self.crypto_service.register_extra_symbol(sym)
                except Exception:
                    pass
        threading.Thread(target=_register_syms, daemon=True, name="sym-register").start()

        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="paper-trading-engine"
        )
        self._thread.start()
        logger.info("[PaperTradingEngine] Started (always-on).")

    def stop(self):
        """Stop for clean shutdown only (app close)."""
        self._stop = True

    # ─── Status / snapshots (UI reads) ─────────────────────────────────────
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop

    def get_status_text(self) -> str:
        with self._lock:
            n = len(self._open_trades)
        return f"Auto-running — {n} open paper trade(s)"

    def get_open_trades_snapshot(self) -> list:
        with self._lock:
            return [dict(t) for t in self._open_trades.values()]

    def get_floating_pnl(self) -> float:
        with self._lock:
            return sum(t.get("live_pnl", 0.0) for t in self._open_trades.values())

    def get_latest_prices(self) -> dict:
        with self._lock:
            return dict(self._latest_prices)

    # ─── Manual signal injection (from Manual Scanner "Apply to Algo") ──────
    def open_trade_from_signal(self, signal, max_duration_minutes: float = 0.0) -> str:
        """
        Immediately open a paper trade from any Signal object.

        max_duration_minutes -- if > 0, auto-closes at market price after that
                                many minutes (scalp timer). 0 = TP/SL only.
        Returns a short human-readable status string.
        """
        sym = signal.symbol

        with self._lock:
            if sym in self._open_trades:
                return f"⚠ {sym} already has an open paper trade."

        prices     = self._fetch_prices()
        live_price = (
            self._resolve_price(sym, prices)
            or getattr(signal, "current_price", 0)
            or signal.entry_price
        )
        if not live_price:
            return f"⚠ No live price available for {sym}."

        account = db.get_account()
        balance = account.get("balance", 0.0)
        if balance <= 0:
            return "⚠ Paper balance is zero — please deposit funds first."

        sizing = lm.compute_position(
            sym, balance, self._get_risk_pct(),
            signal.entry_price, signal.stop_loss,
        )
        if sizing["units"] <= 0:
            return f"⚠ Position size too small for {sym} — SL may be too tight."

        opened_at = time.time()
        sig_id    = self._get_signal_id(signal)

        trade = {
            "signal_id":      sig_id,
            "symbol":         sym,
            "timeframe":      getattr(signal, "setup_timeframe", ""),
            "signal_type":    signal.direction,
            "entry_price":    live_price,
            "stop_loss":      signal.stop_loss,
            "take_profit":    signal.take_profit_1,
            "size":           sizing["units"],
            "size_label":     sizing["size_label"],
            "leverage":       sizing["leverage"],
            "asset_class":    lm.asset_class_label(sym),
            "opened_at":      opened_at,
            "confidence":     signal.confidence,
            "strategy":       getattr(signal, "trade_type", "Manual"),
            "live_pnl":       0.0,
            "_max_duration_s": max_duration_minutes * 60.0 if max_duration_minutes > 0 else 0.0,
        }

        trade_id = db.open_trade(trade)
        trade["id"] = trade_id

        if sig_id:
            try:
                from services import signal_storage as _ss
                _ss.mark_triggered(sig_id, trade_id)
            except Exception:
                pass

        with self._lock:
            self._open_trades[sym] = trade
            self._last_acted_signal[sym] = (signal.direction, round(signal.entry_price, 6))

        # Register for live pricing (handles symbols not in default ASSETS list)
        try:
            self.crypto_service.register_extra_symbol(sym)
        except Exception:
            pass

        timer_note = f"  ⏱ auto-exit in {max_duration_minutes:.0f} min" if max_duration_minutes > 0 else ""
        nc.push(
            "paper_trade",
            f"📄 Manual Paper Trade: {sym}",
            f"{signal.direction} @ {live_price:.5f}  {sizing['size_label']}  Lev:{sizing['leverage']}x{timer_note}",
            data=trade,
        )
        logger.info(
            f"[PaperTradingEngine] MANUAL OPEN {signal.direction} {sym}"
            f" @ {live_price:.5f}  {sizing['size_label']}"
            + (f"  timer={max_duration_minutes:.0f}min" if max_duration_minutes > 0 else "")
        )
        return (f"✅ {sym} {signal.direction} @ {live_price:.5f}"
                f"  {sizing['size_label']}"
                + (f"  ⏱ exits in {max_duration_minutes:.0f} min" if max_duration_minutes > 0 else ""))

    def close_trade_now(self, symbol: str) -> str:
        """Force-close an open paper trade at current market price."""
        with self._lock:
            trade = self._open_trades.get(symbol)
        if not trade:
            return f"⚠ No open trade for {symbol}."
        prices = self._fetch_prices()
        exit_price = self._resolve_price(symbol, prices) or trade["entry_price"]
        return self._do_close(trade, exit_price, "MANUAL_CLOSE")

    # ─── Core loop ─────────────────────────────────────────────────────────
    def _run_loop(self):
        while not self._stop:
            try:
                prices = self._fetch_prices()
                self._update_live_pnl(prices)
                self._check_open_trades(prices)
                self._open_from_signals(prices)
            except Exception as exc:
                logger.warning(f"[PaperTradingEngine] cycle error: {exc}")
            time.sleep(POLL_INTERVAL_SECONDS)

    # ─── Price fetch ────────────────────────────────────────────────────────
    def _fetch_prices(self) -> dict:
        """Build a comprehensive price dict with every possible symbol variant
        so lookups succeed regardless of how the trade's symbol was stored.

        Covers:
          - Display label:  'EUR/GBP', 'BTC'
          - Slash-stripped: 'EURGBP', 'BTC'
          - Uppercase:      'EURGBP', 'BTC'
          - With /USD:      'BTC/USD' for crypto stored that way
          - Base-only:      'BTC' for crypto stored without slash
        """
        prices = {}

        def _register(raw: str, p: float):
            """Register a price under all common symbol variants."""
            if not raw or not p:
                return
            u = raw.upper()
            prices[raw] = p
            prices[u] = p
            prices[u.replace("/", "")] = p
            prices[raw.replace("/", "")] = p
            if "/" not in raw:
                prices[f"{u}/USD"] = p
                prices[f"{u}/USDT"] = p
                prices[f"{u}USD"] = p
                prices[f"{u}USDT"] = p
            else:
                base = raw.split("/")[0].upper()
                _FIAT = {"USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD",
                         "CZK","SEK","NOK","DKK","HKD","SGD","MXN","ZAR",
                         "PLN","TRY","HUF","RON","BGN","RUB","INR","BRL",
                         "XAU","XAG","XPT","XPD"}
                if base not in _FIAT:
                    prices[base] = p

        # 1. Pull from the watchlist cache (covers all ASSETS in CryptoService)
        try:
            for item in self.crypto_service.fetch_top_market_prices():
                p = item.get("price")
                if p is None:
                    continue
                p = float(p)
                for field in ("asset", "name", "ticker", "coin", "symbol"):
                    val = item.get(field)
                    if val:
                        _register(str(val).strip(), p)
        except Exception:
            pass

        # 2. Also directly fetch prices for any open trades whose symbol is
        #    NOT already in the watchlist (e.g. exotic forex pairs, custom syms),
        #    OR whose watchlist price failed the sanity check (e.g. wrong MT5 symbol).
        with self._lock:
            open_syms = [
                t.get("symbol", "")
                for t in self._open_trades.values()
                if not t.get("_reserved") and t.get("symbol")
            ]

        missing = [s for s in open_syms if not self._resolve_price(s, prices)]
        if missing:
            # Try all available providers in order — the free provider (Binance/CoinGecko)
            # will return correct real-world prices even when MT5 gives demo prices.
            all_providers = getattr(self.crypto_service, "_providers", [])
            if not all_providers:
                provider = getattr(self.crypto_service, "_providers", [None])[0]                            if hasattr(self.crypto_service, "_providers") else None
                all_providers = [provider] if provider else []

            for sym in missing:
                px = None
                for provider in all_providers:
                    if provider and hasattr(provider, "get_price"):
                        try:
                            candidate = provider.get_price(sym)
                            if candidate and self._price_is_sane(sym, float(candidate)):
                                px = float(candidate)
                                break
                        except Exception:
                            pass
                # Fallback: try via crypto_service.fetch_market_data (last candle close)
                if not px:
                    try:
                        df = self.crypto_service.fetch_market_data(sym, "1m")
                        if df is not None and not df.empty:
                            candidate = float(df["close"].iloc[-1])
                            if self._price_is_sane(sym, candidate):
                                px = candidate
                    except Exception:
                        pass
                if px:
                    _register(sym, float(px))

        with self._lock:
            self._latest_prices = dict(prices)
        return prices

    # ─── Robust price resolver ─────────────────────────────────────────────
    def _resolve_price(self, sym: str, prices: dict) -> float:
        """Try every known alias of `sym` against `prices` dict.
        Returns 0.0 if genuinely unavailable or if price fails sanity check.
        
        The sanity check catches misconfigured MT5 symbols that return demo/test
        prices (e.g. BTC showing $28 instead of ~$64,000).
        """
        u = sym.upper()
        stripped = u.replace("/", "")
        for key in (
            sym,                                 # exact stored form
            u,                                   # uppercase
            sym.replace("/", ""),                # slash-stripped original case
            stripped,                            # uppercase + stripped (e.g. BTCUSDT)
            f"{stripped}T",                      # BTCUSDT → already handled, but BTCUSD→BTCUSDT
            f"{u}/USD",                          # bare crypto → BTC/USD
            f"{stripped}/USD",                   # stripped → stripped/USD
            f"{u}USD",                           # concatenated: BTCUSD
            f"{u}USDT",                          # concatenated: BTCUSDT
            sym.split("/")[0].upper() if "/" in sym else "",  # base of pair (BTC from BTC/USD)
        ):
            if key and key in prices:
                px = float(prices[key])
                if self._price_is_sane(sym, px):
                    return px
                # Price failed sanity — log once and keep looking for a better source
        return 0.0

    # ─── Crypto price sanity guard ─────────────────────────────────────────
    # Known approximate minimum prices for major coins (well below any realistic
    # real-world low). If a fetched price falls under these thresholds it almost
    # certainly came from a misconfigured MT5 symbol or stale demo data — we
    # reject it so the engine falls back to the free provider instead.
    _CRYPTO_PRICE_FLOORS: dict = {
        "BTC":  5_000.0,   # BTC has never traded below ~$3k in modern era
        "ETH":    100.0,
        "BNB":      5.0,
        "SOL":      0.5,
        "XRP":      0.01,
    }

    def _price_is_sane(self, sym: str, price: float) -> bool:
        """Return False if price looks like a misconfigured/demo value."""
        if price <= 0:
            return False
        base = sym.upper().split("/")[0].replace("USDT","").replace("USD","")
        floor = self._CRYPTO_PRICE_FLOORS.get(base)
        if floor and price < floor:
            logger.warning(
                f"[PaperEngine] Price sanity FAIL for {sym}: got {price:.4f} "
                f"but floor is {floor:.2f}. Likely wrong MT5 symbol or demo data — "
                f"skipping this price. Check Settings → Data Feed → MT5 symbol mapping."
            )
            return False
        return True

    # ─── Live P&L mark-to-market ────────────────────────────────────────────
    def _update_live_pnl(self, prices: dict):
        """
        Mark every open trade to market.

        FIX (2026-07-13): For crypto assets, we now prefer the Binance
        live price (via price_feed.get_price_for_pnl) over whatever the
        active chart provider returned.  This guarantees identical PNL
        behaviour whether the user is connected to TradingView, Binance,
        or MT5 — because MT5 demo accounts can return absurdly low crypto
        prices (e.g. BTC = $28) that make PNL calculations completely wrong.
        """
        # Import here to avoid circular at module load time
        try:
            from services import price_feed as _pf
            _pf_feed = _pf._feed  # module-level singleton
        except Exception:
            _pf_feed = None

        with self._lock:
            for sym, trade in self._open_trades.items():
                if trade.get("_reserved"):
                    continue

                # Try Binance/PriceFeed first for crypto (always real prices)
                price = 0.0
                if _pf_feed is not None:
                    try:
                        p_pnl = _pf_feed.get_price_for_pnl(sym)
                        if p_pnl and self._price_is_sane(sym, p_pnl):
                            price = float(p_pnl)
                    except Exception:
                        pass

                # Fallback: use prices dict built from the active provider
                if not price:
                    price = self._resolve_price(sym, prices)

                if not price:
                    continue

                trade["live_price"] = price   # expose for UI snapshot
                trade["live_pnl"] = lm.compute_pnl(
                    sym, trade["signal_type"],
                    trade["entry_price"], price, trade["size"]
                )

    # ─── Open new trades from signals ──────────────────────────────────────
    def _open_from_signals(self, prices: dict):
        for signal in self.market_scanner.get_signals():
            sym = signal.symbol

            # ── Atomic reservation — prevents TOCTOU race ─────────────────
            # Claim the slot inside the lock BEFORE any DB/network work.
            # If a second thread (or a re-entrant cycle) sneaks in between
            # the check and the open_trade() call it will see the reserved
            # entry and skip, guaranteeing exactly-once opening per symbol.
            with self._lock:
                if sym in self._open_trades:
                    continue
                key = (signal.direction, round(signal.entry_price, 6))
                if self._last_acted_signal.get(sym) == key:
                    continue
                # Reserve the slot with a sentinel value
                self._open_trades[sym] = {"_reserved": True}

            try:
                opened = self._try_open_trade(signal, sym, prices, key)
            except Exception as exc:
                logger.warning(f"[PaperTradingEngine] open failed for {sym}: {exc}")
                opened = False

            if not opened:
                # Release the reservation on failure
                with self._lock:
                    if self._open_trades.get(sym, {}).get("_reserved"):
                        del self._open_trades[sym]

    def _try_open_trade(self, signal, sym: str, prices: dict, key: tuple) -> bool:
        """Perform the actual trade opening after the slot has been reserved."""
        live_price = (
            self._resolve_price(sym, prices)
            or getattr(signal, "current_price", None)
        )
        if not live_price:
            return False

        account = db.get_account()
        balance = account.get("balance", 0.0)
        if balance <= 0:
            return False

        sizing = lm.compute_position(
            sym, balance, self._get_risk_pct(),
            signal.entry_price, signal.stop_loss,
        )
        if sizing["units"] <= 0:
            return False

        opened_at = time.time()
        sig_id = self._get_signal_id(signal)

        trade = {
            "signal_id":   sig_id,
            "symbol":      sym,
            "timeframe":   signal.setup_timeframe,
            "signal_type": signal.direction,
            "entry_price": live_price,
            "stop_loss":   signal.stop_loss,
            "take_profit": signal.take_profit_1,
            "size":        sizing["units"],
            "size_label":  sizing["size_label"],
            "leverage":    sizing["leverage"],
            "asset_class": lm.asset_class_label(sym),
            "opened_at":   opened_at,
            "confidence":  signal.confidence,
            "strategy":    signal.trade_type,
            "live_pnl":    0.0,
        }

        trade_id = db.open_trade(trade)
        trade["id"] = trade_id

        if sig_id:
            try:
                signal_storage.mark_triggered(sig_id, trade_id)
            except Exception:
                pass

        with self._lock:
            self._open_trades[sym] = trade
            self._last_acted_signal[sym] = key

        # Ensure the symbol is registered for live pricing (handles exotic pairs
        # not in the default ASSETS list — e.g. EUR/CZK, APT, custom symbols)
        try:
            self.crypto_service.register_extra_symbol(sym)
        except Exception:
            pass

        nc.push(
            "paper_trade",
            f"📄 Paper Trade Opened: {sym}",
            f"{signal.direction} @ {live_price:.5f}  "
            f"Size: {sizing['size_label']}  Lev: {sizing['leverage']}x",
            data=trade,
        )
        logger.info(
            f"[PaperTradingEngine] OPEN {signal.direction} {sym} "
            f"@ {live_price:.5f}  SL={signal.stop_loss:.5f} "
            f"TP={signal.take_profit_1:.5f}  {sizing['size_label']}"
        )
        return True

    # ─── Check TP/SL on open trades ─────────────────────────────────────────
    def _check_open_trades(self, prices: dict):
        now = time.time()
        for sym, trade in list(self._open_trades.items()):
            if trade.get("_reserved"):
                continue
            price = self._resolve_price(sym, prices)
            if not price:
                continue

            direction = trade["signal_type"]
            hit_tp = (price >= trade["take_profit"]) if direction == "BUY" else (price <= trade["take_profit"])
            hit_sl = (price <= trade["stop_loss"])   if direction == "BUY" else (price >= trade["stop_loss"])

            # ── Scalp timer: auto-exit at market price when timer expires ──
            max_dur = trade.get("_max_duration_s", 0.0)
            if max_dur > 0 and (now - trade["opened_at"]) >= max_dur:
                self._do_close(trade, price, "SCALP_TIMEOUT")
                continue

            if hit_tp or hit_sl:
                exit_price  = trade["take_profit"] if hit_tp else trade["stop_loss"]
                exit_reason = "TAKE_PROFIT"        if hit_tp else "STOP_LOSS"
                self._do_close(trade, exit_price, exit_reason)

    def _do_close(self, trade: dict, exit_price: float, exit_reason: str) -> str:
        """Shared close logic: TP/SL, scalp timer, and manual close."""
        sym       = trade["symbol"]
        direction = trade["signal_type"]

        pnl = lm.compute_pnl(sym, direction, trade["entry_price"], exit_price, trade["size"])
        pnl_pct = 0.0
        if trade["entry_price"]:
            raw_pct = (exit_price - trade["entry_price"]) / trade["entry_price"] * 100.0
            pnl_pct = raw_pct if direction == "BUY" else -raw_pct

        result    = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")
        closed_at = time.time()

        db.close_trade(trade["id"], exit_price, closed_at, pnl, pnl_pct,
                       result, exit_reason, trade["opened_at"])
        db.apply_balance_delta(pnl, "TRADE_PNL", note=f"{sym} {direction} {exit_reason}")

        sig_id = trade.get("signal_id")
        if sig_id:
            try:
                signal_storage.close_signal(sig_id, exit_price, result)
            except Exception:
                pass

        with self._lock:
            self._open_trades.pop(sym, None)
            # Clear dedup so a new signal on the same symbol can open a fresh trade
            self._last_acted_signal.pop(sym, None)

        reason_labels = {
            "TAKE_PROFIT":   "TP hit",
            "STOP_LOSS":     "SL hit",
            "SCALP_TIMEOUT": "Timer expired",
            "MANUAL_CLOSE":  "Closed manually",
        }
        label = reason_labels.get(exit_reason, exit_reason)
        emoji = "✅" if result == "WIN" else "❌"
        nc.push(
            "paper_trade",
            f"{emoji} Trade Closed: {sym}",
            f"{direction}  {label}  P/L: {pnl:+.2f}  {result}",
            data={**trade, "exit_price": exit_price, "pnl": pnl, "result": result},
        )
        logger.info(
            f"[PaperTradingEngine] CLOSE {direction} {sym}"
            f" @ {exit_price:.5f}  ({exit_reason})  P/L {pnl:+.2f}  [{result}]"
        )
        return f"{'✅' if result == 'WIN' else '❌'} {sym} P/L: {pnl:+.2f}  {result}"

    # ─── Helper: resolve signal id ──────────────────────────────────────────
    def _get_signal_id(self, signal) -> Optional[int]:
        """Ensure the signal is in signal_storage and return its id.

        The signal may already exist (upsert_signal is idempotent for the
        same symbol+direction+entry within the TTL window) or it may not
        have been stored yet.  We call upsert_signal here so the signal is
        guaranteed to exist before we link it to the trade, then return the
        resulting id regardless of whether it was newly created or updated.
        """
        try:
            sig_id, _ = signal_storage.upsert_signal(signal)
            return sig_id
        except Exception:
            pass

        # Fallback: search by symbol + direction across all recent statuses
        # (ACTIVE, TRIGGERED — TRIGGERED means another trade already linked it)
        try:
            for status in ("ACTIVE", "TRIGGERED", None):
                kwargs = dict(symbol=signal.symbol, direction=signal.direction, limit=1)
                if status:
                    kwargs["status"] = status
                rows = signal_storage.get_signals(**kwargs)
                if rows:
                    return rows[0]["id"]
        except Exception:
            pass
        return None