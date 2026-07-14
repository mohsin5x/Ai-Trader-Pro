"""
utils/notifications.py
========================
Desktop push-notification helper for AI Trader Pro.

Uses plyer if available (cross-platform desktop notifications).
Falls back to a silent no-op so the rest of the app never crashes
when plyer is absent or when running headless / in environments that
don't support system notifications (e.g. CI, Linux without libnotify).
"""
from __future__ import annotations

try:
    from plyer import notification as _plyer_notification
    _PLYER_OK = True
except Exception:
    _plyer_notification = None   # type: ignore[assignment]
    _PLYER_OK = False


def trigger_alert(title: str, message: str, timeout: int = 5) -> None:
    """
    Fire a system desktop notification.

    Safe to call from any thread.  If plyer is unavailable or the
    notification subsystem errors, the call is silently swallowed so
    the trading pipeline is never interrupted.
    """
    if not _PLYER_OK or _plyer_notification is None:
        return
    try:
        _plyer_notification.notify(
            title=title,
            message=message,
            app_name="AI Trader Pro",
            timeout=timeout,
        )
    except Exception:
        pass
