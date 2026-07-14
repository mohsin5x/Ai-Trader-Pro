"""
ui/main_window.py
==================
AI Trader Pro — Main Application Window
All 20 upgrade requirements implemented while preserving all existing
trading logic, AI models, APIs, signal generation, data flow, and architecture.
"""

import threading
import time
import tkinter as tk
# --- Custom Non-Blocking Messagebox ---
import customtkinter as ctk

class CustomMessageBox:
    @staticmethod
    def showinfo(title, message, parent=None, **kwargs):
        # FIX: Use make_dialog pattern — no update_idletasks(), no -topmost toggle,
        # no missing parent. This prevents the black-screen flash on dialog open.
        from ui.modal_overlay import make_dialog
        dialog = ctk.CTkToplevel(parent)
        make_dialog(dialog, parent, title=title, size=(380, 160))
        ctk.CTkLabel(dialog, text=message, wraplength=320,
                     justify="center").pack(pady=20, padx=20, fill="x")
        ctk.CTkButton(dialog, text="OK", width=100,
                      command=dialog.destroy).pack(pady=10)
        dialog.wait_window()

    @staticmethod
    def showerror(title, message, parent=None, **kwargs):
        CustomMessageBox.showinfo(f"Error — {title}", message, parent=parent)

    @staticmethod
    def askyesno(title, message, parent=None, **kwargs):
        """
        Modal yes/no dialog. Returns True if Yes clicked, False if No/closed.
        Uses make_dialog pattern — no black-screen flash, no update_idletasks().
        """
        from ui.modal_overlay import make_dialog
        result = [False]
        dialog = ctk.CTkToplevel(parent)
        make_dialog(dialog, parent, title=title, size=(420, 200), use_grab=True)

        ctk.CTkLabel(dialog, text=message, wraplength=360,
                     justify="center").pack(pady=20, padx=20, fill="x")

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(pady=10)

        def _yes():
            result[0] = True
            dialog.destroy()

        def _no():
            result[0] = False
            dialog.destroy()

        ctk.CTkButton(btn_row, text="No", width=100,
                      fg_color="gray30", command=_no).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="Yes", width=100,
                      command=_yes).pack(side="left", padx=8)
        dialog.wait_window()
        return result[0]


messagebox = CustomMessageBox()
# --------------------------------------
import customtkinter as ctk
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

from ui.theme import Colors, Fonts, Spacing, Sidebar, Window, Chart, save_appearance_mode
from ui.chart_widget import ChartWidget
from ui.coin_selector import CoinSelector
from ui.ai_panel import AIPanel
from ui.trade_panel import TradePanel
from ui.trade_journal_panel import TradeJournalPanel
from ui.news_panel import NewsDetailModal
from ui.signal_engine_panel import SignalEnginePanel
from ui.algo_trading_panel import AlgoTradingPanel
from ui.paper_trading_history_panel import PaperTradingHistoryPanel
from ui.signal_history_panel import SignalHistoryPanel
from ui.settings_panel import SettingsPanel
from ui.notification_bell import NotificationBell
from ui.watchlist_page import WatchlistPage
from ui.news_page import NewsPage
from ui.market_scanner_page import MarketScannerPage
from ui.manual_scanner_page import ManualScannerPage
from ui.system_status_panel import SystemStatusPanel
from ui.risk_tools_panel import RiskToolsPanel

from ui.market_sessions_page import MarketSessionsPage
from ui.knowledge_page import KnowledgePage

from services.crypto_service import CryptoService
from services.market_analyzer import MarketAnalyzer
from services.ai_engine import AIEngine
from services.signal_engine import SignalEngine
from services.market_scanner import MarketScanner
from services.paper_trading_engine import PaperTradingEngine
from services import paper_trading_db
from services import price_feed as _price_feed_module
from services import history_service
from services import chart_overlays
from services import provider_settings
from services import leverage_manager as lm
from services.notification_center import nc
from ui.components import bind_fast_scroll
from ui.scaling import S, SF, s, sf, pad, wrap, sidebar_wrap

# ── Navigation items ─────────────────────────────────────────────────────────
NAV_ITEMS = [
    ("dashboard",       "📊", "Dashboard"),
    ("ai_signals",      "🤖", "AI Signals"),
    ("signal_history",  "📋", "Signal History"),
    ("market_scanner",  "🔭", "Market Scanner"),
    ("manual_scanner",  "🎯", "Manual Scanner"),
    ("order_execution", "⚡", "Order Execution"),
    ("algo_trading",    "🔁", "Algo Trading"),
    ("trade_history",   "📜", "Paper Trading"),
    ("watchlist",       "📈", "Watchlist"),
    ("news",            "📰", "News"),
    ("risk_tools",      "🛡️", "Risk Tools"),
    ("system_status",   "💻", "System Status"),
    ("market_sessions", "🕐", "Market Sessions"),
    ("knowledge",       "📚", "Knowledge & Tips"),
    ("settings",        "⚙️", "Settings"),
]

# Minimum seconds between consecutive notification popups per symbol.
# Prevents the same signal from triggering a new toast every scan cycle.
_POPUP_COOLDOWN = 30


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AI Trader Pro  v2.0  —  Professional AI Trading Terminal  ·  Mohsin Abbas")

        # ── DPI / scaling — MUST run before ANY widget is built ───────
        # If scaling.init() is called after widget construction (as it
        # used to be in main.py STEP 3), every widget built in __init__
        # gets font tuples computed at the default scale factor of 1.0.
        # After init() the factor updates but existing widgets keep their
        # old (too-small or wrong-size) fonts — only freshly built
        # widgets get the correct size.  Moving init() here means the
        # correct DPI-aware factor is in place before the first label or
        # button is ever created, so every page looks consistent from the
        # very first render.
        try:
            from ui import scaling as _sc_early
            _sc_early.init(self)
            from ui.theme import Fonts as _Fonts_early
            _Fonts_early.refresh()
        except Exception:
            pass  # safe fallback — scaling defaults to 1.0 if init fails

        # ── Legacy DPI detection (kept for minsize calc below) ────────
        # ctk.ScalingTracker gives us the OS UI scaling factor so we can
        # set a sensible minimum size and initial geometry.
        try:
            _scale = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            _scale = 1.0
        _scale = max(1.0, min(_scale, 2.5))   # clamp 100–250%

        # Scale the minimum window size with DPI so it doesn't become
        # impossibly large on high-DPI displays (e.g. 4K at 200%)
        # Scaling manager will set the proper min size after init;
        # use a safe temporary minimum here.
        self.minsize(900, 600)

        _init_w = min(Window.WIDTH,  self.winfo_screenwidth()  - 80)
        _init_h = min(Window.HEIGHT, self.winfo_screenheight() - 80)
        self.geometry(f"{_init_w}x{_init_h}")
        self.configure(fg_color=Colors.APP_BG)

        # ── Services (unchanged) ──────────────────────────────────────
        self.crypto_service  = CryptoService()
        self.market_analyzer = MarketAnalyzer()
        self.ai_engine       = AIEngine()
        self.signal_engine   = SignalEngine(self.crypto_service, self.market_analyzer)
        self.market_scanner  = MarketScanner(self.crypto_service, self.signal_engine)
        self.market_scanner.start()

        # ── PriceFeed: high-frequency Binance direct feed ─────────────
        # MUST be initialized before PaperTradingEngine so that
        # _fetch_prices() can immediately read live Binance spot prices.
        # This is the single authoritative real-time price source shared
        # by the paper trading engine, algo engine, and watchlist.
        self.price_feed = _price_feed_module.init_feed(
            crypto_service=self.crypto_service
        )

        paper_trading_db.init_db()
        self.paper_trading_engine = PaperTradingEngine(
            self.crypto_service, self.market_scanner,
            get_risk_percentage=lambda: self.risk_percentage,
        )
        # Start engine immediately so is_running()=True and _open_trades is
        # populated from DB before any panel's first _bg_fetch fires.
        self.paper_trading_engine.start()

        # ── State ─────────────────────────────────────────────────────
        self.state_lock     = threading.Lock()
        self.current_coin   = "EUR/USD"
        self.current_timeframe = "1h"
        self.current_strategy  = "ICT Smart Money"
        self.state_version  = 0

        # Performance: single-thread executor prevents thread pile-up
        self._pipeline_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")
        self._pipeline_future   = None

        self.account_balance = provider_settings.load_account_balance()
        self.floating_pnl   = 0.0
        self.risk_percentage = 0.01
        self.current_suggested_size_text = "0.00 LOTS"
        self.current_suggested_units_raw = 0.0
        self.active_positions = []
        self.latest_watchlist_prices = {}

        self._last_popup_time    = 0.0
        self._resize_after_id    = None
        self._current_chart_height = Chart.HEIGHT()
        self._ai_sl = 0.0
        self._ai_tp = 0.0
        self._last_news_count   = 0

        # ── Root grid ─────────────────────────────────────────────────
        self.grid_columnconfigure(0, weight=0)   # slim sidebar
        self.grid_columnconfigure(1, weight=1)   # page content
        self.grid_rowconfigure(0, weight=1)

        # ── Slim sidebar ──────────────────────────────────────────────
        self._build_sidebar()

        # ── Page host ─────────────────────────────────────────────────
        self.page_host = ctk.CTkFrame(self, fg_color=Colors.APP_BG, corner_radius=0)
        self.page_host.grid(row=0, column=1, sticky="nsew")
        self.page_host.grid_columnconfigure(0, weight=1)
        self.page_host.grid_rowconfigure(0, weight=1)

        # ── Build all pages ───────────────────────────────────────────
        self.pages = {}
        # Build only critical pages immediately (needed for first render)
        self._build_dashboard_page()
        self._build_settings_page()   # needed for config

        # All other pages deferred: shown placeholder, built after first paint
        self._deferred_pages_built = False

        self._refresh_trade_journal()
        self.show_page("dashboard")

        self.start_live_ticking()
        self._refresh_signal_engine_panel()
        self._schedule_journal_refresh()
        self.market_scanner.register_new_signal_callback(self._on_new_scanner_signal)

        # FIX (2026-07-13): Wire MT5 init-complete callback so the chart
        # pipeline fires the moment the async COM handshake succeeds, instead
        # of waiting up to 2 s for the next start_live_ticking tick.
        # Without this, the chart stays blank from startup until the first tick.
        self._register_mt5_init_callback()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_root_resize)
        # Also sync chart height when window is maximized/restored
        self.bind("<Map>", lambda e: self.after(200, self._sync_chart_height_to_window))

        if hasattr(self.coin_selector, "coin_menu"):
            self.coin_selector.coin_menu.set(self.current_coin)
        self.after(200, self._sync_chart_height_to_window)

        # FIX (2026-07-13): Defer heavy page builds to AFTER maximize completes.
        # Original 600ms fired during the WM's zoom layout pass which caused
        # widgets to call winfo_width()/winfo_height() on parents that hadn't
        # been resized yet, crashing or producing incorrect sizes.
        # 1200ms is safely after the 350ms + 750ms remeasure passes in main.py.
        #
        # FIX 2 (2026-07-13): Increased to 1800ms and added update_idletasks()
        # guard inside _build_deferred_pages to prevent "Too early to use font:
        # no default root window" warnings. These occur when CTkFont introspection
        # fires before the Tk message pump has fully processed the first paint.
        # FIX: after() fires inside mainloop so Tk is always ready. Small delay lets dashboard render first.
        self.after(200, self._build_deferred_pages)

    def _register_mt5_init_callback(self):
        """
        If the active provider is MT5Provider, register a callback so the
        chart pipeline fires immediately when the async COM handshake completes.
        This fixes the "MT5 connected but chart blank until next tick" issue.
        Safe to call for non-MT5 providers (no-op if provider has no
        set_on_init_complete method).
        """
        try:
            provider = self.crypto_service._providers[0] if self.crypto_service._providers else None
            if provider and hasattr(provider, "set_on_init_complete"):
                def _on_mt5_ready():
                    # Called from a background thread -- schedule on the Tk mainloop
                    try:
                        if self.winfo_exists():
                            self.after(0, self.trigger_pipeline)
                    except Exception:
                        pass
                provider.set_on_init_complete(_on_mt5_ready)
        except Exception as e:
            from utils.logger import logger
            logger.warning(f"[MainWindow] _register_mt5_init_callback failed (non-fatal): {e}")

    # ─────────────────────────────────────────────────────────────────
    # Sidebar — icon+label nav, asset selector, founder branding
    # ─────────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(
            self, width=S.SIDEBAR_W(), corner_radius=0,
            fg_color=Colors.SIDEBAR_BG,
        )
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        self.sidebar_frame.grid_columnconfigure(0, weight=1)

        # ── Logo row ────────────────────────────────────────────────
        logo_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        logo_frame.grid(row=0, column=0, sticky="ew", padx=s(10), pady=(14, 6))

        # Gold diamond icon placeholder
        ctk.CTkLabel(logo_frame, text="◆", font=SF.HEADER(),
                     text_color=Colors.GOLD, fg_color="transparent").pack(side="left", padx=(0, 6))
        title_col = ctk.CTkFrame(logo_frame, fg_color="transparent")
        title_col.pack(side="left")
        ctk.CTkLabel(title_col, text="AI TRADER PRO",
                     font=SF.LOGO(), text_color=Colors.TEXT).pack(anchor="w")
        ctk.CTkLabel(title_col, text="Intelligent Trading. Smarter Decisions.",
                     font=SF.NANO(), text_color=Colors.TEXT_MUTED).pack(anchor="w")

        # Notification bell on the right
        self.notification_bell = NotificationBell(
            logo_frame, on_new_signal_popup=self._schedule_signal_popup)
        self.notification_bell.pack(side="right")

        # ── Live / connection status ─────────────────────────────────
        live_row = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        live_row.grid(row=1, column=0, sticky="ew", padx=s(10), pady=(0, 2))
        live_row.grid_columnconfigure(1, weight=1)

        self.lbl_live_dot = ctk.CTkLabel(
            live_row, text="● LIVE", font=SF.STATUS_BOLD(),
            text_color=Colors.BUY)
        self.lbl_live_dot.grid(row=0, column=0, sticky="w")
        self._start_live_dot_ticker()  # dynamic market open/close status

        self.lbl_conn_status = ctk.CTkLabel(
            live_row, text="", font=SF.STATUS(),
            text_color=Colors.TEXT_MUTED)
        self.lbl_conn_status.grid(row=0, column=2, sticky="e")

        self.lbl_active_markets = ctk.CTkLabel(
            live_row, text="", font=SF.STATUS_BOLD(),
            text_color=Colors.NEUTRAL, anchor="e")
        self.lbl_active_markets.grid(row=0, column=1, sticky="e", padx=(4, 6))
        self._start_active_markets_ticker()

        # ── Divider ───────────────────────────────────────────────────
        ctk.CTkFrame(self.sidebar_frame, fg_color=Colors.BORDER, height=1
                     ).grid(row=2, column=0, sticky="ew", padx=s(10), pady=(2, 4))

        # ── Asset + Timeframe selector ────────────────────────────────
        selector_frame = ctk.CTkFrame(
            self.sidebar_frame, fg_color=Colors.CARD_BG_ALT,
            corner_radius=s(8), border_width=1, border_color=Colors.BORDER)
        selector_frame.grid(row=3, column=0, sticky="ew", padx=S.SM(), pady=(0, 4))
        self.coin_selector = CoinSelector(
            selector_frame,
            on_coin_change=self.change_coin,
            on_timeframe_change=self.change_timeframe)
        self.coin_selector.pack(fill="x", padx=2, pady=2)

        # ── Divider ───────────────────────────────────────────────────
        ctk.CTkFrame(self.sidebar_frame, fg_color=Colors.BORDER, height=1
                     ).grid(row=4, column=0, sticky="ew", padx=s(10), pady=(0, 2))

        # ── Nav buttons (scrollable) ──────────────────────────────────
        nav_frame = ctk.CTkScrollableFrame(
            self.sidebar_frame, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.PRIMARY)
        nav_frame.grid(row=5, column=0, sticky="nsew", padx=0, pady=0)
        nav_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_frame.grid_rowconfigure(5, weight=1)
        bind_fast_scroll(nav_frame)

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for row_idx, (key, icon, label) in enumerate(NAV_ITEMS):
            btn = ctk.CTkButton(
                nav_frame, text=f"{icon}  {label}", anchor="w",
                height=S.NAV_BTN_H(), corner_radius=s(6),
                fg_color="transparent", hover_color=Colors.HOVER,
                text_color=Colors.TEXT_SECONDARY, font=SF.NAV(),
                command=lambda k=key: self.show_page(k))
            btn.grid(row=row_idx, column=0, sticky="ew", padx=S.NAV_BTN_PAD(), pady=s(1))
            self.nav_buttons[key] = btn

        # ── Divider ───────────────────────────────────────────────────
        ctk.CTkFrame(self.sidebar_frame, fg_color=Colors.BORDER, height=1
                     ).grid(row=6, column=0, sticky="ew", padx=s(10), pady=2)

        # ── Sync status ───────────────────────────────────────────────
        self.lbl_last_sync = ctk.CTkLabel(
            self.sidebar_frame, text="Syncing…",
            font=SF.STATUS(), text_color=Colors.TEXT_MUTED,
            wraplength=sidebar_wrap())
        self.lbl_last_sync.grid(row=7, column=0, sticky="ew", padx=s(10), pady=(2, 2))

        # ── About / Exit ──────────────────────────────────────────────
        ctk.CTkButton(
            self.sidebar_frame, text="About AI Trader Pro",
            height=s(22), corner_radius=s(4), fg_color="transparent",
            hover_color=Colors.HOVER, text_color=Colors.TEXT_MUTED,
            font=SF.STATUS(), command=self._open_about,
        ).grid(row=8, column=0, sticky="ew", padx=s(10), pady=(0, 2))

        ctk.CTkButton(
            self.sidebar_frame, text="⏻  Exit",
            height=s(28), corner_radius=s(6), fg_color=Colors.CARD_BG_ALT,
            hover_color="#3D1016", text_color=Colors.SELL,
            font=SF.PILL_LG(), command=self._on_close,
        ).grid(row=9, column=0, sticky="ew", padx=s(10), pady=(0, 4))

        # ── Founder branding + avatar ─────────────────────────────────
        brand = ctk.CTkFrame(self.sidebar_frame, fg_color=Colors.CARD_BG,
                              corner_radius=s(8), border_width=1, border_color=Colors.BORDER)
        brand.grid(row=10, column=0, sticky="ew", padx=S.SM(), pady=(0, 8))

        # Avatar circle
        av = ctk.CTkFrame(brand, fg_color=Colors.PRIMARY, width=S.AVATAR(), height=S.AVATAR(),
                           corner_radius=S.AVATAR_R())
        av.pack(side="left", padx=s(10), pady=S.SM())
        av.pack_propagate(False)
        ctk.CTkLabel(av, text="MA", font=SF.NORMAL(),
                     text_color=Colors.ON_BUY).place(relx=0.5, rely=0.5, anchor="center")

        info = ctk.CTkFrame(brand, fg_color="transparent")
        info.pack(side="left", pady=S.SM())
        ctk.CTkLabel(info, text="Mohsin Abbas",
                     font=SF.PILL_LG(), text_color=Colors.GOLD).pack(anchor="w")
        ctk.CTkLabel(info, text="Founder & Owner",
                     font=SF.NANO(), text_color=Colors.TEXT_MUTED).pack(anchor="w")
        ctk.CTkLabel(info, text="Version 2.0.0",
                     font=SF.NANO(), text_color=Colors.TEXT_MUTED).pack(anchor="w")

    def _start_live_dot_ticker(self):
        """Updates the LIVE dot to show green only when at least one major market is open."""
        from datetime import datetime, timezone as _tz
        _SESSIONS = [
            ("Sydney",   22, 7),
            ("Tokyo",     0, 9),
            ("London",    8, 17),
            ("New York", 13, 22),
        ]
        def _is_open(h, s, e):
            return (h >= s or h < e) if s > e else (s <= h < e)
        def _tick():
            try:
                if not self.winfo_exists():
                    return
                h = datetime.now(_tz.utc).hour
                any_open = any(_is_open(h, s, e) for _, s, e in _SESSIONS)
                if any_open:
                    self.lbl_live_dot.configure(text="● LIVE", text_color="#00C853")
                else:
                    self.lbl_live_dot.configure(text="○ CLOSED", text_color="#FF6B6B")
            except Exception:
                return
            self.after(60_000, _tick)
        _tick()

    def _start_active_markets_ticker(self):
        """Updates the slim active-markets label every 60 s without the full SessionClockPanel."""
        from datetime import datetime, timezone as _tz
        _SESSIONS = [
            ("Sydney",   "AU", 22, 7),
            ("Tokyo",    "JP",  0, 9),
            ("London",   "GB",  8, 17),
            ("New York", "US", 13, 22),
        ]
        _FLAGS = {"Sydney": "🇦🇺", "Tokyo": "🇯🇵", "London": "🇬🇧", "New York": "🇺🇸"}

        def _is_open(h, s, e):
            return (h >= s or h < e) if s > e else (s <= h < e)

        def _tick():
            try:
                if not self.winfo_exists():
                    return
                h = datetime.now(_tz.utc).hour
                open_now = [_FLAGS[n] + n for n, _, s, e in _SESSIONS if _is_open(h, s, e)]
                if open_now:
                    self.lbl_active_markets.configure(
                        text=" · ".join(open_now), text_color=Colors.BUY)
                else:
                    self.lbl_active_markets.configure(
                        text="All closed", text_color=Colors.TEXT_MUTED)
            except Exception:
                return
            self.after(60_000, _tick)

        _tick()  # run immediately, then every 60 s

    # ─────────────────────────────────────────────────────────────────
    # Page helpers
    # ─────────────────────────────────────────────────────────────────
    def _register_page(self, key: str, frame):
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_remove()
        self.pages[key] = frame

    def _tk_is_ready(self) -> bool:
        """Always True — readiness guaranteed by after() being inside mainloop."""
        return True

    def _build_deferred_pages(self):
        """Build all remaining pages. Safe because after() runs inside mainloop."""
        if self._deferred_pages_built:
            return

        # Setup the queue of pages to build on the first run
        if not hasattr(self, "_pages_to_build"):
            self._pages_to_build = [
                ("ai_signals",       self._build_ai_signals_page),
                ("signal_history",   self._build_signal_history_page),
                ("market_scanner",   self._build_market_scanner_page),
                ("manual_scanner",   self._build_manual_scanner_page),
                ("order_exec",       self._build_order_execution_page),
                ("algo_trading",     self._build_algo_trading_page),
                ("trade_history",    self._build_trade_history_page),
                ("watchlist",        self._build_watchlist_page),
                ("news",             self._build_news_page),
                ("risk_tools",       self._build_risk_tools_page),
                ("system_status",    self._build_system_status_page),
                ("market_sessions",  self._build_market_sessions_page),
                ("knowledge",        self._build_knowledge_page)
            ]
        # Track retry counts per page to avoid infinite loops
        if not hasattr(self, "_pages_retry_count"):
            self._pages_retry_count = {}

        # If the queue is empty, we are done
        if not self._pages_to_build:
            self._deferred_pages_built = True
            from utils.logger import logger as _log
            _log.info("[Deferred] All pages built successfully.")
            self.after(0, self._update_signal_badge)
            return

        # Pop the next page and build it
        name, fn = self._pages_to_build.pop(0)

        try:
            fn()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            
            from utils.logger import logger as _log
            retry_count = self._pages_retry_count.get(name, 0)
            max_retries = 8  # ~640ms of additional retries before giving up
            if retry_count < max_retries:
                # Put the page back at the END of the queue to retry after others build
                self._pages_to_build.append((name, fn))
                self._pages_retry_count[name] = retry_count + 1
                if retry_count == 0:
                    # Only log on first failure to avoid log spam
                    _log.warning(f"[Deferred] {name}: {exc} — will retry")
            else:
                # Gave up after max retries; page stays unbuilt (show_page will
                # never show it, which is preferable to an infinite retry loop)
                _log.warning(f"[Deferred] {name}: gave up after {max_retries} retries: {exc}")

        # Schedule the next page build 80ms later so the UI doesn't lock up
        self.after(100, self._build_deferred_pages)

    def show_page(self, key: str, _retry_count: int = 0):
        # 1. Update the sidebar buttons immediately so UI feels responsive
        for bk, btn in self.nav_buttons.items():
            if bk == key:
                btn.configure(fg_color=Colors.PRIMARY, text_color=Colors.ON_BUY)
            else:
                btn.configure(fg_color="transparent", text_color=Colors.TEXT_SECONDARY)
                
        # 2. If page not built yet, retry with backoff (cap at 30 attempts ~ 9 sec)
        if key not in self.pages:
            if _retry_count < 30:
                self.after(300, lambda k=key, c=_retry_count: self.show_page(k, c + 1))
            return

        # 3. Hide all pages, then show the requested one
        for pk, frame in self.pages.items():
            if pk == key:
                frame.grid()
            else:
                frame.grid_remove()
                
        if key == "dashboard":
            self.after(50, self._sync_chart_height_to_window)
    # ─────────────────────────────────────────────────────────────────
    # Dashboard
    # ─────────────────────────────────────────────────────────────────
    def _build_dashboard_page(self):
        """Bloomberg / TradingView style dashboard:
          row0 = top header bar (market pill, account pills, AI btn, avatar)
          row1 = KPI stat cards (Balance, Equity, Daily P/L, Weekly P/L,
                                 Monthly P/L, Win Rate, AI Accuracy, Open Positions)
          row2 = body (chart area left, right panel: watchlist+news+sessions)
          row3 = bottom row (AI Signals cards + Market Scanner mini-table)
          row4 = status bar (AI, API, Scanner, Paper Trader, Latency, CPU, RAM, Clock)
        """
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=0)   # top header bar — fixed
        page.grid_rowconfigure(1, weight=0)   # KPI cards row — fixed
        page.grid_rowconfigure(2, weight=1)   # body (chart + right panel) — expands
        page.grid_rowconfigure(3, weight=0)   # AI Signals + scanner bottom row — fixed
        page.grid_rowconfigure(4, weight=0)   # status bar — fixed
        self._register_page("dashboard", page)

        _STRATEGIES = [
            "ICT Smart Money", "Smart Money Concepts", "Support & Resistance",
            "Liquidity Concepts", "Order Blocks", "Fair Value Gaps",
            "Break of Structure", "Change of Character",
            "Scalping", "Swing Trading", "Trend Following", "Breakout",
        ]

        # ════════════════════════════════════════════════════════════════
        # ROW 0 — Top header bar
        # ════════════════════════════════════════════════════════════════
        hdr = ctk.CTkFrame(page, fg_color=Colors.SIDEBAR_BG,
                            height=S.HDR_H(), corner_radius=0,
                            border_width=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)   # search area grows

        # ── Left: Market pill + Account pill ─────────────────────────
        left_hdr = ctk.CTkFrame(hdr, fg_color="transparent")
        left_hdr.grid(row=0, column=0, sticky="nsew", padx=(10, 4), pady=S.XS())

        # Market type selector
        mkt_pill = ctk.CTkFrame(left_hdr, fg_color=Colors.CARD_BG_ALT,
                                 corner_radius=s(6), border_width=1,
                                 border_color=Colors.BORDER)
        mkt_pill.pack(side="left", padx=(0, 6))
        self.strategy_menu = ctk.CTkOptionMenu(
            mkt_pill, values=_STRATEGIES, command=self.change_strategy,
            fg_color=Colors.CARD_BG_ALT, button_color=Colors.CARD_BG_ALT,
            button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
            dropdown_fg_color=Colors.CARD_BG, dropdown_hover_color=Colors.HOVER,
            dropdown_text_color=Colors.TEXT, font=SF.TINY(),
            corner_radius=s(4), height=S.BTN_H(), width=s(150))
        self.strategy_menu.set(self.current_strategy)
        self.strategy_menu.pack(padx=6, pady=6)

        # Account type pill
        acc_pill = ctk.CTkFrame(left_hdr, fg_color=Colors.CARD_BG_ALT,
                                 corner_radius=s(6), border_width=1,
                                 border_color=Colors.BORDER)
        acc_pill.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(acc_pill, text="Live Account", font=SF.PILL_LG(),
                     text_color=Colors.BUY, cursor="hand2").pack(padx=s(10), pady=S.SM())

        # Balance pill (clickable to edit)
        bal_pill = ctk.CTkFrame(left_hdr, fg_color=Colors.CARD_BG_ALT,
                                 corner_radius=s(6), border_width=1,
                                 border_color=Colors.BORDER)
        bal_pill.pack(side="left", padx=(0, 4))
        bal_inner = ctk.CTkFrame(bal_pill, fg_color="transparent")
        bal_inner.pack(padx=6, pady=S.XS())
        ctk.CTkLabel(bal_inner, text="Balance", font=SF.TAG(),
                     text_color=Colors.TEXT_MUTED).pack(anchor="w")
        self.lbl_balance = ctk.CTkLabel(
            bal_inner, text=f"${self.account_balance:,.2f}",
            font=SF.MONO_TINY(), text_color=Colors.TEXT, cursor="hand2")
        self.lbl_balance.pack(anchor="w")
        self.lbl_balance.bind("<Button-1>", lambda e: self._open_edit_balance_dialog())

        # Equity pill
        eq_pill = ctk.CTkFrame(left_hdr, fg_color=Colors.CARD_BG_ALT,
                                corner_radius=s(6), border_width=1,
                                border_color=Colors.BORDER)
        eq_pill.pack(side="left", padx=(0, 4))
        eq_inner = ctk.CTkFrame(eq_pill, fg_color="transparent")
        eq_inner.pack(padx=6, pady=S.XS())
        ctk.CTkLabel(eq_inner, text="Equity", font=SF.TAG(),
                     text_color=Colors.TEXT_MUTED).pack(anchor="w")
        self.lbl_equity = ctk.CTkLabel(
            eq_inner, text=f"${self.account_balance:,.2f}",
            font=SF.MONO_TINY(), text_color=Colors.TEXT)
        self.lbl_equity.pack(anchor="w")

        # P/L Today pill
        pnl_pill = ctk.CTkFrame(left_hdr, fg_color=Colors.CARD_BG_ALT,
                                 corner_radius=s(6), border_width=1,
                                 border_color=Colors.BORDER)
        pnl_pill.pack(side="left", padx=(0, 4))
        pnl_inner = ctk.CTkFrame(pnl_pill, fg_color="transparent")
        pnl_inner.pack(padx=6, pady=S.XS())
        ctk.CTkLabel(pnl_inner, text="P/L Today", font=SF.TAG(),
                     text_color=Colors.TEXT_MUTED).pack(anchor="w")
        self.lbl_floating_pnl = ctk.CTkLabel(
            pnl_inner, text="+$0.00",
            font=SF.MONO_TINY(), text_color=Colors.BUY)
        self.lbl_floating_pnl.pack(anchor="w")

        # ── Centre: Search bar ────────────────────────────────────────
        srch = ctk.CTkFrame(hdr, fg_color=Colors.CARD_BG,
                             corner_radius=s(6), border_width=1,
                             border_color=Colors.BORDER, height=S.NAV_BTN_H())
        srch.grid(row=0, column=1, sticky="ew", padx=s(12), pady=13)
        srch.grid_propagate(False)
        ctk.CTkLabel(srch, text="🔍  Search Market / Symbol",
                     font=SF.PILL(), text_color=Colors.TEXT_MUTED,
                     anchor="w").place(relx=0.02, rely=0.5, anchor="w")

        # ── Right: AI Assistant + icons + avatar ─────────────────────
        right_hdr = ctk.CTkFrame(hdr, fg_color="transparent")
        right_hdr.grid(row=0, column=2, sticky="e", padx=(4, 10), pady=S.XS())

        # AI Assistant button
        ctk.CTkButton(
            right_hdr, text="🤖  AI Assistant", width=s(120), height=S.BTN_H(),
            corner_radius=s(6), fg_color=Colors.PRIMARY,
            hover_color=Colors.PRIMARY_HOVER, text_color=Colors.ON_BUY,
            font=SF.BTN(),
            command=lambda: self.show_page("ai_signals"),
        ).pack(side="left", padx=(0, 8))

        # Icon buttons row
        for icon, tip, cmd in [
            ("🔔", "Notifications", lambda: self.notification_bell._toggle_panel()),
            ("⚙", "Settings",      lambda: self.show_page("settings")),
            ("☾", "Theme",         self._toggle_theme),
        ]:
            btn = ctk.CTkButton(
                right_hdr, text=icon, width=s(30), height=S.BTN_H(), corner_radius=s(6),
                fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                text_color=Colors.TEXT_MUTED, font=SF.SUBHEADER(),
                command=cmd or (lambda: None))
            btn.pack(side="left", padx=2)

        # Avatar + name
        av_frame = ctk.CTkFrame(right_hdr, fg_color="transparent")
        av_frame.pack(side="left", padx=(8, 0))
        av_circle = ctk.CTkFrame(av_frame, fg_color=Colors.PRIMARY,
                                  width=s(30), height=S.BTN_H(), corner_radius=15)
        av_circle.pack(side="left")
        av_circle.pack_propagate(False)
        ctk.CTkLabel(av_circle, text="MA", font=SF.STATUS_BOLD(),
                     text_color=Colors.ON_BUY).place(relx=0.5, rely=0.5, anchor="center")
        name_col = ctk.CTkFrame(av_frame, fg_color="transparent")
        name_col.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(name_col, text="Mohsin Abbas",
                     font=SF.STATUS_BOLD(), text_color=Colors.TEXT).pack(anchor="w")
        ctk.CTkLabel(name_col, text="Founder & Owner",
                     font=SF.NANO(), text_color=Colors.TEXT_MUTED).pack(anchor="w")

        # ════════════════════════════════════════════════════════════════
        # ROW 1 — 8 KPI stat cards
        # ════════════════════════════════════════════════════════════════
        kpi_row = ctk.CTkFrame(page, fg_color="transparent")
        kpi_row.grid(row=1, column=0, sticky="ew", padx=6, pady=(4, 0))
        for i in range(8):
            kpi_row.grid_columnconfigure(i, weight=1)

        def _kpi_card(parent, col, label, value_text, value_color=None,
                      sub_text="", sub_color=None, has_sparkline=False,
                      is_gauge=False, gauge_pct=0.0):
            card = ctk.CTkFrame(parent, fg_color=Colors.CARD_BG,
                                 border_width=1, border_color=Colors.BORDER,
                                 corner_radius=s(8))
            card.grid(row=0, column=col, sticky="ew", padx=3, pady=2)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=s(10), pady=S.SM())

            ctk.CTkLabel(inner, text=label, font=SF.TINY(),
                         text_color=Colors.LABEL, anchor="w").pack(anchor="w")

            if is_gauge:
                # Circular-style gauge using colour arc text
                gauge_row = ctk.CTkFrame(inner, fg_color="transparent")
                gauge_row.pack(fill="x")
                pct_color = (Colors.BUY if gauge_pct >= 60 else
                             Colors.NEUTRAL if gauge_pct >= 40 else Colors.SELL)
                ctk.CTkLabel(gauge_row, text=value_text,
                             font=SF.PRICE_SM(),
                             text_color=pct_color).pack(side="left")
                # Progress arc as a thin progress bar
                arc = ctk.CTkProgressBar(inner, height=4, corner_radius=2,
                                          progress_color=pct_color,
                                          fg_color=Colors.WELL_BG)
                arc.set(gauge_pct / 100.0)
                arc.pack(fill="x", pady=(4, 0))
            elif has_sparkline:
                row_v = ctk.CTkFrame(inner, fg_color="transparent")
                row_v.pack(fill="x")
                ctk.CTkLabel(row_v, text=value_text, font=SF.PRICE_SM(),
                             text_color=value_color or Colors.TEXT).pack(side="left")
                if sub_text:
                    ctk.CTkLabel(row_v, text=f"  {sub_text}",
                                 font=SF.STATUS_BOLD(),
                                 text_color=sub_color or Colors.BUY).pack(side="left",
                                                                           pady=(4, 0))
                # Tiny sparkline bar — hidden until real P/L data populates it
                # (avoids the always-65% hardcoded fill complaint).
                # _kpi_card returns (card, spark) so callers can drive it.
                spark = ctk.CTkProgressBar(inner, height=3, corner_radius=1,
                                            progress_color=value_color or Colors.BUY,
                                            fg_color=Colors.WELL_BG)
                spark.set(0.0)
                spark.pack(fill="x", pady=(4, 0))
            else:
                ctk.CTkLabel(inner, text=value_text, font=SF.PRICE_SM(),
                             text_color=value_color or Colors.TEXT, anchor="w").pack(anchor="w")
                if sub_text:
                    ctk.CTkLabel(inner, text=sub_text, font=SF.STATUS(),
                                 text_color=sub_color or Colors.TEXT_MUTED,
                                 anchor="w").pack(anchor="w")
            # Return both card and sparkline widget (None if not has_sparkline)
            return card, (spark if has_sparkline else None)

        # Balance card — special: shows live label
        bal_card = ctk.CTkFrame(kpi_row, fg_color=Colors.CARD_BG,
                                 border_width=1, border_color=Colors.BORDER,
                                 corner_radius=s(8))
        bal_card.grid(row=0, column=0, sticky="ew", padx=3, pady=2)
        bal_inner = ctk.CTkFrame(bal_card, fg_color="transparent")
        bal_inner.pack(fill="both", expand=True, padx=s(10), pady=S.SM())
        ctk.CTkLabel(bal_inner, text="💼  Balance", font=SF.TINY(),
                     text_color=Colors.LABEL, anchor="w").pack(anchor="w")
        self.lbl_kpi_balance = ctk.CTkLabel(
            bal_inner, text=f"${self.account_balance:,.2f}",
            font=SF.PRICE_SM(), text_color=Colors.TEXT, anchor="w",
            cursor="hand2")
        self.lbl_kpi_balance.pack(anchor="w")
        self.lbl_kpi_balance.bind("<Button-1>", lambda e: self._open_edit_balance_dialog())

        # Equity card
        eq_card = ctk.CTkFrame(kpi_row, fg_color=Colors.CARD_BG,
                                border_width=1, border_color=Colors.BORDER,
                                corner_radius=s(8))
        eq_card.grid(row=0, column=1, sticky="ew", padx=3, pady=2)
        eq_inner = ctk.CTkFrame(eq_card, fg_color="transparent")
        eq_inner.pack(fill="both", expand=True, padx=s(10), pady=S.SM())
        ctk.CTkLabel(eq_inner, text="📊  Equity", font=SF.TINY(),
                     text_color=Colors.LABEL, anchor="w").pack(anchor="w")
        self.lbl_kpi_equity = ctk.CTkLabel(
            eq_inner, text=f"${self.account_balance:,.2f}",
            font=SF.PRICE_SM(), text_color=Colors.TEXT, anchor="w")
        self.lbl_kpi_equity.pack(anchor="w")

        # Daily P/L
        _, self._spark_daily = _kpi_card(kpi_row, 2, "📈  Daily P/L", "+$0.00",
                          Colors.BUY, "+0.00%", Colors.BUY, has_sparkline=True)

        # Weekly P/L
        _, self._spark_weekly = _kpi_card(kpi_row, 3, "📅  Weekly P/L", "+$0.00",
                  Colors.BUY, "+0.00%", Colors.BUY, has_sparkline=True)

        # Monthly P/L
        _, self._spark_monthly = _kpi_card(kpi_row, 4, "🗓  Monthly P/L", "+$0.00",
                  Colors.BUY, "+0.00%", Colors.BUY, has_sparkline=True)

        # Win Rate gauge
        _kpi_card(kpi_row, 5, "🎯  Win Rate", "—%",
                  is_gauge=True, gauge_pct=0.0)

        # AI Accuracy gauge
        _kpi_card(kpi_row, 6, "🤖  AI Accuracy", "—%",
                  is_gauge=True, gauge_pct=0.0)

        # Open Positions
        op_card = ctk.CTkFrame(kpi_row, fg_color=Colors.CARD_BG,
                                border_width=1, border_color=Colors.BORDER,
                                corner_radius=s(8))
        op_card.grid(row=0, column=7, sticky="ew", padx=3, pady=2)
        op_inner = ctk.CTkFrame(op_card, fg_color="transparent")
        op_inner.pack(fill="both", expand=True, padx=s(10), pady=S.SM())
        ctk.CTkLabel(op_inner, text="📉  Open Positions", font=SF.TINY(),
                     text_color=Colors.LABEL, anchor="w").pack(anchor="w")
        self.lbl_kpi_open_pos = ctk.CTkLabel(
            op_inner, text="0",
            font=SF.PRICE_SM(), text_color=Colors.NEUTRAL, anchor="w")
        self.lbl_kpi_open_pos.pack(anchor="w")

        # ════════════════════════════════════════════════════════════════
        # ROW 2 — Body: chart area (left) + right panel
        # ════════════════════════════════════════════════════════════════
        body = ctk.CTkFrame(page, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        body.grid_columnconfigure(0, weight=1)   # chart
        body.grid_columnconfigure(1, weight=0)   # right panel fixed width
        body.grid_rowconfigure(0, weight=1)

        # ── Chart column ──────────────────────────────────────────────
        chart_col = ctk.CTkFrame(body, fg_color="transparent")
        chart_col.grid(row=0, column=0, sticky="nsew", padx=(6, 3), pady=S.XS())
        chart_col.grid_rowconfigure(0, weight=1)
        chart_col.grid_columnconfigure(0, weight=1)

        self.chart_widget = ChartWidget(
            chart_col, on_strategy_change=self.change_strategy,
            strategies=_STRATEGIES, current_strategy=self.current_strategy)
        self.chart_widget.grid(row=0, column=0, sticky="nsew")

        # Mini status bar under chart
        chart_status = ctk.CTkFrame(chart_col, fg_color=Colors.CARD_BG,
                                     corner_radius=s(6), height=s(24),
                                     border_width=1, border_color=Colors.BORDER)
        chart_status.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        chart_status.grid_propagate(False)
        self.lbl_market_info = ctk.CTkLabel(
            chart_status,
            text="Strategy: — | Signal: — | Confidence: —",
            font=SF.MONO_TINY(), text_color=Colors.TEXT_MUTED, anchor="w")
        self.lbl_market_info.pack(side="left", padx=s(10))
        self.lbl_calc_lots = ctk.CTkLabel(
            chart_status, text="SIZE: CALC…",
            font=SF.MONO_TINY(), text_color=Colors.BUY)
        self.lbl_calc_lots.pack(side="right", padx=s(10))

        # ── Right panel (DPI-aware width) ─────────────────────────────
        RIGHT_W = S.RIGHT_W()
        right_panel = ctk.CTkFrame(body, fg_color="transparent", width=RIGHT_W)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(3, 6), pady=S.XS())
        right_panel.grid_propagate(False)
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(0, weight=2)   # watchlist
        right_panel.grid_rowconfigure(1, weight=2)   # news
        right_panel.grid_rowconfigure(2, weight=1)   # sessions

        # Watchlist mini-panel
        wl_frame = ctk.CTkFrame(right_panel, fg_color=Colors.CARD_BG,
                                 border_width=1, border_color=Colors.BORDER,
                                 corner_radius=s(8))
        wl_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 3))
        wl_frame.grid_rowconfigure(2, weight=1)   # row=2 holds the scrollable list
        wl_frame.grid_columnconfigure(0, weight=1)

        wl_hdr = ctk.CTkFrame(wl_frame, fg_color="transparent")
        wl_hdr.grid(row=0, column=0, sticky="ew", padx=s(10), pady=(8, 4))
        ctk.CTkLabel(wl_hdr, text="Watchlist",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(wl_hdr, text="+", width=S.ICON_BTN(), height=s(24), corner_radius=s(5),
                      fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                      text_color=Colors.TEXT, font=SF.SUBHEADER(),
                      command=lambda: self.show_page("watchlist"),
                      ).pack(side="right", padx=(0, 2))

        # Watchlist column headers
        wl_cols = ctk.CTkFrame(wl_frame, fg_color=Colors.WELL_BG)
        wl_cols.grid(row=1, column=0, sticky="ew", padx=6)
        for i, (txt, w) in enumerate([("Symbol", 3), ("Last Price", 3),
                                        ("Change", 3), ("% Change", 2)]):
            wl_cols.grid_columnconfigure(i, weight=w)
            ctk.CTkLabel(wl_cols, text=txt, font=SF.STATUS_BOLD(),
                         text_color=Colors.LABEL).grid(row=0, column=i,
                                                        sticky="w", padx=S.XS(), pady=3)

        # Watchlist data rows container
        self._wl_scroll = ctk.CTkScrollableFrame(
            wl_frame, fg_color="transparent", height=140,
            scrollbar_button_color=Colors.BORDER)
        self._wl_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self._wl_scroll.grid_columnconfigure(0, weight=1)
        self._wl_rows: list[dict] = []
        # Empty state — live prices load once the data pipeline connects
        _wl_empty = ctk.CTkFrame(self._wl_scroll, fg_color="transparent")
        _wl_empty.pack(fill="x", pady=S.SM())
        ctk.CTkLabel(
            _wl_empty,
            text="⏳  Loading prices…",
            font=SF.STATUS(),
            text_color=Colors.TEXT_MUTED,
        ).pack(anchor="w", padx=S.SM())
        ctk.CTkLabel(
            _wl_empty,
            text="Configure an API key in Settings for live prices.",
            font=SF.NANO(),
            text_color=Colors.LABEL,
            wraplength=s(230),
            justify="left",
        ).pack(anchor="w", padx=S.SM(), pady=(2, 0))
        self._wl_empty_frame = _wl_empty

        # Market News mini-panel
        news_frame = ctk.CTkFrame(right_panel, fg_color=Colors.CARD_BG,
                                   border_width=1, border_color=Colors.BORDER,
                                   corner_radius=s(8))
        news_frame.grid(row=1, column=0, sticky="nsew", pady=3)
        news_frame.grid_rowconfigure(1, weight=1)
        news_frame.grid_columnconfigure(0, weight=1)

        news_hdr = ctk.CTkFrame(news_frame, fg_color="transparent")
        news_hdr.grid(row=0, column=0, sticky="ew", padx=s(10), pady=(8, 4))
        ctk.CTkLabel(news_hdr, text="Market News",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")
        for icon in ("≡", "📅"):
            ctk.CTkButton(news_hdr, text=icon, width=26, height=s(24), corner_radius=s(4),
                          fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                          text_color=Colors.TEXT_MUTED, font=SF.NAV(),
                          command=lambda: self.show_page("news"),
                          ).pack(side="right", padx=2)

        self._dash_news_scroll = ctk.CTkScrollableFrame(
            news_frame, fg_color="transparent", height=130,
            scrollbar_button_color=Colors.BORDER)
        self._dash_news_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self._dash_news_items = []
        # Empty state — real headlines load from the news service
        _news_empty = ctk.CTkFrame(self._dash_news_scroll, fg_color="transparent")
        _news_empty.pack(fill="x", pady=S.SM())
        ctk.CTkLabel(
            _news_empty,
            text="⏳  Loading market news…",
            font=SF.STATUS(),
            text_color=Colors.TEXT_MUTED,
        ).pack(anchor="w", padx=S.SM())
        ctk.CTkLabel(
            _news_empty,
            text="Add a Finnhub API key in Settings to enable live news.",
            font=SF.NANO(),
            text_color=Colors.LABEL,
            wraplength=s(230),
            justify="left",
        ).pack(anchor="w", padx=S.SM(), pady=(2, 0))
        self._dash_news_empty_frame = _news_empty

        # Market Sessions mini-panel
        sess_frame = ctk.CTkFrame(right_panel, fg_color=Colors.CARD_BG,
                                   border_width=1, border_color=Colors.BORDER,
                                   corner_radius=s(8))
        sess_frame.grid(row=2, column=0, sticky="nsew", pady=(3, 0))
        sess_hdr = ctk.CTkFrame(sess_frame, fg_color="transparent")
        sess_hdr.pack(fill="x", padx=s(10), pady=(8, 4))
        ctk.CTkLabel(sess_hdr, text="Market Sessions",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(sess_hdr, text="View Full", width=64, height=s(22),
                      corner_radius=s(4), fg_color=Colors.CARD_BG_ALT,
                      hover_color=Colors.HOVER, text_color=Colors.PRIMARY,
                      font=SF.STATUS_BOLD(),
                      command=lambda: self.show_page("market_sessions"),
                      ).pack(side="right")

        # Session pills — live auto-refresh every 60 s
        sess_body = ctk.CTkFrame(sess_frame, fg_color="transparent")
        sess_body.pack(fill="x", padx=S.SM(), pady=(0, 8))
        _SESSIONS_DISP = [
            ("🇦🇺 Sydney",    22,  7, "22:00–07:00"),
            ("🇯🇵 Tokyo",      0,  9, "00:00–09:00"),
            ("🇬🇧 London",     8, 17, "08:00–17:00"),
            ("🇺🇸 New York",  13, 22, "13:00–22:00"),
        ]
        self._dash_sess_dot_labels:  list[ctk.CTkLabel] = []
        self._dash_sess_name_labels: list[ctk.CTkLabel] = []
        self._dash_sess_meta = _SESSIONS_DISP   # keep reference for tick
        for sname, s_open, s_close, stime in _SESSIONS_DISP:
            pill = ctk.CTkFrame(sess_body, fg_color=Colors.WELL_BG, corner_radius=s(5))
            pill.pack(fill="x", pady=1)
            dot_lbl = ctk.CTkLabel(pill, text="○",
                         font=SF.TINY(), text_color=Colors.TEXT_MUTED)
            dot_lbl.pack(side="left", padx=(8, 4), pady=S.XS())
            name_lbl = ctk.CTkLabel(pill, text=sname, font=SF.STATUS_BOLD(),
                         text_color=Colors.TEXT_MUTED)
            name_lbl.pack(side="left")
            ctk.CTkLabel(pill, text=stime, font=SF.MONO_TINY(),
                         text_color=Colors.TEXT_MUTED).pack(side="right", padx=S.SM())
            self._dash_sess_dot_labels.append(dot_lbl)
            self._dash_sess_name_labels.append(name_lbl)
        # Kick off live tick immediately
        self._dash_sess_tick()

        # ════════════════════════════════════════════════════════════════
        # ROW 3 — AI Signals preview + Market Scanner mini-table
        # ════════════════════════════════════════════════════════════════
        bottom_row = ctk.CTkFrame(page, fg_color="transparent")
        bottom_row.grid(row=3, column=0, sticky="ew", padx=6, pady=(2, 0))
        bottom_row.grid_columnconfigure(0, weight=5)   # AI Signals
        bottom_row.grid_columnconfigure(1, weight=4)   # Market Scanner
        bottom_row.grid_rowconfigure(0, weight=1)

        # ── AI Signals preview ────────────────────────────────────────
        sig_panel = ctk.CTkFrame(bottom_row, fg_color=Colors.CARD_BG,
                                  border_width=1, border_color=Colors.BORDER,
                                  corner_radius=s(8))
        sig_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 3), pady=(0, 4))
        sig_panel.grid_columnconfigure(0, weight=1)
        sig_panel.grid_columnconfigure(1, weight=1)
        sig_panel.grid_rowconfigure(0, weight=0)   # header — fixed
        sig_panel.grid_rowconfigure(1, weight=1)   # signal cards — expands

        sig_hdr = ctk.CTkFrame(sig_panel, fg_color="transparent")
        sig_hdr.grid(row=0, column=0, columnspan=2, sticky="ew", padx=s(10), pady=(8, 4))
        ctk.CTkLabel(sig_hdr, text="AI Signals",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(sig_hdr, text="View All", width=64, height=s(22),
                      corner_radius=s(4), fg_color="transparent",
                      hover_color=Colors.HOVER, text_color=Colors.PRIMARY,
                      font=SF.STATUS_BOLD(),
                      command=lambda: self.show_page("ai_signals"),
                      ).pack(side="right")

        # Live signal cards container — updated by _update_dash_ai_signals()
        self._dash_sig_container = ctk.CTkFrame(sig_panel, fg_color="transparent")
        self._dash_sig_container.grid(row=1, column=0, columnspan=2, sticky="nsew",
                                       padx=6, pady=(0, 6))
        self._dash_sig_container.grid_columnconfigure(0, weight=1)
        self._dash_sig_container.grid_columnconfigure(1, weight=1)

        # Placeholder until first scanner result arrives
        self._dash_sig_placeholder = ctk.CTkLabel(
            self._dash_sig_container,
            text="⏳  Scanning markets for AI signals…\nSignals appear when the engine finds high-probability setups.",
            font=SF.TINY(), text_color=Colors.TEXT_MUTED, justify="center")
        self._dash_sig_placeholder.grid(row=0, column=0, columnspan=2, padx=s(10), pady=20)

        # ── Market Scanner mini-table ─────────────────────────────────
        ms_panel = ctk.CTkFrame(bottom_row, fg_color=Colors.CARD_BG,
                                 border_width=1, border_color=Colors.BORDER,
                                 corner_radius=s(8))
        ms_panel.grid(row=0, column=1, sticky="nsew", padx=(3, 0), pady=(0, 4))

        ms_hdr = ctk.CTkFrame(ms_panel, fg_color="transparent")
        ms_hdr.pack(fill="x", padx=s(10), pady=(8, 4))
        ctk.CTkLabel(ms_hdr, text="Market Scanner",
                     font=SF.SUBHEADER(), text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(ms_hdr, text="View All", width=64, height=s(22),
                      corner_radius=s(4), fg_color="transparent",
                      hover_color=Colors.HOVER, text_color=Colors.PRIMARY,
                      font=SF.STATUS_BOLD(),
                      command=lambda: self.show_page("market_scanner"),
                      ).pack(side="right")

        ms_cols_f = ctk.CTkFrame(ms_panel, fg_color=Colors.WELL_BG)
        ms_cols_f.pack(fill="x", padx=S.SM())
        for i, (txt, w) in enumerate([("Symbol", 2), ("Dir", 1),
                                        ("Signal", 2), ("Conf%", 2),
                                        ("Trend", 2), ("TF", 2),
                                        ("Entry", 3)]):
            ms_cols_f.grid_columnconfigure(i, weight=w)
            ctk.CTkLabel(ms_cols_f, text=txt, font=SF.STATUS_BOLD(),
                         text_color=Colors.LABEL).grid(row=0, column=i,
                                                        sticky="w", padx=S.XS(), pady=3)

        self._dash_ms_scroll = ctk.CTkScrollableFrame(ms_panel, fg_color="transparent",
                                                       scrollbar_button_color=Colors.BORDER,
                                                       height=110)
        self._dash_ms_scroll.pack(fill="both", expand=True, padx=S.SM(), pady=(0, 6))
        bind_fast_scroll(self._dash_ms_scroll)

        # Placeholder label until scanner data arrives
        self._dash_ms_placeholder = ctk.CTkLabel(
            self._dash_ms_scroll,
            text="⏳  Waiting for scanner data…",
            font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self._dash_ms_placeholder.pack(padx=s(10), pady=s(12))

        # ════════════════════════════════════════════════════════════════
        # ROW 4 — Bottom status bar
        # ════════════════════════════════════════════════════════════════
        self._dash_status_bar = ctk.CTkFrame(
            page, fg_color=Colors.SIDEBAR_BG, height=s(26),
            corner_radius=0, border_width=0)
        self._dash_status_bar.grid(row=4, column=0, sticky="ew")
        self._dash_status_bar.grid_propagate(False)

        def _status_pill(parent, label_text, value_text, val_color, side="left", padx=s(10)):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(side=side, padx=padx, pady=3)
            ctk.CTkLabel(f, text=label_text, font=SF.STATUS(),
                         text_color=Colors.TEXT_MUTED).pack(side="left")
            ctk.CTkLabel(f, text=" " + value_text, font=SF.STATUS_BOLD(),
                         text_color=val_color).pack(side="left")

        _status_pill(self._dash_status_bar, "AI Status:", "● ONLINE", Colors.BUY, padx=S.SM())
        _status_pill(self._dash_status_bar, "API Status:", "● CONNECTED", Colors.BUY)
        _status_pill(self._dash_status_bar, "Scanner:", "● RUNNING", Colors.BUY)
        _status_pill(self._dash_status_bar, "Paper Trader:", "● ACTIVE", Colors.BUY)

        self._lbl_status_bar_info = ctk.CTkLabel(   # hidden sync label — pipeline writes here too
            self._dash_status_bar, text="",
            font=SF.MONO_TINY(), text_color=Colors.TEXT_MUTED)
        self._lbl_status_bar_info.pack(side="left", padx=S.SM())

        # Right side: Latency + CPU + RAM + clock
        import time as _time
        self._dash_clock = ctk.CTkLabel(
            self._dash_status_bar,
            text=_time.strftime("%H:%M:%S  %d/%m/%Y"),
            font=SF.MONO_TINY(), text_color=Colors.TEXT_SECONDARY)
        self._dash_clock.pack(side="right", padx=s(10))

        # RAM label — live updatable
        _ram_f = ctk.CTkFrame(self._dash_status_bar, fg_color="transparent")
        _ram_f.pack(side="right", padx=6, pady=3)
        ctk.CTkLabel(_ram_f, text="RAM:", font=SF.STATUS(),
                     text_color=Colors.TEXT_MUTED).pack(side="left")
        self._lbl_status_ram = ctk.CTkLabel(_ram_f, text=" — MB", font=SF.STATUS_BOLD(),
                                             text_color=Colors.TEXT_MUTED)
        self._lbl_status_ram.pack(side="left")

        # CPU label — live updatable
        _cpu_f = ctk.CTkFrame(self._dash_status_bar, fg_color="transparent")
        _cpu_f.pack(side="right", padx=6, pady=3)
        ctk.CTkLabel(_cpu_f, text="CPU:", font=SF.STATUS(),
                     text_color=Colors.TEXT_MUTED).pack(side="left")
        self._lbl_status_cpu = ctk.CTkLabel(_cpu_f, text=" —%", font=SF.STATUS_BOLD(),
                                             text_color=Colors.TEXT_MUTED)
        self._lbl_status_cpu.pack(side="left")

        # Latency label — live updatable
        _lat_f = ctk.CTkFrame(self._dash_status_bar, fg_color="transparent")
        _lat_f.pack(side="right", padx=6, pady=3)
        ctk.CTkLabel(_lat_f, text="Latency:", font=SF.STATUS(),
                     text_color=Colors.TEXT_MUTED).pack(side="left")
        self._lbl_status_latency = ctk.CTkLabel(_lat_f, text=" —ms", font=SF.STATUS_BOLD(),
                                                 text_color=Colors.BUY)
        self._lbl_status_latency.pack(side="left")

        # Risk segmented button stays accessible
        self.risk_segment = ctk.CTkSegmentedButton(
            self._dash_status_bar, values=["0.5%", "1.0%", "2.0%"],
            command=self.modify_firm_risk_exposure,
            fg_color=Colors.CARD_BG, selected_color=Colors.PRIMARY,
            unselected_color=Colors.CARD_BG,
            text_color=Colors.TEXT_SECONDARY,
            font=SF.STATUS_BOLD(), width=s(140), height=20)
        self.risk_segment.set("1.0%")
        self.risk_segment.pack(side="right", padx=S.SM())

        # Kick off clock update loop
        self._dash_clock_tick()
        # Kick off live system stats (CPU/RAM/Latency) — first reading after 2 s
        self.after(2000, self._dash_sysstat_tick)

    def _dash_clock_tick(self):
        """Update the dashboard clock every second."""
        import time as _t
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if hasattr(self, "_dash_clock"):
            try:
                if self._dash_clock.winfo_exists():
                    self._dash_clock.configure(text=_t.strftime("%H:%M:%S  %d/%m/%Y"))
            except Exception:
                pass
        self.after(1000, self._dash_clock_tick)

    def _dash_sess_tick(self):
        """Refresh dashboard Market Sessions pills every 60 s with live OPEN/CLOSED status."""
        try:
            if not self.winfo_exists():
                return
            from datetime import datetime, timezone as _tz
            _h = datetime.now(_tz.utc).hour
            for i, (sname, s_open, s_close, _stime) in enumerate(self._dash_sess_meta):
                if s_open < s_close:
                    is_open = s_open <= _h < s_close
                else:
                    is_open = _h >= s_open or _h < s_close
                dot  = self._dash_sess_dot_labels[i]
                name = self._dash_sess_name_labels[i]
                dot.configure(text="●" if is_open else "○",
                              text_color=Colors.BUY if is_open else Colors.TEXT_MUTED)
                name.configure(text_color=Colors.TEXT if is_open else Colors.TEXT_MUTED)
        except Exception:
            return
        self.after(60_000, self._dash_sess_tick)

    def _dash_sysstat_tick(self):
        """Refresh status bar CPU, RAM, and Latency every 5 seconds safely."""
        import threading as _thr

        # FIX: Don't spawn a new thread if the old one is still stuck waiting on a network timeout
        if hasattr(self, '_sysstat_thread') and self._sysstat_thread.is_alive():
            self.after(5000, self._dash_sysstat_tick)
            return

        def _collect():
            lat_ms, cpu_pct, ram_mb = "—", "—", "—"
            try:
                import psutil as _ps
                cpu_pct = f"{_ps.cpu_percent(interval=0.5):.0f}%"
                mem = _ps.virtual_memory()
                ram_mb  = f"{mem.used // 1_048_576} MB / {mem.total // 1_048_576} MB"
            except Exception:
                pass
            try:
                import socket, time as _t
                _t0 = _t.monotonic()
                s = socket.create_connection(("api.binance.com", 443), timeout=3)
                s.close()
                lat_ms = f"{int((_t.monotonic() - _t0) * 1000)}ms"
            except Exception:
                pass
            
            try:
                if self.winfo_exists():
                    self.after(0, lambda: self._apply_sysstat(lat_ms, cpu_pct, ram_mb))
            except Exception:
                pass

        self._sysstat_thread = _thr.Thread(target=_collect, daemon=True)
        self._sysstat_thread.start()
        
        try:
            if self.winfo_exists():
                self.after(5000, self._dash_sysstat_tick)
        except Exception:
            pass

    def _apply_sysstat(self, lat_ms: str, cpu_pct: str, ram_mb: str):
        try:
            if hasattr(self, "_lbl_status_latency"):
                lat_color = Colors.BUY
                try:
                    v = int(lat_ms.replace("ms",""))
                    lat_color = Colors.BUY if v < 100 else Colors.NEUTRAL if v < 300 else Colors.SELL
                except Exception:
                    lat_color = Colors.TEXT_MUTED
                self._lbl_status_latency.configure(text=f" {lat_ms}", text_color=lat_color)
            if hasattr(self, "_lbl_status_cpu"):
                cpu_color = Colors.TEXT_MUTED
                try:
                    v = float(cpu_pct.replace("%",""))
                    cpu_color = Colors.BUY if v < 50 else Colors.NEUTRAL if v < 80 else Colors.SELL
                except Exception:
                    pass
                self._lbl_status_cpu.configure(text=f" {cpu_pct}", text_color=cpu_color)
            if hasattr(self, "_lbl_status_ram"):
                self._lbl_status_ram.configure(text=f" {ram_mb}")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────
    # AI Signals page
    # ─────────────────────────────────────────────────────────────────
    def _build_ai_signals_page(self):
        page = ctk.CTkScrollableFrame(
            self.page_host, fg_color=Colors.APP_BG, corner_radius=0,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY,
        )
        page.grid_columnconfigure(0, weight=1)
        self._register_page("ai_signals", page)
        bind_fast_scroll(page)

        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(),
                 pady=(Spacing.LG(), Spacing.MD()))
        ctk.CTkLabel(hdr, text="AI SIGNALS", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")
        self.lbl_active_signal_count = ctk.CTkLabel(
            hdr, text="", font=SF.NAV_BOLD(),
            text_color=Colors.ON_BUY, fg_color=Colors.BUY,
            corner_radius=s(10), padx=S.SM(), pady=2)
        self.lbl_active_signal_count.pack(side="left", padx=s(10))

        # Scanner controls on right
        ctrl_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        ctrl_frame.pack(side="right")

        self._btn_scanner_pause = ctk.CTkButton(
            ctrl_frame, text="⏸ Pause Scanner", width=s(130), height=s(28), corner_radius=s(6),
            fg_color=Colors.NEUTRAL, hover_color=Colors.HOVER_STRONG,
            text_color=Colors.TEXT, font=SF.PILL_LG(),
            command=self._toggle_scanner_pause)
        self._btn_scanner_pause.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            ctrl_frame, text="⟳ Refresh", width=s(90), height=s(28), corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=self._refresh_signal_engine_panel,
        ).pack(side="left")

        self.ai_panel = AIPanel(page)
        self.ai_panel.grid(row=1, column=0, sticky="ew",
                            padx=Spacing.LG(), pady=(0, Spacing.LG()))

        self.signal_engine_panel = SignalEnginePanel(
            page, get_account_context=self.get_account_risk_context)
        self.signal_engine_panel.grid(row=2, column=0, sticky="ew",
                                       padx=Spacing.LG(), pady=(0, Spacing.LG()))

    # ─────────────────────────────────────────────────────────────────
    # Signal History
    # ─────────────────────────────────────────────────────────────────
    def _build_signal_history_page(self):
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self._register_page("signal_history", page)

        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(),
                 pady=(Spacing.LG(), Spacing.MD()))
        ctk.CTkLabel(hdr, text="SIGNAL HISTORY", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(
            hdr, text="⟳ Refresh", width=s(90), height=s(28), corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=lambda: self.signal_history_panel._trigger_refresh() if hasattr(self, "signal_history_panel") else None,
        ).pack(side="right")

        self.signal_history_panel = SignalHistoryPanel(page)
        self.signal_history_panel.grid(row=1, column=0, sticky="nsew",
                                        padx=Spacing.LG(), pady=(0, Spacing.LG()))

    # ─────────────────────────────────────────────────────────────────
    # Market Scanner (auto, dedicated page)
    # ─────────────────────────────────────────────────────────────────
    def _build_market_scanner_page(self):
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self._register_page("market_scanner", page)
        self.market_scanner_page = MarketScannerPage(
            page,
            market_scanner=self.market_scanner,
            get_account_context=self.get_account_risk_context,
            signal_engine=self.signal_engine,
        )
        self.market_scanner_page.grid(row=0, column=0, sticky="nsew")

    # ─────────────────────────────────────────────────────────────────
    # Manual Scanner (new dedicated page)
    # ─────────────────────────────────────────────────────────────────
    def _build_manual_scanner_page(self):
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self._register_page("manual_scanner", page)
        self.manual_scanner_page = ManualScannerPage(
            page,
            crypto_service=self.crypto_service,
            signal_engine=self.signal_engine,
            market_analyzer=self.market_analyzer,
            get_account_context=self.get_account_risk_context,
            on_apply_to_algo=self._apply_signal_to_algo,
            on_auto_ai_apply=self._apply_signal_to_algo,
        )
        self.manual_scanner_page.grid(row=0, column=0, sticky="nsew")

    # ─────────────────────────────────────────────────────────────────
    # Order Execution
    # ─────────────────────────────────────────────────────────────────
    def _build_order_execution_page(self):
        page = ctk.CTkScrollableFrame(
            self.page_host, fg_color=Colors.APP_BG, corner_radius=0,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY,
        )
        page.grid_columnconfigure(0, weight=1)
        self._register_page("order_execution", page)
        bind_fast_scroll(page)

        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(),
                 pady=(Spacing.LG(), Spacing.MD()))
        ctk.CTkLabel(hdr, text="ORDER EXECUTION", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(
            hdr, text="⟳ Refresh", width=s(90), height=s(28), corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=self._refresh_trade_journal,
        ).pack(side="right")

        self.trade_panel = TradePanel(
            page,
            on_execute_order=self.execute_market_order_callback,
            on_close_position=self.close_position_callback,
        )
        self.trade_panel.grid(row=1, column=0, sticky="ew",
                               padx=Spacing.LG(), pady=(0, Spacing.LG()))
        self.trade_journal_panel = TradeJournalPanel(page)
        self.trade_journal_panel.grid(row=2, column=0, sticky="ew",
                                       padx=Spacing.LG(), pady=(0, Spacing.LG()))

    # ─────────────────────────────────────────────────────────────────
    # Algo Trading
    # ─────────────────────────────────────────────────────────────────
    def _build_algo_trading_page(self):
        page = ctk.CTkScrollableFrame(
            self.page_host, fg_color=Colors.APP_BG, corner_radius=0,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY,
        )
        page.grid_columnconfigure(0, weight=1)
        self._register_page("algo_trading", page)
        bind_fast_scroll(page)

        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(),
                 pady=(Spacing.LG(), Spacing.MD()))
        ctk.CTkLabel(hdr, text="ALGO TRADING", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(
            hdr, text="⟳ Refresh", width=s(90), height=s(28), corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=lambda: self.algo_trading_panel._refresh() if hasattr(self, "algo_trading_panel") else None,
        ).pack(side="right")

        self.algo_trading_panel = AlgoTradingPanel(page, engine=self.paper_trading_engine)
        self.algo_trading_panel.grid(row=1, column=0, sticky="ew",
                                      padx=Spacing.LG(), pady=(0, Spacing.LG()))

    # ─────────────────────────────────────────────────────────────────
    # Paper Trading History
    # ─────────────────────────────────────────────────────────────────
    def _build_trade_history_page(self):
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self._register_page("trade_history", page)

        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(),
                 pady=(Spacing.LG(), Spacing.MD()))
        ctk.CTkLabel(hdr, text="PAPER TRADING HISTORY", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(
            hdr, text="⟳ Refresh", width=s(90), height=s(28), corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=lambda: self.paper_trading_history_panel._refresh() if hasattr(self, "paper_trading_history_panel") else None,
        ).pack(side="right")

        self.paper_trading_history_panel = PaperTradingHistoryPanel(
            page, engine=self.paper_trading_engine)
        self.paper_trading_history_panel.grid(row=1, column=0, sticky="nsew",
                                               padx=Spacing.LG(), pady=(0, Spacing.LG()))

    # ─────────────────────────────────────────────────────────────────
    # Watchlist page
    # ─────────────────────────────────────────────────────────────────
    def _build_watchlist_page(self):
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self._register_page("watchlist", page)
        self.watchlist_page = WatchlistPage(
            page, on_asset_click=self.change_coin_from_watchlist)
        self.watchlist_page.grid(row=0, column=0, sticky="nsew")

    # ─────────────────────────────────────────────────────────────────
    # News page
    # ─────────────────────────────────────────────────────────────────
    def _build_news_page(self):
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self._register_page("news", page)
        self.news_page = NewsPage(
            page, on_news_click=self.display_macro_intelligence_modal)
        self.news_page.grid(row=0, column=0, sticky="nsew")

    # ─────────────────────────────────────────────────────────────────
    # Risk Tools page (new)
    # ─────────────────────────────────────────────────────────────────
    def _build_risk_tools_page(self):
        page = ctk.CTkScrollableFrame(
            self.page_host, fg_color=Colors.APP_BG, corner_radius=0,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY,
        )
        page.grid_columnconfigure(0, weight=1)
        self._register_page("risk_tools", page)
        bind_fast_scroll(page)
        ctk.CTkLabel(page, text="RISK MANAGEMENT TOOLS", font=SF.TITLE(),
                     text_color=Colors.TEXT).grid(
            row=0, column=0, sticky="w",
            padx=Spacing.LG(), pady=(Spacing.LG(), Spacing.MD()))
        self.risk_tools_panel = RiskToolsPanel(
            page, get_account_context=self.get_account_risk_context)
        self.risk_tools_panel.grid(row=1, column=0, sticky="ew",
                                    padx=Spacing.LG(), pady=(0, Spacing.LG()))

    # ─────────────────────────────────────────────────────────────────
    # System Status page (new)
    # ─────────────────────────────────────────────────────────────────
    def _build_system_status_page(self):
        page = ctk.CTkScrollableFrame(
            self.page_host, fg_color=Colors.APP_BG, corner_radius=0,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY,
        )
        page.grid_columnconfigure(0, weight=1)
        self._register_page("system_status", page)
        bind_fast_scroll(page)
        ctk.CTkLabel(page, text="SYSTEM STATUS", font=SF.TITLE(),
                     text_color=Colors.TEXT).grid(
            row=0, column=0, sticky="w",
            padx=Spacing.LG(), pady=(Spacing.LG(), Spacing.MD()))
        self.system_status_panel = SystemStatusPanel(
            page,
            crypto_service=self.crypto_service,
            market_scanner=self.market_scanner,
            paper_trading_engine=self.paper_trading_engine,
        )
        self.system_status_panel.grid(row=1, column=0, sticky="ew",
                                       padx=Spacing.LG(), pady=(0, Spacing.LG()))

    # ─────────────────────────────────────────────────────────────────
    # Market Sessions dedicated page
    # ─────────────────────────────────────────────────────────────────
    def _build_market_sessions_page(self):
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self._register_page("market_sessions", page)
        self.market_sessions_page = MarketSessionsPage(page)
        self.market_sessions_page.grid(row=0, column=0, sticky="nsew")

    # ─────────────────────────────────────────────────────────────────
    # Knowledge & Tips
    # ─────────────────────────────────────────────────────────────────
    def _build_knowledge_page(self):
        page = ctk.CTkFrame(self.page_host, fg_color=Colors.APP_BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self._register_page("knowledge", page)
        self.knowledge_page = KnowledgePage(page)
        self.knowledge_page.grid(row=0, column=0, sticky="nsew")

    # ─────────────────────────────────────────────────────────────────
    # Settings
    # ─────────────────────────────────────────────────────────────────
    def _build_settings_page(self):
        page = ctk.CTkScrollableFrame(
            self.page_host, fg_color=Colors.APP_BG, corner_radius=0,
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY,
        )
        page.grid_columnconfigure(0, weight=1)
        self._register_page("settings", page)
        bind_fast_scroll(page)
        ctk.CTkLabel(page, text="SETTINGS", font=SF.TITLE(),
                     text_color=Colors.TEXT).grid(
            row=0, column=0, sticky="w",
            padx=Spacing.LG(), pady=(Spacing.LG(), Spacing.MD()))
        self.settings_panel = SettingsPanel(page, on_saved=self._on_data_source_changed)
        self.settings_panel.grid(row=1, column=0, sticky="ew",
                                  padx=Spacing.LG(), pady=(0, Spacing.LG()))

    def _on_data_source_changed(self, provider):
        self.crypto_service.set_provider(provider)

    def _toggle_scanner_pause(self):
        """Pause or resume the auto market scanner."""
        if not hasattr(self, "_btn_scanner_pause"):
            return
        if self.market_scanner.is_paused():
            self.market_scanner.resume()
            self._btn_scanner_pause.configure(text="⏸ Pause Scanner",
                                               fg_color=Colors.NEUTRAL)
        else:
            self.market_scanner.pause()
            self._btn_scanner_pause.configure(text="▶ Resume Scanner",
                                               fg_color=Colors.BUY)

    # ─────────────────────────────────────────────────────────────────
    # Apply signal to algo trading
    # ─────────────────────────────────────────────────────────────────
    def _apply_signal_to_algo(self, signal, max_duration_minutes: float = 0.0):
        """Called from ManualScannerPage when user clicks 'Apply to Algo'."""
        try:
            result_msg = self.paper_trading_engine.open_trade_from_signal(
                signal, max_duration_minutes=max_duration_minutes
            )
            self.show_page("algo_trading")
            nc.push(
                "paper_trade",
                "📄 Paper Trade Opened",
                result_msg,
                data=signal.to_dict() if hasattr(signal, "to_dict") else {},
            )
        except Exception as e:
            from utils.logger import logger
            logger.warning(f"[apply_to_algo] {type(e).__name__}: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Signal badge + popup
    # ─────────────────────────────────────────────────────────────────
    def _on_new_scanner_signal(self, signal):
        self._safe_after(0, self._update_signal_badge)

    def _update_signal_badge(self):
        count = self.market_scanner.get_active_signal_count()
        key = "ai_signals"
        if count > 0:
            if hasattr(self, "lbl_active_signal_count"):
                self.lbl_active_signal_count.configure(text=f" {count} active ")
            if key in self.nav_buttons:
                self.nav_buttons[key].configure(text=f"🤖  AI Signals  [{count}]")
        else:
            if hasattr(self, "lbl_active_signal_count"):
                self.lbl_active_signal_count.configure(text="")
            if key in self.nav_buttons:
                self.nav_buttons[key].configure(text="🤖  AI Signals")

    def _schedule_signal_popup(self, notification):
        now = time.time()
        if now - self._last_popup_time < _POPUP_COOLDOWN:
            return
        # Check user notification preference
        try:
            from ui.settings_panel import SettingsPanel as _SP
            prefs = _SP.load_notif_prefs()
            if not prefs.get("notif_ai_signal", True):
                return   # user disabled AI signal popups
        except Exception:
            pass
        self._last_popup_time = now
        self.after(0, lambda: self._show_signal_popup(notification))

    def _show_signal_popup(self, notification):
        try:
            # Check notification pref again on main thread
            try:
                from ui.settings_panel import SettingsPanel as _SP
                prefs = _SP.load_notif_prefs()
            except Exception:
                prefs = {}

            popup = ctk.CTkToplevel(self)
            popup.withdraw()  # FIX: hide until fully built to prevent black flash
            popup.overrideredirect(True)
            popup.configure(fg_color=Colors.CARD_BG)
            rx = self.winfo_rootx() + self.winfo_width() - 380
            ry = self.winfo_rooty() + 56
            popup.geometry(f"360x84+{rx}+{ry}")
            inner = ctk.CTkFrame(popup, fg_color=Colors.SIDEBAR_BG,
                                  border_width=1, border_color=Colors.BUY, corner_radius=s(8))
            inner.pack(fill="both", expand=True, padx=2, pady=2)
            ctk.CTkLabel(inner, text=notification.title,
                         font=SF.NAV_BOLD(),
                         text_color=Colors.BUY).pack(anchor="w", padx=s(12), pady=(8, 2))
            ctk.CTkLabel(inner, text=notification.message,
                         font=SF.TINY(), text_color=Colors.TEXT_SECONDARY,
                         wraplength=s(330), anchor="w", justify="left").pack(
                anchor="w", padx=s(12), pady=(0, 8))
            # FIX: Deiconify after 10ms so the window is fully composed before showing
            popup.after(10, lambda: (
                popup.deiconify() if popup.winfo_exists() else None,
                popup.attributes("-topmost", True) if popup.winfo_exists() else None
            ))
            popup.after(5000, lambda: popup.destroy() if popup.winfo_exists() else None)
            inner.bind("<Button-1>", lambda e: popup.destroy())

            # Play sound if enabled
            if prefs.get("notif_sound", True):
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:
                    try:
                        import subprocess
                        subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────
    # Resize
    # ─────────────────────────────────────────────────────────────────
    def _on_root_resize(self, event):
        """Debounced resize handler — updates scaling factor then syncs chart."""
        if event.widget is not self:
            return
            
        # FIX: Only trigger if the dimensions actually changed, ignore window dragging
        if not hasattr(self, '_last_geom'):
            self._last_geom = (event.width, event.height)
        elif self._last_geom == (event.width, event.height):
            return 
        self._last_geom = (event.width, event.height)

        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(150, self._do_adaptive_resize)

    def _do_adaptive_resize(self):
        """
        Called ~300 ms after a resize event settles (delay raised to capture
        post-zoom geometry from the window manager).
        """
        self._resize_after_id = None
        try:
            from ui import scaling as _sc
            from ui.scaling import S, SF, s, sidebar_wrap, compute_min_size

            # Re-measure first so S.* values reflect the new window size
            _sc._measure(self)

            # Update sidebar frame width
            if hasattr(self, "sidebar_frame"):
                self.sidebar_frame.configure(width=S.SIDEBAR_W())

            # Update sync label wraplength
            if hasattr(self, "lbl_last_sync"):
                self.lbl_last_sync.configure(wraplength=sidebar_wrap())

            # Update min window size for the current DPI
            mw, mh = compute_min_size()
            self.minsize(mw, mh)

        except Exception:
            pass
        self._sync_chart_height_to_window()

    def _sync_chart_height_to_window(self):
        # FIX: Removed the self.update_idletasks() that was causing the infinite loop
        win_h = self.winfo_height()
        if win_h < 300:
            return
            
        fixed_h = 0
        try:
            page = self.pages.get("dashboard")
            if page:
                for child in page.winfo_children():
                    info = child.grid_info()
                    if not info:
                        continue
                    row = info.get("row", -1)
                    if row in (0, 1, 3, 4):   
                        fixed_h += child.winfo_height()
        except Exception:
            fixed_h = 338   

        new_h = max(300, win_h - fixed_h - 16) 
        if abs(new_h - self._current_chart_height) > 8:
            self._current_chart_height = new_h
            try:
                self.chart_widget.configure(height=new_h)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────
    # Order execution callbacks
    # ─────────────────────────────────────────────────────────────────
    def execute_market_order_callback(self, asset, side, price, sl=0.0, tp=0.0):
        if price <= 0:
            return
        raw_units = self.current_suggested_units_raw or 10_000.0
        size_label = self.current_suggested_size_text.replace("SUGGESTED SIZE: ", "")
        self.active_positions.append({
            "id": int(time.time() * 1000),
            "asset": asset, "side": side,
            "strategy": self.current_strategy,
            "entry": price, "sl": sl, "tp": tp,
            "units": raw_units, "size_text": size_label,
            "pnl": 0.0, "leverage": lm.get_leverage(asset),
            "opened_at": time.time(),
        })
        self._recalculate_portfolio_exposure(price)

    def _format_size_text(self, asset, units):
        if "/" in asset and "XAU" not in asset:
            return f"{units/100_000:.2f} LOTS"
        return f"{units:.2f} UNITS"

    def close_position_callback(self, position_id, fraction=1.0):
        fraction = max(0.0, min(1.0, fraction))
        if fraction <= 0:
            return
        for pos in self.active_positions:
            if pos["id"] != position_id:
                continue
            if fraction >= 0.999:
                self.account_balance += pos["pnl"]
                self._log_closed_trade(pos)
                self.active_positions.remove(pos)
            else:
                realized_units = pos["units"] * fraction
                realized_pnl   = pos["pnl"]   * fraction
                self.account_balance += realized_pnl
                leg = dict(pos)
                leg["units"] = realized_units
                leg["pnl"]   = realized_pnl
                leg["size_text"] = self._format_size_text(pos["asset"], realized_units)
                self._log_closed_trade(leg)
                pos["units"] -= realized_units
                pos["size_text"] = self._format_size_text(pos["asset"], pos["units"])
            break
        self.lbl_balance.configure(text=f"${self.account_balance:,.2f}")
        if hasattr(self, "lbl_kpi_balance"): self.lbl_kpi_balance.configure(text=f"${self.account_balance:,.2f}")
        self._recalculate_portfolio_exposure(None)

    def _log_closed_trade(self, pos):
        is_fx = "/" in pos["asset"] and "XAU" not in pos["asset"]
        mult   = pos["units"] * 100 if is_fx else pos["units"]
        diff   = (pos["pnl"] / mult) if mult else 0.0
        exit_p = pos["entry"] + diff if pos["side"] == "BUY" else pos["entry"] - diff
        history_service.log_trade({
            "asset": pos["asset"], "side": pos["side"],
            "strategy": pos.get("strategy", self.current_strategy),
            "entry": pos["entry"], "exit": exit_p,
            "size": pos.get("size_text", ""), "pnl": pos["pnl"],
        })
        self._refresh_trade_journal()

    def _refresh_trade_journal(self):
        if not hasattr(self, "trade_journal_panel"):
            return
        csv_trades  = history_service.load_trades(limit=25)
        try:
            db_trades_raw = paper_trading_db.get_trades(status="CLOSED", limit=50)
            db_trades = []
            for t in db_trades_raw:
                import time as _t
                ts = ""
                try:
                    ts = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(float(t["closed_at"] or t["opened_at"])))
                except Exception:
                    pass
                db_trades.append({
                    "timestamp": ts,
                    "asset":     t.get("symbol", ""),
                    "side":      t.get("signal_type", ""),
                    "strategy":  t.get("strategy", ""),
                    "entry":     str(t.get("entry_price", 0.0)),
                    "exit":      str(t.get("exit_price", 0.0)),
                    "size":      t.get("size_label", ""),
                    "pnl":       str(t.get("pnl", 0.0) or 0.0),
                    "result":    t.get("result", ""),
                })
        except Exception:
            db_trades = []

        seen = set()
        merged = []
        for trade in (csv_trades + db_trades):
            key = (trade.get("asset"), trade.get("entry"), trade.get("pnl"))
            if key not in seen:
                seen.add(key)
                merged.append(trade)

        merged.sort(key=lambda t: t.get("timestamp", ""), reverse=True)
        merged = merged[:50]

        pnls = []
        for t in merged:
            try:
                pnls.append(float(t.get("pnl", 0.0)))
            except Exception:
                pass
        wins   = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        total  = len(pnls)
        merged_summary = {
            "total":    total,
            "wins":     wins,
            "losses":   losses,
            "win_rate": (wins / total * 100.0) if total else 0.0,
            "net_pnl":  sum(pnls),
        }

        self.trade_journal_panel.render(merged, merged_summary)

    def _recalculate_portfolio_exposure(self, current_market_price=None):
        total = 0.0
        for pos in self.active_positions:
            tp = (current_market_price if current_market_price and pos["asset"] == self.current_coin
                  else self.latest_watchlist_prices.get(pos["asset"], pos["entry"]))
            pnl = lm.compute_pnl(pos["asset"], pos["side"], pos["entry"], tp, pos["units"])
            pos["pnl"]      = pnl
            pos["notional"] = pos["units"] * tp
            total += pnl

        self.floating_pnl = total
        eq = self.account_balance + total
        ec = Colors.BUY if total > 0 else Colors.SELL if total < 0 else Colors.TEXT_SECONDARY
        sign = "+" if total > 0 else ""
        self.lbl_equity.configure(text=f"${eq:,.2f}", text_color=ec)
        self.lbl_floating_pnl.configure(text=f"{sign}${total:,.2f}", text_color=ec)
        # Also update KPI bar labels if they exist
        if hasattr(self, "lbl_kpi_equity"):
            self.lbl_kpi_equity.configure(text=f"${eq:,.2f}", text_color=ec)
        if hasattr(self, "lbl_kpi_open_pos"):
            self.lbl_kpi_open_pos.configure(
                text=str(len(self.active_positions)),
                text_color=Colors.NEUTRAL if self.active_positions else Colors.TEXT_MUTED)
        if hasattr(self, "trade_panel"):
            self.trade_panel.render_active_positions(self.active_positions)

    def display_macro_intelligence_modal(self, news_item):
        NewsDetailModal(self, news_item)

    def modify_firm_risk_exposure(self, selected):
        pct_map = {"0.5%": 0.005, "1.0%": 0.01, "2.0%": 0.02}
        with self.state_lock:
            self.risk_percentage = pct_map.get(selected, 0.01)
        self.trigger_pipeline()

    def _open_edit_balance_dialog(self):
        dlg = ctk.CTkInputDialog(
            text="Enter your real MT5 account balance (USD):",
            title="Set Account Balance")
        raw = dlg.get_input()
        if not raw:
            return
        try:
            new_bal = float(raw.replace(",", "").replace("$", "").strip())
        except ValueError:
            return
        if new_bal <= 0:
            return
        self.account_balance = new_bal
        provider_settings.save_account_balance(new_bal)
        self.lbl_balance.configure(text=f"${new_bal:,.2f}")
        if hasattr(self, "lbl_kpi_balance"): self.lbl_kpi_balance.configure(text=f"${new_bal:,.2f}")
        self.lbl_equity.configure(text=f"${new_bal + self.floating_pnl:,.2f}")
        if hasattr(self, "lbl_kpi_equity"): self.lbl_kpi_equity.configure(text=f"${new_bal + self.floating_pnl:,.2f}")

    def _schedule_journal_refresh(self):
        if not self.winfo_exists():
            return
        self._refresh_trade_journal()
        self.after(10_000, self._schedule_journal_refresh)

    def get_account_risk_context(self):
        return self.account_balance, self.risk_percentage

    def get_state_snapshot(self):
        with self.state_lock:
            return (self.current_coin, self.current_timeframe,
                    self.current_strategy, self.state_version)

    def change_coin(self, coin):
        with self.state_lock:
            self.current_coin = coin
            self.state_version += 1
        self.trigger_pipeline()

    def change_coin_from_watchlist(self, coin):
        if hasattr(self.coin_selector, "coin_menu"):
            self.coin_selector.coin_menu.set(coin)
        self.change_coin(coin)

    def change_timeframe(self, tf):
        with self.state_lock:
            self.current_timeframe = tf
            self.state_version += 1
        self.trigger_pipeline()

    def change_strategy(self, strat):
        with self.state_lock:
            self.current_strategy = strat
            self.state_version += 1
        if hasattr(self, "strategy_menu"):
            self.strategy_menu.set(strat)
        if hasattr(self, "chart_widget"):
            self.chart_widget.set_strategy_display(strat)
        self.trigger_pipeline()

    def _toggle_theme(self):
        """Toggle between Dark and Light appearance modes and persist the choice."""
        current = ctk.get_appearance_mode()
        new_mode = "Light" if current == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        save_appearance_mode(new_mode)

    def start_live_ticking(self):
        if not self.winfo_exists():
            return
        # Only fire pipeline if previous run is done (prevents thread pileup)
        if self._pipeline_future is None or self._pipeline_future.done():
            self.trigger_pipeline()
        self._update_kpi_sparklines()
        # Use a faster tick interval for MT5 (local COM, no rate limits)
        # vs cloud APIs that need rate-limit breathing room.
        try:
            _provider_name = getattr(self.crypto_service._providers[0], "name", "") if self.crypto_service._providers else ""
            _interval = 2000 if _provider_name == "mt5" else 5000
        except Exception:
            _interval = 5000
        self.after(_interval, self.start_live_ticking)

    def _update_kpi_sparklines(self):
        """Compute daily/weekly/monthly P/L from closed paper trades and drive sparklines."""
        try:
            import time as _t
            now = _t.time()
            day_start   = now - 86400
            week_start  = now - 86400 * 7
            month_start = now - 86400 * 30

            all_closed = paper_trading_db.get_trades(status="CLOSED", limit=500)
            daily_pnl = weekly_pnl = monthly_pnl = 0.0
            for t in all_closed:
                pnl = float(t.get("pnl") or 0.0)
                ts  = float(t.get("closed_at") or t.get("opened_at") or 0)
                if ts >= day_start:
                    daily_pnl += pnl
                if ts >= week_start:
                    weekly_pnl += pnl
                if ts >= month_start:
                    monthly_pnl += pnl

            # Normalise to [0, 1] for the progress bar: 0.5 = breakeven,
            # capped at ±$500 range so small amounts still show movement.
            def _to_fill(v, scale=500.0):
                return max(0.0, min(1.0, (v + scale) / (2 * scale)))

            for spark, val in [
                (getattr(self, "_spark_daily",   None), daily_pnl),
                (getattr(self, "_spark_weekly",  None), weekly_pnl),
                (getattr(self, "_spark_monthly", None), monthly_pnl),
            ]:
                if spark is None:
                    continue
                try:
                    if not spark.winfo_exists():
                        continue
                    fill  = _to_fill(val)
                    color = Colors.BUY if val >= 0 else Colors.SELL
                    spark.configure(progress_color=color)
                    spark.set(fill)
                except Exception:
                    pass
        except Exception:
            pass

    def _refresh_signal_engine_panel(self):
        signals = self.market_scanner.get_signals()
        status  = self.market_scanner.get_status_text()
        if hasattr(self, "signal_engine_panel"):
            self.signal_engine_panel.update_signals(signals, status_text=status)
        if hasattr(self, "market_scanner_page"):
            self.market_scanner_page.update_signals(signals, status_text=status)
        # ── Sync dashboard panels with the same live data ──────────────
        self._update_dash_ai_signals(signals)
        self._update_dash_market_scanner(signals)
        self._update_signal_badge()
        # Update system status if visible
        if hasattr(self, "system_status_panel"):
            try:
                self.system_status_panel.update_scanner_status(
                    self.market_scanner.get_status_text(),
                    self.market_scanner.get_active_signal_count()
                )
            except Exception:
                pass
        if self.winfo_exists():
            self.after(5000, self._refresh_signal_engine_panel)

    def _update_dash_ai_signals(self, signals: list):
        """Update dashboard AI Signals panel with live signals from the real engine."""
        if not hasattr(self, "_dash_sig_container"):
            return
        try:
            for w in self._dash_sig_container.winfo_children():
                w.destroy()
        except Exception:
            return

        if not signals:
            lbl = ctk.CTkLabel(
                self._dash_sig_container,
                text="⏳  Scanning markets for AI signals…\nSignals appear when the engine finds high-probability setups.",
                font=SF.TINY(), text_color=Colors.TEXT_MUTED, justify="center")
            lbl.grid(row=0, column=0, columnspan=2, padx=s(10), pady=20)
            return

        # Show up to 2 signal cards (same as before, but from real data)
        for col_i, sig in enumerate(signals[:2]):
            dir_col = Colors.BUY if sig.direction == "BUY" else Colors.SELL
            on_col  = Colors.ON_BUY if sig.direction == "BUY" else Colors.ON_SELL
            sc = ctk.CTkFrame(self._dash_sig_container, fg_color=Colors.CARD_BG_ALT,
                               border_width=1, border_color=Colors.BORDER, corner_radius=s(6))
            sc.grid(row=0, column=col_i, sticky="nsew",
                    padx=(6 if col_i == 0 else 3, 3 if col_i == 0 else 6), pady=(0, 6))

            sc_top = ctk.CTkFrame(sc, fg_color="transparent")
            sc_top.pack(fill="x", padx=6, pady=(4, 1))
            ctk.CTkLabel(sc_top, text=sig.symbol, font=SF.MONO_SM(),
                         text_color=Colors.TEXT).pack(side="left")
            ctk.CTkLabel(sc_top, text=f" {sig.direction} ",
                         font=SF.STATUS_BOLD(), text_color=on_col,
                         fg_color=dir_col, corner_radius=s(4)).pack(side="left", padx=3)
            ctk.CTkLabel(sc_top, text=f"{sig.confidence}%\nConf",
                         font=SF.NANO(), text_color=dir_col,
                         justify="center").pack(side="right")

            sc_sub = ctk.CTkFrame(sc, fg_color="transparent")
            sc_sub.pack(fill="x", padx=S.SM(), pady=(0, 2))
            strat_short = getattr(sig, "strategy", self.current_strategy)[:20]
            ctk.CTkLabel(sc_sub, text=f"Strategy  {strat_short}",
                         font=SF.STATUS(), text_color=Colors.TEXT_MUTED).pack(side="left")
            ctk.CTkLabel(sc_sub, text=f"TF  {getattr(sig,'setup_timeframe', '—')}",
                         font=SF.STATUS(), text_color=Colors.TEXT_MUTED).pack(side="right")

            lvls = ctk.CTkFrame(sc, fg_color="transparent")
            lvls.pack(fill="x", padx=S.SM())
            for lbl_t, val, vc in [
                ("Entry", f"{sig.entry_price:.5g}", Colors.TEXT),
                ("TP1",   f"{sig.take_profit_1:.5g}", Colors.BUY),
                ("SL",    f"{sig.stop_loss:.5g}",    Colors.SELL),
                ("R:R",   f"1:{sig.risk_reward:.2f}", Colors.NEUTRAL),
            ]:
                c2 = ctk.CTkFrame(lvls, fg_color="transparent")
                c2.pack(side="left", expand=True)
                ctk.CTkLabel(c2, text=lbl_t, font=SF.NANO(),
                             text_color=Colors.LABEL).pack()
                ctk.CTkLabel(c2, text=val, font=SF.MONO_TINY(),
                             text_color=vc).pack()

            rm_r = ctk.CTkFrame(sc, fg_color="transparent")
            rm_r.pack(fill="x", padx=6, pady=(2, 1))
            ctk.CTkLabel(rm_r, text="Confidence", font=SF.STATUS(),
                         text_color=Colors.LABEL).pack(side="left")
            rm_bar = ctk.CTkProgressBar(rm_r, height=6, corner_radius=3,
                                         progress_color=dir_col, fg_color=Colors.WELL_BG)
            rm_bar.set(min(sig.confidence / 100.0, 1.0))
            rm_bar.pack(side="left", fill="x", expand=True, padx=(6, 0))

            btn_r = ctk.CTkFrame(sc, fg_color="transparent")
            btn_r.pack(fill="x", padx=6, pady=(2, 6))
            ctk.CTkButton(btn_r, text="View Signal", height=s(24), corner_radius=s(5),
                          fg_color=dir_col,
                          hover_color=Colors.BUY_HOVER if sig.direction == "BUY" else Colors.SELL_HOVER,
                          text_color=on_col, font=SF.STATUS_BOLD(),
                          command=lambda: self.show_page("ai_signals"),
                          ).pack(side="left", fill="x", expand=True, padx=(0, 3))
            ctk.CTkButton(btn_r, text="Paper Trade", height=s(24), corner_radius=s(5),
                          fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
                          text_color=Colors.TEXT_SECONDARY, font=SF.STATUS_BOLD(),
                          command=lambda: self.show_page("trade_history"),
                          ).pack(side="right", fill="x", expand=True, padx=(3, 0))

        # If only 1 signal and column 1 is empty, add a "scanning" label
        if len(signals) == 1:
            lbl = ctk.CTkLabel(self._dash_sig_container,
                                text="🔭  More signals\nwill appear here",
                                font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                                justify="center")
            lbl.grid(row=0, column=1, padx=s(10), pady=20)

    def _update_dash_market_scanner(self, signals: list):
        """Update dashboard Market Scanner mini-table with live scanner signals."""
        if not hasattr(self, "_dash_ms_scroll"):
            return
        try:
            for w in self._dash_ms_scroll.winfo_children():
                w.destroy()
        except Exception:
            return

        if not signals:
            ctk.CTkLabel(self._dash_ms_scroll,
                          text="⏳  Waiting for scanner data…",
                          font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                          ).pack(padx=s(10), pady=s(12))
            return

        for sig in signals[:8]:   # show up to 8 rows
            d_col = Colors.BUY if sig.direction == "BUY" else Colors.SELL
            arr   = "↗" if sig.direction == "BUY" else "↘"
            rf = ctk.CTkFrame(self._dash_ms_scroll, fg_color="transparent")
            rf.pack(fill="x")
            for j, (v, w, vc) in enumerate([
                (sig.symbol,                         2, Colors.TEXT),
                (arr,                                1, d_col),
                (sig.direction,                      2, d_col),
                (f"{sig.confidence}%",               2, Colors.NEUTRAL),
                (getattr(sig, "trend", "—")[:8],     2, Colors.TEXT_MUTED),
                (getattr(sig, "setup_timeframe","—"), 2, Colors.TEXT_SECONDARY),
                (f"{sig.entry_price:.5g}",            3, Colors.TEXT),
            ]):
                rf.grid_columnconfigure(j, weight=w)
                ctk.CTkLabel(rf, text=v, font=SF.MONO_TINY(),
                             text_color=vc).grid(row=0, column=j,
                                                  sticky="w", padx=S.XS(), pady=2)

    def _open_about(self):
        try:
            from ui.about_dialog import AboutDialog
            AboutDialog(self)
        except Exception:
            pass

    def _on_close(self):
        """Graceful shutdown: confirm → stop threads → save → disconnect → exit."""
        # ── Confirmation dialog ───────────────────────────────────────
        confirmed = messagebox.askyesno(
            "Exit AI Trader Pro",
            "Are you sure you want to exit?\n\n"
            "All running services will be stopped safely\n"
            "and your settings will be saved.",
            icon="question",
            parent=self,
        )
        if not confirmed:
            return

        # ── Disable further interactions immediately ───────────────────
        try:
            self.withdraw()          # hide window while shutting down
        except Exception:
            pass

        from utils.logger import logger
        logger.info("[Shutdown] User confirmed exit — beginning graceful shutdown.")

        # ── Stop background threads ───────────────────────────────────
        try:
            self.market_scanner.stop()
            logger.info("[Shutdown] Market scanner stopped.")
        except Exception as e:
            logger.warning(f"[Shutdown] market_scanner.stop() error: {e}")

        try:
            self.paper_trading_engine.stop()
            logger.info("[Shutdown] Paper trading engine stopped.")
        except Exception as e:
            logger.warning(f"[Shutdown] paper_trading_engine.stop() error: {e}")

        # ── Stop pipeline executor ────────────────────────────────────
        try:
            self._pipeline_executor.shutdown(wait=False, cancel_futures=True)
            logger.info("[Shutdown] Pipeline executor shut down.")
        except TypeError:
            # cancel_futures added in Python 3.9 — fallback for older
            try:
                self._pipeline_executor.shutdown(wait=False)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"[Shutdown] executor shutdown error: {e}")

        # ── Save settings and open data ───────────────────────────────
        try:
            from services import provider_settings as _ps
            _ps.save_account_balance(self.account_balance)
            logger.info("[Shutdown] Account balance saved.")
        except Exception as e:
            logger.warning(f"[Shutdown] balance save error: {e}")

        # ── Disconnect APIs / services ────────────────────────────────
        try:
            self.crypto_service.shutdown()
            logger.info("[Shutdown] Crypto service disconnected.")
        except Exception as e:
            logger.warning(f"[Shutdown] crypto_service.shutdown() error: {e}")

        # ── Close database connections ────────────────────────────────
        try:
            from services import paper_trading_db as _ptdb
            _ptdb.close()
            logger.info("[Shutdown] Paper trading DB closed.")
        except Exception:
            pass
        try:
            from services import signal_storage as _ss
            if hasattr(_ss, "close"):
                _ss.close()
        except Exception:
            pass

        # ── Shutdown notification center ──────────────────────────────
        try:
            nc.shutdown(timeout=2.0)
            logger.info("[Shutdown] NotificationCenter stopped.")
        except Exception as e:
            logger.warning(f"[Shutdown] nc.shutdown() error: {e}")

        logger.info("[Shutdown] Graceful shutdown complete. Goodbye.")

        # ── Final destroy ─────────────────────────────────────────────
        try:
            self.destroy()
        except Exception:
            pass

    def trigger_pipeline(self):
        coin, tf, strat, ver = self.get_state_snapshot()
        if self._pipeline_future and not self._pipeline_future.done():
            self._pipeline_future.cancel()
        self._pipeline_future = self._pipeline_executor.submit(
            self._async_processing_worker, coin, tf, strat, ver
        )

    def _safe_after(self, delay, func, *args):
        """Thread-safe wrapper for self.after — checks winfo_exists first."""
        try:
            if self.winfo_exists():
                self.after(delay, func, *args)
        except RuntimeError:
            pass

    def _async_processing_worker(self, coin, timeframe, strategy, version):
        try:
            raw   = self.crypto_service.fetch_market_data(coin, timeframe)
            wdata = self.crypto_service.fetch_top_market_prices()
            ndata = self.crypto_service.fetch_live_news()
            if version != self.state_version:
                return
            proc  = self.market_analyzer.calculate_indicators(raw)
            ai_out = self.ai_engine.run_strategy(proc, strategy, symbol=coin)
            if version != self.state_version:
                return
            self._safe_after(0, self._ui_sync_cb, proc, ai_out, coin, wdata, ndata, strategy)
        except Exception as e:
            from utils.error_handler import format_user_error
            msg = format_user_error(e)
            from utils.logger import logger
            logger.warning(f"[Pipeline] {type(e).__name__}: {e}")
            if hasattr(self, "lbl_conn_status"):
                self._safe_after(0, lambda m=msg: self.lbl_conn_status.configure(
                    text="⚡", text_color=Colors.NEUTRAL))
            if hasattr(self, "lbl_last_sync"):
                self._safe_after(0, lambda m=msg: self.lbl_last_sync.configure(
                    text=m[:60], text_color=Colors.NEUTRAL))

    def _ui_sync_cb(self, df, ai_data, coin, wdata, ndata, strategy):
        for item in wdata:
            nm = item.get("asset")
            pv = item.get("price", 0.0)
            if nm and pv:
                self.latest_watchlist_prices[nm] = pv

        entry = ai_data.get("entry", 0.0)
        sl    = ai_data.get("sl",    0.0)
        tp    = ai_data.get("tp",    0.0)
        sig   = ai_data.get("signal", "")
        strat_name = strategy or self.current_strategy

        try:
            overlays = chart_overlays.build_overlays(df, strat_name, ai_data)
        except Exception:
            overlays = []

        self.chart_widget.update_chart(df, entry=entry, sl=sl, tp=tp,
                                        signal=sig, overlays=overlays)
        try:
            self.chart_widget.set_pair_info(coin, self.current_timeframe)
        except Exception:
            pass
        close_price = df["close"].iloc[-1] if not df.empty else 0.0

        if close_price:
            wdata = list(wdata)
            synced = False
            for i, item in enumerate(wdata):
                if item.get("asset") == coin:
                    wdata[i] = {**item, "price": close_price}
                    synced = True
                    break
            if not synced:
                wdata.append({"asset": coin, "price": close_price})
            self.latest_watchlist_prices[coin] = close_price

        if entry > 0 and sl > 0 and entry != sl:
            sz = lm.compute_position(coin, self.account_balance,
                                      self.risk_percentage, entry, sl)
            self.current_suggested_units_raw = sz["units"]
            self.current_suggested_size_text = sz["size_label"]
            self.lbl_calc_lots.configure(
                text=f"SIZE: {sz['size_label']}  ·  {sz['leverage']}x",
                text_color=Colors.BUY)
        else:
            self.lbl_calc_lots.configure(text="SIZE: NO SETUP",
                                          text_color=Colors.TEXT_MUTED)

        if hasattr(self, "ai_panel"):
            self.ai_panel.update_analysis(
                strategy=ai_data["strategy"], signal=sig,
                confidence=ai_data["confidence"], reasoning=ai_data["reasoning"],
                entry=entry, sl=sl, tp=tp, rr=ai_data.get("rr", 0.0))

        if hasattr(self, "trade_panel"):
            self.trade_panel.update_ui(coin=coin, price=close_price,
                                        signal=sig, ai_sl=sl, ai_tp=tp)
        self._ai_sl = sl
        self._ai_tp = tp

        self._recalculate_portfolio_exposure(close_price)

        if hasattr(self, "watchlist_page"):
            self.watchlist_page.update_watchlist(wdata)
        if ndata:
            if len(ndata) > self._last_news_count:
                try:
                    from ui.settings_panel import SettingsPanel as _SP
                    _news_enabled = _SP.load_notif_prefs().get("notif_news", False)
                except Exception:
                    _news_enabled = False
                for item in ndata[self._last_news_count:]:
                    hl = item.get("headline", item.get("title", "Market News"))
                    if _news_enabled:
                        nc.push("market_news", "📰 Market News", hl[:120], data=item)
            self._last_news_count = len(ndata)
            if hasattr(self, "news_page"):
                self.news_page.update_news_feed(ndata)

        if hasattr(self, "lbl_market_info"):
            conf = ai_data.get("confidence", "—")
            self.lbl_market_info.configure(
                text=f"Strategy: {strat_name}  │  Signal: {sig or 'STAY OUT'}  │  Confidence: {conf}")

        status = self.crypto_service.get_connection_status()
        if hasattr(self, "lbl_conn_status"):
            if status.get("connected"):
                self.lbl_conn_status.configure(text="●", text_color=Colors.BUY)
            else:
                self.lbl_conn_status.configure(text="○", text_color=Colors.NEUTRAL)
        if hasattr(self, "lbl_last_sync"):
            if status.get("connected"):
                broker = status.get("broker") or ""
                self.lbl_last_sync.configure(
                    text=f"Synced {time.strftime('%H:%M:%S')}" +
                         (f"  ·  {broker}" if broker else ""))
            else:
                self.lbl_last_sync.configure(
                    text=status.get("reason", "Waiting…"))

        # Update system status panel
        if hasattr(self, "system_status_panel"):
            try:
                self.system_status_panel.update_connection_status(status)
                self.system_status_panel.update_market_data(close_price, coin)
            except Exception:
                pass
    def _schedule_signal_popup(self, sig):
        """Show a toast notification without freezing the UI thread."""
        if not hasattr(self, '_last_popup_time'):
            self._last_popup_time = 0
        now = time.time()
        if now - self._last_popup_time < 5:
            return
        self._last_popup_time = now
        try:
            if self.winfo_exists():
                self.after(100, lambda s=sig: self._show_toast(s))
        except Exception:
            pass

    def _show_toast(self, sig):
        try:
            from ui.components import ToastNotification
            msg = f"{sig.get('symbol', '')} - {sig.get('action', '')}"
            ToastNotification(self, message=msg).show()
        except Exception:
            pass