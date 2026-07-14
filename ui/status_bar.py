"""
ui/status_bar.py
==================
Application-level footer status bar (optional standalone widget).
Not wired into main_window.py's dashboard bottom bar, but available
for embedding in any page frame if needed.
"""
from __future__ import annotations
import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors

_FOUNDER  = "Mohsin Abbas"
_VERSION  = "v2.0"
_APP_NAME = "AI Trader Pro"


class AppStatusBar(ctk.CTkFrame):
    """
    Thin footer bar showing:
      left  — connection / sync status text
      center — application branding (AI Trader Pro | Mohsin Abbas)
      right  — version
    """

    def __init__(self, parent, **kwargs):
        super().__init__(
            parent, height=S.ICON_BTN(), corner_radius=0,
            fg_color=Colors.SIDEBAR_BG,
            **kwargs,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)

        self._lbl_left = ctk.CTkLabel(
            self, text="", font=SF.STATUS(), text_color=Colors.TEXT_MUTED,
        )
        self._lbl_left.grid(row=0, column=0, sticky="w", padx=10)

        ctk.CTkLabel(
            self,
            text=f"{_APP_NAME}  ·  {_FOUNDER}",
            font=SF.STATUS(),
            text_color=Colors.LABEL,
        ).grid(row=0, column=1)

        ctk.CTkLabel(
            self,
            text=_VERSION,
            font=SF.MONO_SM(),
            text_color=Colors.TEXT_MUTED,
        ).grid(row=0, column=2, sticky="e", padx=10)

    def set_status(self, text: str, color: str | None = None):
        self._lbl_left.configure(
            text=text,
            text_color=color or Colors.TEXT_MUTED,
        )
