"""
=========================================================
 AI Trader Pro - Trade Journal Panel
=========================================================
Displays running performance stats (win rate, net P/L,
trade count) plus a scrollable log of recently closed
trades, backed by services/history_service.py.
"""

import customtkinter as ctk
from ui.components import bind_fast_scroll
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing


class TradeJournalPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(
            master, fg_color=Colors.CARD_BG, corner_radius=s(10),
            border_width=1, border_color=Colors.BORDER, **kwargs
        )

        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 6))

        ctk.CTkLabel(
            header_row, text="TRADE JOURNAL",
            font=SF.SUBHEADER(), text_color=Colors.TEXT
        ).pack(side="left")

        self.lbl_summary = ctk.CTkLabel(
            header_row, text="0 trades  •  0.0% win rate  •  $0.00 net",
            font=SF.MONO(), text_color=Colors.TEXT_SECONDARY
        )
        self.lbl_summary.pack(side="right")

        self.rows_container = ctk.CTkScrollableFrame(
            self, fg_color=Colors.WELL_BG, corner_radius=s(8), height=150,
            scrollbar_button_color=Colors.BORDER, scrollbar_button_hover_color=Colors.BUY,
        )

        bind_fast_scroll(self.rows_container)
        self.rows_container.pack(fill="both", expand=True, padx=Spacing.MD(), pady=(0, Spacing.MD()))

        self.lbl_empty = ctk.CTkLabel(
            self.rows_container, text="No closed trades yet. Executed trades will appear here.",
            font=SF.SMALL(), text_color=Colors.TEXT_MUTED
        )
        self.lbl_empty.pack(pady=20)

    def render(self, trades: list, summary: dict):
        """Redraws the summary line and the recent-trades log."""
        pnl_color = Colors.BUY if summary["net_pnl"] >= 0 else Colors.SELL
        self.lbl_summary.configure(
            text=f"{summary['total']} trades  •  {summary['win_rate']:.1f}% win rate  •  ${summary['net_pnl']:,.2f} net",
            text_color=pnl_color
        )

        for child in self.rows_container.winfo_children():
            child.destroy()

        if not trades:
            self.lbl_empty = ctk.CTkLabel(
                self.rows_container, text="No closed trades yet. Executed trades will appear here.",
                font=SF.SMALL(), text_color=Colors.TEXT_MUTED
            )
            self.lbl_empty.pack(pady=20)
            return

        for trade in trades:
            self._create_row(trade)

    def _create_row(self, trade: dict):
        pnl = float(trade.get("pnl", 0.0))
        row_color = Colors.BUY if pnl > 0 else (Colors.SELL if pnl < 0 else Colors.TEXT_SECONDARY)
        side_color = Colors.BUY if trade.get("side") == "BUY" else Colors.SELL

        row = ctk.CTkFrame(self.rows_container, fg_color=Colors.CARD_BG, corner_radius=s(6))
        row.pack(fill="x", pady=2, padx=2)
        for i in range(5):
            row.grid_columnconfigure(i, weight=1)

        ctk.CTkLabel(row, text=trade.get("timestamp", ""), font=SF.MONO_TINY(), text_color=Colors.TEXT_MUTED) \
            .grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ctk.CTkLabel(row, text=trade.get("asset", ""), font=SF.NAV_BOLD(), text_color=Colors.TEXT) \
            .grid(row=0, column=1, sticky="w", padx=8)
        ctk.CTkLabel(row, text=trade.get("side", ""), font=SF.NAV_BOLD(), text_color=side_color) \
            .grid(row=0, column=2, sticky="w", padx=8)
        ctk.CTkLabel(row, text=trade.get("strategy", ""), font=SF.PILL(), text_color=Colors.TEXT_SECONDARY) \
            .grid(row=0, column=3, sticky="w", padx=8)
        ctk.CTkLabel(row, text=f"${pnl:,.2f}", font=SF.MONO_SM(), text_color=row_color) \
            .grid(row=0, column=4, sticky="e", padx=8)
