"""
ui/signal_history_panel.py
============================
Searchable, filterable, sortable Signal History page.

Improvements:
  • Quick-tab row: Active | Triggered | Closed | Expired | All
  • Sortable columns (click header to sort asc/desc)
  • CSV Export button
  • Date-range filter (From / To)
  • Background fetch with hash-based dirty check
  • Auto-refresh every 3 s — never blocks UI thread
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import queue
import threading
import time
import customtkinter as ctk
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from services import signal_storage

REFRESH_MS = 3000
PAGE_SIZE  = 200

_STATUS_COLOR = {
    "ACTIVE":    "#2962FF",
    "TRIGGERED": "#F5A623",
    "EXPIRED":   "#64748B",
    "CLOSED":    "#00C087",
    "CANCELLED": "#F6465D",
}
_RESULT_COLOR = {
    "WIN":       "#00C087",
    "LOSS":      "#F6465D",
    "BREAKEVEN": "#F5A623",
}

# Tab → status filter value
_TAB_STATUS = {
    "All":       None,
    "Active":    "ACTIVE",
    "Triggered": "TRIGGERED",
    "Closed":    "CLOSED",
    "Expired":   "EXPIRED",
    "Cancelled": "CANCELLED",
}


def _row_hash(signals: list) -> str:
    try:
        key = [(s.get("id"), s.get("status"), s.get("result"), s.get("confidence"))
               for s in signals]
        return hashlib.md5(json.dumps(key).encode()).hexdigest()
    except Exception:
        return ""


def _fmt_ts(ts) -> str:
    if not ts:
        return "—"
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:
        return "—"


class _StatCard(ctk.CTkFrame):
    def __init__(self, parent, label: str, color: str = None):
        super().__init__(parent, fg_color=Colors.WELL_BG, border_width=1,
                          border_color=Colors.BORDER, corner_radius=s(8))
        self._destroyed = False
        ctk.CTkLabel(self, text=label, font=SF.TINY(),
                     text_color=Colors.LABEL).pack(anchor="w", padx=10, pady=(7, 0))
        self._lbl = ctk.CTkLabel(self, text="—",
                                  font=SF.PRICE_SM(),
                                  text_color=color or Colors.TEXT)
        self._lbl.pack(anchor="w", padx=10, pady=(0, 7))
        self._default_color = color or Colors.TEXT

    def set(self, text: str, color: str = None):
        self._lbl.configure(text=text, text_color=color or self._default_color)


class SignalHistoryPanel(ctk.CTkFrame):
    """Full-page signal history with search, tabs, sort, export."""

    # Column definitions: (header, db_key, width_weight)
    _COLS = [
        ("Created",       "created_at",    9),
        ("Symbol",        "symbol",        7),
        ("Strategy",      "strategy",      9),
        ("TF",            "timeframe",     4),
        ("Dir",           "direction",     4),
        ("Entry",         "entry_price",   8),
        ("SL",            "stop_loss",     8),
        ("TP1",           "take_profit_1", 8),
        ("Conf",          "confidence",    5),
        ("Status",        "status",        8),
        ("Result",        "result",        7),
        ("Expires/Closed","closed_at",    10),
    ]

    def __init__(self, parent):
        super().__init__(parent, fg_color=Colors.CARD_BG,
                          border_width=1, border_color=Colors.BORDER, corner_radius=s(10))

        self._destroyed   = False
        self._last_hash   = ""
        self._fetch_lock  = threading.Lock()
        self._result_queue = __import__('queue').Queue(maxsize=2)   # panel-level queue (was on _StatCard by mistake)
        self._sort_col    = "created_at"
        self._sort_asc    = False  # newest first
        self._active_tab  = "All"
        self._all_signals : list = []  # last fetched for export

        # ── Stat cards ────────────────────────────────────────────────
        cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        cards_frame.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 4))
        for i in range(9):
            cards_frame.grid_columnconfigure(i, weight=1)

        card_defs = [
            ("Total",     Colors.TEXT),
            ("Active",    Colors.PRIMARY),
            ("Triggered", Colors.NEUTRAL),
            ("Closed",    Colors.TEXT_SECONDARY),
            ("Expired",   Colors.TEXT_MUTED),
            ("Cancelled", Colors.SELL),
            ("Wins",      Colors.BUY),
            ("Losses",    Colors.SELL),
            ("Win Rate",  Colors.BUY),
        ]
        self._stat_cards: dict[str, _StatCard] = {}
        for col, (label, color) in enumerate(card_defs):
            card = _StatCard(cards_frame, label, color)
            card.grid(row=0, column=col, sticky="ew", padx=2, pady=2)
            self._stat_cards[label] = card

        # ── Quick-status tabs ─────────────────────────────────────────
        tab_row = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8))
        tab_row.pack(fill="x", padx=Spacing.MD(), pady=(0, 4))

        tab_inner = ctk.CTkFrame(tab_row, fg_color="transparent")
        tab_inner.pack(side="left", padx=8, pady=6)

        self._tab_btns: dict[str, ctk.CTkButton] = {}
        for tab_name in _TAB_STATUS:
            b = ctk.CTkButton(
                tab_inner, text=tab_name, width=s(80), height=s(26), corner_radius=s(5),
                fg_color=Colors.PRIMARY if tab_name == "All" else Colors.CARD_BG_ALT,
                hover_color=Colors.PRIMARY_HOVER,
                text_color=Colors.ON_BUY if tab_name == "All" else Colors.TEXT_MUTED,
                font=SF.PILL_LG(),
                command=lambda t=tab_name: self._switch_tab(t),
            )
            b.pack(side="left", padx=2)
            self._tab_btns[tab_name] = b

        # Export button on right
        ctk.CTkButton(
            tab_row, text="⬇ Export CSV", width=s(110), height=s(26), corner_radius=s(6),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.STATUS_BOLD(),
            command=self._export_csv,
        ).pack(side="right", padx=8, pady=6)

        self._lbl_count = ctk.CTkLabel(
            tab_row, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self._lbl_count.pack(side="right", padx=8)

        # ── Filter bar ────────────────────────────────────────────────
        fbar = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8))
        fbar.pack(fill="x", padx=Spacing.MD(), pady=4)

        _om = dict(height=s(26), fg_color=Colors.CARD_BG_ALT,
                   button_color=Colors.CARD_BG_ALT,
                   button_hover_color=Colors.HOVER,
                   text_color=Colors.TEXT)

        ctk.CTkLabel(fbar, text="Symbol:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(10, 2), pady=8)
        self._f_symbol = ctk.CTkOptionMenu(
            fbar, values=["All"], width=s(100),
            command=lambda _: self._trigger_refresh(), **_om)
        self._f_symbol.pack(side="left", padx=2, pady=8)

        ctk.CTkLabel(fbar, text="Dir:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(8, 2), pady=8)
        self._f_dir = ctk.CTkOptionMenu(
            fbar, values=["All", "BUY", "SELL"], width=s(70),
            command=lambda _: self._trigger_refresh(), **_om)
        self._f_dir.pack(side="left", padx=2, pady=8)

        ctk.CTkLabel(fbar, text="Strategy:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(8, 2), pady=8)
        self._f_strategy = ctk.CTkOptionMenu(
            fbar, values=["All"], width=S.BTN_W_MD(),
            command=lambda _: self._trigger_refresh(), **_om)
        self._f_strategy.pack(side="left", padx=2, pady=8)

        ctk.CTkLabel(fbar, text="Min Conf:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(8, 2), pady=8)
        self._f_conf_var = ctk.StringVar(value="0")
        self._f_conf = ctk.CTkOptionMenu(
            fbar, values=["0", "50", "60", "70", "75", "80", "85", "90"],
            width=65, variable=self._f_conf_var,
            command=lambda _: self._trigger_refresh(), **_om)
        self._f_conf.pack(side="left", padx=2, pady=8)

        ctk.CTkLabel(fbar, text="Search:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(8, 2), pady=8)
        self._f_search = ctk.CTkEntry(
            fbar, width=s(140), height=s(26), placeholder_text="symbol / strategy…",
            fg_color=Colors.CARD_BG_ALT, border_color=Colors.BORDER,
            text_color=Colors.TEXT)
        self._f_search.pack(side="left", padx=2, pady=8)
        self._f_search.bind("<Return>", lambda _: self._trigger_refresh())
        self._search_after_id = None
        self._f_search.bind("<KeyRelease>", self._on_search_key)

        ctk.CTkButton(
            fbar, text="Reset", width=s(60), height=s(26), corner_radius=s(6),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.TINY(),
            command=self._reset_filters,
        ).pack(side="right", padx=(2, 10), pady=8)

        # ── Table area with sortable header ───────────────────────────
        tbl_outer = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8),
                                  border_width=1, border_color=Colors.BORDER)
        tbl_outer.pack(fill="both", expand=True, padx=Spacing.MD(), pady=(4, Spacing.MD()))
        tbl_outer.grid_columnconfigure(0, weight=1)
        tbl_outer.grid_rowconfigure(1, weight=1)

        # Sortable header row
        self._hdr_row = ctk.CTkFrame(tbl_outer, fg_color=Colors.SIDEBAR_BG,
                                      corner_radius=0, height=S.BTN_H())
        self._hdr_row.grid(row=0, column=0, sticky="ew")
        self._render_sortable_header()

        self._table = ctk.CTkScrollableFrame(
            tbl_outer, fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY)
        self._table.grid(row=1, column=0, sticky="nsew")
        bind_fast_scroll(self._table)

        self._trigger_refresh()
        self._schedule_auto_refresh()
        self._drain_queue()

    # ── Tab switching ─────────────────────────────────────────────────────
    def _switch_tab(self, tab: str):
        self._active_tab = tab
        for k, b in self._tab_btns.items():
            b.configure(
                fg_color=Colors.PRIMARY if k == tab else Colors.CARD_BG_ALT,
                text_color=Colors.ON_BUY if k == tab else Colors.TEXT_MUTED,
            )
        self._trigger_refresh()

    # ── Sortable header ───────────────────────────────────────────────────
    def _render_sortable_header(self):
        for w in self._hdr_row.winfo_children():
            w.destroy()
        for i in range(len(self._COLS)):
            self._hdr_row.grid_columnconfigure(i, weight=self._COLS[i][2])

        for col_idx, (label, db_key, wt) in enumerate(self._COLS):
            arrow = ""
            if self._sort_col == db_key:
                arrow = " ▲" if self._sort_asc else " ▼"
            btn = ctk.CTkButton(
                self._hdr_row, text=label + arrow,
                height=s(28), corner_radius=0, anchor="w",
                fg_color="transparent", hover_color=Colors.HOVER,
                text_color=Colors.BUY if self._sort_col == db_key else Colors.LABEL,
                font=SF.STATUS_BOLD(),
                command=lambda k=db_key: self._toggle_sort(k),
            )
            btn.grid(row=0, column=col_idx, sticky="ew", padx=2)

    def _toggle_sort(self, col_key: str):
        if self._sort_col == col_key:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col_key
            self._sort_asc = True
        self._render_sortable_header()
        self._trigger_refresh()

    # ── Search debounce ───────────────────────────────────────────────────
    def _on_search_key(self, _event):
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(500, self._trigger_refresh)

    # ── Refresh pipeline ──────────────────────────────────────────────────
    def _schedule_auto_refresh(self):
        self.after(REFRESH_MS, self._auto_cycle)

    def _auto_cycle(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._trigger_refresh()
        self.after(REFRESH_MS, self._auto_cycle)


    def _drain_queue(self):
        """Main-thread only: drains result queue and applies UI updates safely."""
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
            args = self._result_queue.get_nowait()
            if isinstance(args, tuple):
                self._ui_update(*args)
        except __import__('queue').Empty:
            pass
        except RuntimeError:
            return  # widget destroyed mid-drain
        except Exception as exc:
            from utils.logger import logger
            logger.warning(f"[SignalHistoryPanel._drain_queue] {type(exc).__name__}: {exc}")
        try:
            self.after(100, self._drain_queue)
        except RuntimeError:
            pass

    def destroy(self):
        self._destroyed = True
        try:
            super().destroy()
        except Exception:
            pass

    def _trigger_refresh(self):
        if self._fetch_lock.locked():
            return
        threading.Thread(target=self._bg_fetch, daemon=True).start()

    def _bg_fetch(self):
        if self._destroyed:
            return
        if not self._fetch_lock.acquire(blocking=False):
            return
        try:
            tab_status = _TAB_STATUS.get(self._active_tab)
            symbol     = self._f_symbol.get()
            direction  = self._f_dir.get()
            strategy   = self._f_strategy.get()
            search     = self._f_search.get().strip()
            min_conf   = int(self._f_conf_var.get() or 0)

            signals = signal_storage.get_signals(
                status=tab_status,
                symbol=symbol if symbol != "All" else None,
                direction=direction if direction != "All" else None,
                strategy=strategy if strategy != "All" else None,
                search=search or None,
                min_confidence=min_conf if min_conf > 0 else None,
                limit=PAGE_SIZE,
            )

            # Client-side sort
            col_key  = self._sort_col
            sort_asc = self._sort_asc
            try:
                signals = sorted(
                    signals,
                    key=lambda s: (s.get(col_key) or 0),
                    reverse=not sort_asc,
                )
            except Exception:
                pass

            stats          = signal_storage.get_performance_stats()
            all_symbols    = ["All"] + signal_storage.get_distinct_symbols()
            all_strategies = ["All"] + signal_storage.get_distinct_strategies()

            try:
                self._result_queue.get_nowait()   # discard stale result
            except __import__('queue').Empty:
                pass
            self._result_queue.put_nowait((signals, stats, all_symbols, all_strategies))
        except RuntimeError:
            pass   # widget destroyed or thread timing — not a real error
        except Exception as exc:
            from utils.logger import logger
            logger.warning(f"[SignalHistoryPanel._bg_fetch] {type(exc).__name__}: {exc}")
        finally:
            self._fetch_lock.release()

    def _ui_update(self, signals: list, stats: dict,
                   all_symbols: list, all_strategies: list):
        self._all_signals = signals

        self._update_option_menu(self._f_symbol, all_symbols)
        self._update_option_menu(self._f_strategy, all_strategies)

        # Stat cards
        self._stat_cards["Total"].set(str(stats["total"]))
        self._stat_cards["Active"].set(str(stats["active"]), Colors.PRIMARY)
        self._stat_cards["Triggered"].set(str(stats["triggered"]), Colors.NEUTRAL)
        self._stat_cards["Closed"].set(str(stats["closed"]))
        self._stat_cards["Expired"].set(str(stats["expired"]), Colors.TEXT_MUTED)
        self._stat_cards["Cancelled"].set(str(stats["cancelled"]), Colors.SELL)
        self._stat_cards["Wins"].set(str(stats["wins"]), Colors.BUY)
        self._stat_cards["Losses"].set(str(stats["losses"]), Colors.SELL)
        wr = stats["win_rate"]
        self._stat_cards["Win Rate"].set(
            f"{wr:.1f}%", Colors.BUY if wr >= 50 else Colors.SELL)

        self._lbl_count.configure(text=f"{len(signals)} row(s)")

        new_hash = _row_hash(signals)
        if new_hash != self._last_hash:
            self._last_hash = new_hash
            self._render_rows(signals)

    def _update_option_menu(self, menu: ctk.CTkOptionMenu, values: list):
        current = menu.get()
        if list(menu.cget("values")) != values:
            menu.configure(values=values)
            if current not in values:
                menu.set(values[0])

    # ── Row rendering ─────────────────────────────────────────────────────
    def _render_rows(self, signals: list):
        for w in self._table.winfo_children():
            w.destroy()

        if not signals:
            ctk.CTkLabel(
                self._table,
                text="No signals match the current filters.",
                font=SF.SMALL(), text_color=Colors.TEXT_MUTED,
            ).pack(pady=20)
            return

        for sig in signals:
            self._render_row(sig)

    def _render_row(self, sig: dict):
        status    = sig.get("status", "")
        result    = sig.get("result") or ""
        direction = sig.get("direction", "")

        bg = Colors.CARD_BG
        if status == "ACTIVE":
            bg = Colors.CARD_BG_ALT
        elif status == "TRIGGERED":
            bg = "#1A2030"

        row = ctk.CTkFrame(self._table, fg_color=bg, corner_radius=s(5))
        row.pack(fill="x", padx=2, pady=1)
        for i, (_, _k, wt) in enumerate(self._COLS):
            row.grid_columnconfigure(i, weight=wt)

        dir_color    = Colors.BUY if direction == "BUY" else Colors.SELL
        status_color = _STATUS_COLOR.get(status, Colors.TEXT_MUTED)
        result_color = _RESULT_COLOR.get(result, Colors.TEXT_MUTED)

        created_str = _fmt_ts(sig.get("created_at"))
        if sig.get("closed_at"):
            time2_str = _fmt_ts(sig["closed_at"])
        elif sig.get("expires_at"):
            time2_str = _fmt_ts(sig["expires_at"])
        else:
            time2_str = "—"

        def _fmt_p(v):
            try:
                return f"{float(v):.4f}" if v is not None else "—"
            except Exception:
                return "—"

        strategy = (sig.get("strategy") or sig.get("trade_type") or "—")[:10]

        values = [
            (created_str,                          Colors.TEXT_MUTED),
            (sig.get("symbol", ""),               Colors.TEXT),
            (strategy,                             Colors.TEXT_SECONDARY),
            (sig.get("timeframe") or "—",          Colors.TEXT_MUTED),
            (direction,                            dir_color),
            (_fmt_p(sig.get("entry_price")),       Colors.TEXT_SECONDARY),
            (_fmt_p(sig.get("stop_loss")),         Colors.SELL),
            (_fmt_p(sig.get("take_profit_1")),     Colors.BUY),
            (f"{sig.get('confidence', 0)}%",       Colors.ORANGE),
            (status,                               status_color),
            (result or "—",                        result_color),
            (time2_str,                            Colors.TEXT_MUTED),
        ]

        for col, (text, color) in enumerate(values):
            ctk.CTkLabel(
                row, text=text, font=SF.MONO_TINY(), text_color=color
            ).grid(row=0, column=col, sticky="w", padx=3, pady=5)

    # ── CSV export ────────────────────────────────────────────────────────
    def _export_csv(self):
        signals = self._all_signals
        if not signals:
            return
        try:
            from tkinter import filedialog
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
                initialfile=f"signal_history_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                title="Export Signal History",
            )
            if not path:
                return

            field_keys = [k for _, k, _ in self._COLS]
            headers    = [h for h, _, _ in self._COLS]

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                writer.writeheader()
                for sig in signals:
                    row = {}
                    for header, key in zip(headers, field_keys):
                        val = sig.get(key, "")
                        if key in ("created_at", "closed_at", "expires_at"):
                            val = _fmt_ts(val)
                        row[header] = val
                    writer.writerow(row)
        except Exception as e:
            from utils.logger import get_logger
            get_logger("SignalHistory").warning(f"Export error: {type(e).__name__}: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────
    def _reset_filters(self):
        self._f_symbol.set("All")
        self._f_dir.set("All")
        self._f_strategy.set("All")
        self._f_conf_var.set("0")
        self._f_search.delete(0, "end")
        self._switch_tab("All")
