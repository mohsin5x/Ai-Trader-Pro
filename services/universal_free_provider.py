"""
services/universal_free_provider.py
=====================================
UniversalFreeProvider -- the "Default (Free)" data source.

Sources (tried in priority order, no API key required):
  1. ccxt / Binance  — crypto prices & candles (fast, reliable)
  2. OKX public API  — crypto fallback (different exchange)
  3. Bitget public   — additional crypto fallback
  4. Twelve Data free tier — forex/metals/indices (key optional for quotes)
  5. Open Exchange Rates / fixer.io free tier hints via direct HTTP
  6. tvDatafeed      — forex fallback (TradingView, no login)
  7. yfinance        — broad fallback for anything Yahoo Finance covers

All libraries are optional — if missing the source is silently skipped.
NEVER fabricates a price: missing = None, UI shows "Data unavailable".
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import threading
import time
import json
import urllib.request
import urllib.error

import pandas as pd

from services.market_data_provider import MarketDataProvider, RateLimiter
from utils.logger import logger

# ── Optional library imports ─────────────────────────────────────────────────
try:
    import ccxt as _ccxt
    _CCXT_OK = True
except ImportError:
    _ccxt = None          # type: ignore
    _CCXT_OK = False

try:
    from tvDatafeed import TvDatafeed as _TvDatafeed, Interval as _TvInterval
    _TV_OK = True
except ImportError:
    _TvDatafeed = None    # type: ignore
    _TV_OK = False

try:
    import yfinance as _yf
    _YF_OK = True
except ImportError:
    _yf = None            # type: ignore
    _YF_OK = False

# ── Symbol tables ─────────────────────────────────────────────────────────────
_FIAT = {
    "USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD",
    "CZK","SEK","NOK","DKK","HKD","SGD","MXN","ZAR",
    "PLN","TRY","HUF","RON","BGN","RUB","INR","BRL",
    "CNH","CNY","KRW","TWD","THB","IDR","PHP","MYR",
    "XAU","XAG",
}

# crypto symbols that trade against USDT/BUSD on Binance
_KNOWN_CRYPTO = {
    "BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","MATIC","DOT",
    "LINK","LTC","UNI","ATOM","TRX","TON","BCH","APT","ARB","OP",
    "INJ","SUI","NEAR","FTM","ALGO","VET","AAVE","MKR","LDO","RUNE",
    "HBAR","PEPE","SHIB","WIF","BONK","JUP","SEI","STRK","MANTA",
}

# CoinGecko IDs for common tokens (used as HTTP fallback)
_COINGECKO_IDS = {
    "BTC":"bitcoin","ETH":"ethereum","BNB":"binancecoin","SOL":"solana",
    "XRP":"ripple","ADA":"cardano","DOGE":"dogecoin","AVAX":"avalanche-2",
    "MATIC":"matic-network","DOT":"polkadot","LINK":"chainlink","LTC":"litecoin",
    "UNI":"uniswap","ATOM":"cosmos","TRX":"tron","TON":"the-open-network",
    "BCH":"bitcoin-cash","APT":"aptos","ARB":"arbitrum","OP":"optimism",
    "INJ":"injective-protocol","SUI":"sui","NEAR":"near","FTM":"fantom",
    "ALGO":"algorand","VET":"vechain","AAVE":"aave","MKR":"maker",
    "SHIB":"shiba-inu",
}

# TradingView exchange map (tvdatafeed fallback)
_TV_EXCHANGE = {
    "EUR/USD":"FX_IDC","GBP/USD":"FX_IDC","USD/JPY":"FX_IDC",
    "AUD/USD":"FX_IDC","USD/CAD":"FX_IDC","USD/CHF":"FX_IDC","NZD/USD":"FX_IDC",
    "EUR/GBP":"FX_IDC","EUR/JPY":"FX_IDC","GBP/JPY":"FX_IDC",
    "XAU/USD":"OANDA","XAG/USD":"OANDA",
    "US30":"DJ","NAS100":"NASDAQ","SPX500":"SP",
}


def _http_get(url: str, timeout: int = 6) -> Optional[dict]:
    """Simple JSON GET with a browser UA, returns None on any failure."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (AI-Trader-Pro/2.0)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


class UniversalFreeProvider(MarketDataProvider):
    """
    Free provider that works without any API key.
    Tries multiple sources in priority order for maximum reliability.
    """

    display_name = "Default (Free)"

    def __init__(self, ccxt_exchange_id: str = "binance"):
        super().__init__(
            api_key=None,
            quote_limiter=RateLimiter(30, 60),
            candle_limiter=RateLimiter(60, 60),
        )
        self._ccxt_id   = ccxt_exchange_id
        self._ccxt_lock = threading.Lock()
        self._ccxt_client = None

        self._tv_lock   = threading.Lock()
        self._tv_client = None

        # Cache: symbol -> (price, fetched_at)
        self._price_cache: Dict[str, Tuple[float, float]] = {}
        self._cache_lock  = threading.Lock()
        self._CACHE_TTL   = 12.0   # seconds

        # Log warnings once only
        self._warned: set = set()

    # ── is_configured ────────────────────────────────────────────────────────
    def is_configured(self) -> bool:
        return True   # always ready (no key required)

    # ── Routing ──────────────────────────────────────────────────────────────
    def _is_crypto(self, sym: str) -> bool:
        s = sym.upper().replace("/", "")
        # Bare tickers
        if sym.upper() in _KNOWN_CRYPTO:
            return True
        # X/USDT, X/USD where X is crypto
        if "/" in sym:
            base = sym.split("/")[0].upper()
            quote = sym.split("/")[1].upper()
            if base in _KNOWN_CRYPTO and quote in ("USDT","USD","BUSD","USDC"):
                return True
        return False

    def _is_forex(self, sym: str) -> bool:
        if "/" not in sym:
            return False
        b, q = sym.split("/")[0].upper(), sym.split("/")[1].upper()
        return b in _FIAT and q in _FIAT

    # ── Public API ───────────────────────────────────────────────────────────
    def get_price(self, symbol: str) -> Optional[float]:
        # Check cache first
        with self._cache_lock:
            if symbol in self._price_cache:
                px, ts = self._price_cache[symbol]
                if time.time() - ts < self._CACHE_TTL:
                    return px

        price = None
        if self._is_crypto(symbol):
            price = self._crypto_price(symbol)
        elif self._is_forex(symbol):
            price = self._forex_price(symbol)
        else:
            # Try crypto path first, then forex
            price = self._crypto_price(symbol) or self._forex_price(symbol)

        if price and price > 0:
            with self._cache_lock:
                self._price_cache[symbol] = (price, time.time())
        return price

    def get_candles(self, symbol: str, timeframe: str, outputsize: int = 200) -> Optional[pd.DataFrame]:
        if self._is_crypto(symbol):
            return self._crypto_candles(symbol, timeframe, outputsize)
        elif self._is_forex(symbol):
            return self._forex_candles(symbol, timeframe, outputsize)
        else:
            df = self._crypto_candles(symbol, timeframe, outputsize)
            if df is None or df.empty:
                df = self._forex_candles(symbol, timeframe, outputsize)
            return df

    def get_quotes(self, labels: List[str]) -> Dict[str, Optional[dict]]:
        result = {}
        for lbl in labels:
            px = self.get_price(lbl)
            result[lbl] = {"price": px, "bid": px, "ask": px} if px else None
        return result

    # ── Crypto: ccxt + HTTP fallbacks ────────────────────────────────────────
    def _get_ccxt(self):
        if not _CCXT_OK:
            return None
        with self._ccxt_lock:
            if self._ccxt_client is None:
                try:
                    ex_cls = getattr(_ccxt, self._ccxt_id, None) or _ccxt.binance
                    self._ccxt_client = ex_cls({
                        "enableRateLimit": True,
                        "timeout": 8000,
                        "options": {"defaultType": "spot"},
                    })
                    self._ccxt_client.load_markets()
                except Exception as e:
                    if "ccxt_init" not in self._warned:
                        self._warned.add("ccxt_init")
                        logger.warning(f"[FreeProvider] ccxt init failed: {e}")
                    return None
        return self._ccxt_client

    def _ccxt_sym(self, symbol: str) -> str:
        s = symbol.upper()
        if "/" in s:
            base, quote = s.split("/")
            if quote in ("USD", "USDC"):
                return f"{base}/USDT"
            return s
        # bare ticker
        return f"{s}/USDT"

    def _crypto_price(self, symbol: str) -> Optional[float]:
        # 1. ccxt
        ex = self._get_ccxt()
        if ex:
            try:
                ccxt_sym = self._ccxt_sym(symbol)
                if ccxt_sym in ex.markets:
                    t = ex.fetch_ticker(ccxt_sym)
                    px = t.get("last") or t.get("close")
                    if px:
                        return float(px)
            except Exception:
                pass

        # 2. OKX public REST (no key)
        base = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()
        try:
            data = _http_get(f"https://www.okx.com/api/v5/market/ticker?instId={base}-USDT")
            if data and data.get("data"):
                px = data["data"][0].get("last")
                if px:
                    return float(px)
        except Exception:
            pass

        # 3. Bybit public REST (no key)
        try:
            data = _http_get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={base}USDT")
            if data and data.get("result", {}).get("list"):
                px = data["result"]["list"][0].get("lastPrice")
                if px:
                    return float(px)
        except Exception:
            pass

        # 4. CoinGecko (rate limited but free, no key for basic quotes)
        gecko_id = _COINGECKO_IDS.get(base)
        if gecko_id:
            try:
                data = _http_get(
                    f"https://api.coingecko.com/api/v3/simple/price?ids={gecko_id}&vs_currencies=usd",
                    timeout=8,
                )
                if data and gecko_id in data:
                    px = data[gecko_id].get("usd")
                    if px:
                        return float(px)
            except Exception:
                pass

        return None

    def _crypto_candles(self, symbol: str, timeframe: str, outputsize: int) -> Optional[pd.DataFrame]:
        ex = self._get_ccxt()
        if not ex:
            return None

        tf_map = {
            "1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
            "1h":"1h","2h":"2h","4h":"4h","6h":"6h","8h":"8h","12h":"12h",
            "1d":"1d","1w":"1w",
        }
        ccxt_tf = tf_map.get(timeframe, "1h")
        ccxt_sym = self._ccxt_sym(symbol)

        try:
            if ccxt_sym not in ex.markets:
                return None
            ohlcv = ex.fetch_ohlcv(ccxt_sym, ccxt_tf, limit=outputsize)
            if not ohlcv:
                return None
            df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df["timestamp"] = df["timestamp"].dt.tz_localize(None)
            return df
        except Exception as e:
            if "ccxt_candles" not in self._warned:
                self._warned.add("ccxt_candles")
                logger.warning(f"[FreeProvider] ccxt candles failed for {symbol}: {e}")
        return None

    # ── Forex: tvdatafeed + yfinance fallbacks ────────────────────────────────
    def _get_tv(self):
        if not _TV_OK:
            return None
        with self._tv_lock:
            if self._tv_client is None:
                try:
                    self._tv_client = _TvDatafeed()
                except Exception:
                    return None
        return self._tv_client

    def _forex_price(self, symbol: str) -> Optional[float]:
        # 1. tvdatafeed
        tv = self._get_tv()
        if tv:
            try:
                tv_sym = symbol.replace("/", "")
                exch   = _TV_EXCHANGE.get(symbol, "FX_IDC")
                df = tv.get_hist(symbol=tv_sym, exchange=exch, interval=_TvInterval.in_1_minute, n_bars=2)
                if df is not None and not df.empty:
                    return float(df["close"].iloc[-1])
            except Exception:
                pass

        # 2. yfinance
        if _YF_OK:
            try:
                yf_sym = symbol.replace("/", "") + "=X"
                t = _yf.Ticker(yf_sym)
                info = t.fast_info
                px = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
                if px:
                    return float(px)
            except Exception:
                pass

        # 3. Open Exchange Rates (free tier, USD base only)
        if "/" in symbol:
            b, q = symbol.split("/")
            if b.upper() == "USD":
                try:
                    data = _http_get("https://open.er-api.com/v6/latest/USD")
                    if data and "rates" in data:
                        rate = data["rates"].get(q.upper())
                        if rate:
                            return float(rate)
                except Exception:
                    pass
            elif q.upper() == "USD":
                try:
                    data = _http_get("https://open.er-api.com/v6/latest/USD")
                    if data and "rates" in data:
                        rate = data["rates"].get(b.upper())
                        if rate:
                            return 1.0 / float(rate)
                except Exception:
                    pass

        # 4. Frankfurter (ECB data, EUR-based, free)
        if "/" in symbol:
            b, q = symbol.split("/")
            try:
                data = _http_get(f"https://api.frankfurter.app/latest?from={b.upper()}&to={q.upper()}")
                if data and "rates" in data:
                    rate = data["rates"].get(q.upper())
                    if rate:
                        return float(rate)
            except Exception:
                pass

        return None

    def _forex_candles(self, symbol: str, timeframe: str, outputsize: int) -> Optional[pd.DataFrame]:
        # 1. tvdatafeed
        tv = self._get_tv()
        if tv:
            tf_map = {
                "1m": _TvInterval.in_1_minute,
                "5m": _TvInterval.in_5_minute,
                "15m": _TvInterval.in_15_minute,
                "30m": _TvInterval.in_30_minute,
                "1h": _TvInterval.in_1_hour,
                "4h": _TvInterval.in_4_hour,
                "1d": _TvInterval.in_daily,
                "1w": _TvInterval.in_weekly,
            } if _TV_OK else {}
            tv_tf = tf_map.get(timeframe)
            if tv_tf is not None:
                try:
                    tv_sym = symbol.replace("/", "")
                    exch   = _TV_EXCHANGE.get(symbol, "FX_IDC")
                    df = tv.get_hist(symbol=tv_sym, exchange=exch, interval=tv_tf, n_bars=outputsize)
                    if df is not None and not df.empty:
                        df = df.reset_index()
                        df.rename(columns={"datetime": "timestamp"}, inplace=True)
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        return df[["timestamp","open","high","low","close","volume"]]
                except Exception:
                    pass

        # 2. yfinance
        if _YF_OK:
            tf_map_yf = {
                "1m":"1m","5m":"5m","15m":"15m","30m":"30m",
                "1h":"60m","4h":"60m","1d":"1d","1w":"1wk",
            }
            yf_tf = tf_map_yf.get(timeframe, "60m")
            period = "7d" if timeframe in ("1m","5m","15m","30m") else "1y"
            try:
                yf_sym = symbol.replace("/","") + "=X"
                df = _yf.download(yf_sym, interval=yf_tf, period=period,
                                  progress=False, auto_adjust=True)
                if df is not None and not df.empty:
                    df.reset_index(inplace=True)
                    df.rename(columns={
                        "Datetime":"timestamp","Date":"timestamp",
                        "Open":"open","High":"high","Low":"low",
                        "Close":"close","Volume":"volume",
                    }, inplace=True)
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    return df[["timestamp","open","high","low","close","volume"]].tail(outputsize)
            except Exception:
                pass

        return None
