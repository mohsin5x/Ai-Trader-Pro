import time
import customtkinter as ctk
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from ui.modal_overlay import BaseDialog

# ----------------------------------------------------------------------
# Beginner glossary -- plain-English definitions for the technical terms
# that show up in Signal.reasons (see services/signal_engine.py and
# services/smc_analysis.py for where each term is actually produced).
# ----------------------------------------------------------------------
GLOSSARY = [
    ("Trend (EMA20 / EMA50 / SMA200)",
     "Three moving averages of price. When the faster ones (EMA20, EMA50) sit above the "
     "slower one (SMA200) in the right order, price is trending up (and vice versa for down). "
     "The engine only signals when this higher-timeframe trend agrees with the trade direction."),
    ("ADX",
     "Measures how strong a trend is (not its direction) -- higher ADX means the trend is "
     "more reliable to follow, lower ADX means the market is choppy/directionless."),
    ("Order Block",
     "The last candle (or small cluster) before a strong, decisive move away from it -- "
     "thought to mark where large players entered. Price often returns to \"retest\" this "
     "zone before continuing in the original direction."),
    ("Fair Value Gap (FVG)",
     "A 3-candle imbalance where price moved so fast it left a gap between candle 1's and "
     "candle 3's wicks. Price often comes back to \"fill\" this gap before continuing."),
    ("Liquidity Sweep",
     "Price wicks beyond a recent high/low (triggering stop-losses resting there) and then "
     "closes back inside the range -- often a sign of a reversal, not a breakout."),
    ("Break of Structure (BOS)",
     "Price closes beyond a previous swing high/low, confirming the trend is continuing in "
     "that direction."),
    ("Change of Character (CHoCH)",
     "The first break of structure in the *opposite* direction of the prior trend -- an early "
     "warning that a reversal may be starting."),
    ("RSI (Relative Strength Index)",
     "A 0-100 momentum gauge. Above ~70 is often called \"overbought\", below ~30 \"oversold\". "
     "The engine looks for RSI confirming a move without already being overextended."),
    ("Volume vs 20-period average",
     "Compares current trading volume to its recent average -- a move on above-average volume "
     "is considered more convincing than the same move on quiet volume."),
    ("R:R (Risk:Reward)",
     "How much you stand to gain versus how much you're risking. R:R 1:2 means your take-profit "
     "target is twice as far away as your stop-loss."),
    ("Confidence / Strength",
     "How many independent confirmations (trend + setup + entry signals) agreed with each other. "
     "This is NOT a win-rate guarantee -- it just means more of the engine's checks lined up."),
]


class GlossaryModal(BaseDialog):
    """Plain-English reference for the ICT/SMC and indicator terms used
    throughout the Signal Engine's confirmation reasons -- aimed at
    someone learning to read these signals, not just execute them."""

    def __init__(self, parent):
        super().__init__(parent,
                         title="Signal Glossary — What These Terms Mean",
                         size=(620, 600))
        self.configure(fg_color=Colors.APP_BG)

        ctk.CTkLabel(self, text="SIGNAL GLOSSARY", font=SF.HEADER(), text_color=Colors.TEXT).pack(
            anchor="w", padx=20, pady=(20, 4))
        ctk.CTkLabel(self, text="Plain-English explanations for the terms you'll see in every signal's analysis.",
                     font=SF.SMALL(), text_color=Colors.TEXT_MUTED, wraplength=s(580), justify="left").pack(
            anchor="w", padx=20, pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8))
        bind_fast_scroll(scroll)  # fast scroll fix
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        for term, definition in GLOSSARY:
            card = ctk.CTkFrame(scroll, fg_color=Colors.CARD_BG, border_width=1,
                                 border_color=Colors.BORDER, corner_radius=s(8))
            card.pack(fill="x", padx=4, pady=5)
            ctk.CTkLabel(card, text=term, font=SF.SUBHEADER(), text_color=Colors.BUY,
                         wraplength=s(560), justify="left").pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkLabel(card, text=definition, font=SF.SMALL(), text_color=Colors.TEXT_SECONDARY,
                         wraplength=s(560), justify="left").pack(anchor="w", padx=12, pady=(0, 10))


class SignalDetailModal(BaseDialog):
    """Full breakdown for one scanner signal -- every confirmation reason,
    all three take-profit levels, the trade classification, a beginner
    glossary, and a copyable MT5-mobile trade ticket sized off the
    user's real account balance/risk setting."""

    def __init__(self, parent, signal, get_account_context=None):
        super().__init__(parent,
                         title=f"AI Signal Engine — {signal.symbol} Full Analysis",
                         size=(680, 820), resizable=(False, False))
        self.configure(fg_color=Colors.APP_BG)

        self.signal = signal
        self._get_account_context = get_account_context

        container = ctk.CTkFrame(self, fg_color=Colors.SIDEBAR_BG, border_width=1,
                                  border_color=Colors.BORDER, corner_radius=s(12))
        container.pack(fill="both", expand=True, padx=15, pady=15)

        dir_color = Colors.BUY if signal.direction == "BUY" else Colors.SELL

        header = ctk.CTkFrame(container, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(header, text=f"{signal.symbol}", font=SF.HEADER(), text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(header, text="? Glossary", width=s(90), height=s(26), corner_radius=s(6),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.TEXT,
                      font=SF.PILL_LG(), command=lambda: GlossaryModal(self)).pack(side="right", padx=(0, 8))
        ctk.CTkLabel(header, text=f" {signal.direction} ", font=SF.MONO(),
                     text_color=(Colors.ON_BUY if signal.direction == "BUY" else Colors.ON_SELL),
                     fg_color=dir_color, corner_radius=s(6)).pack(side="right")

        ctk.CTkLabel(container, text=f"{signal.trade_type} · {signal.setup_timeframe} setup · {signal.trend} trend · {signal.session}",
                     font=SF.SMALL(), text_color=Colors.LABEL).pack(anchor="w", padx=15, pady=(0, 10))

        # --- Levels grid ---
        grid = ctk.CTkFrame(container, fg_color=Colors.CARD_BG, border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        grid.pack(fill="x", padx=15, pady=5)
        for i in range(6):
            grid.grid_columnconfigure(i, weight=1)

        cells = [
            ("ENTRY", f"${signal.entry_price:,.4f}"),
            ("CURRENT", f"${signal.current_price:,.4f}"),
            ("STOP LOSS", f"${signal.stop_loss:,.4f}"),
            ("TP1", f"${signal.take_profit_1:,.4f}"),
            ("TP2", f"${signal.take_profit_2:,.4f}"),
            ("TP3", f"${signal.take_profit_3:,.4f}"),
        ]
        for i, (label, value) in enumerate(cells):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=0, column=i, pady=12, sticky="nsew")
            ctk.CTkLabel(cell, text=label, font=SF.STATUS_BOLD(), text_color=Colors.LABEL).pack()
            ctk.CTkLabel(cell, text=value, font=SF.MONO(), text_color=Colors.TEXT).pack()

        stats_row = ctk.CTkFrame(container, fg_color="transparent")
        stats_row.pack(fill="x", padx=15, pady=(6, 4))
        ctk.CTkLabel(stats_row, text=f"Confidence: {signal.confidence}%  ·  Strength: {signal.strength}  ·  R:R 1:{signal.risk_reward:.2f}",
                     font=SF.MONO(), text_color=Colors.ORANGE).pack(side="left")

        src_row = ctk.CTkFrame(container, fg_color="transparent")
        src_row.pack(fill="x", padx=15, pady=(0, 10))
        created = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(signal.created_at))
        updated = time.strftime('%H:%M:%S', time.localtime(signal.updated_at))
        ctk.CTkLabel(src_row, text=f"Data source: {signal.data_source}   ·   Created: {created}   ·   Updated: {updated}",
                     font=SF.TINY(), text_color=Colors.TEXT_MUTED).pack(anchor="w")

        # --- MT5 mobile trade ticket ---
        ticket_box = ctk.CTkFrame(container, fg_color=Colors.WELL_BG, border_width=1,
                                   border_color=Colors.BORDER, corner_radius=s(8))
        ticket_box.pack(fill="x", padx=15, pady=(4, 8))
        ticket_header = ctk.CTkFrame(ticket_box, fg_color="transparent")
        ticket_header.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(ticket_header, text="MT5 MOBILE TRADE TICKET", font=SF.PILL_LG(),
                     text_color=Colors.LABEL).pack(side="left")
        self.lbl_copy_status = ctk.CTkLabel(ticket_header, text="", font=SF.TINY(), text_color=Colors.BUY)
        self.lbl_copy_status.pack(side="right")

        self.lbl_ticket_size = ctk.CTkLabel(ticket_box, text="Suggested size: --", font=SF.MONO_SM(),
                                             text_color=Colors.TEXT, justify="left", anchor="w")
        self.lbl_ticket_size.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkButton(ticket_box, text="Copy Trade Ticket", height=s(28), corner_radius=s(6),
                      fg_color=Colors.BUY, text_color=Colors.ON_BUY, hover_color=Colors.HOVER_STRONG,
                      font=SF.NAV_BOLD(), command=self._copy_trade_ticket).pack(
            fill="x", padx=10, pady=(0, 10))

        self._compute_and_show_size()

        # --- Reasons ---
        ctk.CTkLabel(container, text="COMPLETE ANALYSIS — CONFIRMATIONS", font=SF.PILL_LG(),
                     text_color=Colors.LABEL).pack(anchor="w", padx=15, pady=(10, 4))

        reasons_box = ctk.CTkScrollableFrame(container, fg_color=Colors.WELL_BG, border_width=1,
                                              border_color=Colors.BORDER, corner_radius=s(8), height=220)
        bind_fast_scroll(reasons_box)  # fast scroll fix
        reasons_box.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        if signal.reasons:
            for reason in signal.reasons:
                ctk.CTkLabel(reasons_box, text=f"•  {reason}", font=SF.NORMAL(), text_color=Colors.TEXT_SECONDARY,
                             justify="left", wraplength=s(590), anchor="w").pack(fill="x", padx=8, pady=3)
        else:
            ctk.CTkLabel(reasons_box, text="No confirmation detail recorded.", font=SF.NORMAL(),
                         text_color=Colors.TEXT_MUTED).pack(padx=8, pady=8)

        ctk.CTkLabel(container, text=signal.news_risk_note, font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                     wraplength=s(610), justify="left").pack(anchor="w", padx=15, pady=(0, 4))
        ctk.CTkLabel(container, text="Confidence reflects how many independent confirmations agreed -- not a guaranteed win rate or financial advice.",
                     font=SF.TINY(), text_color=Colors.TEXT_MUTED, wraplength=s(610), justify="left").pack(anchor="w", padx=15, pady=(0, 12))

    # ------------------------------------------------------------------


    def _suggested_size(self):
        """Mirrors ui/main_window.py's SUGGESTED SIZE formula exactly,
        using the user's REAL account balance/risk% (not the paper
        trading balance) -- this ticket is meant to be copied into their
        real MT5 mobile app."""
        if not self._get_account_context:
            return None, "Set your real account balance in Settings to see a suggested size here."

        balance, risk_pct = self._get_account_context()
        price_delta = abs(self.signal.entry_price - self.signal.stop_loss)
        if price_delta <= 0 or balance <= 0:
            return None, "Suggested size unavailable for this signal."

        risk_cash = balance * risk_pct
        raw_units = risk_cash / price_delta
        if "/" in self.signal.symbol and "XAU" not in self.signal.symbol:
            lots = raw_units / 100000.0
            return raw_units, f"{lots:.2f} LOTS  (risking ${risk_cash:,.2f} = {risk_pct*100:.1f}% of ${balance:,.2f})"
        return raw_units, f"{raw_units:.2f} UNITS  (risking ${risk_cash:,.2f} = {risk_pct*100:.1f}% of ${balance:,.2f})"

    def _compute_and_show_size(self):
        _, label = self._suggested_size()
        self.lbl_ticket_size.configure(text=f"Suggested size: {label}")

    def _copy_trade_ticket(self):
        _, size_label = self._suggested_size()
        s = self.signal
        ticket = (
            f"{s.symbol}  {s.direction}\n"
            f"Entry: {s.entry_price:.5f}\n"
            f"Stop Loss: {s.stop_loss:.5f}\n"
            f"Take Profit 1: {s.take_profit_1:.5f}\n"
            f"Take Profit 2: {s.take_profit_2:.5f}\n"
            f"Take Profit 3: {s.take_profit_3:.5f}\n"
            f"Size: {size_label}\n"
            f"R:R 1:{s.risk_reward:.2f}  ·  Confidence {s.confidence}%\n"
            f"-- Paste these levels manually into your MT5 mobile app. "
            f"This app places no real orders."
        )
        self.clipboard_clear()
        self.clipboard_append(ticket)
        self.lbl_copy_status.configure(text="Copied!")
        self.after(2500, lambda: self.lbl_copy_status.configure(text=""))


class _SignalCard(ctk.CTkFrame):
    def __init__(self, parent, signal, on_open, on_apply_algo=None):
        super().__init__(parent, fg_color=Colors.WELL_BG, border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        dir_color = Colors.BUY if signal.direction == "BUY" else Colors.SELL
        on_dir_color = Colors.ON_BUY if signal.direction == "BUY" else Colors.ON_SELL

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))

        ctk.CTkLabel(top, text=signal.symbol, font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")
        ctk.CTkLabel(top, text=f" {signal.direction} ", font=SF.MONO_SM(), text_color=on_dir_color,
                     fg_color=dir_color, corner_radius=s(5)).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(top, text=f"{signal.trade_type}", font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                     fg_color=Colors.CARD_BG, corner_radius=s(5), padx=6, pady=2).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(top, text=f"{signal.confidence}% · {signal.strength}", font=SF.MONO_SM(),
                     text_color=Colors.ORANGE).pack(side="right")

        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(
            mid,
            text=(f"Entry ${signal.entry_price:,.4f}   SL ${signal.stop_loss:,.4f}   "
                  f"TP1 ${signal.take_profit_1:,.4f}   TP2 ${signal.take_profit_2:,.4f}   TP3 ${signal.take_profit_3:,.4f}   "
                  f"R:R 1:{signal.risk_reward:.2f}"),
            font=SF.MONO_SM(), text_color=Colors.TEXT_SECONDARY,
            wraplength=s(860), anchor="w", justify="left",
        ).pack(anchor="w", fill="x")

        # AI Explanation preview — first 2 reasons
        reasons = signal.reasons or []
        if reasons:
            exp_frame = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, corner_radius=s(6))
            exp_frame.pack(fill="x", padx=10, pady=(2, 4))
            ctk.CTkLabel(exp_frame, text="🧠 Why:", font=SF.STATUS_BOLD(),
                         text_color=Colors.LABEL).pack(anchor="w", padx=8, pady=(5, 0))
            for reason in reasons[:2]:
                ctk.CTkLabel(exp_frame, text=f"• {reason[:110]}{'…' if len(reason) > 110 else ''}",
                             font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                             justify="left", wraplength=s(840), anchor="w").pack(anchor="w", padx=8, pady=1)
            if len(reasons) > 2:
                ctk.CTkLabel(exp_frame, text=f"  + {len(reasons) - 2} more confirmation(s) — click Full Analysis",
                             font=SF.STATUS(), text_color=Colors.TEXT_MUTED,
                             anchor="w").pack(anchor="w", padx=8, pady=(0, 5))
            else:
                ctk.CTkFrame(exp_frame, height=4, fg_color="transparent").pack()

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=10, pady=(2, 8))
        ctk.CTkLabel(
            bottom,
            text=f"{signal.trend} trend · {signal.setup_timeframe} setup · {signal.session} · {signal.data_source}",
            font=SF.TINY(), text_color=Colors.TEXT_MUTED,
        ).pack(side="left")

        btn = ctk.CTkButton(bottom, text="Full Analysis", width=s(110), height=S.ICON_BTN(), corner_radius=s(6),
                             fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.BUY,
                             font=SF.PILL_LG(), command=lambda: on_open(signal))
        btn.pack(side="right")

        if on_apply_algo:
            ctk.CTkButton(bottom, text="→ Apply to Algo", width=S.BTN_W_MD(), height=S.ICON_BTN(), corner_radius=s(6),
                          fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
                          text_color=Colors.ON_BUY, font=SF.STATUS_BOLD(),
                          command=lambda s=signal: on_apply_algo(s)).pack(side="right", padx=(0, 4))


class SignalEnginePanel(ctk.CTkFrame):
    """Live list of active AI Signal Engine setups across every scanned
    market. Purely a display of whatever services/market_scanner.py has
    found -- shows nothing (not a fake placeholder signal) when the
    scanner hasn't found a qualifying setup yet."""

    def __init__(self, parent, get_account_context=None):
        super().__init__(parent, fg_color=Colors.CARD_BG, border_width=1, border_color=Colors.BORDER, corner_radius=s(10))
        self._get_account_context = get_account_context

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 4))
        ctk.CTkLabel(header, text="AI SIGNAL ENGINE — MARKET SCANNER", font=SF.SMALL(), text_color=Colors.LABEL).pack(side="left")
        ctk.CTkButton(header, text="? Glossary", width=s(90), height=s(22), corner_radius=s(6),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.TEXT,
                      font=SF.STATUS_BOLD(), command=lambda: GlossaryModal(self.winfo_toplevel())).pack(side="right", padx=(0, 8))
        self.lbl_status = ctk.CTkLabel(header, text="Scanning markets...", font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self.lbl_status.pack(side="right")

        self.list_container = ctk.CTkScrollableFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(8), height=260)
        bind_fast_scroll(self.list_container)  # fast scroll fix
        self.list_container.pack(fill="both", expand=True, padx=Spacing.MD(), pady=(0, Spacing.MD()))

        self._empty_label = ctk.CTkLabel(
            self.list_container,
            text="No high-probability setups right now. The engine only signals when multiple\ntimeframes and confirmations agree — it will not force a trade in poor conditions.",
            font=SF.SMALL(), text_color=Colors.TEXT_MUTED, justify="left",
        )
        self._empty_label.pack(padx=10, pady=20, anchor="w")

    @staticmethod
    def _forex_market_open() -> bool:
        from datetime import datetime, timezone as _tz
        now = datetime.now(_tz.utc)
        wd, h = now.weekday(), now.hour
        if wd == 5: return False                    # Saturday
        if wd == 6 and h < 22: return False         # Sunday before Sydney
        return True

    def update_signals(self, signals: list, status_text: str = ""):
        for child in self.list_container.winfo_children():
            child.destroy()

        if status_text:
            self.lbl_status.configure(text=status_text)

        market_open = self._forex_market_open()

        # Filter out forex signals generated while markets are closed
        if not market_open:
            signals = [s for s in signals
                       if not ('/' in s.symbol or s.symbol in ('US30','NAS100','SPX500'))]

        if not signals:
            msg = ("No high-probability setups right now. The engine only signals when multiple\n"
                   "timeframes and confirmations agree — it will not force a trade in poor conditions.")
            if not market_open:
                msg = ("⛔  Forex markets are CLOSED (Weekend).\n\n"
                       "Forex, indices and precious metal signals are paused until Sunday 22:00 UTC\n"
                       "when the Sydney session opens.\n\n"
                       "Crypto signals (BTC, ETH, etc.) continue 24/7.")
            self._empty_label = ctk.CTkLabel(
                self.list_container, text=msg,
                font=SF.SMALL(), text_color=Colors.TEXT_MUTED, justify="left",
            )
            self._empty_label.pack(padx=10, pady=20, anchor="w")
            return

        for signal in signals:
            card = _SignalCard(self.list_container, signal, on_open=self._open_detail)
            card.pack(fill="x", padx=4, pady=4)

    def _open_detail(self, signal):
        SignalDetailModal(self.winfo_toplevel(), signal, get_account_context=self._get_account_context)
