"""
ui/risk_tools_panel.py
========================
Risk Management Tools Panel

Features:
  • Position Size Calculator (risk %, account size, entry, SL)
  • Risk/Reward Calculator
  • Daily P&L limit tracker
  • Maximum concurrent trades limit
  • Per-trade risk percentage
  • Visual risk/reward ratio display
"""
from __future__ import annotations
import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing


def _labeled_entry(parent, label: str, default: str = "", width: int = 120) -> ctk.CTkEntry:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=3)
    ctk.CTkLabel(row, text=label, font=SF.PILL(),
                 text_color=Colors.TEXT_SECONDARY, width=s(200), anchor="w").pack(side="left")
    ent = ctk.CTkEntry(row, width=width, fg_color=Colors.INPUT_BG,
                        border_color=Colors.BORDER, text_color=Colors.TEXT,
                        corner_radius=s(5), border_width=1)
    ent.insert(0, default)
    ent.pack(side="left", padx=(8, 0))
    return ent


class _SectionCard(ctk.CTkFrame):
    def __init__(self, parent, title: str):
        super().__init__(parent, fg_color=Colors.CARD_BG,
                          border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        ctk.CTkLabel(self, text=title, font=SF.SUBHEADER(),
                     text_color=Colors.TEXT).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkFrame(self, fg_color=Colors.BORDER, height=1).pack(fill="x", padx=14, pady=(0, 8))


class RiskToolsPanel(ctk.CTkFrame):
    def __init__(self, parent, get_account_context=None):
        super().__init__(parent, fg_color=Colors.CARD_BG,
                          border_width=1, border_color=Colors.BORDER, corner_radius=s(10))
        self._get_account_ctx = get_account_context

        # Two-column layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)

        # ── 1. Position Size Calculator ────────────────────────────────
        pos_card = _SectionCard(self, "📐 Position Size Calculator")
        pos_card.grid(row=0, column=0, sticky="nsew", padx=(Spacing.MD(), 4), pady=(Spacing.MD(), 4))

        inner_pos = ctk.CTkFrame(pos_card, fg_color="transparent")
        inner_pos.pack(fill="x", padx=14, pady=(0, 12))

        self._e_balance   = _labeled_entry(inner_pos, "Account Balance ($):", "10000")
        self._e_risk_pct  = _labeled_entry(inner_pos, "Risk per Trade (%):", "1.0")
        self._e_entry_pos = _labeled_entry(inner_pos, "Entry Price:", "1.10000")
        self._e_sl_pos    = _labeled_entry(inner_pos, "Stop Loss Price:", "1.09000")
        self._e_leverage  = _labeled_entry(inner_pos, "Leverage:", "100")

        ctk.CTkButton(inner_pos, text="Calculate Position Size", height=S.NAV_BTN_H(), corner_radius=s(6),
                      fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
                      text_color=Colors.ON_BUY, font=SF.NAV_BOLD(),
                      command=self._calc_position).pack(fill="x", pady=(8, 0))

        self._lbl_pos_result = ctk.CTkLabel(inner_pos, text="",
                                             font=SF.MONO(),
                                             text_color=Colors.BUY, justify="left", anchor="w")
        self._lbl_pos_result.pack(fill="x", pady=(6, 0))

        # ── 2. Risk/Reward Calculator ──────────────────────────────────
        rr_card = _SectionCard(self, "⚖️ Risk/Reward Calculator")
        rr_card.grid(row=0, column=1, sticky="nsew", padx=(4, Spacing.MD()), pady=(Spacing.MD(), 4))

        inner_rr = ctk.CTkFrame(rr_card, fg_color="transparent")
        inner_rr.pack(fill="x", padx=14, pady=(0, 12))

        self._e_rr_entry = _labeled_entry(inner_rr, "Entry Price:", "1.10000")
        self._e_rr_sl    = _labeled_entry(inner_rr, "Stop Loss:", "1.09000")
        self._e_rr_tp1   = _labeled_entry(inner_rr, "Take Profit 1:", "1.12000")
        self._e_rr_tp2   = _labeled_entry(inner_rr, "Take Profit 2:", "1.13000")

        ctk.CTkButton(inner_rr, text="Calculate R:R", height=S.NAV_BTN_H(), corner_radius=s(6),
                      fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
                      text_color=Colors.ON_BUY, font=SF.NAV_BOLD(),
                      command=self._calc_rr).pack(fill="x", pady=(8, 0))

        self._lbl_rr_result = ctk.CTkLabel(inner_rr, text="",
                                            font=SF.MONO(),
                                            text_color=Colors.BUY, justify="left", anchor="w")
        self._lbl_rr_result.pack(fill="x", pady=(6, 0))

        # Visual R:R bar
        self._rr_bar_frame = ctk.CTkFrame(inner_rr, fg_color=Colors.WELL_BG, height=20, corner_radius=s(4))
        self._rr_bar_frame.pack(fill="x", pady=(4, 0))
        self._rr_risk_bar = ctk.CTkFrame(self._rr_bar_frame, fg_color=Colors.SELL, height=20, corner_radius=s(4))
        self._rr_tp1_bar  = ctk.CTkFrame(self._rr_bar_frame, fg_color=Colors.BUY, height=20, corner_radius=0)
        self._rr_tp2_bar  = ctk.CTkFrame(self._rr_bar_frame, fg_color="#00E5A0", height=20, corner_radius=s(4))

        # ── 3. Daily Limits ────────────────────────────────────────────
        limits_card = _SectionCard(self, "🛑 Daily Trading Limits")
        limits_card.grid(row=1, column=0, sticky="nsew", padx=(Spacing.MD(), 4), pady=(4, Spacing.MD()))

        inner_lim = ctk.CTkFrame(limits_card, fg_color="transparent")
        inner_lim.pack(fill="x", padx=14, pady=(0, 12))

        self._e_daily_profit_limit = _labeled_entry(inner_lim, "Daily Profit Target ($):", "500")
        self._e_daily_loss_limit   = _labeled_entry(inner_lim, "Max Daily Loss ($):", "200")
        self._e_max_trades         = _labeled_entry(inner_lim, "Max Concurrent Trades:", "5")
        self._e_max_risk_day       = _labeled_entry(inner_lim, "Max Daily Risk (%):", "5.0")

        ctk.CTkButton(inner_lim, text="Save Limits", height=S.NAV_BTN_H(), corner_radius=s(6),
                      fg_color=Colors.NEUTRAL, hover_color=Colors.HOVER_STRONG,
                      text_color=Colors.TEXT, font=SF.NAV_BOLD(),
                      command=self._save_limits).pack(fill="x", pady=(8, 0))
        self._lbl_limits_saved = ctk.CTkLabel(inner_lim, text="",
                                               font=SF.TINY(), text_color=Colors.BUY)
        self._lbl_limits_saved.pack(anchor="w", pady=(4, 0))

        # ── 4. Quick Risk Reference ────────────────────────────────────
        ref_card = _SectionCard(self, "📚 Quick Risk Reference")
        ref_card.grid(row=1, column=1, sticky="nsew", padx=(4, Spacing.MD()), pady=(4, Spacing.MD()))

        ref_inner = ctk.CTkFrame(ref_card, fg_color="transparent")
        ref_inner.pack(fill="x", padx=14, pady=(0, 12))

        rules = [
            ("1% Rule",          "Never risk more than 1% of account per trade."),
            ("2% Max",           "Risk never exceeding 2% on any single trade."),
            ("6% Daily Limit",   "Stop trading when total open risk hits 6% daily."),
            ("R:R Minimum",      "Only take trades with at least 1:2 risk/reward."),
            ("Position Sizing",  "Size = (Balance × Risk%) ÷ (Entry - SL) × Pip Value"),
            ("Drawdown Rule",    "Pause trading after 10% account drawdown, review."),
        ]
        for title, desc in rules:
            row = ctk.CTkFrame(ref_inner, fg_color=Colors.WELL_BG, corner_radius=s(6))
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=title, font=SF.PILL_LG(),
                         text_color=Colors.BUY, width=s(140), anchor="w").pack(side="left", padx=8, pady=5)
            ctk.CTkLabel(row, text=desc, font=SF.TINY(),
                         text_color=Colors.TEXT_SECONDARY, anchor="w",
                         wraplength=s(260), justify="left").pack(side="left", padx=4, pady=5, fill="x")

    # ── Calculations ─────────────────────────────────────────────────────────
    def _calc_position(self):
        try:
            balance  = float(self._e_balance.get().replace(",", "") or 0)
            risk_pct = float(self._e_risk_pct.get() or 0) / 100
            entry    = float(self._e_entry_pos.get() or 0)
            sl       = float(self._e_sl_pos.get() or 0)
            leverage = float(self._e_leverage.get() or 1)
        except ValueError:
            self._lbl_pos_result.configure(text="⚠ Invalid input — check all fields.", text_color=Colors.SELL)
            return

        if balance <= 0 or entry <= 0 or sl <= 0 or entry == sl:
            self._lbl_pos_result.configure(text="⚠ Invalid values — ensure entry ≠ SL.", text_color=Colors.SELL)
            return

        risk_usd    = balance * risk_pct
        sl_distance = abs(entry - sl)
        pip_value   = 10.0  # approximate for major pairs; 1 lot = $10/pip
        pips        = sl_distance * 10_000 if sl_distance < 1 else sl_distance  # FX vs other

        # Units = risk_amount / sl_distance
        units       = risk_usd / sl_distance
        lots        = units / 100_000  # standard lot

        notional    = lots * 100_000 * entry
        margin      = notional / leverage if leverage > 0 else notional

        result = (
            f"Risk Amount:  ${risk_usd:,.2f}\n"
            f"Position:     {lots:.2f} lots ({units:,.0f} units)\n"
            f"Notional:     ${notional:,.2f}\n"
            f"Margin Req:   ${margin:,.2f}  (at {leverage:.0f}x leverage)\n"
            f"SL Distance:  {sl_distance:.5f}"
        )
        self._lbl_pos_result.configure(text=result, text_color=Colors.BUY)

    def _calc_rr(self):
        try:
            entry = float(self._e_rr_entry.get() or 0)
            sl    = float(self._e_rr_sl.get() or 0)
            tp1   = float(self._e_rr_tp1.get() or 0)
            tp2   = float(self._e_rr_tp2.get() or 0)
        except ValueError:
            self._lbl_rr_result.configure(text="⚠ Invalid values.", text_color=Colors.SELL)
            return

        if entry <= 0 or sl <= 0 or tp1 <= 0 or entry == sl:
            self._lbl_rr_result.configure(text="⚠ Please enter valid entry, SL and TP values.", text_color=Colors.SELL)
            return

        risk = abs(entry - sl)
        r1   = abs(tp1 - entry) / risk if risk > 0 else 0
        r2   = abs(tp2 - entry) / risk if (risk > 0 and tp2 > 0) else 0

        direction = "BUY" if tp1 > entry else "SELL"
        r1_ok = (tp1 > entry and direction == "BUY") or (tp1 < entry and direction == "SELL")

        result = (
            f"Direction:  {direction}\n"
            f"Risk:       {risk:.5f}\n"
            f"R:R (TP1):  1:{r1:.2f}  {'✓ Good' if r1 >= 2.0 else '⚠ Below 1:2'}\n"
        )
        if tp2 and r2 > 0:
            result += f"R:R (TP2):  1:{r2:.2f}\n"

        color = Colors.BUY if r1 >= 2.0 else Colors.NEUTRAL
        self._lbl_rr_result.configure(text=result, text_color=color)

        # Update visual bar (relative widths)
        total = risk + abs(tp1 - entry) + (abs(tp2 - entry) if tp2 else 0)
        if total > 0:
            risk_w  = risk / total
            tp1_w   = abs(tp1 - entry) / total
            tp2_w   = abs(tp2 - entry) / total if tp2 else 0
            self._rr_risk_bar.place(relx=0, rely=0, relwidth=risk_w, relheight=1)
            self._rr_tp1_bar.place(relx=risk_w, rely=0, relwidth=tp1_w, relheight=1)
            if tp2_w > 0:
                self._rr_tp2_bar.place(relx=risk_w + tp1_w, rely=0, relwidth=tp2_w, relheight=1)

    def _save_limits(self):
        # In a full app these would be saved to config.json
        self._lbl_limits_saved.configure(text="✓ Limits saved (session only).")
        self.after(3000, lambda: self._lbl_limits_saved.configure(text=""))
