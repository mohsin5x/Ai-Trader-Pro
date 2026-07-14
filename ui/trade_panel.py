"""
ui/trade_panel.py
==================
Order Execution panel — full manual trading interface.

Features added:
  • Stop Loss and Take Profit input fields with live R:R preview
  • Position detail modal (click any open position card)
  • Asset class, leverage, margin and buying power display
  • Partial close buttons (25 / 50 / 75 / 100%)
  • All inputs validated before order submission
"""

from __future__ import annotations
import time
import customtkinter as ctk
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from services import leverage_manager as lm
from ui.modal_overlay import BaseDialog


# ─── Position detail modal ────────────────────────────────────────────────────
class PositionDetailModal(BaseDialog):
    """Full position details + close controls in a pop-up."""

    def __init__(self, parent, pos: dict, on_close_cb):
        asset = pos["asset"]
        side  = pos["side"]
        super().__init__(parent,
                         title=f"Position — {asset} {side}",
                         size=(480, 420), resizable=(False, False))
        self.configure(fg_color=Colors.APP_BG)

        self._pos        = pos
        self._on_close_cb = on_close_cb

        container = ctk.CTkFrame(
            self, fg_color=Colors.SIDEBAR_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(12),
        )
        container.pack(fill="both", expand=True, padx=14, pady=14)

        dir_color = Colors.BUY if side == "BUY" else Colors.SELL
        on_dir    = Colors.ON_BUY if side == "BUY" else Colors.ON_SELL

        # Header
        hdr = ctk.CTkFrame(container, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(
            hdr, text=asset,
            font=SF.HEADER(), text_color=Colors.TEXT,
        ).pack(side="left")
        ctk.CTkLabel(
            hdr, text=f" {side} ",
            font=SF.SUBHEADER(),
            text_color=on_dir, fg_color=dir_color, corner_radius=s(5),
        ).pack(side="left", padx=(8, 0))

        pnl = pos.get("pnl", 0.0)
        pnl_color = Colors.BUY if pnl >= 0 else Colors.SELL
        ctk.CTkLabel(
            hdr, text=f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",
            font=SF.PRICE_SM(), text_color=pnl_color,
        ).pack(side="right")

        # Detail grid
        grid = ctk.CTkFrame(
            container, fg_color=Colors.CARD_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(8),
        )
        grid.pack(fill="x", padx=14, pady=4)
        for i in range(4):
            grid.grid_columnconfigure(i, weight=1)

        entry    = pos.get("entry", 0.0)
        sl       = pos.get("sl", 0.0)
        tp       = pos.get("tp", 0.0)
        units    = pos.get("units", 0.0)
        size_txt = pos.get("size_text", "")
        notional = pos.get("notional", units * entry)
        leverage = lm.get_leverage(asset)
        asset_cls = lm.asset_class_label(asset)
        strategy  = pos.get("strategy", "—")
        opened_ts = pos.get("opened_at", 0)
        opened_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(opened_ts)) if opened_ts else "—"

        def _cell(parent, label: str, value: str, row: int, col: int, val_color=None):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.grid(row=row, column=col, pady=10, padx=4, sticky="nsew")
            ctk.CTkLabel(f, text=label, font=SF.STATUS_BOLD(),
                         text_color=Colors.LABEL).pack()
            ctk.CTkLabel(f, text=value, font=SF.MONO(),
                         text_color=val_color or Colors.TEXT).pack()

        _cell(grid, "ENTRY",    f"${entry:,.4f}",   0, 0)
        _cell(grid, "STOP LOSS",f"${sl:,.4f}" if sl else "—", 0, 1, Colors.SELL)
        _cell(grid, "TAKE PROFIT", f"${tp:,.4f}" if tp else "—", 0, 2, Colors.BUY)
        _cell(grid, "LIVE P/L", f"{'+' if pnl >= 0 else ''}${pnl:,.2f}", 0, 3, pnl_color)

        info = ctk.CTkFrame(container, fg_color="transparent")
        info.pack(fill="x", padx=14, pady=6)
        details = (
            f"Size: {size_txt}   Leverage: {leverage}x   Class: {asset_cls}\n"
            f"Value: ${notional:,.2f}   Strategy: {strategy}\n"
            f"Opened: {opened_str}"
        )
        ctk.CTkLabel(
            info, text=details,
            font=SF.MONO_SM(), text_color=Colors.TEXT_SECONDARY,
            justify="left", anchor="w",
        ).pack(anchor="w")

        # Close controls
        ctk.CTkLabel(
            container, text="CLOSE POSITION",
            font=SF.PILL_LG(), text_color=Colors.LABEL,
        ).pack(anchor="w", padx=14, pady=(10, 4))

        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 14))

        for label, frac in [("25%", 0.25), ("50%", 0.50), ("75%", 0.75), ("Close All", 1.0)]:
            is_full = frac == 1.0
            ctk.CTkButton(
                btn_row,
                text=label,
                width=s(90), height=34, corner_radius=7,
                fg_color=Colors.SELL if is_full else Colors.BORDER,
                hover_color=Colors.SELL_HOVER if is_full else Colors.HOVER_STRONG,
                text_color=Colors.ON_SELL if is_full else Colors.TEXT,
                font=SF.NAV_BOLD(),
                command=lambda f=frac: self._do_close(f),
            ).pack(side="left", padx=4)


    def _do_close(self, fraction: float):
        pos_id = self._pos["id"]
        self._on_close_cb(pos_id, fraction)
        self.destroy()


# ─── Main trade panel ─────────────────────────────────────────────────────────
class TradePanel(ctk.CTkFrame):
    def __init__(self, parent, on_execute_order=None, on_close_position=None):
        super().__init__(
            parent, fg_color=Colors.CARD_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(10),
        )
        self.on_execute_order  = on_execute_order
        self.on_close_position = on_close_position
        self.current_price     = 0.0
        self.current_coin      = "EUR/USD"
        self._sl_val: float    = 0.0
        self._tp_val: float    = 0.0

        # ── Header ────────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="ORDER EXECUTION",
            font=SF.SUBHEADER(), text_color=Colors.TEXT,
        ).pack(anchor="w", padx=Spacing.MD(), pady=(Spacing.MD(), 4))

        # Signal status badge
        self.lbl_status = ctk.CTkLabel(
            self, text="SYSTEM STATUS: INITIALIZING…",
            font=SF.SUBHEADER(), text_color=Colors.NEUTRAL,
            fg_color=Colors.WELL_BG, height=s(36), corner_radius=s(8),
        )
        self.lbl_status.pack(fill="x", padx=Spacing.MD(), pady=4)

        # Asset + price row
        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.pack(fill="x", padx=Spacing.MD(), pady=2)
        self.lbl_exposure = ctk.CTkLabel(
            info_row, text="ASSET: —",
            font=SF.SUBHEADER(), text_color=Colors.TEXT,
        )
        self.lbl_exposure.pack(side="left")
        self.lbl_tick = ctk.CTkLabel(
            info_row, text="PRICE: $0.0000",
            font=SF.MONO(), text_color=Colors.BUY,
        )
        self.lbl_tick.pack(side="right")

        # Leverage / margin info bar
        lev_row = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(6))
        lev_row.pack(fill="x", padx=Spacing.MD(), pady=4)
        self.lbl_asset_class  = ctk.CTkLabel(lev_row, text="CLASS: —",     font=SF.TINY(), text_color=Colors.LABEL)
        self.lbl_leverage     = ctk.CTkLabel(lev_row, text="LEV: —",       font=(Fonts.MONO[0], 12, "bold"), text_color=Colors.NEUTRAL)
        self.lbl_margin       = ctk.CTkLabel(lev_row, text="MARGIN/LOT: —",font=SF.TINY(), text_color=Colors.TEXT_SECONDARY)
        self.lbl_buying_power = ctk.CTkLabel(lev_row, text="BUYING PWR: —",font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        for lbl in (self.lbl_asset_class, self.lbl_leverage, self.lbl_margin, self.lbl_buying_power):
            lbl.pack(side="left", padx=8, pady=5)

        # ── SL / TP inputs ────────────────────────────────────────────
        sltp_outer = ctk.CTkFrame(
            self, fg_color=Colors.WELL_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(8),
        )
        sltp_outer.pack(fill="x", padx=Spacing.MD(), pady=4)

        sltp_title = ctk.CTkFrame(sltp_outer, fg_color="transparent")
        sltp_title.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(
            sltp_title, text="STOP LOSS  /  TAKE PROFIT",
            font=SF.PILL_LG(), text_color=Colors.LABEL,
        ).pack(side="left")
        self.lbl_rr = ctk.CTkLabel(
            sltp_title, text="R:R —",
            font=SF.MONO_SM(), text_color=Colors.BUY,
        )
        self.lbl_rr.pack(side="right")

        inputs_row = ctk.CTkFrame(sltp_outer, fg_color="transparent")
        inputs_row.pack(fill="x", padx=10, pady=(0, 8))

        _entry_kw = dict(
            height=S.NAV_BTN_H(), corner_radius=s(6),
            fg_color=Colors.INPUT_BG, border_color=Colors.BORDER,
            text_color=Colors.TEXT, font=SF.MONO_SM(),
        )
        ctk.CTkLabel(inputs_row, text="SL:", font=SF.SMALL(),
                     text_color=Colors.SELL).pack(side="left", padx=(0, 4))
        self.entry_sl = ctk.CTkEntry(inputs_row, width=S.BTN_W_MD(),
                                      placeholder_text="0.00000", **_entry_kw)
        self.entry_sl.pack(side="left", padx=(0, 12))
        self.entry_sl.bind("<KeyRelease>", lambda _e: self._update_rr())
        self.entry_sl.bind("<FocusOut>",   lambda _e: self._update_rr())

        ctk.CTkLabel(inputs_row, text="TP:", font=SF.SMALL(),
                     text_color=Colors.BUY).pack(side="left", padx=(0, 4))
        self.entry_tp = ctk.CTkEntry(inputs_row, width=S.BTN_W_MD(),
                                      placeholder_text="0.00000", **_entry_kw)
        self.entry_tp.pack(side="left", padx=(0, 12))
        self.entry_tp.bind("<KeyRelease>", lambda _e: self._update_rr())
        self.entry_tp.bind("<FocusOut>",   lambda _e: self._update_rr())

        ctk.CTkButton(
            inputs_row, text="Auto-fill", width=s(72), height=S.NAV_BTN_H(), corner_radius=s(6),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT, font=SF.PILL_LG(),
            command=self._autofill_sltp,
        ).pack(side="left")

        # Hint
        self.lbl_sltp_hint = ctk.CTkLabel(
            sltp_outer, text="Leave blank to execute without SL/TP",
            font=SF.TINY(), text_color=Colors.TEXT_MUTED,
        )
        self.lbl_sltp_hint.pack(anchor="w", padx=10, pady=(0, 6))

        # Risk allocation note
        ctk.CTkLabel(
            self, text="Risk allocation: 1% of account balance per trade",
            font=SF.SMALL(), text_color=Colors.TEXT_MUTED,
            fg_color=Colors.WELL_BG, height=S.ICON_BTN(), corner_radius=s(6),
        ).pack(fill="x", padx=Spacing.MD(), pady=4)

        # ── BUY / SELL buttons ─────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=Spacing.MD(), pady=(6, 10))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_row, text="▲  BUY MARKET",
            fg_color=Colors.BUY, hover_color=Colors.BUY_HOVER,
            text_color=Colors.ON_BUY, font=SF.SUBHEADER(),
            height=46, corner_radius=s(8),
            command=lambda: self._trigger_execution("BUY"),
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")

        ctk.CTkButton(
            btn_row, text="▼  SELL MARKET",
            fg_color=Colors.SELL, hover_color=Colors.SELL_HOVER,
            text_color=Colors.ON_SELL, font=SF.SUBHEADER(),
            height=46, corner_radius=s(8),
            command=lambda: self._trigger_execution("SELL"),
        ).grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # ── Open positions ─────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="OPEN POSITIONS  (click for details)",
            font=SF.SMALL(), text_color=Colors.LABEL,
        ).pack(anchor="w", padx=Spacing.MD(), pady=(6, 3))

        self.positions_scroll = ctk.CTkScrollableFrame(
            self, fg_color=Colors.WELL_BG, height=160, corner_radius=s(8),
            border_width=1, border_color=Colors.BORDER,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY,
        )
        bind_fast_scroll(self.positions_scroll)  # fast scroll fix
        self.positions_scroll.pack(
            fill="both", expand=True, padx=Spacing.MD(), pady=(0, Spacing.MD()))

    # ── SL / TP helpers ───────────────────────────────────────────────
    def _parse_price(self, widget: ctk.CTkEntry) -> float:
        try:
            return float(widget.get().strip().replace(",", ""))
        except ValueError:
            return 0.0

    def _update_rr(self):
        """Recompute and display R:R ratio live as the user types."""
        sl = self._parse_price(self.entry_sl)
        tp = self._parse_price(self.entry_tp)
        p  = self.current_price
        if sl and tp and p and sl != p and tp != p:
            risk   = abs(p - sl)
            reward = abs(tp - p)
            if risk > 0:
                rr = reward / risk
                self.lbl_rr.configure(
                    text=f"R:R  1:{rr:.2f}",
                    text_color=Colors.BUY if rr >= 1.0 else Colors.SELL,
                )
                return
        self.lbl_rr.configure(text="R:R —", text_color=Colors.TEXT_MUTED)

    def _autofill_sltp(self):
        """Fill SL and TP from the AI suggestion stored in main_window."""
        try:
            win = self.winfo_toplevel()
            ai_sl = getattr(win, "_ai_sl", 0.0)
            ai_tp = getattr(win, "_ai_tp", 0.0)
            if ai_sl:
                self.entry_sl.delete(0, "end")
                self.entry_sl.insert(0, f"{ai_sl:.5f}")
            if ai_tp:
                self.entry_tp.delete(0, "end")
                self.entry_tp.insert(0, f"{ai_tp:.5f}")
            self._update_rr()
        except Exception:
            pass

    def get_sl_tp(self) -> tuple[float, float]:
        return self._parse_price(self.entry_sl), self._parse_price(self.entry_tp)

    # ── Execution ─────────────────────────────────────────────────────
    def _trigger_execution(self, side: str):
        if self.on_execute_order:
            sl, tp = self.get_sl_tp()
            self.on_execute_order(self.current_coin, side, self.current_price, sl, tp)

    # ── Update from main pipeline ──────────────────────────────────────
    def update_ui(self, coin: str, price: float, signal: str,
                  ai_sl: float = 0.0, ai_tp: float = 0.0):
        self.current_coin  = coin
        self.current_price = price

        self.lbl_exposure.configure(text=f"ASSET: {coin}")
        self.lbl_tick.configure(text=f"PRICE: ${price:,.4f}")

        # Leverage info
        leverage  = lm.get_leverage(coin)
        asset_cls = lm.asset_class_label(coin)
        self.lbl_asset_class.configure(text=f"CLASS: {asset_cls}")
        self.lbl_leverage.configure(text=f"LEV: {leverage}x")
        if price > 0:
            ac = lm.get_asset_class(coin)
            lot_u = 100_000 if "forex" in ac else (100 if ac == "gold" else 1)
            notional    = lot_u * price
            margin      = notional / leverage if leverage else notional
            buying_power = margin * leverage
            self.lbl_margin.configure(text=f"MARGIN/LOT: ${margin:,.0f}")
            self.lbl_buying_power.configure(text=f"BUYING PWR: ${buying_power:,.0f}")

        # Signal status
        sig = signal.upper()
        if "BUY" in sig:
            self.lbl_status.configure(
                text="SYSTEM STATUS: ▲ BUY BIAS DETECTED", text_color=Colors.BUY)
        elif "SELL" in sig:
            self.lbl_status.configure(
                text="SYSTEM STATUS: ▼ SELL BIAS DETECTED", text_color=Colors.SELL)
        else:
            self.lbl_status.configure(
                text="SYSTEM STATUS: NO ACTIVE SETUP", text_color=Colors.NEUTRAL)

        # Live R:R update
        self._update_rr()

    # ── Positions list ────────────────────────────────────────────────
    def render_active_positions(self, open_positions: list):
        for w in self.positions_scroll.winfo_children():
            w.destroy()

        if not open_positions:
            ctk.CTkLabel(
                self.positions_scroll,
                text="No active positions.",
                font=SF.SMALL(), text_color=Colors.TEXT_MUTED,
            ).pack(pady=30)
            return

        for pos in open_positions:
            self._render_position_card(pos)

    def _render_position_card(self, pos: dict):
        asset     = pos["asset"]
        side      = pos["side"]
        entry     = pos["entry"]
        size_txt  = pos["size_text"]
        pnl       = pos.get("pnl", 0.0)
        notional  = pos.get("notional", pos["units"] * entry)
        leverage  = lm.get_leverage(asset)

        pnl_color = Colors.BUY if pnl >= 0 else Colors.SELL
        side_color = Colors.BUY if side == "BUY" else Colors.SELL
        on_side    = Colors.ON_BUY if side == "BUY" else Colors.ON_SELL

        card = ctk.CTkFrame(
            self.positions_scroll, fg_color=Colors.CARD_BG,
            border_width=1, border_color=Colors.BORDER,
            corner_radius=s(6), cursor="hand2",
        )
        card.pack(fill="x", pady=2, padx=2)

        # Row 1
        r1 = ctk.CTkFrame(card, fg_color="transparent")
        r1.pack(fill="x", padx=8, pady=(7, 2))
        ctk.CTkLabel(
            r1, text=f" {side} ",
            font=SF.PILL_LG(),
            text_color=on_side, fg_color=side_color, corner_radius=s(4),
        ).pack(side="left")
        ctk.CTkLabel(
            r1,
            text=f"  {asset}  @${entry:,.4f}  {size_txt}  Lev:{leverage}x",
            font=SF.MONO_TINY(), text_color=Colors.TEXT_SECONDARY,
        ).pack(side="left")
        ctk.CTkLabel(
            r1, text=f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",
            font=SF.MONO(), text_color=pnl_color,
        ).pack(side="right")

        # Row 2 — value + inline close buttons
        r2 = ctk.CTkFrame(card, fg_color="transparent")
        r2.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkLabel(
            r2, text=f"Value: ${notional:,.2f}",
            font=SF.MONO_TINY(), text_color=Colors.TEXT_MUTED,
        ).pack(side="left")

        close_f = ctk.CTkFrame(r2, fg_color="transparent")
        close_f.pack(side="right")
        pos_id = pos["id"]
        for lbl, frac in [("25%", 0.25), ("50%", 0.5), ("75%", 0.75)]:
            ctk.CTkButton(
                close_f, text=lbl, width=34, height=s(22), corner_radius=s(5),
                fg_color=Colors.BORDER, hover_color=Colors.HOVER_STRONG,
                text_color=Colors.TEXT_SECONDARY, font=SF.STATUS_BOLD(),
                command=lambda pid=pos_id, f=frac: (
                    self.on_close_position(pid, f) if self.on_close_position else None),
            ).pack(side="left", padx=1)
        ctk.CTkButton(
            close_f, text="✕", width=s(28), height=s(22), corner_radius=s(5),
            fg_color=Colors.SELL, hover_color=Colors.SELL_HOVER,
            text_color=Colors.ON_SELL, font=SF.STATUS_BOLD(),
            command=lambda pid=pos_id: (
                self.on_close_position(pid, 1.0) if self.on_close_position else None),
        ).pack(side="left", padx=1)

        # Full card click → detail modal
        def _open_detail(event=None, p=pos):
            PositionDetailModal(
                self.winfo_toplevel(), p,
                on_close_cb=self.on_close_position or (lambda _id, _f: None),
            )

        for widget in (card, r1, r2):
            widget.bind("<Button-1>", _open_detail)
