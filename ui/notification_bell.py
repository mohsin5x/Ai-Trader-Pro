"""
ui/notification_bell.py
========================
Notification Bell — unread badge + drop-down history panel.

Supports all notification types:
  buy, sell, ai_signal, high_confidence, paper_trade, market_news,
  warning, error, success, info, system, connection, api, market_alert
"""

import time
import tkinter as tk
import customtkinter as ctk

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts
from services.notification_center import nc, Notification

POLL_MS   = 1500    # badge refresh interval
MAX_SHOWN = 200     # max rows in panel

# ── Per-type icons and accent colours ─────────────────────────────────────
TYPE_META: dict[str, tuple[str, str]] = {
    "ai_signal":       ("🤖", "#2962FF"),
    "high_confidence": ("🔥", "#F5A623"),
    "buy":             ("📈", "#00C087"),
    "sell":            ("📉", "#F6465D"),
    "paper_trade":     ("📄", "#00C087"),
    "market_news":     ("📰", "#94A3B8"),
    "market_alert":    ("⚠️",  "#F5A623"),
    "warning":         ("⚠️",  "#F5A623"),
    "error":           ("❌", "#F6465D"),
    "success":         ("✅", "#00C087"),
    "info":            ("ℹ️",  "#2962FF"),
    "connection":      ("🔗", "#64748B"),
    "api":             ("🔌", "#64748B"),
    "system":          ("⚙️",  "#64748B"),
}


def _meta(ntype: str) -> tuple[str, str]:
    return TYPE_META.get(ntype, ("•", Colors.TEXT_SECONDARY))


class _NotificationPanel(ctk.CTkToplevel):
    """Drop-down notification history panel."""

    def __init__(self, parent_bell: "NotificationBell", on_close):
        # ── ROOT-CAUSE FIX ────────────────────────────────────────────
        # CRASH: RuntimeError "Too early to use font: no default root window"
        #
        # CTkToplevel.__init__ -> tk.Toplevel.__init__ temporarily disturbs
        # tkinter's internal _default_root on Windows.  Any CTk widget that
        # creates a CTkFont (CTkLabel, CTkButton, CTkScrollableFrame...)
        # during __init__ calls tkinter.font.Font() before _default_root is
        # re-established, causing the crash shown in the traceback.
        #
        # FIX: Two-phase init.
        #   Phase 1 (__init__): call super().__init__(), withdraw(), set
        #     geometry -- NO CTk widget construction at all.
        #   Phase 2 (_build_ui, scheduled via after(20, ...)): the Tk event
        #     loop has run at least once; _default_root is stable; build all
        #     widgets safely.  Then deiconify() to reveal the panel.
        # ─────────────────────────────────────────────────────────────
        try:
            root = parent_bell.winfo_toplevel()
        except Exception:
            root = None
        super().__init__(root)
        try:
            self.withdraw()                    # hide while building
        except Exception:
            pass

        self._parent_bell = parent_bell
        self._on_close    = on_close
        self.scroll       = None              # set in _build_ui

        _pw, _ph = s(450), s(560)
        self.configure(fg_color=Colors.SIDEBAR_BG)
        self.resizable(False, True)
        self.transient(root)

        # Geometry only -- no CTk widgets yet
        try:
            rx = parent_bell.winfo_rootx()
            ry = parent_bell.winfo_rooty() + parent_bell.winfo_height() + 6
            sw = self.winfo_screenwidth()
            x  = min(max(0, rx - 400), sw - 460)
            self.geometry(f"{_pw}x{_ph}+{x}+{ry}")
        except Exception:
            self.geometry(f"{_pw}x{_ph}")

        self.title("Notifications")
        self.protocol("WM_DELETE_WINDOW", self._close)

        # Defer ALL widget construction to after the event loop runs once.
        # This guarantees _default_root is stable before any CTkFont is created.
        self.after(20, self._build_ui)

    def _build_ui(self):
        """Phase 2: build all widgets once the Toplevel is fully initialised."""
        try:
            if not self.winfo_exists():
                return

            # ── Header ──────────────────────────────────────────────
            hdr = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, corner_radius=0, height=s(44))
            hdr.pack(fill="x")
            hdr.pack_propagate(False)

            ctk.CTkLabel(
                hdr, text="🔔  Notifications",
                font=SF.SUBHEADER(), text_color=Colors.TEXT,
            ).pack(side="left", padx=14, pady=10)

            ctk.CTkButton(
                hdr, text="✕ Clear", width=68, height=s(26), corner_radius=s(6),
                fg_color=Colors.CARD_BG_ALT, hover_color=Colors.SELL,
                text_color=Colors.TEXT_MUTED, font=SF.TINY(),
                command=self._clear_all,
            ).pack(side="right", padx=(0, 8), pady=9)

            ctk.CTkButton(
                hdr, text="✓ Mark all read", width=s(110), height=s(26), corner_radius=s(6),
                fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                text_color=Colors.TEXT, font=SF.TINY(),
                command=self._mark_all_read,
            ).pack(side="right", padx=4, pady=9)

            # ── Scrollable list ─────────────────────────────────────
            self.scroll = ctk.CTkScrollableFrame(
                self, fg_color=Colors.APP_BG, corner_radius=0,
                scrollbar_button_color=Colors.BORDER,
                scrollbar_button_hover_color=Colors.PRIMARY,
            )
            self.scroll.pack(fill="both", expand=True)
            self.scroll.grid_columnconfigure(0, weight=1)

            # Keyboard navigation
            self.bind("<Escape>", lambda _: self._close())
            self.bind("<Up>",     lambda _: self._scroll_step(-3))
            self.bind("<Down>",   lambda _: self._scroll_step(3))
            self.bind("<Prior>",  lambda _: self._scroll_step(-15))
            self.bind("<Next>",   lambda _: self._scroll_step(15))
            self.bind("<Home>",   lambda _: self._scroll_to(0.0))
            self.bind("<End>",    lambda _: self._scroll_to(1.0))

            self._render()

        except Exception:
            pass  # never crash the main thread

        # Reveal after one more event tick so canvas layout is complete
        self.after(10, self._on_mapped)

    # ── Scroll helpers ─────────────────────────────────────────────
    def _on_mapped(self):
        """Deferred show -- runs after event loop maps the window."""
        try:
            if not self.winfo_exists():
                return
            self.deiconify()
            self.lift()
            self.focus_set()
        except Exception:
            pass

    def _get_canvas(self):
        for attr in ("_parent_canvas", "_canvas", "canvas"):
            if hasattr(self.scroll, attr):
                c = getattr(self.scroll, attr)
                if hasattr(c, "yview_scroll"):
                    return c
        return None

    def _scroll_step(self, units: int):
        c = self._get_canvas()
        if c:
            c.yview_scroll(units, "units")

    def _scroll_to(self, frac: float):
        c = self._get_canvas()
        if c:
            c.yview_moveto(frac)

    # ── Rendering ──────────────────────────────────────────────────
    def _render(self):
        if self.scroll is None:
            return  # _build_ui not yet complete — safe to ignore
        for w in self.scroll.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        items = list(reversed(nc.get_all()))[:MAX_SHOWN]
        if not items:
            ctk.CTkLabel(
                self.scroll, text="No notifications yet.",
                font=SF.SMALL(), text_color=Colors.TEXT_MUTED,
            ).pack(pady=32)
            return

        for n in items:
            self._render_row(n)

    def _render_row(self, n: Notification):
        icon, accent = _meta(n.ntype)
        bg           = Colors.CARD_BG if n.read else Colors.WELL_BG
        title_color  = Colors.TEXT_MUTED if n.read else accent

        row = ctk.CTkFrame(
            self.scroll, fg_color=bg, corner_radius=s(6),
            border_width=1,
            border_color=Colors.BORDER if n.read else accent,
        )
        row.pack(fill="x", padx=6, pady=2)
        row.bind("<Button-1>", lambda _e, nid=n.nid: self._mark_one(nid))

        # Title row
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(5, 1))

        ctk.CTkLabel(
            top, text=f"{icon}  {n.title}",
            font=(Fonts.SMALL[0], Fonts.SMALL[1], "bold"),
            text_color=title_color, anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            top,
            text=time.strftime("%H:%M:%S", time.localtime(n.created_at)),
            font=SF.TINY(), text_color=Colors.TEXT_MUTED,
        ).pack(side="right")

        # Message
        ctk.CTkLabel(
            row, text=n.message,
            font=SF.TINY(), text_color=Colors.TEXT_SECONDARY,
            wraplength=s(400), anchor="w", justify="left",
        ).pack(fill="x", padx=8, pady=(0, 5))

    # ── Actions ────────────────────────────────────────────────────
    def _mark_one(self, nid: int):
        nc.mark_read(nid)
        self._render()

    def _mark_all_read(self):
        nc.mark_all_read()
        self._render()

    def _clear_all(self):
        nc.clear_all()
        self._render()

    def _close(self):
        self._on_close()
        try:
            self.destroy()
        except Exception:
            pass


class NotificationBell(ctk.CTkFrame):
    """
    Bell button + unread-count badge.
    Calls on_new_signal_popup(notification) for ai_signal / high_confidence types.
    """

    def __init__(self, parent, on_new_signal_popup=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._popup:               _NotificationPanel | None = None
        self._on_new_signal_popup = on_new_signal_popup
        self._last_count           = 0

        self.btn = ctk.CTkButton(
            self, text="🔔", width=38, height=S.ROW_H(), corner_radius=s(8),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT, font=SF.HEADER(),
            command=self._toggle_panel,
        )
        self.btn.pack(side="left")

        # Badge (plain tk.Label so we can use place() for absolute overlay)
        self.badge = tk.Label(
            self, text="", bg=Colors.SELL, fg="white",
            font=SF.STATUS_BOLD(), padx=3, pady=0,
            relief="flat", bd=0,
        )

        self._destroyed = False
        nc.add_listener(self._on_notification)
        self._schedule_badge()

    # ── Lifecycle ──────────────────────────────────────────────────
    def destroy(self):
        self._destroyed = True
        try:
            nc.remove_listener(self._on_notification)
        except Exception:
            pass
        try:
            super().destroy()
        except Exception:
            pass

    # ── Badge ──────────────────────────────────────────────────────
    def _schedule_badge(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            self._refresh_badge()
        except Exception:
            pass
        self.after(POLL_MS, self._schedule_badge)

    def _refresh_badge(self):
        try:
            count = nc.unread_count()
            if count != self._last_count:
                self._last_count = count
                if count > 0:
                    self.badge.configure(text=str(count) if count < 100 else "99+")
                    self.badge.place(relx=0.62, rely=0.0, anchor="nw")
                else:
                    self.badge.place_forget()
        except Exception:
            pass

    # ── Notification listener (any thread) ─────────────────────────
    def _on_notification(self, n: Notification):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            self.after(0, self._refresh_badge)
            if n.ntype in ("ai_signal", "high_confidence") and self._on_new_signal_popup:
                self.after(0, lambda: self._on_new_signal_popup(n))
            # If panel is open, refresh it live
            if self._popup:
                try:
                    if self._popup.winfo_exists():
                        self._popup.after(0, self._popup._render)
                except Exception:
                    pass
        except Exception:
            pass

    # ── Panel toggle ───────────────────────────────────────────────
    def _toggle_panel(self):
        if self._popup:
            try:
                if self._popup.winfo_exists():
                    self._popup._close()
                    self._popup = None
                    return
            except Exception:
                self._popup = None
        try:
            self._popup = _NotificationPanel(self, on_close=self._on_panel_closed)
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(
                f"[NotificationBell] Could not open panel: {_e}"
            )
            self._popup = None

    def _on_panel_closed(self):
        self._popup = None
        self._refresh_badge()
