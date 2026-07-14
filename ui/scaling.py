"""
ui/scaling.py
=============
AI Trader Pro — Centralized Adaptive Scaling Manager

This module is the SINGLE source of truth for all size/font/spacing
calculations. Every UI file imports from here instead of using hardcoded
numbers. The manager:

  1. Detects current screen resolution and DPI/OS scaling at startup.
  2. Computes a unified scale factor that accounts for both pixel density
     and OS Display Scaling (100 % – 300 %).
  3. Exposes typed helper functions:  s()  sf()  fs()  pad()  wrap()
  4. Registers a <Configure> callback on the root window so layout adapts
     live when the window is resized or dragged to a different monitor.
  5. Works correctly inside PyInstaller frozen EXEs and on Linux/macOS.

Usage:
    from ui.scaling import S, SF, s, sf, fs, pad, wrap, ScaledFonts, ScaledSizes

    # Integer size scaled to current DPI
    width = s(220)          # 220 at 100 % → 264 at 120 % DPI

    # Floating-point scale (for canvas math)
    ratio = sf(1.5)

    # Font tuple already scaled
    font = fs(12, "bold")          # ("Segoe UI", 14, "bold") at 120 % DPI
    font = fs(12, "bold", "Consolas")

    # Padding convenience
    px, py = pad(16, 8)            # (19, 10) at 120 %

    # Text wrap width in pixels
    w = wrap(320)
"""

from __future__ import annotations

import sys
import threading
import math
from typing import Tuple, Optional

import customtkinter as ctk

# ── Internal state ──────────────────────────────────────────────────────────
_lock            = threading.Lock()
_scale_factor: float = 1.0      # composite: DPI × OS scaling × window factor
_dpi_scale: float    = 1.0      # raw OS DPI scaling (from ctk or Windows API)
_win_w: int          = 1920
_win_h: int          = 1080
_screen_w: int       = 1920
_screen_h: int       = 1080
_root: Optional[object] = None  # weakref-style ref to root CTk window

# ── Reference design resolution ─────────────────────────────────────────────
_REF_W    = 1920
_REF_H    = 1080
_REF_FONT = 15          # base body font size at 1920×1080 @ 100 % (was 13 — increased for readability)

# ── Resolution breakpoints (width, height) → font base multiplier ───────────
#   Designed so fonts look natural at each resolution/DPI combo.
_BREAKPOINTS = [
    (3840, 2160, 1.80),   # 4K UHD
    (2560, 1440, 1.35),   # 2K QHD
    (1920, 1200, 1.10),   # WUXGA
    (1920, 1080, 1.00),   # Full HD  ← reference
    (1600,  900, 0.93),   # HD+
    (1366,  768, 0.87),   # HD laptop
    (1280,  720, 0.83),   # 720p
    (1024,  768, 0.78),   # XGA (minimum)
]


# ── Initialise ───────────────────────────────────────────────────────────────

def init(root) -> None:
    """
    Call once after the CTk root window is created and before any widgets.
    Stores a reference to the root and measures the initial screen metrics.
    """
    global _root
    _root = root
    _measure(root)
    # Re-measure on every window resize (debounced to 150 ms)
    root.bind("<Configure>", _on_configure, add="+")


def _measure(root) -> None:
    """Snapshot current screen + window metrics and recompute _scale_factor."""
    global _dpi_scale, _win_w, _win_h, _screen_w, _screen_h, _scale_factor

    # ── OS DPI/scaling factor ─────────────────────────────────────────
    dpi = 1.0
    try:
        dpi = ctk.ScalingTracker.get_window_scaling(root)
    except Exception:
        pass
    if dpi <= 0 or math.isnan(dpi):
        dpi = 1.0
    dpi = max(0.5, min(dpi, 4.0))

    # Windows-specific: also read the actual system DPI for sanity check
    if sys.platform == "win32":
        try:
            import ctypes
            hdc = ctypes.windll.user32.GetDC(0)
            raw_dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
            win_dpi = raw_dpi / 96.0
            # Use whichever is larger (CTk may report widget scaling, not monitor DPI)
            dpi = max(dpi, win_dpi)
        except Exception:
            pass

    # ── Screen resolution ─────────────────────────────────────────────
    try:
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        if sw > 0 and sh > 0:
            _screen_w, _screen_h = int(sw), int(sh)
    except Exception:
        pass

    # ── Window size (after first Map; defaults to screen size before that) ──
    try:
        w = root.winfo_width()
        h = root.winfo_height()
        if w > 100 and h > 100:
            _win_w, _win_h = int(w), int(h)
        else:
            _win_w, _win_h = _screen_w, _screen_h
    except Exception:
        _win_w, _win_h = _screen_w, _screen_h

    # ── Resolution-based font multiplier ─────────────────────────────
    res_mult = _resolution_multiplier(_screen_w, _screen_h)

    # ── Composite scale factor ────────────────────────────────────────
    # We blend DPI with the resolution breakpoint so the app looks right
    # both when Windows display scaling is used (same logical pixels, higher
    # physical DPI) and when the raw screen resolution is genuinely large
    # (4K without OS scaling).
    # Cap at 1.35 so fonts don't become oversized at 125-150% DPI on 1080p.
    composite = (dpi * 0.55 + res_mult * 0.45)
    composite = max(0.75, min(composite, 1.50))  # raised cap so fullscreen tabs don't clip

    with _lock:
        _dpi_scale    = dpi
        _scale_factor = composite


# ── Debounced resize handler ─────────────────────────────────────────────────
_resize_pending: Optional[str] = None   # after() ID

def _on_configure(event) -> None:
    global _resize_pending
    if _root is None:
        return
    try:
        if _resize_pending:
            _root.after_cancel(_resize_pending)
        # Use a longer delay (300 ms) so winfo_width/height reflect the
        # maximized size when Windows sends the <Configure> after zooming.
        _resize_pending = _root.after(300, _do_resize)
    except Exception:
        pass

def _do_resize() -> None:
    global _resize_pending
    _resize_pending = None
    if _root is None:
        return
    try:
        _measure(_root)
    except Exception:
        pass


# ── Resolution lookup ────────────────────────────────────────────────────────

def _resolution_multiplier(w: int, h: int) -> float:
    """Return the font/size multiplier for the given screen resolution."""
    for min_w, min_h, mult in _BREAKPOINTS:
        if w >= min_w and h >= min_h:
            return mult
    # Smaller than all breakpoints — use the smallest defined
    return _BREAKPOINTS[-1][2]


# ── Public scale factor accessors ────────────────────────────────────────────

def factor() -> float:
    """Current composite scale factor (thread-safe snapshot)."""
    with _lock:
        return _scale_factor

def dpi_factor() -> float:
    """Current OS DPI/display-scaling factor only."""
    with _lock:
        return _dpi_scale

def screen_size() -> Tuple[int, int]:
    with _lock:
        return _screen_w, _screen_h

def window_size() -> Tuple[int, int]:
    with _lock:
        return _win_w, _win_h


# ── Core helpers ─────────────────────────────────────────────────────────────

def s(value: int | float, *, min_val: int = 1) -> int:
    """
    Scale an integer pixel size (width, height, padding, margin…).
    Returns an int ≥ min_val.

    Example:
        s(220)   →  220 at 100 %,  264 at ~120 %,  396 at ~180 %
    """
    result = round(value * factor())
    return max(min_val, int(result))


def sf(value: float) -> float:
    """Scale a float (for canvas math, line widths, ratios)."""
    return float(value) * factor()


def fs(size: int, weight: str = "", family: str = "") -> tuple:
    """
    Return a scaled font tuple compatible with CTk / tkinter.

    Args:
        size:   Reference font size at 1920×1080 @ 100 %
        weight: "bold" | "italic" | "bold italic" | "" (normal)
        family: Font family name; defaults to "Segoe UI" on Windows,
                "SF Pro Display" on macOS, "Ubuntu" on Linux.

    Example:
        fs(13)          →  ("Segoe UI", 13)   at 100 %
        fs(13, "bold")  →  ("Segoe UI", 15, "bold")  at ~120 %
        fs(11, family="Consolas")  →  ("Consolas", 12)  at ~110 %
    """
    if not family:
        family = _default_font_family()
    scaled = max(7, round(size * factor()))
    if weight:
        return (family, scaled, weight)
    return (family, scaled)


def pad(x: int, y: int | None = None) -> Tuple[int, int]:
    """
    Return scaled (padx, pady) tuple.
    If y is None, returns (sx, sx) (uniform padding).
    """
    sx = s(x)
    sy = s(y if y is not None else x)
    return sx, sy


def wrap(width: int) -> int:
    """Return a scaled wraplength for CTkLabel.wraplength."""
    return s(width)


# ── Scaled constants (lazy-evaluated, always current) ───────────────────────

class S:
    """
    Namespace of pre-scaled dimensional constants.
    Access as  S.SIDEBAR_W,  S.NAV_BTN_H, etc.
    All values are recomputed from the current factor() each time.
    """

    # ── Sidebar ──────────────────────────────────────────────────────
    @staticmethod
    def SIDEBAR_W()    -> int: return s(220)
    @staticmethod
    def NAV_BTN_H()    -> int: return s(38)     # was 32 — increased to fit larger nav font
    @staticmethod
    def NAV_BTN_PAD()  -> int: return s(6)
    @staticmethod
    def LOGO_ICON_SZ() -> int: return s(18)

    # ── Top header bar ───────────────────────────────────────────────
    @staticmethod
    def HDR_H()        -> int: return s(62)     # was 58
    @staticmethod
    def PILL_H()       -> int: return s(34)     # was 30
    @staticmethod
    def BTN_H()        -> int: return s(34)     # was 30
    @staticmethod
    def BTN_H_LG()     -> int: return s(44)     # was 40
    @staticmethod
    def BTN_H_XL()     -> int: return s(56)     # was 52
    @staticmethod
    def BTN_W_SM()     -> int: return s(80)
    @staticmethod
    def BTN_W_MD()     -> int: return s(120)
    @staticmethod
    def BTN_W_LG()     -> int: return s(160)

    # ── Cards / KPI strip ────────────────────────────────────────────
    @staticmethod
    def CARD_PAD()     -> int: return s(12)
    @staticmethod
    def CARD_RADIUS()  -> int: return s(8)
    @staticmethod
    def KPI_H()        -> int: return s(68)

    # ── Chart ────────────────────────────────────────────────────────
    @staticmethod
    def CHART_H()      -> int: return _adaptive_chart_height()
    @staticmethod
    def CHART_TOOL_H() -> int: return s(38)
    @staticmethod
    def CHART_TF_H()   -> int: return s(22)

    # ── Right column ─────────────────────────────────────────────────
    @staticmethod
    def RIGHT_W()      -> int: return s(310)
    @staticmethod
    def NEWS_H()       -> int: return s(160)
    @staticmethod
    def SESSION_H()    -> int: return s(120)

    # ── Bottom row ───────────────────────────────────────────────────
    @staticmethod
    def BOTTOM_H()     -> int: return s(200)
    @staticmethod
    def STATUS_H()     -> int: return s(28)

    # ── Tables / rows ─────────────────────────────────────────────────
    @staticmethod
    def ROW_H()        -> int: return s(44)     # was 38
    @staticmethod
    def ROW_H_SM()     -> int: return s(34)     # was 28
    @staticmethod
    def ICON_BTN()     -> int: return s(24)

    # ── Spacing ───────────────────────────────────────────────────────
    @staticmethod
    def XS()  -> int: return s(4)
    @staticmethod
    def SM()  -> int: return s(8)
    @staticmethod
    def MD()  -> int: return s(14)
    @staticmethod
    def LG()  -> int: return s(20)
    @staticmethod
    def XL()  -> int: return s(28)
    @staticmethod
    def XXL() -> int: return s(36)

    # ── Avatar / icon sizes ───────────────────────────────────────────
    @staticmethod
    def AVATAR()       -> int: return s(42)
    @staticmethod
    def AVATAR_R()     -> int: return s(21)


class SF:
    """
    Namespace of pre-scaled font tuples.
    Use as  SF.TITLE(), SF.HEADER(), SF.NORMAL(), SF.MONO() etc.

    FONT SIZE GUIDE (at 1920x1080 100% DPI — all values +2 from original for readability):
      TITLE=22  HEADER=17  SUBHEADER=15  NORMAL=14  SMALL=12
      TINY=11   MICRO=10   NANO=9
    """
    @staticmethod
    def TITLE()      -> tuple: return fs(22, "bold")       # was 20
    @staticmethod
    def HEADER()     -> tuple: return fs(17, "bold")       # was 15
    @staticmethod
    def SUBHEADER()  -> tuple: return fs(15, "bold")       # was 13
    @staticmethod
    def NORMAL()     -> tuple: return fs(14)               # was 12
    @staticmethod
    def SMALL()      -> tuple: return fs(12)               # was 10
    @staticmethod
    def TINY()       -> tuple: return fs(11)               # was 9
    @staticmethod
    def MICRO()      -> tuple: return fs(10)               # was 8
    @staticmethod
    def NANO()       -> tuple: return fs(9)                # was 7

    # Monospaced
    @staticmethod
    def PRICE()      -> tuple: return fs(19, "bold", "Consolas")  # was 17
    @staticmethod
    def PRICE_SM()   -> tuple: return fs(14, "bold", "Consolas")  # was 12
    @staticmethod
    def MONO()       -> tuple: return fs(14, family="Consolas")    # was 12
    @staticmethod
    def MONO_SM()    -> tuple: return fs(12, family="Consolas")    # was 10
    @staticmethod
    def MONO_TINY()  -> tuple: return fs(11, family="Consolas")    # was 9

    # UI-specific
    @staticmethod
    def NAV()        -> tuple: return fs(13)               # was 11
    @staticmethod
    def NAV_BOLD()   -> tuple: return fs(13, "bold")       # was 11
    @staticmethod
    def LOGO()       -> tuple: return fs(13, "bold")       # was 11
    @staticmethod
    def LOGO_SUB()   -> tuple: return fs(9)                # was 7
    @staticmethod
    def PILL_LG()    -> tuple: return fs(12, "bold")       # was 10
    @staticmethod
    def PILL()       -> tuple: return fs(11)               # was 9
    @staticmethod
    def TAG()        -> tuple: return fs(9)                # was 6
    @staticmethod
    def STATUS()     -> tuple: return fs(10)               # was 8
    @staticmethod
    def STATUS_BOLD()-> tuple: return fs(11, "bold")       # was 9
    @staticmethod
    def BTN()        -> tuple: return fs(12, "bold")       # was 10
    @staticmethod
    def BTN_LG()     -> tuple: return fs(14, "bold")       # was 12


# ── Adaptive helpers ─────────────────────────────────────────────────────────

def _adaptive_chart_height() -> int:
    """
    Chart height is a fraction of the current window height so it always
    fills the available space without overflow.
    """
    with _lock:
        h = _win_h
    # Chart takes ~40 % of window height (minus header + KPIs + status bars)
    # but is clamped to a sensible min/max.
    raw = int(h * 0.42)
    return max(s(280), min(raw, s(800)))


def _default_font_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "SF Pro Display"
    return "Ubuntu"


# ── Wraplength helper for sidebar and panels ─────────────────────────────────

def sidebar_wrap() -> int:
    """Wraplength for labels inside the sidebar."""
    return S.SIDEBAR_W() - s(20)


def panel_wrap(ref: int = 300) -> int:
    """Wraplength for labels inside generic panels."""
    return s(ref)


# ── Min-window geometry helper ───────────────────────────────────────────────

def compute_min_size() -> Tuple[int, int]:
    """
    Return (min_width, min_height) appropriate for the current display.
    Ensures the window never becomes smaller than the smallest supported
    resolution (1024×768) while clamping on high-DPI so it doesn't exceed
    the screen.
    """
    sw, sh = screen_size()
    # Never demand more than 90 % of the physical screen
    min_w = max(900, min(s(1024), int(sw * 0.9)))
    min_h = max(600, min(s(768),  int(sh * 0.9)))
    return min_w, min_h


# ── Monitor-change detection ─────────────────────────────────────────────────

def poll_monitor_change(root, interval_ms: int = 5000) -> None:
    """
    Periodically check whether the DPI has changed (e.g. window moved to
    a different monitor) and re-measure if so.  Runs as a Tkinter after() loop.
    """
    _prev = [_dpi_scale]

    def _check():
        try:
            if not root.winfo_exists():
                return
            _measure(root)
            if abs(_dpi_scale - _prev[0]) > 0.05:
                _prev[0] = _dpi_scale
        except Exception:
            pass
        root.after(interval_ms, _check)

    root.after(interval_ms, _check)
