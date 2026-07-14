"""
ui/session_clock_panel.py
===========================
Compact sidebar Forex Market Sessions widget.

Design goals:
  • Minimal height — never pushes nav buttons off-screen
  • Shows OPEN / CLOSED for each of the 4 major sessions
  • Bottom line shows only the currently open market(s)
  • Updates every second, purely on the main thread (no background threads)
"""
import customtkinter as ctk
from datetime import datetime, timezone
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors

# (name, UTC open hour, UTC close hour)
SESSIONS = [
    ("Sydney",    22, 7),
    ("Tokyo",      0, 9),
    ("London",     8, 17),
    ("New York",  13, 22),
]

SESSION_FLAGS = {
    "Sydney":   "🇦🇺",
    "Tokyo":    "🇯🇵",
    "London":   "🇬🇧",
    "New York": "🇺🇸",
}

# Short names for the status line
SESSION_SHORT = {
    "Sydney":   "Sydney",
    "Tokyo":    "Tokyo",
    "London":   "London",
    "New York": "New York",
}


def is_session_open(hour: int, start: int, end: int) -> bool:
    """True if UTC hour falls inside the session window (handles midnight wrap)."""
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


class SessionClockPanel(ctk.CTkFrame):
    """
    Compact sidebar session indicator.
    Pure main-thread: uses .after(1000, self.refresh) — no worker threads.
    """

    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            fg_color=Colors.SIDEBAR_BG,
            corner_radius=s(6),
            border_width=1,
            border_color=Colors.BORDER,
            **kwargs,
        )
        self._destroyed = False

        # ── Header row: "SESSIONS" label + UTC clock ──────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(6, 2))
        ctk.CTkLabel(
            hdr, text="SESSIONS", font=SF.STATUS_BOLD(),
            text_color=Colors.LABEL,
        ).pack(side="left")
        self._lbl_utc = ctk.CTkLabel(
            hdr, text="", font=SF.MONO_TINY(),
            text_color=Colors.TEXT_MUTED,
        )
        self._lbl_utc.pack(side="right")

        # ── Session rows (one per market) ─────────────────────────────
        sessions_frame = ctk.CTkFrame(self, fg_color="transparent")
        sessions_frame.pack(fill="x", padx=8)

        self._rows: dict[str, dict] = {}
        for name, start, end in SESSIONS:
            flag = SESSION_FLAGS.get(name, "")
            row  = ctk.CTkFrame(sessions_frame, fg_color="transparent")
            row.pack(fill="x", pady=0)

            lbl_name = ctk.CTkLabel(
                row,
                text=f"{flag} {name}",
                font=SF.STATUS(),
                text_color=Colors.TEXT_MUTED,
                anchor="w",
            )
            lbl_name.pack(side="left")

            lbl_status = ctk.CTkLabel(
                row,
                text="○",
                font=SF.STATUS_BOLD(),
                text_color=Colors.TEXT_MUTED,
                anchor="e",
            )
            lbl_status.pack(side="right")

            self._rows[name] = {
                "name_lbl":   lbl_name,
                "status_lbl": lbl_status,
            }

        # ── Bottom status line: "🟢 Open Now: London & New York" ──────
        self._lbl_open_now = ctk.CTkLabel(
            self,
            text="",
            font=SF.STATUS_BOLD(),
            text_color=Colors.BUY,
            anchor="w",
        )
        self._lbl_open_now.pack(fill="x", padx=8, pady=(2, 6))

        self.refresh()

    # ─────────────────────────────────────────────────────────────────
    def refresh(self):
        if self._destroyed:
            return

        now_utc      = datetime.now(timezone.utc)
        hour         = now_utc.hour
        open_sessions: list[str] = []

        for name, start, end in SESSIONS:
            open_now = is_session_open(hour, start, end)
            row      = self._rows[name]

            if open_now:
                open_sessions.append(name)
                row["name_lbl"].configure(text_color=Colors.TEXT_SECONDARY)
                row["status_lbl"].configure(text="●", text_color=Colors.BUY)
            else:
                row["name_lbl"].configure(text_color=Colors.TEXT_MUTED)
                row["status_lbl"].configure(text="○", text_color=Colors.TEXT_MUTED)

        self._lbl_utc.configure(text=now_utc.strftime("%H:%M UTC"))

        if open_sessions:
            joined = " & ".join(SESSION_SHORT[s] for s in open_sessions)
            self._lbl_open_now.configure(
                text=f"🟢 Open: {joined}",
                text_color=Colors.BUY,
            )
        else:
            self._lbl_open_now.configure(
                text="🔴 All sessions closed",
                text_color=Colors.TEXT_MUTED,
            )

        self.after(1000, self.refresh)

    def destroy(self):
        self._destroyed = True
        try:
            super().destroy()
        except Exception:
            pass
