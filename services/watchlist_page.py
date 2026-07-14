"""
ui/watchlist_page.py
======================
Full-page Live Market Watchlist — Bloomberg-style.

Features:
  • Tabs: Forex | Crypto | Metals | Indices | Commodities
  • Search bar (filters symbol + name instantly)
  • Sort: by Symbol, Price, Change% (asc/desc toggle)
  • % Change column with color (green/red)
  • Real-time price updates via update_watchlist()
  • Click row → triggers on_asset_click(symbol) to load chart
  • All background reads; zero UI freeze
"""
from __future__ import annotations
import time
import threading
import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing

# ─── Symbol registry ─────────────────────────────────────────────────────────
TABS: list[tuple[str, list[tuple[str, str]]]] = [
    ("⭐ Favs", None),   # sentinel — populated from favorites set
    ("Forex", [
        ("EUR/USD","EUR/USD"),("GBP/USD","GBP/USD"),("USD/JPY","USD/JPY"),
        ("AUD/USD","AUD/USD"),("USD/CAD","USD/CAD"),("USD/CHF","USD/CHF"),
        ("NZD/USD","NZD/USD"),("EUR/GBP","EUR/GBP"),("EUR/JPY","EUR/JPY"),
        ("GBP/JPY","GBP/JPY"),("EUR/AUD","EUR/AUD"),("EUR/CAD","EUR/CAD"),
        ("AUD/JPY","AUD/JPY"),("GBP/AUD","GBP/AUD"),("GBP/CAD","GBP/CAD"),
        ("CAD/JPY","CAD/JPY"),("NZD/JPY","NZD/JPY"),("CHF/JPY","CHF/JPY"),
        ("EUR/NZD","EUR/NZD"),("EUR/CHF","EUR/CHF"),("GBP/CHF","GBP/CHF"),
        ("GBP/NZD","GBP/NZD"),("AUD/NZD","AUD/NZD"),("AUD/CAD","AUD/CAD"),
        ("AUD/CHF","AUD/CHF"),("NZD/CAD","NZD/CAD"),("NZD/CHF","NZD/CHF"),
        ("USD/MXN","USD/MXN"),("USD/ZAR","USD/ZAR"),("USD/NOK","USD/NOK"),
        ("USD/SEK","USD/SEK"),("USD/TRY","USD/TRY"),
    ]),
    ("Crypto", [
        ("BTC","Bitcoin"),("ETH","Ethereum"),("BNB","BNB"),
        ("SOL","Solana"),("XRP","Ripple"),("ADA","Cardano"),
        ("DOGE","Dogecoin"),("AVAX","Avalanche"),("MATIC","Polygon"),
        ("DOT","Polkadot"),("LINK","Chainlink"),("LTC","Litecoin"),
        ("UNI","Uniswap"),("ATOM","Cosmos"),("TRX","Tron"),
        ("TON","Toncoin"),("BCH","Bitcoin Cash"),("APT","Aptos"),
        ("ARB","Arbitrum"),("OP","Optimism"),("INJ","Injective"),
        ("SUI","Sui"),("NEAR","NEAR"),("FTM","Fantom"),("ALGO","Algorand"),
        ("VET","VeChain"),("AAVE","Aave"),("MKR","Maker"),("LDO","Lido"),
        ("RUNE","THORChain"),("HBAR","Hedera"),
    ]),
    ("Metals", [
        ("XAU/USD","Gold / USD"),("XAG/USD","Silver / USD"),
    ]),
    ("Indices", [
        ("US30","Dow Jones 30"),("NAS100","Nasdaq 100"),("SPX500","S&P 500"),
    ]),
    ("All", None),   # sentinel — all instruments
]

# Binance price cache for crypto (populated by background thread)
_binance_price_cache_wl: dict[str, float] = {}

def _fetch_binance_prices_wl() -> dict[str, float]:
    global _binance_price_cache_wl
    try:
        import json
        from urllib.request import urlopen, Request
        req = Request(
            "https://api.binance.com/api/v3/ticker/24hr",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        prices = {}
        changes = {}
        for item in data:
            sym = item["symbol"]
            if sym.endswith("USDT"):
                base = sym[:-4]
                prices[base] = float(item["lastPrice"])
                changes[base] = float(item["priceChangePercent"])
        _binance_price_cache_wl = {"prices": prices, "changes": changes}
        return _binance_price_cache_wl
    except Exception:
        return _binance_price_cache_wl



def _price_fmt(symbol: str, price: float) -> str:
    """Smart price formatter — adapts decimal places to price magnitude.
    
    Ensures BTC always shows $64,061 not $28 or $64061.0000.
    Works for all asset classes without a hardcoded symbol list.
    """
    if not price or price <= 0:
        return "—"
    s = symbol.upper()
    # Forex / metals: always 5 decimal places
    _FOREX_ENDINGS = ("USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD")
    if "/" in symbol and any(s.endswith(e) for e in _FOREX_ENDINGS):
        return f"{price:,.5f}"
    if "XAU" in s or "XAG" in s:
        return f"{price:,.2f}"
    # Indices
    if any(idx in s for idx in ("US30","NAS100","SPX500","DAX","FTSE","UK100","GER40","JP225")):
        return f"{price:,.1f}"
    # Crypto and everything else — by price magnitude
    if price >= 10_000:
        return f"{price:,.2f}"   # BTC, high-value: $64,061.20
    elif price >= 1_000:
        return f"{price:,.2f}"   # ETH, BNB: $1,822.40
    elif price >= 100:
        return f"{price:,.2f}"   # SOL, AVAX: $246.60
    elif price >= 1:
        return f"{price:,.4f}"   # APT, TRX: $5.0800
    else:
        return f"{price:,.6f}"   # DOGE, SHIB: $0.073600


# ─── Row widget ───────────────────────────────────────────────────────────────
class _Row(ctk.CTkFrame):
    def __init__(self, parent, symbol: str, name: str, on_click, idx: int, on_fav=None, _on_fav_set=None):
        bg = Colors.CARD_BG if idx % 2 == 0 else Colors.WELL_BG
        super().__init__(parent, fg_color=bg, height=S.ROW_H(), corner_radius=s(4), cursor="hand2")
        self.pack(fill="x", padx=4, pady=1)
        self.pack_propagate(False)
        self._bg = bg
        self._symbol = symbol

        # Columns: fav | symbol | name | price | change
        for col, weight in enumerate((1, 3, 5, 4, 3)):
            self.grid_columnconfigure(col, weight=weight)

        self._is_fav = symbol in (_on_fav_set if _on_fav_set else set())
        self._fav_btn = ctk.CTkButton(
            self, text="★" if self._is_fav else "☆",
            width=S.ICON_BTN(), height=S.ICON_BTN(), corner_radius=s(4), font=SF.NORMAL(),
            fg_color="transparent",
            hover_color=Colors.HOVER,
            text_color=Colors.GOLD if self._is_fav else Colors.TEXT_MUTED,
            command=lambda: on_fav(symbol))
        self._fav_btn.grid(row=0, column=0, sticky="w", padx=(6, 0))

        self._lbl_sym = ctk.CTkLabel(self, text=symbol, font=SF.MONO_SM(),
                                      text_color=Colors.TEXT, anchor="w")
        self._lbl_sym.grid(row=0, column=1, sticky="w", padx=(4,4))

        self._lbl_name = ctk.CTkLabel(self, text=name[:18], font=SF.TINY(),
                                       text_color=Colors.TEXT_MUTED, anchor="w")
        self._lbl_name.grid(row=0, column=2, sticky="w", padx=4)

        self._lbl_price = ctk.CTkLabel(self, text="—", font=SF.MONO_SM(),
                                        text_color=Colors.TEXT_SECONDARY, anchor="e")
        self._lbl_price.grid(row=0, column=3, sticky="e", padx=4)

        self._lbl_chg = ctk.CTkLabel(self, text="—", font=SF.MONO_SM(),
                                      text_color=Colors.TEXT_MUTED, anchor="e")
        self._lbl_chg.grid(row=0, column=4, sticky="e", padx=(4,10))

        self.bind("<Enter>", lambda e: self.configure(fg_color=Colors.HOVER))
        self.bind("<Leave>", lambda e: self.configure(fg_color=self._bg))
        for w in self.winfo_children():
            if w is not self._fav_btn:
                w.bind("<Button-1>", lambda e, s=symbol: on_click(s))
        self.bind("<Button-1>", lambda e, s=symbol: on_click(s))
    
    def set_fav_state(self, is_fav: bool):
        self._is_fav = is_fav
        self._fav_btn.configure(
            text="★" if is_fav else "☆",
            text_color=Colors.GOLD if is_fav else Colors.TEXT_MUTED)

    def update(self, price: float | None, change_pct: float | None):
        if price is None:
            self._lbl_price.configure(text="—", text_color=Colors.TEXT_MUTED)
            self._lbl_chg.configure(text="—", text_color=Colors.TEXT_MUTED)
            return
        self._lbl_price.configure(text=_price_fmt(self._symbol, price),
                                   text_color=Colors.TEXT)
        if change_pct is not None:
            sign = "+" if change_pct >= 0 else ""
            color = Colors.BUY if change_pct >= 0 else Colors.SELL
            self._lbl_chg.configure(text=f"{sign}{change_pct:.2f}%", text_color=color)
        else:
            self._lbl_chg.configure(text="—", text_color=Colors.TEXT_MUTED)


# ─── Main page ────────────────────────────────────────────────────────────────
class WatchlistPage(ctk.CTkFrame):
    def __init__(self, parent, on_asset_click=None):
        super().__init__(parent, fg_color=Colors.APP_BG, corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._on_asset_click = on_asset_click or (lambda s: None)
        self._price_map:  dict[str,float]  = {}
        self._change_map: dict[str,float]  = {}
        self._search_var  = ctk.StringVar()
        self._sort_col    = "symbol"   # symbol | price | change
        self._sort_asc    = True
        self._active_tab  = "Forex"
        self._rows: dict[str,_Row] = {}
        self._favorites:  set[str]  = set()   # ← user-starred symbols
        self._destroyed   = False

        # ── Page header ───────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(), pady=(Spacing.LG(), 6))

        ctk.CTkLabel(hdr, text="LIVE MARKET WATCHLIST", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")

        self._btn_refresh = ctk.CTkButton(
            hdr, text="⟳ Refresh", width=s(90), height=s(28), corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=self._manual_refresh)
        self._btn_refresh.pack(side="right", padx=(6, 0))

        self._lbl_count = ctk.CTkLabel(hdr, text="", font=SF.TINY(),
                                        text_color=Colors.TEXT_MUTED)
        self._lbl_count.pack(side="right", padx=8)

        self._lbl_updated = ctk.CTkLabel(hdr, text="", font=SF.TINY(),
                                          text_color=Colors.TEXT_MUTED)
        self._lbl_updated.pack(side="right", padx=8)

        # ── Controls bar: tabs + search + sort ────────────────────────
        ctrl = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                             border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        ctrl.grid(row=1, column=0, sticky="ew", padx=Spacing.LG(), pady=(0, 6))

        # Tab buttons
        self._tab_btns: dict[str,ctk.CTkButton] = {}
        tab_bar = ctk.CTkFrame(ctrl, fg_color="transparent")
        tab_bar.pack(side="left", padx=8, pady=8)
        for label, _ in TABS:
            b = ctk.CTkButton(
                tab_bar, text=label, width=s(72), height=s(26), corner_radius=s(5),
                fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                text_color=Colors.TEXT_MUTED, font=SF.PILL_LG(),
                command=lambda k=label: self._switch_tab(k),
            )
            b.pack(side="left", padx=2)
            self._tab_btns[label] = b

        # Search
        ctk.CTkLabel(ctrl, text="🔍", font=SF.SUBHEADER(),
                     text_color=Colors.TEXT_MUTED).pack(side="left", padx=(12, 4))
        self._search_entry = ctk.CTkEntry(
            ctrl, width=s(180), height=s(28), textvariable=self._search_var,
            placeholder_text="Search symbol or name…",
            fg_color=Colors.INPUT_BG, border_color=Colors.BORDER, text_color=Colors.TEXT,
            font=SF.NAV(),
        )
        self._search_entry.pack(side="left", padx=4, pady=8)
        self._search_var.trace_add("write", lambda *_: self._rebuild_table())

        # Sort buttons
        sort_frame = ctk.CTkFrame(ctrl, fg_color="transparent")
        sort_frame.pack(side="right", padx=8, pady=8)
        ctk.CTkLabel(sort_frame, text="Sort:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(0,4))
        for col, lbl in [("symbol","Symbol"),("price","Price"),("change","Change%")]:
            ctk.CTkButton(
                sort_frame, text=lbl, width=s(70), height=s(26), corner_radius=s(5),
                fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                text_color=Colors.TEXT_MUTED, font=SF.STATUS_BOLD(),
                command=lambda c=col: self._toggle_sort(c),
            ).pack(side="left", padx=2)

        # ── Table area ────────────────────────────────────────────────
        table_outer = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                                    border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        table_outer.grid(row=2, column=0, sticky="nsew", padx=Spacing.LG(), pady=(0,Spacing.LG()))
        table_outer.grid_columnconfigure(0, weight=1)
        table_outer.grid_rowconfigure(1, weight=1)

        # Column headers
        hdr_row = ctk.CTkFrame(table_outer, fg_color=Colors.SIDEBAR_BG, corner_radius=0)
        hdr_row.grid(row=0, column=0, sticky="ew")
        for col, weight, text in [(0,3,"SYMBOL"),(1,5,"NAME"),(2,4,"PRICE"),(3,3,"CHANGE %")]:
            hdr_row.grid_columnconfigure(col, weight=weight)
            ctk.CTkLabel(hdr_row, text=text, font=("Segoe UI",9,"bold"),
                          text_color=Colors.LABEL, anchor="w" if col<2 else "e"
                         ).grid(row=0, column=col, sticky="we",
                                padx=(10 if col==0 else 4), pady=8)

        self._scroll = ctk.CTkScrollableFrame(
            table_outer, fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY,
        )
        self._scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

        # FIX: Boost scroll speed - CTkScrollableFrame default is too slow
        self._bind_fast_scroll(self._scroll)
        # Poll the shared PriceFeed singleton from the main thread.
        # The PriceFeed (initialized in main_window.py) fetches ALL Binance
        # tickers every 3 s via a single HTTP call — no need for a separate
        # per-watchlist background thread duplicating the same work.
        self.after(500, self._drain_price_feed)
        # Separate 24hr change% fetch (runs every 30 s — less frequent is fine
        # for the change% column, and Binance 24hr endpoint is heavier)
        self.after(1000, lambda: threading.Thread(
            target=self._fetch_binance_bg, daemon=True).start())
        self.after(30000, self._schedule_change_refresh)
        self._switch_tab("Forex")

    # ── Fast scroll binding ───────────────────────────────────────────
    def _bind_fast_scroll(self, frame):
        """Bind faster mousewheel scrolling to CTkScrollableFrame.
        Default CTkScrollableFrame scroll is 1 unit per delta=120 on Windows.
        This multiplies it by 4x for responsive feel."""
        def _fast_wheel(event):
            # Access the internal canvas of CTkScrollableFrame
            canvas = getattr(frame, '_parent_canvas', None)
            if canvas is None:
                # Try common attribute names across CTk versions
                for attr in ('_parent_canvas', '_canvas', 'canvas'):
                    if hasattr(frame, attr):
                        canvas = getattr(frame, attr)
                        break
            if canvas is not None:
                # Windows: event.delta is ±120 per notch; multiply for speed
                units = -int(event.delta / 30)
                canvas.yview_scroll(units, "units")
            return "break"  # prevent propagation to parent

        def _bind_recursive(widget):
            widget.bind("<MouseWheel>", _fast_wheel, add="+")
            widget.bind("<Button-4>", lambda e: (getattr(getattr(frame, '_parent_canvas', None) or frame, 'yview_scroll', lambda *a: None)(-3, "units")), add="+")
            widget.bind("<Button-5>", lambda e: (getattr(getattr(frame, '_parent_canvas', None) or frame, 'yview_scroll', lambda *a: None)(3, "units")), add="+")
            for child in widget.winfo_children():
                _bind_recursive(child)

        _bind_recursive(frame)

    # ── Tab switching ──────────────────────────────────────────────────
    def _all_symbols(self) -> list[tuple[str,str]]:
        result = []
        for lbl, syms in TABS:
            if lbl != "All" and syms:
                result.extend(syms)
        return result

    def _tab_symbols(self, tab: str) -> list[tuple[str,str]]:
        if tab == "All":
            return self._all_symbols()
        if tab == "⭐ Favs":
            # Build list from all tabs filtering to favorites
            all_syms = {s: n for _, items in TABS if items for s, n in items}
            return [(s, all_syms.get(s, s)) for s in sorted(self._favorites)]
        for lbl, syms in TABS:
            if lbl == tab and syms:
                return syms
        return []

    def _toggle_fav(self, symbol: str):
        """Add or remove symbol from favorites and rebuild."""
        if symbol in self._favorites:
            self._favorites.discard(symbol)
        else:
            self._favorites.add(symbol)
        # Update star button in existing row
        if symbol in self._rows:
            self._rows[symbol].set_fav_state(symbol in self._favorites)
        # Rebuild Favs tab count badge
        fav_btn = self._tab_btns.get("⭐ Favs")
        if fav_btn:
            n = len(self._favorites)
            fav_btn.configure(text=f"⭐ Favs{' (' + str(n) + ')' if n else ''}")
        if self._active_tab == "⭐ Favs":
            self._rebuild_table()

    def _switch_tab(self, key: str):
        self._active_tab = key
        for k, b in self._tab_btns.items():
            b.configure(
                fg_color=Colors.PRIMARY if k==key else Colors.CARD_BG_ALT,
                text_color=Colors.ON_BUY if k==key else Colors.TEXT_MUTED,
            )
        # Defer rebuild slightly so button highlight renders first (prevents UI freeze on All)
        self.after(10, self._rebuild_table)

    # ── Sort ──────────────────────────────────────────────────────────
    def _toggle_sort(self, col: str):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._rebuild_table()

    # ── Table rebuild (optimized: reuses rows, no destroy/recreate) ──
    def _rebuild_table(self):
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        q = self._search_var.get().strip().upper()
        syms = self._tab_symbols(self._active_tab)
        if q:
            syms = [(s,n) for s,n in syms if q in s.upper() or q in n.upper()]

        # Sort
        if self._sort_col == "price":
            syms = sorted(syms, key=lambda x: self._price_map.get(x[0], 0.0),
                          reverse=not self._sort_asc)
        elif self._sort_col == "change":
            syms = sorted(syms, key=lambda x: self._change_map.get(x[0], 0.0),
                          reverse=not self._sort_asc)
        else:
            syms = sorted(syms, key=lambda x: x[0], reverse=not self._sort_asc)

        needed = {s for s,_ in syms}

        # Remove rows that are no longer visible (batch, safe)
        to_remove = [sym for sym in list(self._rows.keys()) if sym not in needed]
        for sym in to_remove:
            try:
                row = self._rows.pop(sym)
                row.pack_forget()
                row.destroy()
            except Exception:
                pass

        # Empty state for Favorites tab
        # Remove any stale empty-state label first
        for w in list(self._scroll.winfo_children()):
            if getattr(w, '_empty_state', False):
                try:
                    w.destroy()
                except Exception:
                    pass

        if not syms:
            lbl = ctk.CTkLabel(
                self._scroll,
                text=(
                    "⭐  No favourites yet\n\nClick the ★ star next to any instrument to add it here."
                    if self._active_tab == "⭐ Favs"
                    else "No instruments match your search."
                ),
                font=SF.SMALL(), text_color=Colors.TEXT_MUTED,
                justify="center",
            )
            lbl._empty_state = True
            lbl.pack(pady=40, expand=True)
            return

        # Reorder/create rows
        for idx, (symbol, name) in enumerate(syms):
            try:
                if symbol in self._rows:
                    row = self._rows[symbol]
                    bg = Colors.CARD_BG if idx % 2 == 0 else Colors.WELL_BG
                    row._bg = bg
                    try:
                        row.configure(fg_color=bg)
                    except Exception:
                        pass
                else:
                    row = _Row(self._scroll, symbol, name, self._on_asset_click,
                               idx, on_fav=self._toggle_fav,
                               _on_fav_set=self._favorites)
                    self._rows[symbol] = row
                    # Only bind scroll on the row frame itself, not recursively (prevents crash on large lists)
                    self._bind_scroll_safe(row)
                row.pack(fill="x", padx=4, pady=1)
                price  = self._price_map.get(symbol)
                change = self._change_map.get(symbol)
                try:
                    row.update(price, change)
                except Exception:
                    pass
            except Exception:
                pass

        try:
            self._lbl_count.configure(text=f"{len(syms)} instruments")
        except Exception:
            pass

    def _bind_scroll_safe(self, widget):
        """Bind fast scroll only on the widget itself (not recursively) to prevent crash on large lists."""
        canvas = getattr(self._scroll, '_parent_canvas', None)
        if canvas is None:
            for attr in ('_parent_canvas', '_canvas', 'canvas'):
                if hasattr(self._scroll, attr):
                    canvas = getattr(self._scroll, attr)
                    break
        if canvas is None:
            return
        def _fast_wheel(event, c=canvas):
            try:
                units = -int(event.delta / 30)
                c.yview_scroll(units, "units")
            except Exception:
                pass
            return "break"
        try:
            widget.bind("<MouseWheel>", _fast_wheel, add="+")
        except Exception:
            pass

    # ── Market-hours awareness ─────────────────────────────────────────
    @staticmethod
    def _is_forex_market_open_now() -> bool:
        """True when at least one major forex session is active (Mon–Fri, Sun 22:00+ UTC)."""
        from datetime import datetime, timezone as _tz
        now = datetime.now(_tz.utc)
        wd  = now.weekday()   # 0=Mon … 5=Sat, 6=Sun
        h   = now.hour
        if wd == 5:            # Saturday — always closed
            return False
        if wd == 6 and h < 22: # Sunday before Sydney open
            return False
        return True

    # ── Price updates (called from main_window + Binance bg thread) ──
    def update_watchlist(self, price_list: list):
        """Accept same format as old MarketWatchlist.update_watchlist()."""
        if self._destroyed:
            return
        for item in price_list:
            sym   = item.get("asset")
            price = item.get("price")
            chg   = item.get("change_pct")
            if sym and price is not None:
                self._price_map[sym]  = price
                if chg is not None:
                    self._change_map[sym] = chg
        market_open = self._is_forex_market_open_now()
        for sym, row in list(self._rows.items()):
            try:
                is_forex = ('/' in sym or sym in ('US30', 'NAS100', 'SPX500'))
                if is_forex and not market_open:
                    # Show last known price but grey out change to indicate market closed
                    row.update(self._price_map.get(sym), None)
                else:
                    row.update(self._price_map.get(sym), self._change_map.get(sym))
            except Exception:
                pass
        try:
            status = "Updated " + time.strftime('%H:%M:%S')
            if not market_open:
                status += " — Forex CLOSED (Weekend)"
            self._lbl_updated.configure(text=status)
        except Exception:
            pass

    def _drain_price_feed(self):
        """Main-thread: pull the latest crypto prices from the shared PriceFeed
        singleton (which already fetches Binance every 3 s in its own thread)
        and apply them to the visible watchlist rows.

        This replaces the old per-watchlist Binance background thread with a
        lightweight read from a shared cache — same real-time Binance data,
        no duplicate HTTP requests.
        """
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        try:
            from services.price_feed import get_all_prices as _pf_all
            all_prices = _pf_all()
            if all_prices:
                # Build bare-symbol → price map (e.g. BTC → 64066.0)
                prices = {}
                for ticker, px in all_prices.items():
                    if ticker.endswith("USDT") and not ticker.endswith("BUSDT"):
                        base = ticker[:-4]
                        prices[base] = float(px)
                    elif not "/" in ticker and len(ticker) <= 6:
                        # Already a bare symbol registered by PriceFeed
                        prices[ticker] = float(px)
                if prices:
                    self._apply_binance_prices(prices, {})
        except Exception:
            pass

        # Also run the legacy module-level fetch for 24hr change % data
        # (PriceFeed only tracks spot price, not 24hr change %)
        try:
            data = _binance_price_cache_wl
            changes = data.get("changes", {})
            if changes:
                for base, pct in changes.items():
                    self._change_map[base] = pct
        except Exception:
            pass

        try:
            if not self._destroyed:
                self.after(3000, self._drain_price_feed)  # match PriceFeed interval
        except RuntimeError:
            pass

    # Keep for 24hr change % background fetching (price now comes from PriceFeed)
    def _fetch_binance_bg(self):
        """Background: fetch Binance 24hr data for change % column only.
        Prices come from the shared PriceFeed singleton instead."""
        if self._destroyed:
            return
        _fetch_binance_prices_wl()  # updates module-level _binance_price_cache_wl

    def _apply_binance_prices(self, prices: dict, changes: dict):
        """Main-thread: merge Binance prices into price_map for crypto symbols."""
        if self._destroyed:
            return
        for base, px in prices.items():
            if base not in self._price_map or self._price_map[base] == 0:
                self._price_map[base] = px
            else:
                self._price_map[base] = px   # always use fresh Binance price for crypto
        for base, pct in changes.items():
            self._change_map[base] = pct
        # Refresh visible crypto rows
        for sym, row in self._rows.items():
            if "/" not in sym and sym not in ("US30","NAS100","SPX500"):
                row.update(self._price_map.get(sym), self._change_map.get(sym))
        self._lbl_updated.configure(text=f"Updated {time.strftime('%H:%M:%S')} (Binance)")

    def _schedule_change_refresh(self):
        """Periodically re-fetch 24hr change % data from Binance in the background."""
        if self._destroyed:
            return
        threading.Thread(target=self._fetch_binance_bg, daemon=True).start()
        try:
            if not self._destroyed:
                self.after(30000, self._schedule_change_refresh)
        except RuntimeError:
            pass

    def destroy(self):
        self._destroyed = True
        try:
            super().destroy()
        except Exception:
            pass

    def _manual_refresh(self):
        self._btn_refresh.configure(text="Loading…", state="disabled")
        self.after(1500, lambda: self._btn_refresh.configure(text="⟳ Refresh", state="normal"))
        # Force a visible table rebuild
        self._rebuild_table()
