"""
ui/news_panel.py
==================
Live Market News — paginated, high-impact prioritised.

Changes:
  - Pages of 6 items (prev / next nav buttons + page counter)
  - HIGH impact news sorted to top and shown with red accent banner
  - HIGH impact badge glows red; MED orange; LOW muted — instant visual triage
  - Compact layout so the sidebar doesn't scroll forever
  - Detail modal unchanged (real article link, source, summary)
"""

import webbrowser
import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from ui.modal_overlay import BaseDialog

NEWS_PER_PAGE = 6   # items shown per page in the sidebar panel


# ─── Impact helpers ──────────────────────────────────────────────────────────
def _impact_colors(impact: str) -> tuple[str, str]:
    """(badge_bg, text_color) for a given impact level."""
    impact = (impact or "").upper()
    if impact == "HIGH":
        return Colors.STATUS_HIGH, Colors.TEXT
    if impact == "MED":
        return Colors.STATUS_MED, Colors.TEXT
    return Colors.STATUS_LOW, Colors.TEXT_MUTED


# ─── Detail modal ─────────────────────────────────────────────────────────────
class NewsDetailModal(BaseDialog):
    def __init__(self, parent, news_item: dict):
        super().__init__(parent,
                         title=f"News — {news_item.get('source', 'Market News')}",
                         size=(560, 460), resizable=(False, False))
        self.configure(fg_color=Colors.APP_BG)

        container = ctk.CTkFrame(
            self, fg_color=Colors.SIDEBAR_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(12),
        )
        container.pack(fill="both", expand=True, padx=15, pady=15)

        impact = (news_item.get("impact") or "LOW").upper()
        badge_bg, _ = _impact_colors(impact)

        # Header
        header_row = ctk.CTkFrame(container, fg_color="transparent")
        header_row.pack(fill="x", padx=15, pady=(15, 10))

        source    = news_item.get("source") or "Unknown source"
        published = news_item.get("time")   or "--"
        ctk.CTkLabel(
            header_row, text=f"{source}  ·  {published}",
            font=SF.MONO(), text_color=Colors.LABEL,
        ).pack(side="left")
        ctk.CTkLabel(
            header_row, text=f" {impact} IMPACT ",
            font=SF.PILL_LG(), text_color=Colors.TEXT,
            fg_color=badge_bg, corner_radius=s(5),
        ).pack(side="right")

        # Headline
        ctk.CTkLabel(
            container, text=news_item.get("title", ""),
            font=SF.SUBHEADER(), text_color=Colors.TEXT,
            justify="left", wraplength=s(500),
        ).pack(anchor="w", padx=15, pady=(0, 15))

        # Summary
        description = (news_item.get("description") or "").strip()
        if description:
            ctk.CTkLabel(
                container, text="SUMMARY",
                font=SF.PILL_LG(), text_color=Colors.LABEL,
            ).pack(anchor="w", padx=15, pady=(0, 4))
            ctk.CTkLabel(
                container, text=description,
                font=SF.NORMAL(), text_color=Colors.TEXT_SECONDARY,
                justify="left", wraplength=s(500),
            ).pack(anchor="w", padx=15, pady=(0, 15))

        # Open article button
        url = news_item.get("url") or ""
        if url:
            ctk.CTkButton(
                container, text="Open Full Article ↗", height=S.ROW_H(), corner_radius=s(8),
                fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
                text_color=Colors.ON_BUY, font=SF.SUBHEADER(),
                command=lambda: webbrowser.open(url),
            ).pack(fill="x", padx=15, pady=(6, 15), side="bottom")


# ─── Sidebar news panel ───────────────────────────────────────────────────────
class LiveNewsPanel(ctk.CTkFrame):
    """
    Compact paginated news list for the sidebar.
    HIGH-impact items are pulled to the top and shown with a red left-border.
    Page navigation sits below the item list — no endless scroll.
    """

    def __init__(self, parent, on_news_click=None):
        super().__init__(
            parent, fg_color=Colors.CARD_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=s(10),
        )
        self.on_news_click = on_news_click
        self._all_news:   list = []
        self._page:       int  = 0   # 0-indexed current page
        self._has_data:   bool = False

        # ── Header + HIGH badge ──────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 4))

        ctk.CTkLabel(
            hdr, text="LIVE MARKET NEWS",
            font=SF.SMALL(), text_color=Colors.LABEL,
        ).pack(side="left")

        self._lbl_high_count = ctk.CTkLabel(
            hdr, text="",
            font=SF.STATUS_BOLD(), text_color=Colors.TEXT,
            fg_color=Colors.STATUS_HIGH, corner_radius=s(4), padx=6, pady=1,
        )
        self._lbl_high_count.pack(side="right")

        # ── Item list area ───────────────────────────────────────────────
        self._list_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._list_frame.pack(fill="x", padx=Spacing.SM())

        self._render_empty("Loading live news…")

        # ── Pagination bar ───────────────────────────────────────────────
        self._nav_bar = ctk.CTkFrame(self, fg_color="transparent")
        self._nav_bar.pack(fill="x", padx=Spacing.SM(), pady=(2, Spacing.SM()))

        _btn_kw = dict(
            width=s(28), height=s(22), corner_radius=s(5),
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT, font=SF.PILL_LG(),
        )
        self._btn_prev = ctk.CTkButton(
            self._nav_bar, text="‹", command=self._prev_page, **_btn_kw)
        self._btn_prev.pack(side="left", padx=(2, 2))

        self._lbl_page = ctk.CTkLabel(
            self._nav_bar, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED)
        self._lbl_page.pack(side="left", padx=4)

        self._btn_next = ctk.CTkButton(
            self._nav_bar, text="›", command=self._next_page, **_btn_kw)
        self._btn_next.pack(side="left", padx=(2, 0))

        # "High impact only" toggle
        self._high_only = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self._nav_bar, text="HIGH only", variable=self._high_only,
            font=SF.TINY(), text_color=Colors.TEXT_MUTED,
            fg_color=Colors.STATUS_HIGH, hover_color=Colors.HOVER,
            border_color=Colors.BORDER, width=14, height=14,
            command=self._on_filter_toggle,
        ).pack(side="right", padx=(0, 4))

    # ── Helpers ───────────────────────────────────────────────────────────


    def _render_empty(self, msg: str):
        for w in self._list_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._list_frame, text=msg,
            font=SF.SMALL(),
            text_color=Colors.TEXT_MUTED, wraplength=s(260), justify="left",
        ).pack(pady=14, padx=6)

    def _visible_news(self) -> list:
        """Applies HIGH-only filter and returns current page slice."""
        src = self._all_news
        if self._high_only.get():
            src = [n for n in src if (n.get("impact") or "").upper() == "HIGH"]
        return src

    def _total_pages(self) -> int:
        return max(1, -(-len(self._visible_news()) // NEWS_PER_PAGE))   # ceil div

    def _prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def _next_page(self):
        if self._page < self._total_pages() - 1:
            self._page += 1
            self._render_page()

    def _on_filter_toggle(self):
        self._page = 0
        self._render_page()

    # ── Main render ───────────────────────────────────────────────────────
    def update_news_feed(self, news_list: list):
        if not news_list:
            if not self._has_data:
                from config import settings
                if not settings.FINNHUB_API_KEY:
                    self._render_empty(
                        "Live news needs a free Finnhub key.\n"
                        "Add FINNHUB_API_KEY to your .env and restart."
                    )
                else:
                    self._render_empty("No live news available right now.")
            return

        # Sort: HIGH first, then MED, then LOW — within each group keep time order
        _rank = {"HIGH": 0, "MED": 1, "LOW": 2}
        self._all_news = sorted(
            news_list,
            key=lambda n: _rank.get((n.get("impact") or "LOW").upper(), 2),
        )
        self._has_data = True

        # Update HIGH count badge
        high_n = sum(1 for n in self._all_news if (n.get("impact") or "").upper() == "HIGH")
        if high_n:
            self._lbl_high_count.configure(text=f" 🔥 {high_n} HIGH ")
        else:
            self._lbl_high_count.configure(text="")

        # Reset to page 0 only when feed content actually changes
        self._page = 0
        self._render_page()

    def _render_page(self):
        for w in self._list_frame.winfo_children():
            w.destroy()

        visible = self._visible_news()
        total_pages = self._total_pages()

        if not visible:
            ctk.CTkLabel(
                self._list_frame, text="No HIGH-impact news right now.",
                font=SF.SMALL(), text_color=Colors.TEXT_MUTED,
            ).pack(pady=12)
            self._lbl_page.configure(text="")
            self._btn_prev.configure(state="disabled")
            self._btn_next.configure(state="disabled")
            return

        start = self._page * NEWS_PER_PAGE
        page_items = visible[start: start + NEWS_PER_PAGE]

        for item in page_items:
            self._render_item(item)

        # Update pagination controls
        self._lbl_page.configure(
            text=f"  {self._page + 1} / {total_pages}  ")
        self._btn_prev.configure(state="normal" if self._page > 0 else "disabled")
        self._btn_next.configure(
            state="normal" if self._page < total_pages - 1 else "disabled")

    def _render_item(self, item: dict):
        impact   = (item.get("impact") or "LOW").upper()
        badge_bg, text_color = _impact_colors(impact)
        is_high  = impact == "HIGH"

        # Outer frame — red left-border accent for HIGH
        border_color = Colors.STATUS_HIGH if is_high else Colors.BORDER
        item_frame = ctk.CTkFrame(
            self._list_frame,
            fg_color=Colors.WELL_BG if not is_high else Colors.CARD_BG,
            border_width=1, border_color=border_color,
            corner_radius=s(6), cursor="hand2",
        )
        item_frame.pack(fill="x", pady=2, padx=1)

        # For HIGH items — a thin coloured top stripe
        if is_high:
            stripe = ctk.CTkFrame(item_frame, fg_color=Colors.STATUS_HIGH, height=3, corner_radius=0)
            stripe.pack(fill="x", padx=0, pady=0)

        meta_row = ctk.CTkFrame(item_frame, fg_color="transparent")
        meta_row.pack(fill="x", padx=8, pady=(5, 1))

        source = item.get("source") or "Market News"
        ctk.CTkLabel(
            meta_row, text=source,
            font=SF.STATUS_BOLD(), text_color=Colors.PRIMARY,
        ).pack(side="left")

        ctk.CTkLabel(
            meta_row, text=f" {impact} ",
            font=SF.STATUS_BOLD(), text_color=Colors.TEXT,
            fg_color=badge_bg, corner_radius=3,
        ).pack(side="right")

        title_text = item.get("title", "")
        lbl_title = ctk.CTkLabel(
            item_frame, text=title_text,
            font=SF.SMALL(),
            text_color=text_color,
            justify="left", wraplength=s(248), cursor="hand2", anchor="w",
        )
        lbl_title.pack(anchor="w", padx=8, pady=(1, 1), fill="x")

        lbl_time = ctk.CTkLabel(
            item_frame, text=item.get("time", "--"),
            font=SF.MONO_TINY(), text_color=Colors.TEXT_MUTED,
        )
        lbl_time.pack(anchor="w", padx=8, pady=(0, 5))

        # Hover + click
        item_frame.bind("<Enter>", lambda e, f=item_frame, bc=border_color:
                        f.configure(border_color=Colors.PRIMARY))
        item_frame.bind("<Leave>", lambda e, f=item_frame, bc=border_color:
                        f.configure(border_color=bc))

        if self.on_news_click:
            for w in (item_frame, lbl_title, lbl_time):
                w.bind("<Button-1>", lambda event, i=item: self.on_news_click(i))
