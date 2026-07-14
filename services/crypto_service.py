"""
services/crypto_service.py

Live market data service for AI Trader Pro.

FIX (removed MetaTrader 5 dependency):
This module previously required a running, logged-in MetaTrader 5
terminal on the same Windows machine. That meant the app couldn't run
on its own -- users needed MT5 installed, a broker account, and MT5
logged in before any price would show up.

This service now sources every quote and candle from a professional
live market data API (Twelve Data by default, with Finnhub and Alpha
Vantage supported as easy drop-in fallbacks -- see
services/market_data_provider.py and config/settings.py). Users only
need an internet connection and an API key. There are no hardcoded
prices, no demo prices, no cached fallback prices pretending to be
live, and no random-number generators anywhere in this file.

If there's no internet, no API key configured, or the provider can't
price a symbol, callers get back empty candle data / `None` prices
instead of a fabricated number. The UI layer (main_window.py /
watchlist_panel.py) shows "Waiting for Internet..." or
"Data unavailable" in that case rather than a stale-looking value.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from config import settings
from services.market_data_provider import build_provider_chain, has_internet, TTLCache
from services.provider_settings import load_provider
from utils.logger import logger


class CryptoService:
    """
    NOTE: class name kept as `CryptoService` (rather than renamed to
    e.g. `MarketDataService`) purely so every existing import across the
    app (ui/main_window.py, main_mobile.py) keeps working without
    touching unrelated files. Despite the name, this class doesn't talk
    to any single crypto exchange -- it's a thin wrapper around
    whichever live data API is configured in config/settings.py.
    """

    # Every asset the app can display / scan. Kept in sync with
    # ui/coin_selector.py and ui/watchlist_panel.py.
    ASSETS = [
        # Forex Majors
        "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "USD/CHF", "NZD/USD",
        # Forex Crosses
        "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/AUD", "EUR/CAD",
        "AUD/JPY", "GBP/AUD", "GBP/CAD", "CAD/JPY", "NZD/JPY", "CHF/JPY",
        # Metals
        "XAU/USD", "XAG/USD",
        # Crypto (all watchlist symbols — must match watchlist_page.py exactly)
        "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE",
        "AVAX", "MATIC", "DOT", "LINK", "LTC", "UNI", "ATOM",
        "TRX", "TON", "BCH", "APT", "ARB", "OP", "INJ",
        "SUI", "NEAR", "FTM", "ALGO", "VET", "AAVE", "MKR",
        "LDO", "RUNE", "HBAR",
        # Indices
        "US30", "NAS100", "SPX500",
    ]

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = TTLCache()
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="market-data")

        self._providers = self._init_providers()
        self._last_status_reason = "Waiting for Internet..." if not has_internet() else "Data unavailable"

        # FIX: round-robin cursor into ASSETS so every refresh cycle
        # starts from a different symbol. Combined with the credit-aware
        # budget cap below, this guarantees every asset eventually gets
        # refreshed instead of the same first few symbols always winning
        # the available credit budget while the rest starve forever.
        self._watchlist_rr_offset = 0

        # Background refresher is now explicitly started via start()
        # so it does not block or spin up during application initialization.
        self._bg_stop = False
        self._bg_thread = None

    def start(self):
        """
        Explicitly start the background workers.
        Call this after the UI is fully responsive.
        """
        if self._bg_thread is None:
            self._bg_stop = False
            self._bg_thread = threading.Thread(target=self._background_refresh_loop, daemon=True)
            self._bg_thread.start()
            logger.info("[CryptoService] Background refresh loop started.")

    # ------------------------------------------------------------------
    # Provider selection -- wired to ui/settings_panel.py via
    # services/provider_settings.py (config.json)
    # ------------------------------------------------------------------
    def _init_providers(self):
        """Uses whatever the user picked in Settings (persisted to
        config.json by services/provider_settings.save_settings) as the
        active data source. Falls back to the legacy .env-based provider
        chain (Twelve Data -> Finnhub -> Alpha Vantage) only if reading
        that saved preference fails outright -- so a missing/corrupted
        config.json can never leave the app with zero data sources."""
        try:
            return [load_provider()]
        except Exception as e:
            logger.warning(f"[CryptoService] load_provider() failed ({e}) -- falling back to .env provider chain.")
            return build_provider_chain()

    def set_provider(self, provider) -> None:
        """Hot-swaps the active data source at runtime -- e.g. called
        from ui/settings_panel.py's on_saved callback right after the
        user hits Save, so the change takes effect immediately instead
        of requiring an app restart. Clears every cached quote/candle so
        nothing left over from the old provider can be shown as if it
        came from the new one."""
        with self._lock:
            self._providers = [provider]
            self._watchlist_rr_offset = 0
        self._cache.clear()
        logger.info(f"[CryptoService] Data source switched to {provider.display_name}.")

    # ------------------------------------------------------------------
    # Connection / provider status
    # ------------------------------------------------------------------
    def is_connected(self) -> bool:
        return bool(self._providers) and has_internet()

    def get_connection_status(self) -> dict:
        """Broker/provider name + connection state for the UI status bar.
        Keys match what ui/main_window.py already expects."""
        if not self._providers:
            return {
                "connected": False, "broker": "", "server": "",
                "reason": "No data provider configured -- pick one in Settings or add an API key in .env",
            }

        if not has_internet():
            return {"connected": False, "broker": "", "server": "", "reason": "Waiting for Internet..."}

        provider = self._providers[0]

        # FIX: the app can now select providers that don't need an API
        # key at all (Default/Free) or that depend on something local
        # (an MT5 terminal actually running) -- so "a provider object
        # exists" no longer means "it can actually price anything right
        # now". Check is_configured() so the status bar doesn't claim
        # e.g. "Connected: MetaTrader 5" when no terminal is running.
        if not provider.is_configured():
            return {
                "connected": False, "broker": provider.display_name, "server": "",
                "reason": f"{provider.display_name} selected but not ready (missing library, "
                          f"no MT5 terminal running, or no API key set in Settings).",
            }

        return {
            "connected": True,
            "broker": provider.display_name,
            "server": "Live Market Data API",
        }

    # ------------------------------------------------------------------
    # Background cache warmer
    # ------------------------------------------------------------------
    def _background_refresh_loop(self):
        while not self._bg_stop:
            try:
                self._refresh_watchlist_cache()
            except Exception as e:
                logger.warning(f"[CryptoService] background refresh error: {e}")
            time.sleep(max(5, settings.WATCHLIST_REFRESH_SECONDS))

    def shutdown(self):
        self._bg_stop = True
        self._executor.shutdown(wait=False)
        for provider in self._providers:
            shutdown_fn = getattr(provider, "shutdown", None)
            if callable(shutdown_fn):
                try:
                    shutdown_fn()
                except Exception as e:
                    logger.warning(f"[CryptoService] {provider.display_name} shutdown() failed: {e}")

    # ------------------------------------------------------------------
    # Quotes / watchlist
    # ------------------------------------------------------------------
    def _refresh_watchlist_cache(self):
        if not self._providers:
            return

        # MT5 is a local COM bridge — skip the internet gate for it
        _is_local = getattr(self._providers[0], "name", "") in ("mt5",)
        if not _is_local and not has_internet():
            return

        # Build asset list: standard ASSETS + any extra symbols registered at runtime
        # (e.g. exotic forex pairs from open paper trades)
        extra = list(getattr(self, "_extra_symbols", set()))
        assets = self.ASSETS + [s for s in extra if s not in self.ASSETS]
        n = len(assets)
        if not n:
            return

        offset = self._watchlist_rr_offset % n
        rotated = assets[offset:] + assets[:offset]
        slice_size = max(1, min(n, settings.WATCHLIST_MAX_SYMBOLS_PER_CYCLE))
        remaining = rotated[:slice_size]
        self._watchlist_rr_offset = (offset + slice_size) % n

        for provider in self._providers:
            if not remaining:
                break
            try:
                quotes = provider.get_quotes(remaining)
            except Exception as e:
                logger.warning(f"[{provider.display_name}] get_quotes failed: {e}")
                continue

            still_missing = []
            for label in remaining:
                data = quotes.get(label)
                if data:
                    self._cache.set(f"quote:{label}", {**data, "provider": provider.display_name})
                else:
                    still_missing.append(label)
            remaining = still_missing  # only unresolved assets are tried on the next (fallback) provider

    def fetch_top_market_prices(self) -> list:
        """Live price for every asset in the watchlist, read from cache
        (kept warm by the background refresher). Any asset that can't
        currently be priced gets price/bid/ask = None (never 0.0-as-fake)
        so the UI can render "Waiting for Internet..." / "Data
        unavailable" for that row instead."""
        online = has_internet()
        results = []

        # Include any extra symbols registered at runtime (e.g. open trade symbols
        # not in the default ASSETS list)
        all_labels = list(self.ASSETS)
        extras = [s for s in getattr(self, "_extra_symbols", set()) if s not in self.ASSETS]
        all_labels.extend(extras)

        for label in all_labels:
            clean = label.replace("/", "")
            entry = {
                "asset": label, "name": label, "ticker": label, "coin": label,
                "symbol": clean, "connected": False,
                "price": None, "bid": None, "ask": None, "spread": None,
                "value": None, "close": None, "status_message": None,
            }

            cached = self._cache.get_fresh(f"quote:{label}", settings.WATCHLIST_REFRESH_SECONDS * 2)
            if cached is None:
                cached = self._cache.get_stale(f"quote:{label}", settings.STALE_DATA_GRACE_SECONDS)

            if cached:
                entry.update({
                    "connected": True,
                    "price": cached["price"], "bid": cached["bid"], "ask": cached["ask"],
                    "spread": (cached["ask"] - cached["bid"]) if cached["bid"] and cached["ask"] else 0.0,
                    "value": cached["price"], "close": cached["price"],
                })
            else:
                entry["status_message"] = "Waiting for Internet..." if not online else "Data unavailable"

            results.append(entry)

        return results

    def register_extra_symbol(self, symbol: str) -> None:
        """Register a symbol not in ASSETS so it gets included in price fetches.
        Called by PaperTradingEngine when a trade is opened on an exotic pair."""
        if not hasattr(self, "_extra_symbols"):
            self._extra_symbols = set()
        if symbol and symbol not in self.ASSETS:
            self._extra_symbols.add(symbol)
            # Kick off an immediate fetch for this symbol in the background
            import threading as _t
            _t.Thread(
                target=self._fetch_one_symbol,
                args=(symbol,),
                daemon=True,
                name=f"fetch-{symbol}",
            ).start()

    def _fetch_one_symbol(self, symbol: str) -> None:
        """Fetch and cache a single symbol's quote immediately."""
        if not self._providers or not has_internet():
            return
        for provider in self._providers:
            try:
                quotes = provider.get_quotes([symbol])
                data = quotes.get(symbol)
                if data and data.get("price"):
                    self._cache.set(f"quote:{symbol}", {
                        **data, "provider": provider.display_name
                    })
                    return
            except Exception:
                continue

    # ------------------------------------------------------------------
    # OHLC candles for the main chart
    # ------------------------------------------------------------------
    def fetch_market_data(self, asset: str, timeframe: str) -> pd.DataFrame:
        """Live OHLCV candles for `asset`/`timeframe`, sourced from the
        configured market data API and cached for CHART_REFRESH_SECONDS
        so rapid UI polling never re-hits the network or blows through
        the provider's rate limit. Returns an empty (but correctly
        columned) DataFrame if no provider is connected or none of them
        offer this symbol -- callers already handle an empty frame."""
        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        cache_key = f"candles:{asset}:{timeframe}"

        # MT5 is a local COM bridge — use a much shorter cache TTL (2s vs 20s)
        # so the chart reflects live broker ticks quickly.
        _is_local_provider = bool(self._providers) and getattr(self._providers[0], "name", "") in ("mt5",)
        _chart_ttl = 2 if _is_local_provider else settings.CHART_REFRESH_SECONDS

        fresh = self._cache.get_fresh(cache_key, _chart_ttl)
        if fresh is not None:
            return fresh.copy()

        if not self._providers:
            stale = self._cache.get_stale(cache_key, settings.STALE_DATA_GRACE_SECONDS)
            return stale.copy() if stale is not None else empty

        # MT5 is a local COM bridge — it works without an internet connection.
        # Only apply the internet gate for cloud-based providers.
        if not _is_local_provider and not has_internet():
            stale = self._cache.get_stale(cache_key, settings.STALE_DATA_GRACE_SECONDS)
            return stale.copy() if stale is not None else empty

        for provider in self._providers:
            try:
                df = provider.get_candles(asset, timeframe, outputsize=settings.MAX_CANDLES)
            except Exception as e:
                logger.warning(f"[{provider.display_name}] get_candles failed for {asset}: {e}")
                df = None

            if df is not None and not df.empty:
                self._cache.set(cache_key, df)
                return df.copy()

        # Every configured provider failed / didn't offer this symbol --
        # fall back to the last real candles we successfully fetched
        # (if recent enough), otherwise report unavailable.
        stale = self._cache.get_stale(cache_key, settings.STALE_DATA_GRACE_SECONDS)
        return stale.copy() if stale is not None else empty

    def fetch_live_news(self) -> list:
        """Live forex/macro news from Finnhub's News API -- each item
        carries a real source, a real publish timestamp, and a link back
        to the original article. No placeholder/fabricated headlines are
        ever returned: with no key configured, or if the request fails,
        this returns an empty list and the panel shows nothing rather
        than pretending. Get a free key at https://finnhub.io and set
        FINNHUB_API_KEY in your .env (see config/settings.py)."""
        cache_key = "news:forex"
        fresh = self._cache.get_fresh(cache_key, settings.NEWS_REFRESH_SECONDS)
        if fresh is not None:
            return fresh

        if not settings.FINNHUB_API_KEY:
            return []

        if not has_internet():
            stale = self._cache.get_stale(cache_key, settings.STALE_DATA_GRACE_SECONDS)
            return stale if stale is not None else []

        try:
            resp = requests.get(
                "https://finnhub.io/api/v1/news",
                params={"category": "forex", "token": settings.FINNHUB_API_KEY},
                timeout=8,
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            logger.warning(f"[CryptoService] fetch_live_news failed: {e}")
            stale = self._cache.get_stale(cache_key, settings.STALE_DATA_GRACE_SECONDS)
            return stale if stale is not None else []

        if not isinstance(raw, list):
            return []

        now = time.time()
        # High-impact macro keywords -- a lightweight heuristic since
        # Finnhub's general news feed doesn't grade impact itself.
        high_impact_kw = ("FED", "FOMC", "RATE", "CPI", "INFLATION", "GDP", "NFP",
                           "NONFARM", "UNEMPLOYMENT", "CENTRAL BANK", "ECB", "BOE", "BOJ")

        news_list = []
        for item in raw[:25]:
            headline = (item.get("headline") or "").strip()
            url = item.get("url") or ""
            if not headline or not url:
                continue  # never show an entry with no real source to link back to

            ts = item.get("datetime")
            if ts:
                mins = max(0, int((now - ts) / 60))
                if mins < 1:
                    age = "just now"
                elif mins < 60:
                    age = f"{mins} min{'s' if mins != 1 else ''} ago"
                else:
                    hrs = mins // 60
                    age = f"{hrs}h ago" if hrs < 24 else f"{hrs // 24}d ago"
            else:
                age = "--"

            impact = "HIGH" if any(k in headline.upper() for k in high_impact_kw) else "MED"

            news_list.append({
                "title": headline,
                "time": age,
                "impact": impact,
                "source": item.get("source") or "Finnhub",
                "description": (item.get("summary") or "").strip(),
                "url": url,
                "currency": "FX",
            })

        if news_list:
            self._cache.set(cache_key, news_list)
        return news_list