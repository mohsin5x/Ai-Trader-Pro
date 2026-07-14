"""
utils/path_manager.py
=======================
Centralised, PyInstaller-aware path resolver for AI Trader Pro.

When running from source: paths resolve relative to the project root.
When frozen (PyInstaller EXE): user-writable files (databases, logs, config)
redirect to %LOCALAPPDATA%\\AI Trader Pro\\  (Windows) or ~/.ai_trader_pro/
(macOS/Linux) so they survive app updates and are never inside _MEIPASS.

Read-only assets (images, bundled data) always resolve from the bundle root
whether frozen or not.

Usage:
    from utils.path_manager import get_data_path, get_assets_path, get_logs_path

    db_path = get_data_path("paper_trading.db")    # writable
    icon    = get_assets_path("icon_32.png")       # read-only asset
    logfile = get_logs_path("ai_trader_pro.log")   # writable
"""
from __future__ import annotations
import os
import sys


def _app_root() -> str:
    """Project root whether running from source or frozen."""
    if getattr(sys, "frozen", False):
        # PyInstaller sets sys.executable to the .exe path
        return os.path.dirname(sys.executable)
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )


def _user_data_root() -> str:
    """
    Writable directory for user data.

    • Windows: %LOCALAPPDATA%\\AI Trader Pro
    • macOS:   ~/Library/Application Support/AI Trader Pro
    • Linux:   ~/.local/share/AI Trader Pro
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.path.expanduser("~/.local/share")
    path = os.path.join(base, "AI Trader Pro")
    os.makedirs(path, exist_ok=True)
    return path


def get_data_path(filename: str) -> str:
    """Path to a writable data file (databases, CSVs)."""
    if getattr(sys, "frozen", False):
        root = _user_data_root()
    else:
        root = os.path.join(_app_root(), "data")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, filename)


def get_logs_path(filename: str) -> str:
    """Path to a writable log file."""
    if getattr(sys, "frozen", False):
        root = os.path.join(_user_data_root(), "logs")
    else:
        root = os.path.join(_app_root(), "logs")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, filename)


def get_assets_path(filename: str) -> str:
    """Path to a read-only asset (images, icons)."""
    return os.path.join(_app_root(), "assets", filename)


def get_config_path(filename: str = "config.json") -> str:
    """Path to the main config.json (writable)."""
    if getattr(sys, "frozen", False):
        return os.path.join(_user_data_root(), filename)
    return os.path.join(_app_root(), filename)
