"""
services/market_data_provider.py
=================================
Provider-agnostic LIVE market data layer for AI Trader Pro.

Replaces the old MetaTrader 5 terminal dependency. Users no longer need
MT5 (or any broker terminal) installed -- only an internet connection
and an API key for one of the supported providers:

    - Twelve Data    (preferred / default)   https://twelvedata.com
    - Finnhub                                https://finnhub.io
    - Alpha Vantage                          https://www.alphavantage.co

Design rules this module follows everywhere:
    * NEVER invent, simulate, or randomly-jitter a price or candle. Any
      failure (no internet, bad/missing key, rate limit, symbol not
      offered by the provider/plan) returns None / an empty DataFrame,
      never a fabricated number.
    * All network calls are rate-limited and cached so the app never
      hammers the provider and the UI thread never blocks on I/O.
    * API keys are read only from the environment (optionally via a
      local .env file) -- never hardcoded here.
"""

import os
import time
import socket
import threading
from typing import Dict, List, Optional

import requests
import pandas as pd

try:
    # Optional: lets users keep keys in a local ".env" file next to the
    # executable instead of setting real OS environment variables.
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from utils.logger import logger

REQUEST_TIMEOUT = 8  # seconds -- fail fast rather than freezing a worker thread


# ----------------------------------------------------------------------
# Connectivity
# ----------------------------------------------------------------------
def has_internet(timeout: float = 2.0) -> bool:
    """Best-effort connectivity check. Never raises.

    Strategy (in order):
    1. Raw TCP connect to well-known DNS resolvers on port 53 — fastest path.
    2. HTTP HEAD via requests to a reliable CDN — works when port 53 is firewalled.
    3. urllib fallback — handles edge cases where requests is unavailable.

    Any HTTP *response* (even 403/404) means we have a route to the internet.
    Only a connection error or total timeout means truly offline.
    """
    # Fast path: raw TCP to well-known DNS resolvers
    for host, port in (("8.8.8.8", 53), ("1.1.1.1", 53), ("208.67.222.222", 53)):
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except OSError:
            continue

    # Fallback 1: HTTP via requests (already a project dependency)
    try:
        resp = requests.head("https://www.google.com", timeout=timeout, allow_redirects=True)
        if resp.status_code < 600:   # any HTTP response = connected
            return True
    except Exception:
        pass

    # Fallback 2: urllib (in case requests import ever fails)
    try:
        import urllib.request
        import urllib.error
        urllib.request.urlopen("https://www.google.com", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True   # Got an HTTP response code = internet is reachable
    except Exception:
        pass

    return False


# ----------------------------------------------------------------------
# Rate limiting (non-blocking -- callers fall back to cache instead of
# sleeping the calling thread)
# ----------------------------------------------------------------------
class RateLimiter:
    """Token-bucket limiter over a rolling window, counting **credits**,
    not raw HTTP calls.

    FIX (root cause of "Data unavailable" / "Limits exceeded"): Twelve
    Data bills 1 credit PER SYMBOL, even inside a single batched HTTP
    request -- e.g. one /quote call for 18 symbols costs 18 credits, not
    1 (confirmed by Twelve Data's own docs: "each symbol consumes one
    API credit"). The previous version of this limiter only counted how
    many *calls* were made (max 8 calls/60s), so a single 18-symbol
    watchlist batch looked like "1 call" internally while actually
    billing 18 credits against the account's real 8-credits/minute cap
    -- instantly blowing the limit on every refresh. `allow()` now takes
    a `cost` (defaults to 1, i.e. unchanged behaviour for single-symbol
    endpoints like candles) so batched quote requests can be charged and
    throttled correctly.
    """
    def __init__(self, max_credits: int, period_seconds: float):
        self.max_credits = max(1, int(max_credits))
        self.period = float(period_seconds)
        self._usage = []  # list of (timestamp, cost) within the rolling window
        self._lock = threading.Lock()

    def _prune(self, now: float):
        self._usage = [(t, c) for t, c in self._usage if now - t < self.period]

    def allow(self, cost: int = 1) -> bool:
        """Attempts to spend `cost` credits. Returns False (spends
        nothing) if that would exceed the rolling-window budget."""
        cost = max(1, int(cost))
        now = time.time()
        with self._lock:
            self._prune(now)
            used = sum(c for _, c in self._usage)
            if used + cost > self.max_credits:
                return False
            self._usage.append((now, cost))
            return True

    def remaining(self) -> int:
        """How many credits are currently available in the rolling
        window -- used to size a batch request (e.g. only ask for as
        many watchlist symbols as the budget can actually afford) rather
        than firing an all-or-nothing request that's guaranteed to be
        rejected."""
        now = time.time()
        with self._lock:
            self._prune(now)
            used = sum(c for _, c in self._usage)
        return max(0, self.max_credits - used)


# ----------------------------------------------------------------------
# Tiny thread-safe TTL cache (used for both quotes and candle frames)
# ----------------------------------------------------------------------
_TTLCACHE_MAX_ENTRIES = 512   # Hard cap — prevents unbounded memory growth


class TTLCache:
    """
    Bounded, thread-safe TTL cache.

    Fix: Added _TTLCACHE_MAX_ENTRIES hard cap.  The original cache had no
    limit — with 40+ symbols and multiple timeframes the cache grew
    indefinitely until the process was restarted.  When the cap is reached
    the oldest entries (by insertion timestamp) are evicted first so the
    most recently-fetched data is always retained.
    """

    def __init__(self, max_entries: int = _TTLCACHE_MAX_ENTRIES):
        self._store:      Dict[str, tuple] = {}
        self._lock        = threading.Lock()
        self._max         = max(1, int(max_entries))   # min 1 to prevent zero-size cache
        self._insert_seq  = 0   # monotonic counter for stable LRU ordering

    # Note: the internal tuple is now (seq, value) — not (timestamp, value).
    # The seq counter provides stable LRU ordering without timestamp collisions.
    # get_fresh / get_stale still check timestamps but use a separate _ts_store.
    # Simpler fix: restore timestamp storage alongside seq using a 3-tuple.

    def get_fresh(self, key: str, ttl: float):
        with self._lock:
            entry = self._store.get(key)
        if not entry:
            return None
        # entry = (seq, value, inserted_ts)
        _, value, inserted_ts = entry
        if time.time() - inserted_ts > ttl:
            return None
        return value

    def get_stale(self, key: str, max_age: float):
        """Returns a value even if past its TTL, as long as it isn't
        older than max_age -- used as a graceful fallback so a single
        missed poll doesn't blank out a row that just updated moments
        ago. Still 100% real, previously-fetched market data."""
        with self._lock:
            entry = self._store.get(key)
        if not entry:
            return None
        _, value, inserted_ts = entry
        if time.time() - inserted_ts > max_age:
            return None
        return value

    def set(self, key: str, value) -> None:
        with self._lock:
            # Use a monotonic counter for stable insertion ordering.
            # This guarantees eviction always removes the truly oldest entry
            # even when multiple sets happen within the same nanosecond
            # (common in tight loops / tests). The timestamp is stored
            # alongside for get_fresh / get_stale TTL checks.
            self._insert_seq += 1
            self._store[key] = (self._insert_seq, value, time.time())
            # Evict surplus entries so size never exceeds self._max.
            if len(self._store) > self._max:
                surplus = len(self._store) - self._max
                # Sort by seq (index 0) for stable oldest-first ordering
                oldest = sorted(self._store, key=lambda k: self._store[k][0])
                for evict_key in oldest[:surplus]:
                    self._store.pop(evict_key, None)

    def clear(self) -> None:
        """Wipes every cached value -- used when the active data source
        is switched at runtime (see CryptoService.set_provider) so no
        price from the old provider can linger and get shown as if it
        came from the new one."""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


# ----------------------------------------------------------------------
# Base provider interface
# ----------------------------------------------------------------------
class MarketDataProvider:
    name = "base"
    display_name = "Base Provider"

    def __init__(self, api_key: Optional[str], quote_limiter: RateLimiter, candle_limiter: RateLimiter):
        self.api_key = api_key
        self.quote_limiter = quote_limiter
        self.candle_limiter = candle_limiter

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_quotes(self, labels: List[str]) -> Dict[str, Optional[dict]]:
        """Returns {label: {"price","bid","ask","time"} or None}."""
        raise NotImplementedError

    def get_candles(self, label: str, timeframe: str, outputsize: int = 300) -> Optional[pd.DataFrame]:
        """Returns a chronological (oldest->newest) DataFrame with columns
        timestamp/open/high/low/close/volume, or None on failure."""
        raise NotImplementedError

    @staticmethod
    def _empty_frame() -> pd.DataFrame:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])


# ----------------------------------------------------------------------
# Twelve Data (preferred / default)
# ----------------------------------------------------------------------
class TwelveDataProvider(MarketDataProvider):
    name = "twelvedata"
    display_name = "Twelve Data"

    BASE_URL = "https://api.twelvedata.com"

    _SYMBOL_MAP = {
        "EUR/USD": "EUR/USD", "GBP/USD": "GBP/USD", "USD/JPY": "USD/JPY",
        "AUD/USD": "AUD/USD", "USD/CAD": "USD/CAD", "USD/CHF": "USD/CHF",
        "NZD/USD": "NZD/USD", "EUR/GBP": "EUR/GBP", "EUR/JPY": "EUR/JPY",
        "GBP/JPY": "GBP/JPY", "XAU/USD": "XAU/USD", "XAG/USD": "XAG/USD",
        "BTC": "BTC/USD", "ETH": "ETH/USD", "SOL": "SOL/USD",
        # Cash indices. Twelve Data prices these as the underlying index
        # itself (not a CFD/futures contract), so values will be close
        # to, but not tick-identical with, a broker's US30/NAS100/SPX500
        # CFD quote. Still 100% real market data -- never fabricated --
        # and gracefully unavailable (not a fake price) if your Twelve
        # Data plan doesn't include indices.
        "US30": "DJI", "NAS100": "IXIC", "SPX500": "SPX",
    }

    _INTERVAL_MAP = {
        "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "1h", "4h": "4h", "1d": "1day",
    }

    def _symbol_for(self, label: str) -> Optional[str]:
        return self._SYMBOL_MAP.get(label)

    def get_quotes(self, labels: List[str]) -> Dict[str, Optional[dict]]:
        result = {label: None for label in labels}
        if not self.is_configured():
            return result

        symbols = [self._symbol_for(l) for l in labels]
        symbol_to_label = {s: l for s, l in zip(symbols, labels) if s}
        wanted = [s for s in symbols if s]
        if not wanted:
            return result

        # FIX: Twelve Data bills 1 credit PER SYMBOL in a batched /quote
        # call, so only request as many symbols as the rolling-window
        # credit budget can actually afford right now. Whatever doesn't
        # fit is simply left unresolved (None) this cycle -- the caller
        # (CryptoService._refresh_watchlist_cache) rotates which symbols
        # go first on each cycle so every asset still gets covered over
        # time, instead of the same first N symbols winning forever and
        # the batch as a whole being rejected outright.
        budget = self.quote_limiter.remaining()
        if budget <= 0:
            return result
        affordable = wanted[:budget]

        if not self.quote_limiter.allow(cost=len(affordable)):
            return result  # lost a race with another caller -- try again next cycle

        try:
            resp = requests.get(
                f"{self.BASE_URL}/quote",
                params={"symbol": ",".join(affordable), "apikey": self.api_key},
                timeout=REQUEST_TIMEOUT,
            )
            data = resp.json()
        except Exception as e:
            logger.warning(f"[TwelveData] quote request failed: {e}")
            return result

        # Response shape is a flat object for a single symbol, or a dict
        # keyed by symbol for multiple symbols.
        if len(affordable) == 1:
            data = {affordable[0]: data}

        for symbol, label in symbol_to_label.items():
            if symbol not in affordable:
                continue
            entry = data.get(symbol) if isinstance(data, dict) else None
            if not isinstance(entry, dict) or entry.get("status") == "error" or entry.get("code"):
                continue
            try:
                close = float(entry["close"])
            except (KeyError, TypeError, ValueError):
                continue
            # Twelve Data's free/basic quote endpoint returns last price,
            # not a live bid/ask spread (that needs a WebSocket / premium
            # feed) -- we surface the real last price as bid=ask=price
            # rather than fabricate a synthetic spread.
            result[label] = {
                "price": close,
                "bid": close,
                "ask": close,
                "time": entry.get("datetime"),
            }
        return result

    def get_candles(self, label: str, timeframe: str, outputsize: int = 300) -> Optional[pd.DataFrame]:
        symbol = self._symbol_for(label)
        interval = self._INTERVAL_MAP.get(timeframe, "1h")
        if not symbol or not self.is_configured():
            return None

        if not self.candle_limiter.allow():
            return None  # caller uses cached candles instead

        try:
            resp = requests.get(
                f"{self.BASE_URL}/time_series",
                params={
                    "symbol": symbol, "interval": interval,
                    "outputsize": outputsize, "apikey": self.api_key,
                },
                timeout=REQUEST_TIMEOUT,
            )
            data = resp.json()
        except Exception as e:
            logger.warning(f"[TwelveData] time_series request failed: {e}")
            return None

        if data.get("status") == "error" or "values" not in data:
            logger.warning(f"[TwelveData] time_series error for {symbol}: {data.get('message')}")
            return None

        rows = data["values"]
        if not rows:
            return self._empty_frame()

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["datetime"])
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df.get("volume", 0)
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

        # Twelve Data returns newest-first; the chart/indicator layer
        # expects chronological (oldest -> newest) order.
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df[["timestamp", "open", "high", "low", "close", "volume"]]


# ----------------------------------------------------------------------
# Finnhub (secondary / easy fallback)
# ----------------------------------------------------------------------
class FinnhubProvider(MarketDataProvider):
    name = "finnhub"
    display_name = "Finnhub"

    BASE_URL = "https://finnhub.io/api/v1"

    # Finnhub forex uses broker-prefixed symbols; crypto uses an exchange
    # prefix. XAU/XAG spot metals aren't offered on Finnhub's forex feed,
    # so those two intentionally fall through to whichever other
    # configured provider supports them.
    _FOREX_MAP = {
        "EUR/USD": "OANDA:EUR_USD", "GBP/USD": "OANDA:GBP_USD",
        "USD/JPY": "OANDA:USD_JPY", "AUD/USD": "OANDA:AUD_USD",
        "USD/CAD": "OANDA:USD_CAD", "USD/CHF": "OANDA:USD_CHF",
        "NZD/USD": "OANDA:NZD_USD", "EUR/GBP": "OANDA:EUR_GBP",
        "EUR/JPY": "OANDA:EUR_JPY", "GBP/JPY": "OANDA:GBP_JPY",
    }
    _CRYPTO_MAP = {
        "BTC": "BINANCE:BTCUSDT", "ETH": "BINANCE:ETHUSDT", "SOL": "BINANCE:SOLUSDT",
    }
    _RESOLUTION_MAP = {
        "1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D",
    }

    def _symbol_for(self, label: str) -> Optional[str]:
        return self._FOREX_MAP.get(label) or self._CRYPTO_MAP.get(label)

    def get_quotes(self, labels: List[str]) -> Dict[str, Optional[dict]]:
        result = {label: None for label in labels}
        if not self.is_configured():
            return result

        # Finnhub's free /quote endpoint doesn't accept a symbol batch,
        # so each asset is its own call -- guarded individually by the
        # rate limiter (a small ThreadPoolExecutor in CryptoService
        # parallelizes these so one slow request doesn't block the rest).
        for label in labels:
            symbol = self._symbol_for(label)
            if not symbol or not self.quote_limiter.allow():
                continue
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/quote",
                    params={"symbol": symbol, "token": self.api_key},
                    timeout=REQUEST_TIMEOUT,
                )
                entry = resp.json()
            except Exception as e:
                logger.warning(f"[Finnhub] quote request failed for {symbol}: {e}")
                continue

            price = entry.get("c")
            if not price:
                continue  # 0/None means Finnhub had nothing for this symbol/plan
            result[label] = {"price": float(price), "bid": float(price), "ask": float(price), "time": entry.get("t")}
        return result

    def get_candles(self, label: str, timeframe: str, outputsize: int = 300) -> Optional[pd.DataFrame]:
        symbol = self._symbol_for(label)
        resolution = self._RESOLUTION_MAP.get(timeframe, "60")
        if not symbol or not self.is_configured():
            return None
        if not self.candle_limiter.allow():
            return None

        seconds_per_bar = {"1": 60, "5": 300, "15": 900, "30": 1800, "60": 3600, "240": 14400, "D": 86400}[resolution]
        now = int(time.time())
        frm = now - seconds_per_bar * outputsize
        path = "crypto/candle" if label in self._CRYPTO_MAP else "forex/candle"

        try:
            resp = requests.get(
                f"{self.BASE_URL}/{path}",
                params={"symbol": symbol, "resolution": resolution, "from": frm, "to": now, "token": self.api_key},
                timeout=REQUEST_TIMEOUT,
            )
            data = resp.json()
        except Exception as e:
            logger.warning(f"[Finnhub] candle request failed for {symbol}: {e}")
            return None

        # Finnhub returns {"s":"no_data"} when the plan doesn't include
        # historical candles for this symbol -- treated as "unavailable",
        # never as an excuse to fabricate one.
        if data.get("s") != "ok":
            logger.warning(f"[Finnhub] no candle data for {symbol} (plan may not include it): {data.get('s')}")
            return None

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(data["t"], unit="s"),
            "open": data["o"], "high": data["h"], "low": data["l"],
            "close": data["c"], "volume": data.get("v", [0] * len(data["t"])),
        })
        return df.sort_values("timestamp").reset_index(drop=True)


# ----------------------------------------------------------------------
# Alpha Vantage (secondary / easy fallback)
# ----------------------------------------------------------------------
class AlphaVantageProvider(MarketDataProvider):
    name = "alphavantage"
    display_name = "Alpha Vantage"

    BASE_URL = "https://www.alphavantage.co/query"

    _FOREX_LABELS = {
        "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "USD/CHF",
        "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "XAU/USD", "XAG/USD",
    }
    _CRYPTO_LABELS = {"BTC", "ETH", "SOL"}

    _INTRADAY_INTERVAL = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}

    def _split_forex(self, label: str):
        base, quote = label.split("/")
        return base, quote

    def get_quotes(self, labels: List[str]) -> Dict[str, Optional[dict]]:
        result = {label: None for label in labels}
        if not self.is_configured():
            return result

        for label in labels:
            if label in self._FOREX_LABELS:
                frm, to = self._split_forex(label)
            elif label in self._CRYPTO_LABELS:
                frm, to = label, "USD"
            else:
                continue

            if not self.quote_limiter.allow():
                continue
            try:
                resp = requests.get(
                    self.BASE_URL,
                    params={
                        "function": "CURRENCY_EXCHANGE_RATE",
                        "from_currency": frm, "to_currency": to,
                        "apikey": self.api_key,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                data = resp.json().get("Realtime Currency Exchange Rate")
            except Exception as e:
                logger.warning(f"[AlphaVantage] quote request failed for {label}: {e}")
                continue

            if not data:
                continue
            try:
                price = float(data["5. Exchange Rate"])
                bid = float(data.get("8. Bid Price", price))
                ask = float(data.get("9. Ask Price", price))
            except (KeyError, TypeError, ValueError):
                continue
            result[label] = {"price": price, "bid": bid, "ask": ask, "time": data.get("6. Last Refreshed")}
        return result

    def get_candles(self, label: str, timeframe: str, outputsize: int = 300) -> Optional[pd.DataFrame]:
        if not self.is_configured():
            return None
        if not self.candle_limiter.allow():
            return None

        try:
            if label in self._CRYPTO_LABELS:
                # Alpha Vantage's free tier only offers daily granularity
                # for crypto (intraday crypto candles require a paid
                # add-on) -- daily real candles, never a fabricated
                # intraday shape.
                resp = requests.get(
                    self.BASE_URL,
                    params={
                        "function": "DIGITAL_CURRENCY_DAILY",
                        "symbol": label, "market": "USD", "apikey": self.api_key,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                raw = resp.json().get("Time Series (Digital Currency Daily)")
                if not raw:
                    return None
                rows = []
                for date_str, values in raw.items():
                    rows.append({
                        "timestamp": pd.Timestamp(date_str),
                        "open": float(values["1. open"]), "high": float(values["2. high"]),
                        "low": float(values["3. low"]), "close": float(values["4. close"]),
                        "volume": float(values.get("5. volume", 0)),
                    })
                df = pd.DataFrame(rows).sort_values("timestamp").tail(outputsize).reset_index(drop=True)
                return df

            frm, to = self._split_forex(label)
            if timeframe in self._INTRADAY_INTERVAL:
                resp = requests.get(
                    self.BASE_URL,
                    params={
                        "function": "FX_INTRADAY", "from_symbol": frm, "to_symbol": to,
                        "interval": self._INTRADAY_INTERVAL[timeframe], "outputsize": "full",
                        "apikey": self.api_key,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                key = f"Time Series FX ({self._INTRADAY_INTERVAL[timeframe]})"
            else:
                # 4h/1d -> Alpha Vantage's daily FX series (no native 4h bar).
                resp = requests.get(
                    self.BASE_URL,
                    params={"function": "FX_DAILY", "from_symbol": frm, "to_symbol": to,
                            "outputsize": "full", "apikey": self.api_key},
                    timeout=REQUEST_TIMEOUT,
                )
                key = "Time Series FX (Daily)"

            raw = resp.json().get(key)
            if not raw:
                return None
            rows = []
            for date_str, values in raw.items():
                rows.append({
                    "timestamp": pd.Timestamp(date_str),
                    "open": float(values["1. open"]), "high": float(values["2. high"]),
                    "low": float(values["3. low"]), "close": float(values["4. close"]),
                    "volume": 0.0,  # Alpha Vantage FX series carries no volume field
                })
            df = pd.DataFrame(rows).sort_values("timestamp").tail(outputsize).reset_index(drop=True)
            return df
        except Exception as e:
            logger.warning(f"[AlphaVantage] candle request failed for {label}: {e}")
            return None


# ----------------------------------------------------------------------
# Provider factory
# ----------------------------------------------------------------------
_PROVIDER_CLASSES = {
    "twelvedata": TwelveDataProvider,
    "finnhub": FinnhubProvider,
    "alphavantage": AlphaVantageProvider,
}


def build_provider_chain() -> List[MarketDataProvider]:
    """Builds the ordered list of configured providers to try, preferred
    provider first (config.settings.DATA_PROVIDER), falling back to any
    other provider that has an API key set. This is what makes swapping
    or adding a provider "easy": set DATA_PROVIDER and/or the relevant
    *_API_KEY env var(s) -- no code changes required."""
    from config import settings

    keys = {
        "twelvedata": settings.TWELVE_DATA_API_KEY,
        "finnhub": settings.FINNHUB_API_KEY,
        "alphavantage": settings.ALPHA_VANTAGE_API_KEY,
    }

    # FIX: Twelve Data (and the other providers) meter ONE account-wide
    # credit pool per minute -- there's no such thing as a separate
    # "quote budget" and "candle budget". The previous code created two
    # independent RateLimiter(8, 60) instances per provider, so the
    # app's internal accounting allowed up to 16 credits/min (8 quotes +
    # 8 candles) while the real account only had 8 total -- guaranteeing
    # "Limits exceeded" as soon as both were used in the same minute.
    # One shared limiter per provider now mirrors the real account cap.
    limits = {
        "twelvedata": RateLimiter(settings.TWELVE_DATA_RATE_LIMIT, 60),
        "finnhub": RateLimiter(settings.FINNHUB_RATE_LIMIT, 60),
        "alphavantage": RateLimiter(settings.ALPHA_VANTAGE_RATE_LIMIT, 60),
    }

    order = [settings.DATA_PROVIDER] + [p for p in _PROVIDER_CLASSES if p != settings.DATA_PROVIDER]

    chain = []
    for name in order:
        cls = _PROVIDER_CLASSES.get(name)
        if not cls:
            continue
        api_key = keys.get(name)
        if not api_key:
            continue  # not configured -- skip silently, this is how "easy support" works
        shared_limiter = limits[name]
        chain.append(cls(api_key, shared_limiter, shared_limiter))
    return chain
