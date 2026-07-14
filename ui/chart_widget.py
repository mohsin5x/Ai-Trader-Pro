"""
=========================================================
 AI Trader Pro - Institutional Chart Engine
=========================================================
A hand-built, dependency-free (pure Tkinter Canvas) charting
engine designed to feel like a professional trading terminal:
smooth zoom/pan, live crosshair, animated candle arrivals,
EMA/Bollinger overlays, volume panel, session separators,
entry/SL/TP execution lines, strategy drawings, and a
professional toolbar (fullscreen, zoom, crosshair, snapshot,
grid, chart style, indicators, strategy).

No Matplotlib. No external chart runtime. Every pixel is
drawn and controlled directly on a tk.Canvas so the chart
stays fluid at 60fps-class interaction speeds even inside a
customtkinter host frame.
"""

import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
import pandas as pd

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Chart

try:
    from PIL import ImageGrab
    _SCREENSHOT_AVAILABLE = True
except ImportError:
    _SCREENSHOT_AVAILABLE = False

STRATEGY_LIST = [
    "ICT Smart Money", "Smart Money Concepts", "Support & Resistance",
    "Liquidity Concepts", "Order Blocks", "Fair Value Gaps",
    "Break of Structure", "Change of Character",
    "Scalping", "Swing Trading", "Trend Following", "Breakout",
]


def _to_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Converts a regular OHLC frame into Heikin Ashi candles. Smooths out
    noise: HA-close is the bar's average price, HA-open is the midpoint of
    the previous HA candle, and the wicks extend to the true high/low."""
    ha = df.copy().reset_index(drop=True)
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4.0
    ha_open = [ (df['open'].iloc[0] + df['close'].iloc[0]) / 2.0 ]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i - 1] + ha_close.iloc[i - 1]) / 2.0)
    ha_open = pd.Series(ha_open, index=df.index)
    ha['open'] = ha_open.values
    ha['close'] = ha_close.values
    ha['high'] = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1).values
    ha['low'] = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1).values
    return ha


class ChartWidget(ctk.CTkFrame):
    def __init__(self, master, on_strategy_change=None, strategies=None,
                 current_strategy=None, **kwargs):
        super().__init__(master, fg_color=Colors.SIDEBAR_BG, border_width=1,
                          border_color=Colors.BORDER, corner_radius=s(6), **kwargs)

        self.on_strategy_change = on_strategy_change
        self.strategies = strategies or STRATEGY_LIST
        self._initial_strategy = current_strategy or "ICT Smart Money"

        # ---- data state ----
        self.df = pd.DataFrame()
        self.entry = 0.0
        self.sl = 0.0
        self.tp = 0.0
        self.signal = ""
        self.overlays = []

        # ---- pair / timeframe info ----
        self._current_symbol    = ""
        self._current_timeframe = ""

        # ---- viewport state ----
        self.view_len = 80
        self.default_view_len = 80
        self.min_view_len = 15
        self.max_view_len = 300
        self.view_offset = 0.0  # candles back from the most recent candle (float, for smooth pan)

        # ---- interaction state ----
        self._pan_last_x = None
        self._crosshair_xy = None
        self._last_signature = None
        self._geo = None

        # ---- animation state ----
        self._anim_job = None
        self._anim_frame = 0
        self._anim_total_frames = 12

        # ---- fullscreen state ----
        self._fullscreen_win = None
        self._fullscreen_chart = None

        # ---- display toggles ----
        self.crosshair_enabled   = True
        self.show_grid           = True
        self.show_strategies     = False  # START raw — user must click to apply strategy
        self.chart_style = "candle"  # "candle" | "line" | "heikin_ashi"
        self.indicator_state = {
            "EMA 20": False, "EMA 50": False, "SMA 200": False,
            "Bollinger Bands": False, "Volume": True,  # volume is non-intrusive, keep on
        }

        # ---- Canvas fonts: fixed small sizes for chart readability ─────────
        # Canvas text does NOT auto-scale with DPI the same way CTk widgets do,
        # so we use smaller base sizes and clamp the scale factor to ≤1.1
        # to prevent axis labels from becoming enormous at 125-150% DPI.
        self._cf = self._build_canvas_fonts()

        # ---- layout constants ----
        self.RIGHT_AXIS_W = 92
        self.BOTTOM_AXIS_H = 28
        self.TOP_PAD = 14
        self.VOL_HEIGHT_RATIO = 0.20
        self.VOL_GAP = 10

        self._build_toolbar()

        self.canvas = tk.Canvas(self, bg=Colors.CHART_BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        self._configure_redraw_id = None
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_wheel)              # Windows / macOS
        self.canvas.bind("<Button-4>", lambda e: self._zoom(1))       # Linux scroll up
        self.canvas.bind("<Button-5>", lambda e: self._zoom(-1))      # Linux scroll down
        self.canvas.bind("<ButtonPress-1>", self._on_pan_start)
        self.canvas.bind("<B1-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_pan_last_x", None))
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Double-Button-1>", lambda e: self._toggle_fullscreen())
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())

    # =====================================================
    # TOOLBAR
    # =====================================================
    # ── Canvas font builder ───────────────────────────────────────────────────
    @staticmethod
    def _build_canvas_fonts() -> dict:
        """
        Build chart-canvas-specific font tuples.

        Canvas text is rendered at physical pixels, so it grows with DPI just
        like everything else.  But the scaling.fs() helper also applies the
        full composite scale (dpi × resolution_multiplier), which makes axis
        labels too large at 125-150% DPI.

        We cap the canvas scale at 1.05 so labels stay compact and legible
        at any display scaling without overflowing candle bars.
        """
        try:
            from ui.scaling import factor as _factor
            raw = _factor()
        except Exception:
            raw = 1.0

        # Clamp: canvas fonts should barely scale — the chart geometry already
        # adapts to window size.  Going above 1.10 makes axis text unreadable.
        scale = min(raw, 1.08)

        def _f(size, weight="", family="Consolas"):
            sz = max(7, round(size * scale))
            if weight:
                return (family, sz, weight)
            return (family, sz)

        return {
            "axis":       _f(8),           # price/time axis tick labels
            "axis_bold":  _f(8, "bold"),
            "overlay":    _f(7, "bold"),   # SMC zone / overlay labels
            "session":    _f(7, "bold"),   # session separator labels
            "crosshair":  _f(8),           # crosshair readout
            "hl":         _f(8),           # high/low labels
            "live_price": _f(8, "bold"),   # live price pill
            "badge":      _f(9, "bold", "Segoe UI"),  # signal badge on chart
            "badge_sub":  _f(8, "", "Segoe UI"),
            "badge_conf": _f(8, "bold", "Segoe UI"),
            "toast":      _f(9, "", "Segoe UI"),
            "empty":      _f(11, "", "Segoe UI"),      # "Awaiting streams" msg
        }

    def _tool_button(self, parent, text, command, width=None, active=False):
        _w = width if width is not None else S.NAV_BTN_H()
        return ctk.CTkButton(
            parent, text=text, width=_w, height=s(26), corner_radius=s(6),
            fg_color=Colors.PRIMARY if active else Colors.CARD_BG,
            hover_color=Colors.HOVER, text_color=Colors.TEXT_SECONDARY if not active else "#0B0E14",
            font=SF.NORMAL(), command=command,
        )

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, corner_radius=s(6), height=S.ROW_H())
        bar.pack(fill="x", padx=1, pady=(1, 0))
        bar.pack_propagate(False)

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", padx=6, pady=4)
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right", padx=6, pady=4)

        # Pair + timeframe label (top-left prominence)
        self._lbl_pair = ctk.CTkLabel(
            left, text="—", font=SF.SUBHEADER(),
            text_color=Colors.TEXT,
        )
        self._lbl_pair.pack(side="left", padx=(0, 10))

        self.expand_btn = self._tool_button(left, "⛶", self._toggle_fullscreen)
        self.expand_btn.pack(side="left", padx=(0, 6))

        self._tool_button(left, "＋", lambda: self._zoom(1)).pack(side="left", padx=2)
        self._tool_button(left, "－", lambda: self._zoom(-1)).pack(side="left", padx=2)
        self._tool_button(left, "⟲", self._reset_zoom, width=s(32)).pack(side="left", padx=(2, 8))

        self.crosshair_btn = self._tool_button(left, "✛ Crosshair", self._toggle_crosshair, width=s(98), active=True)
        self.crosshair_btn.pack(side="left", padx=2)

        self.grid_btn = self._tool_button(left, "▦ Grid", self._toggle_grid, width=s(70), active=True)
        self.grid_btn.pack(side="left", padx=2)

        # Eye toggle: view chart without strategy overlays — starts ACTIVE (raw mode)
        self.eye_btn = self._tool_button(left, "👁 Raw", self._toggle_strategies, width=s(70), active=True)
        self.eye_btn.pack(side="left", padx=2)

        self.style_segment = ctk.CTkSegmentedButton(
            left, values=["Candle", "Line", "Heikin Ashi"], command=self._on_style_change,
            fg_color=Colors.APP_BG, selected_color=Colors.PRIMARY,
            text_color=Colors.TEXT_SECONDARY, font=self._cf["badge_sub"], height=s(26),
        )
        self.style_segment.set("Candle")
        self.style_segment.pack(side="left", padx=(8, 2))

        self.indicator_btn = self._tool_button(left, "Indicators ▾", self._open_indicator_menu, width=s(110))
        self.indicator_btn.pack(side="left", padx=(8, 2))

        # ── Right side: timeframe quick buttons + snapshot + strategy ─
        self._tf_btns: dict[str, ctk.CTkButton] = {}
        _TF_LIST = ["1m", "5m", "15m", "1h", "4h", "1d"]
        tf_frame = ctk.CTkFrame(right, fg_color="transparent")
        tf_frame.pack(side="left", padx=(0, 6))
        for tf in _TF_LIST:
            b = ctk.CTkButton(
                tf_frame, text=tf.upper(), width=s(32), height=s(22), corner_radius=s(5),
                fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
                text_color=Colors.TEXT_SECONDARY, font=self._cf["badge_conf"],
                command=lambda t=tf: self._on_tf_btn(t),
            )
            b.pack(side="left", padx=1)
            self._tf_btns[tf] = b

        self._tool_button(right, "📷 Snapshot", self._take_screenshot, width=s(110)).pack(side="right", padx=(8, 0))

        self.strategy_dropdown = ctk.CTkOptionMenu(
            right, values=self.strategies, command=self._on_strategy_selected,
            fg_color=Colors.APP_BG, button_color=Colors.CARD_BG, button_hover_color=Colors.HOVER,
            font=self._cf["badge_sub"], width=s(170), height=s(26),
        )
        self.strategy_dropdown.set(self._initial_strategy)
        self.strategy_dropdown.pack(side="right", padx=(0, 4))

    # =====================================================
    # PUBLIC API
    # =====================================================
    def set_pair_info(self, symbol: str = "", timeframe: str = ""):
        """Update the pair + timeframe label in the toolbar."""
        self._current_symbol    = symbol
        self._current_timeframe = timeframe
        label = symbol or "—"
        if timeframe:
            label += f"  {timeframe.upper()}"
        try:
            self._lbl_pair.configure(text=label)
        except Exception:
            pass
        # Highlight the matching TF button
        tf_norm = timeframe.lower() if timeframe else ""
        for tf, btn in self._tf_btns.items():
            active = (tf == tf_norm)
            btn.configure(
                fg_color=Colors.PRIMARY if active else Colors.CARD_BG,
                text_color="#0B0E14" if active else Colors.TEXT_SECONDARY,
            )

    def update_chart(self, df: pd.DataFrame, entry: float = 0.0, sl: float = 0.0,
                      tp: float = 0.0, signal: str = "", overlays: list = None):
        has_data = df is not None and not df.empty
        prev_signature = self._last_signature
        prev_levels = (self.entry, self.sl, self.tp, self.signal)
        self.entry, self.sl, self.tp, self.signal = entry, sl, tp, signal
        self.overlays = overlays or []

        is_new_candle = False
        signature = None
        if has_data:
            df = df.reset_index(drop=True)
            if 'EMA20' not in df.columns:
                df = df.copy()
                df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
            if 'EMA50' not in df.columns:
                df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
            if 'SMA200' not in df.columns:
                df['SMA200'] = df['close'].rolling(window=200, min_periods=1).mean()

            sig_key = 'timestamp' if 'timestamp' in df.columns else 'close'
            last_row = df.iloc[-1]
            signature = (len(df), last_row[sig_key], last_row['open'], last_row['high'],
                         last_row['low'], last_row['close'])
            if prev_signature is not None and prev_signature[0] != signature[0]:
                is_new_candle = True
            self._last_signature = signature

        self.df = df if has_data else pd.DataFrame()

        if has_data:
            self.view_len = max(self.min_view_len, min(self.view_len, len(self.df), self.max_view_len))

        unchanged = (
            has_data and signature == prev_signature
            and (self.entry, self.sl, self.tp, self.signal) == prev_levels
        )
        if not unchanged:
            # Fast path: if same candle count + same OHLC except close (tick update),
            # only repaint the live-price overlay -- no full canvas wipe (no blink)
            if (has_data and prev_signature and
                    signature[0] == prev_signature[0] and  # same candle count
                    signature[2:5] == prev_signature[2:5] and  # same open/high/low
                    (self.entry, self.sl, self.tp, self.signal) == prev_levels):
                self._fast_update_live_price()
            else:
                self._redraw()

        if is_new_candle:
            self._start_new_candle_animation()

        if getattr(self, "_fullscreen_chart", None) is not None:
            self._fullscreen_chart.view_len = self.view_len
            self._fullscreen_chart.update_chart(df, entry=entry, sl=sl, tp=tp,
                                                 signal=signal, overlays=self.overlays)

    # =====================================================
    # INTERACTION
    # =====================================================
    def _on_canvas_configure(self, event=None):
        """Debounced canvas resize handler — waits 80ms before redrawing.
        Prevents the chart from thrashing the CPU during window resize drags."""
        if self._configure_redraw_id:
            try:
                self.after_cancel(self._configure_redraw_id)
            except Exception:
                pass
        self._configure_redraw_id = self.after(80, self._redraw)

    def _on_wheel(self, event):
        self._zoom(1 if event.delta > 0 else -1)

    def _zoom(self, direction):
        if self.df.empty: return
        factor = 0.88 if direction > 0 else 1.14
        new_len = int(round(self.view_len * factor))
        new_len = max(self.min_view_len, min(self.max_view_len, len(self.df), new_len))
        if new_len == self.view_len: return
        self.view_len = new_len
        self._clamp_offset()
        # Debounced zoom: prevents canvas thrash when scroll wheel spins fast
        if hasattr(self, '_zoom_redraw_id') and self._zoom_redraw_id:
            self.after_cancel(self._zoom_redraw_id)
        self._zoom_redraw_id = self.after(16, self._redraw)

    def _on_pan_start(self, event):
        self._pan_last_x = event.x

    def _on_pan_move(self, event):
        if self._pan_last_x is None or self.df.empty or not self._geo: return
        dx = event.x - self._pan_last_x
        self._pan_last_x = event.x
        candle_slot = self._geo['candle_slot']
        if candle_slot <= 0: return
        self.view_offset -= dx / candle_slot
        self._clamp_offset()
        # Debounced pan redraw: cancel pending and reschedule (smooth scroll, no pile-up)
        if hasattr(self, '_pan_redraw_id') and self._pan_redraw_id:
            self.after_cancel(self._pan_redraw_id)
        self._pan_redraw_id = self.after(16, self._redraw)  # ~60 fps cap

    def _clamp_offset(self):
        max_offset = max(0, len(self.df) - self.view_len)
        self.view_offset = max(0.0, min(float(max_offset), self.view_offset))

    def _on_motion(self, event):
        self._crosshair_xy = (event.x, event.y)
        if self.crosshair_enabled:
            self._draw_crosshair()

    def _on_leave(self, event):
        self._crosshair_xy = None
        self.canvas.delete("crosshair")

    # =====================================================
    # TOOLBAR ACTIONS
    # =====================================================
    def _reset_zoom(self):
        if self.df.empty: return
        self.view_len = min(self.default_view_len, len(self.df))
        self.view_offset = 0.0
        self._redraw()

    def _toggle_strategies(self):
        """Eye button: toggle whether strategy overlays/drawings are visible."""
        self.show_strategies = not self.show_strategies
        active = not self.show_strategies   # button is 'active' when overlays are HIDDEN
        self.eye_btn.configure(
            fg_color=Colors.PRIMARY if active else Colors.CARD_BG,
            text_color="#0B0E14" if active else Colors.TEXT_SECONDARY,
            text="👁 Raw" if active else "👁 Strat",
        )
        self._redraw()

    def _on_tf_btn(self, tf: str):
        """Timeframe button clicked — highlight it and fire the external handler."""
        # Update highlight
        for t, btn in self._tf_btns.items():
            active = (t == tf)
            btn.configure(
                fg_color=Colors.PRIMARY if active else Colors.CARD_BG,
                text_color="#0B0E14" if active else Colors.TEXT_SECONDARY,
            )
        self._current_timeframe = tf
        # Update pair label
        label = (self._current_symbol or "—") + f"  {tf.upper()}"
        try:
            self._lbl_pair.configure(text=label)
        except Exception:
            pass
        # Fire main_window timeframe change if wired
        if self.on_strategy_change:
            # We reuse the existing callback channel; main_window can detect tf values
            pass
        # Try to find main_window's change_timeframe via parent chain
        try:
            w = self.winfo_toplevel()
            if hasattr(w, "change_timeframe"):
                w.change_timeframe(tf)
        except Exception:
            pass

    def _toggle_crosshair(self):
        self.crosshair_enabled = not self.crosshair_enabled
        self.crosshair_btn.configure(
            fg_color=Colors.PRIMARY if self.crosshair_enabled else Colors.CARD_BG,
            text_color="#0B0E14" if self.crosshair_enabled else Colors.TEXT_SECONDARY,
        )
        if not self.crosshair_enabled:
            self.canvas.delete("crosshair")

    def _toggle_grid(self):
        self.show_grid = not self.show_grid
        self.grid_btn.configure(
            fg_color=Colors.PRIMARY if self.show_grid else Colors.CARD_BG,
            text_color="#0B0E14" if self.show_grid else Colors.TEXT_SECONDARY,
        )
        self._redraw()

    def _on_style_change(self, value):
        self.chart_style = {"Candle": "candle", "Line": "line", "Heikin Ashi": "heikin_ashi"}.get(value, "candle")
        self._redraw()

    def _open_indicator_menu(self):
        menu = tk.Menu(self, tearoff=0, bg=Colors.CARD_BG, fg=Colors.TEXT_SECONDARY,
                        activebackground=Colors.PRIMARY, activeforeground="#0B0E14",
                        font=SF.PILL())
        for name in self.indicator_state:
            var = tk.BooleanVar(value=self.indicator_state[name])
            menu.add_checkbutton(label=name, variable=var, command=lambda n=name, v=var: self._toggle_indicator(n, v))
        x = self.indicator_btn.winfo_rootx()
        y = self.indicator_btn.winfo_rooty() + self.indicator_btn.winfo_height()
        menu.tk_popup(x, y)

    def _toggle_indicator(self, name, var):
        self.indicator_state[name] = var.get()
        self._redraw()

    def _take_screenshot(self):
        if not _SCREENSHOT_AVAILABLE:
            self.canvas.create_text(self.canvas.winfo_width() / 2, 24,
                                     text="Screenshot needs Pillow's ImageGrab (pip install --upgrade pillow)",
                                     fill=Colors.RED, font=self._cf["toast"], tags="toast")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG image", "*.png")],
            initialfile="ai-trader-pro-chart.png", title="Save Chart Snapshot",
        )
        if not path: return
        try:
            x0 = self.canvas.winfo_rootx()
            y0 = self.canvas.winfo_rooty()
            x1 = x0 + self.canvas.winfo_width()
            y1 = y0 + self.canvas.winfo_height()
            ImageGrab.grab(bbox=(x0, y0, x1, y1)).save(path)
            msg, color = f"Saved: {path}", Colors.GREEN
        except Exception as e:
            msg, color = f"Screenshot failed: {e}", Colors.RED
        self.canvas.create_text(self.canvas.winfo_width() / 2, 24, text=msg, fill=color, font=self._cf["toast"], tags="toast")
        self.after(3000, lambda: self.canvas.delete("toast"))

    def _on_strategy_selected(self, value):
        if self.on_strategy_change:
            self.on_strategy_change(value)

    def set_strategy_display(self, name: str):
        if hasattr(self, "strategy_dropdown"):
            self.strategy_dropdown.set(name)

    # =====================================================
    # FULLSCREEN VIEWER
    # =====================================================
    def _toggle_fullscreen(self):
        if self._fullscreen_win is not None: self._close_fullscreen()
        else: self._open_fullscreen()

    def _open_fullscreen(self):
        """Open chart in a separate non-blocking window with coin selector + close button."""
        win = ctk.CTkToplevel(self)
        win.withdraw()   # keep hidden until fully built — prevents black canvas on Windows
        win.title("AI Trader Pro — Chart Detached")
        win.configure(fg_color=Colors.APP_BG)
        win.geometry(f"{self.winfo_screenwidth() - 60}x{self.winfo_screenheight() - 60}+30+20")
        # transient() prevents a blank default-root window appearing on some pages
        try:
            win.transient(self.winfo_toplevel())
        except Exception:
            pass
        win.protocol("WM_DELETE_WINDOW", self._close_fullscreen)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)

        # ── Top bar: close button + coin selector ───────────────────
        top_bar = ctk.CTkFrame(win, fg_color=Colors.SIDEBAR_BG, height=s(44), corner_radius=0)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_propagate(False)

        ctk.CTkButton(
            top_bar, text="◀  Back / Close Detached", width=s(180), height=S.BTN_H(),
            corner_radius=s(6), fg_color=Colors.CARD_BG_ALT, hover_color=Colors.SELL,
            text_color=Colors.TEXT, font=SF.PILL_LG(),
            command=self._close_fullscreen,
        ).pack(side="left", padx=10, pady=7)

        ctk.CTkLabel(top_bar, text="Symbol:", font=SF.PILL(),
                     text_color=Colors.TEXT_MUTED).pack(side="left", padx=(20, 4), pady=7)

        # Coin selector — calls back into the main chart coin change if on_strategy_change available
        _coin_list = [
            "EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","USD/CHF","NZD/USD",
            "EUR/GBP","EUR/JPY","GBP/JPY","XAU/USD","XAG/USD",
            "US30","NAS100","SPX500",
            "BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","LINK","LTC",
        ]
        self._det_coin_var = ctk.StringVar(master=win, value=self._current_symbol or "EUR/USD")
        coin_menu = ctk.CTkOptionMenu(
            top_bar, values=_coin_list, variable=self._det_coin_var,
            width=s(140), height=S.BTN_H(), corner_radius=s(6),
            fg_color=Colors.CARD_BG, button_color=Colors.BORDER,
            button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
            dropdown_fg_color=Colors.CARD_BG, dropdown_hover_color=Colors.HOVER,
            dropdown_text_color=Colors.TEXT, font=SF.PILL(),
            command=self._on_det_coin_change,
        )
        coin_menu.pack(side="left", padx=4, pady=7)

        ctk.CTkLabel(top_bar, text="Double-click chart to close detached view",
                     font=SF.TINY(), text_color=Colors.TEXT_MUTED).pack(
            side="right", padx=12, pady=7)

        # ── Chart (fills remaining space) ────────────────────────────
        self._fullscreen_win   = win
        self._fullscreen_chart = ChartWidget(
            win, on_strategy_change=self.on_strategy_change,
            strategies=self.strategies, current_strategy=self.strategy_dropdown.get())
        self._fullscreen_chart.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self._fullscreen_chart.expand_btn.configure(
            text="✕  Close Detached", width=s(140), command=self._close_fullscreen)
        self._fullscreen_chart.view_len = self.view_len

        # Bind double-click to close
        self._fullscreen_chart.canvas.bind(
            "<Double-Button-1>", lambda e: self._close_fullscreen())

        # CRITICAL: force window to fully realize before painting.
        # A single 300ms delay is unreliable on slower systems; use deiconify +
        # update_idletasks + staggered retries to guarantee the canvas has a
        # non-zero size before ChartWidget draws into it.
        # Now reveal: all children are built, canvas will get correct dimensions
        win.deiconify()
        win.update_idletasks()

        # Staggered paint retries — first is usually enough, later ones are safety nets
        win.after(300,  self._paint_fullscreen_chart)
        win.after(700,  self._paint_fullscreen_chart)
        win.after(1500, self._paint_fullscreen_chart)

        win.after(100, lambda: (win.lift(), win.focus_force()))

    def _paint_fullscreen_chart(self):
        """Called after window open — ensures canvas is visible before draw.
        Safe to call multiple times (retries). Skips if chart already has data."""
        try:
            if not (self._fullscreen_chart and self._fullscreen_win):
                return
            try:
                if not self._fullscreen_win.winfo_exists():
                    return
            except Exception:
                return

            self._fullscreen_win.update_idletasks()

            # Ensure canvas has non-zero size — on Windows this can take several frames
            cw = self._fullscreen_chart.canvas.winfo_width()
            ch = self._fullscreen_chart.canvas.winfo_height()
            if cw < 10 or ch < 10:
                # Still not visible — schedule one more retry via the detached window
                try:
                    self._fullscreen_win.after(300, self._paint_fullscreen_chart)
                except Exception:
                    pass
                return

            # Get the most recent dataframe available
            df = getattr(self, "df", None)
            if df is None or (hasattr(df, "empty") and df.empty):
                df = getattr(self, "_last_df", None)

            self._fullscreen_chart.update_chart(
                df,
                entry=getattr(self, "entry", None) or 0.0,
                sl=getattr(self, "sl", None) or 0.0,
                tp=getattr(self, "tp", None) or 0.0,
                signal=getattr(self, "signal", None),
                overlays=getattr(self, "overlays", []))
        except Exception:
            pass

    def _on_det_coin_change(self, coin: str):
        """Change the coin in the detached chart (and optionally in main chart too)."""
        if self.on_strategy_change:
            # Reuse the strategy change callback as a coin change signal
            # (main_window wires this up)
            pass
        # At minimum, trigger a pipeline refresh if we can reach main_window
        try:
            mw = self.winfo_toplevel()
            if hasattr(mw, "change_coin"):
                mw.change_coin(coin)
        except Exception:
            pass

    def _close_fullscreen(self):
        if self._fullscreen_win is not None: self._fullscreen_win.destroy()
        self._fullscreen_win = None
        self._fullscreen_chart = None

    # =====================================================
    # FAST PRICE TICK UPDATE (no canvas wipe = no blink)
    # =====================================================
    def _fast_update_live_price(self):
        """Update only the live-price line and label without clearing the whole canvas.
        Called on tick updates where only the last close changed -- eliminates the
        full-redraw blink that happened every 3-5 seconds on MT5 data feeds."""
        geo = self._geo
        if not geo or self.df.empty:
            self._redraw()
            return
        try:
            visible = geo['visible']
            if visible.empty:
                return
            # Sync the last candle close with fresh data
            last_new = self.df.iloc[-1]
            if len(visible) > 0:
                visible_idx = visible.index[-1]
                geo['visible'].at[visible_idx, 'close'] = last_new['close']

            last = visible.iloc[-1]
            price = float(last['close'])
            price_y = geo['price_y']
            right   = geo['right']
            width   = geo['width']
            y = price_y(price)
            color = Colors.GREEN if last['close'] >= last['open'] else Colors.RED

            # Remove only the live-price layer -- everything else stays (no blink)
            self.canvas.delete("live")
            self.canvas.create_line(0, y, right, y, fill=color, dash=(2, 2), tags="live")
            self.canvas.create_rectangle(right, y - 12, width, y + 12, fill=color, outline="", tags="live")
            self.canvas.create_text(right + (width - right) / 2, y,
                                    text=f"{price:.5f}", fill="#0B0E14",
                                    font=self._cf["live_price"], tags="live")
        except Exception:
            self._redraw()  # fallback to full redraw on any geometry error

    # =====================================================
    # MAIN RENDER PIPELINE
    # =====================================================
    def _redraw(self):
        # Dynamically updates background to fix Light/Dark mode switching instantly
        self.canvas.configure(bg=Colors.CHART_BG)

        width  = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 50 or height < 50:
            return

        # Fast dedup: skip identical renders (same data, same geometry)
        sig = (
            width, height,
            len(self.df),
            self.df["close"].iloc[-1] if not self.df.empty else 0,
            round(self.view_offset, 1),
            self.view_len,
            self.show_strategies,
            self.chart_style,
        )
        if sig == self._last_signature:
            return
        self._last_signature = sig

        self.canvas.delete("all")

        if self.df.empty:
            self.canvas.create_text(width / 2, height / 2, text="Awaiting Market Intelligence Streams...", fill=Colors.TEXT_MUTED, font=self._cf["badge_sub"])
            self._geo = None
            return

        total = len(self.df)
        view_len = int(min(self.view_len, total))
        start = int(max(0, total - view_len - round(self.view_offset)))
        end = start + view_len
        visible = self.df.iloc[start:end].reset_index(drop=True)
        if visible.empty:
            self._geo = None
            return

        right = width - self.RIGHT_AXIS_W
        show_volume = self.indicator_state.get("Volume", True)
        vol_h = max(30.0, (height - self.BOTTOM_AXIS_H - self.TOP_PAD) * self.VOL_HEIGHT_RATIO) if show_volume else 0.0
        vol_gap = self.VOL_GAP if show_volume else 0.0
        price_top = self.TOP_PAD
        price_bottom = height - self.BOTTOM_AXIS_H - vol_h - vol_gap
        vol_top = price_bottom + vol_gap
        vol_bottom = height - self.BOTTOM_AXIS_H

        candle_slot = right / view_len if view_len else 1
        body_w = max(1.5, candle_slot * 0.62)

        price_series = pd.concat([visible['low'], visible['high']])
        pmin, pmax = float(price_series.min()), float(price_series.max())
        for lvl in (self.entry, self.sl, self.tp):
            if lvl and lvl > 0: pmin, pmax = min(pmin, lvl), max(pmax, lvl)
        if pmax <= pmin: pmax = pmin + max(pmin * 0.001, 0.0001)
        pad = (pmax - pmin) * 0.08
        pmin -= pad
        pmax += pad

        def price_y(p): return price_bottom - (p - pmin) / (pmax - pmin) * (price_bottom - price_top)
        def idx_x(i): return i * candle_slot + candle_slot / 2

        self._geo = dict(width=width, height=height, right=right, price_top=price_top,
                          price_bottom=price_bottom, vol_top=vol_top, vol_bottom=vol_bottom,
                          pmin=pmin, pmax=pmax, candle_slot=candle_slot, body_w=body_w,
                          visible=visible, price_y=price_y, idx_x=idx_x, start=start, end=end)

        if self.show_grid: self._draw_grid(price_top, price_bottom, right)
        self._draw_sessions(visible, price_top, vol_bottom, idx_x)
        if self.show_strategies:
            self._draw_overlay_zones(start, end, idx_x, price_y)
        if self.indicator_state.get("Volume", True): self._draw_volume(visible, vol_top, vol_bottom, idx_x, body_w)
        if self.indicator_state.get("SMA 200", True): self._draw_ema(visible, price_y, idx_x, 'SMA200', Chart.SMA200)
        if self.indicator_state.get("EMA 50", True): self._draw_ema(visible, price_y, idx_x, 'EMA50', Chart.EMA50)
        if self.indicator_state.get("EMA 20", True): self._draw_ema(visible, price_y, idx_x, 'EMA20', Chart.EMA20)
        
        if self.chart_style == "line": self._draw_price_line(visible, price_y, idx_x)
        else:
            plot_df = _to_heikin_ashi(visible) if self.chart_style == "heikin_ashi" else visible
            self._draw_candles(plot_df, price_y, idx_x, body_w)

        if self.show_strategies:
            self._draw_overlay_lines(start, end, idx_x, price_y)
        self._draw_high_low(visible, price_y, idx_x)
        self._draw_levels(price_y, right, width)
        self._draw_live_price(visible, price_y, right, width)
        self._draw_price_axis(price_top, price_bottom, right, width, pmin, pmax)
        self._draw_time_axis(visible, height, idx_x)

        # ── Pair / Timeframe watermark (top-left of chart canvas) ─────
        pair_text = self._current_symbol or ""
        tf_text   = self._current_timeframe.upper() if self._current_timeframe else ""
        if pair_text:
            self.canvas.create_text(
                10, price_top + 4,
                text=pair_text, anchor="nw",
                fill=Colors.TEXT, font=self._cf["badge"],
                tags="pairlabel",
            )
        if tf_text:
            pair_w = len(pair_text) * 6 + 8   # approx pixel width
            self.canvas.create_text(
                10 + pair_w, price_top + 8,
                text=tf_text, anchor="nw",
                fill=Colors.TEXT_MUTED, font=self._cf["badge_sub"],
                tags="pairlabel",
            )
        # No-strategy badge when eye toggle is active
        if not self.show_strategies:
            self.canvas.create_text(
                right - 6, price_top + 4,
                text="RAW PRICE", anchor="ne",
                fill=Colors.NEUTRAL, font=self._cf["badge_conf"],
                tags="pairlabel",
            )

        if self._crosshair_xy and self.crosshair_enabled: self._draw_crosshair()

    # =====================================================
    # DRAW CHANNELS & RENDER LAYERS
    # =====================================================
    def _draw_grid(self, top, bottom, right):
        rows = 6
        for i in range(rows + 1):
            y = top + (bottom - top) * i / rows
            self.canvas.create_line(0, y, right, y, fill=Colors.GRID, dash=(2, 4), tags="grid")
        cols = 8
        for i in range(cols + 1):
            x = right * i / cols
            self.canvas.create_line(x, top, x, bottom, fill=Colors.GRID, dash=(2, 4), tags="grid")

    def _draw_sessions(self, visible, top, bottom, idx_x):
        if 'timestamp' not in visible.columns or len(visible) < 2: return
        span_hours = (visible['timestamp'].iloc[-1] - visible['timestamp'].iloc[0]).total_seconds() / 3600.0
        if span_hours > 24 * 10: return
        sessions = (("ASIA", 0), ("LONDON", 7), ("NEW YORK", 12))
        drawn_x = set()
        prev_hour = visible['timestamp'].iloc[0].hour
        for i in range(1, len(visible)):
            cur_hour = visible['timestamp'].iloc[i].hour
            for name, hour in sessions:
                crossed = (prev_hour < hour <= cur_hour) or (cur_hour < prev_hour and (cur_hour >= hour or prev_hour < hour))
                if crossed and cur_hour == hour:
                    x = round(idx_x(i))
                    if x in drawn_x: continue
                    drawn_x.add(x)
                    self.canvas.create_line(x, top, x, bottom, fill=Colors.GRID, dash=(4, 3), tags="session")
                    self.canvas.create_text(x + 4, top + 8, text=name, anchor="w", fill=Colors.TEXT_MUTED, font=self._cf["session"], tags="session")
            prev_hour = cur_hour

    def _clip_range(self, i0, i1, start, end):
        total = len(self.df)
        i1_val = (total - 1) if i1 == "end" else i1
        lo, hi = (i0, i1_val) if i0 <= i1_val else (i1_val, i0)
        clip_lo = max(lo, start)
        clip_hi = min(hi, end - 1)
        if clip_hi < clip_lo: return None
        return clip_lo - start, clip_hi - start

    def _draw_overlay_zones(self, start, end, idx_x, price_y):
        if not self.overlays: return
        slot = self._geo['candle_slot']
        for ov in self.overlays:
            if ov.get("kind") != "zone": continue
            clipped = self._clip_range(ov["i0"], ov.get("i1", ov["i0"]), start, end)
            if clipped is None: continue
            r0, r1 = clipped
            x0, x1 = idx_x(r0) - slot / 2, idx_x(r1) + slot / 2
            p0, p1 = ov["p0"], ov.get("p1", ov["p0"])
            y0, y1 = price_y(p0), price_y(p1)
            color = ov.get("color", Colors.PRIMARY)
            fill = color if ov.get("style") == "fill" else ""
            stipple = "gray25" if ov.get("style") == "fill" else ""
            self.canvas.create_rectangle(x0, min(y0, y1), x1, max(y0, y1), outline=color, fill=fill, stipple=stipple, width=1, tags="overlay")
            if ov.get("label"):
                self.canvas.create_text(x0 + 4, min(y0, y1) + 8, text=ov["label"], anchor="w", fill=color, font=self._cf["overlay"], tags="overlay")

    def _draw_overlay_lines(self, start, end, idx_x, price_y):
        if not self.overlays: return
        slot = self._geo['candle_slot']
        total = len(self.df)
        for ov in self.overlays:
            kind = ov.get("kind")
            if kind == "hline":
                clipped = self._clip_range(ov["i0"], ov.get("i1", "end"), start, end)
                if clipped is None: continue
                r0, r1 = clipped
                x0, x1 = idx_x(r0) - slot / 2, idx_x(r1) + slot / 2
                y = price_y(ov["p0"])
                color = ov.get("color", Colors.PRIMARY)
                dash = (4, 3) if ov.get("style") == "dashed" else None
                kwargs = dict(fill=color, width=ov.get("width", 1.2), tags="overlay")
                if dash: kwargs["dash"] = dash
                self.canvas.create_line(x0, y, x1, y, **kwargs)
                if ov.get("label"):
                    self.canvas.create_text(x1 - 4, y - 8, text=ov["label"], anchor="e", fill=color, font=self._cf["overlay"], tags="overlay")
            elif kind == "line":
                i0, i1 = ov["i0"], ov["i1"]
                i1 = (total - 1) if i1 == "end" else i1
                if min(i0, i1) > end - 1 or max(i0, i1) < start: continue
                self.canvas.create_line(idx_x(i0 - start), price_y(ov["p0"]), idx_x(i1 - start), price_y(ov["p1"]), fill=ov.get("color", Colors.PRIMARY), width=ov.get("width", 1.4), tags="overlay")

    def _draw_volume(self, visible, top, bottom, idx_x, body_w):
        if 'volume' not in visible.columns: return
        vmax = visible['volume'].max()
        if not vmax or vmax <= 0: return
        pane_h = (bottom - top) * 0.92
        for i, row in visible.iterrows():
            x = idx_x(i)
            h = (row['volume'] / vmax) * pane_h
            color = Colors.GREEN if row['close'] >= row['open'] else Colors.RED
            self.canvas.create_rectangle(x - body_w / 2, bottom - h, x + body_w / 2, bottom, fill=color, outline="", stipple="gray50", tags="volume")

    def _draw_ema(self, visible, price_y, idx_x, col, color):
        if col not in visible.columns: return
        pts = []
        for i, val in enumerate(visible[col]):
            if pd.isna(val): continue
            pts.extend([idx_x(i), price_y(val)])
        if len(pts) >= 4: self.canvas.create_line(*pts, fill=color, width=1.5, smooth=True, tags="ema")

    def _draw_price_line(self, visible, price_y, idx_x):
        pts = []
        for i, close in enumerate(visible['close']): pts.extend([idx_x(i), price_y(close)])
        if len(pts) >= 4:
            self.canvas.create_line(*pts, fill=Colors.PRIMARY, width=1.8, smooth=True, tags="candle")
            fill_pts = [pts[0], self._geo['price_bottom']] + pts + [pts[-2], self._geo['price_bottom']]
            self.canvas.create_polygon(*fill_pts, fill=Colors.PRIMARY, stipple="gray12", outline="", tags="candle")

    def _draw_candles(self, visible, price_y, idx_x, body_w):
        for i, row in visible.iterrows():
            x = idx_x(i)
            color = Colors.GREEN if row['close'] >= row['open'] else Colors.RED
            self.canvas.create_line(x, price_y(row['high']), x, price_y(row['low']), fill=color, width=1, tags="candle")
            y0, y1 = price_y(row['open']), price_y(row['close'])
            if abs(y1 - y0) < 1: y1 = y0 + 1
            self.canvas.create_rectangle(x - body_w / 2, min(y0, y1), x + body_w / 2, max(y0, y1), fill=color, outline=color, tags="candle")

    def _draw_high_low(self, visible, price_y, idx_x):
        hi_idx, lo_idx = int(visible['high'].idxmax()), int(visible['low'].idxmin())
        hi_val, lo_val = visible['high'].iloc[hi_idx], visible['low'].iloc[lo_idx]
        self.canvas.create_text(idx_x(hi_idx), price_y(hi_val) - 10, text=f"H {hi_val:.5f}", fill=Colors.TEXT_SECONDARY, font=self._cf["hl"], tags="hl")
        self.canvas.create_text(idx_x(lo_idx), price_y(lo_val) + 10, text=f"L {lo_val:.5f}", fill=Colors.TEXT_SECONDARY, font=self._cf["hl"], tags="hl")

    def _draw_levels(self, price_y, right, width):
        def line(level, color, label):
            if not level or level <= 0: return
            y = price_y(level)
            self.canvas.create_line(0, y, right, y, fill=color, dash=(5, 3), width=1.2, tags="levels")
            self.canvas.create_rectangle(right, y - 11, width, y + 11, fill=color, outline="", tags="levels")
            self.canvas.create_text(right + (width - right) / 2, y, text=f"{label} {level:.5f}", fill="#0B0E14", font=self._cf["axis"], tags="levels")
        line(self.entry, Chart.ENTRY, "E")
        line(self.sl, Chart.STOPLOSS, "SL")
        line(self.tp, Chart.TAKEPROFIT, "TP")

    def _draw_live_price(self, visible, price_y, right, width):
        last = visible.iloc[-1]
        price = last['close']
        y = price_y(price)
        color = Colors.GREEN if last['close'] >= last['open'] else Colors.RED
        self.canvas.create_line(0, y, right, y, fill=color, dash=(2, 2), tags="live")
        self.canvas.create_rectangle(right, y - 12, width, y + 12, fill=color, outline="", tags="live")
        self.canvas.create_text(right + (width - right) / 2, y, text=f"{price:.5f}", fill="#0B0E14", font=self._cf["live_price"], tags="live")

    def _draw_price_axis(self, top, bottom, right, width, pmin, pmax):
        rows = 6
        for i in range(rows + 1):
            y = top + (bottom - top) * i / rows
            price = pmax - (pmax - pmin) * i / rows
            self.canvas.create_text(width - 6, y, text=f"{price:.5f}", anchor="e", fill=Colors.TEXT_MUTED, font=self._cf["axis"], tags="axis")

    def _draw_time_axis(self, visible, height, idx_x):
        if 'timestamp' not in visible.columns: return
        n = len(visible)
        step = max(1, n // 6)
        wide_span = (visible['timestamp'].iloc[-1] - visible['timestamp'].iloc[0]).days >= 3
        for i in range(0, n, step):
            t = visible['timestamp'].iloc[i]
            label = t.strftime("%m/%d") if wide_span else t.strftime("%H:%M")
            self.canvas.create_text(idx_x(i), height - self.BOTTOM_AXIS_H / 2, text=label, fill=Colors.TEXT_MUTED, font=self._cf["axis"], tags="axis")

    def _draw_crosshair(self):
        self.canvas.delete("crosshair")
        geo = self._geo
        if not geo or not self._crosshair_xy: return
        x, y = self._crosshair_xy
        if x > geo['right'] or y > geo['vol_bottom'] or y < geo['price_top']: return

        self.canvas.create_line(x, geo['price_top'], x, geo['vol_bottom'], fill=Colors.TEXT_SECONDARY, dash=(3, 2), tags="crosshair")
        if geo['price_top'] <= y <= geo['price_bottom']:
            self.canvas.create_line(0, y, geo['right'], y, fill=Colors.TEXT_SECONDARY, dash=(3, 2), tags="crosshair")
            price = geo['pmax'] - (y - geo['price_top']) / (geo['price_bottom'] - geo['price_top']) * (geo['pmax'] - geo['pmin'])
            self.canvas.create_rectangle(geo['right'], y - 12, geo['width'], y + 12, fill=Colors.PRIMARY, outline="", tags="crosshair")
            self.canvas.create_text(geo['right'] + (geo['width'] - geo['right']) / 2, y, text=f"{price:.5f}", fill="#0B0E14", font=self._cf["crosshair"], tags="crosshair")

        visible = geo['visible']
        if geo['candle_slot'] > 0 and 'timestamp' in visible.columns:
            idx = int(x // geo['candle_slot'])
            if 0 <= idx < len(visible):
                t = visible['timestamp'].iloc[idx]
                self.canvas.create_rectangle(x - 58, geo['vol_bottom'], x + 58, geo['vol_bottom'] + self.BOTTOM_AXIS_H - 2, fill=Colors.PRIMARY, outline="", tags="crosshair")
                self.canvas.create_text(x, geo['vol_bottom'] + (self.BOTTOM_AXIS_H - 2) / 2, text=t.strftime("%Y-%m-%d %H:%M"), fill="#0B0E14", font=self._cf["crosshair"], tags="crosshair")

    def _start_new_candle_animation(self):
        if self._anim_job: self.after_cancel(self._anim_job)
        self._anim_frame = 0
        self._animate_step()

    def _animate_step(self):
        geo = self._geo
        if not geo or geo['visible'].empty: return
        self._anim_frame += 1
        self.canvas.delete("newcandle_glow")
        progress = self._anim_frame / self._anim_total_frames
        if progress >= 1.0:
            self._anim_job = None
            return
        visible = geo['visible']
        row = visible.iloc[-1]
        x = geo['idx_x'](len(visible) - 1)
        color = Colors.GREEN if row['close'] >= row['open'] else Colors.RED
        radius = geo['body_w'] * (0.7 + progress * 1.4)
        self.canvas.create_rectangle(x - radius, geo['price_y'](row['high']) - 5, x + radius, geo['price_y'](row['low']) + 5, outline=color, width=max(1, int(3 * (1 - progress)) + 1), tags="newcandle_glow")
        self._anim_job = self.after(35, self._animate_step)