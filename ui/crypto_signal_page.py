"""
ui/crypto_signal_page.py
==========================
Crypto Signal Generator — dedicated page for AI-powered BUY/SELL/WAIT
signal generation with full ICT/SMC analysis.

Features:
  - Exchange + symbol + timeframe + strategy + scan mode selection
  - One-click signal generation (runs in background, never freezes UI)
  - BUY/SELL/WAIT output with confidence meter
  - Entry, SL, TP1/TP2/TP3, Risk:Reward display
  - Trend, session, support/resistance
  - Full AI reasoning: confirmations (green ✓) + failures (red ✗)
  - Explanation of SMC/ICT concepts: Order Blocks, FVG, BOS, CHoCH,
    Liquidity Sweeps, Premium/Discount zones
"""
from __future__ import annotations

import threading
import time
import customtkinter as ctk

try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from services.signal_engine import SCAN_MODES, DEFAULT_SCAN_MODE

# ── Crypto symbols the generator supports ────────────────────────────────
CRYPTO_SYMBOLS = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE",
    "AVAX", "MATIC", "DOT", "LINK", "LTC", "UNI", "ATOM",
    "BCH", "COMP", "AAVE", "MKR",
]

FOREX_SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
    "USD/CHF", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY",
    "XAU/USD", "XAG/USD",
]

ALL_SYMBOLS = CRYPTO_SYMBOLS + FOREX_SYMBOLS

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

STRATEGIES = [
    "ICT Smart Money", "Smart Money Concepts", "Order Blocks",
    "Fair Value Gaps", "Liquidity Concepts", "Break of Structure",
    "Scalping", "Swing Trading", "Trend Following",
]


class CryptoSignalPage(ctk.CTkFrame):
    """
    Dedicated Crypto / Forex Signal Generator page.
    """

    def __init__(self, parent, crypto_service, signal_engine, market_analyzer,
                 paper_trading_engine=None, **kwargs):
        super().__init__(parent, fg_color=Colors.APP_BG, corner_radius=0, **kwargs)
        self.crypto_service       = crypto_service
        self.signal_engine        = signal_engine
        self.market_analyzer      = market_analyzer
        self.paper_trading_engine = paper_trading_engine
        self._analyzing           = False
        self._last_result         = None

        self._build_ui()

    # ── UI Construction ────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── LEFT: Controls ─────────────────────────────────────────────
        left = ctk.CTkFrame(self, fg_color=Colors.SIDEBAR_BG, corner_radius=s(10),
                             border_width=1, border_color=Colors.BORDER, width=s(280))
        left.grid(row=0, column=0, sticky="ns", padx=(s(12), s(6)), pady=s(12))
        left.grid_propagate(False)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="🔮  CRYPTO SIGNAL GENERATOR",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).grid(
            row=0, column=0, sticky="w", padx=s(14), pady=(s(14), s(4)))

        ctk.CTkLabel(left, text="AI-powered BUY / SELL / WAIT analysis with full ICT/SMC reasoning.",
                     font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                     wraplength=s(240), justify="left").grid(
            row=1, column=0, sticky="w", padx=s(14), pady=(0, s(10)))

        # Divider
        ctk.CTkFrame(left, fg_color=Colors.BORDER, height=1).grid(
            row=2, column=0, sticky="ew", padx=s(10))

        # Symbol selector
        self._label(left, 3, "Symbol")
        self._sym_var = ctk.StringVar(value="BTC")
        self._sym_menu = ctk.CTkOptionMenu(
            left, values=ALL_SYMBOLS, variable=self._sym_var,
            fg_color=Colors.CARD_BG, button_color=Colors.BORDER,
            button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
            dropdown_fg_color=Colors.CARD_BG, dropdown_hover_color=Colors.HOVER,
            dropdown_text_color=Colors.TEXT, font=SF.NORMAL(),
            width=s(240),
        )
        self._sym_menu.grid(row=4, column=0, padx=s(14), pady=(0, s(8)))

        # Scan mode selector
        self._label(left, 5, "Scan Mode (Timeframe Pipeline)")
        self._mode_var = ctk.StringVar(value=DEFAULT_SCAN_MODE)
        self._mode_menu = ctk.CTkOptionMenu(
            left, values=list(SCAN_MODES.keys()), variable=self._mode_var,
            fg_color=Colors.CARD_BG, button_color=Colors.BORDER,
            button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
            dropdown_fg_color=Colors.CARD_BG, dropdown_hover_color=Colors.HOVER,
            dropdown_text_color=Colors.TEXT, font=SF.NORMAL(),
            width=s(240),
        )
        self._mode_menu.grid(row=6, column=0, padx=s(14), pady=(0, s(8)))

        # Strategy
        self._label(left, 7, "Strategy Lens")
        self._strat_var = ctk.StringVar(value="ICT Smart Money")
        ctk.CTkOptionMenu(
            left, values=STRATEGIES, variable=self._strat_var,
            fg_color=Colors.CARD_BG, button_color=Colors.BORDER,
            button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
            dropdown_fg_color=Colors.CARD_BG, dropdown_hover_color=Colors.HOVER,
            dropdown_text_color=Colors.TEXT, font=SF.NORMAL(),
            width=s(240),
        ).grid(row=8, column=0, padx=s(14), pady=(0, s(10)))

        # Divider
        ctk.CTkFrame(left, fg_color=Colors.BORDER, height=1).grid(
            row=9, column=0, sticky="ew", padx=s(10))

        # GENERATE button
        self._btn_analyze = ctk.CTkButton(
            left, text="⚡  Generate Signal", height=S.ROW_H(),
            corner_radius=s(8), fg_color=Colors.PRIMARY,
            hover_color=Colors.PRIMARY_HOVER, text_color=Colors.ON_BUY,
            font=SF.SUBHEADER(), command=self._on_generate,
        )
        self._btn_analyze.grid(row=10, column=0, padx=s(14), pady=s(12), sticky="ew")

        # Status
        self._lbl_status = ctk.CTkLabel(
            left, text="Select a symbol and click Generate.",
            font=SF.TINY(), text_color=Colors.TEXT_MUTED,
            wraplength=s(240), justify="center",
        )
        self._lbl_status.grid(row=11, column=0, padx=s(14), pady=(0, s(8)))

        # Apply to Algo button (hidden initially)
        self._btn_apply = ctk.CTkButton(
            left, text="▶  Open Paper Trade", height=s(34),
            corner_radius=s(8), fg_color=Colors.BUY,
            hover_color=Colors.BUY_HOVER, text_color=Colors.ON_BUY,
            font=SF.NAV_BOLD(), command=self._on_apply_to_algo,
        )
        # Grid but hide initially
        self._btn_apply.grid(row=12, column=0, padx=s(14), pady=(0, s(12)), sticky="ew")
        self._btn_apply.grid_remove()

        # ── RIGHT: Results ─────────────────────────────────────────────
        self._right = ctk.CTkFrame(self, fg_color=Colors.APP_BG, corner_radius=0)
        self._right.grid(row=0, column=1, sticky="nsew", padx=(0, s(12)), pady=s(12))
        self._right.grid_columnconfigure(0, weight=1)
        self._right.grid_rowconfigure(1, weight=1)

        # Signal header card
        self._header_card = ctk.CTkFrame(
            self._right, fg_color=Colors.SIDEBAR_BG, corner_radius=s(10),
            border_width=1, border_color=Colors.BORDER,
        )
        self._header_card.grid(row=0, column=0, sticky="ew", pady=(0, s(8)))
        self._build_header_card()

        # Scrollable reasoning area
        self._scroll = ctk.CTkScrollableFrame(
            self._right, fg_color=Colors.APP_BG, corner_radius=0,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.PRIMARY,
        )
        bind_fast_scroll(self._scroll)
        self._scroll.grid(row=1, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

        self._show_idle_state()

    def _label(self, parent, row, text):
        ctk.CTkLabel(parent, text=text, font=SF.TINY(), text_color=Colors.LABEL).grid(
            row=row, column=0, sticky="w", padx=s(14), pady=(s(6), s(2)))

    def _build_header_card(self):
        hc = self._header_card
        hc.grid_columnconfigure(0, weight=3)
        hc.grid_columnconfigure(1, weight=2)
        hc.grid_columnconfigure(2, weight=2)
        hc.grid_columnconfigure(3, weight=2)
        hc.grid_columnconfigure(4, weight=2)
        hc.grid_columnconfigure(5, weight=2)

        self._lbl_sig     = ctk.CTkLabel(hc, text="—", font=(Fonts.HEADER[0], 36, "bold"), text_color=Colors.TEXT)
        self._lbl_sym     = ctk.CTkLabel(hc, text="—", font=SF.SUBHEADER(), text_color=Colors.TEXT_SECONDARY)
        self._lbl_conf    = ctk.CTkLabel(hc, text="—", font=SF.PRICE_SM(), text_color=Colors.NEUTRAL)
        self._lbl_trend   = ctk.CTkLabel(hc, text="—", font=SF.MONO_SM(), text_color=Colors.TEXT_MUTED)
        self._lbl_session = ctk.CTkLabel(hc, text="—", font=SF.TINY(), text_color=Colors.TEXT_MUTED)

        self._lbl_sig.grid(row=0, column=0, rowspan=2, padx=s(16), pady=s(14), sticky="w")
        self._lbl_sym.grid(row=0, column=1, padx=s(8), pady=(s(14), 0), sticky="w")
        self._lbl_conf.grid(row=1, column=1, padx=s(8), pady=(0, s(14)), sticky="w")
        self._lbl_trend.grid(row=0, column=2, padx=s(8), sticky="w")
        self._lbl_session.grid(row=1, column=2, padx=s(8), sticky="w")

        # Price cells
        self._price_cells: dict[str, ctk.CTkLabel] = {}
        for i, (key, label) in enumerate([
            ("entry", "ENTRY"), ("sl", "STOP LOSS"), ("tp1", "TP1"),
            ("tp2", "TP2"), ("tp3", "TP3"), ("rr", "RISK:REWARD"),
        ]):
            col = i % 3 + 3
            row = i // 3
            cell = ctk.CTkFrame(hc, fg_color=Colors.CARD_BG, corner_radius=s(6))
            cell.grid(row=row, column=col, padx=s(4), pady=s(6), sticky="ew")
            ctk.CTkLabel(cell, text=label, font=SF.TINY(), text_color=Colors.LABEL).pack(
                anchor="w", padx=s(8), pady=(s(4), 0))
            val_lbl = ctk.CTkLabel(cell, text="—", font=SF.MONO_SM(), text_color=Colors.TEXT)
            val_lbl.pack(anchor="w", padx=s(8), pady=(0, s(4)))
            self._price_cells[key] = val_lbl

        # Confidence bar
        bar_frame = ctk.CTkFrame(hc, fg_color=Colors.WELL_BG, height=s(6), corner_radius=s(3))
        bar_frame.grid(row=2, column=0, columnspan=6, sticky="ew", padx=s(12), pady=(0, s(10)))
        bar_frame.grid_propagate(False)
        self._conf_bar = ctk.CTkFrame(bar_frame, fg_color=Colors.BORDER, height=s(6), corner_radius=s(3))
        self._conf_bar.place(relx=0, rely=0, relwidth=0.0, relheight=1.0)

    # ── Signal generation ──────────────────────────────────────────────
    def _on_generate(self):
        if self._analyzing:
            return
        self._analyzing = True
        self._btn_analyze.configure(text="⏳ Analyzing...", state="disabled")
        self._lbl_status.configure(text="Fetching market data...", text_color=Colors.NEUTRAL)
        self._btn_apply.grid_remove()

        sym  = self._sym_var.get()
        mode = self._mode_var.get()
        threading.Thread(target=self._bg_analyze, args=(sym, mode), daemon=True).start()

    def _bg_analyze(self, symbol: str, mode: str):
        try:
            from services.signal_explainer import SignalExplainer
            explainer = SignalExplainer(self.crypto_service, self.market_analyzer)
            result = explainer.explain(symbol, mode)
        except Exception as e:
            result = {
                "signal": "WAIT", "confidence": 0,
                "entry": 0, "stop_loss": 0,
                "take_profit_1": 0, "take_profit_2": 0, "take_profit_3": 0,
                "risk_reward": 0, "trend": "Error", "session": "—",
                "confirmations": [], "failures": [f"Analysis error: {e}"],
                "summary": f"Analysis failed: {e}",
                "symbol": symbol, "mode": mode,
            }
        finally:
            self._analyzing = False
        try:
            self.after(0, self._display_result, result)
        except Exception:
            pass

    def _display_result(self, result: dict):
        self._last_result = result
        self._analyzing   = False
        self._btn_analyze.configure(text="⚡  Generate Signal", state="normal")

        sig       = result.get("signal", "WAIT")
        conf      = result.get("confidence", 0)
        symbol    = result.get("symbol", "")
        mode      = result.get("mode", "")
        trend     = result.get("trend", "Neutral")
        session   = result.get("session", "—")
        entry     = result.get("entry", 0)
        sl        = result.get("stop_loss", 0)
        tp1       = result.get("take_profit_1", 0)
        tp2       = result.get("take_profit_2", 0)
        tp3       = result.get("take_profit_3", 0)
        rr        = result.get("risk_reward", 0)
        confirms  = result.get("confirmations", [])
        failures  = result.get("failures", [])
        summary   = result.get("summary", "")
        support   = result.get("support", 0)
        resistance= result.get("resistance", 0)

        # Signal color
        sig_color = Colors.BUY if sig == "BUY" else (Colors.SELL if sig == "SELL" else Colors.NEUTRAL)
        self._lbl_sig.configure(text=sig, text_color=sig_color)
        self._lbl_sym.configure(text=f"{symbol}  ·  {mode}")
        self._lbl_conf.configure(
            text=f"{conf}% confidence",
            text_color=Colors.BUY if conf >= 80 else Colors.NEUTRAL if conf >= 60 else Colors.SELL,
        )
        self._lbl_trend.configure(
            text=f"Trend: {trend}",
            text_color=Colors.BUY if "Bullish" in trend else Colors.SELL if "Bearish" in trend else Colors.TEXT_MUTED,
        )
        self._lbl_session.configure(text=session)

        # Price cells
        def _fp(v): return f"{v:.5f}" if v else "—"
        self._price_cells["entry"].configure(text=_fp(entry), text_color=Colors.TEXT)
        self._price_cells["sl"].configure(text=_fp(sl), text_color=Colors.SELL if sl else Colors.TEXT_MUTED)
        self._price_cells["tp1"].configure(text=_fp(tp1), text_color=Colors.BUY if tp1 else Colors.TEXT_MUTED)
        self._price_cells["tp2"].configure(text=_fp(tp2), text_color=Colors.BUY if tp2 else Colors.TEXT_MUTED)
        self._price_cells["tp3"].configure(text=_fp(tp3), text_color=Colors.BUY if tp3 else Colors.TEXT_MUTED)
        self._price_cells["rr"].configure(
            text=f"1:{rr:.1f}" if rr else "—",
            text_color=Colors.GOLD if rr >= 2 else Colors.TEXT,
        )

        # Confidence bar
        self._conf_bar.place(relx=0, rely=0, relwidth=min(conf/100, 1.0), relheight=1.0)
        self._conf_bar.configure(fg_color=sig_color)

        self._lbl_status.configure(
            text=f"✓ Analysis complete — {len(confirms)} confirmations, {len(failures)} failed conditions.",
            text_color=Colors.BUY if sig != "WAIT" else Colors.NEUTRAL,
        )

        # Show Apply button for BUY/SELL
        if sig in ("BUY", "SELL") and self.paper_trading_engine:
            self._btn_apply.grid()
        else:
            self._btn_apply.grid_remove()

        # Rebuild reasoning area
        for w in self._scroll.winfo_children():
            try: w.destroy()
            except Exception: pass

        self._scroll.grid_columnconfigure(0, weight=1)

        # Summary card
        self._section_card(self._scroll, "📋 AI SIGNAL SUMMARY", summary, Colors.PRIMARY)

        # Support / Resistance
        if support or resistance:
            sr_txt = f"Support: {support:.5f}   |   Resistance: {resistance:.5f}"
            self._section_card(self._scroll, "📊 SUPPORT & RESISTANCE", sr_txt, Colors.GOLD)

        # Confirmations
        if confirms:
            self._reasons_card(self._scroll, f"✅ CONFIRMATIONS ({len(confirms)})", confirms, Colors.BUY)

        # Failures / Why WAIT
        if failures:
            title = "⚠ CONDITIONS NOT MET" if sig == "WAIT" else f"⚠ FAILED CONDITIONS ({len(failures)})"
            self._reasons_card(self._scroll, title, failures, Colors.SELL)

        # SMC Analysis details
        smc = result.get("smc_analysis", {})
        if smc:
            self._smc_card(self._scroll, smc)

    def _section_card(self, parent, title: str, body: str, accent: str):
        card = ctk.CTkFrame(parent, fg_color=Colors.SIDEBAR_BG, corner_radius=s(8),
                             border_width=1, border_color=Colors.BORDER)
        card.pack(fill="x", pady=(0, s(6)), padx=0)
        ctk.CTkLabel(card, text=title, font=SF.NAV_BOLD(), text_color=accent).pack(
            anchor="w", padx=s(12), pady=(s(10), s(4)))
        ctk.CTkLabel(card, text=body, font=SF.SMALL(), text_color=Colors.TEXT_SECONDARY,
                     wraplength=s(700), justify="left").pack(
            anchor="w", padx=s(12), pady=(0, s(10)))

    def _reasons_card(self, parent, title: str, items: list, accent: str):
        card = ctk.CTkFrame(parent, fg_color=Colors.SIDEBAR_BG, corner_radius=s(8),
                             border_width=1, border_color=Colors.BORDER)
        card.pack(fill="x", pady=(0, s(6)), padx=0)
        ctk.CTkLabel(card, text=title, font=SF.NAV_BOLD(), text_color=accent).pack(
            anchor="w", padx=s(12), pady=(s(10), s(4)))
        for item in items:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=s(8), pady=s(2))
            bullet = "✓" if accent == Colors.BUY else "✗"
            ctk.CTkLabel(row, text=f"{bullet}  {item}", font=SF.SMALL(),
                         text_color=Colors.TEXT_SECONDARY if accent == Colors.BUY else Colors.TEXT_MUTED,
                         wraplength=s(700), justify="left", anchor="w").pack(
                anchor="w", padx=s(4), pady=s(2))
        ctk.CTkFrame(card, fg_color="transparent", height=s(4)).pack()

    def _smc_card(self, parent, smc: dict):
        if not smc:
            return
        card = ctk.CTkFrame(parent, fg_color=Colors.SIDEBAR_BG, corner_radius=s(8),
                             border_width=1, border_color=Colors.BORDER)
        card.pack(fill="x", pady=(0, s(6)), padx=0)
        ctk.CTkLabel(card, text="🔍 SMC / ICT ANALYSIS BY TIMEFRAME",
                     font=SF.NAV_BOLD(), text_color=Colors.CYAN).pack(
            anchor="w", padx=s(12), pady=(s(10), s(4)))

        concepts = ["order_block", "fvg", "liquidity_sweep", "bos", "choch", "zone"]
        labels   = {
            "order_block":     "Order Block",
            "fvg":             "Fair Value Gap",
            "liquidity_sweep": "Liquidity Sweep",
            "bos":             "Break of Structure",
            "choch":           "Change of Character",
            "zone":            "Price Zone",
        }

        for tf, facts in sorted(smc.items()):
            tf_row = ctk.CTkFrame(card, fg_color=Colors.CARD_BG, corner_radius=s(6))
            tf_row.pack(fill="x", padx=s(8), pady=s(3))
            ctk.CTkLabel(tf_row, text=tf.upper(), font=SF.STATUS_BOLD(),
                         text_color=Colors.PRIMARY, width=s(50)).pack(side="left", padx=s(8), pady=s(6))
            for key in concepts:
                val = facts.get(key, "—") or "—"
                if val and val != "—":
                    col = Colors.BUY if "bullish" in str(val) or "discount" in str(val) else (
                        Colors.SELL if "bearish" in str(val) or "premium" in str(val) else Colors.NEUTRAL
                    )
                    ctk.CTkLabel(tf_row, text=f"{labels[key]}: {val}",
                                 font=SF.TINY(), text_color=col).pack(side="left", padx=s(8), pady=s(6))
        ctk.CTkFrame(card, fg_color="transparent", height=s(6)).pack()

    def _show_idle_state(self):
        for w in self._scroll.winfo_children():
            try: w.destroy()
            except Exception: pass

        ctk.CTkLabel(
            self._scroll,
            text="⚡ Select a symbol, choose a scan mode, and click Generate Signal.",
            font=SF.SUBHEADER(), text_color=Colors.TEXT_MUTED,
        ).pack(expand=True, pady=s(60))

        concepts_text = (
            "This generator runs a full multi-timeframe ICT/SMC pipeline:\n\n"
            "• TREND: EMA20/EMA50/SMA200 + ADX on higher timeframes\n"
            "• SETUP: Order Blocks, Fair Value Gaps, Liquidity Sweeps, Premium/Discount zones\n"
            "• ENTRY: BOS/CHoCH, RSI, MACD, Volume, Momentum on lower timeframes\n"
            "• CONFIDENCE: Weighted confluence score across all confirmations\n"
            "• LEVELS: ATR-based Entry, Stop Loss, TP1/TP2/TP3, Risk:Reward\n\n"
            "WAIT signals explain exactly which conditions failed and why no trade is taken."
        )
        ctk.CTkLabel(
            self._scroll,
            text=concepts_text,
            font=SF.SMALL(), text_color=Colors.TEXT_MUTED,
            wraplength=s(700), justify="left",
        ).pack(pady=(0, s(30)))

    def _on_apply_to_algo(self):
        if not self._last_result or not self.paper_trading_engine:
            return
        result = self._last_result
        if result.get("signal") not in ("BUY", "SELL"):
            return

        from models.signal_model import Signal
        import time as _t

        now = _t.time()
        sig = Signal(
            symbol        = result["symbol"],
            direction     = result["signal"],
            entry_price   = result["entry"],
            current_price = result["entry"],
            stop_loss     = result["stop_loss"],
            take_profit_1 = result["take_profit_1"],
            take_profit_2 = result["take_profit_2"],
            take_profit_3 = result["take_profit_3"],
            risk_reward   = result["risk_reward"],
            confidence    = result["confidence"],
            strength      = "Moderate",
            trend         = result["trend"],
            setup_timeframe = "15M",
            trade_type    = "Intraday",
            data_source   = "CryptoSignalPage",
            session       = result["session"],
            reasons       = result["confirmations"],
        )

        status = self.paper_trading_engine.open_trade_from_signal(sig)
        self._lbl_status.configure(text=status,
                                    text_color=Colors.BUY if "✅" in status else Colors.SELL)
