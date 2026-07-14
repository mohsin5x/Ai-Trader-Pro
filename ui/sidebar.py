"""
=========================================================
 AI Trader Pro - Sidebar
=========================================================
"""

import customtkinter as ctk

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts
from ui.components import Panel, SectionTitle, StyledComboBox


class Sidebar(Panel):

    def __init__(self, master):

        super().__init__(master, title="MARKET CONTROL")

        self.configure(width=s(340))
        
        # Configure the main column to stretch horizontally 
        # to replicate the 'fill="x"' behavior from pack
        self.grid_columnconfigure(0, weight=1)

        # ==========================================
        # APP LOGO
        # ==========================================

        self.logo = ctk.CTkLabel(
            self,
            text="AI TRADER PRO",
            font=SF.TITLE(),
            text_color=Colors.PRIMARY
        )
        self.logo.grid(row=0, column=0, pady=(5, 0), padx=10, sticky="n")

        self.version = ctk.CTkLabel(
            self,
            text="Professional Edition",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        )
        self.version.grid(row=1, column=0, pady=(0, 20), sticky="n")

        # ==========================================
        # MARKET TYPE
        # ==========================================

        SectionTitle(self, text="Market").grid(
            row=2,
            column=0,
            sticky="w",
            padx=15
        )

        self.market_box = StyledComboBox(
            self,
            values=[
                "Forex",
                "Crypto",
                "Stocks",
                "Indices"
            ]
        )

        self.market_box.set("Forex")
        self.market_box.grid(
            row=3,
            column=0,
            sticky="ew",
            padx=15,
            pady=(5, 15)
        )

        # ==========================================
        # ASSET
        # ==========================================

        SectionTitle(self, text="Trading Asset").grid(
            row=4,
            column=0,
            sticky="w",
            padx=15
        )

        self.asset_box = StyledComboBox(
            self,
            values=[
                "EUR/USD",
                "GBP/USD",
                "USD/JPY",
                "XAU/USD",
                "BTC/USDT",
                "ETH/USDT"
            ]
        )

        self.asset_box.set("EUR/USD")
        self.asset_box.grid(
            row=5,
            column=0,
            sticky="ew",
            padx=15,
            pady=(5, 15)
        )

        # ==========================================
        # TIMEFRAME
        # ==========================================

        SectionTitle(self, text="Operational Horizon").grid(
            row=6,
            column=0,
            sticky="w",
            padx=15
        )

        self.timeframe_box = StyledComboBox(
            self,
            values=[
                "1 Minute",
                "5 Minutes",
                "15 Minutes",
                "30 Minutes",
                "1 Hour",
                "4 Hours",
                "Daily"
            ]
        )

        self.timeframe_box.set("15 Minutes")
        self.timeframe_box.grid(
            row=7,
            column=0,
            sticky="ew",
            padx=15,
            pady=(5, 15)
        )

        # ==========================================
        # AI STRATEGY
        # ==========================================

        SectionTitle(self, text="AI Strategy").grid(
            row=8,
            column=0,
            sticky="w",
            padx=15
        )

        self.strategy_box = StyledComboBox(
            self,
            values=[
                # Forex Strategies
                "ICT Smart Money",
                "Scalping AI",
                "Swing AI",
                "Trend Following",
                "EMA + RSI",
                # Crypto Strategies
                "Crypto: Trend + EMA Cross",
                "Crypto: RSI Divergence",
                "Crypto: MACD Momentum",
                "Crypto: Bollinger Squeeze",
                "Crypto: Volume Profile",
                "Crypto: On-Chain Breakout",
                "Crypto: Wyckoff Accumulation",
                "Crypto: DCA Swing",
            ]
        )

        self.strategy_box.set("ICT Smart Money")
        self.strategy_box.grid(
            row=9,
            column=0,
            sticky="ew",
            padx=15,
            pady=(5, 20)
        )
        
        # ==========================================
        # WATCHLIST
        # ==========================================

        self.watchlist_title = ctk.CTkLabel(
            self,
            text="INSTITUTIONAL WATCHLIST",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        )
        self.watchlist_title.grid(
            row=10,
            column=0,
            sticky="w",
            padx=15,
            pady=(10, 8)
        )

        self.watchlist_frame = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            corner_radius=s(10),
            border_width=1,
            border_color=Colors.BORDER
        )
        self.watchlist_frame.grid(
            row=11,
            column=0,
            sticky="ew",
            padx=15,
            pady=(0, 15)
        )

        self.assets = [
            ("EUR/USD", "1.17420", "▲"),
            ("GBP/USD", "1.36210", "▲"),
            ("USD/JPY", "145.61", "▼"),
            ("BTC/USDT", "108,540", "▲"),
            ("ETH/USDT", "2,680", "▲"),
            ("XAU/USD", "3368.20", "▼")
        ]

        self.price_labels = {}

        # Internal container management rules allow sub-frames to handle layout independently
        for symbol, price, direction in self.assets:

            row_frame = ctk.CTkFrame(
                self.watchlist_frame,
                fg_color="transparent"
            )
            row_frame.pack(fill="x", padx=8, pady=5)

            symbol_label = ctk.CTkLabel(
                row_frame,
                text=symbol,
                font=SF.NORMAL(),
                width=s(90),
                anchor="w",
                text_color=Colors.TEXT
            )
            symbol_label.pack(side="left")

            price_label = ctk.CTkLabel(
                row_frame,
                text=price,
                font=SF.MONO(),
                text_color=Colors.TEXT
            )
            price_label.pack(side="left", padx=5)

            arrow = Colors.GREEN if direction == "▲" else Colors.RED

            trend = ctk.CTkLabel(
                row_frame,
                text=direction,
                font=SF.SUBHEADER(),
                text_color=arrow
            )
            trend.pack(side="right")

            self.price_labels[symbol] = price_label

        # ==========================================
        # MARKET STATUS
        # ==========================================

        self.status_frame = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            corner_radius=s(10),
            border_width=1,
            border_color=Colors.BORDER
        )
        self.status_frame.grid(
            row=12,
            column=0,
            sticky="ew",
            padx=15,
            pady=(0, 15)
        )

        ctk.CTkLabel(
            self.status_frame,
            text="MARKET STATUS",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.market_status = ctk.CTkLabel(
            self.status_frame,
            text="🟢 MARKET OPEN",
            font=SF.NORMAL(),
            text_color=Colors.GREEN
        )
        self.market_status.pack(anchor="w", padx=10)

        self.server_status = ctk.CTkLabel(
            self.status_frame,
            text="Server : Connected",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        )
        self.server_status.pack(anchor="w", padx=10)

        self.ai_status = ctk.CTkLabel(
            self.status_frame,
            text="AI Engine : Online",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        )
        self.ai_status.pack(anchor="w", padx=10)

        self.feed_status = ctk.CTkLabel(
            self.status_frame,
            text="Market Feed : Live",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        )
        self.feed_status.pack(anchor="w", padx=10, pady=(0, 10))

        # ==========================================
        # ACCOUNT SUMMARY
        # ==========================================

        self.account_frame = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            corner_radius=s(10),
            border_width=1,
            border_color=Colors.BORDER
        )
        self.account_frame.grid(
            row=13,
            column=0,
            sticky="ew",
            padx=15,
            pady=(0, 15)
        )

        ctk.CTkLabel(
            self.account_frame,
            text="ACCOUNT SUMMARY",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.balance_label = ctk.CTkLabel(
            self.account_frame,
            text="Balance : $10,000.00",
            font=SF.NORMAL(),
            text_color=Colors.TEXT
        )
        self.balance_label.pack(anchor="w", padx=10)

        self.equity_label = ctk.CTkLabel(
            self.account_frame,
            text="Equity : $10,000.00",
            font=SF.NORMAL(),
            text_color=Colors.TEXT
        )
        self.equity_label.pack(anchor="w", padx=10)

        self.pnl_label = ctk.CTkLabel(
            self.account_frame,
            text="Today's P/L : +0.00%",
            font=SF.NORMAL(),
            text_color=Colors.GREEN
        )
        self.pnl_label.pack(anchor="w", padx=10, pady=(0, 10))

        # ==========================================
        # AI ENGINE
        # ==========================================

        self.ai_frame = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            corner_radius=s(10),
            border_width=1,
            border_color=Colors.BORDER
        )
        self.ai_frame.grid(
            row=14,
            column=0,
            sticky="ew",
            padx=15,
            pady=(0, 15)
        )

        ctk.CTkLabel(
            self.ai_frame,
            text="AI ENGINE",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.ai_progress = ctk.CTkProgressBar(
            self.ai_frame,
            progress_color=Colors.PRIMARY
        )
        self.ai_progress.pack(
            fill="x",
            padx=10,
            pady=(0, 5)
        )
        self.ai_progress.set(0.82)

        self.ai_label = ctk.CTkLabel(
            self.ai_frame,
            text="Confidence : 82%",
            font=SF.NORMAL(),
            text_color=Colors.TEXT
        )
        self.ai_label.pack(pady=(0, 10))

        # ==========================================
        # NEWS
        # ==========================================

        self.news_frame = ctk.CTkFrame(
            self,
            fg_color=Colors.PANEL_BG,
            corner_radius=s(10),
            border_width=1,
            border_color=Colors.BORDER
        )
        self.news_frame.grid(
            row=15,
            column=0,
            sticky="ew",
            padx=15,
            pady=(0, 15)
        )

        ctk.CTkLabel(
            self.news_frame,
            text="MARKET NEWS",
            font=SF.SUBHEADER(),
            text_color=Colors.TEXT
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.news_label = ctk.CTkLabel(
            self.news_frame,
            text="No news available...",
            wraplength=s(280),
            justify="left",
            font=SF.SMALL(),
            text_color=Colors.TEXT_SECONDARY
        )
        self.news_label.pack(
            padx=10,
            pady=(0, 10),
            anchor="w"
        )