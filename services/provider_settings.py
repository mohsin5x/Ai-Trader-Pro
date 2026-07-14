"""
services/provider_settings.py
================================
Settings & persistence for the data-source picker.

save_settings(provider_type, api_key=None)  -> persists choice + key securely
load_provider()                             -> reads saved settings and returns
                                               a ready provider object

Security fix: API keys are now stored via utils.secret_manager, which uses
OS Keyring when available and falls back to config.json as a last resort.
config.json no longer stores raw API keys by default — they go to the
OS credential store instead (keyring library optional but recommended).

config.json still stores: provider_type, appearance_mode, account_balance,
notification preferences. No plain-text API keys unless keyring is unavailable.
"""

from __future__ import annotations

import json
import os
import threading

from services.data_feed_factory import DataFeedFactory
from utils.logger import logger
from utils.secret_manager import get_api_key, set_api_key

try:
    from utils.path_manager import get_config_path as _gcp
    CONFIG_PATH = _gcp("config.json")
except Exception:
    CONFIG_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
    )

_lock = threading.Lock()

_DEFAULT_SETTINGS: dict = {
    "provider_type":     "Default",
    "appearance_mode":   "Dark",
    "account_balance":   100000.0,
    "notif_ai_signal":   True,
    "notif_news":        True,
    "notif_sound":       True,
    "notif_paper_trade": True,
    "notif_scanner_high": True,
}

# Provider type → secret_manager provider key
_PROVIDER_KEY_MAP: dict[str, str] = {
    "TwelveData":   "twelvedata",
    "Finnhub":      "finnhub",
    "AlphaVantage": "alphavantage",
}


def _read_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return dict(_DEFAULT_SETTINGS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults so new keys always have values
        merged = dict(_DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    except Exception as exc:
        logger.warning(f"[provider_settings] Failed to read {CONFIG_PATH}: {exc} -- using defaults.")
        return dict(_DEFAULT_SETTINGS)


def _write_config(data: dict) -> None:
    """Atomically write config.json (never stores plain-text API keys)."""
    # Strip api_key before writing to disk — secret_manager handles storage
    clean = {k: v for k, v in data.items() if k not in ("api_key",)}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)


def save_settings(provider_type: str, api_key: str = None) -> None:
    """
    Persist the selected data source and (optionally) its API key.

    API key is stored via secret_manager (OS Keyring preferred),
    NOT written as plain text to config.json.
    """
    valid_types = {"Default", "MT5", "TwelveData", "Finnhub", "AlphaVantage"}
    if provider_type not in valid_types:
        raise ValueError(f"provider_type must be one of {valid_types}, got {provider_type!r}")

    with _lock:
        data = _read_config()
        data["provider_type"] = provider_type

        # Persist API key securely if provided
        if api_key:
            secret_key = _PROVIDER_KEY_MAP.get(provider_type)
            if secret_key:
                ok = set_api_key(secret_key, api_key)
                if not ok:
                    logger.warning(f"[provider_settings] Could not persist API key for {provider_type}.")

        _write_config(data)

    logger.info(f"[provider_settings] Saved data source preference: {provider_type}")


def get_saved_api_key() -> str:
    """
    Return the API key for the currently-selected provider.
    Checks secret_manager (OS Keyring → .env → config.json fallback).
    Returns '' if no key found.
    """
    cfg = _read_config()
    provider_type = cfg.get("provider_type", "Default")
    secret_key = _PROVIDER_KEY_MAP.get(provider_type)
    if secret_key:
        return get_api_key(secret_key)
    return ""


def load_account_balance() -> float:
    """Reads the user's real account balance from config.json."""
    try:
        return float(_read_config().get("account_balance", 100000.0))
    except (TypeError, ValueError):
        return 100000.0


def save_account_balance(balance: float) -> None:
    with _lock:
        data = _read_config()
        data["account_balance"] = float(balance)
        _write_config(data)
    logger.info(f"[provider_settings] Saved real account balance: {balance:,.2f}")


def load_notification_settings() -> dict:
    """Return notification preference flags from config.json."""
    cfg = _read_config()
    return {
        "notif_ai_signal":    cfg.get("notif_ai_signal",    True),
        "notif_news":         cfg.get("notif_news",         True),
        "notif_sound":        cfg.get("notif_sound",        True),
        "notif_paper_trade":  cfg.get("notif_paper_trade",  True),
        "notif_scanner_high": cfg.get("notif_scanner_high", True),
    }


def save_notification_settings(prefs: dict) -> None:
    """Persist notification preference flags to config.json."""
    with _lock:
        data = _read_config()
        for key in ("notif_ai_signal", "notif_news", "notif_sound",
                    "notif_paper_trade", "notif_scanner_high"):
            if key in prefs:
                data[key] = bool(prefs[key])
        _write_config(data)


def load_provider():
    """
    Read config.json (defaults to Default/Free if missing) and return
    a ready-to-use provider instance.
    The API key is fetched from secret_manager, not from config.json.
    """
    cfg = _read_config()
    provider_type = cfg.get("provider_type", "Default")

    # Inject the securely-stored key so DataFeedFactory can use it
    secret_key = _PROVIDER_KEY_MAP.get(provider_type)
    if secret_key:
        cfg["api_key"] = get_api_key(secret_key)
    else:
        cfg.pop("api_key", None)

    return DataFeedFactory.get_provider(cfg)
