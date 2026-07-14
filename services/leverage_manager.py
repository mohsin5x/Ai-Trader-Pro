"""
services/leverage_manager.py
==============================
Centralised leverage lookup and margin/P&L calculation for every asset
class supported by AI Trader Pro. Called from:
  - services/paper_trading_engine.py  (position sizing + P&L)
  - ui/main_window.py                  (suggested lot size)
  - ui/paper_trading_history_panel.py  (display leverage column)
  - ui/trade_panel.py                  (order execution display)

Leverage defaults follow standard retail broker offerings.
Users can override any value at runtime through the Settings panel.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Asset-class detection helpers
# ---------------------------------------------------------------------------

_FOREX_MAJORS = {
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
    "USD/CHF", "NZD/USD",
}
_FOREX_CROSS = {
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/AUD", "AUD/JPY",
    "GBP/AUD", "EUR/CAD", "CAD/JPY", "GBP/CAD", "NZD/JPY",
    "CHF/JPY", "EUR/NZD", "GBP/NZD", "AUD/CAD", "AUD/CHF",
    # Exotic / EM pairs
    "EUR/CZK", "USD/CZK", "EUR/PLN", "USD/PLN", "EUR/HUF",
    "USD/HUF", "EUR/SEK", "USD/SEK", "EUR/NOK", "USD/NOK",
    "EUR/DKK", "USD/DKK", "EUR/TRY", "USD/TRY", "USD/MXN",
    "USD/ZAR", "USD/SGD", "USD/HKD", "USD/RUB", "USD/INR",
    "USD/BRL", "EUR/RON", "EUR/BGN", "USD/CNH", "USD/CNY",
    "NZD/USD", "NZD/CAD", "NZD/CHF",
}

# All fiat currency codes — used to detect forex pairs dynamically
_FIAT_CODES = {
    "USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD",
    "CZK","SEK","NOK","DKK","HKD","SGD","MXN","ZAR",
    "PLN","TRY","HUF","RON","BGN","RUB","INR","BRL",
    "CNH","CNY","KRW","TWD","THB","IDR","PHP","MYR",
}
_GOLD = {"XAU/USD", "GOLD", "XAUUSD"}
_SILVER = {"XAG/USD", "SILVER", "XAGUSD"}
_CRYPTO = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE",
    "AVAX", "MATIC", "DOT", "LINK", "LTC", "UNI", "ATOM",
    "TRX", "TON", "BCH", "APT", "ARB", "OP", "INJ",
    "SUI", "NEAR", "FTM", "ALGO", "VET", "AAVE", "MKR",
    "LDO", "RUNE", "HBAR",
    "BTC/USD", "ETH/USD", "BTCUSDT", "ETHUSDT",
}
_INDICES = {"US30", "NAS100", "SPX500", "DAX40", "FTSE100", "UK100",
            "GER40", "JP225"}
_STOCKS = {"AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA"}
_OIL = {"WTI", "BRENT", "USOIL", "UKOIL", "CL", "OIL"}

# Default leverage per asset class (1:X)
_LEVERAGE_MAP: dict[str, int] = {
    "forex_major":  100,
    "forex_cross":   50,
    "gold":          50,
    "silver":        50,
    "crypto":         2,
    "indices":        20,
    "stocks":          5,
    "oil":            20,
    "default":        10,
}


def get_asset_class(symbol: str) -> str:
    """Return a canonical asset-class string for the given symbol.
    
    Detection priority:
    1. Known major/cross sets (fast path)
    2. Metals (XAU, XAG)
    3. Crypto known set + prefix heuristic
    4. Indices / Oil / Stocks
    5. Dynamic fiat/fiat detection — any X/Y where both are fiat codes → forex
    6. Any remaining slash pair without XAU/XAG → forex cross (exotic)
    """
    s = symbol.upper().replace(" ", "")
    s_noslash = s.replace("/", "")

    if s in _FOREX_MAJORS or s_noslash in {x.replace("/", "") for x in _FOREX_MAJORS}:
        return "forex_major"
    if s in _FOREX_CROSS or s_noslash in {x.replace("/", "") for x in _FOREX_CROSS}:
        return "forex_cross"
    if s in _GOLD:
        return "gold"
    if s in _SILVER:
        return "silver"
    if s in _CRYPTO or any(s.startswith(c) for c in {"BTC", "ETH", "SOL", "BNB", "XRP"}):
        return "crypto"
    if s in _INDICES:
        return "indices"
    if s in _OIL:
        return "oil"
    if s in _STOCKS:
        return "stocks"

    # Dynamic fiat/fiat detection — handles exotic pairs like EUR/CZK, USD/MXN, etc.
    if "/" in symbol:
        parts = s.split("/")
        if len(parts) == 2:
            base, quote = parts[0].strip(), parts[1].strip()
            if base in _FIAT_CODES and quote in _FIAT_CODES:
                return "forex_cross"
        # Fall back: any slash pair not matching metals → forex cross
        if "XAU" not in s and "XAG" not in s:
            return "forex_cross"

    return "default"


def get_leverage(symbol: str) -> int:
    """Return the standard leverage multiplier (e.g. 100 for Forex majors)."""
    return _LEVERAGE_MAP.get(get_asset_class(symbol), _LEVERAGE_MAP["default"])


def asset_class_label(symbol: str) -> str:
    """Human-readable label for display in the UI."""
    cls = get_asset_class(symbol)
    labels = {
        "forex_major": "Forex Major",
        "forex_cross": "Forex Cross",
        "gold":        "Gold (XAU)",
        "silver":      "Silver (XAG)",
        "crypto":      "Crypto",
        "indices":     "Index",
        "stocks":      "Stock",
        "oil":         "Oil/Commodity",
        "default":     "Other",
    }
    return labels.get(cls, "Other")


# ---------------------------------------------------------------------------
# Position sizing (risk-based, leverage-aware)
# ---------------------------------------------------------------------------

def compute_position(
    symbol: str,
    account_balance: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
) -> dict:
    """
    Returns a dict with all sizing fields needed by both the engine and UI:
      units         – raw contract units
      lots          – standard lots (for FX / metals)
      size_label    – human-readable "0.25 LOTS" or "120 UNITS"
      leverage      – applied leverage multiplier
      margin        – required margin in account currency
      buying_power  – notional value of the position
      risk_cash     – dollar amount risked
      asset_class   – canonical class string
    """
    price_delta = abs(entry_price - stop_loss)
    leverage = get_leverage(symbol)
    asset_cls = get_asset_class(symbol)
    risk_cash = account_balance * risk_pct

    if price_delta <= 0 or account_balance <= 0:
        return {
            "units": 0.0, "lots": 0.0, "size_label": "0.00 UNITS",
            "leverage": leverage, "margin": 0.0, "buying_power": 0.0,
            "risk_cash": 0.0, "asset_class": asset_cls,
        }

    # ---------------------------------------------------------------
    # Units calculation: risk_cash = price_delta * pip_value * units
    #   For FX: 1 standard lot = 100,000 units; pip_value ≈ 1 per unit (USD quoted)
    #   For metals/crypto/indices: 1 unit = 1 contract
    # ---------------------------------------------------------------
    if asset_cls in ("forex_major", "forex_cross"):
        raw_units = risk_cash / price_delta          # units in base currency
        lots = raw_units / 100_000.0
        size_label = f"{lots:.2f} LOTS"
    elif asset_cls in ("gold", "silver"):
        raw_units = risk_cash / price_delta          # oz
        lots = raw_units / 100.0                     # 1 lot = 100 oz for XAU
        size_label = f"{lots:.3f} LOTS ({raw_units:.2f} oz)"
    elif asset_cls in ("indices",):
        raw_units = risk_cash / price_delta          # contracts
        lots = raw_units
        size_label = f"{raw_units:.2f} UNITS"
    elif asset_cls == "crypto":
        # Correct crypto sizing:
        # risk_cash = price_delta_in_USD * units_in_coin  →  units = risk_cash / price_delta
        # price_delta is already absolute USD diff, so formula is correct.
        # For high-value coins (BTC ~64k), this produces small fractional units (e.g. 0.001563 BTC).
        raw_units = risk_cash / price_delta  # coins
        lots = raw_units
        # Smart label: more decimals for expensive coins
        if entry_price >= 1000:
            size_label = f"{raw_units:.6f} UNITS"
        elif entry_price >= 1:
            size_label = f"{raw_units:.4f} UNITS"
        else:
            size_label = f"{raw_units:.2f} UNITS"
    else:
        raw_units = risk_cash / price_delta
        lots = raw_units
        size_label = f"{raw_units:.2f} UNITS"

    notional = raw_units * entry_price
    margin = notional / leverage if leverage else notional
    buying_power = margin * leverage

    return {
        "units":        raw_units,
        "lots":         lots,
        "size_label":   size_label,
        "leverage":     leverage,
        "margin":       margin,
        "buying_power": buying_power,
        "risk_cash":    risk_cash,
        "asset_class":  asset_cls,
    }


def compute_pnl(
    symbol: str,
    direction: str,
    entry_price: float,
    current_price: float,
    units: float,
) -> float:
    """
    Mark-to-market P&L in account currency (USD).
    Correctly handles FX pip values, gold oz, crypto, indices.
    """
    asset_cls = get_asset_class(symbol)
    diff = (current_price - entry_price) if direction == "BUY" else (entry_price - current_price)

    if asset_cls in ("forex_major", "forex_cross"):
        # For USD-quoted pairs (e.g. EUR/USD) 1 pip = $0.0001 per unit
        # For JPY-quoted pairs the pip is larger but price_diff handles it
        return diff * units
    elif asset_cls in ("gold",):
        return diff * units          # 1 oz * price diff in USD
    elif asset_cls in ("silver",):
        return diff * units
    elif asset_cls in ("indices", "oil", "stocks", "default"):
        return diff * units
    elif asset_cls == "crypto":
        return diff * units
    return diff * units


# ---------------------------------------------------------------------------
# Runtime leverage overrides — persisted to config.json
# ---------------------------------------------------------------------------
# Users can change leverage per asset class in the Settings panel.
# These overrides survive app restarts and are merged with the defaults
# above so new asset classes always have a sensible default.

def _get_override_path() -> str:
    try:
        from utils.path_manager import get_config_path
        return get_config_path("leverage_overrides.json")
    except Exception:
        import os
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "leverage_overrides.json",
        )


def load_leverage_overrides() -> None:
    """
    Load user-defined leverage overrides from config and merge them
    into _LEVERAGE_MAP.  Called once at startup and after Settings save.
    """
    import json, os
    path = _get_override_path()
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            overrides: dict = json.load(f)
        for asset_class, value in overrides.items():
            lev = int(value)
            if asset_class in _LEVERAGE_MAP and lev > 0:
                _LEVERAGE_MAP[asset_class] = lev
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"[LeverageManager] Failed to load overrides: {exc}")


def save_leverage_override(asset_class: str, leverage: int) -> bool:
    """
    Persist a single asset-class leverage override to config.
    Returns True on success.
    """
    import json, os, threading
    _lock = threading.Lock()
    path = _get_override_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock:
        try:
            existing: dict = {}
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            existing[asset_class] = max(1, int(leverage))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            _LEVERAGE_MAP[asset_class] = existing[asset_class]
            return True
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                f"[LeverageManager] Failed to save override for {asset_class}: {exc}"
            )
            return False


def get_all_leverages() -> dict:
    """Return a copy of the current _LEVERAGE_MAP (defaults + overrides)."""
    return dict(_LEVERAGE_MAP)


# Load overrides on module import so the app always starts with the
# user's saved preferences already in effect.
try:
    load_leverage_overrides()
except Exception:
    pass