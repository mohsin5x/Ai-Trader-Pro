"""
utils/secret_manager.py
=======================
Production-grade secret management for AI Trader Pro.

Priority order for API keys (highest to lowest):
  1. OS Keyring  (most secure — keys stored in OS credential store)
  2. Environment variables / .env file
  3. config.json  (user convenience — never commit with real keys)

Design rules:
  - Keys are NEVER logged, printed, or included in tracebacks.
  - get_api_key() always returns str (empty string if not found).
  - set_api_key() stores to OS Keyring when available, falls back to
    config.json when keyring is not installed or unavailable.
  - All operations are thread-safe.
  - Keyring failures are silent (logged at DEBUG only) so the app
    never crashes when the OS credential store is unavailable
    (e.g., headless CI/CD environments).
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from utils.logger import logger

# ── Optional Keyring import ────────────────────────────────────────────────
try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False
    logger.debug("[SecretManager] keyring not installed — using .env / config.json only.")

_SERVICE_NAME = "AITraderPro"
_lock = threading.Lock()


# ── Public API ─────────────────────────────────────────────────────────────

def get_api_key(provider: str) -> str:
    """
    Retrieve an API key for the given provider name.
    Returns empty string if no key is found in any source.

    provider examples: "twelvedata", "finnhub", "alphavantage"
    """
    key = _from_keyring(provider) or _from_env(provider) or _from_config(provider)
    return key or ""


def set_api_key(provider: str, key: str) -> bool:
    """
    Persist an API key for the given provider.
    Tries OS Keyring first, falls back to config.json.
    Returns True on success, False on failure.
    Key value is intentionally not logged.
    """
    if not key or not provider:
        return False

    if _KEYRING_AVAILABLE:
        try:
            keyring.set_password(_SERVICE_NAME, provider, key)
            logger.info(f"[SecretManager] API key for '{provider}' saved to OS Keyring.")
            return True
        except Exception as exc:
            logger.debug(f"[SecretManager] Keyring write failed ({type(exc).__name__}) — falling back to config.json.")

    return _to_config(provider, key)


def delete_api_key(provider: str) -> bool:
    """Remove a stored API key from all sources that hold it."""
    deleted = False

    if _KEYRING_AVAILABLE:
        try:
            keyring.delete_password(_SERVICE_NAME, provider)
            deleted = True
            logger.info(f"[SecretManager] Removed API key for '{provider}' from OS Keyring.")
        except Exception:
            pass

    # Clear from config.json too
    try:
        _clear_config(provider)
        deleted = True
    except Exception:
        pass

    return deleted


def has_api_key(provider: str) -> bool:
    """Return True if any key source has a non-empty key for this provider."""
    return bool(get_api_key(provider))


# ── Internal helpers ───────────────────────────────────────────────────────

def _from_keyring(provider: str) -> Optional[str]:
    if not _KEYRING_AVAILABLE:
        return None
    try:
        val = keyring.get_password(_SERVICE_NAME, provider)
        return val if val else None
    except Exception:
        return None


def _env_var_name(provider: str) -> str:
    """Map provider name to expected environment variable name."""
    _ENV_MAP = {
        "twelvedata":   "TWELVE_DATA_API_KEY",
        "finnhub":      "FINNHUB_API_KEY",
        "alphavantage": "ALPHA_VANTAGE_API_KEY",
    }
    return _ENV_MAP.get(provider.lower(), f"{provider.upper()}_API_KEY")


def _from_env(provider: str) -> Optional[str]:
    val = os.environ.get(_env_var_name(provider), "").strip()
    return val if val else None


def _get_config_path() -> str:
    try:
        from utils.path_manager import get_config_path
        return get_config_path("config.json")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
        )


def _from_config(provider: str) -> Optional[str]:
    """Read API key from config.json — only used as last resort."""
    import json
    try:
        with open(_get_config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        # config.json stores a single "api_key" for the current provider
        # We also check provider-specific keys for forward compatibility
        val = data.get(f"{provider}_api_key") or data.get("api_key") or ""
        return val.strip() if isinstance(val, str) and val.strip() else None
    except Exception:
        return None


def _to_config(provider: str, key: str) -> bool:
    """Write API key to config.json as fallback when keyring unavailable."""
    import json
    config_path = _get_config_path()
    with _lock:
        try:
            data = {}
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[f"{provider}_api_key"] = key
            # Also set generic api_key for the currently selected provider
            # so legacy code that only checks "api_key" still works
            if data.get("provider_type", "").lower().replace(" ", "") == provider.lower():
                data["api_key"] = key
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"[SecretManager] API key for '{provider}' saved to config.json.")
            return True
        except Exception as exc:
            logger.error(f"[SecretManager] Failed to save key for '{provider}': {exc}")
            return False


def _clear_config(provider: str):
    """Remove API key for provider from config.json."""
    import json
    config_path = _get_config_path()
    with _lock:
        if not os.path.exists(config_path):
            return
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.pop(f"{provider}_api_key", None)
        # Clear generic api_key if it matches this provider
        if data.get("provider_type", "").lower().replace(" ", "") == provider.lower():
            data["api_key"] = None
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
