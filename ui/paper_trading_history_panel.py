"""
ui/paper_trading_history_panel.py
====================================
Paper Trading History — redesigned to match the reference UI.

Design matches reference screenshot:
  • Stat cards with icon + label + value (icon left, value large)
  • Table with: Time, Symbol, Type (badge), Side, Entry, Live, SL, TP, Size, P/L, Status, Details
  • Type badge: Forex (blue), Crypto (yellow/amber), Other (purple)
  • Status badge: OPEN (green outline), CLOSED (grey), BREAKEVEN (amber outline)
  • Details column: "..." button opens detail popup
  • Pagination: "Showing X to Y of Z entries" + page buttons + rows-per-page
  • Timezone footer
  • Background DB thread → main-thread render (no UI freezes)
  • Hash-based dirty check → no widget churn when data is unchanged
  • Live Price + Live P/L injected for OPEN trades from engine snapshot

Threading rules (strict):
  _bg_fetch      → background thread, ONLY reads data, NEVER touches widgets
  _drain_queue   → main thread (scheduled via .after), ONLY place that writes widgets
  _ui_update     → called by _drain_queue on main thread
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from tkinter import filedialog
import customtkinter as ctk
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from services import paper_trading_db as db
from services import paper_trading_analytics as analytics

REFRESH_MS = 2000
LIVE_MS    = 500

ROWS_PER_PAGE_OPTIONS = [10, 25, 50, 100]

# ── Asset class badge colours ──────────────────────────────────────────────
_TYPE_BADGE: dict[str, tuple] = {
    "forex":   ("#1A3A6B", "#4A90D9"),   # dark blue bg, blue text
    "crypto":  ("#3A2A00", "#F5A623"),   # dark amber bg, amber text
    "other":   ("#2A1A3A", "#B76EF0"),   # dark purple bg, purple text
    "indices": ("#1A2A3A", "#00BCD4"),
    "metals":  ("#2A2A1A", "#C8B400"),
}

def _type_colors(asset_class: str):
    key = (asset_class or "other").lower()
    for k, v in _TYPE_BADGE.items():
        if k in key:
            return v
    return _TYPE_BADGE["other"]

def _classify_display(asset_class: str, symbol: str) -> str:
    """Return a clean display label for the Type badge."""
    ac = (asset_class or "").lower()
    if "forex" in ac:
        return "Forex"
    if "crypto" in ac:
        return "Crypto"
    if "index" in ac or "indices" in ac:
        return "Index"
    if "metal" in ac or "gold" in ac or "silver" in ac:
        return "Metal"
    # Fallback: infer from symbol
    sym = symbol.upper()
    if "/" in sym:
        parts = sym.split("/")
        fiat = {"USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD","XAU","XAG"}
        if parts[0] in fiat and parts[1] in fiat:
            return "Forex"
    crypto_known = {"BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","MATIC",
                    "DOT","LINK","LTC","UNI","ATOM","TRX","BCH","TON"}
    if sym in crypto_known:
        return "Crypto"
    return "Other"


def _hash(trades: list) -> str:
    try:
        key = [(t.get("id"), t.get("status"), t.get("pnl"),
                round(t.get("live_pnl", 0.0) or 0.0, 2))
               for t in trades]
        return hashlib.md5(json.dumps(key).encode()).hexdigest()
    except Exception:
        return ""


# ── Stat Card ─────────────────────────────────────────────────────────────
_STAT_ICONS = {
    "Balance":      "💳",
    "Equity":       "📈",
    "Float P/L":    "📊",
    "Total Trades": "📋",
    "Wins":         "🏆",
    "Losses":       "🔴",
    "Win Rate":     "🎯",
    "Total P/L":    "$",
}

def _fmt_price(price: float, symbol: str = "") -> str:
    """Smart price formatter: adjusts decimal places based on asset price magnitude.
    
    BTC @ $64,000  → "$64,000.20"  (2 decimals)
    ETH @ $1,822   → "$1,822.20"   (2 decimals)  
    APT @ $5.08    → "$5.0800"     (4 decimals)
    TRX @ $0.79    → "$0.7900"     (4 decimals)
    Forex EUR/USD  → "1.14239"     (5 decimals)
    """
    if price <= 0:
        return "—"
    sym_upper = (symbol or "").upper().replace("/", "")
    # Forex / metals: always 5 decimal places
    _FIAT = {"USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD","XAU","XAG"}
    parts = sym_upper.replace("USDT","").replace("USD","")
    is_forex = any(sym_upper.endswith(c) or sym_upper.startswith(c) for c in _FIAT) and "/" in (symbol or "")
    if is_forex:
        return f"{price:,.5f}"
    # Crypto / indices by price magnitude
    if price >= 10_000:
        return f"{price:,.2f}"
    elif price >= 100:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:,.4f}"
    else:
        return f"{price:,.6f}"



class _StatCard(ctk.CTkFrame):
    def __init__(self, parent, label: str):
        super().__init__(parent, fg_color=Colors.WELL_BG,
                          border_width=1, border_color=Colors.BORDER, corner_radius=s(10))
        self._destroyed = False
        icon = _STAT_ICONS.get(label, "•")

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=s(8), pady=(s(6), 0))

        ctk.CTkLabel(top, text=icon, font=(Fonts.TITLE[0], s(14)),
                     text_color=Colors.PRIMARY).pack(side="left")
        ctk.CTkLabel(top, text=f"  {label}", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left")

        self._lbl = ctk.CTkLabel(self, text="—",
                                  font=SF.SUBHEADER(),
                                  text_color=Colors.TEXT)
        self._lbl.pack(anchor="w", padx=s(8), pady=(0, s(6)))

    def set(self, text: str, color: str = None):
        if not self._destroyed:
            self._lbl.configure(text=text, text_color=color or Colors.TEXT)


# ── Type Badge ────────────────────────────────────────────────────────────
class _TypeBadge(ctk.CTkLabel):
    def __init__(self, parent, asset_class: str, symbol: str):
        label = _classify_display(asset_class, symbol)
        bg, fg = _type_colors(label)
        super().__init__(parent, text=label,
                         font=SF.TINY(),
                         text_color=fg,
                         fg_color=bg,
                         corner_radius=s(4),
                         padx=s(6), pady=s(2))


# ── Status Badge ──────────────────────────────────────────────────────────
def _status_badge_colors(result_txt: str):
    rt = (result_txt or "").upper()
    if rt == "OPEN":
        return (Colors.CARD_BG_ALT, Colors.BUY, Colors.BUY)          # bg, text, border
    if rt in ("WIN", "CLOSED"):
        return (Colors.CARD_BG_ALT, Colors.BUY, Colors.BORDER)
    if rt == "LOSS":
        return (Colors.CARD_BG_ALT, Colors.SELL, Colors.BORDER)
    if rt == "BREAKEVEN":
        return (Colors.CARD_BG_ALT, Colors.NEUTRAL, Colors.NEUTRAL)
    return (Colors.CARD_BG_ALT, Colors.TEXT_MUTED, Colors.BORDER)


class _StatusBadge(ctk.CTkFrame):
    def __init__(self, parent, result_txt: str):
        bg, fg, border = _status_badge_colors(result_txt)
        super().__init__(parent, fg_color=bg,
                          border_width=1, border_color=border, corner_radius=s(5))
        ctk.CTkLabel(self, text=result_txt or "—",
                     font=SF.TINY(),
                     text_color=fg).pack(padx=s(6), pady=1)


# ── Main Panel ────────────────────────────────────────────────────────────
class PaperTradingHistoryPanel(ctk.CTkFrame):
    def __init__(self, parent, engine=None):
        super().__init__(parent, fg_color=Colors.CARD_BG,
                          border_width=1, border_color=Colors.BORDER, corner_radius=s(10))
        self._destroyed    = False
        self._engine       = engine
        self._last_hash    = ""
        self._fetch_lock   = threading.Lock()
        self._result_queue = queue.Queue(maxsize=2)
        self._all_trades: list = []      # unfiltered, for pagination
        self._filtered_trades: list = [] # after filter, before pagination
        self._current_page  = 1
        self._rows_per_page = ROWS_PER_PAGE_OPTIONS[0]

        # Live-price labels keyed by trade id
        self._live_widgets: dict[int, dict] = {}

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 4))

        ctk.CTkLabel(hdr, text="📄  PAPER TRADING HISTORY",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")

        ctk.CTkButton(hdr, text="⟳ Refresh", width=s(90), height=s(28),
                      corner_radius=s(6), fg_color=Colors.CARD_BG_ALT,
                      hover_color=Colors.HOVER, text_color=Colors.TEXT_MUTED,
                      font=SF.TINY(),
                      command=self._trigger_refresh).pack(side="right", padx=4)

        # ── Quick-stats bar ────────────────────────────────────────────
        sbar = ctk.CTkFrame(self, fg_color="transparent")
        sbar.pack(fill="x", padx=Spacing.MD(), pady=(4, 4))
        for i in range(8):
            sbar.grid_columnconfigure(i, weight=1)
        stat_defs = ["Balance","Equity","Float P/L","Total Trades","Wins","Losses","Win Rate","Total P/L"]
        self._scards: dict[str, _StatCard] = {}
        for col, lbl in enumerate(stat_defs):
            c = _StatCard(sbar, lbl)
            c.grid(row=0, column=col, sticky="ew", padx=2, pady=2)
            self._scards[lbl] = c

        # ── Filter row ─────────────────────────────────────────────────
        frow = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8))
        frow.pack(fill="x", padx=Spacing.MD(), pady=4)

        ctk.CTkLabel(frow, text="Filters:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(12, 6), pady=8)

        _om = dict(height=s(28), fg_color=Colors.INPUT_BG,
                   button_color=Colors.INPUT_BG,
                   button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
                   corner_radius=s(6))

        ctk.CTkLabel(frow, text="Symbol:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(4, 2), pady=8)
        self._f_symbol = ctk.CTkOptionMenu(
            frow, values=["All"], width=s(110),
            command=lambda _: self._on_filter_change(), **_om)
        self._f_symbol.pack(side="left", padx=2, pady=8)

        ctk.CTkLabel(frow, text="Status:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(8, 2), pady=8)
        self._f_status = ctk.CTkOptionMenu(
            frow, values=["All", "OPEN", "CLOSED"], width=s(90),
            command=lambda _: self._on_filter_change(), **_om)
        self._f_status.pack(side="left", padx=2, pady=8)

        ctk.CTkLabel(frow, text="Result:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(8, 2), pady=8)
        self._f_result = ctk.CTkOptionMenu(
            frow, values=["All", "WIN", "LOSS", "BREAKEVEN"], width=s(100),
            command=lambda _: self._on_filter_change(), **_om)
        self._f_result.pack(side="left", padx=2, pady=8)

        ctk.CTkButton(frow, text="Export CSV", width=s(90), height=s(26),
                      corner_radius=s(6), fg_color=Colors.CARD_BG_ALT,
                      hover_color=Colors.HOVER, text_color=Colors.TEXT, font=SF.TINY(),
                      command=lambda: self._export("csv")).pack(side="right", padx=4, pady=8)
        ctk.CTkButton(frow, text="Export Excel", width=s(100), height=s(26),
                      corner_radius=s(6), fg_color=Colors.CARD_BG_ALT,
                      hover_color=Colors.HOVER, text_color=Colors.TEXT, font=SF.TINY(),
                      command=lambda: self._export("xlsx")).pack(side="right", padx=4, pady=8)

        # ── Table ──────────────────────────────────────────────────────
        self._table = ctk.CTkScrollableFrame(
            self, fg_color=Colors.WELL_BG, corner_radius=s(8),
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY)
        bind_fast_scroll(self._table)
        self._table.pack(fill="both", expand=True,
                          padx=Spacing.MD(), pady=(4, 0))
        self._render_header()

        # ── Bottom bar: pagination + timezone ─────────────────────────
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=Spacing.MD(), pady=(4, Spacing.MD()))

        # Left: showing X-Y of Z + export feedback
        self._lbl_showing = ctk.CTkLabel(
            bot, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self._lbl_showing.pack(side="left")

        self.lbl_export = ctk.CTkLabel(
            bot, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self.lbl_export.pack(side="left", padx=16)

        # Right: rows-per-page + page nav
        right = ctk.CTkFrame(bot, fg_color="transparent")
        right.pack(side="right")

        ctk.CTkLabel(right, text="Rows per page:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(0, 4))
        self._rpp_menu = ctk.CTkOptionMenu(
            right, values=[str(r) for r in ROWS_PER_PAGE_OPTIONS],
            width=s(60), height=s(26), corner_radius=s(6),
            fg_color=Colors.INPUT_BG, button_color=Colors.INPUT_BG,
            button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
            command=self._on_rpp_change)
        self._rpp_menu.set(str(self._rows_per_page))
        self._rpp_menu.pack(side="left", padx=4)

        self._btn_prev = ctk.CTkButton(
            right, text="‹", width=s(28), height=s(28), corner_radius=s(6),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT, font=SF.SUBHEADER(),
            command=self._prev_page)
        self._btn_prev.pack(side="left", padx=2)

        self._lbl_page = ctk.CTkLabel(
            right, text="1", font=SF.TINY(),
            text_color=Colors.TEXT,
            fg_color=Colors.PRIMARY, corner_radius=s(5),
            width=s(28), height=s(28))
        self._lbl_page.pack(side="left", padx=2)

        self._btn_next = ctk.CTkButton(
            right, text="›", width=s(28), height=s(28), corner_radius=s(6),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT, font=SF.SUBHEADER(),
            command=self._next_page)
        self._btn_next.pack(side="left", padx=2)

        # ── Timezone footer ────────────────────────────────────────────
        import datetime
        try:
            tz_name = time.strftime("%Z") or "Local"
        except Exception:
            tz_name = "Local"
        tz_frame = ctk.CTkFrame(self, fg_color="transparent")
        tz_frame.pack(fill="x", padx=Spacing.MD(), pady=(0, 4))
        ctk.CTkLabel(tz_frame,
                     text=f"ⓘ  All times shown in your local timezone ({tz_name})",
                     font=SF.TINY(), text_color=Colors.TEXT_MUTED).pack(side="left")

        # Start loops
        self._trigger_refresh()
        self._drain_queue()
        self._schedule()
        self._tick_live()

    # ── Column definitions ─────────────────────────────────────────────
    # (header_text, weight, anchor)
    _COLS = [
        ("Time",    5,  "w"),
        ("Symbol",  4,  "w"),
        ("Type",    4,  "w"),
        ("Side",    3,  "w"),
        ("Entry",   6,  "w"),
        ("Live",    6,  "w"),
        ("SL",      6,  "w"),
        ("TP",      6,  "w"),
        ("Size",    7,  "w"),
        ("P/L",     5,  "w"),
        ("Status",  5,  "w"),
        ("Details", 3,  "center"),
    ]
    _COL_LIVE  = 5
    _COL_PNL   = 9

    def _render_header(self):
        hdr = ctk.CTkFrame(self._table, fg_color="transparent")
        hdr.pack(fill="x", padx=4, pady=(4, 2))
        for i, (lbl, wt, anchor) in enumerate(self._COLS):
            hdr.grid_columnconfigure(i, weight=wt)
            color = Colors.PRIMARY if lbl in ("Live", "P/L") else Colors.LABEL
            ctk.CTkLabel(hdr, text=lbl, font=SF.TINY(),
                          text_color=color,
                          anchor=anchor).grid(row=0, column=i, sticky="ew", padx=4, pady=2)

    # ── Filter / pagination callbacks ──────────────────────────────────
    def _on_filter_change(self):
        self._current_page = 1
        self._trigger_refresh()

    def _on_rpp_change(self, val):
        try:
            self._rows_per_page = int(val)
        except Exception:
            self._rows_per_page = 10
        self._current_page = 1
        self._repaginate()

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._repaginate()

    def _next_page(self):
        total_pages = max(1, -(-len(self._filtered_trades) // self._rows_per_page))
        if self._current_page < total_pages:
            self._current_page += 1
            self._repaginate()

    def _repaginate(self):
        """Re-render table from cached _filtered_trades without re-fetching."""
        start = (self._current_page - 1) * self._rows_per_page
        page  = self._filtered_trades[start: start + self._rows_per_page]
        self._render_rows(page)
        self._update_pagination_ui()

    def _update_pagination_ui(self):
        total = len(self._filtered_trades)
        rpp   = self._rows_per_page
        start = (self._current_page - 1) * rpp + 1
        end   = min(self._current_page * rpp, total)
        if total == 0:
            start = 0
        self._lbl_showing.configure(
            text=f"Showing {start} to {end} of {total} entries")
        total_pages = max(1, -(-total // rpp))
        self._lbl_page.configure(text=str(self._current_page))
        self._btn_prev.configure(state="normal" if self._current_page > 1 else "disabled")
        self._btn_next.configure(state="normal" if self._current_page < total_pages else "disabled")

    # ── Refresh scheduling ─────────────────────────────────────────────
    def _schedule(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self.after(REFRESH_MS, self._cycle)

    def _cycle(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._trigger_refresh()
        self.after(REFRESH_MS, self._cycle)

    # ── Queue drain ────────────────────────────────────────────────────
    def _drain_queue(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            payload = self._result_queue.get_nowait()
            if isinstance(payload, tuple):
                self._ui_update(*payload)
        except queue.Empty:
            pass
        except Exception:
            pass
        self.after(100, self._drain_queue)

    # ── Live-price ticker ──────────────────────────────────────────────
    def _tick_live(self):
        if self._destroyed:
            return
        if self._engine and self._live_widgets:
            try:
                # Build price map with all symbol variants
                price_map: dict[str, float] = {}
                pnl_map:   dict[int, float]  = {}
                for snap in self._engine.get_open_trades_snapshot():
                    if snap.get("_reserved"):
                        continue
                    sym = snap.get("symbol", "")
                    px  = snap.get("live_price") or snap.get("current_price") or 0.0
                    if sym and px:
                        px = float(px)
                        u = sym.upper()
                        for k in (sym, u, sym.replace("/",""), u.replace("/","")):
                            price_map[k] = px
                    tid = snap.get("id")
                    if tid is not None:
                        pnl_map[tid] = float(snap.get("live_pnl") or 0.0)

                for tid, w in list(self._live_widgets.items()):
                    t        = w["trade"]
                    sym      = t.get("symbol", "")
                    u        = sym.upper()
                    # Try all variants for price resolution
                    live_px  = 0.0
                    for k in (sym, u, sym.replace("/",""), u.replace("/","")):
                        if k in price_map:
                            live_px = price_map[k]
                            break
                    live_pnl = pnl_map.get(tid, t.get("live_pnl", 0.0))

                    price_lbl = w.get("price_lbl")
                    if price_lbl:
                        px_txt = _fmt_price(live_px, t.get("symbol","")) if live_px else "—"
                        entry = float(t.get("entry_price") or 0.0)
                        direction = t.get("signal_type", "BUY")
                        if live_px and entry:
                            fav = (live_px > entry) if direction == "BUY" else (live_px < entry)
                            px_color = Colors.BUY if fav else Colors.SELL
                        else:
                            px_color = Colors.TEXT_SECONDARY
                        price_lbl.configure(text=px_txt, text_color=px_color)

                    pnl_lbl = w.get("pnl_lbl")
                    if pnl_lbl:
                        sign    = "+" if live_pnl >= 0 else ""
                        pnl_txt = f"{sign}${live_pnl:,.2f}*"
                        pnl_col = Colors.BUY if live_pnl >= 0 else Colors.SELL
                        pnl_lbl.configure(text=pnl_txt, text_color=pnl_col)
            except Exception:
                pass
        if not self._destroyed:
            try:
                if self.winfo_exists():
                    self.after(LIVE_MS, self._tick_live)
            except Exception:
                pass

    # ── Background fetch ───────────────────────────────────────────────
    def _trigger_refresh(self):
        if self._fetch_lock.locked():
            return
        threading.Thread(target=self._bg_fetch, daemon=True).start()

    def _refresh(self):
        self._trigger_refresh()

    def _bg_fetch(self):
        if not self._fetch_lock.acquire(blocking=False):
            return
        try:
            symbols  = ["All"] + db.get_distinct_symbols()
            account  = db.get_account()
            balance  = account.get("balance", 0.0)
            floating = self._engine.get_floating_pnl() if self._engine else 0.0
            equity   = balance + floating

            all_t  = db.get_trades()
            stats  = analytics.compute_stats(all_t)

            sym_filter    = self._f_symbol.get() if self._f_symbol.get() != "All" else None
            status_filter = self._f_status.get() if self._f_status.get() != "All" else None
            result_filter = self._f_result.get() if self._f_result.get() != "All" else None

            filtered = db.get_trades(
                symbol=sym_filter,
                status=status_filter,
                result=result_filter,
                limit=5000,   # fetch all, pagination is client-side
            )

            # Inject live data for OPEN trades
            if self._engine:
                snap_by_id:  dict[int, dict] = {}
                snap_by_sym: dict[str, dict] = {}
                for snap in self._engine.get_open_trades_snapshot():
                    if snap.get("_reserved"):
                        continue
                    if snap.get("id"):
                        snap_by_id[snap["id"]] = snap
                    sym = snap.get("symbol", "")
                    if sym:
                        u = sym.upper()
                        # Register under all common forms
                        for k in (sym, u, sym.replace("/",""), u.replace("/","")):
                            snap_by_sym[k] = snap

                for t in filtered:
                    if t["status"] == "OPEN":
                        sym = t.get("symbol", "")
                        u   = sym.upper()
                        eng = snap_by_id.get(t["id"])
                        if not eng:
                            for k in (sym, u, sym.replace("/",""), u.replace("/","")):
                                eng = snap_by_sym.get(k)
                                if eng:
                                    break
                        if eng:
                            t["live_pnl"]   = float(eng.get("live_pnl")    or 0.0)
                            t["live_price"] = float(eng.get("live_price")   or
                                                    eng.get("current_price") or 0.0)
                        else:
                            t.setdefault("live_pnl",   0.0)
                            t.setdefault("live_price", 0.0)

            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                pass
            self._result_queue.put_nowait(
                (symbols, balance, equity, floating, stats, filtered)
            )
        except Exception as exc:
            try:
                from utils.logger import logger
                logger.warning(f"[PaperTradingHistoryPanel._bg_fetch] {type(exc).__name__}: {exc}")
            except Exception:
                pass
        finally:
            self._fetch_lock.release()

    # ── UI update ──────────────────────────────────────────────────────
    def _ui_update(self, symbols, balance, equity, floating, stats, filtered):
        if self._destroyed:
            return

        # Symbol option-menu
        cur = self._f_symbol.get()
        if list(self._f_symbol.cget("values")) != symbols:
            self._f_symbol.configure(values=symbols)
            if cur not in symbols:
                self._f_symbol.set(symbols[0])

        # Stat cards
        pnl_c = Colors.BUY if floating >= 0 else Colors.SELL
        tp_c  = Colors.BUY if stats["total_pnl"] >= 0 else Colors.SELL
        wr    = stats["win_rate"]
        self._scards["Balance"].set(f"${balance:,.2f}")
        self._scards["Equity"].set(f"${equity:,.2f}", pnl_c)
        self._scards["Float P/L"].set(
            f"{'+' if floating >= 0 else ''}${floating:,.2f}", pnl_c)
        self._scards["Total Trades"].set(str(stats["total_trades"]))
        self._scards["Wins"].set(str(stats["wins"]), Colors.BUY)
        self._scards["Losses"].set(str(stats["losses"]), Colors.SELL)
        self._scards["Win Rate"].set(
            f"{wr:.1f}%", Colors.BUY if wr >= 50 else Colors.SELL)
        self._scards["Total P/L"].set(f"${stats['total_pnl']:,.2f}", tp_c)

        # Store all filtered trades for pagination
        new_hash = _hash(filtered)
        if new_hash != self._last_hash:
            self._last_hash = new_hash
            self._filtered_trades = filtered
            self._current_page = max(1, min(
                self._current_page,
                max(1, -(-len(filtered) // self._rows_per_page))
            ))
            self._repaginate()

    # ── Row rendering ──────────────────────────────────────────────────
    def _render_rows(self, trades: list):
        self._live_widgets.clear()
        for w in self._table.winfo_children():
            w.destroy()
        self._render_header()

        if not trades:
            ctk.CTkLabel(self._table,
                          text="No paper trades match the current filters.",
                          font=SF.SMALL(), text_color=Colors.TEXT_MUTED).pack(pady=24)
            return

        for t in trades:
            self._render_row(t)

    # _TABLE_FONT: fixed 8pt, bypasses DPI scaling for compact Excel-like rows
    _TABLE_FONT = ("Consolas", 8)
    _TABLE_FONT_B = ("Consolas", 8, "bold")

    def _render_row(self, t: dict):
        is_open   = t["status"] == "OPEN"
        dir_color = Colors.BUY if t["signal_type"] == "BUY" else Colors.SELL
        live_pnl  = t.get("live_pnl",   0.0)
        live_px   = t.get("live_price", 0.0)
        pnl       = t.get("pnl") or 0.0
        pnl_val   = live_pnl if is_open else pnl
        pnl_color = Colors.BUY if pnl_val >= 0 else Colors.SELL
        pnl_text  = f"{'+' if pnl_val >= 0 else ''}${pnl_val:,.2f}{'*' if is_open else ''}"

        result_txt = "OPEN" if is_open else (t.get("result") or "CLOSED")
        asset_cls  = t.get("asset_class") or ""
        sym        = t["symbol"]

        # Time: show HH:MM:SS only (date is less important in table)
        _, opened_time = _fmt_ts_split(t.get("opened_at"))
        exit_str  = _fmt_price(t["exit_price"], sym) if t.get("exit_price") else "—"

        # Live price column
        if is_open:
            entry     = float(t.get("entry_price") or 0.0)
            direction = t.get("signal_type", "BUY")
            if live_px and entry:
                fav = (live_px > entry) if direction == "BUY" else (live_px < entry)
                px_color = Colors.BUY if fav else Colors.SELL
            else:
                px_color = Colors.TEXT_SECONDARY
            px_text = _fmt_price(live_px, sym) if live_px else "—"
        else:
            px_text  = f"{exit_str}"
            px_color = Colors.TEXT_SECONDARY

        row = ctk.CTkFrame(self._table, fg_color=Colors.CARD_BG, corner_radius=3)
        row.pack(fill="x", padx=2, pady=0)
        for i, (_, wt, _) in enumerate(self._COLS):
            row.grid_columnconfigure(i, weight=wt)

        # ── Col 0: Time ────────────────────────────────────────────────
        ctk.CTkLabel(row, text=opened_time, font=self._TABLE_FONT,
                      text_color=Colors.TEXT_MUTED).grid(
            row=0, column=0, sticky="w", padx=2, pady=3)

        # ── Col 1: Symbol ──────────────────────────────────────────────
        ctk.CTkLabel(row, text=sym, font=self._TABLE_FONT,
                      text_color=Colors.TEXT).grid(
            row=0, column=1, sticky="w", padx=2, pady=3)

        # ── Col 2: Type badge ──────────────────────────────────────────
        badge_frame = ctk.CTkFrame(row, fg_color="transparent")
        badge_frame.grid(row=0, column=2, sticky="w", padx=4, pady=4)
        _TypeBadge(badge_frame, asset_cls, sym).pack(anchor="w")

        # ── Col 3: Side (BUY/SELL) ─────────────────────────────────────
        ctk.CTkLabel(row, text=t["signal_type"], font=self._TABLE_FONT,
                      text_color=dir_color).grid(
            row=0, column=3, sticky="w", padx=2, pady=3)

        # ── Col 4: Entry ───────────────────────────────────────────────
        ctk.CTkLabel(row, text=_fmt_price(t["entry_price"], sym), font=self._TABLE_FONT,
                      text_color=Colors.TEXT_SECONDARY).grid(
            row=0, column=4, sticky="w", padx=2, pady=3)

        # ── Col 5: Live price ──────────────────────────────────────────
        price_lbl = ctk.CTkLabel(row, text=px_text, font=self._TABLE_FONT,
                                   text_color=px_color)
        price_lbl.grid(row=0, column=self._COL_LIVE, sticky="w", padx=2, pady=3)

        # ── Col 6: SL ──────────────────────────────────────────────────
        ctk.CTkLabel(row, text=_fmt_price(t["stop_loss"], sym), font=self._TABLE_FONT,
                      text_color=Colors.SELL).grid(
            row=0, column=6, sticky="w", padx=2, pady=3)

        # ── Col 7: TP ──────────────────────────────────────────────────
        ctk.CTkLabel(row, text=_fmt_price(t["take_profit"], sym), font=self._TABLE_FONT,
                      text_color=Colors.BUY).grid(
            row=0, column=7, sticky="w", padx=2, pady=3)

        # ── Col 8: Size ────────────────────────────────────────────────
        ctk.CTkLabel(row, text=t.get("size_label", ""), font=self._TABLE_FONT,
                      text_color=Colors.TEXT_SECONDARY).grid(
            row=0, column=8, sticky="w", padx=2, pady=3)

        # ── Col 9: P/L (live for open) ─────────────────────────────────
        pnl_lbl = ctk.CTkLabel(row, text=pnl_text, font=self._TABLE_FONT,
                                 text_color=pnl_color)
        pnl_lbl.grid(row=0, column=self._COL_PNL, sticky="w", padx=2, pady=3)

        # ── Col 10: Status badge ───────────────────────────────────────
        status_frame = ctk.CTkFrame(row, fg_color="transparent")
        status_frame.grid(row=0, column=10, sticky="w", padx=4, pady=4)
        _StatusBadge(status_frame, result_txt).pack(anchor="w")

        # ── Col 11: Details "..." button ───────────────────────────────
        ctk.CTkButton(
            row, text="···", width=s(28), height=s(22), corner_radius=s(4),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.TINY(),
            command=lambda trade=t: self._show_detail(trade)
        ).grid(row=0, column=11, padx=4, pady=4)

        # Register for live-tick updates
        if is_open:
            trade_id = t.get("id")
            if trade_id is not None:
                self._live_widgets[trade_id] = {
                    "price_lbl": price_lbl,
                    "pnl_lbl":   pnl_lbl,
                    "trade":     t,
                }

    # ── Detail popup ───────────────────────────────────────────────────
    def _show_detail(self, t: dict):
        try:
            from ui.modal_overlay import make_dialog
            dlg, inner = make_dialog(self, title=f"Trade Detail — {t['symbol']}", width=s(420))
        except Exception:
            return

        rows = [
            ("Symbol",     t.get("symbol", "—")),
            ("Type",       _classify_display(t.get("asset_class",""), t.get("symbol",""))),
            ("Side",       t.get("signal_type", "—")),
            ("Status",     t.get("status", "—")),
            ("Opened At",  _fmt_ts_split(t.get("opened_at"))[0] + " " + _fmt_ts_split(t.get("opened_at"))[1]),
            ("Entry Price", _fmt_price(t["entry_price"], t.get("symbol","")) if t.get("entry_price") else "—"),
            ("Exit Price",  _fmt_price(t["exit_price"],  t.get("symbol","")) if t.get("exit_price")  else "—"),
            ("Stop Loss",   _fmt_price(t["stop_loss"],   t.get("symbol","")) if t.get("stop_loss")   else "—"),
            ("Take Profit", _fmt_price(t["take_profit"], t.get("symbol","")) if t.get("take_profit") else "—"),
            ("Size",        t.get("size_label", "—")),
            ("Leverage",    f"{t.get('leverage',1)}x"),
            ("Result",      t.get("result") or ("OPEN" if t.get("status")=="OPEN" else "—")),
            ("P/L",         f"${(t.get('pnl') or 0.0):+,.2f}"),
            ("Signal #",    str(t.get("signal_id") or "—")),
        ]
        for label, val in rows:
            r = ctk.CTkFrame(inner, fg_color="transparent")
            r.pack(fill="x", padx=4, pady=2)
            ctk.CTkLabel(r, text=label, font=SF.TINY(),
                         text_color=Colors.LABEL, width=s(110), anchor="w").pack(side="left")
            ctk.CTkLabel(r, text=str(val), font=SF.MONO_TINY(),
                         text_color=Colors.TEXT, anchor="w").pack(side="left", padx=8)

        ctk.CTkButton(inner, text="Close", width=s(100), height=s(30),
                      fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
                      text_color="#FFFFFF", corner_radius=s(6),
                      command=dlg.destroy).pack(pady=(12, 4))

    # ── Lifecycle ──────────────────────────────────────────────────────
    def destroy(self):
        self._destroyed = True
        self._live_widgets.clear()
        try:
            super().destroy()
        except Exception:
            pass

    # ── Export ─────────────────────────────────────────────────────────
    def _export(self, fmt: str):
        trades = db.get_trades(
            symbol=self._f_symbol.get() if self._f_symbol.get() != "All" else None,
            status=self._f_status.get() if self._f_status.get() != "All" else None,
            result=self._f_result.get() if self._f_result.get() != "All" else None,
        )
        if not trades:
            self.lbl_export.configure(text="Nothing to export.")
            return
        ext  = ".xlsx" if fmt == "xlsx" else ".csv"
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=[(fmt.upper(), f"*{ext}")],
            initialfile=f"paper_trades{ext}",
        )
        if not path:
            return
        if fmt == "xlsx":
            ok = db.export_xlsx(path, trades)
            if not ok:
                db.export_csv(path.rsplit(".", 1)[0] + ".csv", trades)
        else:
            db.export_csv(path, trades)
        self.lbl_export.configure(text=f"✓ Exported {len(trades)} trade(s)")


# ── Helpers ────────────────────────────────────────────────────────────────

def _fmt_ts_split(ts) -> tuple:
    try:
        t = time.localtime(float(ts))
        return time.strftime("%Y-%m-%d", t), time.strftime("%H:%M:%S", t)
    except Exception:
        return "—", "—"
