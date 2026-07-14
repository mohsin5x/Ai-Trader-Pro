"""
=========================================================
 AI Trader Pro - Top Bar
=========================================================
"""

import customtkinter as ctk

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts
from ui.components import Panel


class TopBar(Panel):

    def __init__(self, master):

        super().__init__(master)

        self.pack_propagate(False)

        # Main Container
        self.container = ctk.CTkFrame(
            self,
            fg_color="transparent"
        )

        self.container.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=10
        )

        # -------------------------------
        # Balance
        # -------------------------------

        self.balance = self.create_card(
            "Balance",
            "$10,000.00"
        )

        # -------------------------------
        # Equity
        # -------------------------------

        self.equity = self.create_card(
            "Equity",
            "$10,000.00"
        )

        # -------------------------------
        # Profit / Loss
        # -------------------------------

        self.pnl = self.create_card(
            "Today's P/L",
            "+0.00%"
        )

        # -------------------------------
        # Risk
        # -------------------------------

        self.risk = self.create_card(
            "Risk",
            "1%"
        )

        # -------------------------------
        # Server
        # -------------------------------

        self.server = self.create_card(
            "Server",
            "ONLINE"
        )


    def create_card(self, title, value):

        frame = ctk.CTkFrame(
            self.container,
            fg_color=Colors.PANEL_BG,
            corner_radius=s(10),
            border_width=1,
            border_color=Colors.BORDER
        )

        frame.pack(
            side="left",
            padx=6,
            fill="both",
            expand=True
        )

        ctk.CTkLabel(
            frame,
            text=title,
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(pady=(10, 2))

        value_label = ctk.CTkLabel(
            frame,
            text=value,
            font=SF.HEADER(),
            text_color=Colors.TEXT
        )

        value_label.pack(pady=(0, 10))

        return value_label