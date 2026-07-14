"""
ui/system_status_panel.py
===========================
System Status Panel — real-time monitoring of all app subsystems.

Thread-safety fix (Python 3.12 RuntimeError: main thread is not in main loop):
  Root cause: _bg_collect() ran on a daemon thread and called self.after()
  directly. In Python 3.12 Tkinter enforces that .after() MUST be called from
  the main thread. Calling it from any worker thread raises RuntimeError.

  Fix: Worker thread writes results into a thread-safe queue. A single
  persistent Tkinter .after() loop (the "drain loop") running exclusively on
  the main thread reads from that queue and applies UI updates. The background
  worker NEVER touches any Tkinter object or calls any Tkinter method.

Additional protections:
  • _destroyed flag — prevents any UI call after widget.destroy()
  • _worker_lock — ensures at most one worker thread runs at a time
  • Queue bounded to 1 item — old stale results are discarded automatically
  • Clean shutdown via destroy() override
"""
from __future__ import annotations

import queue
import threading
import time
import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

# How often the drain loop checks the result queue (milliseconds).
# Keep this small so the UI feels instant; it never blocks.
_DRAIN_MS   = 100
# How often a new background collection is triggered (milliseconds).
_COLLECT_MS = 2000


class _StatusItem(ctk.CTkFrame):
    """Single status row: icon + label + value. All methods are main-thread only."""

    def __init__(self, parent, icon: str, label: str):
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(self, text=icon, font=SF.SUBHEADER(),
                     text_color=Colors.TEXT, width=s(28)).pack(side="left")
        ctk.CTkLabel(self, text=label, font=SF.NAV(),
                     text_color=Colors.TEXT_SECONDARY,
                     width=S.BTN_W_LG(), anchor="w").pack(side="left", padx=(4, 8))

        self._lbl_value = ctk.CTkLabel(
            self, text="Checking…",
            font=SF.MONO_SM(),
            text_color=Colors.TEXT_MUTED)
        self._lbl_value.pack(side="left")

        self._indicator = ctk.CTkLabel(
            self, text="●", font=SF.NORMAL(),
            text_color=Colors.TEXT_MUTED)
        self._indicator.pack(side="right", padx=8)

    def update(self, text: str, status: str = "neutral", value_color=None):
        """Must only be called from the main Tkinter thread."""
        color_map = {
            "ok":      Colors.BUY,
            "warn":    Colors.NEUTRAL,
            "error":   Colors.SELL,
            "neutral": Colors.TEXT_MUTED,
        }
        dot_color = color_map.get(status, Colors.TEXT_MUTED)
        self._lbl_value.configure(text=text, text_color=value_color or dot_color)
        self._indicator.configure(text_color=dot_color)


class SystemStatusPanel(ctk.CTkFrame):
    """
    Full system status dashboard.

    Threading model
    ───────────────
    Main thread  ──► _schedule_collect()  every _COLLECT_MS ms
                        └─ submits _bg_collect() to a daemon thread
                 ──► _drain_queue()       every _DRAIN_MS ms
                        └─ reads _result_queue; calls _apply_results()

    Worker thread ──► _bg_collect()
                        └─ does ALL network / psutil / service calls
                        └─ puts ONE dict into _result_queue
                        └─ NEVER touches any Tkinter widget or calls .after()
    """

    def __init__(self, parent, crypto_service=None, market_scanner=None,
                 paper_trading_engine=None):
        super().__init__(parent, fg_color=Colors.CARD_BG,
                         border_width=1, border_color=Colors.BORDER, corner_radius=s(10))

        self._crypto_service       = crypto_service
        self._market_scanner       = market_scanner
        self._paper_trading_engine = paper_trading_engine

        # Thread-safe communication: worker → main thread.
        # maxsize=1: stale results are discarded; only the latest matters.
        self._result_queue: queue.Queue[dict] = queue.Queue(maxsize=1)

        # Lifecycle management
        self._destroyed    = False          # set True in destroy(); blocks all UI calls
        self._worker_lock  = threading.Lock()  # prevents overlapping workers
        self._worker_busy  = False

        # Values injected by main_window via the three update_*() hooks
        self._conn_status:  dict  = {}
        self._market_price: float = 0.0
        self._market_coin:  str   = ""
        self._scanner_count: int  = 0

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 4))
        ctk.CTkLabel(hdr, text="SYSTEM STATUS", font=SF.SUBHEADER(),
                     text_color=Colors.TEXT).pack(side="left")
        ctk.CTkButton(
            hdr, text="⟳ Refresh", width=s(80), height=s(26), corner_radius=s(6),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.TINY(),
            command=self._trigger_collect,
        ).pack(side="right")
        self._lbl_last_update = ctk.CTkLabel(
            hdr, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self._lbl_last_update.pack(side="right", padx=8)

        # ── Status items ──────────────────────────────────────────────
        items_frame = ctk.CTkFrame(
            self, fg_color=Colors.WELL_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        items_frame.pack(fill="x", padx=Spacing.MD(), pady=4)

        self._api_item      = _StatusItem(items_frame, "🌐", "API Connection")
        self._internet_item = _StatusItem(items_frame, "📡", "Internet Connectivity")
        self._scanner_item  = _StatusItem(items_frame, "🔭", "Market Scanner")
        self._ai_item       = _StatusItem(items_frame, "🤖", "AI Engine")
        self._data_item     = _StatusItem(items_frame, "📊", "Market Data Feed")
        self._paper_item    = _StatusItem(items_frame, "📝", "Paper Trading Engine")
        self._cpu_item      = _StatusItem(items_frame, "⚙️",  "CPU Usage")
        self._ram_item      = _StatusItem(items_frame, "💾", "RAM Usage")
        self._update_item   = _StatusItem(items_frame, "🕐", "Last Data Update")

        # ── Stats bar ─────────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=Colors.BORDER, height=1).pack(
            fill="x", padx=Spacing.MD(), pady=6)

        stats_frame = ctk.CTkFrame(
            self, fg_color=Colors.WELL_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        stats_frame.pack(fill="x", padx=Spacing.MD(), pady=(0, Spacing.MD()))
        for i in range(4):
            stats_frame.grid_columnconfigure(i, weight=1)

        for col, (label, attr) in enumerate([
            ("Active Signals",     "_lbl_stat_signals"),
            ("Scanner Symbols",    "_lbl_stat_symbols"),
            ("Open Paper Trades",  "_lbl_stat_trades"),
            ("Data Provider",      "_lbl_stat_provider"),
        ]):
            f = ctk.CTkFrame(stats_frame, fg_color="transparent")
            f.grid(row=0, column=col, padx=8, pady=10, sticky="nsew")
            ctk.CTkLabel(f, text=label, font=SF.STATUS_BOLD(),
                         text_color=Colors.LABEL).pack()
            lbl = ctk.CTkLabel(f, text="—", font=SF.PRICE_SM(),
                               text_color=Colors.TEXT)
            lbl.pack()
            setattr(self, attr, lbl)

        # ── Start both loops on the main thread ───────────────────────
        self._trigger_collect()          # kick off first collection immediately
        self._schedule_collect()         # schedule periodic re-collections
        self._drain_queue()              # start the drain loop

    # ─────────────────────────────────────────────────────────────────
    # Main-thread scheduling
    # ─────────────────────────────────────────────────────────────────

    def _schedule_collect(self):
        """Main-thread periodic timer: fires _trigger_collect every _COLLECT_MS."""
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._trigger_collect()
        self.after(_COLLECT_MS, self._schedule_collect)

    def _trigger_collect(self):
        """
        Main-thread: spawn a background worker if none is running.
        _worker_lock ensures at most one worker thread lives at a time.
        """
        if self._destroyed:
            return
        with self._worker_lock:
            if self._worker_busy:
                return          # previous worker still running — skip this cycle
            self._worker_busy = True

        t = threading.Thread(target=self._bg_collect, daemon=True,
                             name="sys-status-collect")
        t.start()

    def _drain_queue(self):
        """
        Main-thread drain loop: runs every _DRAIN_MS ms.
        Reads ONE result dict from the queue (non-blocking) and applies it.
        This is the ONLY place _apply_results() is ever called, always on the
        main thread — eliminating the RuntimeError completely.
        """
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            result = self._result_queue.get_nowait()
            self._apply_results(result)
        except queue.Empty:
            pass
        except Exception:
            pass        # widget may be in teardown — silently ignore
        # Reschedule on the main thread via .after() — always safe here
        self.after(_DRAIN_MS, self._drain_queue)

    # ─────────────────────────────────────────────────────────────────
    # Background worker — NEVER touches Tkinter
    # ─────────────────────────────────────────────────────────────────

    def _bg_collect(self):
        """
        Runs on a daemon thread.
        IMPORTANT: must NOT call any Tkinter method, ctk method, or self.after().
        All results are passed back via _result_queue.
        """
        results: dict = {}
        try:
            # Internet connectivity
            try:
                from services.market_data_provider import has_internet
                results["internet"] = has_internet()
            except Exception:
                results["internet"] = False

            # API / broker connection
            if self._crypto_service:
                try:
                    results["conn"] = self._crypto_service.get_connection_status()
                except Exception:
                    results["conn"] = {}

            # Market scanner
            if self._market_scanner:
                try:
                    thread = self._market_scanner._thread
                    results["scanner_running"] = (
                        thread is not None and thread.is_alive()
                    )
                    results["scanner_symbols"] = len(self._market_scanner.symbols)
                    results["scanner_signals"] = \
                        self._market_scanner.get_active_signal_count()
                except Exception:
                    results["scanner_running"] = False

            # Paper trading engine
            if self._paper_trading_engine:
                try:
                    results["paper_running"] = self._paper_trading_engine.is_running()
                    results["open_trades"] = len(
                        self._paper_trading_engine.get_open_trades_snapshot()
                    )
                except Exception:
                    results["paper_running"] = False
                    results["open_trades"]   = 0

            # CPU / RAM (psutil — can be slow, always non-blocking here)
            if _PSUTIL:
                try:
                    results["cpu"]     = psutil.cpu_percent(interval=None)
                    mem                = psutil.virtual_memory()
                    results["ram_pct"] = mem.percent
                    results["ram_gb"]  = mem.used / 1024 ** 3
                except Exception:
                    pass

        finally:
            # Mark worker as idle before pushing result so next cycle can start
            with self._worker_lock:
                self._worker_busy = False

            # Push result into queue. If queue is full (a prior result wasn't
            # drained yet), discard the old one and insert the fresh one.
            try:
                self._result_queue.put_nowait(results)
            except queue.Full:
                try:
                    self._result_queue.get_nowait()   # discard stale
                except queue.Empty:
                    pass
                try:
                    self._result_queue.put_nowait(results)
                except queue.Full:
                    pass

    # ─────────────────────────────────────────────────────────────────
    # UI update — main thread only (called from _drain_queue)
    # ─────────────────────────────────────────────────────────────────

    def _apply_results(self, r: dict):
        """Called exclusively from _drain_queue on the main thread."""
        if self._destroyed:
            return
        try:
            self._apply_results_inner(r)
        except Exception:
            pass    # widget destroyed mid-update — silently absorb

    def _apply_results_inner(self, r: dict):
        now_str = time.strftime("%H:%M:%S")

        internet = r.get("internet", False)
        self._internet_item.update(
            "Connected" if internet else "Offline",
            "ok" if internet else "error")

        conn         = r.get("conn", {})
        api_connected = conn.get("connected", False)
        provider     = conn.get("broker") or conn.get("provider") or "—"
        self._api_item.update(
            f"Connected  ·  {provider}" if api_connected
            else conn.get("reason", "Disconnected"),
            "ok" if api_connected else ("warn" if internet else "error"))

        scanner_ok = r.get("scanner_running", False)
        signals    = r.get("scanner_signals", self._scanner_count)
        symbols    = r.get("scanner_symbols", 0)
        self._scanner_item.update(
            f"Running  ·  {signals} signal(s) active" if scanner_ok else "Stopped",
            "ok" if scanner_ok else "error")

        self._ai_item.update("Online — Ready", "ok", Colors.BUY)

        if self._market_coin and self._market_price:
            self._data_item.update(
                f"{self._market_coin} @ {self._market_price:,.4f}",
                "ok" if api_connected else "warn")
        else:
            self._data_item.update("Waiting for data…", "neutral")

        paper_ok    = r.get("paper_running", False)
        open_trades = r.get("open_trades", 0)
        self._paper_item.update(
            f"Running  ·  {open_trades} open trade(s)" if paper_ok else "Stopped",
            "ok" if paper_ok else "warn")

        if _PSUTIL and "cpu" in r:
            cpu = r["cpu"]
            ram = r.get("ram_pct", 0)
            self._cpu_item.update(
                f"{cpu:.1f}%",
                "ok" if cpu < 70 else ("warn" if cpu < 90 else "error"))
            self._ram_item.update(
                f"{ram:.1f}%  ({r.get('ram_gb', 0):.1f} GB used)",
                "ok" if ram < 75 else ("warn" if ram < 90 else "error"))
        elif _PSUTIL:
            # psutil present but reading failed (permissions, etc.)
            self._cpu_item.update("Unable to read", "neutral")
            self._ram_item.update("Unable to read", "neutral")
        else:
            # psutil not installed — guide user to fix it
            self._cpu_item.update("Run: pip install psutil", "warn")
            self._ram_item.update("Run: pip install psutil", "warn")

        self._update_item.update(now_str, "ok")
        self._lbl_last_update.configure(text=f"Updated {now_str}")

        self._lbl_stat_signals.configure(
            text=str(signals),
            text_color=Colors.BUY if signals > 0 else Colors.TEXT_MUTED)
        self._lbl_stat_symbols.configure(text=str(symbols))
        self._lbl_stat_trades.configure(text=str(open_trades))
        self._lbl_stat_provider.configure(
            text=(conn.get("broker") or conn.get("provider") or "—")[:18])

    # ─────────────────────────────────────────────────────────────────
    # External update hooks (called from main_window — main thread only)
    # ─────────────────────────────────────────────────────────────────

    def update_connection_status(self, status: dict):
        self._conn_status = status

    def update_market_data(self, price: float, coin: str):
        self._market_price = price
        self._market_coin  = coin

    def update_scanner_status(self, status_text: str, signal_count: int):
        self._scanner_count = signal_count

    # ─────────────────────────────────────────────────────────────────
    # Clean shutdown
    # ─────────────────────────────────────────────────────────────────

    def destroy(self):
        """
        Set the destroyed flag BEFORE calling super().destroy() so that any
        pending .after() callbacks see _destroyed=True and exit immediately
        without touching widgets that no longer exist.
        """
        self._destroyed = True
        try:
            super().destroy()
        except Exception:
            pass
