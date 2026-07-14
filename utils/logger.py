"""
utils/logger.py
================
Centralized logger for AI Trader Pro.
Logs to both console and a rotating file in the logs/ directory.
Uses path_manager so the log file is always writable, even in a
PyInstaller-frozen EXE (where logs/ inside _MEIPASS is read-only).
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# ── Log path (EXE-safe) ────────────────────────────────────────────────
try:
    from utils.path_manager import get_logs_path as _glp
    _LOG_FILE = _glp("ai_trader_pro.log")
    _LOG_DIR  = os.path.dirname(_LOG_FILE)
except Exception:
    _LOG_DIR  = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
    )
    _LOG_FILE = os.path.join(_LOG_DIR, "ai_trader_pro.log")

os.makedirs(_LOG_DIR, exist_ok=True)

# ── Format ─────────────────────────────────────────────────────────────
_FMT      = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _build_logger(name: str = "AITraderPro") -> logging.Logger:
    log = logging.getLogger(name)
    if log.handlers:
        return log          # already configured

    log.setLevel(logging.DEBUG)

    # Console handler — INFO and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(_FMT, _DATE_FMT))
    log.addHandler(ch)

    # Rotating file handler — DEBUG and above (5 MB × 3 backup files)
    try:
        fh = RotatingFileHandler(
            _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_FMT, _DATE_FMT))
        log.addHandler(fh)
    except Exception as e:
        log.warning(f"Could not create log file handler: {e}")

    return log


logger = _build_logger()


def get_logger(name: str) -> logging.Logger:
    """Get a child logger namespaced under AITraderPro."""
    return logging.getLogger(f"AITraderPro.{name}")
