"""
ui/splash_screen.py  (FIXED 2026-07-13)
========================================
Startup splash screen for AI Trader Pro.

FIX: Original code used SF.MONO_SM() / SF.NAV() / SF.TINY() before
scaling.init() is called — SF requires a live CTk root, so calling it
from a plain tk.Tk splash causes AttributeError / NameError crashes that
silently killed the splash and sometimes the whole startup sequence.

Resolution: use plain tk font tuples for the splash overlay text.
The splash is destroyed long before the main window is shown so there is
no visual inconsistency.
"""
from __future__ import annotations
import os
import tkinter as tk

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

_SPLASH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "splash_screen.png",
)
_DURATION_MS = 2600

APP_VERSION = "2.0"
APP_FOUNDER = "Mohsin Abbas"

# Plain font tuples — no dependency on scaling.py or theme.py
_FONT_MONO  = ("Consolas", 9)
_FONT_NAV   = ("Segoe UI", 10)
_FONT_TINY  = ("Segoe UI", 8)


class SplashScreen:
    """
    Borderless, centred splash window.
    Call show() before creating MainWindow, close() after.
    """

    def __init__(self):
        self._win: tk.Tk | None = None

    def show(self):
        if not _PIL_OK or not os.path.exists(_SPLASH_PATH):
            return

        try:
            self._win = tk.Tk()
            # Withdraw immediately — prevents the bare Tk frame from
            # flashing as a "default root" window before we style it.
            self._win.withdraw()
            self._win.overrideredirect(True)
            self._win.attributes("-topmost", True)
            self._win.configure(bg="#0B0E14")

            pil_img = Image.open(_SPLASH_PATH)
            sw, sh  = pil_img.size
            scr_w   = self._win.winfo_screenwidth()
            scr_h   = self._win.winfo_screenheight()
            x = (scr_w - sw) // 2
            y = (scr_h - sh) // 2
            self._win.geometry(f"{sw}x{sh}+{x}+{y}")

            tk_img = ImageTk.PhotoImage(pil_img)
            canvas = tk.Canvas(
                self._win, width=sw, height=sh,
                bg="#0B0E14", highlightthickness=0, bd=0
            )
            canvas.pack()
            canvas.create_image(0, 0, anchor="nw", image=tk_img)
            canvas.image = tk_img   # keep reference alive

            # Version overlay (bottom-left) — plain font tuple, no SF dependency
            canvas.create_text(
                16, sh - 32,
                anchor="sw",
                text=f"Version {APP_VERSION}",
                fill="#94A3B8",
                font=_FONT_MONO,
            )
            # Founder overlay (bottom-right)
            canvas.create_text(
                sw - 16, sh - 32,
                anchor="se",
                text=f"Owner & Founder: {APP_FOUNDER}",
                fill="#F0B429",
                font=_FONT_NAV,
            )
            # Copyright line
            canvas.create_text(
                sw // 2, sh - 14,
                anchor="s",
                text=f"\u00a9 2025 {APP_FOUNDER}  \u00b7  AI Trader Pro  \u00b7  All rights reserved.",
                fill="#64748B",
                font=_FONT_TINY,
            )

            self._win.update()
            # Now show — geometry and content are fully set, no bare frame flash
            self._win.deiconify()

        except Exception as e:
            print(f"[SplashScreen] warning: {e}")
            if self._win:
                try:
                    self._win.destroy()
                except Exception:
                    pass
            self._win = None

    def close(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None

    def show_and_wait(self):
        """Show splash and block for _DURATION_MS, then close."""
        self.show()
        if self._win:
            self._win.after(_DURATION_MS, self.close)
            try:
                self._win.mainloop()
            except Exception:
                pass
