"""
utils/error_handler.py
=======================
Global error handler for AI Trader Pro.

Provides:
  • Automatic recovery for transient errors (network timeouts, rate limits)
  • Structured error logging with context
  • User-friendly error messages (no stack traces shown to end users)
  • Retry decorator for recoverable operations
"""
from __future__ import annotations

import functools
import time
import traceback
from typing import Callable, Any, Optional

from utils.logger import logger


class RecoverableError(Exception):
    """An error that can be retried after a short wait."""
    pass


class FatalError(Exception):
    """An error that cannot be recovered from automatically."""
    pass


def retry(max_attempts: int = 3, delay: float = 1.0,
          exceptions: tuple = (Exception,), label: str = "operation"):
    """
    Decorator: retry a function up to max_attempts times on failure.

    Args:
        max_attempts: Maximum number of tries.
        delay: Seconds to wait between retries (doubles each attempt).
        exceptions: Exception types that trigger a retry.
        label: Human-readable name for logging.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    wait = delay * (2 ** attempt)
                    logger.warning(
                        f"[{label}] Attempt {attempt + 1}/{max_attempts} failed: "
                        f"{type(exc).__name__}: {exc}. Retrying in {wait:.1f}s…"
                    )
                    if attempt < max_attempts - 1:
                        time.sleep(wait)
            logger.error(f"[{label}] All {max_attempts} attempts failed. Last: {last_exc}")
            raise last_exc
        return wrapper
    return decorator


def safe_call(fn: Callable, *args, default=None, label: str = "", **kwargs) -> Any:
    """
    Call fn safely, returning `default` on any exception.
    Logs the error with context for debugging.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        ctx = label or getattr(fn, "__name__", str(fn))
        logger.warning(f"[safe_call:{ctx}] {type(exc).__name__}: {exc}")
        return default


def format_user_error(exc: Exception) -> str:
    """Convert an exception to a clean user-facing message."""
    err_type = type(exc).__name__
    msg = str(exc)

    # Map known error types to friendly messages
    if "ConnectionError" in err_type or "Timeout" in err_type:
        return "Network connection lost. Retrying…"
    if "RateLimitError" in err_type or "429" in msg:
        return "API rate limit reached. Waiting before next request…"
    if "AuthError" in err_type or "401" in msg or "403" in msg:
        return "API authentication failed. Check your API key in Settings."
    if "JSONDecodeError" in err_type:
        return "Received invalid data from server. Will retry."
    if "PermissionError" in err_type:
        return "File access error. Check app folder permissions."

    # Generic fallback — avoid showing raw stack traces
    return f"Temporary error: {err_type}. The app will continue automatically."


def log_exception(exc: Exception, context: str = "") -> str:
    """Log a full exception with traceback and return the user-friendly message."""
    tb = traceback.format_exc()
    logger.error(f"[{context}] Exception:\n{tb}")
    return format_user_error(exc)
