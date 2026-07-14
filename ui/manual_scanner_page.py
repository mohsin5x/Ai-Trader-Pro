"""
ui/manual_scanner_page.py
==========================
Manual Market Scanner — pick markets, strategy mode, AND scan timeframe,
then scan only the selected instruments.

New in this version:
  • SCAN MODE selector: Swing (1D/4H), Intraday (4H/1H), Scalp (1H/30M),
    Scalp (30M/15M), Scalp (15M/5M), Micro-Scalp (5M/1M)
  • Each mode shifts the entire multi-timeframe pipeline so the trend,
    setup, and entry frames all match the chosen trading horizon.
  • STRATEGY filter (which AI strategy label to highlight per signal)
  • Min confidence slider
  • Live signal count while scanning
  • Explain modal + Apply to Algo button per signal
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
from models.signal_model import Signal
from services.signal_engine import SCAN_MODES, DEFAULT_SCAN_MODE
from ui.modal_overlay import BaseDialog, make_dialog

# ── Market categories ────────────────────────────────────────────────────────
MARKET_CATEGORIES = {
    "Forex Majors": [
        "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
        "USD/CAD", "USD/CHF", "NZD/USD",
    ],
    "Forex Crosses": [
        "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/AUD",
        "EUR/CAD", "AUD/JPY", "GBP/AUD", "GBP/CAD",
        "CAD/JPY", "NZD/JPY", "CHF/JPY",
        # Added crosses
        "EUR/NZD", "EUR/CHF", "GBP/CHF", "GBP/NZD",
        "AUD/NZD", "AUD/CAD", "AUD/CHF",
        "NZD/USD", "NZD/CAD", "NZD/CHF",
        "CAD/CHF", "USD/SGD", "USD/HKD",
        "USD/MXN", "USD/NOK", "USD/SEK",
        "USD/DKK", "USD/ZAR", "USD/TRY",
        "EUR/PLN", "EUR/HUF", "EUR/CZK",
        "EUR/SEK", "EUR/NOK",
    ],
    "Crypto — Large Cap": [
        "BTC", "ETH", "BNB", "SOL", "XRP",
        "ADA", "DOGE", "AVAX", "MATIC", "DOT",
        "LINK", "LTC", "UNI", "ATOM",
        # Added large cap
        "TRX", "TON", "SHIB", "DAI", "WBTC",
        "BCH", "APT", "OP", "ARB", "FIL",
    ],
    "Crypto — Mid Cap": [
        "INJ", "SUI", "SEI", "NEAR", "FTM",
        "ALGO", "VET", "SAND", "MANA", "AXS",
        "GALA", "CRV", "AAVE", "SNX", "MKR",
        "COMP", "YFI", "1INCH", "CAKE", "LDO",
        # Added to reach 100 total
        "RUNE", "KAVA", "ZIL", "IOTA", "THETA",
        "HBAR", "ENJ", "CHZ", "BAT",
    ],
    "Metals": ["XAU/USD", "XAG/USD"],
    "Indices": ["US30", "NAS100", "SPX500"],
}

ALL_STRATEGIES = [
    # ── Forex Strategies ──────────────────────────────────────────────────────
    "ICT Smart Money",       # [Forex]
    "Smart Money Concepts",  # [Forex]
    "Support & Resistance",  # [Forex]
    "Liquidity Concepts",    # [Forex]
    "Order Blocks",          # [Forex]
    "Fair Value Gaps",       # [Forex]
    "Break of Structure",    # [Forex]
    "Change of Character",   # [Forex]
    "Scalping",              # [Forex]
    "Swing Trading",         # [Forex]
    "Trend Following",       # [Forex]
    "Breakout",              # [Forex]
    # ── Crypto Strategies ─────────────────────────────────────────────────────
    "Crypto: Trend + EMA Cross",    # [Crypto]
    "Crypto: RSI Divergence",       # [Crypto]
    "Crypto: MACD Momentum",        # [Crypto]
    "Crypto: Bollinger Squeeze",    # [Crypto]
    "Crypto: Volume Profile",       # [Crypto]
    "Crypto: On-Chain Breakout",    # [Crypto]
    "Crypto: Wyckoff Accumulation", # [Crypto]
    "Crypto: DCA Swing",            # [Crypto]
]

_SIGNAL_COOLDOWN_SECONDS = 180   # shorter cooldown for scalp modes

# ── Scan mode display info ────────────────────────────────────────────────────
_MODE_INFO = {
    "Swing (1D/4H)":       ("🌊", "Daily+4H trend · 1H setup · 30M entry · wider SL · 1:3–5 TP",     Colors.__dict__.get("CYAN", "#00E5FF")),
    "Intraday (4H/1H)":    ("📊", "4H+1H trend · 15M setup · 5M+1M entry · balanced · 1:2 TP",       "#848E9C"),
    "Scalp (1H/30M)":      ("⚡", "1H+30M trend · 5M setup · 1M entry · tight SL · 1:1.5 TP",        Colors.__dict__.get("NEUTRAL", "#F5A623")),
    "Scalp (30M/15M)":     ("⚡", "30M+15M trend · 5M setup · 1M entry · very tight · 1:1.2 TP",     Colors.__dict__.get("NEUTRAL", "#F5A623")),
    "Scalp (15M/5M)":      ("🔥", "15M+5M trend · 1M setup · 1M entry · ultra-tight · 1:1 TP",       Colors.__dict__.get("SELL",    "#F6465D")),
    "Micro-Scalp (5M/1M)": ("🔥", "5M+1M trend · 1M setup · 1M entry · minimum SL · 1:0.8 TP",      Colors.__dict__.get("SELL",    "#F6465D")),
}

def _fp(v):
    if not v:
        return "—"
    return f"{v:,.2f}" if v > 100 else f"{v:,.4f}"


# ── Signal explanation modal ─────────────────────────────────────────────────
class _ExplainModal(BaseDialog):
    def __init__(self, parent, signal: Signal):
        super().__init__(parent,
                         title=f"Signal Explanation — {signal.symbol}",
                         size=(660, 560), resizable=(True, True))
        self.configure(fg_color=Colors.APP_BG)

        dir_color = Colors.BUY if signal.direction == "BUY" else Colors.SELL

        hdr = ctk.CTkFrame(self, fg_color=Colors.SIDEBAR_BG,
                            border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        hdr.pack(fill="x", padx=16, pady=(16, 8))
        h_inner = ctk.CTkFrame(hdr, fg_color="transparent")
        h_inner.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(h_inner, text=signal.symbol, font=SF.HEADER(), text_color=Colors.TEXT).pack(side="left")
        ctk.CTkLabel(h_inner, text=f" {signal.direction} ", font=SF.MONO(),
                     text_color=(Colors.ON_BUY if signal.direction == "BUY" else Colors.ON_SELL),
                     fg_color=dir_color, corner_radius=s(6)).pack(side="left", padx=8)
        ctk.CTkLabel(h_inner, text=f"{signal.confidence}% · {signal.strength} · {signal.trade_type}",
                     font=SF.MONO(), text_color=Colors.NEUTRAL).pack(side="right")

        # Levels
        levels = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                               border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        levels.pack(fill="x", padx=16, pady=(0, 8))
        for i in range(6):
            levels.grid_columnconfigure(i, weight=1)
        for col, (label, value, color) in enumerate([
            ("ENTRY",     _fp(signal.entry_price),    Colors.TEXT),
            ("STOP LOSS", _fp(signal.stop_loss),      Colors.SELL),
            ("TP 1",      _fp(signal.take_profit_1),  Colors.BUY),
            ("TP 2",      _fp(signal.take_profit_2),  Colors.BUY),
            ("TP 3",      _fp(signal.take_profit_3),  Colors.BUY),
            ("R:R",       f"1:{signal.risk_reward:.2f}", Colors.NEUTRAL),
        ]):
            ctk.CTkLabel(levels, text=label, font=SF.TINY(), text_color=Colors.LABEL).grid(
                row=0, column=col, pady=(8, 0), padx=8)
            ctk.CTkLabel(levels, text=value, font=SF.MONO_SM(), text_color=color).grid(
                row=1, column=col, pady=(0, 8), padx=8)

        ctk.CTkLabel(self, text="WHY THIS SIGNAL WAS GENERATED",
                     font=SF.NAV_BOLD(), text_color=Colors.LABEL).pack(anchor="w", padx=16, pady=(4, 4))

        scroll = ctk.CTkScrollableFrame(self, fg_color=Colors.WELL_BG,
                                         corner_radius=s(8), border_width=1, border_color=Colors.BORDER)
        bind_fast_scroll(scroll)
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        reasons = signal.reasons or []
        if not reasons:
            ctk.CTkLabel(scroll, text="No detailed confirmation data available.",
                         font=SF.SMALL(), text_color=Colors.TEXT_MUTED).pack(padx=8, pady=8)
        else:
            for i, reason in enumerate(reasons, 1):
                row = ctk.CTkFrame(scroll, fg_color=Colors.CARD_BG if i % 2 == 0 else "transparent",
                                   corner_radius=s(6))
                row.pack(fill="x", padx=4, pady=2)
                ctk.CTkLabel(row, text=f"✓  {reason}", font=SF.SMALL(),
                             text_color=Colors.TEXT_SECONDARY, justify="left",
                             wraplength=s(590), anchor="w").pack(fill="x", padx=10, pady=6)

        info = (f"Mode: {signal.trade_type}  ·  Setup TF: {signal.setup_timeframe}  ·  "
                f"Session: {signal.session}  ·  Trend: {signal.trend}")
        ctk.CTkLabel(self, text=info, font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                     wraplength=s(600), justify="left").pack(anchor="w", padx=16, pady=(0, 16))


# ── Signal result row ─────────────────────────────────────────────────────────
class _SignalRow(ctk.CTkFrame):
    def __init__(self, parent, signal: Signal, idx: int, on_explain, on_apply_algo, on_auto_ai=None):
        bg = Colors.CARD_BG if idx % 2 == 0 else Colors.WELL_BG
        super().__init__(parent, fg_color=bg, corner_radius=s(4), height=56)
        self.pack(fill="x", padx=4, pady=1)
        self.pack_propagate(False)

        is_buy    = signal.direction == "BUY"
        dir_color = Colors.BUY if is_buy else Colors.SELL
        dir_arrow = "▲" if is_buy else "▼"
        conf      = signal.confidence
        conf_color = Colors.BUY if conf >= 90 else Colors.NEUTRAL if conf >= 75 else Colors.TEXT_MUTED
        created   = time.strftime("%H:%M", time.localtime(signal.created_at)) if signal.created_at else "—"

        # Trade type badge color
        tt = signal.trade_type or ""
        tt_color = (Colors.SELL if "Micro" in tt else
                    Colors.NEUTRAL if "Scalp" in tt else
                    Colors.__dict__.get("CYAN", "#00E5FF") if "Swing" in tt else Colors.TEXT_MUTED)

        cols = (3, 2, 2, 3, 3, 3, 2, 2, 2, 2, 2, 2)
        for i, w in enumerate(cols):
            self.grid_columnconfigure(i, weight=w)

        col = 0
        ctk.CTkLabel(self, text=signal.symbol, font=SF.MONO_SM(),
                     text_color=Colors.TEXT, anchor="w").grid(row=0, column=col, sticky="w", padx=(10, 4))
        col += 1
        ctk.CTkLabel(self, text=f"{dir_arrow} {signal.direction}", font=SF.PILL_LG(),
                     text_color=dir_color, anchor="w").grid(row=0, column=col, sticky="w", padx=4)
        col += 1
        ctk.CTkLabel(self, text=signal.setup_timeframe or "—", font=SF.STATUS_BOLD(),
                     text_color=tt_color, anchor="center").grid(row=0, column=col, sticky="ew", padx=4)
        col += 1
        ctk.CTkLabel(self, text=_fp(signal.entry_price), font=SF.MONO_TINY(),
                     text_color=Colors.TEXT_SECONDARY, anchor="e").grid(row=0, column=col, sticky="e", padx=4)
        col += 1
        ctk.CTkLabel(self, text=_fp(signal.stop_loss), font=SF.MONO_TINY(),
                     text_color=Colors.SELL, anchor="e").grid(row=0, column=col, sticky="e", padx=4)
        col += 1
        ctk.CTkLabel(self, text=_fp(signal.take_profit_1), font=SF.MONO_TINY(),
                     text_color=Colors.BUY, anchor="e").grid(row=0, column=col, sticky="e", padx=4)
        col += 1
        ctk.CTkLabel(self, text=f"{conf}%", font=SF.MONO_SM(),
                     text_color=conf_color, anchor="e").grid(row=0, column=col, sticky="e", padx=4)
        col += 1
        ctk.CTkLabel(self, text=created, font=SF.MONO_TINY(),
                     text_color=Colors.TEXT_MUTED, anchor="center").grid(row=0, column=col, sticky="ew", padx=4)
        col += 1
        rr_text = f"1:{signal.risk_reward:.1f}"
        ctk.CTkLabel(self, text=rr_text, font=SF.MONO_TINY(),
                     text_color=Colors.NEUTRAL, anchor="center").grid(row=0, column=col, sticky="ew", padx=4)
        col += 1
        ctk.CTkButton(self, text="Explain", width=s(60), height=s(28), corner_radius=s(5),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                      text_color=Colors.BUY, font=SF.STATUS_BOLD(),
                      command=lambda s=signal: on_explain(s)).grid(row=0, column=col, padx=4)
        col += 1
        # "→ Algo" — opens timer dialog (with auto-exit option)
        ctk.CTkButton(self, text="→ Algo", width=62, height=s(28), corner_radius=s(5),
                      fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
                      text_color=Colors.ON_BUY, font=SF.STATUS_BOLD(),
                      command=lambda s=signal: on_apply_algo(s)).grid(row=0, column=col, padx=2)
        col += 1
        # "⚡ Auto AI" — instantly sends to paper trading engine without dialog
        def _direct_auto_ai(s=signal):
            if on_auto_ai:
                on_auto_ai(s)
        ctk.CTkButton(self, text="⚡ Auto", width=62, height=s(28), corner_radius=s(5),
                      fg_color="#2D6A2D", hover_color="#3A8A3A",
                      text_color=Colors.TEXT, font=SF.STATUS_BOLD(),
                      command=_direct_auto_ai).grid(row=0, column=col, padx=(2, 10))


# ── Main page ─────────────────────────────────────────────────────────────────
class ManualScannerPage(ctk.CTkFrame):
    def __init__(self, parent, crypto_service=None, signal_engine=None,
                 market_analyzer=None, get_account_context=None, on_apply_to_algo=None,
                 on_auto_ai_apply=None):
        super().__init__(parent, fg_color=Colors.APP_BG, corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._destroyed    = False
        self._on_auto_ai_apply = on_auto_ai_apply
        self._crypto_service   = crypto_service
        self._signal_engine    = signal_engine
        self._market_analyzer  = market_analyzer
        self._get_account_ctx  = get_account_context
        self._on_apply_to_algo = on_apply_to_algo

        self._lock        = threading.Lock()
        self._results: list[Signal] = []
        self._scan_thread: threading.Thread | None = None
        self._paused      = False
        self._stop_scan   = False
        self._seen_signals: dict[str, tuple] = {}

        self._build_header()
        self._build_mode_selector()
        self._build_config_panel()
        self._build_progress()
        self._build_table()

    # ── Header ───────────────────────────────────────────────────────────────


    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(), pady=(Spacing.LG(), 4))

        ctk.CTkLabel(hdr, text="MANUAL MARKET SCANNER", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")

        ctrl = ctk.CTkFrame(hdr, fg_color="transparent")
        ctrl.pack(side="right")

        self._btn_scan = ctk.CTkButton(
            ctrl, text="▶  Scan Markets", width=s(140), height=34, corner_radius=s(6),
            fg_color=Colors.BUY, hover_color=Colors.BUY_HOVER,
            text_color=Colors.ON_BUY, font=SF.NAV_BOLD(),
            command=self._start_scan)
        self._btn_scan.pack(side="left", padx=(0, 6))

        self._btn_pause = ctk.CTkButton(
            ctrl, text="⏸ Pause", width=84, height=34, corner_radius=s(6),
            fg_color=Colors.NEUTRAL, hover_color=Colors.HOVER_STRONG,
            text_color=Colors.TEXT, font=SF.PILL_LG(),
            command=self._toggle_pause, state="disabled")
        self._btn_pause.pack(side="left", padx=(0, 6))

        self._btn_stop = ctk.CTkButton(
            ctrl, text="■ Stop", width=74, height=34, corner_radius=s(6),
            fg_color=Colors.SELL, hover_color=Colors.SELL_HOVER,
            text_color=Colors.TEXT, font=SF.PILL_LG(),
            command=self._stop_scan_fn, state="disabled")
        self._btn_stop.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            ctrl, text="⟳ Refresh", width=84, height=34, corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=self._refresh_results).pack(side="left")

    # ── Scan mode selector ───────────────────────────────────────────────────
    def _build_mode_selector(self):
        outer = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                              border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        outer.grid(row=1, column=0, sticky="ew", padx=Spacing.LG(), pady=(0, 6))

        title_row = ctk.CTkFrame(outer, fg_color="transparent")
        title_row.pack(fill="x", padx=14, pady=(10, 6))
        ctk.CTkLabel(title_row, text="SCAN MODE — Timeframe & Trading Style",
                     font=SF.NAV_BOLD(), text_color=Colors.TEXT).pack(side="left")
        ctk.CTkLabel(title_row,
                     text="Scalp modes use shorter TF pipelines and tighter SL/TP for more frequent signals",
                     font=SF.TINY(), text_color=Colors.TEXT_MUTED).pack(side="right")

        mode_row = ctk.CTkFrame(outer, fg_color="transparent")
        mode_row.pack(fill="x", padx=14, pady=(0, 10))

        self._mode_var = ctk.StringVar(value=DEFAULT_SCAN_MODE)
        self._mode_btns: dict[str, ctk.CTkButton] = {}

        for mode_key in SCAN_MODES.keys():
            icon, desc, color = _MODE_INFO.get(mode_key, ("📊", mode_key, Colors.TEXT_MUTED))
            btn = ctk.CTkButton(
                mode_row,
                text=f"{icon} {mode_key}",
                width=S.BTN_W_LG(), height=s(44), corner_radius=s(8),
                fg_color=Colors.CARD_BG_ALT,
                hover_color=Colors.HOVER_STRONG,
                text_color=Colors.TEXT_SECONDARY,
                font=SF.STATUS_BOLD(),
                command=lambda k=mode_key: self._select_mode(k),
            )
            btn.pack(side="left", padx=3)
            self._mode_btns[mode_key] = btn

        # Info label showing details of selected mode
        self._lbl_mode_info = ctk.CTkLabel(
            outer, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED, anchor="w")
        self._lbl_mode_info.pack(fill="x", padx=14, pady=(0, 8))

        # Select default
        self._select_mode(DEFAULT_SCAN_MODE)

    def _select_mode(self, mode: str):
        self._mode_var.set(mode)
        icon, desc, color = _MODE_INFO.get(mode, ("📊", mode, Colors.TEXT_MUTED))
        for k, btn in self._mode_btns.items():
            if k == mode:
                btn.configure(fg_color=color, text_color=Colors.TEXT,
                               border_width=2, border_color=Colors.TEXT)
            else:
                btn.configure(fg_color=Colors.CARD_BG_ALT, text_color=Colors.TEXT_SECONDARY,
                               border_width=0)
        self._lbl_mode_info.configure(
            text=f"  {desc}",
            text_color=color,
        )

    # ── Config panel (markets + strategies) ──────────────────────────────────
    def _build_config_panel(self):
        cfg = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                            border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        cfg.grid(row=2, column=0, sticky="ew", padx=Spacing.LG(), pady=(0, 6))
        cfg.grid_columnconfigure(0, weight=1)
        cfg.grid_columnconfigure(1, weight=1)

        # Left: market categories
        left = ctk.CTkFrame(cfg, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=12, pady=10)

        ctk.CTkLabel(left, text="Market Categories:", font=SF.NAV_BOLD(),
                     text_color=Colors.TEXT).pack(anchor="w", pady=(0, 6))

        cat_grid = ctk.CTkFrame(left, fg_color="transparent")
        cat_grid.pack(fill="x")
        self._cat_vars: dict[str, ctk.BooleanVar] = {}
        for i, cat in enumerate(MARKET_CATEGORIES.keys()):
            var = ctk.BooleanVar(value=(cat == "Forex Majors"))
            self._cat_vars[cat] = var
            ctk.CTkCheckBox(
                cat_grid,
                text=f"{cat} ({len(MARKET_CATEGORIES[cat])})",
                variable=var, font=SF.PILL(),
                text_color=Colors.TEXT_SECONDARY,
                fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
                checkmark_color=Colors.ON_BUY,
            ).grid(row=i // 3, column=i % 3, sticky="w", padx=8, pady=3)

        # Right: strategies — SEPARATED into Forex tab and Crypto tab
        right = ctk.CTkFrame(cfg, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=12, pady=10)

        # ── Tab header row ────────────────────────────────────────────
        strat_hdr = ctk.CTkFrame(right, fg_color="transparent")
        strat_hdr.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(strat_hdr, text="Strategies:",
                     font=SF.NAV_BOLD(),
                     text_color=Colors.TEXT).pack(side="left")

        # All / None apply to whichever tab is active
        ctk.CTkButton(strat_hdr, text="All ✓", width=46, height=s(22), corner_radius=s(4),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                      text_color=Colors.TEXT_SECONDARY, font=SF.TINY(),
                      command=self._strat_select_all).pack(side="right", padx=(3, 0))
        ctk.CTkButton(strat_hdr, text="None ✗", width=s(50), height=s(22), corner_radius=s(4),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                      text_color=Colors.TEXT_SECONDARY, font=SF.TINY(),
                      command=self._strat_select_none).pack(side="right", padx=(0, 3))

        # ── Tab switcher buttons ──────────────────────────────────────
        tab_row = ctk.CTkFrame(right, fg_color=Colors.WELL_BG, corner_radius=s(6))
        tab_row.pack(fill="x", pady=(0, 6))

        self._strat_tab = "forex"   # active tab state
        self._btn_tab_forex  = ctk.CTkButton(
            tab_row, text="📈 Forex / Metals / Indices",
            width=s(180), height=s(28), corner_radius=s(5),
            fg_color=Colors.PRIMARY, text_color=Colors.ON_BUY,
            hover_color=Colors.PRIMARY_HOVER, font=SF.STATUS_BOLD(),
            command=lambda: self._switch_strat_tab("forex"))
        self._btn_tab_forex.pack(side="left", padx=(4, 2), pady=4)

        self._btn_tab_crypto = ctk.CTkButton(
            tab_row, text="₿ Crypto",
            width=s(90), height=s(28), corner_radius=s(5),
            fg_color=Colors.CARD_BG_ALT, text_color=Colors.TEXT_SECONDARY,
            hover_color=Colors.HOVER_STRONG, font=SF.STATUS_BOLD(),
            command=lambda: self._switch_strat_tab("crypto"))
        self._btn_tab_crypto.pack(side="left", padx=(2, 4), pady=4)

        # ── Strategy checkboxes — two pages in one container ──────────
        self._strat_container = ctk.CTkFrame(right, fg_color="transparent")
        self._strat_container.pack(fill="x")

        self._strat_vars: dict[str, ctk.BooleanVar] = {}

        # Forex strategies grid
        self._forex_grid = ctk.CTkFrame(self._strat_container, fg_color="transparent")
        _FOREX = [s for s in ALL_STRATEGIES if not s.startswith("Crypto:")]
        for i, strat in enumerate(_FOREX):
            var = ctk.BooleanVar(value=True)
            self._strat_vars[strat] = var
            ctk.CTkCheckBox(
                self._forex_grid, text=strat, variable=var,
                font=SF.TINY(), text_color=Colors.TEXT_SECONDARY,
                fg_color=Colors.CYAN, hover_color="#00B8D4",
                checkmark_color="#002030",
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=6, pady=2)
        self._forex_grid.pack(fill="x")

        # Crypto strategies grid (hidden initially)
        self._crypto_grid = ctk.CTkFrame(self._strat_container, fg_color="transparent")
        _CRYPTO = [s for s in ALL_STRATEGIES if s.startswith("Crypto:")]
        for i, strat in enumerate(_CRYPTO):
            # strip "Crypto: " prefix for display brevity
            label = strat.replace("Crypto: ", "")
            var = ctk.BooleanVar(value=True)
            self._strat_vars[strat] = var
            ctk.CTkCheckBox(
                self._crypto_grid, text=label, variable=var,
                font=SF.TINY(), text_color=Colors.TEXT_SECONDARY,
                fg_color=Colors.NEUTRAL, hover_color="#C87800",
                checkmark_color="#1A0800",
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=6, pady=2)
        # crypto_grid starts hidden; shown when tab is switched

        # ── Tag line ──────────────────────────────────────────────────
        self._lbl_strat_tag = ctk.CTkLabel(
            right, text="📈 Forex: ICT / Smart Money / Price Action",
            font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self._lbl_strat_tag.pack(anchor="w", pady=(2, 0))

        # ── Min confidence slider ────────────────────────────────────
        conf_row = ctk.CTkFrame(right, fg_color="transparent")
        conf_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(conf_row, text="Min Confidence:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(0, 8))
        self._lbl_conf_val = ctk.CTkLabel(conf_row, text="70%",
                                           font=SF.MONO_SM(),
                                           text_color=Colors.NEUTRAL, width=s(40))
        self._lbl_conf_val.pack(side="right")
        self._conf_slider = ctk.CTkSlider(
            conf_row, from_=50, to=95, number_of_steps=9,
            progress_color=Colors.PRIMARY, button_color=Colors.PRIMARY,
            button_hover_color=Colors.PRIMARY_HOVER,
            command=self._on_conf_slider)
        self._conf_slider.set(70)
        self._conf_slider.pack(side="left", fill="x", expand=True)

    def _on_conf_slider(self, value):
        v = int(round(value / 5) * 5)
        self._lbl_conf_val.configure(text=f"{v}%")

    def _switch_strat_tab(self, tab: str):
        """Switch strategy panel between 'forex' and 'crypto'."""
        self._strat_tab = tab
        if tab == "forex":
            self._crypto_grid.pack_forget()
            self._forex_grid.pack(fill="x")
            self._btn_tab_forex.configure(
                fg_color=Colors.CYAN, text_color="#002030",
                font=SF.STATUS_BOLD())
            self._btn_tab_crypto.configure(
                fg_color=Colors.CARD_BG_ALT, text_color=Colors.TEXT_SECONDARY,
                font=SF.STATUS_BOLD())
            self._lbl_strat_tag.configure(
                text="📈 Forex: ICT / Smart Money / Price Action / Scalp / Swing")
        else:
            self._forex_grid.pack_forget()
            self._crypto_grid.pack(fill="x")
            self._btn_tab_crypto.configure(
                fg_color=Colors.NEUTRAL, text_color="#1A0800",
                font=SF.STATUS_BOLD())
            self._btn_tab_forex.configure(
                fg_color=Colors.CARD_BG_ALT, text_color=Colors.TEXT_SECONDARY,
                font=SF.STATUS_BOLD())
            self._lbl_strat_tag.configure(
                text="₿ Crypto: EMA / RSI / MACD / Bollinger / Volume / Wyckoff")

    def _strat_select_all(self):
        """Select all strategies in the currently active tab."""
        if self._strat_tab == "forex":
            keys = [s for s in ALL_STRATEGIES if not s.startswith("Crypto:")]
        else:
            keys = [s for s in ALL_STRATEGIES if s.startswith("Crypto:")]
        for k in keys:
            if k in self._strat_vars:
                self._strat_vars[k].set(True)

    def _strat_select_none(self):
        """Deselect all strategies in the currently active tab."""
        if self._strat_tab == "forex":
            keys = [s for s in ALL_STRATEGIES if not s.startswith("Crypto:")]
        else:
            keys = [s for s in ALL_STRATEGIES if s.startswith("Crypto:")]
        for k in keys:
            if k in self._strat_vars:
                self._strat_vars[k].set(False)

    # ── Progress bar ─────────────────────────────────────────────────────────
    def _build_progress(self):
        prog_frame = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                                   border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        prog_frame.grid(row=3, column=0, sticky="ew", padx=Spacing.LG(), pady=(0, 6))

        inner = ctk.CTkFrame(prog_frame, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=(8, 4))

        self._lbl_status = ctk.CTkLabel(
            inner,
            text="Select scan mode, markets and click ▶ Scan Markets.",
            font=SF.PILL(), text_color=Colors.TEXT_MUTED)
        self._lbl_status.pack(side="left")

        self._lbl_signal_count = ctk.CTkLabel(
            inner, text="", font=SF.PILL_LG(), text_color=Colors.BUY)
        self._lbl_signal_count.pack(side="right", padx=12)

        self._lbl_eta = ctk.CTkLabel(inner, text="", font=SF.MONO_TINY(), text_color=Colors.TEXT_MUTED)
        self._lbl_eta.pack(side="right")

        self._progress = ctk.CTkProgressBar(
            prog_frame, height=6,
            progress_color=Colors.PRIMARY, fg_color=Colors.WELL_BG, corner_radius=3)
        self._progress.set(0)
        self._progress.pack(fill="x", padx=12, pady=(0, 8))

    # ── Results table ─────────────────────────────────────────────────────────
    def _build_table(self):
        outer = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                              border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        outer.grid(row=4, column=0, sticky="nsew", padx=Spacing.LG(), pady=(0, Spacing.LG()))
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        # Column header row
        hdr_row = ctk.CTkFrame(outer, fg_color=Colors.SIDEBAR_BG, height=S.BTN_H(), corner_radius=0)
        hdr_row.grid(row=0, column=0, sticky="ew")
        hdr_row.pack_propagate(False)
        cols = [(3,"ASSET"),(2,"DIR"),(2,"TF"),(3,"ENTRY"),(3,"SL"),(3,"TP1"),(2,"CONF"),(2,"TIME"),(2,"R:R"),(2,"EXPLAIN"),(2,"ACTION")]
        for i, (w, label) in enumerate(cols):
            hdr_row.grid_columnconfigure(i, weight=w)
            ctk.CTkLabel(hdr_row, text=label, font=SF.STATUS_BOLD(),
                         text_color=Colors.LABEL, anchor="center").grid(row=0, column=i, sticky="ew", padx=6, pady=6)

        self._scroll = ctk.CTkScrollableFrame(
            outer, fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY)
        self._scroll.grid(row=1, column=0, sticky="nsew")
        bind_fast_scroll(self._scroll)

        ctk.CTkLabel(
            self._scroll,
            text="Select scan mode, markets and strategies above,\n"
                 "then click ▶ Scan Markets to begin.\n\n"
                 "Scalp modes will generate more frequent signals on lower timeframes.",
            font=SF.NORMAL(), text_color=Colors.TEXT_MUTED,
            justify="center").pack(pady=60)

    # ── Scan controls ─────────────────────────────────────────────────────────
    def _get_selected_symbols(self) -> list[str]:
        symbols, seen = [], set()
        for cat, var in self._cat_vars.items():
            if var.get():
                for s in MARKET_CATEGORIES[cat]:
                    if s not in seen:
                        symbols.append(s)
                        seen.add(s)
        return symbols

    def _get_selected_strategies(self) -> set[str]:
        """Return set of enabled strategy names from whichever tabs have any enabled."""
        return {k for k, v in self._strat_vars.items() if v.get()}

    def _auto_switch_tab_for_symbols(self, symbols: list[str]):
        """Auto-switch strategy tab based on which market categories are selected."""
        has_crypto = any(
            s for s in symbols
            if not ("/" in s or s in ("US30", "NAS100", "SPX500",
                                       "XAU/USD", "XAG/USD"))
        )
        has_forex = any("/" in s or s in ("US30", "NAS100", "SPX500",
                                            "XAU/USD", "XAG/USD") for s in symbols)
        if has_crypto and not has_forex:
            self._switch_strat_tab("crypto")
        elif has_forex and not has_crypto:
            self._switch_strat_tab("forex")
        # Mixed: keep current tab

    def _get_min_confidence(self) -> int:
        return int(round(self._conf_slider.get() / 5) * 5)

    def _start_scan(self):
        symbols = self._get_selected_symbols()
        mode    = self._mode_var.get()

        if not symbols:
            self._lbl_status.configure(
                text="⚠ Please select at least one market category.", text_color=Colors.NEUTRAL)
            return
        # Cleanup any finished thread
        if self._scan_thread and self._scan_thread.is_alive():
            self._lbl_status.configure(
                text="⚠ Scan already running — click ■ Stop first.",
                text_color=Colors.NEUTRAL)
            return
        self._scan_thread = None   # clear reference to dead thread

        # Auto-switch strategy tab to match selected markets
        self._auto_switch_tab_for_symbols(symbols)

        # Warn if signal engine not connected (but still allow scan to run)
        if not self._signal_engine:
            self._lbl_status.configure(
                text="⚠ Signal engine not connected — connect MT5 or TradingView first.",
                text_color=Colors.SELL)
            return

        self._stop_scan = False
        self._paused    = False
        self._results.clear()
        self._seen_signals.clear()
        self._btn_scan.configure(state="disabled")
        self._btn_pause.configure(state="normal")
        self._btn_stop.configure(state="normal")
        self._progress.set(0)
        self._clear_table()
        self._lbl_signal_count.configure(text="")

        icon, desc, _ = _MODE_INFO.get(mode, ("📊", mode, ""))
        self._lbl_status.configure(
            text=f"Starting {icon} {mode} scan across {len(symbols)} markets…",
            text_color=Colors.TEXT_MUTED)

        self._scan_thread = threading.Thread(
            target=self._scan_worker, args=(symbols, mode),
            daemon=True, name="manual-scanner")
        self._scan_thread.start()

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._btn_pause.configure(text="▶ Resume")
            self._lbl_status.configure(text="⏸ Scan paused.", text_color=Colors.NEUTRAL)
        else:
            self._btn_pause.configure(text="⏸ Pause")
            self._lbl_status.configure(text="Resuming…", text_color=Colors.TEXT_MUTED)

    def destroy(self):
        self._destroyed = True
        self._stop_scan = True
        try:
            super().destroy()
        except Exception:
            pass

    def _safe_after(self, delay, func, *args):
        """Thread-safe self.after() — no-op if widget destroyed."""
        if self._destroyed:
            return
        try:
            if self.winfo_exists():
                self.after(delay, func, *args)
        except Exception:
            pass

    def _stop_scan_fn(self):
        self._stop_scan = True
        self._paused    = False
        self._btn_scan.configure(state="normal")
        self._btn_pause.configure(state="disabled", text="⏸ Pause")
        self._btn_stop.configure(state="disabled")

    def _refresh_results(self):
        with self._lock:
            results = list(self._results)
        self._safe_after(0, self._render_results, results)

    # ── Background scan worker ────────────────────────────────────────────────
    def _scan_worker(self, symbols: list[str], mode: str):
        total            = len(symbols)
        found: list[Signal] = []
        start_time       = time.time()
        min_conf         = self._get_min_confidence()
        # Snapshot selected strategies once at scan start (thread-safe read of BooleanVars)
        active_strategies: set[str] = self._get_selected_strategies()

        for i, symbol in enumerate(symbols):
            if self._stop_scan or self._destroyed:
                break
            while self._paused and not self._stop_scan and not self._destroyed:
                time.sleep(0.2)

            pct     = i / total
            elapsed = time.time() - start_time
            eta     = (elapsed / (i + 1)) * (total - i - 1) if i > 0 else 0
            eta_str = f"ETA: {int(eta)}s" if eta > 0 else ""
            self._safe_after(0, self._update_progress, pct, i + 1, total, symbol, eta_str, mode)

            try:
                if self._signal_engine:
                    signal = self._signal_engine.analyze_with_mode(symbol, mode)
                    if signal is not None and signal.confidence >= min_conf:
                        # ── Strategy filter: only accept signals whose strategy
                        #    is checked in the active strategy tab ─────────────
                        sig_strategy = getattr(signal, "strategy", "") or ""
                        # Strategy filter: if no strategies selected, accept all
                        if active_strategies:
                            match = any(
                                sig_strategy.startswith(s) or s in sig_strategy
                                or s.replace("Crypto: ", "") in sig_strategy
                                or not sig_strategy   # no strategy tag = accept
                                for s in active_strategies
                            )
                            if not match:
                                continue
                        # ─────────────────────────────────────────────────────
                        now  = time.time()
                        prev = self._seen_signals.get(symbol)
                        cooldown = 60 if ("Scalp" in mode or "Micro" in mode) else _SIGNAL_COOLDOWN_SECONDS
                        if prev is None or prev[0] != signal.direction or (now - prev[1]) > cooldown:
                            self._seen_signals[symbol] = (signal.direction, now)
                            found.append(signal)
                            with self._lock:
                                self._results = list(found)
                            self._safe_after(0, self._render_results, list(found))
            except Exception as e:
                from utils.logger import get_logger
                get_logger("ManualScanner").warning(f"[{mode}] {symbol}: {type(e).__name__}: {e}")

            # shorter delay for scalp modes (they need speed)
            delay = 0.2 if ("Scalp" in mode or "Micro" in mode) else 0.5
            time.sleep(delay)

        self._safe_after(0, self._on_scan_complete, found, mode)

    def _update_progress(self, pct, done, total, symbol, eta, mode):
        self._progress.set(pct)
        icon = _MODE_INFO.get(mode, ("📊",))[0]
        self._lbl_status.configure(
            text=f"{icon} [{mode}]  Scanning {symbol}…  ({done}/{total})",
            text_color=Colors.TEXT_MUTED)
        self._lbl_eta.configure(text=eta)
        n = len(self._results)
        if n > 0:
            self._lbl_signal_count.configure(text=f"  {n} signal{'s' if n != 1 else ''} found  ")

    def _on_scan_complete(self, signals: list, mode: str):
        self._progress.set(1.0)
        n    = len(signals)
        icon = _MODE_INFO.get(mode, ("📊",))[0]
        self._lbl_status.configure(
            text=f"✓ {icon} [{mode}] complete — {n} signal{'s' if n != 1 else ''} found.",
            text_color=Colors.BUY if n > 0 else Colors.TEXT_MUTED)
        self._lbl_eta.configure(text="")
        self._lbl_signal_count.configure(text=f"  {n} signal{'s' if n != 1 else ''}  " if n > 0 else "")
        self._btn_scan.configure(state="normal")
        self._btn_pause.configure(state="disabled", text="⏸ Pause")
        self._btn_stop.configure(state="disabled")
        self._render_results(signals)

    # ── Table rendering ───────────────────────────────────────────────────────
    def _clear_table(self):
        for w in self._scroll.winfo_children():
            w.destroy()

    def _render_results(self, signals: list):
        self._clear_table()
        if not signals:
            ctk.CTkLabel(
                self._scroll,
                text="No qualifying signals found.\n\n"
                     "Try a scalp mode for more signals, or select more markets.",
                font=SF.NORMAL(), text_color=Colors.TEXT_MUTED,
                justify="center").pack(pady=60)
            return
        # Sort: confidence descending
        for i, sig in enumerate(sorted(signals, key=lambda s: s.confidence, reverse=True)):
            _SignalRow(self._scroll, sig, i,
                       on_explain=self._open_explain,
                       on_apply_algo=self._apply_to_algo,
                       on_auto_ai=self._direct_apply_auto_ai)

    def _open_explain(self, signal: Signal):
        try:
            _ExplainModal(self.winfo_toplevel(), signal)
        except Exception as e:
            from utils.logger import get_logger
            get_logger("ManualScanner").warning(f"explain modal: {type(e).__name__}: {e}")

    def _direct_apply_auto_ai(self, signal: Signal):
        """Instantly send signal to the paper trading engine (no dialog).
        Uses TP/SL exit mode only — same as the auto AI scanner would do."""
        try:
            if self._on_auto_ai_apply:
                self._on_auto_ai_apply(signal, max_duration_minutes=0.0)
            elif self._on_apply_to_algo:
                # Fallback: use algo callback with no timer
                self._on_apply_to_algo(signal, max_duration_minutes=0.0)
        except Exception as e:
            from utils.logger import logger
            logger.warning(f"[ManualScanner._direct_apply_auto_ai] {type(e).__name__}: {e}")

    def _apply_to_algo(self, signal: Signal):
        """Show a timer picker, then open the paper trade with optional auto-exit."""
        self._show_apply_dialog(signal)

    def _show_apply_dialog(self, signal: Signal):
        """Modal to choose exit mode: TP/SL only, or scalp timer."""
        dlg = ctk.CTkToplevel(self)
        dlg.configure(fg_color=Colors.APP_BG)
        make_dialog(dlg, self.winfo_toplevel(),
                    title=f"Apply to Algo — {signal.symbol} {signal.direction}",
                    size=(440, 360))

        dir_color = Colors.BUY if signal.direction == "BUY" else Colors.SELL

        # Header
        hdr = ctk.CTkFrame(dlg, fg_color=Colors.SIDEBAR_BG,
                            border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        hdr.pack(fill="x", padx=16, pady=(16, 10))
        hdr_inner = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_inner.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(hdr_inner, text=signal.symbol, font=SF.SUBHEADER(),
                     text_color=Colors.TEXT).pack(side="left")
        ctk.CTkLabel(hdr_inner, text=f" {signal.direction} ",
                     font=SF.MONO(),
                     text_color=(Colors.ON_BUY if signal.direction == "BUY" else Colors.ON_SELL),
                     fg_color=dir_color, corner_radius=s(6)).pack(side="left", padx=8)
        ctk.CTkLabel(hdr_inner, text=f"{signal.confidence}%  ·  {signal.trade_type}",
                     font=SF.MONO_SM(), text_color=Colors.NEUTRAL).pack(side="right")

        # Levels
        lvl = ctk.CTkFrame(dlg, fg_color=Colors.CARD_BG,
                            border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        lvl.pack(fill="x", padx=16, pady=(0, 10))
        for i in range(4):
            lvl.grid_columnconfigure(i, weight=1)
        for col, (label, val, color) in enumerate([
            ("ENTRY",     f"{signal.entry_price:.5f}",   Colors.TEXT),
            ("STOP LOSS", f"{signal.stop_loss:.5f}",     Colors.SELL),
            ("TP 1",      f"{signal.take_profit_1:.5f}", Colors.BUY),
            ("R:R",       f"1:{signal.risk_reward:.1f}", Colors.NEUTRAL),
        ]):
            ctk.CTkLabel(lvl, text=label, font=SF.TINY(), text_color=Colors.LABEL).grid(
                row=0, column=col, pady=(8, 0), padx=8)
            ctk.CTkLabel(lvl, text=val, font=SF.MONO_SM(), text_color=color).grid(
                row=1, column=col, pady=(0, 8), padx=8)

        # Exit mode selector
        ctk.CTkLabel(dlg, text="AUTO-EXIT MODE", font=SF.PILL_LG(),
                     text_color=Colors.LABEL).pack(anchor="w", padx=16, pady=(4, 6))

        mode_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        mode_frame.pack(fill="x", padx=16, pady=(0, 6))

        DURATION_OPTIONS = [
            (0,    "TP / SL only",       Colors.TEXT_MUTED, "Standard: closes when TP or SL is hit"),
            (5,    "⏱ 5 min scalp",      Colors.NEUTRAL,    "Auto-close in 5 min at market price"),
            (10,   "⏱ 10 min scalp",     Colors.NEUTRAL,    "Auto-close in 10 min at market price"),
            (15,   "⏱ 15 min scalp",     Colors.NEUTRAL,    "Auto-close in 15 min at market price"),
            (30,   "⏱ 30 min scalp",     Colors.BUY,        "Auto-close in 30 min at market price"),
            (60,   "⏱ 1 hour",           Colors.BUY,        "Auto-close in 60 min at market price"),
        ]

        selected_duration = ctk.IntVar(value=0)
        dur_btns = {}
        desc_lbl = ctk.CTkLabel(dlg, text=DURATION_OPTIONS[0][3], font=SF.TINY(),
                                 text_color=Colors.TEXT_MUTED, wraplength=s(400))
        desc_lbl.pack(anchor="w", padx=16, pady=(0, 2))

        def _select_dur(mins, desc):
            selected_duration.set(mins)
            desc_lbl.configure(text=desc)
            for m, btn in dur_btns.items():
                if m == mins:
                    btn.configure(fg_color=Colors.PRIMARY, text_color=Colors.ON_BUY,
                                  border_width=2, border_color=Colors.TEXT)
                else:
                    btn.configure(fg_color=Colors.CARD_BG_ALT, text_color=Colors.TEXT_SECONDARY,
                                  border_width=0)

        for i, (mins, label, color, desc) in enumerate(DURATION_OPTIONS):
            btn = ctk.CTkButton(
                mode_frame, text=label, width=118, height=34, corner_radius=s(8),
                fg_color=Colors.CARD_BG_ALT if mins != 0 else Colors.PRIMARY,
                hover_color=Colors.HOVER_STRONG,
                text_color=Colors.ON_BUY if mins == 0 else Colors.TEXT_SECONDARY,
                border_width=2 if mins == 0 else 0,
                border_color=Colors.TEXT if mins == 0 else Colors.BORDER,
                font=SF.STATUS_BOLD(),
                command=lambda m=mins, d=desc: _select_dur(m, d),
            )
            btn.pack(side="left", padx=2)
            dur_btns[mins] = btn

        # Status label for feedback
        status_lbl = ctk.CTkLabel(dlg, text="", font=SF.TINY(), text_color=Colors.BUY)
        status_lbl.pack(anchor="w", padx=16, pady=(4, 0))

        # Confirm button
        def _confirm():
            dur = selected_duration.get()
            if self._on_apply_to_algo:
                self._on_apply_to_algo(signal, max_duration_minutes=float(dur))
            timer_note = f" — exits in {dur} min" if dur > 0 else ""
            status_lbl.configure(
                text=f"✅ {signal.symbol} {signal.direction} paper trade opened{timer_note}",
                text_color=Colors.BUY)
            self._lbl_status.configure(
                text=f"✅ {signal.symbol} {signal.direction} applied to Algo Trading{timer_note}.",
                text_color=Colors.BUY)
            dlg.after(1200, dlg.destroy)

        ctk.CTkButton(
            dlg, text="▶  Open Paper Trade", height=S.ROW_H(), corner_radius=s(8),
            fg_color=Colors.BUY, hover_color=Colors.BUY_HOVER,
            text_color=Colors.ON_BUY, font=SF.SUBHEADER(),
            command=_confirm,
        ).pack(fill="x", padx=16, pady=(8, 16))
