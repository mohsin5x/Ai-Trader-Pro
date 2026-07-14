"""
services/price_feed.py
========================
Dedicated high-frequency price feed for the Paper Trading Engine.

ROOT CAUSE FIX:
The paper trading engine previously called crypto_service.fetch_top_market_prices()
which is rate-limited to 1 symbol per 15s (WATCHLIST_MAX_SYMBOLS_PER_CYCLE=1).
This means open trades never received live prices, so P&L was always $0.00,
TP/SL never triggered, and the history never moved from OPEN.

This module maintains a SEPARATE price cache that is:
  1. Updated every PRICE_FEED_INTERVAL seconds (default 3s)
  2. Uses ONLY the assets that have open trades (priority) + the full watchlist
  3. For crypto: direct Binance public REST endpoint (no API key, no rate limit)
  4. For forex: uses the same tvdatafeed / provider as before but in a dedicated thread
  5. Thread-safe: all reads return snapshots, never block the engine

The engine imports get_price(symbol) instead of going through crypto_service.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, List

from utils.logger import logger

_PRICE_FEED_INTERVAL = 3.0   # seconds between refresh cycles (module alias for PriceFeed)
PRICE_FEED_INTERVAL = _PRICE_FEED_INTERVAL
_BINANCE_BASE = "https://api.binance.com/api/v3"

# ALL crypto symbols from CryptoService.ASSETS — used to map BTCUSDT → BTC etc.
# This must stay in sync with services/crypto_service.py CryptoService.ASSETS.
_CRYPTO_BARE = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE",
    "AVAX", "MATIC", "DOT", "LINK", "LTC", "UNI", "ATOM",
    "TRX", "TON", "BCH", "APT", "ARB", "OP", "INJ",
    "SUI", "NEAR", "FTM", "ALGO", "VET", "AAVE", "MKR",
    "LDO", "RUNE", "HBAR",
    # Additional common tokens that may appear in trades
    "PEPE", "SHIB", "WIF", "BONK", "JUP", "SEI", "STRK",
    "COMP", "CRV", "SNX", "SAND", "MANA", "AXS", "GALA",
    "BAT", "ENJ", "CHZ", "1INCH", "ZIL", "IOTA", "EOS",
}


def _to_binance_ticker(symbol: str) -> str:
    """Convert our symbol format to Binance ticker (e.g. 'BTC' -> 'BTCUSDT')."""
    s = symbol.upper().replace("/", "")
    if s in {c.replace("/", "") for c in _CRYPTO_BARE}:
        return s + "USDT"
    # BCH, COMP, etc.
    if not s.endswith("USDT") and not s.endswith("USD"):
        return s + "USDT"
    return s


class PriceFeed:
    """
    Lightweight price feed that bypasses the rate-limited CryptoService
    for the paper trading engine's real-time mark-to-market needs.
    """

    def __init__(self, crypto_service=None):
        self._lock = threading.Lock()
        self._prices: Dict[str, float] = {}
        self._crypto_service = crypto_service
        self._priority_symbols: List[str] = []
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self._requests = None
        try:
            import requests as _r
            self._requests = _r
        except ImportError:
            pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="price-feed"
        )
        self._thread.start()
        logger.info("[PriceFeed] Started high-frequency price feed.")

    def stop(self):
        self._stop = True

    def set_priority_symbols(self, symbols: List[str]):
        """Call from engine when trades open/close. These are refreshed first."""
        with self._lock:
            self._priority_symbols = list(symbols)

    def get_price(self, symbol: str) -> Optional[float]:
        """Thread-safe price lookup. Returns None if no data available."""
        with self._lock:
            # Try exact match, then without slash, then uppercase
            return (
                self._prices.get(symbol)
                or self._prices.get(symbol.replace("/", ""))
                or self._prices.get(symbol.replace("/", "").upper())
            )

    def get_price_for_pnl(self, symbol: str) -> Optional[float]:
        """
        Price specifically for PNL mark-to-market.

        FIX (2026-07-13): When MT5 is the active chart provider, its demo
        broker prices for crypto (e.g. BTC at $28 on an MT5 demo account)
        can corrupt PNL calculations.  This method always returns the
        Binance/CoinGecko live price for any recognised crypto symbol,
        falling back to whatever is in the cache for forex/indices.
        This ensures Binance-connected and MT5-connected modes produce
        identical PNL results for crypto, matching TradingView behaviour.
        """
        sym_up = symbol.upper().replace("/", "")
        # Check if this looks like a crypto symbol (in our known bare set)
        base = sym_up.replace("USDT", "").replace("USD", "")
        is_crypto = base in _CRYPTO_BARE

        if is_crypto:
            # For crypto: prefer XYZUSDT (Binance) price which is always
            # fetched from the real Binance public API, not the MT5 feed.
            with self._lock:
                p = (
                    self._prices.get(sym_up + "USDT")
                    or self._prices.get(sym_up + "USD")
                    or self._prices.get(base + "USDT")
                    or self._prices.get(base + "USD")
                    or self._prices.get(base)
                    or self._prices.get(symbol)
                )
            return p if p else None

        # Forex / indices — use standard lookup
        return self.get_price(symbol)

    def get_all_prices(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._prices)

    def _run_loop(self):
        while not self._stop:
            try:
                self._refresh_cycle()
            except Exception as e:
                logger.debug(f"[PriceFeed] cycle error: {e}")
            time.sleep(PRICE_FEED_INTERVAL)

    def _refresh_cycle(self):
        with self._lock:
            priority = list(self._priority_symbols)

        # Step 1: Fetch all crypto via Binance bookTicker (single endpoint, no rate limit)
        self._fetch_binance_bulk()

        # Step 2: For priority symbols not yet priced (forex), use crypto_service
        if self._crypto_service:
            unprice_priority = []
            with self._lock:
                for sym in priority:
                    if not (
                        self._prices.get(sym)
                        or self._prices.get(sym.replace("/", ""))
                        or self._prices.get(sym.replace("/", "").upper())
                    ):
                        unprice_priority.append(sym)
            if unprice_priority:
                self._fetch_via_service(unprice_priority)

    def _fetch_binance_bulk(self):
        """Fetch ALL tickers in one HTTP call. Tries multiple Binance subdomains
        plus a CoinGecko fallback for regions where api.binance.com returns 418."""
        if not self._requests:
            return

        # Try subdomains in order — some regions are blocked on the main domain
        base_urls = [
            "https://api.binance.com/api/v3/ticker/price",
            "https://api1.binance.com/api/v3/ticker/price",
            "https://api2.binance.com/api/v3/ticker/price",
            "https://api3.binance.com/api/v3/ticker/price",
        ]

        for url in base_urls:
            try:
                resp = self._requests.get(url, timeout=6)
                if resp.status_code == 418:
                    # Geo-blocked — try next subdomain
                    logger.debug(f"[PriceFeed] {url} returned 418 (geo-block), trying next")
                    continue
                if resp.status_code != 200:
                    continue
                data = resp.json()
                new_prices: dict[str, float] = {}
                for item in data:
                    ticker = item.get("symbol", "")
                    price  = item.get("price")
                    if not ticker or not price:
                        continue
                    try:
                        p = float(price)
                    except (TypeError, ValueError):
                        continue
                    # Store full ticker (e.g. BTCUSDT) for exact-match lookups
                    new_prices[ticker] = p
                    # Map XYZUSDT → XYZ for every USDT-quoted pair so the
                    # engine can look up "BTC", "BCH", "APT", etc. directly.
                    # We do this for ALL symbols (not just _CRYPTO_BARE) so
                    # any new token the user trades is automatically supported.
                    if ticker.endswith("USDT"):
                        base = ticker[:-4]
                        # Only map bare base if it looks like a real ticker
                        # (skip stablecoins-vs-stablecoins like USDCUSDT)
                        if base and base not in ("BUSD", "USDC", "DAI", "TUSD", "FDUSD"):
                            new_prices[base] = p
                    elif ticker.endswith("USD") and not ticker.endswith("USDT"):
                        base = ticker[:-3]
                        if base and base not in ("BUSD", "USDC", "DAI", "TUSD"):
                            new_prices[base] = p
                if new_prices:
                    with self._lock:
                        self._prices.update(new_prices)
                    logger.debug(f"[PriceFeed] {url}: {len(new_prices)} prices")
                    return  # success — don't try further
            except Exception as e:
                logger.debug(f"[PriceFeed] {url} failed: {e}")
                continue

        # All Binance subdomains failed — try CoinGecko for major cryptos
        self._fetch_coingecko_fallback()

    def _fetch_coingecko_fallback(self):
        """CoinGecko public API fallback when all Binance endpoints are blocked."""
        if not self._requests:
            return
        # Map CoinGecko IDs → our symbols (matches universal_free_provider._COINGECKO_IDS)
        cg_map = {
            "bitcoin": "BTC", "ethereum": "ETH", "binancecoin": "BNB",
            "solana": "SOL", "ripple": "XRP", "cardano": "ADA",
            "dogecoin": "DOGE", "avalanche-2": "AVAX", "matic-network": "MATIC",
            "polkadot": "DOT", "chainlink": "LINK", "litecoin": "LTC",
            "uniswap": "UNI", "cosmos": "ATOM", "tron": "TRX",
            "the-open-network": "TON", "bitcoin-cash": "BCH", "aptos": "APT",
            "arbitrum": "ARB", "optimism": "OP", "injective-protocol": "INJ",
            "sui": "SUI", "near": "NEAR", "fantom": "FTM", "algorand": "ALGO",
            "vechain": "VET", "aave": "AAVE", "maker": "MKR",
            "lido-dao": "LDO", "thorchain": "RUNE", "hedera-hashgraph": "HBAR",
        }
        ids = ",".join(cg_map.keys())
        try:
            resp = self._requests.get(
                f"https://api.coingecko.com/api/v3/simple/price"
                f"?ids={ids}&vs_currencies=usd",
                timeout=8,
            )
            if resp.status_code != 200:
                return
            data = resp.json()
            new_prices: Dict[str, float] = {}
            for cg_id, sym in cg_map.items():
                if cg_id in data and "usd" in data[cg_id]:
                    p = float(data[cg_id]["usd"])
                    new_prices[sym] = p
                    new_prices[sym + "USDT"] = p
            if new_prices:
                with self._lock:
                    self._prices.update(new_prices)
                logger.debug(f"[PriceFeed] CoinGecko fallback: {len(new_prices)} prices")
        except Exception as e:
            logger.debug(f"[PriceFeed] CoinGecko fallback failed: {e}")

    def _fetch_via_service(self, symbols: List[str]):
        """Fallback: use existing crypto_service provider for non-crypto assets."""
        if not self._crypto_service:
            return
        try:
            quotes = {}
            provider = None
            try:
                providers = self._crypto_service._providers
                if providers:
                    provider = providers[0]
            except Exception:
                pass
            if provider:
                quotes = provider.get_quotes(symbols) or {}
            for sym, data in quotes.items():
                if data and data.get("price"):
                    p = float(data["price"])
                    with self._lock:
                        self._prices[sym] = p
                        self._prices[sym.replace("/", "")] = p
                        self._prices[sym.replace("/", "").upper()] = p
        except Exception as e:
            logger.debug(f"[PriceFeed] service fallback failed: {e}")


# ── Module-level singleton ──────────────────────────────────────────────────
_feed: Optional[PriceFeed] = None


def init_feed(crypto_service=None) -> PriceFeed:
    """Initialize and start the global price feed. Called once at app startup."""
    global _feed
    if _feed is None:
        _feed = PriceFeed(crypto_service=crypto_service)
        _feed.start()
    return _feed


def get_price(symbol: str) -> Optional[float]:
    """Get live price for any symbol. Returns None if unavailable."""
    if _feed is None:
        return None
    return _feed.get_price(symbol)


def get_all_prices() -> Dict[str, float]:
    if _feed is None:
        return {}
    return _feed.get_all_prices()


def set_priority_symbols(symbols: List[str]):
    if _feed:
        _feed.set_priority_symbols(symbols)
