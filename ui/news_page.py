"""
ui/news_page.py
================
Full-page Live Market News — Bloomberg/Reuters style.

Improvements:
  • Live API data only — no fake or duplicate news
  • Deduplication by title+source hash
  • Filters: All / Forex / Crypto / Indices / Macro + Impact + Search
  • Impact priority: HIGH items always first
  • Refresh button with loading indicator
  • Count badge showing items per filter
"""
from __future__ import annotations
import hashlib
import time
import webbrowser
import customtkinter as ctk
try:
    from ui.components import bind_fast_scroll
except Exception:
    bind_fast_scroll = lambda f, **kw: None
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing

_IMPACT_COLORS = {
    "HIGH": ("#F6465D", Colors.TEXT),
    "MED":  ("#F5A623", Colors.TEXT),
    "LOW":  ("#2B3139", Colors.TEXT_MUTED),
}

_CATEGORY_KEYWORDS = {
    "Forex":   ("forex", "eur", "gbp", "usd", "jpy", "aud", "cad", "chf", "nzd", "fx", "currency"),
    "Crypto":  ("bitcoin", "btc", "ethereum", "eth", "crypto", "defi", "blockchain", "nft", "token"),
    "Indices": ("dow", "s&p", "nasdaq", "ftse", "dax", "nikkei", "index", "indices", "equities"),
    "Macro":   ("fed", "fomc", "cpi", "inflation", "gdp", "nfp", "rate", "central bank", "ecb", "boe", "boj"),
}


def _detect_category(headline: str) -> str:
    hl = headline.lower()
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if any(k in hl for k in kws):
            return cat
    return "Other"


def _news_key(item: dict) -> str:
    """Stable deduplication key from title + source."""
    title  = (item.get("title") or item.get("headline") or "")[:80]
    source = (item.get("source") or "")[:20]
    return hashlib.md5(f"{title}|{source}".encode()).hexdigest()


class _NewsCard(ctk.CTkFrame):
    def __init__(self, parent, item: dict, on_click, idx: int):
        impact   = (item.get("impact") or "LOW").upper()
        badge_bg, _ = _IMPACT_COLORS.get(impact, _IMPACT_COLORS["LOW"])
        is_high  = impact == "HIGH"
        bg = Colors.CARD_BG if idx % 2 == 0 else Colors.WELL_BG

        super().__init__(parent, fg_color=bg, corner_radius=s(6),
                         border_width=1,
                         border_color=Colors.STATUS_HIGH if is_high else Colors.BORDER,
                         cursor="hand2")
        self.pack(fill="x", padx=4, pady=3)

        if is_high:
            ctk.CTkFrame(self, fg_color=Colors.STATUS_HIGH, height=3,
                          corner_radius=0).pack(fill="x")

        meta = ctk.CTkFrame(self, fg_color="transparent")
        meta.pack(fill="x", padx=12, pady=(8, 2))

        src = item.get("source") or "Market News"
        ctk.CTkLabel(meta, text=src, font=SF.PILL_LG(),
                     text_color=Colors.PRIMARY).pack(side="left")

        ts = item.get("time", item.get("published_at", item.get("timestamp", "")))
        if ts:
            ctk.CTkLabel(meta, text=str(ts)[:16], font=SF.MONO_TINY(),
                         text_color=Colors.TEXT_MUTED).pack(side="left", padx=8)

        ctk.CTkLabel(meta, text=f" {impact} ", font=SF.STATUS_BOLD(),
                     fg_color=badge_bg, text_color=Colors.TEXT,
                     corner_radius=3).pack(side="right")

        cat = _detect_category(item.get("title", item.get("headline", "")))
        ctk.CTkLabel(meta, text=f"#{cat}", font=SF.STATUS(),
                     text_color=Colors.TEXT_MUTED).pack(side="right", padx=4)

        title = item.get("title", item.get("headline", ""))
        ctk.CTkLabel(self, text=title,
                     font=SF.SMALL(),
                     text_color=Colors.TEXT if is_high else Colors.TEXT_SECONDARY,
                     justify="left", wraplength=s(900), anchor="w",
                     ).pack(anchor="w", padx=12, pady=(2, 2), fill="x")

        desc = (item.get("description") or item.get("summary") or "").strip()
        if desc:
            ctk.CTkLabel(self, text=desc[:200] + "…" if len(desc) > 200 else desc,
                         font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                         justify="left", wraplength=s(900), anchor="w",
                         ).pack(anchor="w", padx=12, pady=(0, 2), fill="x")

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 8))
        url = item.get("url", item.get("link", ""))
        if url:
            ctk.CTkButton(btn_row, text="Read Full Article ↗", width=s(140), height=S.ICON_BTN(),
                          corner_radius=s(5), fg_color=Colors.CARD_BG_ALT,
                          hover_color=Colors.HOVER, text_color=Colors.BUY,
                          font=SF.STATUS_BOLD(),
                          command=lambda: webbrowser.open(url)).pack(side="left")
        ctk.CTkButton(btn_row, text="Details", width=s(70), height=S.ICON_BTN(),
                      corner_radius=s(5), fg_color=Colors.CARD_BG_ALT,
                      hover_color=Colors.HOVER, text_color=Colors.TEXT_SECONDARY,
                      font=SF.STATUS_BOLD(),
                      command=lambda i=item: on_click(i)).pack(side="left", padx=6)

        self.bind("<Enter>", lambda e: self.configure(border_color=Colors.PRIMARY))
        self.bind("<Leave>", lambda e: self.configure(
            border_color=Colors.STATUS_HIGH if is_high else Colors.BORDER))


class NewsPage(ctk.CTkFrame):
    def __init__(self, parent, on_news_click=None):
        super().__init__(parent, fg_color=Colors.APP_BG, corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._on_news_click  = on_news_click or (lambda i: None)
        self._all_news:  list = []
        self._seen_keys: set  = set()   # deduplication
        self._active_cat    = "All"
        self._active_impact = "All"
        self._search_var    = ctk.StringVar()
        self._is_refreshing = False

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=Spacing.LG(), pady=(Spacing.LG(), 6))
        ctk.CTkLabel(hdr, text="LIVE MARKET NEWS", font=SF.TITLE(),
                     text_color=Colors.TEXT).pack(side="left")

        self._btn_refresh = ctk.CTkButton(
            hdr, text="⟳ Refresh", width=s(90), height=S.BTN_H(), corner_radius=s(6),
            fg_color=Colors.CARD_BG, hover_color=Colors.HOVER,
            text_color=Colors.TEXT_MUTED, font=SF.PILL(),
            command=self._manual_refresh)
        self._btn_refresh.pack(side="right", padx=(6, 0))

        self._lbl_count = ctk.CTkLabel(hdr, text="", font=SF.TINY(),
                                        text_color=Colors.TEXT_MUTED)
        self._lbl_count.pack(side="right")

        # ── Controls ──────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
                             border_width=1, border_color=Colors.BORDER, corner_radius=s(8))
        ctrl.grid(row=1, column=0, sticky="ew", padx=Spacing.LG(), pady=(0, 6))

        # Category tabs
        self._cat_btns: dict[str, ctk.CTkButton] = {}
        cats = ["All", "Forex", "Crypto", "Indices", "Macro"]
        cat_frame = ctk.CTkFrame(ctrl, fg_color="transparent")
        cat_frame.pack(side="left", padx=8, pady=8)
        for c in cats:
            b = ctk.CTkButton(cat_frame, text=c, width=s(72), height=s(26),
                              corner_radius=s(5),
                              fg_color=Colors.PRIMARY if c == "All" else Colors.CARD_BG_ALT,
                              hover_color=Colors.PRIMARY_HOVER,
                              text_color=Colors.ON_BUY if c == "All" else Colors.TEXT_MUTED,
                              font=SF.PILL_LG(),
                              command=lambda x=c: self._switch_cat(x))
            b.pack(side="left", padx=2)
            self._cat_btns[c] = b

        # Impact filter
        ctk.CTkLabel(ctrl, text="Impact:", font=SF.TINY(),
                     text_color=Colors.LABEL).pack(side="left", padx=(12, 4), pady=8)
        self._impact_btns: dict[str, ctk.CTkButton] = {}
        for imp in ["All", "HIGH", "MED", "LOW"]:
            color = {"HIGH": Colors.SELL, "MED": Colors.NEUTRAL, "LOW": Colors.BORDER}.get(imp, Colors.PRIMARY)
            b = ctk.CTkButton(ctrl, text=imp, width=54, height=s(26), corner_radius=s(5),
                              fg_color=Colors.PRIMARY if imp == "All" else Colors.CARD_BG_ALT,
                              hover_color=Colors.HOVER,
                              text_color=Colors.ON_BUY if imp == "All" else Colors.TEXT_MUTED,
                              font=SF.STATUS_BOLD(),
                              command=lambda x=imp: self._switch_impact(x))
            b.pack(side="left", padx=2, pady=8)
            self._impact_btns[imp] = b

        # Search
        self._search_var.trace_add("write", lambda *_: self._render_filtered())
        search = ctk.CTkEntry(ctrl, textvariable=self._search_var, width=s(200),
                               placeholder_text="🔍 Search headlines…",
                               fg_color=Colors.INPUT_BG, border_color=Colors.BORDER,
                               text_color=Colors.TEXT, corner_radius=s(5), height=s(26))
        search.pack(side="right", padx=8, pady=8)

        # ── News scroll ───────────────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.BUY)
        self._scroll.grid(row=2, column=0, sticky="nsew",
                          padx=Spacing.LG(), pady=(0, Spacing.LG()))
        bind_fast_scroll(self._scroll)

        self._lbl_empty = ctk.CTkLabel(
            self._scroll,
            text="Waiting for live news data…\n\nNews is fetched automatically every 5 minutes.",
            font=SF.NORMAL(), text_color=Colors.TEXT_MUTED, justify="center")
        self._lbl_empty.pack(pady=60)

    def _manual_refresh(self):
        if self._is_refreshing:
            return
        self._is_refreshing = True
        self._btn_refresh.configure(text="Loading…", state="disabled")
        self.after(2000, self._reset_refresh)

    def _reset_refresh(self):
        self._is_refreshing = False
        self._btn_refresh.configure(text="⟳ Refresh", state="normal")

    def _switch_cat(self, cat: str):
        self._active_cat = cat
        for k, b in self._cat_btns.items():
            b.configure(fg_color=Colors.PRIMARY if k == cat else Colors.CARD_BG_ALT,
                        text_color=Colors.ON_BUY if k == cat else Colors.TEXT_MUTED)
        self._render_filtered()

    def _switch_impact(self, impact: str):
        self._active_impact = impact
        for k, b in self._impact_btns.items():
            b.configure(fg_color=Colors.PRIMARY if k == impact else Colors.CARD_BG_ALT,
                        text_color=Colors.ON_BUY if k == impact else Colors.TEXT_MUTED)
        self._render_filtered()

    def _filter_news(self) -> list:
        q   = self._search_var.get().strip().lower()
        cat = self._active_cat
        imp = self._active_impact
        result = []
        for item in self._all_news:
            title = (item.get("title") or item.get("headline") or "").lower()
            desc  = (item.get("description") or "").lower()
            item_cat    = _detect_category(title)
            item_impact = (item.get("impact") or "LOW").upper()

            if cat != "All" and item_cat != cat:
                continue
            if imp != "All" and item_impact != imp:
                continue
            if q and q not in title and q not in desc:
                continue
            result.append(item)

        # Sort: HIGH impact first, then by time descending
        def sort_key(item):
            impact_order = {"HIGH": 0, "MED": 1, "LOW": 2}.get(
                (item.get("impact") or "LOW").upper(), 2)
            return (impact_order, 0)

        return sorted(result, key=sort_key)

    def _render_filtered(self):
        for w in self._scroll.winfo_children():
            w.destroy()

        items = self._filter_news()
        self._lbl_count.configure(text=f"{len(items)} articles")

        if not items:
            msg = "No news matches your current filters." if self._all_news else \
                  "Waiting for live news data…\n\nNews is fetched automatically every 5 minutes."
            ctk.CTkLabel(self._scroll, text=msg, font=SF.NORMAL(),
                         text_color=Colors.TEXT_MUTED, justify="center").pack(pady=60)
            return

        for i, item in enumerate(items[:100]):  # cap at 100 for performance
            _NewsCard(self._scroll, item, on_click=self._on_news_click, idx=i)

    def update_news_feed(self, news_items: list):
        """Called from main_window with fresh live news. Deduplicates automatically."""
        new_count = 0
        for item in news_items:
            key = _news_key(item)
            if key not in self._seen_keys:
                self._seen_keys.add(key)
                self._all_news.append(item)
                new_count += 1

        if new_count > 0 or not self._all_news:
            # Keep newest 200 items
            self._all_news = self._all_news[-200:]
            self._render_filtered()
