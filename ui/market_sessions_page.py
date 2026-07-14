"""
ui/market_sessions_page.py
============================
Dedicated Market Sessions full page.

Sections:
  • Live session clocks with Open/Closed, countdown to open/close
  • Session overlaps with volatility notes
  • Trading hours table
  • Major active pairs per session
  • Volatility indicators per session
  • Best trading windows summary

All updates on the main thread via .after() — no background threads.
"""
from __future__ import annotations
import customtkinter as ctk
from datetime import datetime, timezone, timedelta
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None

# ── Session definitions ───────────────────────────────────────────────────────
# (name, UTC open hour, UTC close hour, hex_color, flag, continent)
SESSIONS_FULL = [
    ("Sydney",    22, 7,  "#00C087", "🇦🇺", "Asia-Pacific"),
    ("Tokyo",      0, 9,  "#2962FF", "🇯🇵", "Asia"),
    ("London",     8, 17, "#F5A623", "🇬🇧", "Europe"),
    ("New York",  13, 22, "#F6465D", "🇺🇸", "Americas"),
]

# Major pairs per session
SESSION_PAIRS = {
    "Sydney":   ["AUD/USD", "AUD/JPY", "NZD/USD", "AUD/NZD", "USD/JPY"],
    "Tokyo":    ["USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/JPY", "CHF/JPY"],
    "London":   ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/JPY"],
    "New York": ["EUR/USD", "USD/CAD", "USD/JPY", "GBP/USD", "USD/CHF"],
}

# Volatility characteristics
SESSION_VOLATILITY = {
    "Sydney":   ("Low–Medium", "Quieter session; AUD and NZD pairs most active."),
    "Tokyo":    ("Medium",     "JPY pairs dominate; EUR/USD relatively quiet."),
    "London":   ("High",       "Highest liquidity; most major pairs move strongly."),
    "New York": ("High",       "Strong momentum; major economic releases at open."),
}

# Overlap windows (pair of session names, description)
OVERLAPS = [
    ("Tokyo",    "London",   "Tokyo/London Overlap",   "08:00–09:00 UTC",
     "EUR/JPY, GBP/JPY active. Transitional — moderate volatility."),
    ("London",   "New York", "London/New York Overlap", "13:00–17:00 UTC",
     "Peak liquidity window of the day. EUR/USD, GBP/USD, USD/JPY very active. Best spreads."),
]


def is_weekend(weekday: int, hour: int, minute: int) -> bool:
    """
    Forex/Crypto markets close Friday ~22:00 UTC and reopen Sunday ~22:00 UTC.
    weekday: 0=Monday … 4=Friday, 5=Saturday, 6=Sunday
    """
    if weekday == 5:                          # All of Saturday
        return True
    if weekday == 4 and hour >= 22:           # Friday after 22:00 UTC
        return True
    if weekday == 6 and (hour < 22 or (hour == 22 and minute == 0)):  # Sunday before 22:00
        return True
    return False


def is_open(hour: int, start: int, end: int) -> bool:
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def minutes_to_open(hour: int, minute: int, start: int) -> int:
    """Minutes until session opens (0 if already open)."""
    current_mins = hour * 60 + minute
    open_mins    = start * 60
    diff = (open_mins - current_mins) % (24 * 60)
    return diff


def minutes_to_close(hour: int, minute: int, end: int) -> int:
    """Minutes until session closes (0 if already closed)."""
    current_mins = hour * 60 + minute
    close_mins   = end * 60
    diff = (close_mins - current_mins) % (24 * 60)
    return diff


def minutes_to_sunday_open(weekday: int, hour: int, minute: int) -> int:
    """Minutes until Sunday 22:00 UTC (market reopen after weekend)."""
    current_mins = hour * 60 + minute
    # days until Sunday
    days_to_sunday = (6 - weekday) % 7
    if weekday == 6 and (hour < 22):
        days_to_sunday = 0
    elif weekday == 6 and hour >= 22:
        days_to_sunday = 7
    target_mins = days_to_sunday * 24 * 60 + 22 * 60  # Sunday 22:00
    diff = target_mins - current_mins
    if diff <= 0:
        diff += 7 * 24 * 60
    return diff


def fmt_duration(total_minutes: int) -> str:
    h = total_minutes // 60
    m = total_minutes % 60
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


# ── Session card ─────────────────────────────────────────────────────────────
class _SessionCard(ctk.CTkFrame):
    def __init__(self, parent, name: str, start: int, end: int,
                 color: str, flag: str, continent: str):
        super().__init__(
            parent,
            fg_color=Colors.CARD_BG,
            border_width=2,
            border_color=Colors.BORDER,
            corner_radius=s(10),
        )
        self._name      = name
        self._start     = start
        self._end       = end
        self._color     = color
        self._destroyed = False

        # Top accent bar (session color)
        ctk.CTkFrame(self, fg_color=color, height=4, corner_radius=0).pack(fill="x")

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            hdr, text=f"{flag} {name}", font=SF.SUBHEADER(),
            text_color=Colors.TEXT,
        ).pack(side="left")

        self._lbl_badge = ctk.CTkLabel(
            hdr, text=" CLOSED ",
            font=SF.STATUS_BOLD(),
            fg_color=Colors.BORDER, text_color=Colors.TEXT_MUTED,
            corner_radius=s(4),
        )
        self._lbl_badge.pack(side="right")

        ctk.CTkLabel(
            hdr, text=continent, font=SF.TINY(),
            text_color=Colors.TEXT_MUTED,
        ).pack(side="right", padx=6)

        # Hours
        hours_txt = f"{start:02d}:00 – {end:02d}:00 UTC"
        ctk.CTkLabel(
            self, text=hours_txt, font=SF.MONO_SM(),
            text_color=Colors.TEXT_SECONDARY,
        ).pack(anchor="w", padx=14, pady=(0, 4))

        # Countdown
        self._lbl_countdown = ctk.CTkLabel(
            self, text="",
            font=SF.MONO(),
            text_color=color,
        )
        self._lbl_countdown.pack(anchor="w", padx=14, pady=(0, 6))

        # Volatility
        vol_level, vol_desc = SESSION_VOLATILITY.get(name, ("—", ""))
        vol_frame = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(6))
        vol_frame.pack(fill="x", padx=14, pady=(0, 6))
        v_inner = ctk.CTkFrame(vol_frame, fg_color="transparent")
        v_inner.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            v_inner, text="Volatility:", font=SF.STATUS_BOLD(),
            text_color=Colors.LABEL,
        ).pack(side="left")
        ctk.CTkLabel(
            v_inner, text=vol_level, font=SF.STATUS_BOLD(),
            text_color=color,
        ).pack(side="left", padx=6)
        ctk.CTkLabel(
            self, text=vol_desc, font=SF.TINY(),
            text_color=Colors.TEXT_MUTED, wraplength=s(260), justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 6))

        # Major pairs
        pairs = SESSION_PAIRS.get(name, [])
        pairs_frame = ctk.CTkFrame(self, fg_color="transparent")
        pairs_frame.pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkLabel(
            pairs_frame, text="Major pairs: ", font=SF.STATUS_BOLD(),
            text_color=Colors.LABEL,
        ).pack(side="left")
        for pair in pairs[:4]:
            ctk.CTkLabel(
                pairs_frame, text=pair,
                font=SF.MONO_TINY(), text_color=Colors.TEXT_SECONDARY,
                fg_color=Colors.SIDEBAR_BG, corner_radius=s(4), padx=5, pady=2,
            ).pack(side="left", padx=2)

    def tick(self, hour: int, minute: int, weekday: int = 0):
        if self._destroyed:
            return
        weekend = is_weekend(weekday, hour, minute)
        if weekend:
            mins_to_reopen = minutes_to_sunday_open(weekday, hour, minute)
            self._lbl_badge.configure(
                text=" WEEKEND ", fg_color="#3A2A00", text_color="#F5A623")
            self._lbl_countdown.configure(
                text=f"Opens in {fmt_duration(mins_to_reopen)}  (Sun 22:00 UTC)",
                text_color="#F5A623")
            self.configure(border_color="#3A2A00")
            return
        open_now = is_open(hour, self._start, self._end)
        if open_now:
            mins = minutes_to_close(hour, minute, self._end)
            self._lbl_badge.configure(
                text=" OPEN ", fg_color=self._color, text_color="#FFFFFF")
            self._lbl_countdown.configure(
                text=f"Closes in {fmt_duration(mins)}", text_color=self._color)
            self.configure(border_color=self._color)
        else:
            mins = minutes_to_open(hour, minute, self._start)
            self._lbl_badge.configure(
                text=" CLOSED ", fg_color=Colors.BORDER, text_color=Colors.TEXT_MUTED)
            self._lbl_countdown.configure(
                text=f"Opens in {fmt_duration(mins)}", text_color=Colors.TEXT_MUTED)
            self.configure(border_color=Colors.BORDER)

    def destroy(self):
        self._destroyed = True
        try:
            super().destroy()
        except Exception:
            pass


# ── Main page ─────────────────────────────────────────────────────────────────
class MarketSessionsPage(ctk.CTkFrame):
    """Full-page market sessions view with live clocks and countdowns."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=Colors.APP_BG, corner_radius=0, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._destroyed = False
        self._cards: list[_SessionCard] = []

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(),
                 pady=(Spacing.LG(), Spacing.MD()))
        ctk.CTkLabel(hdr, text="MARKET SESSIONS", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")
        self._lbl_clock = ctk.CTkLabel(
            hdr, text="",
            font=SF.PRICE_SM(), text_color=Colors.TEXT_SECONDARY,
        )
        self._lbl_clock.pack(side="right")

        # ── Scrollable body ───────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.PRIMARY,
        )
        scroll.grid(row=1, column=0, sticky="nsew",
                    padx=Spacing.LG(), pady=(0, Spacing.LG()))
        scroll.grid_columnconfigure(0, weight=1)
        bind_fast_scroll(scroll)

        # ── Session cards (2-column grid) ─────────────────────────────
        cards_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        cards_frame.pack(fill="x", pady=(0, 16))
        cards_frame.grid_columnconfigure(0, weight=1)
        cards_frame.grid_columnconfigure(1, weight=1)

        for i, (name, start, end, color, flag, continent) in enumerate(SESSIONS_FULL):
            card = _SessionCard(cards_frame, name, start, end, color, flag, continent)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            self._cards.append(card)

        # ── Overlaps section ──────────────────────────────────────────
        ctk.CTkLabel(scroll, text="SESSION OVERLAPS",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(
            anchor="w", pady=(8, 6))

        self._overlap_frames: list[ctk.CTkFrame] = []
        for s1, s2, title, utc_time, desc in OVERLAPS:
            c1 = next(c for n, _, _, c, _, _ in SESSIONS_FULL if n == s1)
            c2 = next(c for n, _, _, c, _, _ in SESSIONS_FULL if n == s2)
            ov = ctk.CTkFrame(
                scroll, fg_color=Colors.CARD_BG,
                border_width=1, border_color=Colors.BORDER, corner_radius=s(8),
            )
            ov.pack(fill="x", pady=4)
            inner = ctk.CTkFrame(ov, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=10)
            # colour bar
            bar = ctk.CTkFrame(ov, height=3, fg_color=c1, corner_radius=0)
            bar.place(relx=0, rely=0, relwidth=0.5, relheight=0)
            ctk.CTkLabel(
                inner, text=title, font=SF.SUBHEADER(),
                text_color=Colors.TEXT,
            ).pack(anchor="w")
            ctk.CTkLabel(
                inner, text=utc_time, font=SF.MONO_SM(),
                text_color=Colors.NEUTRAL,
            ).pack(anchor="w", pady=(2, 4))
            ctk.CTkLabel(
                inner, text=desc, font=SF.PILL(),
                text_color=Colors.TEXT_SECONDARY,
                wraplength=s(700), justify="left",
            ).pack(anchor="w")
            self._overlap_frames.append(ov)

        # ── Trading hours table ───────────────────────────────────────
        ctk.CTkLabel(scroll, text="TRADING HOURS (UTC)",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(
            anchor="w", pady=(16, 6))

        tbl = ctk.CTkFrame(
            scroll, fg_color=Colors.CARD_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(8),
        )
        tbl.pack(fill="x", pady=(0, 8))

        # Header row
        hdr_tbl = ctk.CTkFrame(tbl, fg_color=Colors.SIDEBAR_BG, corner_radius=0)
        hdr_tbl.pack(fill="x")
        for i, (col, wt) in enumerate([
            ("Session", 3), ("Flag", 1), ("Opens (UTC)", 2),
            ("Closes (UTC)", 2), ("Duration", 2), ("Key Pairs", 4),
        ]):
            hdr_tbl.grid_columnconfigure(i, weight=wt)
            ctk.CTkLabel(
                hdr_tbl, text=col, font=SF.STATUS_BOLD(),
                text_color=Colors.LABEL,
            ).grid(row=0, column=i, sticky="w", padx=10, pady=7)

        for j, (name, start, end, color, flag, _) in enumerate(SESSIONS_FULL):
            bg = Colors.CARD_BG if j % 2 == 0 else Colors.WELL_BG
            row_f = ctk.CTkFrame(tbl, fg_color=bg)
            row_f.pack(fill="x")
            dur_h = (end - start) % 24
            pairs_str = ", ".join(SESSION_PAIRS.get(name, [])[:3])
            for i, (text, wt, tc) in enumerate([
                (name,                  3, color),
                (flag,                  1, Colors.TEXT),
                (f"{start:02d}:00",     2, Colors.TEXT_SECONDARY),
                (f"{end:02d}:00",       2, Colors.TEXT_SECONDARY),
                (f"{dur_h}h",          2, Colors.TEXT_MUTED),
                (pairs_str,            4, Colors.TEXT_MUTED),
            ]):
                row_f.grid_columnconfigure(i, weight=wt)
                ctk.CTkLabel(
                    row_f, text=text, font=SF.MONO_TINY(),
                    text_color=tc,
                ).grid(row=0, column=i, sticky="w", padx=10, pady=6)

        # ── Best times summary ────────────────────────────────────────
        ctk.CTkLabel(scroll, text="BEST TRADING WINDOWS",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(
            anchor="w", pady=(16, 6))
        best_frame = ctk.CTkFrame(
            scroll, fg_color=Colors.CARD_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(8),
        )
        best_frame.pack(fill="x", pady=(0, 16))
        tips = [
            ("🥇 Best window",     "13:00–17:00 UTC",  "London/NY overlap — peak volume, tightest spreads, strongest moves."),
            ("🥈 Second best",     "08:00–09:00 UTC",  "Tokyo/London overlap — EUR/JPY and GBP/JPY transitions."),
            ("📉 Avoid",           "20:00–23:00 UTC",  "New York close → Sydney pre-open. Thin liquidity, erratic moves."),
            ("🌙 Low volatility",  "00:00–07:00 UTC",  "Sydney/Tokyo — AUD/NZD/JPY pairs only. Small ranges."),
        ]
        for tip, time_str, desc in tips:
            tip_row = ctk.CTkFrame(best_frame, fg_color="transparent")
            tip_row.pack(fill="x", padx=14, pady=5)
            ctk.CTkLabel(
                tip_row, text=tip, font=SF.PILL_LG(),
                text_color=Colors.TEXT, width=s(140), anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                tip_row, text=time_str, font=SF.MONO_TINY(),
                text_color=Colors.NEUTRAL, width=s(130),
            ).pack(side="left", padx=8)
            ctk.CTkLabel(
                tip_row, text=desc, font=SF.TINY(),
                text_color=Colors.TEXT_SECONDARY,
                wraplength=s(480), justify="left",
            ).pack(side="left")

        # Start tick loop
        self._tick()

    def _tick(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        now = datetime.now(timezone.utc)
        h, m, wd = now.hour, now.minute, now.weekday()   # 0=Mon…6=Sun

        self._lbl_clock.configure(
            text=now.strftime("UTC  %H:%M:%S  —  %A, %d %b %Y")
        )
        for card in self._cards:
            card.tick(h, m, wd)

        self.after(1000, self._tick)

    def destroy(self):
        self._destroyed = True
        for card in self._cards:
            try:
                card._destroyed = True
            except Exception:
                pass
        try:
            super().destroy()
        except Exception:
            pass
