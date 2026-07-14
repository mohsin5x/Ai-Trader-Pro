"""
=========================================================
 AI Trader Pro - Reusable UI Components
=========================================================
"""

import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Card, Button


class Panel(ctk.CTkFrame):
    def __init__(self, master, title="", **kwargs):
        super().__init__(
            master,
            fg_color=Colors.CARD_BG,
            corner_radius=S.CARD_RADIUS(),
            border_width=Card.BORDER_WIDTH,
            border_color=Colors.BORDER,
            **kwargs
        )
        self.grid_columnconfigure(0, weight=1)
        self._next_row = 0

        if title:
            self.title = ctk.CTkLabel(
                self, text=title, font=SF.HEADER(), text_color=Colors.TEXT, anchor="w"
            )
            self.title.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
            self._next_row = 1
            
            Divider(self).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
            self._next_row = 2


class SectionTitle(ctk.CTkLabel):
    def __init__(self, master, text):
        super().__init__(
            master, text=text, font=SF.SUBHEADER(), text_color=Colors.TEXT
        )


class ValueLabel(ctk.CTkLabel):
    def __init__(self, master, text="--"):
        super().__init__(
            master, text=text, font=SF.PRICE(), text_color=Colors.TEXT
        )


class SecondaryLabel(ctk.CTkLabel):
    def __init__(self, master, text=""):
        super().__init__(
            master, text=text, font=SF.SMALL(), text_color=Colors.TEXT_SECONDARY
        )


class PrimaryButton(ctk.CTkButton):
    def __init__(self, master, text, command=None):
        super().__init__(
            master, text=text, command=command,
            height=S.BTN_H(), corner_radius=Button.CORNER_RADIUS,
            fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
            text_color="white", font=SF.NORMAL()
        )


class BuyButton(ctk.CTkButton):
    def __init__(self, master, command=None):
        super().__init__(
            master, text="BUY", command=command,
            height=S.BTN_H_XL(), corner_radius=Button.CORNER_RADIUS,
            fg_color=Colors.BUY, hover_color=Colors.BUY_HOVER,
            font=SF.SUBHEADER(), text_color="white"
        )


class SellButton(ctk.CTkButton):
    def __init__(self, master, command=None):
        super().__init__(
            master, text="SELL", command=command,
            height=S.BTN_H_XL(), corner_radius=Button.CORNER_RADIUS,
            fg_color=Colors.SELL, hover_color=Colors.SELL_HOVER,
            font=SF.SUBHEADER(), text_color="white"
        )


class MetricBox(ctk.CTkFrame):
    def __init__(self, master, title, value="--"):
        super().__init__(
            master, fg_color=Colors.INPUT_BG,
            corner_radius=S.CARD_RADIUS(), border_width=1, border_color=Colors.BORDER
        )
        ctk.CTkLabel(
            self, text=title, font=SF.SMALL(), text_color=Colors.TEXT_SECONDARY
        ).pack(pady=(10, 2))
        
        self.value = ctk.CTkLabel(
            self, text=value, font=SF.PRICE(), text_color=Colors.TEXT
        )
        self.value.pack(pady=(0, 10))

    def set(self, value):
        self.value.configure(text=value)


class StatusBadge(ctk.CTkLabel):
    def __init__(self, master, text="READY", color=Colors.GREEN):
        super().__init__(
            master, text=text, fg_color=color, corner_radius=s(8),
            text_color="white", padx=10, pady=4, font=SF.SMALL()
        )


class Divider(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, height=1, fg_color=Colors.BORDER)


class StyledComboBox(ctk.CTkComboBox):
    def __init__(self, master, values):
        super().__init__(
            master, values=values,
            fg_color=Colors.INPUT_BG, border_color=Colors.BORDER,
            button_color=Colors.INPUT_BG, button_hover_color=Colors.HOVER,
            dropdown_fg_color=Colors.CARD_BG_ALT, dropdown_hover_color=Colors.HOVER,
            dropdown_text_color=Colors.TEXT, text_color=Colors.TEXT,
            corner_radius=s(6), border_width=1
        )


class StyledEntry(ctk.CTkEntry):
    def __init__(self, master, placeholder=""):
        super().__init__(
            master, placeholder_text=placeholder,
            fg_color=Colors.INPUT_BG, border_color=Colors.BORDER,
            text_color=Colors.TEXT, corner_radius=s(6), border_width=1
        )

# ──────────────────────────────────────────────────────────────────────────────
# Scroll helpers — fast mousewheel + keyboard navigation for CTkScrollableFrame
# ──────────────────────────────────────────────────────────────────────────────

def _get_scroll_canvas(frame):
    """Return the internal canvas of a CTkScrollableFrame, or None."""
    for attr in ("_parent_canvas", "_canvas", "canvas"):
        if hasattr(frame, attr):
            c = getattr(frame, attr)
            if hasattr(c, "yview_scroll"):
                return c
    return None


def bind_fast_scroll(frame, multiplier: int = 6):
    """Attach fast mousewheel + keyboard scrolling to a CTkScrollableFrame.

    Call once after creating the frame. Recurses into children so rows
    added later via pack/grid inside the frame also scroll correctly.
    Multiplier controls scroll speed (default 6 units per notch).
    """
    def _fast_wheel(event, _f=frame):
        canvas = _get_scroll_canvas(_f)
        if canvas is None:
            return
        # Windows: delta in multiples of 120; Mac: smaller values
        delta = getattr(event, "delta", 0)
        if delta:
            units = -int(delta / 20)
            if units == 0:
                units = 1 if delta < 0 else -1
        else:
            units = multiplier
        canvas.yview_scroll(units, "units")
        return "break"

    def _linux_up(event, _f=frame):
        c = _get_scroll_canvas(_f)
        if c:
            c.yview_scroll(-multiplier, "units")
        return "break"

    def _linux_down(event, _f=frame):
        c = _get_scroll_canvas(_f)
        if c:
            c.yview_scroll(multiplier, "units")
        return "break"

    def _key_up(event, _f=frame):
        c = _get_scroll_canvas(_f)
        if c:
            c.yview_scroll(-3, "units")

    def _key_down(event, _f=frame):
        c = _get_scroll_canvas(_f)
        if c:
            c.yview_scroll(3, "units")

    def _key_pgup(event, _f=frame):
        c = _get_scroll_canvas(_f)
        if c:
            c.yview_scroll(-15, "units")

    def _key_pgdn(event, _f=frame):
        c = _get_scroll_canvas(_f)
        if c:
            c.yview_scroll(15, "units")

    def _key_home(event, _f=frame):
        c = _get_scroll_canvas(_f)
        if c:
            c.yview_moveto(0.0)

    def _key_end(event, _f=frame):
        c = _get_scroll_canvas(_f)
        if c:
            c.yview_moveto(1.0)

    def _recurse(widget):
        widget.bind("<MouseWheel>", _fast_wheel, add="+")
        widget.bind("<Button-4>",   _linux_up,   add="+")
        widget.bind("<Button-5>",   _linux_down, add="+")
        # Keyboard nav (only fires when widget or child has focus)
        widget.bind("<Up>",    _key_up,   add="+")
        widget.bind("<Down>",  _key_down, add="+")
        widget.bind("<Prior>", _key_pgup, add="+")
        widget.bind("<Next>",  _key_pgdn, add="+")
        widget.bind("<Home>",  _key_home, add="+")
        widget.bind("<End>",   _key_end,  add="+")
        for child in widget.winfo_children():
            _recurse(child)

    _recurse(frame)


def setup_scrollable_frame(frame: "ctk.CTkScrollableFrame",
                            grid_columns: int = 1) -> "ctk.CTkScrollableFrame":
    """
    One-call setup for a CTkScrollableFrame:
      - columnconfigure with weight=1 for all columns
      - bind_fast_scroll for smooth + keyboard scrolling
    Returns the frame for chaining.
    """
    for i in range(grid_columns):
        frame.grid_columnconfigure(i, weight=1)
    bind_fast_scroll(frame)
    return frame
