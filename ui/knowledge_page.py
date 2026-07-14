"""
ui/knowledge_page.py
=====================
Trading Knowledge Hub — Technical tips and education for Forex & Crypto.

Sections:
  • Forex Fundamentals
  • Crypto Fundamentals
  • Technical Analysis
  • Forex Strategies (explained)
  • Crypto Strategies (explained)
  • Risk Management
  • Trading Psychology
  • Quick Reference Glossary
"""
from __future__ import annotations
import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None


# ── Content Data ──────────────────────────────────────────────────────────────

FOREX_FUNDAMENTALS = [
    ("📌 What is Forex?",
     "The Foreign Exchange market is the world's largest financial market, trading over $7.5 "
     "trillion daily. It runs 24 hours from Sunday 22:00 UTC to Friday 22:00 UTC — weekends "
     "are closed. Currencies are quoted in pairs (e.g. EUR/USD): the first is the base, the "
     "second is the quote. A price of 1.0850 means 1 EUR buys 1.0850 USD."),

    ("📌 Pips & Spreads",
     "A pip is the smallest standard price move — 0.0001 for most pairs, 0.01 for JPY pairs. "
     "The spread is the difference between the bid and ask price and is your entry cost. "
     "Tighter spreads = lower trading cost. During the London/New York overlap (13:00–17:00 "
     "UTC), spreads are typically the tightest."),

    ("📌 Lot Sizes",
     "Standard lot = 100,000 units. Mini lot = 10,000 units. Micro lot = 1,000 units. "
     "Nano lot = 100 units. Retail traders usually trade mini or micro lots. Larger lots "
     "amplify both profit and loss."),

    ("📌 Leverage & Margin",
     "Leverage allows you to control large positions with small capital. 1:100 leverage means "
     "$1,000 controls a $100,000 position. Margin is the collateral your broker holds. "
     "Higher leverage = higher risk. Professionals often use 1:10 to 1:30. Never risk more "
     "than you can afford to lose."),

    ("📌 Market Sessions",
     "Sydney: 22:00–07:00 UTC (low volatility, AUD/NZD pairs). "
     "Tokyo: 00:00–09:00 UTC (JPY pairs, moderate volatility). "
     "London: 08:00–17:00 UTC (highest volume, EUR/GBP pairs). "
     "New York: 13:00–22:00 UTC (USD pairs, economic releases). "
     "The London/NY overlap (13:00–17:00 UTC) is the best window for high-probability trades."),

    ("📌 Economic Calendar",
     "Key events that move Forex markets: NFP (Non-Farm Payrolls, first Friday monthly), "
     "FOMC Rate Decisions, CPI/Inflation data, GDP reports, Central Bank speeches. "
     "Avoid holding trades through high-impact news unless you have specific news-trading "
     "strategies in place."),

    ("📌 Currency Correlations",
     "EUR/USD and GBP/USD are positively correlated (~0.80). EUR/USD and USD/CHF move "
     "inversely (~-0.90). AUD/USD and NZD/USD often move together. USD/JPY and equities "
     "(US30, SPX) often correlate in risk-on environments. Understanding correlations "
     "prevents over-exposure to the same directional risk."),
]

CRYPTO_FUNDAMENTALS = [
    ("₿ What is Crypto Trading?",
     "Cryptocurrency markets trade 24/7, 365 days a year — unlike Forex. Bitcoin (BTC) is "
     "the market leader; altcoins often follow its trend. Crypto is quoted against USDT "
     "(Tether) or BTC. High volatility creates large opportunities but also large risks. "
     "Always use stop losses."),

    ("₿ Market Cap & Liquidity",
     "Market cap = price × circulating supply. Large-cap coins (BTC, ETH) have deep "
     "liquidity and smaller spreads. Mid-cap coins have moderate liquidity. Small-cap "
     "('altcoins') are highly volatile and susceptible to manipulation. Stick to top-50 "
     "coins for safer trading."),

    ("₿ Bitcoin Dominance",
     "BTC Dominance (BTC.D) tracks BTC's share of the total crypto market cap. When BTC.D "
     "rises, altcoins typically underperform (capital flowing to BTC). When BTC.D falls, "
     "altcoins often rally (alt season). Monitoring BTC.D helps you time altcoin trades."),

    ("₿ Funding Rates (Perpetual Futures)",
     "In perpetual futures markets, funding rates balance longs and shorts. Positive "
     "funding = longs pay shorts (market is overleveraged long). Negative funding = shorts "
     "pay longs. Extreme funding rates often precede reversals. Use them as a contrarian "
     "sentiment indicator."),

    ("₿ On-Chain Metrics",
     "On-chain data reveals what large holders ('whales') are doing. Key metrics: "
     "Exchange Net Flow (coins moving to/from exchanges), Whale Wallet Activity, "
     "SOPR (Spent Output Profit Ratio), MVRV (Market Value to Realized Value). "
     "Rising exchange inflows often precede sell pressure."),

    ("₿ Halving Cycles",
     "Bitcoin halving occurs every ~4 years (~210,000 blocks), cutting miner rewards in half. "
     "Historically, BTC enters a bull market 6–18 months after a halving due to reduced "
     "supply issuance. Understanding where we are in the halving cycle helps with "
     "long-term positioning."),
]

TECHNICAL_TIPS = [
    ("📊 Support & Resistance",
     "Support = price level where buyers consistently step in. Resistance = level where "
     "sellers overpower buyers. Once broken, support becomes resistance and vice versa "
     "(role reversal). Round numbers (1.1000, 50,000) and previous swing highs/lows act "
     "as strong S/R. Always look at multiple timeframes."),

    ("📊 Trend Identification",
     "An uptrend = series of higher highs and higher lows. Downtrend = lower highs and "
     "lower lows. Range = price oscillating between defined levels. Use the 50 EMA and "
     "200 EMA as dynamic S/R and trend filters. Price above 200 EMA = bullish bias. "
     "Trade in the direction of the higher timeframe trend."),

    ("📊 RSI (Relative Strength Index)",
     "RSI measures momentum on a 0–100 scale. Above 70 = overbought. Below 30 = oversold. "
     "In strong trends, RSI can stay extreme for extended periods. RSI divergence is the "
     "most powerful signal: price makes a new high but RSI fails to — a bearish divergence "
     "signals weakening momentum. Best used on H4 and Daily charts."),

    ("📊 MACD (Moving Average Convergence Divergence)",
     "MACD = 12 EMA − 26 EMA, smoothed by a 9-period signal line. A bullish signal occurs "
     "when MACD crosses above its signal line. The histogram shows momentum strength. "
     "MACD divergence (price vs MACD) is a strong reversal warning. Use MACD to confirm "
     "trend entries, not as a standalone trigger."),

    ("📊 Bollinger Bands",
     "Bollinger Bands (20 SMA ± 2 standard deviations) show volatility. When bands "
     "squeeze (tighten), a breakout is imminent — this is the 'Bollinger Squeeze'. Price "
     "touching the outer band in a trend is not necessarily a reversal — it shows strength. "
     "The 'band walk' (price hugging the upper/lower band) signals a strong trend."),

    ("📊 Fibonacci Retracements",
     "Key Fibonacci levels: 23.6%, 38.2%, 50%, 61.8% (the 'golden ratio'), 78.6%. "
     "In an uptrend, price often retraces to 50–61.8% before resuming. The 61.8% level "
     "is the most commonly respected. Always draw Fibonacci from swing low to swing high "
     "(or reverse for downtrends). Combine with S/R levels for confluence."),

    ("📊 Volume Analysis",
     "Volume confirms price moves. A breakout on high volume is more reliable than one on "
     "low volume. Increasing volume in a trend confirms momentum. Decreasing volume in a "
     "trend signals exhaustion. Divergence between price and volume (price rising on "
     "falling volume) is a warning sign. In crypto, watch for volume spikes near "
     "key levels as whale activity."),

    ("📊 Candlestick Patterns",
     "Key reversal patterns: Doji (indecision), Hammer/Shooting Star (single candle "
     "reversal), Engulfing (two-candle reversal), Morning/Evening Star (three-candle). "
     "Key continuation patterns: Inside Bar, Marubozu (strong trend candle), Three "
     "White Soldiers / Three Black Crows. Always look for patterns at key S/R levels "
     "or after significant moves — not in the middle of nowhere."),
]

FOREX_STRATEGIES = [
    ("🎯 ICT Smart Money / SMC",
     "[Forex] Institutional Concepts Trading (ICT) is based on how banks and institutions "
     "move price. Key concepts: Order Blocks (OB) — the last candle before a strong impulse "
     "move; Fair Value Gaps (FVG) — imbalances in price that tend to fill; Breaker Blocks — "
     "a failed OB that flips; Liquidity Sweeps — price briefly taking out stop losses before "
     "reversing. Best used on H4/H1 charts for entry timing."),

    ("🎯 Liquidity Concepts",
     "[Forex] Price moves to collect liquidity — stop losses clustered above swing highs "
     "(buy-side liquidity) and below swing lows (sell-side liquidity). Smart money triggers "
     "these stops before reversing. Look for 'liquidity grabs' — a quick spike beyond a "
     "key level followed by immediate rejection. These are high-probability reversal signals."),

    ("🎯 Order Blocks",
     "[Forex] An order block is the last bearish candle before a bullish impulse (bullish OB) "
     "or the last bullish candle before a bearish impulse (bearish OB). Price often returns "
     "to these zones to fill remaining orders. Combine with FVGs and liquidity levels for "
     "high-confluence entries. OBs on higher timeframes (Daily/H4) carry more weight."),

    ("🎯 Break of Structure (BOS) & Change of Character (CHoCH)",
     "[Forex] BOS = confirmation that trend continues. CHoCH = first sign of trend reversal "
     "(a lower timeframe swing breaks against the higher timeframe trend). Use BOS for "
     "trend-following entries. Use CHoCH to anticipate and time reversals early. "
     "Always align with higher timeframe bias."),

    ("🎯 Scalping",
     "[Forex] Trading extremely short timeframes (M1–M15) for small profits (5–15 pips). "
     "Requires tight spreads, fast execution, and strict discipline. Best during the London "
     "open (08:00 UTC) and NY open (13:00 UTC) when volatility and volume are highest. "
     "Typical R:R is 1:1 to 1:1.5. Risk 0.25–0.5% per trade maximum."),

    ("🎯 Swing Trading",
     "[Forex] Holding positions from days to weeks, targeting larger moves (50–300+ pips). "
     "Focus on Daily and H4 charts for trend and H1/H4 for entry. Key advantage: less "
     "screen time, wider stops avoid noise. Risk 0.5–1% per trade. Works best in trending "
     "markets; avoid during high-impact news or ranging conditions."),
]

CRYPTO_STRATEGIES = [
    ("₿ Trend + EMA Cross",
     "[Crypto] Use the 21 EMA and 55 EMA crossover on H4 or Daily charts. When 21 EMA "
     "crosses above 55 EMA, go long. When it crosses below, consider shorts or exit longs. "
     "Best in trending BTC markets. During alt season, apply to individual coins for "
     "strong trend entries. Avoid in ranging markets where EMA signals whipsaw."),

    ("₿ RSI Divergence",
     "[Crypto] Look for price making higher highs while RSI makes lower highs (bearish "
     "divergence) or price making lower lows while RSI makes higher lows (bullish divergence). "
     "Most powerful on H4 and Daily charts at key S/R levels. RSI divergence in crypto "
     "often precedes 20–40% reversals. Combine with volume analysis for confirmation."),

    ("₿ MACD Momentum",
     "[Crypto] In strong trending markets, enter when MACD histogram flips positive (bullish) "
     "or negative (bearish) after a pullback. The MACD zero-line cross is a slower but more "
     "reliable signal for swing traders. Best suited for BTC, ETH, and top-10 coins where "
     "trends are more sustained. Avoid during sideways/choppy conditions."),

    ("₿ Bollinger Squeeze (Crypto)",
     "[Crypto] Crypto volatility cycles between compression (squeeze) and expansion (breakout). "
     "When Bollinger Bands narrow significantly, set alerts for the breakout. Enter on the "
     "breakout candle close above/below the band with a stop inside the squeeze zone. "
     "Targets: 1x–3x the squeeze range. Very effective on BTC and ETH 4H charts."),

    ("₿ Volume Profile",
     "[Crypto] Volume Profile shows which price levels had the most trading volume. "
     "High-volume nodes (HVN) act as strong S/R. Low-volume nodes (LVN) cause price to "
     "move quickly through them. The Point of Control (POC) — highest volume price — is a "
     "magnet for price. Use Volume Profile on Binance or TradingView for BTC/ETH to "
     "identify key levels before they're hit."),

    ("₿ On-Chain Breakout",
     "[Crypto] Combine technical breakouts with on-chain confirmation. Before going long on "
     "a breakout: check if exchange outflows are increasing (coins leaving exchanges = "
     "accumulation). Check MVRV: if below 1, historically a buy zone. Check funding rates: "
     "negative funding + price at support = high-probability long. On-chain data reduces "
     "false breakout risk significantly."),

    ("₿ Wyckoff Accumulation",
     "[Crypto] The Wyckoff Method identifies market phases: Accumulation (smart money "
     "buying quietly), Markup (price rises publicly), Distribution (smart money selling), "
     "Markdown (price falls). Key signals: Selling Climax (SC), Automatic Rally (AR), "
     "Spring (final shakeout before markup). BTC often follows clear Wyckoff patterns "
     "on Weekly charts. Identifying the Spring before markup can yield 3x–10x moves."),

    ("₿ DCA Swing",
     "[Crypto] Dollar-Cost Averaging into swing positions. Instead of one entry, split your "
     "position into 3 parts: entry at key support, add at -5%, add at -10% (the 'ladder in'). "
     "Place one stop below the lowest entry. Take partial profits at resistance levels. "
     "This reduces the impact of volatility and false breaks. Best for BTC and ETH at "
     "major support zones identified on Weekly charts."),
]

RISK_MANAGEMENT = [
    ("🛡️ The 1% Rule",
     "Never risk more than 1–2% of your total account on a single trade. This means if you "
     "have a $10,000 account, your maximum loss per trade is $100–$200. This rule ensures "
     "you can survive 50+ losing trades in a row without blowing your account. Professional "
     "traders often risk 0.25–0.5% per trade."),

    ("🛡️ Risk:Reward Ratio",
     "Always aim for a minimum 1:2 risk-to-reward ratio — risk $1 to make $2. "
     "A 1:3 RR means you only need to be right 33% of the time to be profitable. "
     "Strategies with lower win rates (40–50%) can still be highly profitable with good RR. "
     "Track your average RR over time as a key performance metric."),

    ("🛡️ Stop Loss Placement",
     "Place stops at logical market structure levels, not arbitrary pip amounts. "
     "For longs: stop below the most recent swing low or order block. "
     "For shorts: stop above the most recent swing high or order block. "
     "Add a small buffer (5–10 pips for forex, 0.5–1% for crypto) beyond the level to "
     "account for spreads and wicks."),

    ("🛡️ Position Sizing",
     "Position size = (Account Risk $) ÷ (Stop Loss in pips × pip value). "
     "Example: $100 risk, 20-pip stop, $1/pip value = 5 mini lots. "
     "Always calculate position size BEFORE entering a trade. Never increase position size "
     "because you 'feel confident' about a trade. Consistent sizing is the foundation "
     "of long-term profitability."),

    ("🛡️ Correlation Risk",
     "Trading EUR/USD and GBP/USD simultaneously is NOT diversification — they move almost "
     "identically. If both go against you, you've doubled your risk. Limit correlated pairs "
     "to one position at a time, or reduce size on each. Crypto pairs (BTC, ETH, altcoins) "
     "are also highly correlated during risk-off events."),
]

PSYCHOLOGY_TIPS = [
    ("🧠 Discipline Over Impulse",
     "The most profitable traders follow their plan with robotic consistency. Impulsive "
     "decisions (revenge trading after a loss, FOMO entries, moving stop losses) are the "
     "#1 account killer. Before entering any trade, write down your entry, stop, target, "
     "and reason. If you can't, don't trade."),

    ("🧠 Dealing with Losses",
     "Losses are part of trading — even the best traders lose 40–50% of their trades. "
     "A losing trade following your plan is a GOOD trade. A winning trade from a random "
     "impulse is a BAD trade. Never judge a trade by its outcome alone — judge it by "
     "whether you followed your process. Keep a trade journal to review decisions objectively."),

    ("🧠 FOMO (Fear of Missing Out)",
     "FOMO causes traders to enter late, chase price, and accept poor risk:reward setups. "
     "The market always provides new opportunities. If you missed a move, the next "
     "retracement will give you an entry. Write this on your monitor: 'Another bus "
     "is always coming.' Missing a trade is far better than a bad entry."),

    ("🧠 Overtrading",
     "More trades ≠ more profit. Most profitable traders make 2–5 high-quality trades "
     "per week. Set a maximum daily trade limit (e.g. 3 trades). If you hit your daily "
     "loss limit (-2% account), stop trading for the day. Overtrading is caused by boredom, "
     "greed, or revenge — all of which are account destroyers."),
]

GLOSSARY = [
    ("Pip",           "Smallest price unit. 0.0001 for most FX pairs; 0.01 for JPY pairs."),
    ("Spread",        "Difference between bid/ask price. Your entry cost."),
    ("Lot",           "Standard lot = 100,000 units. Mini = 10,000. Micro = 1,000."),
    ("Leverage",      "Controlling a larger position with smaller capital. 1:100 = $1 controls $100."),
    ("Margin",        "Collateral required to open a leveraged position."),
    ("Long",          "Buying, expecting price to rise."),
    ("Short",         "Selling, expecting price to fall."),
    ("Stop Loss",     "Order to close a trade at a defined loss level."),
    ("Take Profit",   "Order to close a trade at a defined profit level."),
    ("Risk:Reward",   "Ratio of potential loss to potential gain. Aim for 1:2+."),
    ("Order Block",   "[SMC] Last candle before a strong impulse move. Acts as future S/R."),
    ("Fair Value Gap","[SMC] Price imbalance/inefficiency that often gets filled."),
    ("Liquidity",     "[SMC] Clusters of stop-loss orders above/below swing points."),
    ("BOS",           "Break of Structure — confirms trend continuation."),
    ("CHoCH",         "Change of Character — first sign of trend reversal."),
    ("USDT",          "[Crypto] Tether — a stablecoin pegged to $1. Most crypto is quoted vs USDT."),
    ("MACD",          "Moving Average Convergence Divergence — momentum oscillator."),
    ("RSI",           "Relative Strength Index — 0–100 momentum indicator."),
    ("EMA",           "Exponential Moving Average — weighted toward recent prices."),
    ("Bollinger Bands","Price envelope: 20 SMA ± 2 standard deviations. Measures volatility."),
    ("Funding Rate",  "[Crypto] Fee paid between longs/shorts in perpetual futures."),
    ("Wyckoff",       "[Crypto] Market phase model: Accumulation, Markup, Distribution, Markdown."),
    ("BTC Dominance", "[Crypto] BTC's % share of total crypto market cap."),
    ("DCA",           "Dollar-Cost Averaging — buying at multiple price levels to average in."),
    ("On-Chain",      "[Crypto] Data directly from the blockchain (wallet movements, volumes)."),
]


# ── UI Helpers ────────────────────────────────────────────────────────────────

def _section_header(parent, text: str, color: str = None):
    color = color or Colors.TEXT
    ctk.CTkLabel(
        parent, text=text,
        font=SF.SUBHEADER(), text_color=color,
        anchor="w",
    ).pack(anchor="w", pady=(18, 6))


def _card(parent, title: str, body: str, title_color: str = None):
    title_color = title_color or Colors.PRIMARY
    frame = ctk.CTkFrame(
        parent, fg_color=Colors.CARD_BG,
        border_width=1, border_color=Colors.BORDER, corner_radius=s(8),
    )
    frame.pack(fill="x", pady=4)

    inner = ctk.CTkFrame(frame, fg_color="transparent")
    inner.pack(fill="x", padx=14, pady=10)

    ctk.CTkLabel(
        inner, text=title,
        font=SF.NAV_BOLD(), text_color=title_color,
        anchor="w", justify="left",
    ).pack(anchor="w", pady=(0, 4))

    ctk.CTkLabel(
        inner, text=body,
        font=SF.PILL(), text_color=Colors.TEXT_SECONDARY,
        wraplength=s(900), justify="left", anchor="w",
    ).pack(anchor="w")


def _glossary_row(parent, term: str, definition: str, idx: int):
    bg = Colors.CARD_BG if idx % 2 == 0 else Colors.WELL_BG
    row = ctk.CTkFrame(parent, fg_color=bg)
    row.pack(fill="x")
    row.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(
        row, text=term,
        font=SF.MONO_SM(), text_color=Colors.NEUTRAL,
        width=s(150), anchor="w",
    ).grid(row=0, column=0, sticky="w", padx=(12, 0), pady=6)

    ctk.CTkLabel(
        row, text=definition,
        font=SF.PILL(), text_color=Colors.TEXT_SECONDARY,
        anchor="w", justify="left", wraplength=s(780),
    ).grid(row=0, column=1, sticky="w", padx=10, pady=6)


# ── Main Page ─────────────────────────────────────────────────────────────────

class KnowledgePage(ctk.CTkFrame):
    """Trading Knowledge Hub — Forex & Crypto technical education."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=Colors.APP_BG, corner_radius=0, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(),
                 pady=(Spacing.LG(), Spacing.MD()))

        ctk.CTkLabel(
            hdr, text="📚  KNOWLEDGE & TIPS",
            font=SF.TITLE(), text_color=Colors.TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            hdr, text="Forex & Crypto — Technical Education Hub",
            font=SF.NAV(), text_color=Colors.TEXT_MUTED,
        ).pack(side="left", padx=16)

        # ── Tab bar ───────────────────────────────────────────────────
        tab_bar = ctk.CTkFrame(self, fg_color=Colors.SIDEBAR_BG,
                                border_width=0, corner_radius=0)
        tab_bar.grid(row=1, column=0, sticky="ew")

        self._tabs = {}
        self._active_tab = None
        self._pages: dict[str, ctk.CTkScrollableFrame] = {}

        tab_items = [
            ("forex",       "💱 Forex Basics",    Colors.NEUTRAL),
            ("crypto",      "₿ Crypto Basics",    "#F7931A"),
            ("technical",   "📊 Technical",        Colors.BUY),
            ("strategies",  "🎯 Strategies",       Colors.PRIMARY),
            ("risk",        "🛡️ Risk Mgmt",        Colors.SELL),
            ("psychology",  "🧠 Psychology",       "#9B59B6"),
            ("glossary",    "📖 Glossary",         Colors.TEXT_SECONDARY),
        ]

        for key, label, color in tab_items:
            btn = ctk.CTkButton(
                tab_bar, text=label,
                font=SF.PILL_LG(),
                fg_color="transparent", hover_color=Colors.HOVER,
                text_color=Colors.TEXT_MUTED, border_width=0,
                corner_radius=0, height=S.ROW_H(), width=s(130),
                command=lambda k=key, c=color: self._show_tab(k, c),
            )
            btn.pack(side="left")
            self._tabs[key] = (btn, color)

        # ── Page host ─────────────────────────────────────────────────
        self._page_host = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self._page_host.grid(row=2, column=0, sticky="nsew",
                              padx=Spacing.LG(), pady=(0, Spacing.LG()))
        self._page_host.grid_columnconfigure(0, weight=1)
        self._page_host.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Build all tabs
        self._build_tab("forex",      FOREX_FUNDAMENTALS,  "#F5A623")
        self._build_tab("crypto",     CRYPTO_FUNDAMENTALS, "#F7931A")
        self._build_tab("technical",  TECHNICAL_TIPS,      Colors.BUY)
        self._build_strategies_tab()
        self._build_tab("risk",       RISK_MANAGEMENT,     Colors.SELL)
        self._build_tab("psychology", PSYCHOLOGY_TIPS,     "#9B59B6")
        self._build_glossary_tab()

        # Show first tab
        self._show_tab("forex", "#F5A623")

    def _make_scroll(self, key: str) -> ctk.CTkScrollableFrame:
        sf = ctk.CTkScrollableFrame(
            self._page_host, fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.PRIMARY,
        )
        sf.grid(row=0, column=0, sticky="nsew")
        sf.grid_columnconfigure(0, weight=1)
        bind_fast_scroll(sf)
        sf.grid_remove()
        self._pages[key] = sf
        return sf

    def _build_tab(self, key: str, items: list, title_color: str):
        sf = self._make_scroll(key)
        for title, body in items:
            _card(sf, title, body, title_color)

    def _build_strategies_tab(self):
        sf = self._make_scroll("strategies")

        _section_header(sf, "📈 Forex Strategies", Colors.NEUTRAL)
        for title, body in FOREX_STRATEGIES:
            _card(sf, title, body, Colors.NEUTRAL)

        _section_header(sf, "₿ Crypto Strategies", "#F7931A")
        for title, body in CRYPTO_STRATEGIES:
            _card(sf, title, body, "#F7931A")

    def _build_glossary_tab(self):
        sf = self._make_scroll("glossary")
        tbl = ctk.CTkFrame(
            sf, fg_color=Colors.CARD_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(8),
        )
        tbl.pack(fill="x", pady=4)

        # Header
        hrow = ctk.CTkFrame(tbl, fg_color=Colors.SIDEBAR_BG, corner_radius=0)
        hrow.pack(fill="x")
        hrow.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hrow, text="Term", font=SF.STATUS_BOLD(),
                     text_color=Colors.LABEL, width=s(150), anchor="w",
                     ).grid(row=0, column=0, sticky="w", padx=12, pady=7)
        ctk.CTkLabel(hrow, text="Definition", font=SF.STATUS_BOLD(),
                     text_color=Colors.LABEL, anchor="w",
                     ).grid(row=0, column=1, sticky="w", padx=10, pady=7)

        for idx, (term, definition) in enumerate(GLOSSARY):
            _glossary_row(tbl, term, definition, idx)

    def _show_tab(self, key: str, color: str):
        # Hide all
        for pg in self._pages.values():
            pg.grid_remove()
        # Deactivate all buttons
        for k, (btn, c) in self._tabs.items():
            btn.configure(fg_color="transparent", text_color=Colors.TEXT_MUTED)
        # Show selected
        if key in self._pages:
            self._pages[key].grid()
        # Activate button
        if key in self._tabs:
            self._tabs[key][0].configure(fg_color=Colors.HOVER, text_color=color)
        self._active_tab = key
