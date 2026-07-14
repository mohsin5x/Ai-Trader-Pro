"""
services/data_feed_factory.py
================================
Task 2: DataFeedFactory. Turns a settings dict (or config.json, via
services/provider_settings.py) into a ready-to-use MarketDataProvider
instance -- "Default (Free)", MT5, or Twelve Data.

FIX (2026-07-13): mt5_overrides section expanded with clear broker-specific
instructions so users can uncomment the correct variant for their broker.
Symbols not found on the broker are now logged with a helpful message pointing
here (see mt5_provider.py _ensure_symbol_selected).
"""

from typing import Optional

from config import settings as app_settings
from services.market_data_provider import RateLimiter, TwelveDataProvider
from services.universal_free_provider import UniversalFreeProvider
from services.mt5_provider import MT5Provider
from services.hybrid_provider import HybridProvider
from utils.logger import logger


class DataFeedFactory:
    """settings_dict shape (see services/provider_settings.py):
        {"provider_type": "Default" | "MT5" | "TwelveData", "api_key": "..."}
    """

    @staticmethod
    def get_provider(settings_dict: dict):
        provider_type = (settings_dict or {}).get("provider_type", "Default")

        if provider_type == "Default":
            return UniversalFreeProvider()

        if provider_type == "MT5":
            # ============================================================
            # BROKER SYMBOL OVERRIDES
            # ============================================================
            # MT5 brokers often use non-standard ticker names for crypto and
            # some forex pairs. If the chart shows no data after connecting,
            # find your broker's symbol names in MT5 Market Watch and add them
            # below, then restart the app.
            #
            # HOW TO CHECK: In MT5 → View → Symbols, search for the asset.
            # The "Symbol" column is the exact name to use on the right side.
            #
            # FORMAT:  "OUR_LABEL": "BROKER_SYMBOL"
            #
            # --- Crypto CFD variants (uncomment the block that matches yours) ---
            #
            # Standard (no suffix — most ECN brokers e.g. ICMarkets, Pepperstone):
            # mt5_overrides = {}  # pass-through: BTC→BTC, ETH→ETH, EURUSD→EURUSD
            #
            # 'm' suffix (e.g. some XM, Exness sub-accounts):
            # mt5_overrides = {
            #     "BTC": "BTCUSDm", "ETH": "ETHUSDm", "BNB": "BNBUSDm",
            #     "SOL": "SOLUSDm", "XRP": "XRPUSDm", "ADA": "ADAUSDm",
            # }
            #
            # Dot suffix (e.g. Tickmill, some FXCM accounts):
            # mt5_overrides = {
            #     "BTC": "BTCUSD.", "ETH": "ETHUSD.", "EUR/USD": "EURUSD.",
            # }
            #
            # '#' suffix (e.g. some Roboforex accounts):
            # mt5_overrides = {
            #     "BTC": "BTCUSD#", "ETH": "ETHUSD#",
            # }
            #
            # Full name (e.g. some Exness accounts):
            # mt5_overrides = {
            #     "BTC": "BITCOIN", "ETH": "ETHEREUM",
            # }
            #
            # Gold / indices renaming (common across many brokers):
            # mt5_overrides = {
            #     "XAU/USD": "XAUUSD",   # or "GOLD", "XAUUSDm", etc.
            #     "US30":    "DJ30",      # Dow Jones — broker-specific
            #     "NAS100":  "NAS100",    # usually standard
            #     "SPX500":  "SP500",     # varies widely
            # }
            #
            # ============================================================
            # DEFAULT: empty dict = pass symbols through unchanged.
            # Most STP/ECN brokers (ICMarkets, Pepperstone, FusionMarkets)
            # use standard names and need no overrides.
            # ============================================================
            mt5_overrides = {}

            # FIX (2026-07-13): selecting "MT5" used to route EVERY symbol
            # -- including crypto -- through the MT5 terminal. Most brokers
            # either don't offer crypto CFDs or use non-standard tickers,
            # so BTC/ETH/etc. showed no data or a broker-marked-up price
            # instead of the real Binance spot price. HybridProvider keeps
            # MT5 as the source for forex/metals/indices while always
            # serving crypto from Binance -- both run at the same time,
            # with no mode switch between them.
            return HybridProvider(mt5_symbol_overrides=mt5_overrides)

        if provider_type == "TwelveData":
            # ============================================================
            # >>> PUT YOUR TWELVE DATA API KEY HERE <<<
            # Preferred: set it via Settings (this is settings_dict["api_key"],
            # persisted by services.provider_settings.save_settings) or in
            # your .env file as TWELVE_DATA_API_KEY=your_key_here.
            # Falls back to the .env value if Settings hasn't set one yet,
            # so existing .env-based setups keep working unchanged.
            # ============================================================
            api_key: Optional[str] = settings_dict.get("api_key") or app_settings.TWELVE_DATA_API_KEY
            if not api_key:
                logger.warning(
                    "[DataFeedFactory] TwelveData selected but no API key found in Settings "
                    "or .env -- falling back to Default (Free)."
                )
                return UniversalFreeProvider()

            limiter = RateLimiter(app_settings.TWELVE_DATA_RATE_LIMIT, 60)
            return TwelveDataProvider(api_key, limiter, limiter)

        logger.warning(f"[DataFeedFactory] Unknown provider_type '{provider_type}' -- falling back to Default (Free).")
        return UniversalFreeProvider()
