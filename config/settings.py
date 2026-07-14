"""
AI Trader Pro - Global Settings
--------------------------------
All application-wide constants should be stored here.
"""

import os

try:
    # Lets users keep API keys in a local ".env" file (next to main.py or
    # the packaged .exe) instead of setting real OS environment variables.
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ==========================
# Application
# ==========================

APP_NAME = "AI Trader Pro"
APP_VERSION = "2.0"

# ==========================
# Theme
# ==========================

THEME = "dark"

BACKGROUND_COLOR = "#111827"
PANEL_COLOR = "#1A1F2E"
TEXT_COLOR = "#FFFFFF"
GRID_COLOR = "#2A2A2A"

UP_CANDLE_COLOR = "#26A69A"
DOWN_CANDLE_COLOR = "#EF5350"

BUY_COLOR = "#00C853"
SELL_COLOR = "#D50000"

# ==========================
# Default Trading Settings
# ==========================

DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_TIMEFRAME = "15m"
DEFAULT_STRATEGY = "ICT Smart Money"

# ==========================
# Data Settings
# ==========================

UPDATE_INTERVAL = 1          # seconds
MAX_CANDLES = 500
MAX_RETRIES = 3

# ==========================
# Chart Settings
# ==========================

SHOW_GRID = True
SHOW_VOLUME = True
SHOW_CROSSHAIR = True
ENABLE_SMOOTH_ZOOM = True

CHART_PADDING = 40

# ==========================
# AI Settings
# ==========================

MIN_CONFIDENCE = 70

# ==========================
# AI Signal Engine (Market Scanner)
# ==========================
# Multi-timeframe confluence engine, separate from the single-timeframe
# strategy dropdown above. See services/signal_engine.py.

# Trend is read from the higher timeframes, the setup/pattern is read
# from the mid timeframe, and entry timing is confirmed on the lower
# timeframes -- combined before any signal is produced.
SIGNAL_TREND_TIMEFRAMES = ["4h", "1h"]
SIGNAL_SETUP_TIMEFRAME = "15m"
SIGNAL_ENTRY_TIMEFRAMES = ["5m", "1m"]

# A signal is only produced once at least this many independent
# confirmations (technical + Smart Money Concepts) agree. Prevents the
# engine from forcing signals off a single indicator.
SIGNAL_MIN_CONFLUENCE = int(os.environ.get("SIGNAL_MIN_CONFLUENCE", "4"))

# Confidence floor (0-100) below which a candidate setup is discarded
# rather than shown. Reuses MIN_CONFIDENCE above by default.
SIGNAL_MIN_CONFIDENCE = int(os.environ.get("SIGNAL_MIN_CONFIDENCE", str(MIN_CONFIDENCE)))

# How often (seconds) the background scanner re-evaluates each symbol.
# Spread across SIGNAL_ENGINE_SYMBOLS so the scanner never bursts every
# provider request at once (respects rate limits via market_data_provider).
SIGNAL_SCAN_INTERVAL_SECONDS = int(os.environ.get("SIGNAL_SCAN_INTERVAL_SECONDS", "90"))
# NOTE: raised from 20s -- the scanner shares the exact same account-wide
# Twelve Data credit pool (TWELVE_DATA_RATE_LIMIT) as the watchlist and
# chart. A shorter interval here directly eats into the credit headroom
# the watchlist fix above depends on. Lower this only if you're on a
# plan with a higher TWELVE_DATA_RATE_LIMIT.

# Risk-to-reward multiples for TP1 / TP2 / TP3, applied to the ATR-based
# stop-loss distance.
SIGNAL_TP_MULTIPLES = (1.0, 2.0, 3.0)
SIGNAL_SL_ATR_MULTIPLE = 1.5

# ==========================
# Risk Management
# ==========================

DEFAULT_RISK_PERCENT = 1.0
DEFAULT_RR = 3.0

# ==========================
# Live Market Data Provider
# ==========================
# Never hardcode real API keys here -- they are read from environment
# variables (optionally via a local ".env" file; see .env.example).
# DATA_PROVIDER selects which one is tried first: "twelvedata" (default,
# recommended), "finnhub", or "alphavantage". Any other configured
# provider is used automatically as a fallback if the preferred one has
# no key set or a request fails -- see services/market_data_provider.py.

DATA_PROVIDER = os.environ.get("DATA_PROVIDER", "twelvedata").strip().lower()

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()

# How often (seconds) live news is refreshed from the news API. Kept
# well above 60s so a free-tier Finnhub key is never at risk of being
# rate-limited just from the news feed alone.
NEWS_REFRESH_SECONDS = int(os.environ.get("NEWS_REFRESH_SECONDS", "300"))

# Requests allowed per rolling 60s window, per provider. These default to
# conservative free-tier limits; raise them in your .env if you're on a
# paid plan. They exist so the app can never hammer your API key.
TWELVE_DATA_RATE_LIMIT = int(os.environ.get("TWELVE_DATA_RATE_LIMIT", "8"))
FINNHUB_RATE_LIMIT = int(os.environ.get("FINNHUB_RATE_LIMIT", "30"))
ALPHA_VANTAGE_RATE_LIMIT = int(os.environ.get("ALPHA_VANTAGE_RATE_LIMIT", "5"))

# How long (seconds) cached quotes/candles stay "fresh" before the app is
# willing to spend another API call refreshing them. The UI still updates
# every few seconds -- it just serves cached data between real fetches.
#
# FIX: Twelve Data bills 1 credit PER SYMBOL, even inside one batched
# request (confirmed in their docs). WATCHLIST_REFRESH_SECONDS is now the
# interval between small, budget-sized watchlist refresh cycles (see
# WATCHLIST_MAX_SYMBOLS_PER_CYCLE below) rather than one all-18-symbols-
# at-once request, which was instantly exceeding an 8-credit/minute Basic
# plan on every single refresh.
WATCHLIST_REFRESH_SECONDS = int(os.environ.get("WATCHLIST_REFRESH_SECONDS", "15"))
CHART_REFRESH_SECONDS = int(os.environ.get("CHART_REFRESH_SECONDS", "20"))

# How many watchlist symbols are requested per refresh cycle. Twelve
# Data's per-symbol billing means this directly controls credit spend:
# (WATCHLIST_MAX_SYMBOLS_PER_CYCLE credits) every WATCHLIST_REFRESH_SECONDS.
# At the defaults (1 symbol / 15s) that's 4 credits/minute for the
# watchlist, leaving headroom in the same shared account credit pool for
# the actively-viewed chart's candle requests (also on TWELVE_DATA_RATE_LIMIT).
# CryptoService rotates which symbols go first each cycle so the whole
# watchlist still gets covered -- raise this (and/or TWELVE_DATA_RATE_LIMIT
# if you're on a bigger plan) for faster full-list refresh.
WATCHLIST_MAX_SYMBOLS_PER_CYCLE = int(os.environ.get("WATCHLIST_MAX_SYMBOLS_PER_CYCLE", "1"))

# How long (seconds) a stale cached value may still be shown as a
# graceful fallback (real, previously-fetched data -- never fabricated)
# if a single refresh attempt fails, before falling back to
# "Data unavailable" instead. Sized comfortably above one full watchlist
# rotation (num symbols / WATCHLIST_MAX_SYMBOLS_PER_CYCLE *
# WATCHLIST_REFRESH_SECONDS) so a symbol waiting its turn in the rotation
# never flashes "Data unavailable" -- it keeps showing its last real price.
STALE_DATA_GRACE_SECONDS = int(os.environ.get("STALE_DATA_GRACE_SECONDS", "320"))
