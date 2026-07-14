"""
=========================================================
 AI Trader Pro - Strategy Panel
=========================================================
"""

import customtkinter as ctk

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts
from ui.components import Panel


class StrategyPanel(Panel):

    def __init__(self, master):

        super().__init__(master, title="AI STRATEGY BLUEPRINT")

        self.grid_columnconfigure((0, 1), weight=1)

        self.create_box("Signal", "BUY", 0, 0)
        self.create_box("Confidence", "82%", 0, 1)

        self.create_box("Entry", "--", 1, 0)
        self.create_box("Stop Loss", "--", 1, 1)

        self.create_box("Take Profit", "--", 2, 0)
        self.create_box("Risk / Reward", "1 : 2", 2, 1)

        ctk.CTkLabel(
            self,
            text="AI Reason",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        ).grid(row=3, column=0, columnspan=2,
               sticky="w", padx=15, pady=(20,5))

        self.reason = ctk.CTkTextbox(
            self,
            height=120,
            fg_color=Colors.PANEL_BG,
            border_color=Colors.BORDER,
            border_width=1
        )

        self.reason.insert(
            "1.0",
            "Waiting for market analysis..."
        )

        self.reason.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="nsew",
            padx=15,
            pady=(0,15)
        )

    def create_box(self, title, value, row, column):

        frame = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            corner_radius=s(10),
            border_width=1,
            border_color=Colors.BORDER
        )

        frame.grid(
            row=row,
            column=column,
            padx=10,
            pady=8,
            sticky="nsew"
        )

        ctk.CTkLabel(
            frame,
            text=title,
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(pady=(8,2))

        value_label = ctk.CTkLabel(
            frame,
            text=value,
            font=SF.HEADER(),
            text_color=Colors.TEXT
        )

        value_label.pack(pady=(0,8))