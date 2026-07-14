"""
ui/settings_panel.py
======================
SettingsPanel -- View layer only. Talks exclusively to the existing
backend surface (services/provider_settings.save_settings /
services/provider_settings.load_provider) -- does not touch
DataFeedFactory, provider_settings.py, or config.json's format.

Framework: customtkinter, matching the rest of this app's UI
(ui/theme.py) so it drops straight into your existing layout.
"""

import os
import sys

import customtkinter as ctk

from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing, save_appearance_mode
from services.provider_settings import save_settings, load_provider, get_saved_api_key
from ui.modal_overlay import BaseDialog, dialog_center


# ----------------------------------------------------------------------
# Map translation contracts for backend provider handling
# ----------------------------------------------------------------------
_LABEL_TO_VALUE = {"TradingView": "Default", "MT5": "MT5", "TwelveData": "TwelveData"}
_VALUE_TO_LABEL = {v: k for k, v in _LABEL_TO_VALUE.items()}

_PROVIDER_CLASS_TO_LABEL = {
    "UniversalFreeProvider": "TradingView",
    "MT5Provider": "MT5",
    "TwelveDataProvider": "TwelveData",
}


class MT5InstructionsDialog(BaseDialog):
    """Shown right before saving if the user picks MT5, since MT5 only
    ever connects when a real, logged-in MetaTrader 5 desktop terminal
    is already running on this machine."""

    def __init__(self, parent, on_continue):
        # use_grab=True preserves the modal lock that blocks the main window
        super().__init__(parent, title="Before you connect MT5",
                         size=(480, 440), resizable=(False, True), use_grab=True)
        self.minsize(420, 380)       # prevents resizing below button visibility threshold
        self.configure(fg_color=Colors.APP_BG)

        self._on_continue = on_continue

        # Red X and Escape both cancel (override BaseDialog default)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda e: self._on_cancel())

        self._build_ui_layout()

    def _build_ui_layout(self):
        container = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, border_width=1,
                                  border_color=Colors.BORDER, corner_radius=s(12))
        container.pack(fill="both", expand=True, padx=14, pady=14)
        container.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            container, text="⚠  MetaTrader 5 Connection", font=SF.HEADER(), text_color=Colors.TEXT
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        steps = (
            "MT5 data only works while a real MT5 desktop terminal is "
            "running and logged in to your broker account on this same "
            "computer. This is why the connection sometimes shows "
            "\"Data unavailable\" -- it's not this app failing, it's the "
            "terminal not being ready yet.\n\n"
            "Before continuing, please make sure:\n"
            "1. The MetaTrader 5 terminal is open\n"
            "2. You're logged in to a broker account (not just installed)\n"
            "3. The dashboard shows a green connection in the bottom-right\n"
            "4. Algo/API trading is allowed in MT5 → Tools → Options → Expert Advisors\n\n"
            "If MT5 closes or you log out later, this app will show "
            "\"Data unavailable\" again until you reopen and log back in."
        )
        ctk.CTkLabel(
            container, text=steps, font=SF.NORMAL(), text_color=Colors.TEXT_SECONDARY,
            justify="left", wraplength=400, anchor="nw"
        ).grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))

        # Buttons always pinned at the bottom row
        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 16))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_row, text="Cancel", fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT, font=SF.NORMAL(), command=self._on_cancel
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            btn_row, text="MT5 Is Open — Continue", fg_color=Colors.BUY, hover_color=Colors.BUY_HOVER,
            text_color=Colors.ON_BUY, font=SF.NORMAL(), command=self._confirm
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def _confirm(self):
        self.grab_release()
        self.destroy()
        self._on_continue()


class RestartPromptDialog(BaseDialog):
    """Appearance changes require an immediate restart."""

    def __init__(self, parent, mode_label: str):
        super().__init__(parent, title="Restart to apply theme",
                         size=(380, 190), resizable=(False, False))
        self.configure(fg_color=Colors.APP_BG)
        self.mode_label = mode_label

        # Intercept the red 'X' window button to close safely without crashing
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._build_ui_layout()

    def _build_ui_layout(self):
        container = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, border_width=1,
                                  border_color=Colors.BORDER, corner_radius=s(12))
        container.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            container, text=f"{self.mode_label} theme saved", font=SF.SUBHEADER(), text_color=Colors.TEXT
        ).pack(anchor="w", padx=16, pady=(16, 6))
        
        ctk.CTkLabel(
            container,
            text="The new colors are applied on next launch. Restart now to see them?",
            font=SF.NORMAL(), text_color=Colors.TEXT_SECONDARY, justify="left", wraplength=s(330)
        ).pack(anchor="w", padx=16, pady=(0, 14))

        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        # THE FIX: Added explicit font parameter to bypass default root lookup failure
        ctk.CTkButton(
            btn_row, text="Later", fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            text_color=Colors.TEXT, font=SF.NORMAL(), command=self._cancel
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        # THE FIX: Added explicit font parameter to bypass default root lookup failure
        ctk.CTkButton(
            btn_row, text="Restart Now", fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
            text_color=Colors.ON_BUY, font=SF.NORMAL(), command=self._restart
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _cancel(self):
        self.grab_release()
        self.destroy()

    def _restart(self):
        self.grab_release()
        os.execv(sys.executable, [sys.executable] + sys.argv)


class SettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, on_saved=None, **kwargs):
        super().__init__(
            parent, fg_color=Colors.CARD_BG, border_width=1,
            border_color=Colors.BORDER, corner_radius=s(10), **kwargs
        )
        self.on_saved = on_saved
        self.grid_columnconfigure(1, weight=1)
        self._saved_api_key = None

        self._build_ui()
        self._load_current_settings()

    def _build_ui(self):
        ctk.CTkLabel(
            self, text="DATA SOURCE SETTINGS", font=SF.SMALL(), text_color=Colors.LABEL
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=Spacing.MD(), pady=(Spacing.MD(), 6))

        # --- Provider dropdown ---
        ctk.CTkLabel(self, text="Provider", font=SF.NORMAL(), text_color=Colors.TEXT).grid(
            row=1, column=0, sticky="w", padx=Spacing.MD(), pady=6
        )
        self.provider_menu = ctk.CTkOptionMenu(
            self, values=list(_LABEL_TO_VALUE.keys()), command=self._on_provider_changed,
            fg_color=Colors.WELL_BG, button_color=Colors.CARD_BG_ALT,
            button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
        )
        self.provider_menu.grid(row=1, column=1, sticky="ew", padx=Spacing.MD(), pady=6)

        # --- API key entry ---
        self.api_key_label = ctk.CTkLabel(self, text="Twelve Data API Key", font=SF.NORMAL(), text_color=Colors.TEXT)
        self.api_key_entry = ctk.CTkEntry(
            self, placeholder_text="Paste your Twelve Data API key...",
            fg_color=Colors.WELL_BG, border_color=Colors.BORDER, text_color=Colors.TEXT, show="•",
        )
        self._api_key_row = 2  

        self.api_key_hint = ctk.CTkLabel(
            self, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED, anchor="w"
        )
        self._api_key_hint_row = 2  

        # --- Theme toggle ---
        ctk.CTkLabel(self, text="Appearance", font=SF.NORMAL(), text_color=Colors.TEXT).grid(
            row=4, column=0, sticky="w", padx=Spacing.MD(), pady=6
        )
        self.theme_button = ctk.CTkButton(
            self, text=self._theme_button_text(), command=self._toggle_theme,
            fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER, text_color=Colors.TEXT,
            font=SF.NORMAL()
        )
        self.theme_button.grid(row=4, column=1, sticky="ew", padx=Spacing.MD(), pady=6)

        # --- Save button ---
        self.save_button = ctk.CTkButton(
            self, text="Save Settings", command=self._on_save_clicked, height=S.ROW_H(),
            fg_color=Colors.BUY, hover_color=Colors.BUY_HOVER, text_color=Colors.ON_BUY,
            font=SF.SUBHEADER(),
        )
        self.save_button.grid(row=5, column=0, columnspan=2, sticky="ew", padx=Spacing.MD(), pady=(12, 4))

        # --- Status line ---
        self.status_label = ctk.CTkLabel(self, text="", font=SF.TINY(), text_color=Colors.TEXT_MUTED, anchor="w")
        self.status_label.grid(row=6, column=0, columnspan=2, sticky="ew", padx=Spacing.MD(), pady=(0, Spacing.MD()))

        # ══════════════════════════════════════════════════════════════
        # BINANCE API SECTION
        # ══════════════════════════════════════════════════════════════
        ctk.CTkFrame(self, fg_color=Colors.BORDER, height=1).grid(
            row=7, column=0, columnspan=2, sticky="ew", padx=Spacing.MD(), pady=(0, 4))
        ctk.CTkLabel(self, text="BINANCE MARKET DATA", font=SF.SMALL(),
                     text_color=Colors.LABEL).grid(
            row=8, column=0, columnspan=2, sticky="w", padx=Spacing.MD(), pady=(Spacing.SM(), 4))

        binance_frame = ctk.CTkFrame(self, fg_color=Colors.WELL_BG,
                                      corner_radius=s(8), border_width=1,
                                      border_color=Colors.BORDER)
        binance_frame.grid(row=9, column=0, columnspan=2, sticky="ew",
                           padx=Spacing.MD(), pady=(0, Spacing.SM()))
        binance_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(binance_frame, text="₿ Public API (no key needed)",
                     font=SF.NORMAL(), text_color=Colors.TEXT).grid(
            row=0, column=0, sticky="w", padx=Spacing.MD(), pady=(Spacing.SM(), 2))
        ctk.CTkLabel(binance_frame, text="● Always ON",
                     font=SF.TINY(),
                     text_color=Colors.BUY).grid(
            row=0, column=1, sticky="e", padx=Spacing.MD(), pady=(Spacing.SM(), 2))

        ctk.CTkLabel(binance_frame,
                     text="Binance public REST API provides real-time crypto spot prices\n"
                          "for the Market Scanner ticker bar and Watchlist crypto tab.\n"
                          "No account, API key, or login required — purely read-only.",
                     font=SF.TINY(), text_color=Colors.TEXT_MUTED,
                     justify="left", anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=Spacing.MD(), pady=(0, 4))

        # Binance test button
        self._lbl_binance_test = ctk.CTkLabel(binance_frame, text="", font=SF.TINY(),
                                               text_color=Colors.TEXT_MUTED)
        self._lbl_binance_test.grid(row=2, column=1, sticky="e", padx=Spacing.MD(), pady=(0, Spacing.SM()))
        ctk.CTkButton(binance_frame, text="Test Connection", width=s(130), height=s(28),
                      corner_radius=s(6), fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
                      text_color=Colors.TEXT, font=SF.TINY(),
                      command=self._test_binance).grid(
            row=2, column=0, sticky="w", padx=Spacing.MD(), pady=(0, Spacing.SM()))

        # ══════════════════════════════════════════════════════════════
        # NOTIFICATIONS SECTION
        # ══════════════════════════════════════════════════════════════
        ctk.CTkFrame(self, fg_color=Colors.BORDER, height=1).grid(
            row=10, column=0, columnspan=2, sticky="ew", padx=Spacing.MD(), pady=(0, 4))
        ctk.CTkLabel(self, text="NOTIFICATION SETTINGS", font=SF.SMALL(),
                     text_color=Colors.LABEL).grid(
            row=11, column=0, columnspan=2, sticky="w", padx=Spacing.MD(), pady=(Spacing.SM(), 4))

        notif_frame = ctk.CTkFrame(self, fg_color=Colors.WELL_BG,
                                    corner_radius=s(8), border_width=1,
                                    border_color=Colors.BORDER)
        notif_frame.grid(row=12, column=0, columnspan=2, sticky="ew",
                         padx=Spacing.MD(), pady=(0, Spacing.SM()))
        notif_frame.grid_columnconfigure(1, weight=1)

        # Load saved notification prefs
        import os as _os, json as _json
        _cfg_path = _os.path.join(_os.path.dirname(__file__), "..", "config.json")
        _notif_cfg = {}
        try:
            with open(_cfg_path) as _f: _notif_cfg = _json.load(_f)
        except Exception: pass

        self._notif_vars: dict[str, ctk.BooleanVar] = {}

        notif_items = [
            ("notif_ai_signal",    "🔔  AI Signal popup",       "Show a popup when a new high-confidence AI signal fires"),
            ("notif_news",         "📰  Market News popup",      "Show news headlines as they arrive"),
            ("notif_sound",        "🔊  Enable sound alerts",    "Play a tone with each signal popup (requires system audio)"),
            ("notif_paper_trade",  "📝  Paper trade updates",    "Notify when a paper trade opens / closes"),
            ("notif_scanner_high", "🎯  High-confidence alerts", "Extra alert when scanner finds ≥90% confidence signal"),
        ]

        for i, (key, label, desc) in enumerate(notif_items):
            default = _notif_cfg.get(key, True if "signal" in key or "sound" in key else False)
            var = ctk.BooleanVar(value=default)
            self._notif_vars[key] = var
            row_f = ctk.CTkFrame(notif_frame, fg_color="transparent")
            row_f.grid(row=i, column=0, columnspan=2, sticky="ew", padx=Spacing.MD(),
                       pady=(Spacing.SM() if i == 0 else 2, 2 if i < len(notif_items)-1 else Spacing.SM()))
            ctk.CTkCheckBox(
                row_f, text=label, variable=var,
                font=SF.NORMAL(),
                text_color=Colors.TEXT,
                fg_color=Colors.PRIMARY, hover_color=Colors.PRIMARY_HOVER,
                checkmark_color=Colors.ON_BUY,
                command=self._save_notif_prefs,
            ).pack(side="left")
            ctk.CTkLabel(row_f, text=desc, font=SF.TINY(),
                         text_color=Colors.TEXT_MUTED).pack(side="left", padx=(12, 0))

        # ── About / Branding section ───────────────────────────────────────
        ctk.CTkLabel(self, text="ABOUT", font=SF.SMALL(), text_color=Colors.LABEL).grid(
            row=14, column=0, columnspan=2, sticky="w", padx=Spacing.MD(), pady=(Spacing.MD(), 6)
        )
        about_frame = ctk.CTkFrame(self, fg_color="transparent")
        about_frame.grid(row=15, column=0, columnspan=2, sticky="ew", padx=Spacing.MD(), pady=(0, Spacing.MD()))
        about_frame.grid_columnconfigure(1, weight=1)

        _rows = [
            ("Application",  "AI Trader Pro"),
            ("Version",      "2.0  ·  Professional Edition"),
            ("Owner",        "Mohsin Abbas"),
            ("Founder",      "Mohsin Abbas"),
            ("Copyright",    "© 2025 Mohsin Abbas. All rights reserved."),
            ("License",      "Professional Commercial License"),
        ]
        for i, (lbl, val) in enumerate(_rows):
            ctk.CTkLabel(about_frame, text=lbl, font=SF.TINY(), text_color=Colors.LABEL,
                         anchor="w").grid(row=i, column=0, sticky="w", pady=2, padx=(0, 12))
            color = Colors.GOLD if lbl in ("Owner", "Founder") else Colors.TEXT_SECONDARY
            ctk.CTkLabel(about_frame, text=val, font=SF.TINY(), text_color=color,
                         anchor="w").grid(row=i, column=1, sticky="w", pady=2)

    # ── Binance test ───────────────────────────────────────────────────────
    def _test_binance(self):
        """Test Binance public API connection in background thread."""
        self._lbl_binance_test.configure(text="Testing…", text_color=Colors.TEXT_MUTED)
        import threading
        threading.Thread(target=self._bg_binance_test, daemon=True).start()

    def _bg_binance_test(self):
        import json
        try:
            from urllib.request import urlopen, Request
            _HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req = Request("https://api.binance.com/api/v3/ping", headers=_HEADERS)
            with urlopen(req, timeout=8) as r:
                r.read()
            req2 = Request("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", headers=_HEADERS)
            with urlopen(req2, timeout=8) as r:
                data = json.loads(r.read())
            btc_px = float(data.get("price", 0))
            try:
                if self.winfo_exists():
                    self.after(0, lambda: self._lbl_binance_test.configure(
                        text=f"✅ Connected  BTC=${btc_px:,.0f}", text_color=Colors.BUY))
            except Exception:
                pass
        except Exception as e:
            err = str(e)[:50]
            try:
                if self.winfo_exists():
                    self.after(0, lambda: self._lbl_binance_test.configure(
                        text=f"❌ {err}", text_color=Colors.SELL))
            except Exception:
                pass

    # ── Notification prefs ─────────────────────────────────────────────────
    def _save_notif_prefs(self):
        """Save notification toggles to config.json immediately."""
        import os, json
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        try:
            data = {}
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    data = json.load(f)
            for key, var in self._notif_vars.items():
                data[key] = var.get()
            with open(cfg_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def load_notif_prefs() -> dict:
        """Read notification prefs from config.json. Safe to call from anywhere."""
        import os, json
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        defaults = {
            "notif_ai_signal":    True,
            "notif_news":         False,
            "notif_sound":        True,
            "notif_paper_trade":  False,
            "notif_scanner_high": True,
        }
        try:
            with open(cfg_path) as f:
                data = json.load(f)
            defaults.update({k: v for k, v in data.items() if k.startswith("notif_")})
        except Exception:
            pass
        return defaults

    def _set_api_key_visible(self, visible: bool):
        if visible:
            self.api_key_label.grid(row=2, column=0, sticky="w", padx=Spacing.MD(), pady=6)
            self.api_key_entry.grid(row=2, column=1, sticky="ew", padx=Spacing.MD(), pady=6)
            self.api_key_hint.grid(row=3, column=1, sticky="w", padx=Spacing.MD(), pady=(0, 4))
        else:
            self.api_key_label.grid_remove()
            self.api_key_entry.grid_remove()
            self.api_key_hint.grid_remove()

    def _refresh_api_key_hint(self):
        if self._saved_api_key:
            masked = f"••••{self._saved_api_key[-4:]}" if len(self._saved_api_key) > 4 else "••••"
            self.api_key_hint.configure(text=f"✓ Key saved ({masked}) -- leave blank to keep using it.")
        else:
            self.api_key_hint.configure(text="")

    def _on_provider_changed(self, selected_label: str):
        self._set_api_key_visible(selected_label == "TwelveData")
        self._refresh_api_key_hint()
        self.status_label.configure(text="")

    def _theme_button_text(self) -> str:
        mode = ctk.get_appearance_mode()
        return "🌙 Dark Mode" if mode == "Dark" else "☀️ Light Mode"

    def _toggle_theme(self):
        current_mode = ctk.get_appearance_mode()
        new_mode = "Light" if current_mode == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        save_appearance_mode(new_mode)
        self.theme_button.configure(text=self._theme_button_text())
        RestartPromptDialog(self.winfo_toplevel(), mode_label=new_mode)

    def _load_current_settings(self):
        try:
            provider = load_provider()
        except Exception:
            provider = None

        label = _PROVIDER_CLASS_TO_LABEL.get(type(provider).__name__ if provider else None, "TradingView")
        self.provider_menu.set(label)
        self._set_api_key_visible(label == "TwelveData")

        try:
            saved = get_saved_api_key()
        except Exception:
            saved = None
        self._saved_api_key = saved

        if label == "TwelveData" and saved:
            self.api_key_entry.insert(0, saved)
        self._refresh_api_key_hint()

    def _on_save_clicked(self):
        label = self.provider_menu.get()
        provider_type = _LABEL_TO_VALUE.get(label, "Default")

        if provider_type == "MT5":
            MT5InstructionsDialog(self.winfo_toplevel(), on_continue=lambda: self._do_save(provider_type, label))
            return

        self._do_save(provider_type, label)

    def _do_save(self, provider_type: str, label: str):
        api_key = None
        if provider_type == "TwelveData":
            typed = self.api_key_entry.get().strip()
            if typed:
                api_key = typed
            elif self._saved_api_key:
                api_key = None
            else:
                self.status_label.configure(text="⚠ Enter a Twelve Data API key first.", text_color=Colors.SELL)
                return

        try:
            save_settings(provider_type, api_key=api_key)
        except ValueError as e:
            self.status_label.configure(text=f"⚠ {e}", text_color=Colors.SELL)
            return

        provider = load_provider()
        actual_label = _PROVIDER_CLASS_TO_LABEL.get(type(provider).__name__, label)

        try:
            self._saved_api_key = get_saved_api_key()
        except Exception:
            pass
        self._refresh_api_key_hint()

        if actual_label != label:
            self.provider_menu.set(actual_label)
            self._set_api_key_visible(actual_label == "TwelveData")
            self.status_label.configure(
                text=f"⚠ Saved, but fell back to {actual_label} ({provider.display_name}).",
                text_color=Colors.NEUTRAL,
            )
        elif provider_type == "MT5":
            connected = False
            try:
                connected = bool(provider.is_configured())
            except Exception:
                connected = False
            if connected:
                self.status_label.configure(text="✓ Saved -- MT5 terminal connected.", text_color=Colors.BUY)
            else:
                self.status_label.configure(
                    text="⚠ Saved, but MT5 terminal isn't reachable yet -- open & log in, then reopen this app.",
                    text_color=Colors.NEUTRAL,
                )
        else:
            self._show_save_toast(f"✓ Saved — now using {provider.display_name}.", Colors.BUY)

        if self.on_saved:
            self.on_saved(provider)

    def _show_save_toast(self, text: str, color: str):
        """Show a prominent save-confirmation toast that auto-hides after 3 s."""
        self.status_label.configure(text=text, text_color=color)
        # Also show a floating toast overlay on the toplevel
        try:
            root = self.winfo_toplevel()
            toast = ctk.CTkLabel(
                root, text=f"  {text}  ",
                font=SF.STATUS_BOLD(),
                text_color=Colors.ON_BUY,
                fg_color=color,
                corner_radius=8,
            )
            toast.place(relx=0.5, rely=0.96, anchor="s")
            root.after(3000, lambda: toast.place_forget() if toast.winfo_exists() else None)
        except Exception:
            pass