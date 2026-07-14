"""
ui/market_scanner_page.py
==========================
Dedicated Market Scanner Page — Bloomberg-style AI signal board.

Features:
  • Confidence slider filter (≥70% to 100%)
  • Pause / Resume auto-scanner controls
  • Live progress bar showing scan progress + ETA
  • Refresh button with loading indicator
  • Apply to Algo Trading button per signal
  • AI Signal Explanation with strategy/indicator breakdown
  • Duplicate-filtered, cooldown-aware signal list
  • Stats: scanning count, active, BUY, SELL, high-confidence
"""
from __future__ import annotations
import time
import queue
import threading
import customtkinter as ctk
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing


# ─── Binance Public API — crypto live prices ─────────────────────────────────
# Uses Binance's public REST API (no auth required) to fetch real-time prices
# for crypto pairs. Falls back to local data if unavailable.
import json as _json
try:
    from urllib.request import urlopen as _urlopen
    from urllib.error   import URLError as _URLError
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

# Popular USDT pairs that are always available on Binance public API
_BINANCE_USDT_PAIRS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
    "AVAXUSDT","MATICUSDT","DOTUSDT","LINKUSDT","LTCUSDT","UNIUSDT","ATOMUSDT",
    "TRXUSDT","SHIBUSDT","BCHUSDT","APTUSDT","ARBUSDT","FILUSDT",
    "INJUSDT","SUIUSDT","NEARUSDT","FTMUSDT","ALGOUSDT","VETUSDT",
    "SANDUSDT","MANAUSDT","AXSUSDT","GALAUSDT","CRVUSDT","AAVEUSDT",
    "SNXUSDT","MKRUSDT","COMPUSDT","LDOUSDT","RUNEUSDT","HBARUSDT",
    "ENJUSDT","CHZUSDT","BATUSDT","TONUSDT","OPUSDT",
]

_binance_price_cache: dict[str, float] = {}
_binance_cache_time: float = 0.0
_BINANCE_CACHE_TTL = 5.0   # seconds

def _fetch_binance_prices() -> dict[str, float]:
    """Fetch all ticker prices from Binance in one HTTP call (public, no auth)."""
    global _binance_price_cache, _binance_cache_time
    import time as _time
    now = _time.time()
    if now - _binance_cache_time < _BINANCE_CACHE_TTL and _binance_price_cache:
        return _binance_price_cache
    if not _HAS_URLLIB:
        return {}
    try:
        from urllib.request import Request as _Request
        _req = _Request(
            "https://api.binance.com/api/v3/ticker/price",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with _urlopen(_req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        prices = {item["symbol"]: float(item["price"]) for item in data}
        _binance_price_cache = prices
        _binance_cache_time  = now
        return prices
    except Exception:
        return _binance_price_cache   # return stale on error

def get_binance_price(symbol: str) -> float | None:
    """Get live Binance price for a crypto symbol like BTC or BTCUSDT."""
    sym = symbol.upper().replace("/", "")
    if not sym.endswith("USDT"):
        sym = sym + "USDT"
    prices = _fetch_binance_prices()
    return prices.get(sym)

def get_binance_usdt_pairs() -> list[str]:
    """Return a display list of Binance pairs with live prices available."""
    prices = _fetch_binance_prices()
    if not prices:
        return _BINANCE_USDT_PAIRS
    return [s for s in _BINANCE_USDT_PAIRS if s in prices]


# ─── Full symbol list for auto scanner (supplements MT5 service symbols) ──────
_AUTO_SCAN_FOREX = [
    "EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","USD/CHF","NZD/USD",
    "EUR/GBP","EUR/JPY","GBP/JPY","EUR/AUD","EUR/CAD","AUD/JPY","GBP/AUD",
    "GBP/CAD","CAD/JPY","NZD/JPY","CHF/JPY","EUR/NZD","EUR/CHF","GBP/CHF",
    "GBP/NZD","AUD/NZD","AUD/CAD","AUD/CHF","NZD/CAD","NZD/CHF",
    "USD/MXN","USD/ZAR","USD/NOK","USD/SEK","USD/TRY",
    "XAU/USD","XAG/USD","US30","NAS100","SPX500",
]
_AUTO_SCAN_CRYPTO = [
    "BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","MATIC","DOT",
    "LINK","LTC","UNI","ATOM","TRX","TON","BCH","APT","ARB","OP",
    "INJ","SUI","SEI","NEAR","FTM","ALGO","VET","AAVE","MKR","LDO",
    "RUNE","HBAR","ENJ","CHZ","BAT","SAND","MANA","AXS","GALA","CRV",
]
_ALL_AUTO_SYMBOLS = _AUTO_SCAN_FOREX + _AUTO_SCAN_CRYPTO   # 75 symbols total
CONFIDENCE_FLOOR_DEFAULT = 85
CONFIDENCE_FLOOR_MIN     = 70
CONFIDENCE_FLOOR_MAX     = 100
REFRESH_MS = 5_000

_STRATEGY_KEYWORDS = [
    ("EMA", "EMA"), ("SMA", "SMA"), ("RSI", "RSI"), ("MACD", "MACD"),
    ("ADX", "ADX"), ("ATR", "ATR"), ("Bollinger", "BB"),
    ("Order Block", "OB"), ("Fair Value Gap", "FVG"), ("Liquidity", "LIQ"),
    ("Break of Structure", "BOS"), ("Change of Character", "CHoCH"),
    ("Smart Money", "SMC"), ("ICT", "ICT"), ("Momentum", "MOM"),
    ("Volume", "VOL"), ("Support", "S/R"), ("Resistance", "S/R"),
    ("Trend", "TREND"), ("Swing", "SWING"), ("Scalp", "SCALP"),
]


def _extract_strategies(reasons: list[str]) -> list[str]:
    found, seen = [], set()
    for reason in (reasons or []):
        for kw, label in _STRATEGY_KEYWORDS:
            if kw.lower() in reason.lower() and label not in seen:
                found.append(label)
                seen.add(label)
    return found or ["—"]


def _expiry_str(expires_at: float | None) -> str:
    if not expires_at:
        return "—"
    remaining = expires_at - time.time()
    if remaining <= 0:
        return "EXPIRED"
    m, s = divmod(int(remaining), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h else f"{m}m {s}s"


def _rr_str(signal) -> str:
    try:
        return f"1:{signal.risk_reward:.2f}"
    except Exception:
        return "—"


# ─── Signal card ─────────────────────────────────────────────────────────────
class _ScannerCard(ctk.CTkFrame):
    def __init__(self, parent, signal, on_detail=None, on_apply_algo=None):
        super().__init__(parent, fg_color=Colors.CARD_BG,
                          border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        self._destroyed = False
        self.pack(fill="x", padx=6, pady=4)
        self._signal = signal

        is_buy  = signal.direction == "BUY"
        dir_bg  = Colors.BUY  if is_buy else Colors.SELL
        dir_fg  = Colors.ON_BUY if is_buy else Colors.ON_SELL
        dir_arr = "▲" if is_buy else "▼"

        conf = signal.confidence
        if conf >= 95:
            conf_color = Colors.BUY
        elif conf >= 90:
            conf_color = "#00E5A0"
        else:
            conf_color = Colors.NEUTRAL

        # Row 1: symbol | direction | confidence | expiry
        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(r1, text=signal.symbol, font=SF.SUBHEADER(),
                     text_color=Colors.TEXT).pack(side="left")
        ctk.CTkLabel(r1, text=f"  {dir_arr} {signal.direction}",
                     font=SF.SUBHEADER(), text_color=dir_bg).pack(side="left", padx=6)
        ctk.CTkLabel(r1, text=f"{conf}%  {signal.strength}",
                     font=SF.MONO(), text_color=conf_color).pack(side="left", padx=12)

        self._lbl_expiry = ctk.CTkLabel(r1, text="⏱ —", font=SF.TINY(),
                                         text_color=Colors.TEXT_MUTED)
        self._lbl_expiry.pack(side="right")

        for badge_txt in [signal.trade_type, signal.setup_timeframe, signal.session[:12]]:
            ctk.CTkLabel(r1, text=f" {badge_txt} ", font=SF.TINY(),
                          text_color=Colors.TEXT_MUTED, fg_color=Colors.WELL_BG,
                          corner_radius=3, padx=4, pady=1).pack(side="right", padx=2)

        # Confidence bar
        bar_bg = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, height=4, corner_radius=2)
        bar_bg.pack(fill="x", padx=12, pady=(0, 6))
        bar_bg.pack_propagate(False)
        ctk.CTkFrame(bar_bg, fg_color=conf_color, height=4, corner_radius=2,
                     width=0).place(relx=0, rely=0, relwidth=min(1.0, conf / 100), relheight=1)

        # Row 2: trade levels
        lvl = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, corner_radius=s(6))
        lvl.pack(fill="x", padx=12, pady=(0, 6))
        for col, weight in enumerate((3, 3, 3, 3, 3)):
            lvl.grid_columnconfigure(col, weight=weight)

        def _cell(col, title, value, val_color=Colors.TEXT):
            ctk.CTkLabel(lvl, text=title, font=SF.STATUS_BOLD(),
                          text_color=Colors.LABEL).grid(row=0, column=col, pady=(6, 0), padx=6)
            ctk.CTkLabel(lvl, text=value, font=SF.MONO_SM(),
                          text_color=val_color).grid(row=1, column=col, pady=(0, 6), padx=6)

        def _fp(v):
            return f"{v:,.4f}" if v else "—"

        _cell(0, "ENTRY",     _fp(signal.entry_price))
        _cell(1, "STOP LOSS", _fp(signal.stop_loss),   Colors.SELL)
        _cell(2, "TP 1",      _fp(signal.take_profit_1), Colors.BUY)
        _cell(3, "TP 2",      _fp(getattr(signal, "take_profit_2", 0)), Colors.BUY)
        _cell(4, "R:R",       _rr_str(signal), Colors.NEUTRAL)

        # Row 3: strategies + buttons
        r3 = ctk.CTkFrame(self, fg_color="transparent")
        r3.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkLabel(r3, text="Strategies:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(0, 4))

        strategies = _extract_strategies(signal.reasons)
        for strat in strategies[:8]:
            ctk.CTkLabel(r3, text=strat, font=SF.STATUS_BOLD(),
                          text_color=Colors.TEXT_SECONDARY,
                          fg_color=Colors.SIDEBAR_BG, corner_radius=s(4),
                          padx=5, pady=1).pack(side="left", padx=2)

        # Apply to Algo button
        if on_apply_algo:
            ctk.CTkButton(r3, text="→ Apply to Algo", width=S.BTN_W_MD(), height=S.ICON_BTN(),
                          corner_radius=s(5), fg_color=Colors.PRIMARY,
                          hover_color=Colors.PRIMARY_HOVER,
                          text_color=Colors.ON_BUY, font=SF.STATUS_BOLD(),
                          command=lambda s=signal: on_apply_algo(s)).pack(side="right", padx=2)

        if on_detail:
            ctk.CTkButton(r3, text="Full Analysis", width=s(100), height=S.ICON_BTN(),
                          corner_radius=s(5), fg_color=Colors.CARD_BG_ALT,
                          hover_color=Colors.HOVER, text_color=Colors.BUY,
                          font=SF.STATUS_BOLD(),
                          command=lambda s=signal: on_detail(s)).pack(side="right")

    def refresh_expiry(self, expires_at: float | None):
        try:
            self._lbl_expiry.configure(text=f"⏱ {_expiry_str(expires_at)}")
        except Exception:
            pass


# ─── Main page ────────────────────────────────────────────────────────────────
class MarketScannerPage(ctk.CTkFrame):
    def __init__(self, parent, market_scanner=None, get_account_context=None,
                 on_apply_to_algo=None, signal_engine=None):
        super().__init__(parent, fg_color=Colors.APP_BG, corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self._destroyed         = False
        self._scanner           = market_scanner
        self._signal_engine     = signal_engine   # ← used for crypto scanning
        self._get_account_ctx   = get_account_context
        self._on_apply_to_algo  = on_apply_to_algo
        self._lock = threading.Lock()
        self._result_queue      = __import__('queue').Queue(maxsize=2)   # panel-level (was on _ScannerCard by mistake)
        self._current_signals   = []
        self._cards:  list      = []
        self._stop_expiry       = False
        self._confidence_floor  = CONFIDENCE_FLOOR_DEFAULT
        self._is_refreshing     = False

        # ── Crypto scanner state ──────────────────────────────────────
        self._crypto_signals:   list  = []          # signals from crypto scan
        self._crypto_scanning:  bool  = False        # bg thread active
        self._crypto_stop:      bool  = False        # stop flag
        self._crypto_lock             = threading.Lock()
        self._crypto_enabled:   bool  = False        # toggled by user
        self._crypto_min_conf:  int   = 80
        # Crypto symbols to scan (top liquid coins MT5 brokers usually carry)
        self._CRYPTO_SCAN_SYMBOLS = _ALL_AUTO_SYMBOLS   # 75 forex+crypto symbols

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(), pady=(Spacing.LG(), 6))

        ctk.CTkLabel(hdr, text="AUTO MARKET SCANNER", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")

        # Confidence slider
        slider_frame = ctk.CTkFrame(hdr, fg_color=Colors.CARD_BG,
                                     corner_radius=s(6), border_width=1, border_color=Colors.BORDER)
        slider_frame.pack(side="left", padx=10)

        ctk.CTkLabel(slider_frame, text="Min Conf:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(8, 2), pady=6)

        self._lbl_conf_badge = ctk.CTkLabel(
            slider_frame, text=f"≥{self._confidence_floor}%",
            font=SF.PILL_LG(), text_color=Colors.ON_BUY,
            fg_color=Colors.PRIMARY, corner_radius=s(5), padx=6, pady=2)
        self._lbl_conf_badge.pack(side="left", padx=4, pady=6)

        self._conf_slider = ctk.CTkSlider(
            slider_frame, from_=CONFIDENCE_FLOOR_MIN, to=CONFIDENCE_FLOOR_MAX,
            number_of_steps=CONFIDENCE_FLOOR_MAX - CONFIDENCE_FLOOR_MIN,
            width=s(130), height=16,
            button_color=Colors.PRIMARY, button_hover_color=Colors.BUY,
            progress_color=Colors.PRIMARY, fg_color=Colors.WELL_BG,
            command=self._on_conf_slider)
        self._conf_slider.set(self._confidence_floor)
        self._conf_slider.pack(side="left", padx=(2, 8), pady=6)

        self._lbl_active = ctk.CTkLabel(hdr, text="— signals", font=SF.MONO(),
                                         text_color=Colors.TEXT_MUTED)
        self._lbl_active.pack(side="left", padx=8)

        # Right controls: Pause/Resume + Refresh
        ctrl = ctk.CTkFrame(hdr, fg_color="transparent")
        ctrl.pack(side="right")

        self._btn_pause = ctk.CTkButton(
            ctrl, text="⏸ Pause", width=s(80), height=S.BTN_H(), corner_radius=s(6),
            fg_color=Colors.NEUTRAL, hover_color=Colors.HOVER_STRONG,
            text_color=Colors.TEXT, font=SF.PILL_LG(),
            command=self._toggle_pause)
        self._btn_pause.pack(side="left", padx=(0, 6))

        self._btn_refresh = ctk.CTkButton(
            ctrl, text="⟳ Refresh", width=s(90), height=S.BTN_H(), corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=self._manual_refresh)
        self._btn_refresh.pack(side="left", padx=(0, 6))

        # ── Crypto scan toggle button ─────────────────────────────────
        self._btn_crypto = ctk.CTkButton(
            ctrl, text="+ Scan All Markets", width=s(140), height=S.BTN_H(), corner_radius=s(6),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER_STRONG,
            text_color=Colors.TEXT_MUTED, font=SF.PILL_LG(),
            command=self._toggle_crypto_scan)
        self._btn_crypto.pack(side="left", padx=(0, 0))

        self._lbl_status = ctk.CTkLabel(hdr, text="", font=SF.TINY(),
                                         text_color=Colors.TEXT_MUTED)
        self._lbl_status.pack(side="right", padx=8)

        # ── Progress bar ──────────────────────────────────────────────
        prog_outer = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                                   border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        prog_outer.grid(row=2, column=0, sticky="ew", padx=Spacing.LG(), pady=(0, 6))

        prog_row = ctk.CTkFrame(prog_outer, fg_color="transparent")
        prog_row.pack(fill="x", padx=12, pady=(6, 2))
        self._lbl_prog_text = ctk.CTkLabel(prog_row, text="Scanning markets…",
                                            font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self._lbl_prog_text.pack(side="left")
        self._lbl_eta = ctk.CTkLabel(prog_row, text="", font=SF.MONO_TINY(),
                                      text_color=Colors.TEXT_MUTED)
        self._lbl_eta.pack(side="right")

        self._progress_bar = ctk.CTkProgressBar(prog_outer, height=4,
                                                  progress_color=Colors.PRIMARY,
                                                  fg_color=Colors.WELL_BG, corner_radius=2)
        self._progress_bar.set(0)
        self._progress_bar.pack(fill="x", padx=12, pady=(0, 6))

        # ── Stats bar ─────────────────────────────────────────────────
        stats = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                              border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        stats.grid(row=3, column=0, sticky="ew", padx=Spacing.LG(), pady=(0, 6))

        self._stat_labels: dict[str, ctk.CTkLabel] = {}
        for col, (k, title) in enumerate([
            ("scanning", "Scanning"), ("active", "Active Signals"),
            ("buy", "BUY"), ("sell", "SELL"), ("high", "≥90% Conf"),
        ]):
            stats.grid_columnconfigure(col, weight=1)
            f = ctk.CTkFrame(stats, fg_color="transparent")
            f.grid(row=0, column=col, pady=10, padx=8, sticky="nsew")
            ctk.CTkLabel(f, text=title, font=SF.STATUS_BOLD(),
                          text_color=Colors.LABEL).pack()
            lbl = ctk.CTkLabel(f, text="—", font=SF.PRICE_SM(),
                                text_color=Colors.TEXT)
            lbl.pack()
            self._stat_labels[k] = lbl

        # ── Signal list ───────────────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY)
        self._scroll.grid(row=4, column=0, sticky="nsew",
                          padx=Spacing.LG(), pady=(0, Spacing.LG()))
        bind_fast_scroll(self._scroll)

        self._lbl_empty = ctk.CTkLabel(
            self._scroll,
            text="Scanning all markets…\n\nSignals will appear here when confidence ≥ "
                 f"{CONFIDENCE_FLOOR_DEFAULT}%.\nThe engine requires multiple independent confirmations "
                 "before generating a signal.\n\nUse the slider to lower the threshold if needed.",
            font=SF.NORMAL(),
            text_color=Colors.TEXT_MUTED, justify="center")
        self._lbl_empty.pack(pady=60)

        self._schedule_refresh()
        self._start_expiry_ticker()
        self._schedule_progress_update()
        self._build_binance_ticker()
        self._start_binance_ticker()
        self._schedule_crypto_merge()   # ← merge crypto signals into display every 3 s

    # ── Binance Live Ticker ──────────────────────────────────────────────────
    def _build_binance_ticker(self):
        """Horizontal live crypto price bar powered by Binance public API (no auth)."""
        # Add a new row for the Binance bar — sits below the signal grid header
        self.grid_rowconfigure(1, weight=0)   # Binance bar — fixed height

        bar = ctk.CTkFrame(self, fg_color=Colors.WELL_BG,
                            border_width=1, border_color=Colors.BORDER,
                            corner_radius=s(6), height=34)
        bar.grid(row=1, column=0, sticky="ew", padx=Spacing.LG(), pady=(0, 4))
        bar.grid_propagate(False)

        ctk.CTkLabel(bar, text="  ₿ BINANCE LIVE ",
                     font=SF.MONO_TINY(), text_color=Colors.NEUTRAL,
                     fg_color=Colors.CARD_BG_ALT, corner_radius=s(4),
                     padx=5, pady=2).pack(side="left", padx=(6, 4), pady=5)

        self._binance_ticker_inner = ctk.CTkFrame(bar, fg_color="transparent")
        self._binance_ticker_inner.pack(side="left", fill="both", expand=True, padx=4)

        self._lbl_binance_status = ctk.CTkLabel(
            bar, text="Connecting…", font=SF.STATUS(),
            text_color=Colors.TEXT_MUTED)
        self._lbl_binance_status.pack(side="right", padx=(4, 8))

        ctk.CTkButton(bar, text="⟳", width=26, height=s(22), corner_radius=s(4),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                      text_color=Colors.TEXT_MUTED, font=SF.PILL(),
                      command=self._trigger_binance_fetch).pack(side="right", padx=(0, 2), pady=5)

    def _start_binance_ticker(self):
        self._prev_binance_prices: dict[str, float] = {}
        import queue as _queue
        self._binance_queue: "_queue.Queue" = _queue.Queue(maxsize=2)
        self._trigger_binance_fetch()
        self._drain_binance_queue()

    def _trigger_binance_fetch(self):
        """Kick off a background thread to fetch Binance prices."""
        threading.Thread(target=self._bg_binance_fetch, daemon=True).start()

    def _bg_binance_fetch(self):
        """Background: fetch prices, push result into queue (never calls self.after directly)."""
        prices = _fetch_binance_prices()
        try:
            self._binance_queue.get_nowait()   # discard stale
        except Exception:
            pass
        try:
            self._binance_queue.put_nowait(prices)
        except Exception:
            pass

    def _drain_binance_queue(self):
        """Main-thread: poll the binance queue every 200 ms and apply updates."""
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
            prices = self._binance_queue.get_nowait()
            self._apply_binance_prices(prices)
        except Exception:
            pass
        # Schedule next fetch every 5 s (from main thread — safe)
        try:
            if not self._destroyed:
                self.after(5000, self._trigger_binance_fetch)
                self.after(200, self._drain_binance_queue)
        except RuntimeError:
            pass

    def _apply_binance_prices(self, prices: dict):
        """Main-thread: rebuild the ticker labels with latest prices."""
        if self._destroyed:
            return
        if not prices:
            self._lbl_binance_status.configure(
                text="⚠ Binance unreachable", text_color=Colors.SELL)
            return

        # Clear old labels
        for w in self._binance_ticker_inner.winfo_children():
            w.destroy()

        shown = 0
        for sym in _BINANCE_USDT_PAIRS[:30]:
            px = prices.get(sym)
            if px is None:
                continue
            prev = self._prev_binance_prices.get(sym, px)
            up   = px >= prev
            arrow = "▲" if up else "▼"
            color = Colors.BUY if up else Colors.SELL
            base  = sym.replace("USDT", "")
            px_fmt = f"${px:,.4f}" if px < 10 else (f"${px:,.2f}" if px < 1000 else f"${px:,.0f}")
            ctk.CTkLabel(
                self._binance_ticker_inner,
                text=f" {base} {arrow}{px_fmt} ",
                font=SF.MONO_TINY(),
                text_color=color,
            ).pack(side="left", padx=1)
            shown += 1

        # Update previous price cache
        for sym in _BINANCE_USDT_PAIRS:
            if sym in prices:
                self._prev_binance_prices[sym] = prices[sym]

        self._lbl_binance_status.configure(
            text=f"● {shown} pairs", text_color=Colors.BUY)

    # ══════════════════════════════════════════════════════════════════════
    # CRYPTO SCANNER — runs alongside the MT5 forex scanner
    # Uses the same signal_engine as Manual Scanner so signals are identical
    # quality. Runs in its own daemon thread, results merged into the main
    # signal list every 3 seconds. Never blocks the UI or MT5 pipeline.
    # ══════════════════════════════════════════════════════════════════════

    def _toggle_crypto_scan(self):
        """Turn the crypto scanner ON or OFF."""
        self._crypto_enabled = not self._crypto_enabled
        if self._crypto_enabled:
            self._btn_crypto.configure(
                text="● Scanning All Markets",
                fg_color=Colors.NEUTRAL,
                text_color="#1A0800",
            )
            self._crypto_stop = False
            self._start_crypto_scan_thread()
        else:
            self._btn_crypto.configure(
                text="+ Scan All Markets",
                fg_color=Colors.CARD_BG_ALT,
                text_color=Colors.TEXT_MUTED,
            )
            self._crypto_stop = True
            with self._crypto_lock:
                self._crypto_signals.clear()

    def _start_crypto_scan_thread(self):
        """Launch a background thread that scans crypto symbols continuously."""
        if self._crypto_scanning:
            return
        threading.Thread(target=self._crypto_scan_worker, daemon=True,
                         name="crypto-scanner").start()

    def _crypto_scan_worker(self):
        """Background: scan each crypto symbol with signal_engine, store results."""
        self._crypto_scanning = True
        try:
            while not self._crypto_stop and not self._destroyed:
                if not self._signal_engine:
                    import time as _t; _t.sleep(5); continue

                fresh: list = []
                for sym in self._CRYPTO_SCAN_SYMBOLS:
                    if self._crypto_stop or self._destroyed:
                        break
                    try:
                        # Use Intraday mode for crypto (good balance of speed + signal quality)
                        signal = self._signal_engine.analyze_with_mode(sym, "Intraday (4H/1H)")
                        if signal and signal.confidence >= self._crypto_min_conf:
                            fresh.append(signal)
                    except Exception:
                        pass
                    import time as _t; _t.sleep(0.3)   # small delay between coins

                if not self._crypto_stop:
                    with self._crypto_lock:
                        self._crypto_signals = list(fresh)

                # Rest 60 s before next full cycle (crypto doesn't need faster)
                import time as _t
                for _ in range(60):
                    if self._crypto_stop or self._destroyed:
                        break
                    _t.sleep(1)
        finally:
            self._crypto_scanning = False

    def _schedule_crypto_merge(self):
        """Main-thread: periodically merge crypto signals into the displayed list."""
        if self._destroyed:
            return
        self.after(3000, self._do_crypto_merge)

    def _do_crypto_merge(self):
        """Main-thread: rebuild visible signal list = forex signals + crypto signals."""
        if self._destroyed:
            return
        if self._crypto_enabled:
            with self._crypto_lock:
                crypto_sigs = list(self._crypto_signals)
            if crypto_sigs:
                # Merge: forex signals first, then crypto — deduplicated by symbol
                combined_syms = {s.symbol for s in self._current_signals}
                extra = [s for s in crypto_sigs if s.symbol not in combined_syms]
                if extra:
                    merged = list(self._current_signals) + extra
                    # Re-sort by confidence descending
                    merged.sort(key=lambda s: s.confidence, reverse=True)
                    self._render_signals(merged)
                    # Update stats bar
                    n      = len(merged)
                    n_buy  = sum(1 for s in merged if s.direction == "BUY")
                    n_sell = n - n_buy
                    n_high = sum(1 for s in merged if s.confidence >= 90)
                    floor  = self._confidence_floor
                    self._lbl_active.configure(
                        text=f"{n} signal{'s' if n != 1 else ''} ≥{floor}%"
                             f"  ({len(self._current_signals)} Forex + {len(extra)} Crypto)")
                    self._stat_labels["active"].configure(
                        text=str(n), text_color=Colors.BUY if n else Colors.TEXT_MUTED)
                    self._stat_labels["buy"].configure(
                        text=str(n_buy),
                        text_color=Colors.BUY if n_buy else Colors.TEXT_MUTED)
                    self._stat_labels["sell"].configure(
                        text=str(n_sell),
                        text_color=Colors.SELL if n_sell else Colors.TEXT_MUTED)
                    self._stat_labels["high"].configure(
                        text=str(n_high),
                        text_color=Colors.NEUTRAL if n_high else Colors.TEXT_MUTED)
            # Update scanning count label to include crypto symbols
            forex_count = len(self._scanner.symbols) if self._scanner else 0
            self._stat_labels["scanning"].configure(
                text=f"{forex_count + len(self._CRYPTO_SCAN_SYMBOLS)}")
        self.after(3000, self._do_crypto_merge)

    # ── Controls ───────────────────────────────────────────────────────────
    def _toggle_pause(self):
        if not self._scanner:
            return
        if self._scanner.is_paused():
            self._scanner.resume()
            self._btn_pause.configure(text="⏸ Pause", fg_color=Colors.NEUTRAL)
        else:
            self._scanner.pause()
            self._btn_pause.configure(text="▶ Resume", fg_color=Colors.BUY)

    def _manual_refresh(self):
        if self._is_refreshing:
            return
        self._is_refreshing = True
        self._btn_refresh.configure(text="Loading…", state="disabled")
        self._refresh()
        self._drain_queue()
        self.after(1500, self._reset_refresh_btn)

    def _reset_refresh_btn(self):
        self._is_refreshing = False
        self._btn_refresh.configure(text="⟳ Refresh", state="normal")

    def _on_conf_slider(self, value):
        new_floor = int(round(value))
        with self._lock:
            self._confidence_floor = new_floor
        self._lbl_conf_badge.configure(text=f"≥{new_floor}%")
        self._refresh()

    # ── Progress updates ───────────────────────────────────────────────────
    def _schedule_progress_update(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._update_progress()
        self.after(1000, self._schedule_progress_update)

    def _update_progress(self):
        if not self._scanner:
            return
        try:
            prog = self._scanner.get_progress()
            total = prog.get("total", 0)
            idx   = prog.get("index", 0)
            curr  = prog.get("current", "")
            eta   = prog.get("eta", 0)
            paused = prog.get("paused", False)

            if paused:
                self._lbl_prog_text.configure(text="⏸ Scanner paused")
                self._lbl_eta.configure(text="")
            elif curr:
                self._lbl_prog_text.configure(text=f"Scanning {curr}  ({idx}/{total})")
                eta_str = f"ETA: {int(eta)}s" if eta > 0 else ""
                self._lbl_eta.configure(text=eta_str)
                pct = idx / total if total > 0 else 0
                self._progress_bar.set(pct)
            else:
                self._lbl_prog_text.configure(text=f"Monitoring {total} markets")
                self._lbl_eta.configure(text="")
                self._progress_bar.set(1.0)
        except Exception:
            pass

    # ── Signal refresh ─────────────────────────────────────────────────────
    def _schedule_refresh(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._refresh()
        self.after(REFRESH_MS, self._schedule_refresh)

    def _refresh(self):
        if not self._scanner:
            return
        threading.Thread(target=self._bg_fetch, daemon=True).start()

    def _bg_fetch(self):
        try:
            all_signals = self._scanner.get_signals()
            status_text = self._scanner.get_status_text()
            with self._lock:
                floor = self._confidence_floor
            filtered = [s for s in all_signals if s.confidence >= floor]
            try:
                from services import signal_storage
                stored = {r["symbol"]: r for r in signal_storage.get_active_signals()}
            except Exception:
                stored = {}
            try:
                self._result_queue.get_nowait()   # discard stale result
            except __import__('queue').Empty:
                pass
            self._result_queue.put_nowait((filtered, stored, status_text))
        except Exception as exc:
            from utils.logger import logger
            logger.warning(f"[MarketScannerPage._bg_fetch] {type(exc).__name__}: {exc}")

    def _render_signals(self, signals: list):
        """Rebuild the scroll list with given signals (main thread)."""
        for w in self._scroll.winfo_children():
            w.destroy()
        self._cards.clear()
        if not signals:
            ctk.CTkLabel(
                self._scroll,
                text=f"No qualifying signals right now.\n\nLower the confidence slider or enable ₿ Crypto scan.",
                font=SF.NORMAL(),
                text_color=Colors.TEXT_MUTED, justify="center").pack(pady=60)
            return
        try:
            from services import signal_storage
            stored = {r["symbol"]: r for r in signal_storage.get_active_signals()}
        except Exception:
            stored = {}
        for sig in signals:
            expires_at = stored.get(sig.symbol, {}).get("expires_at")
            card = _ScannerCard(self._scroll, sig,
                                on_detail=self._open_detail,
                                on_apply_algo=self._apply_to_algo)
            card.refresh_expiry(expires_at)
            self._cards.append((card, sig, expires_at))

    def _ui_update(self, signals: list, stored: dict, status: str):
        self._current_signals = signals
        self._lbl_status.configure(text=status[:80])
        with self._lock:
            floor = self._confidence_floor

        n      = len(signals)
        n_buy  = sum(1 for s in signals if s.direction == "BUY")
        n_sell = n - n_buy
        n_high = sum(1 for s in signals if s.confidence >= 90)

        self._stat_labels["scanning"].configure(
            text=str(len(self._scanner.symbols) if self._scanner else "—"))
        self._stat_labels["active"].configure(text=str(n),
            text_color=Colors.BUY if n else Colors.TEXT_MUTED)
        self._stat_labels["buy"].configure(text=str(n_buy),
            text_color=Colors.BUY if n_buy else Colors.TEXT_MUTED)
        self._stat_labels["sell"].configure(text=str(n_sell),
            text_color=Colors.SELL if n_sell else Colors.TEXT_MUTED)
        self._stat_labels["high"].configure(text=str(n_high),
            text_color=Colors.NEUTRAL if n_high else Colors.TEXT_MUTED)
        self._lbl_active.configure(text=f"{n} signal{'s' if n != 1 else ''} ≥{floor}%")

        for w in self._scroll.winfo_children():
            w.destroy()
        self._cards.clear()

        if not signals:
            self._lbl_empty = ctk.CTkLabel(
                self._scroll,
                text=f"No signals ≥{floor}% confidence right now.\n\n"
                     "The scanner continuously monitors all markets and will\n"
                     "display qualifying signals as soon as they appear.",
                font=SF.NORMAL(),
                text_color=Colors.TEXT_MUTED, justify="center")
            self._lbl_empty.pack(pady=60)
            return

        for sig in signals:
            expires_at = stored.get(sig.symbol, {}).get("expires_at")
            card = _ScannerCard(self._scroll, sig,
                                on_detail=self._open_detail,
                                on_apply_algo=self._apply_to_algo)
            card.refresh_expiry(expires_at)
            self._cards.append((card, sig, expires_at))

    def _open_detail(self, signal):
        try:
            from ui.signal_engine_panel import SignalDetailModal
            SignalDetailModal(self.winfo_toplevel(), signal,
                              get_account_context=self._get_account_ctx)
        except Exception:
            pass

    def _apply_to_algo(self, signal):
        if self._on_apply_to_algo:
            self._on_apply_to_algo(signal)
        else:
            # Try to apply via signal_storage as a fallback
            try:
                from services import signal_storage
                signal_storage.upsert_signal(signal)
            except Exception:
                pass

    # ── Live expiry countdown ─────────────────────────────────────────────
    def _start_expiry_ticker(self):
        self._tick_expiry()

    def _tick_expiry(self):
        if self._stop_expiry:
            return
        for item in self._cards:
            if len(item) == 3:
                card, sig, expires_at = item
                try:
                    card.refresh_expiry(expires_at)
                except Exception:
                    pass
        if not self._destroyed:
            try:
                if self.winfo_exists():
                    self.after(1000, self._tick_expiry)
            except Exception:
                pass

    def _drain_queue(self):
        """Main-thread only: drains result queue and applies UI updates safely."""
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            args = self._result_queue.get_nowait()
            if isinstance(args, tuple):
                self._ui_update(*args)
        except __import__('queue').Empty:
            pass
        except Exception as exc:
            from utils.logger import logger
            logger.warning(f"[MarketScannerPage._drain_queue] {type(exc).__name__}: {exc}")
        self.after(100, self._drain_queue)

    def destroy(self):
        self._stop_expiry = True
        self._destroyed   = True
        self._crypto_stop = True   # ← stop crypto bg thread
        try:
            super().destroy()
        except Exception:
            pass

    def update_signals(self, signals: list, status_text: str = ""):
        try:
            from services import signal_storage
            stored = {r["symbol"]: r for r in signal_storage.get_active_signals()}
        except Exception:
            stored = {}
        with self._lock:
            floor = self._confidence_floor
        high = [s for s in signals if s.confidence >= floor]
        self._ui_update(high, stored, status_text)
