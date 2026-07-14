"""
services/mt5_provider.py
==========================
Optional MetaTrader 5 data source -- ONLY instantiated if the user
explicitly picks "MT5" in Settings. The app's default, out-of-the-box
experience is UniversalFreeProvider (services/universal_free_provider.py);
this file changes nothing about that.

Requires the `MetaTrader5` package AND a running, logged-in MT5
terminal on the same machine -- both are the user's own choice/setup,
not a hidden app requirement. If either isn't available, every method
here fails gracefully (returns None / "Data unavailable") rather than
crashing the app or fabricating a price, same as every other provider.

FIXES APPLIED (2026-07-13):
  1. symbol_select() called before symbol_info_tick() and copy_rates_from_pos()
     so symbols not yet visible in MT5 Market Watch are auto-enabled, which
     was the root cause of "MT5 connected but no chart/quote data loading".
  2. on_init_complete callback: callers (e.g. MainWindow) can register a
     function to be called the moment MT5 finishes its async handshake, so
     the pipeline fires immediately instead of waiting for the next 2-second
     tick.
  3. Improved per-symbol logging: logs reason when copy_rates_from_pos returns
     None (symbol not found vs truly no data) to aid debugging.
"""

from typing import Callable, Dict, List, Optional
import threading

import pandas as pd

from services.market_data_provider import MarketDataProvider, RateLimiter
from utils.logger import logger

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
    _MT5_IMPORT_ERROR = None
except Exception as e:
    _MT5_AVAILABLE = False
    mt5 = None
    _MT5_IMPORT_ERROR = f"{type(e).__name__}: {e}"

_MT5_TIMEFRAME_MAP = {
    "1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4", "1d": "TIMEFRAME_D1",
}


class MT5Provider(MarketDataProvider):
    """Reads live prices/candles from a locally running MetaTrader 5
    terminal. Symbol labels are passed straight through to MT5 (e.g.
    "EURUSD", "XAUUSD") -- rename via `symbol_overrides` if your
    broker uses different tickers (e.g. "EURUSD.m")."""

    name = "mt5"
    display_name = "MetaTrader 5"

    # Candle data TTL: MT5 candles don't change faster than the timeframe itself;
    # caching prevents redundant COM calls that cause UI lag spikes.
    _CANDLE_TTL = 0.5   # seconds
    _QUOTE_TTL  = 0.3   # seconds

    def __init__(self, symbol_overrides: Optional[Dict[str, str]] = None):
        super().__init__(api_key=None, quote_limiter=RateLimiter(120, 60), candle_limiter=RateLimiter(120, 60))
        self._symbol_overrides = symbol_overrides or {}
        self._init_lock = threading.Lock()
        self._initialized = False
        self._logged_missing_package = False

        self._candle_cache: dict = {}
        self._quote_cache:  dict = {}
        self._cache_lock = threading.Lock()
        self._configured_cache: Optional[bool] = None
        self._configured_cache_ts: float = 0.0
        self._CONFIGURED_CACHE_TTL = 5.0

        # --- FIX 2: Callback fired once when MT5 init succeeds ---
        # Register via set_on_init_complete(fn). MainWindow uses this
        # to trigger_pipeline() immediately rather than waiting 2 s.
        self._on_init_complete: Optional[Callable] = None

        # Track which symbols we've already selected to avoid redundant COM calls
        self._selected_symbols: set = set()
        self._selected_lock = threading.Lock()

    def set_on_init_complete(self, callback: Callable) -> None:
        """Register a zero-argument callback to be called once MT5 initialises
        successfully. Safe to call before or after init completes."""
        self._on_init_complete = callback
        # If already initialised, fire immediately
        if self._initialized and callback:
            try:
                callback()
            except Exception as e:
                logger.warning(f"[MT5Provider] on_init_complete callback error: {e}")

    def connect(self) -> bool:
        """
        Explicitly triggers the MT5 connection.
        Must be called by the application controller before data requests.
        """
        if not _MT5_AVAILABLE:
            if not self._logged_missing_package:
                logger.warning(
                    f"[MT5Provider] MetaTrader5 package unavailable ({_MT5_IMPORT_ERROR}) "
                    f"-- run `pip install MetaTrader5`."
                )
                self._logged_missing_package = True
            return False

        if self._initialized:
            return True

        logger.info("[MT5Provider] Connecting to MT5 terminal...")
        with self._init_lock:
            try:
                success = bool(mt5.initialize())
                if success:
                    self._initialized = True
                    logger.info("[MT5Provider] MT5 terminal connected successfully.")
                else:
                    logger.warning(f"[MT5Provider] mt5.initialize() failed: {mt5.last_error()}")
                    self._initialized = False
            except Exception as e:
                logger.critical(f"[MT5Provider] Connection failure: {e}")
                self._initialized = False
            finally:
                import time
                self._configured_cache = self._initialized
                self._configured_cache_ts = time.time()

        if self._initialized and self._on_init_complete:
            try:
                logger.info("[MT5Provider] Firing on_init_complete callback to refresh pipeline.")
                self._on_init_complete()
            except Exception as e:
                logger.warning(f"[MT5Provider] on_init_complete callback error: {e}")

        return self._initialized

    def _symbol_for(self, label: str) -> str:
        return self._symbol_overrides.get(label, label.replace("/", ""))

    # ------------------------------------------------------------------
    # FIX 1: Ensure symbol is visible in Market Watch before any data call
    # ------------------------------------------------------------------
    def _ensure_symbol_selected(self, mt5_symbol: str) -> bool:
        """
        Call mt5.symbol_select(symbol, True) if we haven't done so yet for
        this symbol in this session. MT5's copy_rates_from_pos() and
        symbol_info_tick() both silently return None for symbols that are not
        currently visible in Market Watch -- this was the root cause of the
        "connected but no data" bug.

        Returns True if the symbol is available, False if unknown to the broker.
        """
        with self._selected_lock:
            if mt5_symbol in self._selected_symbols:
                return True  # already confirmed available this session

        try:
            info = mt5.symbol_info(mt5_symbol)
            if info is None:
                # Symbol not known to this broker at all
                logger.warning(
                    f"[MT5Provider] Symbol '{mt5_symbol}' not found on broker -- "
                    f"check symbol_overrides in data_feed_factory.py "
                    f"(e.g. your broker may use '{mt5_symbol}m' or '{mt5_symbol}.')."
                )
                return False

            if not info.visible:
                # Known but hidden in Market Watch -- make it visible
                ok = mt5.symbol_select(mt5_symbol, True)
                if not ok:
                    logger.warning(
                        f"[MT5Provider] symbol_select('{mt5_symbol}', True) failed: "
                        f"{mt5.last_error()} -- data may still be unavailable."
                    )
                else:
                    logger.info(f"[MT5Provider] Auto-added '{mt5_symbol}' to Market Watch.")

            with self._selected_lock:
                self._selected_symbols.add(mt5_symbol)
            return True

        except Exception as e:
            logger.warning(f"[MT5Provider] _ensure_symbol_selected({mt5_symbol}) error: {e}")
            return False

    def _ensure_initialized(self) -> bool:
        """
        Checks initialization state instantly.
        No longer spawns background threads automatically.
        """
        if not _MT5_AVAILABLE:
            if not self._logged_missing_package:
                logger.warning(
                    f"[MT5Provider] MetaTrader5 package unavailable ({_MT5_IMPORT_ERROR}) "
                    f"-- run `pip install MetaTrader5`."
                )
                self._logged_missing_package = True
            return False

        return self._initialized

    def is_configured(self) -> bool:
        import time as _t
        now = _t.time()
        if self._configured_cache is not None and now - self._configured_cache_ts < self._CONFIGURED_CACHE_TTL:
            return self._configured_cache
        result = self._ensure_initialized()
        self._configured_cache = result
        self._configured_cache_ts = now
        return result

    def get_quotes(self, labels: List[str]) -> Dict[str, Optional[dict]]:
        import time as _time
        now = _time.time()
        result = {label: None for label in labels}

        if not self._ensure_initialized():
            # Return cached quotes when terminal is temporarily unavailable
            with self._cache_lock:
                for label in labels:
                    entry = self._quote_cache.get(label)
                    if entry and now - entry[0] < 30.0:  # stale ok for 30s on disconnect
                        result[label] = entry[1]
            return result

        if not self.quote_limiter.allow(cost=max(1, len(labels))):
            # Rate limited -- serve from cache
            with self._cache_lock:
                for label in labels:
                    entry = self._quote_cache.get(label)
                    if entry:
                        result[label] = entry[1]
            return result

        for label in labels:
            # Check per-symbol quote TTL first
            with self._cache_lock:
                entry = self._quote_cache.get(label)
                if entry and now - entry[0] < self._QUOTE_TTL:
                    result[label] = entry[1]
                    continue

            mt5_symbol = self._symbol_for(label)

            # FIX 1: Ensure symbol is in Market Watch before requesting tick
            if not self._ensure_symbol_selected(mt5_symbol):
                continue  # broker doesn't have this symbol -- skip silently

            try:
                tick = mt5.symbol_info_tick(mt5_symbol)
                if tick is None:
                    logger.debug(
                        f"[MT5Provider] symbol_info_tick('{mt5_symbol}') returned None "
                        f"-- no tick data yet (market may be closed or symbol just added)."
                    )
                    # Serve stale cache if available
                    with self._cache_lock:
                        entry = self._quote_cache.get(label)
                        if entry:
                            result[label] = entry[1]
                    continue
                q = {
                    "price": float(tick.last or tick.bid or tick.ask),
                    "bid": float(tick.bid), "ask": float(tick.ask),
                    "time": float(tick.time),
                }
                result[label] = q
                with self._cache_lock:
                    self._quote_cache[label] = (now, q)
            except Exception as e:
                logger.warning(f"[MT5Provider] symbol_info_tick({mt5_symbol}) failed: {e}")
                # Serve stale cache on error
                with self._cache_lock:
                    entry = self._quote_cache.get(label)
                    if entry:
                        result[label] = entry[1]
        return result

    def get_candles(self, label: str, timeframe: str, outputsize: int = 300) -> Optional[pd.DataFrame]:
        if not self._ensure_initialized():
            return None
        tf_attr = _MT5_TIMEFRAME_MAP.get(timeframe)
        if not tf_attr:
            return None

        cache_key = f"{label}:{timeframe}:{outputsize}"
        now = __import__('time').time()

        # Return cached candles if still fresh (avoids COM lag on every tick)
        with self._cache_lock:
            entry = self._candle_cache.get(cache_key)
            if entry and now - entry[0] < self._CANDLE_TTL:
                return entry[1].copy()

        if not self.candle_limiter.allow():
            # Rate limited -- return stale cache if available rather than None
            with self._cache_lock:
                entry = self._candle_cache.get(cache_key)
                if entry:
                    return entry[1].copy()
            return None

        mt5_symbol = self._symbol_for(label)

        # FIX 1: Ensure symbol is in Market Watch before requesting candles
        if not self._ensure_symbol_selected(mt5_symbol):
            # Return stale cache if available rather than blanking the chart
            with self._cache_lock:
                entry = self._candle_cache.get(cache_key)
                if entry:
                    return entry[1].copy()
            return None

        try:
            rates = mt5.copy_rates_from_pos(mt5_symbol, getattr(mt5, tf_attr), 0, outputsize)
            if rates is None or len(rates) == 0:
                err = mt5.last_error()
                logger.warning(
                    f"[MT5Provider] copy_rates_from_pos('{mt5_symbol}', {timeframe}) "
                    f"returned no data. MT5 error: {err}. "
                    f"Possible causes: market closed, symbol has no history on your broker, "
                    f"or broker name differs (check symbol_overrides in data_feed_factory.py)."
                )
                # Return stale cache so the chart doesn't blank out during closed hours
                with self._cache_lock:
                    entry = self._candle_cache.get(cache_key)
                    if entry:
                        return entry[1].copy()
                return None

            df = pd.DataFrame(rates)
            df["timestamp"] = pd.to_datetime(df["time"], unit="s")
            df = df.rename(columns={"tick_volume": "volume"})
            df = df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp").reset_index(drop=True)
            with self._cache_lock:
                self._candle_cache[cache_key] = (now, df)
            return df.copy()

        except Exception as e:
            logger.warning(f"[MT5Provider] copy_rates_from_pos({mt5_symbol}) failed: {e}")
            # Return stale cache on error -- better than blanking the chart
            with self._cache_lock:
                entry = self._candle_cache.get(cache_key)
                if entry:
                    return entry[1].copy()
            return None

    def shutdown(self):
        with self._cache_lock:
            self._candle_cache.clear()
            self._quote_cache.clear()
        with self._selected_lock:
            self._selected_symbols.clear()
        if _MT5_AVAILABLE and self._initialized:
            try:
                mt5.shutdown()
            except Exception:
                pass
            self._initialized = False