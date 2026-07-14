"""
services/hybrid_provider.py
==============================
HybridProvider -- makes MT5 and Binance work at the same time.

PROBLEM THIS FIXES:
Previously, picking "MT5" in Settings pointed the *entire* app (charts,
watchlist, scanner, signals) at MT5Provider -- including crypto symbols
like BTC/ETH. That's wrong for two reasons:
  1. Most MT5 brokers either don't offer crypto CFDs at all, or use
     non-standard ticker names (BTCUSDm, BTCUSD., BITCOIN, ...), so
     crypto symbols showed "Data unavailable" or the wrong price
     (e.g. a demo-account CFD price instead of real spot price).
  2. Even when a broker does offer crypto CFDs, the price is a
     broker-marked-up CFD quote, not the real Binance spot price the
     rest of the app (paper trading PNL, signal engine) uses to judge
     TP/SL and win-rate.

FIX: this wrapper is what DataFeedFactory now hands out for the "MT5"
provider_type. It is not itself a new data source -- it's a router:
  - Any symbol that looks like crypto (BTC, ETH, SOL, ... or BTC/USDT
    etc.) is always served from Binance (via UniversalFreeProvider's
    ccxt/Binance + OKX/Bybit/CoinGecko fallback chain), regardless of
    what's selected in Settings.
  - Everything else (EUR/USD, XAU/USD, US30, NAS100, ...) goes to the
    user's actual MT5 terminal, exactly as before.

Both run concurrently -- there's no mode switch between them, no
"either/or". This mirrors the routing services/price_feed.py already
uses for paper-trading PNL (get_price_for_pnl); this class brings the
same behaviour to charts, quotes, and the watchlist/scanner so every
part of the app agrees on which source owns which symbol.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from services.market_data_provider import MarketDataProvider
from services.mt5_provider import MT5Provider
from services.universal_free_provider import UniversalFreeProvider
from utils.logger import logger

# Kept in sync with services/price_feed.py _CRYPTO_BARE and
# services/crypto_service.py CryptoService.ASSETS.
_CRYPTO_BARE = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE",
    "AVAX", "MATIC", "DOT", "LINK", "LTC", "UNI", "ATOM",
    "TRX", "TON", "BCH", "APT", "ARB", "OP", "INJ",
    "SUI", "NEAR", "FTM", "ALGO", "VET", "AAVE", "MKR",
    "LDO", "RUNE", "HBAR",
}


def _is_crypto_label(label: str) -> bool:
    s = label.upper().replace("/", "")
    if s in _CRYPTO_BARE:
        return True
    for quote in ("USDT", "USD", "USDC", "BUSD"):
        if s.endswith(quote) and s[: -len(quote)] in _CRYPTO_BARE:
            return True
    return False


class HybridProvider(MarketDataProvider):
    """Crypto -> Binance (UniversalFreeProvider). Everything else -> MT5."""

    name = "hybrid_mt5_binance"
    display_name = "MetaTrader 5 (Forex) + Binance (Crypto)"

    def __init__(self, mt5_symbol_overrides: Optional[Dict[str, str]] = None):
        # Reuse the base class' no-op init (limiters aren't used directly
        # by this router -- each wrapped provider owns its own).
        self.api_key = None
        self.quote_limiter = None
        self.candle_limiter = None

        self._mt5 = MT5Provider(symbol_overrides=mt5_symbol_overrides or {})
        self._crypto = UniversalFreeProvider()

    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        # Binance side needs no key and is always ready; MT5 side may
        # still be initialising in the background -- that's fine, forex
        # quotes simply come back empty until it connects.
        return True

    def set_on_init_complete(self, callback) -> None:
        """Pass-through so callers (e.g. MainWindow) can still hook the
        MT5 async handshake exactly as they did with a bare MT5Provider."""
        self._mt5.set_on_init_complete(callback)

    def shutdown(self):
        try:
            self._mt5.shutdown()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def get_quotes(self, labels: List[str]) -> Dict[str, Optional[dict]]:
        crypto_labels = [l for l in labels if _is_crypto_label(l)]
        forex_labels = [l for l in labels if not _is_crypto_label(l)]

        result: Dict[str, Optional[dict]] = {}
        if crypto_labels:
            try:
                result.update(self._crypto.get_quotes(crypto_labels))
            except Exception as e:
                logger.warning(f"[HybridProvider] Binance quotes failed: {e}")
                for l in crypto_labels:
                    result.setdefault(l, None)
        if forex_labels:
            try:
                result.update(self._mt5.get_quotes(forex_labels))
            except Exception as e:
                logger.warning(f"[HybridProvider] MT5 quotes failed: {e}")
                for l in forex_labels:
                    result.setdefault(l, None)
        return result

    def get_candles(self, label: str, timeframe: str, outputsize: int = 300) -> Optional[pd.DataFrame]:
        if _is_crypto_label(label):
            try:
                return self._crypto.get_candles(label, timeframe, outputsize)
            except Exception as e:
                logger.warning(f"[HybridProvider] Binance candles failed for {label}: {e}")
                return self._empty_frame()
        try:
            return self._mt5.get_candles(label, timeframe, outputsize)
        except Exception as e:
            logger.warning(f"[HybridProvider] MT5 candles failed for {label}: {e}")
            return self._empty_frame()
