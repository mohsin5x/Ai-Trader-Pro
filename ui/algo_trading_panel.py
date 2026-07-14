"""
ui/algo_trading_panel.py
============================
Algo Trading Dashboard — always-on automatic paper trading.

Changes:
  • No Start/Stop button — engine runs automatically from app launch
  • Live Balance / Equity / Float P&L updated every 2 s
  • Full stats grid (14 cards) including Profit Factor, Best/Worst trade,
    Best/Worst streak, Avg duration
  • Open trades table with live P&L per row
  • All DB reads happen on a background thread → zero UI freezes
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import customtkinter as ctk
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from services import paper_trading_db as db
from services import paper_trading_analytics as analytics
from ui.modal_overlay import make_dialog

REFRESH_MS = 2000
STARTING_BALANCE_PRESETS = [100, 500, 1_000, 5_000, 10_000, 25_000]


class _StatCard(ctk.CTkFrame):
    def __init__(self, parent, label: str):
        super().__init__(parent, fg_color=Colors.WELL_BG, border_width=1,
                          border_color=Colors.BORDER, corner_radius=s(8))
        self._destroyed = False
        ctk.CTkLabel(self, text=label, font=SF.TINY(),
                     text_color=Colors.LABEL).pack(anchor="w", padx=10, pady=(7, 0))
        self._lbl = ctk.CTkLabel(self, text="—",
                                  font=SF.PRICE_SM(), text_color=Colors.TEXT)
        self._lbl.pack(anchor="w", padx=10, pady=(0, 7))

    def set(self, text: str, color: str = None):
        self._lbl.configure(text=text, text_color=color or Colors.TEXT)


class _EquityCurve(ctk.CTkFrame):
    def __init__(self, parent, height: int = 130):
        super().__init__(parent, fg_color=Colors.WELL_BG, border_width=1,
                          border_color=Colors.BORDER, corner_radius=s(8))
        self._canvas = tk.Canvas(self, height=height, highlightthickness=0,
                                  bg=Colors.WELL_BG)
        self._canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self._canvas.bind("<Configure>", lambda _e: self._redraw())
        self._pts: list = []

    def draw(self, pts: list):
        self._pts = pts
        self._redraw()

    def _redraw(self):
        c = self._canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10 or h < 10:
            return
        if len(self._pts) < 2:
            c.create_text(w / 2, h / 2,
                          text="Not enough closed trades yet for an equity curve",
                          fill=Colors.TEXT_MUTED, font=SF.PILL())
            return
        vals = [p[1] for p in self._pts]
        vmin, vmax = min(vals), max(vals)
        if vmin == vmax:
            vmin -= 1; vmax += 1
        pad = 10

        def sc(i, v):
            x = pad + (i / (len(vals) - 1)) * (w - 2 * pad)
            y = h - pad - ((v - vmin) / (vmax - vmin)) * (h - 2 * pad)
            return x, y

        zy = h - pad - ((0 - vmin) / (vmax - vmin)) * (h - 2 * pad)
        if pad <= zy <= h - pad:
            c.create_line(0, zy, w, zy, fill=Colors.BORDER, dash=(3, 3))
        color = Colors.BUY if vals[-1] >= vals[0] else Colors.SELL
        coords = []
        for i, v in enumerate(vals):
            coords.extend(sc(i, v))
        c.create_line(*coords, fill=color, width=2, smooth=True)


class AlgoTradingPanel(ctk.CTkFrame):
    def __init__(self, parent, engine):
        super().__init__(parent, fg_color=Colors.CARD_BG, border_width=1,
                          border_color=Colors.BORDER, corner_radius=s(10))
        self._destroyed = False
        self.engine = engine
        self._result_queue = queue.Queue(maxsize=2)   # panel-level queue (was missing — caused blank panel)

        # ── Header ───────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 4))

        ctk.CTkLabel(
            hdr, text="ALGO TRADING  — Fully Automatic (simulated, no real orders)",
            font=SF.SUBHEADER(), text_color=Colors.TEXT,
        ).pack(side="left")

        self.lbl_status = ctk.CTkLabel(
            hdr, text="● Starting…",
            font=SF.NAV_BOLD(), text_color=Colors.NEUTRAL)
        self.lbl_status.pack(side="right", padx=6)

        # ── Account bar ──────────────────────────────────────────────
        acct = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8))
        acct.pack(fill="x", padx=Spacing.MD(), pady=4)

        self.lbl_balance = ctk.CTkLabel(
            acct, text="BALANCE: $0.00", font=SF.MONO(), text_color=Colors.TEXT)
        self.lbl_balance.pack(side="left", padx=10, pady=8)

        self.lbl_equity = ctk.CTkLabel(
            acct, text="EQUITY: $0.00", font=SF.MONO(), text_color=Colors.TEXT_SECONDARY)
        self.lbl_equity.pack(side="left", padx=10, pady=8)

        self.lbl_float = ctk.CTkLabel(
            acct, text="FLOAT P/L: $0.00", font=SF.MONO(), text_color=Colors.TEXT_MUTED)
        self.lbl_float.pack(side="left", padx=10, pady=8)

        self.lbl_return = ctk.CTkLabel(
            acct, text="RETURN: 0.00%", font=SF.MONO(), text_color=Colors.TEXT_MUTED)
        self.lbl_return.pack(side="left", padx=10, pady=8)

        btn_kw = dict(height=s(26), corner_radius=s(6), font=SF.PILL_LG(),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                      text_color=Colors.TEXT)
        ctk.CTkButton(acct, text="Deposit",  width=s(80), command=self._on_deposit,
                      **btn_kw).pack(side="right", padx=(4, 10), pady=8)
        ctk.CTkButton(acct, text="Withdraw", width=s(80), command=self._on_withdraw,
                      **btn_kw).pack(side="right", padx=4, pady=8)
        ctk.CTkButton(acct, text="Reset Account", width=S.BTN_W_MD(), command=self._on_reset,
                      **btn_kw).pack(side="right", padx=4, pady=8)

        # Starting-balance presets
        pre_row = ctk.CTkFrame(self, fg_color="transparent")
        pre_row.pack(fill="x", padx=Spacing.MD(), pady=(0, 4))
        ctk.CTkLabel(pre_row, text="Set starting balance:", font=SF.TINY(),
                     text_color=Colors.TEXT_MUTED).pack(side="left", padx=(0, 6))
        for amt in STARTING_BALANCE_PRESETS:
            ctk.CTkButton(
                pre_row, text=f"${amt:,}", width=74, height=S.ICON_BTN(), corner_radius=s(6),
                fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                text_color=Colors.TEXT, font=SF.PILL(),
                command=lambda a=amt: self._confirm_reset(a),
            ).pack(side="left", padx=2)
        ctk.CTkButton(
            pre_row, text="Custom…", width=s(80), height=S.ICON_BTN(), corner_radius=s(6),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT, font=SF.PILL(),
            command=self._custom_balance,
        ).pack(side="left", padx=2)

        # ── Stats grid (14 cards, 7 per row) ────────────────────────
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=Spacing.MD(), pady=4)
        for i in range(7):
            grid.grid_columnconfigure(i, weight=1)

        stat_labels = [
            "Total Trades", "Open Trades", "Wins", "Losses", "Win Rate",
            "Profit Factor", "Total P/L",
            "Avg Profit", "Avg Loss", "Best Trade", "Worst Trade",
            "Best Streak", "Worst Streak", "Max Drawdown",
        ]
        self._stat_cards: dict[str, _StatCard] = {}
        for i, lbl in enumerate(stat_labels):
            card = _StatCard(grid, lbl)
            card.grid(row=i // 7, column=i % 7, sticky="ew", padx=2, pady=2)
            self._stat_cards[lbl] = card

        # ── Equity curve ─────────────────────────────────────────────
        ctk.CTkLabel(self, text="EQUITY CURVE", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(anchor="w", padx=Spacing.MD(), pady=(6, 2))
        self._equity_curve = _EquityCurve(self)
        self._equity_curve.pack(fill="x", padx=Spacing.MD(), pady=(0, 4))

        # ── Open trades mini-table ───────────────────────────────────
        ctk.CTkLabel(self, text="OPEN PAPER TRADES (live mark-to-market)",
                     font=SF.TINY(), text_color=Colors.LABEL).pack(
            anchor="w", padx=Spacing.MD(), pady=(4, 2))
        self._open_tbl = ctk.CTkScrollableFrame(
            self, fg_color=Colors.WELL_BG, corner_radius=s(6), height=130,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY)
        bind_fast_scroll(self._open_tbl)  # fast scroll fix
        self._open_tbl.pack(fill="x", padx=Spacing.MD(), pady=(0, Spacing.MD()))

        self._trigger_refresh()
        self._schedule()
        self._drain_queue()

    # ── Refresh cycle ─────────────────────────────────────────────────
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
                self._ui_update(*args)
        except queue.Empty:
            pass           # nothing ready yet — normal
        except Exception as exc:
            from utils.logger import logger
            logger.warning(f"[AlgoTradingPanel._drain_queue] {type(exc).__name__}: {exc}")
        self.after(100, self._drain_queue)

    def destroy(self):
        self._destroyed = True
        try:
            super().destroy()
        except Exception:
            pass

    def _trigger_refresh(self):
        if self._destroyed:
            return
        threading.Thread(target=self._bg_fetch, daemon=True).start()

    def _bg_fetch(self):
        try:
            account      = db.get_account()
            balance      = account.get("balance", 0.0)
            floating_pnl = self.engine.get_floating_pnl()
            all_trades   = db.get_trades()
            stats        = analytics.compute_stats(all_trades)
            rt           = analytics.compute_realtime_stats(all_trades, balance, floating_pnl)
            open_trades  = self.engine.get_open_trades_snapshot()
            # Fallback: if engine hasn't populated in-memory cache yet, read directly from DB
            if not open_trades:
                raw_db = db.get_open_trades()
                open_trades = [dict(t) for t in raw_db]
                for t in open_trades:
                    t.setdefault("live_pnl", 0.0)

            if self.engine.is_running():
                n = len(open_trades)
                status_txt = f"Auto-running — {n} open paper trade{'s' if n != 1 else ''}"
            else:
                status_txt = "Engine initialising…"

            payload = (balance, floating_pnl, stats, rt, open_trades, status_txt)
            # Always replace stale queue item so UI always gets latest data
            try:
                self._result_queue.get_nowait()   # discard any unread stale result
            except queue.Empty:
                pass
            self._result_queue.put_nowait(payload)
        except Exception as exc:
            from utils.logger import logger
            logger.warning(f"[AlgoTradingPanel._bg_fetch] {type(exc).__name__}: {exc}")

    def _ui_update(self, balance: float, floating_pnl: float,
                   stats: dict, rt: dict, open_trades: list, status_txt: str):
        # Status indicator: green = running, orange = initialising
        if self.engine.is_running():
            status_color = Colors.BUY
        else:
            status_color = Colors.NEUTRAL
        self.lbl_status.configure(text=f"● {status_txt}", text_color=status_color)

        pnl_color = Colors.BUY if floating_pnl >= 0 else Colors.SELL
        equity    = balance + floating_pnl
        sign      = "+" if floating_pnl >= 0 else ""
        ret_pct   = rt.get("return_pct", 0.0)
        ret_col   = Colors.BUY if ret_pct >= 0 else Colors.SELL

        self.lbl_balance.configure(text=f"BALANCE: ${balance:,.2f}")
        self.lbl_equity.configure(text=f"EQUITY: ${equity:,.2f}", text_color=pnl_color)
        self.lbl_float.configure(text=f"FLOAT P/L: {sign}${floating_pnl:,.2f}", text_color=pnl_color)
        self.lbl_return.configure(text=f"RETURN: {ret_pct:+.2f}%", text_color=ret_col)

        self._update_stats(stats)
        self._equity_curve.draw(stats["equity_curve"])
        self._render_open_trades(open_trades)

    def _update_stats(self, s: dict):
        def _c(v): return Colors.BUY if v >= 0 else Colors.SELL

        self._stat_cards["Total Trades"].set(str(s["total_trades"]))
        self._stat_cards["Open Trades"].set(str(s["open_trades"]), Colors.NEUTRAL)
        self._stat_cards["Wins"].set(str(s["wins"]), Colors.BUY)
        self._stat_cards["Losses"].set(str(s["losses"]), Colors.SELL)
        self._stat_cards["Win Rate"].set(f"{s['win_rate']:.1f}%",
                                          Colors.BUY if s["win_rate"] >= 50 else Colors.SELL)
        self._stat_cards["Profit Factor"].set(
            f"{s['profit_factor']:.2f}",
            Colors.BUY if s["profit_factor"] >= 1 else Colors.SELL)
        self._stat_cards["Total P/L"].set(f"${s['total_pnl']:,.2f}", _c(s["total_pnl"]))
        self._stat_cards["Avg Profit"].set(f"${s['avg_profit']:,.2f}", Colors.BUY)
        self._stat_cards["Avg Loss"].set(f"${abs(s['avg_loss']):,.2f}", Colors.SELL)
        self._stat_cards["Best Trade"].set(f"${s['best_trade']:,.2f}", Colors.BUY)
        self._stat_cards["Worst Trade"].set(f"${s['worst_trade']:,.2f}", Colors.SELL)
        self._stat_cards["Best Streak"].set(f"{s['best_streak']} W", Colors.BUY)
        self._stat_cards["Worst Streak"].set(f"{s['worst_streak']} L", Colors.SELL)
        self._stat_cards["Max Drawdown"].set(
            f"${s['max_drawdown']:,.2f} ({s['max_drawdown_pct']:.1f}%)", Colors.SELL)

    def _render_open_trades(self, trades: list):
        import time as _time
        for w in self._open_tbl.winfo_children():
            w.destroy()
        if not trades:
            ctk.CTkLabel(self._open_tbl,
                          text="No open paper trades — engine scanning for AI signals.",
                          font=SF.TINY(), text_color=Colors.TEXT_MUTED).pack(pady=12)
            return

        # Column header
        hdr = ctk.CTkFrame(self._open_tbl, fg_color="transparent")
        hdr.pack(fill="x", padx=2, pady=(2, 1))
        for i, (w, txt) in enumerate([(3,"Symbol"),(2,"Dir"),(3,"Entry"),(2,"Size"),
                                       (2,"Lev"),(2,"Conf"),(3,"P/L"),(4,"Opened At"),(3,"Timer"),(2,"Action")]):
            hdr.grid_columnconfigure(i, weight=w)
            ctk.CTkLabel(hdr, text=txt, font=(Fonts.TINY[0], Fonts.TINY[1]),
                          text_color=Colors.LABEL).grid(row=0, column=i, sticky="w", padx=6)

        now = _time.time()
        for t in trades:
            pnl       = t.get("live_pnl", 0.0)
            pnl_col   = Colors.BUY if pnl >= 0 else Colors.SELL
            direction = t.get("signal_type") or t.get("direction", "—")
            dir_col   = Colors.BUY if direction == "BUY" else Colors.SELL
            lev       = t.get("leverage", 1)
            entry     = t.get("entry_price", 0.0)
            size_lbl  = t.get("size_label", "—")
            conf      = t.get("confidence", 0)
            pnl_sign  = "+" if pnl >= 0 else ""
            sym       = t.get("symbol") or t.get("coin") or t.get("asset") or "—"
            if not sym or sym == "—":
                continue  # skip sentinel/reserved entries

            # Scalp timer display
            max_dur = t.get("_max_duration_s", 0.0)
            if max_dur and max_dur > 0:
                elapsed    = now - t.get("opened_at", now)
                remaining  = max(0.0, max_dur - elapsed)
                mins_left  = int(remaining // 60)
                secs_left  = int(remaining % 60)
                timer_txt  = f"⏱ {mins_left}m{secs_left:02d}s"
                timer_col  = Colors.SELL if remaining < 60 else Colors.NEUTRAL
            else:
                timer_txt  = "TP/SL"
                timer_col  = Colors.TEXT_MUTED

            # Format opened_at timestamp
            opened_at = t.get("opened_at", 0)
            try:
                import time as _t2
                opened_str = _t2.strftime("%m-%d %H:%M:%S", _t2.localtime(float(opened_at)))
            except Exception:
                opened_str = "—"

            row = ctk.CTkFrame(self._open_tbl, fg_color=Colors.CARD_BG,
                                corner_radius=s(4), border_width=1, border_color=Colors.BORDER)
            row.pack(fill="x", padx=2, pady=2)
            for i, w in enumerate((3,2,3,2,2,2,3,4,3,2)):
                row.grid_columnconfigure(i, weight=w)

            vals = [
                (sym,                        Colors.TEXT),
                (direction,                  dir_col),
                (f"{entry:.5f}",             Colors.TEXT_SECONDARY),
                (size_lbl,                   Colors.TEXT_SECONDARY),
                (f"{lev}x",                  Colors.NEUTRAL),
                (f"{conf}%",                 Colors.TEXT_MUTED),
                (f"{pnl_sign}${pnl:,.2f}",   pnl_col),
                (opened_str,                 Colors.TEXT_MUTED),
                (timer_txt,                  timer_col),
            ]
            for col, (val, color) in enumerate(vals):
                ctk.CTkLabel(row, text=val, font=SF.MONO_TINY(),
                              text_color=color).grid(row=0, column=col, sticky="w", padx=5, pady=6)

            # Close Now button
            ctk.CTkButton(
                row, text="✕ Close", width=s(70), height=s(26), corner_radius=s(5),
                fg_color=Colors.SELL, hover_color=Colors.SELL_HOVER,
                text_color=Colors.TEXT, font=SF.STATUS_BOLD(),
                command=lambda s=sym: self._close_trade(s),
            ).grid(row=0, column=9, padx=(4, 8), pady=4)

    def _close_trade(self, symbol: str):
        """Force-close a paper trade at market price via the engine."""
        try:
            msg = self.engine.close_trade_now(symbol)
            from services.notification_center import nc
            nc.push("paper_trade", "Trade Closed", msg)
            self._trigger_refresh()
        except Exception as exc:
            from utils.logger import logger
            logger.warning(f"[AlgoPanel.close_trade] {type(exc).__name__}: {exc}")

    # ── Account actions ────────────────────────────────────────────────
    def _on_deposit(self):
        self._amount_dialog("Deposit",
                            lambda a: db.apply_balance_delta(a, "DEPOSIT", "Manual deposit"))

    def _on_withdraw(self):
        self._amount_dialog("Withdraw",
                            lambda a: db.apply_balance_delta(-a, "WITHDRAWAL", "Manual withdrawal"))

    def _amount_dialog(self, label: str, on_confirm):
        dlg = ctk.CTkInputDialog(text=f"{label} amount (USD):", title=label)
        raw = dlg.get_input()
        if not raw:
            return
        try:
            amt = float(raw.replace(",", "").replace("$", "").strip())
        except ValueError:
            return
        if amt > 0:
            on_confirm(amt)
            self._trigger_refresh()

    def _on_reset(self):
        acct = db.get_account()
        self._confirm_reset(acct.get("starting_balance", 10_000.0))

    def _custom_balance(self):
        dlg = ctk.CTkInputDialog(text="Enter custom starting balance (USD):",
                                  title="Custom Starting Balance")
        raw = dlg.get_input()
        if not raw:
            return
        try:
            amt = float(raw.replace(",", "").replace("$", "").strip())
        except ValueError:
            return
        if amt > 0:
            self._confirm_reset(amt)

    def _confirm_reset(self, start_bal: float):
        win = ctk.CTkToplevel(self)
        win.configure(fg_color=Colors.APP_BG)
        make_dialog(win, self.winfo_toplevel(),
                    title="Confirm Reset", size=(380, 150))
        ctk.CTkLabel(
            win,
            text=f"Reset paper account to ${start_bal:,.2f}?\n\n"
                 "This permanently deletes all paper trade history.",
            font=SF.SMALL(), text_color=Colors.TEXT, wraplength=s(340), justify="left",
        ).pack(padx=16, pady=16)
        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=8)

        def _do():
            db.reset_account(start_bal)
            win.destroy()
            self._trigger_refresh()

        ctk.CTkButton(btn_row, text="Cancel", width=s(90),
                      fg_color=Colors.CARD_BG_ALT, command=win.destroy).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Confirm Reset", width=S.BTN_W_MD(),
                      fg_color=Colors.SELL, text_color=Colors.ON_SELL,
                      command=_do).pack(side="left", padx=6)

    def _refresh(self):
        """Public refresh method for external callers (main_window)."""
        self._cycle()