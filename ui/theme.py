"""
=========================================================
 AI Trader Pro - Institutional Trading Terminal Theme
=========================================================
All hardcoded pixel/font values replaced with scaling.py helpers.
Import S, SF, s, sf, fs, pad, wrap from ui.scaling — never hardcode
pixel sizes directly in widget constructors.
"""

import json
import os
import customtkinter as ctk

try:
    from utils.path_manager import get_config_path as _gcp
    _CONFIG_PATH = _gcp("config.json")
except Exception:
    _CONFIG_PATH = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
    )

def load_appearance_mode() -> str:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        mode = data.get("appearance_mode", "Dark")
        return mode if mode in ("Dark", "Light") else "Dark"
    except Exception:
        return "Dark"

def save_appearance_mode(mode: str) -> None:
    if mode not in ("Dark", "Light"):
        return
    try:
        data = {}
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["appearance_mode"] = mode
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

_ACTIVE_MODE = load_appearance_mode()
ctk.set_appearance_mode(_ACTIVE_MODE)
ctk.set_default_color_theme("blue")

# =========================================================
# COLOR PALETTES  (unchanged — colors are not pixel values)
# =========================================================

_DARK_PALETTE = {
    "APP_BG": "#0B0E14", "SIDEBAR_BG": "#121620", "CARD_BG": "#151924",
    "CARD_BG_ALT": "#1A1F2C", "PANEL_BG": "#151924", "INPUT_BG": "#0F131A",
    "WELL_BG": "#080A10",
    "BORDER": "#2B3139", "BORDER_LIGHT": "#3A4350", "BORDER_FOCUS": "#2962FF",
    "TEXT": "#E2E8F0", "TEXT_SECONDARY": "#94A3B8", "TEXT_MUTED": "#64748B", "LABEL": "#848E9C",
    "PRIMARY": "#2962FF", "PRIMARY_HOVER": "#4A7CFF", "CYAN": "#00E5FF", "GREEN": "#00C087",
    "RED": "#F6465D", "ORANGE": "#F5A623", "YELLOW": "#F8E71C", "PURPLE": "#B100E8",
    "BUY": "#00C087", "BUY_HOVER": "#00E5A0", "SELL": "#F6465D", "SELL_HOVER": "#FF6B7D",
    "NEUTRAL": "#F5A623", "ON_BUY": "#002B1E", "ON_SELL": "#3A0811", "GOLD": "#F0B429",
    "CHART_BG": "#0B0E14", "GRID": "#1A2234",
    "HOVER": "#1E2433", "HOVER_STRONG": "#2A3245", "ACTIVE": "#2962FF",
    "DISABLED": "#3A4350",
    "STATUS_HIGH": "#F6465D", "STATUS_MED": "#F5A623", "STATUS_LOW": "#2B3139",
}

_LIGHT_PALETTE = {
    "APP_BG": "#EEF1F7", "SIDEBAR_BG": "#FFFFFF", "CARD_BG": "#FFFFFF",
    "CARD_BG_ALT": "#F1F4F9", "PANEL_BG": "#FFFFFF", "INPUT_BG": "#F0F3F8",
    "WELL_BG": "#E7EBF3",
    "BORDER": "#DBE1EC", "BORDER_LIGHT": "#C4CCDD", "BORDER_FOCUS": "#3D6FE0",
    "TEXT": "#151B29", "TEXT_SECONDARY": "#48526A", "TEXT_MUTED": "#7C879C", "LABEL": "#71809A",
    "PRIMARY": "#3D6FE0", "PRIMARY_HOVER": "#5A87EC", "CYAN": "#0E9CB3", "GREEN": "#0C9C6E",
    "RED": "#DB3A58", "ORANGE": "#C97F1E", "YELLOW": "#C7A317", "PURPLE": "#8A5AD1",
    "BUY": "#0C9C6E", "BUY_HOVER": "#0A8760", "SELL": "#DB3A58", "SELL_HOVER": "#C22B47",
    "NEUTRAL": "#C97F1E", "ON_BUY": "#EAFBF3", "ON_SELL": "#FDECEF", "GOLD": "#C07A00",
    "CHART_BG": "#FFFFFF", "GRID": "#E3E8F1",
    "HOVER": "#E8ECF5", "HOVER_STRONG": "#DAE0EC", "ACTIVE": "#C4CCDD",
    "DISABLED": "#B7BFCF",
    "STATUS_HIGH": "#DB3A58", "STATUS_MED": "#C97F1E", "STATUS_LOW": "#DBE1EC",
}

class Colors:
    pass

def _apply_palette(mode: str):
    palette = _LIGHT_PALETTE if mode == "Light" else _DARK_PALETTE
    for key, value in palette.items():
        setattr(Colors, key, value)

_apply_palette(_ACTIVE_MODE)
CURRENT_MODE = _ACTIVE_MODE


# =========================================================
# FONTS — dynamic via scaling.py
# All Fonts.* attributes call the scaling system so they
# automatically return the right size for the current DPI.
# =========================================================

class Fonts:
    """
    Font descriptors.  Each attribute returns a fresh scaled tuple by
    calling the live scaling factor — so they always reflect the
    monitor/DPI the window is currently on.
    """
    # These are *properties* so every access calls scaling.fs()
    # We use lazy import to avoid circular imports at module load time.

    @staticmethod
    def _fs(size, weight="", family=""):
        try:
            from ui.scaling import fs as _scale_fs
            return _scale_fs(size, weight, family)
        except Exception:
            t = ("Segoe UI", size)
            return t + ((weight,) if weight else ())

    TITLE     = ("Inter", 22, "bold")    # fallback constants (used before scaling init)
    HEADER    = ("Inter", 17, "bold")
    SUBHEADER = ("Inter", 15, "bold")
    NORMAL    = ("Inter", 14)
    SMALL     = ("Inter", 12)
    TINY      = ("Inter", 11)
    PRICE     = ("Consolas", 19, "bold")
    MONO      = ("Consolas", 14)

    @classmethod
    def refresh(cls):
        """Update all class-level font tuples from the current scale factor."""
        cls.TITLE     = cls._fs(22, "bold")
        cls.HEADER    = cls._fs(17, "bold")
        cls.SUBHEADER = cls._fs(15, "bold")
        cls.NORMAL    = cls._fs(14)
        cls.SMALL     = cls._fs(12)
        cls.TINY      = cls._fs(11)
        cls.PRICE     = cls._fs(19, "bold", "Consolas")
        cls.MONO      = cls._fs(14, family="Consolas")


# =========================================================
# DIMENSIONAL CONSTANTS  — wrappers around scaling.py
# Keep the same class names (Card, Button, Window, Sidebar,
# Chart, Spacing, Order) so existing imports keep working.
# =========================================================

class Card:
    CORNER_RADIUS  = 8
    BORDER_WIDTH   = 1

    @staticmethod
    def PADX() -> int:
        from ui.scaling import s; return s(14)
    @staticmethod
    def PADY() -> int:
        from ui.scaling import s; return s(14)
    @staticmethod
    def INTERNAL_PAD() -> int:
        from ui.scaling import s; return s(10)


class Button:
    CORNER_RADIUS = 6

    @staticmethod
    def HEIGHT() -> int:
        from ui.scaling import s; return s(34)   # was 36
    @staticmethod
    def BIG_HEIGHT() -> int:
        from ui.scaling import s; return s(48)
    @staticmethod
    def FONT() -> tuple:
        from ui.scaling import fs; return fs(12, "bold")  # was 10


class Window:
    WIDTH      = 1760
    HEIGHT     = 980
    MIN_WIDTH  = 1024
    MIN_HEIGHT = 640

    @staticmethod
    def min_size():
        from ui.scaling import compute_min_size
        return compute_min_size()


class Sidebar:
    @staticmethod
    def WIDTH() -> int:
        from ui.scaling import s; return s(220)

    # Legacy int attribute kept for code that reads Sidebar.WIDTH directly
    # (updated by main_window after scaling.init())
    _width_cache: int = 220

    SECTION_HEIGHT  = 140
    WATCHLIST_HEIGHT = 360


class Chart:
    GRID_ALPHA  = 0.18
    CANDLE_UP   = Colors.BUY
    CANDLE_DOWN = Colors.SELL
    EMA20       = Colors.YELLOW
    EMA50       = Colors.CYAN
    SMA200      = Colors.PURPLE
    ENTRY       = Colors.PRIMARY
    STOPLOSS    = Colors.SELL
    TAKEPROFIT  = Colors.BUY
    EXTRA_HORIZONTAL_MARGIN = 200

    @staticmethod
    def HEIGHT() -> int:
        from ui.scaling import S; return S.CHART_H()


class Order:
    @staticmethod
    def BUY_HEIGHT() -> int:
        from ui.scaling import s; return s(54)
    @staticmethod
    def SELL_HEIGHT() -> int:
        from ui.scaling import s; return s(54)
    @staticmethod
    def STATUS_HEIGHT() -> int:
        from ui.scaling import s; return s(50)


class Spacing:
    @staticmethod
    def XS() -> int:  from ui.scaling import s; return s(4)
    @staticmethod
    def SM() -> int:  from ui.scaling import s; return s(8)
    @staticmethod
    def MD() -> int:  from ui.scaling import s; return s(14)
    @staticmethod
    def LG() -> int:  from ui.scaling import s; return s(20)
    @staticmethod
    def XL() -> int:  from ui.scaling import s; return s(28)
    @staticmethod
    def XXL()-> int:  from ui.scaling import s; return s(36)

    # Legacy integer constants (set at init time, used by code that
    # can't call the staticmethod form)
    XS_I  = 4
    SM_I  = 8
    MD_I  = 14
    LG_I  = 20
    XL_I  = 28
    XXL_I = 36


class Shadow:
    COLOR   = "#000000"
    OPACITY = 0.25


APP_NAME    = "AI Trader Pro"
APP_VERSION = "Professional Edition"
