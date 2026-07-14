"""
=========================================================
 AI Trader Pro
 Professional Order Panel
=========================================================

Institutional Trade Execution Panel

Future Compatible:
- Broker Execution API
- Binance
- Bybit
- OANDA
- AI Engine
- Risk Manager
"""

import customtkinter as ctk
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts
from services.notification_center import nc
from services import provider_settings as _ps


class OrderPanel(ctk.CTkScrollableFrame):
    """
    Professional Trade Execution Panel

    UI only.
    No broker logic belongs here.
    """

    def __init__(self, parent):

        super().__init__(
            parent,
            fg_color=Colors.CARD_BG,
            border_width=1,
            border_color=Colors.BORDER,
            corner_radius=s(12)
        )

        self.grid_columnconfigure(0, weight=1)

        self.build_ui()

    def build_ui(self):

        # =====================================================
        # HEADER
        # =====================================================

        ctk.CTkLabel(
            self,
            text="TRADE EXECUTION",
            font=SF.HEADER(),
            text_color=Colors.TEXT
        ).pack(
            anchor="w",
            padx=20,
            pady=(18, 15)
        )

        # =====================================================
        # ACCOUNT SUMMARY
        # =====================================================

        account = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            border_width=1,
            border_color=Colors.BORDER,
            corner_radius=s(10)
        )

        account.pack(
            fill="x",
            padx=20,
            pady=(0, 15)
        )

        ctk.CTkLabel(
            account,
            text="ACCOUNT SUMMARY",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        ).pack(
            anchor="w",
            padx=12,
            pady=(10, 6)
        )

        _real_bal = 10_000.0
        try:
            _real_bal = _ps.load_account_balance()
        except Exception:
            pass
        self.balance_label = ctk.CTkLabel(
            account,
            text=f"Balance : ${_real_bal:,.2f}",
            font=SF.NORMAL(),
            text_color=Colors.TEXT
        )

        self.balance_label.pack(anchor="w", padx=12)

        self.equity_label = ctk.CTkLabel(
            account,
            text="Equity : $10,000.00",
            font=SF.NORMAL(),
            text_color=Colors.TEXT
        )

        self.equity_label.pack(anchor="w", padx=12)

        self.margin_label = ctk.CTkLabel(
            account,
            text="Free Margin : $10,000.00",
            font=SF.NORMAL(),
            text_color=Colors.TEXT_SECONDARY
        )

        self.margin_label.pack(anchor="w", padx=12)

        self.leverage_info = ctk.CTkLabel(
            account,
            text="Leverage : 1:100",
            font=SF.NORMAL(),
            text_color=Colors.TEXT_SECONDARY
        )

        self.leverage_info.pack(
            anchor="w",
            padx=12,
            pady=(0, 10)
        )

        # =====================================================
        # POSITION SIZE
        # =====================================================

        ctk.CTkLabel(
            self,
            text="Position Size",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(
            anchor="w",
            padx=20
        )

        self.position_entry = ctk.CTkEntry(
            self,
            placeholder_text="0.10",
            height=S.ROW_H()
        )

        self.position_entry.pack(
            fill="x",
            padx=20,
            pady=(5, 12)
        )

        # =====================================================
        # LEVERAGE
        # =====================================================

        ctk.CTkLabel(
            self,
            text="Leverage",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(
            anchor="w",
            padx=20
        )

        self.leverage = ctk.CTkOptionMenu(
            self,
            values=[
                "1x",
                "2x",
                "5x",
                "10x",
                "20x",
                "50x",
                "100x"
            ]
        )

        self.leverage.set("10x")

        self.leverage.pack(
            fill="x",
            padx=20,
            pady=(5, 12)
        )
        # =====================================================
        # RISK PERCENTAGE
        # =====================================================

        ctk.CTkLabel(
            self,
            text="Risk Per Trade",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(
            anchor="w",
            padx=20
        )

        self.risk_menu = ctk.CTkOptionMenu(
            self,
            values=[
                "0.5%",
                "1%",
                "2%",
                "3%",
                "5%"
            ]
        )

        self.risk_menu.set("1%")

        self.risk_menu.pack(
            fill="x",
            padx=20,
            pady=(5, 12)
        )

        # =====================================================
        # STOP LOSS
        # =====================================================

        ctk.CTkLabel(
            self,
            text="Stop Loss",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(
            anchor="w",
            padx=20
        )

        self.sl_entry = ctk.CTkEntry(
            self,
            placeholder_text="Auto / Manual"
        )

        self.sl_entry.pack(
            fill="x",
            padx=20,
            pady=(5, 12)
        )

        # =====================================================
        # TAKE PROFIT
        # =====================================================

        ctk.CTkLabel(
            self,
            text="Take Profit",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(
            anchor="w",
            padx=20
        )

        self.tp_entry = ctk.CTkEntry(
            self,
            placeholder_text="Auto / Manual"
        )

        self.tp_entry.pack(
            fill="x",
            padx=20,
            pady=(5, 12)
        )

        # =====================================================
        # ORDER TYPE
        # =====================================================

        ctk.CTkLabel(
            self,
            text="Order Type",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(
            anchor="w",
            padx=20
        )

        self.order_type = ctk.CTkOptionMenu(
            self,
            values=[
                "Market",
                "Limit",
                "Stop",
                "Stop Limit"
            ]
        )

        self.order_type.set("Market")

        self.order_type.pack(
            fill="x",
            padx=20,
            pady=(5, 15)
        )

        # =====================================================
        # EXECUTION SUMMARY
        # =====================================================

        summary = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            border_width=1,
            border_color=Colors.BORDER,
            corner_radius=s(10)
        )

        summary.pack(
            fill="x",
            padx=20,
            pady=(0, 15)
        )

        ctk.CTkLabel(
            summary,
            text="EXECUTION SUMMARY",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        ).pack(
            anchor="w",
            padx=12,
            pady=(10, 8)
        )

        self.summary_entry = ctk.CTkLabel(
            summary,
            text="Entry : --",
            font=SF.NORMAL(),
            text_color=Colors.TEXT
        )

        self.summary_entry.pack(anchor="w", padx=12)

        self.summary_sl = ctk.CTkLabel(
            summary,
            text="Stop Loss : --",
            font=SF.NORMAL(),
            text_color=Colors.SELL
        )

        self.summary_sl.pack(anchor="w", padx=12)

        self.summary_tp = ctk.CTkLabel(
            summary,
            text="Take Profit : --",
            font=SF.NORMAL(),
            text_color=Colors.BUY
        )

        self.summary_tp.pack(anchor="w", padx=12)

        self.summary_rr = ctk.CTkLabel(
            summary,
            text="Risk / Reward : --",
            font=SF.NORMAL(),
            text_color=Colors.TEXT_SECONDARY
        )

        self.summary_rr.pack(
            anchor="w",
            padx=12,
            pady=(0, 10)
        )
        # =====================================================
        # BUY BUTTON
        # =====================================================

        self.buy_btn = ctk.CTkButton(
            self,
            text="BUY MARKET",
            fg_color=Colors.BUY,
            hover_color="#00B96B",
            text_color="white",
            font=SF.SUBHEADER(),
            height=50,
            corner_radius=s(10),
            command=self.place_buy_order,
        )

        self.buy_btn.pack(
            fill="x",
            padx=20,
            pady=(5, 8)
        )

        # =====================================================
        # SELL BUTTON
        # =====================================================

        self.sell_btn = ctk.CTkButton(
            self,
            text="SELL MARKET",
            fg_color=Colors.SELL,
            hover_color="#D84343",
            text_color="white",
            font=SF.SUBHEADER(),
            height=50,
            corner_radius=s(10),
            command=self.place_sell_order,
        )

        self.sell_btn.pack(
            fill="x",
            padx=20,
            pady=(0, 15)
        )

        # =====================================================
        # POSITION STATUS
        # =====================================================

        status = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            border_width=1,
            border_color=Colors.BORDER,
            corner_radius=s(10)
        )

        status.pack(
            fill="x",
            padx=20,
            pady=(0, 15)
        )

        ctk.CTkLabel(
            status,
            text="POSITION STATUS",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        ).pack(
            anchor="w",
            padx=12,
            pady=(10, 6)
        )

        self.status_label = ctk.CTkLabel(
            status,
            text="No Open Position",
            font=SF.NORMAL(),
            text_color=Colors.TEXT_SECONDARY
        )

        self.status_label.pack(
            anchor="w",
            padx=12
        )

        self.pnl_label = ctk.CTkLabel(
            status,
            text="Floating P/L : $0.00",
            font=SF.NORMAL(),
            text_color=Colors.TEXT_SECONDARY
        )

        self.pnl_label.pack(
            anchor="w",
            padx=12
        )

        self.position_type = ctk.CTkLabel(
            status,
            text="Position : ---",
            font=SF.NORMAL(),
            text_color=Colors.TEXT_SECONDARY
        )

        self.position_type.pack(
            anchor="w",
            padx=12,
            pady=(0, 10)
        )

        # =====================================================
        # QUICK ACTIONS
        # =====================================================

        quick = ctk.CTkFrame(
            self,
            fg_color="transparent"
        )

        quick.pack(
            fill="x",
            padx=20,
            pady=(0, 15)
        )

        self.close_btn = ctk.CTkButton(
            quick,
            text="Close Position",
            fg_color=Colors.ORANGE,
            hover_color="#D98200",
            height=s(40)
        )

        self.close_btn.pack(
            side="left",
            expand=True,
            fill="x",
            padx=(0, 5)
        )

        self.emergency_btn = ctk.CTkButton(
            quick,
            text="Emergency Close",
            fg_color=Colors.RED,
            hover_color="#C62828",
            height=s(40)
        )

        self.emergency_btn.pack(
            side="left",
            expand=True,
            fill="x",
            padx=(5, 0)
        )

        # =====================================================
        # AUTO TRADING
        # =====================================================

        self.auto_trade = ctk.CTkSwitch(
            self,
            text="Enable AI Auto Trading"
        )

        self.auto_trade.pack(
            anchor="w",
            padx=20,
            pady=(0, 20)
        )
    # =====================================================
    # UPDATE ACCOUNT INFORMATION
    # =====================================================

    def update_account(
        self,
        balance,
        equity,
        margin,
        leverage
    ):
        """Update account summary."""

        self.balance_label.configure(
            text=f"Balance : ${balance:,.2f}"
        )

        self.equity_label.configure(
            text=f"Equity : ${equity:,.2f}"
        )

        self.margin_label.configure(
            text=f"Free Margin : ${margin:,.2f}"
        )

        self.leverage_info.configure(
            text=f"Leverage : {leverage}"
        )

    # =====================================================
    # UPDATE EXECUTION SUMMARY
    # =====================================================

    def update_execution_summary(
        self,
        entry,
        sl,
        tp,
        rr
    ):
        """Update trade summary."""

        self.summary_entry.configure(
            text=f"Entry : {entry}"
        )

        self.summary_sl.configure(
            text=f"Stop Loss : {sl}"
        )

        self.summary_tp.configure(
            text=f"Take Profit : {tp}"
        )

        self.summary_rr.configure(
            text=f"Risk / Reward : {rr}"
        )

    # =====================================================
    # UPDATE POSITION STATUS
    # =====================================================

    def update_position_status(
        self,
        status="No Open Position",
        pnl=0.0,
        position="---"
    ):
        """Update position information."""

        self.status_label.configure(
            text=status
        )

        if pnl > 0:

            color = Colors.BUY

        elif pnl < 0:

            color = Colors.SELL

        else:

            color = Colors.TEXT_SECONDARY

        self.pnl_label.configure(
            text=f"Floating P/L : ${pnl:,.2f}",
            text_color=color
        )

        self.position_type.configure(
            text=f"Position : {position}"
        )

    # =====================================================
    # GET ORDER VALUES
    # =====================================================

    def get_order_values(self):
        """
        Return current order values.

        Used later by:
        - Broker Execution API
        - Binance
        - OANDA
        - Bybit
        """

        return {

            "position_size":
                self.position_entry.get(),

            "risk":
                self.risk_menu.get(),

            "leverage":
                self.leverage.get(),

            "stop_loss":
                self.sl_entry.get(),

            "take_profit":
                self.tp_entry.get(),

            "order_type":
                self.order_type.get(),

            "auto_trade":
                self.auto_trade.get()
        }

    # =====================================================
    # RESET PANEL
    # =====================================================

    def clear_inputs(self):
        """Clear all input fields."""

        self.position_entry.delete(0, "end")

        self.sl_entry.delete(0, "end")

        self.tp_entry.delete(0, "end")

        self.position_entry.insert(0, "0.10")

        self.risk_menu.set("1%")

        self.leverage.set("10x")

        self.order_type.set("Market")

    # =====================================================
    # FUTURE PLACEHOLDERS
    # =====================================================

    def place_buy_order(self):
        """Simulated BUY — shows confirmation feedback. Real broker execution is not yet implemented."""
        size = self.position_entry.get().strip() or "0.10"
        sl   = self.sl_entry.get().strip() or "—"
        tp   = self.tp_entry.get().strip() or "—"
        msg  = f"Simulated BUY | Size: {size} | SL: {sl} | TP: {tp}"
        nc.push("success", "📗 BUY Order Submitted (Paper)", msg, level="success")
        self._show_inline_feedback("BUY order submitted (Paper Mode)", Colors.BUY)

    def place_sell_order(self):
        """Simulated SELL — shows confirmation feedback. Real broker execution is not yet implemented."""
        size = self.position_entry.get().strip() or "0.10"
        sl   = self.sl_entry.get().strip() or "—"
        tp   = self.tp_entry.get().strip() or "—"
        msg  = f"Simulated SELL | Size: {size} | SL: {sl} | TP: {tp}"
        nc.push("success", "📕 SELL Order Submitted (Paper)", msg, level="success")
        self._show_inline_feedback("SELL order submitted (Paper Mode)", Colors.SELL)

    def _show_inline_feedback(self, text: str, color: str):
        """Display a brief inline confirmation label that fades after 3 seconds."""
        if hasattr(self, "_feedback_lbl") and self._feedback_lbl.winfo_exists():
            self._feedback_lbl.destroy()
        self._feedback_lbl = ctk.CTkLabel(
            self,
            text=f"✔  {text}",
            font=SF.STATUS_BOLD(),
            text_color=color,
            fg_color=Colors.WELL_BG,
            corner_radius=s(6),
        )
        self._feedback_lbl.pack(fill="x", padx=20, pady=(0, 6))
        self.after(3000, lambda: self._feedback_lbl.destroy() if self._feedback_lbl.winfo_exists() else None)

    def close_position(self):
        """
        Placeholder for closing an open position.
        """
        pass

    def emergency_close(self):
        """
        Placeholder for emergency close.
        """
        pass