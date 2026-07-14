import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing


class CoinSelector(ctk.CTkFrame):
    """
    Compact asset + timeframe selector.
    Two dropdowns side-by-side inside a subtle card — no section titles.
    Sits above the nav buttons so nav buttons are always stable in view.
    """

    def __init__(self, parent, on_coin_change, on_timeframe_change):
        super().__init__(parent, fg_color="transparent")
        self.on_coin_change = on_coin_change
        self.on_timeframe_change = on_timeframe_change

        self.grid_columnconfigure(0, weight=3)   # asset menu wider
        self.grid_columnconfigure(1, weight=1)   # timeframe narrower

        _menu_kw = dict(
            fg_color=Colors.INPUT_BG,
            button_color=Colors.BORDER_LIGHT,
            button_hover_color=Colors.HOVER_STRONG,
            text_color=Colors.TEXT,
            dropdown_fg_color=Colors.CARD_BG,
            dropdown_hover_color=Colors.HOVER,
            dropdown_text_color=Colors.TEXT,
            font=SF.NAV(),
            corner_radius=s(6),
            height=S.NAV_BTN_H(),
        )

        self.coin_menu = ctk.CTkOptionMenu(
            self,
            values=[
                # Forex Majors
                "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "USD/CHF", "NZD/USD",
                # Forex Crosses
                "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/AUD", "EUR/CAD",
                "AUD/JPY", "GBP/AUD", "GBP/CAD", "CAD/JPY", "NZD/JPY", "CHF/JPY",
                # Metals
                "XAU/USD", "XAG/USD",
                # Crypto
                "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE",
                "AVAX", "MATIC", "DOT", "LINK", "LTC", "UNI", "ATOM",
                # Indices
                "US30", "NAS100", "SPX500",
            ],
            command=self._coin_selection_intercept,
            **_menu_kw,
        )
        self.coin_menu.set("EUR/USD")
        self.coin_menu.grid(row=0, column=0, sticky="ew", padx=(4, 2), pady=4)

        self.timeframe_menu = ctk.CTkOptionMenu(
            self,
            values=["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            command=self._timeframe_selection_intercept,
            **_menu_kw,
        )
        self.timeframe_menu.set("1h")
        self.timeframe_menu.grid(row=0, column=1, sticky="ew", padx=(2, 4), pady=4)

    def _coin_selection_intercept(self, choice: str):
        self.on_coin_change(choice)

    def _timeframe_selection_intercept(self, choice: str):
        self.on_timeframe_change(choice)