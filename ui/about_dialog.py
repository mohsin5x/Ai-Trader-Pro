"""
ui/about_dialog.py
====================
About dialog for AI Trader Pro.
Shows the logo_about.png, version, tagline, founder credit and legal text.
"""
from __future__ import annotations
import os
import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts
from ui.modal_overlay import BaseDialog

_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "logo_about.png",
)

APP_VERSION  = "2.0"
APP_TAGLINE  = "Smarter Trading. Better Decisions."
APP_FOUNDER  = "Mohsin Abbas"
APP_LEGAL    = (
    "AI Trader Pro is a professional trading analysis platform.\n"
    "All signals are AI-generated for educational purposes only.\n"
    "Past performance does not guarantee future results.\n"
    "Always perform your own due diligence before trading."
)


class AboutDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, title="About AI Trader Pro",
                         size=(480, 420), resizable=(False, False))
        self.configure(fg_color=Colors.APP_BG)

        # ── Logo image ─────────────────────────────────────────────────
        try:
            from PIL import Image
            pil_img = Image.open(_LOGO_PATH)
            ctk_img = ctk.CTkImage(pil_img, size=(360, 90))
            ctk.CTkLabel(self, image=ctk_img, text="",
                         fg_color="transparent").pack(pady=(22, 2))
        except Exception:
            hdr = ctk.CTkFrame(self, fg_color="transparent")
            hdr.pack(pady=(22, 2))
            ctk.CTkLabel(hdr, text="AI Trader",
                         font=SF.TITLE(),
                         text_color=Colors.TEXT).pack(side="left")
            ctk.CTkLabel(hdr, text=" Pro",
                         font=SF.TITLE(),
                         text_color=Colors.PRIMARY).pack(side="left")

        ctk.CTkLabel(self, text=f"Version {APP_VERSION}  ·  Professional Edition",
                     font=SF.MONO_SM(), text_color=Colors.TEXT_MUTED).pack()

        ctk.CTkLabel(self, text=APP_TAGLINE,
                     font=SF.NORMAL(),
                     text_color=Colors.GOLD).pack(pady=(2, 10))

        # ── Divider ────────────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=Colors.BORDER, height=1).pack(fill="x", padx=28)

        # ── Founder credit ─────────────────────────────────────────────
        founder_frame = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, corner_radius=s(8))
        founder_frame.pack(fill="x", padx=28, pady=(12, 4))

        ctk.CTkLabel(
            founder_frame,
            text="Owner & Founder",
            font=SF.PILL(),
            text_color=Colors.TEXT_MUTED,
        ).pack(pady=(10, 0))
        ctk.CTkLabel(
            founder_frame,
            text=APP_FOUNDER,
            font=SF.SUBHEADER(),
            text_color=Colors.GOLD,
        ).pack(pady=(0, 10))

        # ── Divider ────────────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=Colors.BORDER, height=1).pack(fill="x", padx=28, pady=(4, 0))

        ctk.CTkLabel(self, text=APP_LEGAL,
                     font=SF.PILL(), text_color=Colors.TEXT_MUTED,
                     justify="center", wraplength=s(420)).pack(pady=10)

        ctk.CTkLabel(
            self,
            text=f"© 2025 {APP_FOUNDER}  ·  AI Trader Pro v{APP_VERSION}  ·  All rights reserved.",
            font=SF.TINY(),
            text_color=Colors.TEXT_MUTED,
        ).pack(pady=(0, 6))

        ctk.CTkButton(
            self, text="Close", width=s(100), height=S.NAV_BTN_H(), corner_radius=s(6),
            fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
            text_color=Colors.ON_BUY, font=SF.NAV_BOLD(),
            command=self.destroy,
        ).pack(pady=(0, 18))
