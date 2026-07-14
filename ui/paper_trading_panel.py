"""
ui/paper_trading_panel.py
============================
Paper Algo Trading dashboard -- fully simulated, no real orders ever
placed. Drives itself: once mounted, it polls services/paper_trading_db
on its own timer (self.after), so it needs no wiring into main_window's
existing chart/signal refresh pipeline and can't affect it.

Reuses (read-only) the AI signals already produced by
services/market_scanner.py via services/paper_trading_engine.py --
the AI strategy/signal generation logic itself is never touched.
"""

import time
import queue
import threading
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk

from ui.components import bind_fast_scroll
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from services import paper_trading_db as db
from services import paper_trading_analytics as analytics
from ui.modal_overlay import make_dialog

REFRESH_MS = 3000
STARTING_BALANCE_PRESETS = [100, 500, 1000, 10000]


class _StatCard(ctk.CTkFrame):
    def __init__(self, parent, label):
        super().__init__(parent, fg_color=Colors.WELL_BG, border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        self._destroyed = False
        self._result_queue = __import__('queue').Queue(maxsize=1)
        ctk.CTkLabel(self, text=label, font=SF.TINY(), text_color=Colors.LABEL).pack(anchor="w", padx=10, pady=(8, 0))
        self.lbl_value = ctk.CTkLabel(self, text="--", font=SF.PRICE_SM(), text_color=Colors.TEXT)
        self.lbl_value.pack(anchor="w", padx=10, pady=(0, 8))

    def set(self, text, color=None):
        self.lbl_value.configure(text=text, text_color=color or Colors.TEXT)


class _EquityCurveCanvas(ctk.CTkFrame):
    """Minimal hand-rolled line chart -- no matplotlib, consistent with
    ui/chart_widget.py's own pure-Canvas approach."""

    def __init__(self, parent, height=140):
        super().__init__(parent, fg_color=Colors.WELL_BG, border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bg=Colors.WELL_BG)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self._points = []

    def draw(self, points: list):
        self._points = points
        self._redraw()

    def _redraw(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 10 or h < 10:
            return

        if len(self._points) < 2:
            self.canvas.create_text(w / 2, h / 2, text="Not enough closed trades yet for an equity curve",
                                     fill=Colors.TEXT_MUTED, font=SF.PILL())
            return

        values = [p[1] for p in self._points]
        vmin, vmax = min(values), max(values)
        if vmin == vmax:
            vmin -= 1
            vmax += 1
        pad = 10

        def scale(i, v):
            x = pad + (i / (len(values) - 1)) * (w - 2 * pad)
            y = h - pad - ((v - vmin) / (vmax - vmin)) * (h - 2 * pad)
            return x, y

        # Zero/starting-point reference line
        zero_y = h - pad - ((0 - vmin) / (vmax - vmin)) * (h - 2 * pad)
        if 0 <= zero_y <= h:
            self.canvas.create_line(0, zero_y, w, zero_y, fill=Colors.BORDER, dash=(3, 3))

        color = Colors.BUY if values[-1] >= values[0] else Colors.SELL
        coords = []
        for i, v in enumerate(values):
            coords.extend(scale(i, v))
        self.canvas.create_line(*coords, fill=color, width=2, smooth=True)


class PaperTradingPanel(ctk.CTkFrame):
    def __init__(self, parent, engine):
        super().__init__(parent, fg_color=Colors.CARD_BG, border_width=1, border_color=Colors.BORDER, corner_radius=s(10))
        self._destroyed = False
        self.engine = engine

        # ---------------- Header ----------------
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 4))
        ctk.CTkLabel(header, text="PAPER ALGO TRADING  (simulated -- no real orders placed)",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")

        self.btn_toggle = ctk.CTkButton(header, text="⏸ Pause Auto-Trading", width=S.BTN_W_LG(), height=S.BTN_H(), corner_radius=s(6),
                                         fg_color=Colors.SELL, text_color=Colors.ON_SELL, hover_color=Colors.HOVER_STRONG,
                                         font=SF.NAV_BOLD(), command=self._on_toggle)
        self.btn_toggle.pack(side="right", padx=(6, 0))

        # First-run tooltip explaining always-on behaviour
        self.lbl_status = ctk.CTkLabel(header, text="Auto-running — trades fire when signals match",
                                        font=SF.SMALL(), text_color=Colors.TEXT_MUTED)
        self.lbl_status.pack(side="right", padx=(6, 6))

        # ---------------- Account bar ----------------
        acct = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8))
        acct.pack(fill="x", padx=Spacing.MD(), pady=4)

        self.lbl_balance = ctk.CTkLabel(acct, text="BALANCE: $0.00", font=SF.MONO(), text_color=Colors.TEXT)
        self.lbl_balance.pack(side="left", padx=10, pady=8)
        self.lbl_equity = ctk.CTkLabel(acct, text="EQUITY: $0.00", font=SF.MONO(), text_color=Colors.TEXT_SECONDARY)
        self.lbl_equity.pack(side="left", padx=10, pady=8)

        btn_kwargs = dict(height=s(26), corner_radius=s(6), font=SF.PILL_LG(),
                           fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.TEXT)
        ctk.CTkButton(acct, text="Deposit", width=s(80), command=self._on_deposit, **btn_kwargs).pack(side="right", padx=(4, 10), pady=8)
        ctk.CTkButton(acct, text="Withdraw", width=s(80), command=self._on_withdraw, **btn_kwargs).pack(side="right", padx=4, pady=8)
        ctk.CTkButton(acct, text="Reset Account", width=s(110), command=self._on_reset, **btn_kwargs).pack(side="right", padx=4, pady=8)

        preset_row = ctk.CTkFrame(self, fg_color="transparent")
        preset_row.pack(fill="x", padx=Spacing.MD(), pady=(0, 4))
        ctk.CTkLabel(preset_row, text="Starting balance:", font=SF.TINY(), text_color=Colors.TEXT_MUTED).pack(side="left", padx=(0, 6))
        for amount in STARTING_BALANCE_PRESETS:
            ctk.CTkButton(preset_row, text=f"${amount:,}", width=s(70), height=S.ICON_BTN(), corner_radius=s(6),
                          fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.TEXT,
                          font=SF.PILL(), command=lambda a=amount: self._set_starting_balance(a)).pack(side="left", padx=2)
        ctk.CTkButton(preset_row, text="Custom...", width=s(80), height=S.ICON_BTN(), corner_radius=s(6),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.TEXT,
                      font=SF.PILL(), command=self._set_custom_starting_balance).pack(side="left", padx=2)

        # ---------------- Analytics grid ----------------
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=Spacing.MD(), pady=4)
        for i in range(5):
            grid.grid_columnconfigure(i, weight=1)

        labels = ["Total Trades", "Wins", "Losses", "Win Rate", "Loss Rate",
                  "Total P/L", "Avg Profit", "Avg Loss", "Risk:Reward", "Max Drawdown"]
        self.stat_cards = {}
        for i, label in enumerate(labels):
            card = _StatCard(grid, label)
            card.grid(row=i // 5, column=i % 5, sticky="ew", padx=3, pady=3)
            self.stat_cards[label] = card

        # ---------------- Equity curve ----------------
        ctk.CTkLabel(self, text="EQUITY CURVE (cumulative P/L)", font=SF.TINY(), text_color=Colors.LABEL).pack(
            anchor="w", padx=Spacing.MD(), pady=(6, 2))
        self.equity_curve = _EquityCurveCanvas(self)
        self.equity_curve.pack(fill="x", padx=Spacing.MD(), pady=(0, 6))

        # ---------------- Filters + export ----------------
        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(fill="x", padx=Spacing.MD(), pady=(0, 4))

        ctk.CTkLabel(filter_row, text="TRADE HISTORY", font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")

        self.filter_symbol = ctk.CTkOptionMenu(filter_row, values=["All"], width=s(110), height=s(26),
                                                fg_color=Colors.CARD_BG_ALT, button_color=Colors.CARD_BG_ALT,
                                                button_hover_color=Colors.HOVER, command=lambda _: self._refresh())
        self.filter_symbol.pack(side="right", padx=(4, 0))
        self.filter_timeframe = ctk.CTkOptionMenu(filter_row, values=["All"], width=s(90), height=s(26),
                                                   fg_color=Colors.CARD_BG_ALT, button_color=Colors.CARD_BG_ALT,
                                                   button_hover_color=Colors.HOVER, command=lambda _: self._refresh())
        self.filter_timeframe.pack(side="right", padx=(4, 0))
        self.filter_status = ctk.CTkOptionMenu(filter_row, values=["All", "OPEN", "CLOSED"], width=s(90), height=s(26),
                                                fg_color=Colors.CARD_BG_ALT, button_color=Colors.CARD_BG_ALT,
                                                button_hover_color=Colors.HOVER, command=lambda _: self._refresh())
        self.filter_status.pack(side="right", padx=(4, 10))

        ctk.CTkButton(filter_row, text="Export CSV", width=s(90), height=s(26), corner_radius=s(6),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.TEXT,
                      font=SF.PILL_LG(), command=lambda: self._export("csv")).pack(side="right", padx=2)
        ctk.CTkButton(filter_row, text="Export Excel", width=s(100), height=s(26), corner_radius=s(6),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.TEXT,
                      font=SF.PILL_LG(), command=lambda: self._export("xlsx")).pack(side="right", padx=2)

        self.export_status = ctk.CTkLabel(self, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self.export_status.pack(anchor="e", padx=Spacing.MD())

        # ---------------- Trade history table ----------------
        self.table = ctk.CTkScrollableFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8), height=220)
        bind_fast_scroll(self.table)
        self.table.pack(fill="both", expand=True, padx=Spacing.MD(), pady=(4, Spacing.MD()))
        self._render_table_header()
        self._empty_row = ctk.CTkLabel(self.table, text="No paper trades yet -- start Algo Trading to begin.",
                                        font=SF.SMALL(), text_color=Colors.TEXT_MUTED)
        self._empty_row.pack(pady=16)

        self._refresh()
        self._drain_queue()
        self.after(REFRESH_MS, self._auto_refresh)

    # ------------------------------------------------------------------
    def _render_table_header(self):
        cols = ["Opened", "Symbol", "Dir", "Entry", "Exit", "SL", "TP", "Size", "P/L", "Result"]
        hdr = ctk.CTkFrame(self.table, fg_color="transparent")
        hdr.pack(fill="x", padx=2, pady=(2, 4))
        for i, c in enumerate(cols):
            hdr.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(hdr, text=c, font=SF.STATUS_BOLD(), text_color=Colors.LABEL).grid(
                row=0, column=i, sticky="w", padx=4)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _on_toggle(self):
        if self.engine.is_running():
            self.engine.stop()
        else:
            self.engine.start()
        self._refresh()

    def _set_starting_balance(self, amount):
        self._confirm_reset(amount)

    def _set_custom_starting_balance(self):
        dialog = ctk.CTkInputDialog(text="Enter custom starting balance (USD):", title="Custom Starting Balance")
        raw = dialog.get_input()
        if raw is None:
            return
        try:
            amount = float(raw.replace(",", "").replace("$", "").strip())
        except ValueError:
            return
        if amount > 0:
            self._confirm_reset(amount)

    def _confirm_reset(self, starting_balance):
        confirm = ctk.CTkToplevel(self)
        confirm.configure(fg_color=Colors.APP_BG)
        make_dialog(confirm, self.winfo_toplevel(),
                    title="Confirm", size=(380, 150))
        ctk.CTkLabel(confirm, text=f"Set starting balance to ${starting_balance:,.2f}?\n\n"
                                     "This clears all paper trade history and resets equity.",
                     font=SF.SMALL(), text_color=Colors.TEXT, wraplength=s(340), justify="left").pack(padx=16, pady=16)
        row = ctk.CTkFrame(confirm, fg_color="transparent")
        row.pack(pady=8)

        def do_reset():
            db.reset_account(starting_balance)
            confirm.destroy()
            self._refresh()

        ctk.CTkButton(row, text="Cancel", width=s(90), fg_color=Colors.CARD_BG_ALT,
                      command=confirm.destroy).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Confirm", width=s(90), fg_color=Colors.BUY, text_color=Colors.ON_BUY,
                      command=do_reset).pack(side="left", padx=6)

    def _on_deposit(self):
        self._amount_dialog("Deposit", lambda amt: db.apply_balance_delta(amt, "DEPOSIT", "Manual deposit"))

    def _on_withdraw(self):
        self._amount_dialog("Withdraw", lambda amt: db.apply_balance_delta(-amt, "WITHDRAWAL", "Manual withdrawal"))

    def _amount_dialog(self, label, on_confirm):
        dialog = ctk.CTkInputDialog(text=f"{label} amount (USD):", title=label)
        raw = dialog.get_input()
        if raw is None:
            return
        try:
            amount = float(raw.replace(",", "").replace("$", "").strip())
        except ValueError:
            return
        if amount > 0:
            on_confirm(amount)
            self._refresh()

    def _on_reset(self):
        account = db.get_account()
        self._confirm_reset(account.get("starting_balance", 10000.0))

    def _export(self, fmt):
        trades = db.get_trades(
            symbol=self.filter_symbol.get(), timeframe=self.filter_timeframe.get(),
            status=self.filter_status.get(),
        )
        if not trades:
            self.export_status.configure(text="Nothing to export for the current filters.")
            return

        ext = ".xlsx" if fmt == "xlsx" else ".csv"
        filepath = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[(fmt.upper(), f"*{ext}")],
                                                  initialfile=f"paper_trade_history{ext}")
        if not filepath:
            return

        if fmt == "xlsx":
            ok = db.export_xlsx(filepath, trades)
            if not ok:
                self.export_status.configure(
                    text="Excel export needs 'openpyxl' (pip install openpyxl) -- exporting CSV instead.")
                db.export_csv(filepath.rsplit(".", 1)[0] + ".csv", trades)
                return
        else:
            db.export_csv(filepath, trades)

        self.export_status.configure(text=f"Exported {len(trades)} trade(s) to {filepath}")

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _drain_queue(self):
        """Main-thread only: drains result queue and applies UI updates safely."""
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            args = self._result_queue.get_nowait()
            if isinstance(args, tuple):
                self._apply_refresh(*args)
            else:
                self._apply_refresh(args)
        except Exception:
            pass
        self.after(100, self._drain_queue)

    def destroy(self):
        self._destroyed = True
        try:
            super().destroy()
        except Exception:
            pass

    def _auto_refresh(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        threading.Thread(target=self._bg_refresh, daemon=True).start()
        self.after(REFRESH_MS, self._auto_refresh)

    def _refresh(self):
        if self._destroyed:
            return
        threading.Thread(target=self._bg_refresh, daemon=True).start()

    def _bg_refresh(self):
        """Fetch all data in background, then apply to UI on main thread."""
        try:
            account      = db.get_account()
            balance      = account.get("balance", 0.0)
            floating_pnl = self.engine.get_floating_pnl()
            all_trades   = db.get_trades()
            stats        = analytics.compute_stats(all_trades)
            open_trades  = db.get_open_trades()
            filtered     = db.get_trades(
                symbol=self.filter_symbol.get(),
                timeframe=self.filter_timeframe.get(),
                status=self.filter_status.get(),
                limit=200,
            )
            symbols    = ["All"] + db.get_distinct_symbols()
            timeframes = ["All"] + db.get_distinct_timeframes()
            status_txt = self.engine.get_status_text()
            running    = self.engine.is_running()
            self._result_queue.put_nowait((balance, floating_pnl, stats, filtered, symbols, timeframes, status_txt, running))
        except Exception:
            pass

    def _apply_refresh(self, balance, floating_pnl, stats, filtered,
                       symbols, timeframes, status_txt, running):
        equity = balance + floating_pnl
        pnl_color = Colors.BUY if floating_pnl >= 0 else Colors.SELL

        self.btn_toggle.configure(
            text="⏸ Pause Auto-Trading" if running else "▶ Resume Auto-Trading",
            fg_color=Colors.SELL if running else Colors.BUY,
            text_color=Colors.ON_SELL if running else Colors.ON_BUY,
        )
        self.lbl_status.configure(text=status_txt)
        self.lbl_balance.configure(text=f"BALANCE: ${balance:,.2f}")
        self.lbl_equity.configure(
            text=f"EQUITY: ${equity:,.2f}  (Float P/L: {'+' if floating_pnl >= 0 else ''}"
                 f"${floating_pnl:,.2f})",
            text_color=pnl_color)

        if list(self.filter_symbol.cget("values")) != symbols:
            self.filter_symbol.configure(values=symbols)
        if list(self.filter_timeframe.cget("values")) != timeframes:
            self.filter_timeframe.configure(values=timeframes)

        self._update_stats(stats)
        self.equity_curve.draw(stats["equity_curve"])
        self._render_rows(filtered)

    def _estimate_floating_pnl(self, open_trades: list) -> float:
        """Pull live floating P&L directly from the engine's mark-to-market."""
        try:
            return self.engine.get_floating_pnl()
        except Exception:
            return 0.0

    def _update_stats(self, stats: dict):
        self.stat_cards["Total Trades"].set(str(stats["total_trades"]))
        self.stat_cards["Wins"].set(str(stats["wins"]), Colors.BUY)
        self.stat_cards["Losses"].set(str(stats["losses"]), Colors.SELL)
        self.stat_cards["Win Rate"].set(f"{stats['win_rate']:.1f}%", Colors.BUY)
        self.stat_cards["Loss Rate"].set(f"{stats['loss_rate']:.1f}%", Colors.SELL)
        self.stat_cards["Total P/L"].set(f"${stats['total_pnl']:,.2f}",
                                          Colors.BUY if stats["total_pnl"] >= 0 else Colors.SELL)
        self.stat_cards["Avg Profit"].set(f"${stats['avg_profit']:,.2f}", Colors.BUY)
        self.stat_cards["Avg Loss"].set(f"${stats['avg_loss']:,.2f}", Colors.SELL)
        self.stat_cards["Risk:Reward"].set(f"1:{stats['risk_reward']:.2f}")
        self.stat_cards["Max Drawdown"].set(f"${stats['max_drawdown']:,.2f} ({stats['max_drawdown_pct']:.1f}%)", Colors.SELL)

    def _render_rows(self, trades: list):
        for child in self.table.winfo_children():
            child.destroy()
        self._render_table_header()

        if not trades:
            ctk.CTkLabel(self.table, text="No paper trades match the current filters.",
                         font=SF.SMALL(), text_color=Colors.TEXT_MUTED).pack(pady=16)
            return

        for t in trades:
            row = ctk.CTkFrame(self.table, fg_color=Colors.CARD_BG, corner_radius=s(6))
            row.pack(fill="x", padx=2, pady=1)
            for i in range(10):
                row.grid_columnconfigure(i, weight=1)

            dir_color = Colors.BUY if t["signal_type"] == "BUY" else Colors.SELL
            if t["status"] == "OPEN":
                pnl_text, pnl_color, result_text = "--", Colors.TEXT_MUTED, "OPEN"
            else:
                pnl = t.get("pnl") or 0.0
                pnl_color = Colors.BUY if pnl >= 0 else Colors.SELL
                pnl_text = f"${pnl:,.2f}"
                result_text = t.get("result", "")

            opened_str = time.strftime("%m-%d %H:%M", time.localtime(t["opened_at"]))
            values = [
                (opened_str, Colors.TEXT_MUTED),
                (t["symbol"], Colors.TEXT),
                (t["signal_type"], dir_color),
                (f"{t['entry_price']:,.4f}", Colors.TEXT_SECONDARY),
                (f"{t['exit_price']:,.4f}" if t.get("exit_price") else "--", Colors.TEXT_SECONDARY),
                (f"{t['stop_loss']:,.4f}", Colors.TEXT_SECONDARY),
                (f"{t['take_profit']:,.4f}", Colors.TEXT_SECONDARY),
                (t.get("size_label", ""), Colors.TEXT_SECONDARY),
                (pnl_text, pnl_color),
                (result_text, pnl_color),
            ]
            for i, (text, color) in enumerate(values):
                ctk.CTkLabel(row, text=text, font=SF.MONO_TINY(), text_color=color).grid(
                    row=0, column=i, sticky="w", padx=4, pady=6)
