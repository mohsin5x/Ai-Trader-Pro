import time

import customtkinter as ctk
from ui.scaling import S, SF, s, sf, pad, wrap
from ui.theme import Colors, Fonts, Spacing
from ui.modal_overlay import BaseDialog


class AIDeepAnalysisModal(BaseDialog):
    def __init__(self, parent, asset, strategy, signal, confidence, reasoning, rr=0.0):
        super().__init__(parent,
                         title=f"AI Quantitative Intelligence Report — {asset}",
                         size=(680, 640), resizable=(False, False))
        self.configure(fg_color=Colors.APP_BG)
        # Premium outer cell border
        container = ctk.CTkFrame(self, fg_color=Colors.SIDEBAR_BG, border_width=1,
                                  border_color=Colors.BORDER, corner_radius=s(12))
        container.pack(fill="both", expand=True, padx=15, pady=15)

        # Header Block
        header_row = ctk.CTkFrame(container, fg_color="transparent")
        header_row.pack(fill="x", padx=15, pady=(15, 5))

        ctk.CTkLabel(header_row, text="AI ENGINE: RULE-BASED SIGNAL MODEL", font=SF.MONO_SM(),
                     text_color=Colors.BUY).pack(side="left")
        ctk.CTkLabel(header_row, text="SIMULATED / PAPER TRADING", font=SF.PILL_LG(), text_color=Colors.TEXT,
                     fg_color=Colors.CARD_BG, corner_radius=s(5), padx=6, pady=2).pack(side="right")

        # Main Title
        ctk.CTkLabel(container, text=f"{strategy} Analysis Report", font=SF.HEADER(), text_color=Colors.TEXT) \
            .pack(anchor="w", padx=15, pady=(5, 12))

        # --- SIGNAL SUMMARY MATRIX ---
        matrix_frame = ctk.CTkFrame(container, fg_color=Colors.CARD_BG, border_width=1,
                                     border_color=Colors.BORDER, corner_radius=s(8))
        matrix_frame.pack(fill="x", padx=15, pady=5)
        for i in range(3):
            matrix_frame.grid_columnconfigure(i, weight=1)

        # Signal Direction Cell
        c1 = ctk.CTkFrame(matrix_frame, fg_color="transparent")
        c1.grid(row=0, column=0, pady=14, sticky="nsew")
        ctk.CTkLabel(c1, text="SIGNAL", font=SF.PILL_LG(), text_color=Colors.LABEL).pack()
        sig_color = Colors.BUY if "BUY" in signal.upper() else (Colors.SELL if "SELL" in signal.upper() else Colors.TEXT)
        ctk.CTkLabel(c1, text=signal if signal else "NEUTRAL", font=SF.PRICE_SM(), text_color=sig_color).pack()

        # Rule Confidence Cell (fixed per-strategy weight, not a backtested stat — labelled honestly)
        c2 = ctk.CTkFrame(matrix_frame, fg_color="transparent")
        c2.grid(row=0, column=1, pady=14, sticky="nsew")
        ctk.CTkLabel(c2, text="RULE CONFIDENCE", font=SF.PILL_LG(), text_color=Colors.LABEL).pack()
        ctk.CTkLabel(c2, text=confidence, font=SF.PRICE_SM(), text_color=Colors.ORANGE).pack()

        # Risk:Reward Cell — real, computed value (replaces the old fabricated "trend accuracy" stat)
        c3 = ctk.CTkFrame(matrix_frame, fg_color="transparent")
        c3.grid(row=0, column=2, pady=14, sticky="nsew")
        ctk.CTkLabel(c3, text="RISK : REWARD", font=SF.PILL_LG(), text_color=Colors.LABEL).pack()
        ctk.CTkLabel(c3, text=f"1 : {rr:.2f}" if rr else "—", font=SF.PRICE_SM(), text_color=Colors.TEXT_SECONDARY).pack()

        # --- TECHNICAL CONTEXT ---
        tech_frame = ctk.CTkFrame(container, fg_color="transparent")
        tech_frame.pack(fill="x", padx=15, pady=10)

        left_col = ctk.CTkFrame(tech_frame, fg_color=Colors.WELL_BG, border_width=1,
                                 border_color=Colors.BORDER, corner_radius=s(6), width=s(260), height=110)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 5))
        left_col.pack_propagate(False)

        ctk.CTkLabel(left_col, text=" HOW THIS STRATEGY WORKS", font=SF.PILL_LG(),
                     text_color=Colors.LABEL, anchor="w").pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(
            left_col,
            text=f"Strategy: {strategy}\nSignal source: technical rules on\nOHLC price data (EMA/RSI/S&R etc.)",
            font=SF.MONO_SM(), text_color=Colors.TEXT_SECONDARY, justify="left", anchor="w"
        ).pack(fill="x", padx=12, pady=2)

        right_col = ctk.CTkFrame(tech_frame, fg_color=Colors.WELL_BG, border_width=1,
                                  border_color=Colors.BORDER, corner_radius=s(6), width=s(260), height=110)
        right_col.pack(side="right", fill="both", expand=True, padx=(5, 0))
        right_col.pack_propagate(False)

        ctk.CTkLabel(right_col, text=" IMPORTANT", font=SF.PILL_LG(),
                     text_color=Colors.LABEL, anchor="w").pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(
            right_col,
            text="This is a simulated paper-trading\nenvironment. No real orders are\nplaced and no financial advice.",
            font=SF.MONO_SM(), text_color=Colors.TEXT_SECONDARY, justify="left", anchor="w"
        ).pack(fill="x", padx=12, pady=2)

        # Narrative Analytical Summary
        ctk.CTkLabel(container, text="STRATEGY REASONING", font=SF.PILL_LG(), text_color=Colors.LABEL) \
            .pack(anchor="w", padx=15, pady=(10, 4))

        reason_txt = reasoning if reasoning else "Waiting for the next candle to evaluate this strategy's rules against current price action."
        lbl_reason = ctk.CTkLabel(container, text=reason_txt, font=SF.NORMAL(), text_color=Colors.TEXT_SECONDARY,
                                   justify="left", wraplength=s(610))
        lbl_reason.pack(anchor="w", fill="x", padx=15, pady=(0, 15))


class AIPanel(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=Colors.CARD_BG, border_width=1, border_color=Colors.BORDER, corner_radius=s(10))

        # Memory storage cache variables for the modal report generator
        self.cached_strategy = "ICT Smart Money"
        self.cached_signal = "STAY OUT"
        self.cached_confidence = "85%"
        self.cached_reasoning = ""
        self.cached_rr = 0.0
        self.active_asset = "EUR/USD"

        # Main Header Layout — title on the left, live signal badge on the right
        # so the current bias is visible at a glance without opening the modal.
        self.header_row = ctk.CTkFrame(self, fg_color="transparent")
        self.header_row.pack(fill="x", padx=Spacing.MD(), pady=(Spacing.MD(), 6))

        self.lbl_panel_title = ctk.CTkLabel(self.header_row, text="STRATEGY SIGNAL", font=SF.SMALL(), text_color=Colors.LABEL)
        self.lbl_panel_title.pack(side="left")

        self.lbl_signal_badge = ctk.CTkLabel(
            self.header_row, text=" STAY OUT ", font=SF.NAV_BOLD(),
            text_color=Colors.TEXT, fg_color=Colors.WELL_BG, corner_radius=s(5)
        )
        self.lbl_signal_badge.pack(side="right")

        # "Last signal generated" timestamp -- shows when the strategy
        # engine last produced this reading, so it's clear whether it's
        # fresh or stale, and updates every refresh cycle.
        self.lbl_last_signal_time = ctk.CTkLabel(
            self, text="Last signal: --:--:--", font=SF.TINY(), text_color=Colors.TEXT_MUTED, anchor="w"
        )
        self.lbl_last_signal_time.pack(anchor="w", padx=Spacing.MD(), pady=(0, 4))

        # New-signal notification banner -- hidden by default, briefly
        # shown (then auto-hidden) whenever the strategy engine actually
        # produces a *different* signal than last time, so a genuinely
        # new setup doesn't get missed among routine refreshes.
        self.notification_banner = ctk.CTkLabel(
            self, text="", font=SF.NAV_BOLD(), text_color=Colors.ON_BUY,
            fg_color=Colors.BUY, corner_radius=s(6), height=s(28),
        )
        self._notification_after_id = None
        self._last_signal_key = None

        # Confidence strength meter — thin colored track that fills according
        # to the strategy's stated confidence, tinted by trade direction.
        self.meter_track = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, height=6, corner_radius=3)
        self.meter_track.pack(fill="x", padx=Spacing.MD(), pady=(0, Spacing.SM()))
        self.meter_track.pack_propagate(False)
        self.meter_fill = ctk.CTkFrame(self.meter_track, fg_color=Colors.BORDER_LIGHT, corner_radius=3)
        self.meter_fill.place(relx=0, rely=0, relwidth=0.0, relheight=1.0)

        # --- CORE SIGNAL DATA GRID ---
        self.grid_container = ctk.CTkFrame(self, fg_color=Colors.WELL_BG, border_width=1,
                                            border_color=Colors.BORDER, corner_radius=s(8))
        self.grid_container.pack(fill="x", padx=Spacing.MD(), pady=4)
        for i in range(4):
            self.grid_container.grid_columnconfigure(i, weight=1)

        # Trigger Column
        lbl_t1 = ctk.CTkLabel(self.grid_container, text="TRIGGER ENTRY", font=SF.STATUS_BOLD(), text_color=Colors.LABEL)
        lbl_t1.grid(row=0, column=0, pady=(8, 0))
        self.lbl_entry = ctk.CTkLabel(self.grid_container, text="NO SETUP", font=SF.MONO(), text_color=Colors.TEXT)
        self.lbl_entry.grid(row=1, column=0, pady=(0, 8))

        # Stop Loss Column
        lbl_t2 = ctk.CTkLabel(self.grid_container, text="STOP LOSS (SL)", font=SF.STATUS_BOLD(), text_color=Colors.LABEL)
        lbl_t2.grid(row=0, column=1, pady=(8, 0))
        self.lbl_sl = ctk.CTkLabel(self.grid_container, text="INACTIVE", font=SF.MONO(), text_color=Colors.TEXT)
        self.lbl_sl.grid(row=1, column=1, pady=(0, 8))

        # Take Profit Column
        lbl_t3 = ctk.CTkLabel(self.grid_container, text="TAKE PROFIT (TP)", font=SF.STATUS_BOLD(), text_color=Colors.LABEL)
        lbl_t3.grid(row=0, column=2, pady=(8, 0))
        self.lbl_tp = ctk.CTkLabel(self.grid_container, text="INACTIVE", font=SF.MONO(), text_color=Colors.TEXT)
        self.lbl_tp.grid(row=1, column=2, pady=(0, 8))

        # Risk Reward Column
        lbl_t4 = ctk.CTkLabel(self.grid_container, text="RISK/REWARD", font=SF.STATUS_BOLD(), text_color=Colors.LABEL)
        lbl_t4.grid(row=0, column=3, pady=(8, 0))
        self.lbl_rr = ctk.CTkLabel(self.grid_container, text="0.00 R", font=SF.MONO(), text_color=Colors.BUY)
        self.lbl_rr.grid(row=1, column=3, pady=(0, 8))

        # Lower Description Inline Text block
        self.lbl_metrics_header = ctk.CTkLabel(self, text="[ICT SMART MONEY] - Confidence: 85%", font=SF.PILL_LG(), text_color=Colors.LABEL)
        self.lbl_metrics_header.pack(anchor="w", padx=Spacing.MD(), pady=(10, 2))

        self.lbl_reasoning = ctk.CTkLabel(
            self, text="Waiting for the next candle to evaluate this strategy's rules.",
            font=SF.NAV(), text_color=Colors.TEXT_SECONDARY, justify="left", wraplength=s(520)
        )
        self.lbl_reasoning.pack(anchor="w", fill="x", padx=Spacing.MD(), pady=(0, 10))

        # --- DEEP ANALYSIS BUTTON ---
        self.btn_deep_scan = ctk.CTkButton(
            self, text="VIEW DETAILED ANALYSIS", fg_color=Colors.CARD_BG_ALT, hover_color=Colors.HOVER,
            border_width=1, border_color=Colors.BORDER_LIGHT, text_color=Colors.BUY, font=SF.NAV_BOLD(),
            height=s(36), corner_radius=s(8),
            command=self.launch_deep_analysis_report
        )
        self.btn_deep_scan.pack(fill="x", padx=Spacing.MD(), pady=(4, Spacing.MD()))



    def update_analysis(self, strategy: str, signal: str, confidence: str, reasoning: str, entry: float, sl: float, tp: float, rr: float):
        """Updates internal visualization matrices when ticker telemetry cycles update."""
        self.cached_strategy = strategy
        self.cached_signal = signal if signal else "STAY OUT"
        self.cached_confidence = confidence
        self.cached_reasoning = reasoning
        self.cached_rr = rr

        # A genuinely *new* setup is identified by strategy+direction+
        # entry changing -- not just any refresh cycle, which fires every
        # few seconds even when nothing changed. Only flash/notify when
        # this key actually differs from last time (and skip the very
        # first call, so opening the app doesn't fire a false "new signal").
        signal_key = (strategy, self.cached_signal, round(entry, 5) if entry else 0.0)
        is_actionable = self.cached_signal.upper() not in ("STAY OUT", "NEUTRAL", "")
        if self._last_signal_key is not None and signal_key != self._last_signal_key and is_actionable:
            self._flash_new_signal_notification()
        self._last_signal_key = signal_key
        self.lbl_last_signal_time.configure(text=f"Last signal: {time.strftime('%H:%M:%S')}")

        # Live signal badge — mirrors the direction/color language used
        # everywhere else in the app (buy = green, sell = red, flat = neutral)
        sig_upper = self.cached_signal.upper()
        if "BUY" in sig_upper:
            badge_bg, badge_fg = Colors.BUY, Colors.ON_BUY
        elif "SELL" in sig_upper:
            badge_bg, badge_fg = Colors.SELL, Colors.ON_SELL
        else:
            badge_bg, badge_fg = Colors.WELL_BG, Colors.TEXT_SECONDARY
        self.lbl_signal_badge.configure(text=f" {self.cached_signal} ", fg_color=badge_bg, text_color=badge_fg)

        # Confidence meter fill — parses "85%" style strings defensively
        try:
            pct = float(str(confidence).replace("%", "").strip()) / 100.0
        except (ValueError, TypeError):
            pct = 0.0
        pct = max(0.0, min(1.0, pct))
        meter_color = Colors.BUY if "BUY" in sig_upper else (Colors.SELL if "SELL" in sig_upper else Colors.BORDER_LIGHT)
        self.meter_fill.configure(fg_color=meter_color)
        self.meter_fill.place(relx=0, rely=0, relwidth=pct, relheight=1.0)

        self.lbl_metrics_header.configure(text=f"[{strategy.upper()}] - Confidence: {confidence}")

        if reasoning:
            self.lbl_reasoning.configure(text=reasoning)
        else:
            self.lbl_reasoning.configure(text="Evaluating current candle structure against this strategy's rules...")

        if entry > 0:
            self.lbl_entry.configure(text=f"${entry:,.4f}")
            self.lbl_sl.configure(text=f"${sl:,.4f}")
            self.lbl_tp.configure(text=f"${tp:,.4f}")
            self.lbl_rr.configure(text=f"{rr:.2f} R")
        else:
            self.lbl_entry.configure(text="NO SETUP")
            self.lbl_sl.configure(text="INACTIVE")
            self.lbl_tp.configure(text="INACTIVE")
            self.lbl_rr.configure(text="0.00 R")

    def _flash_new_signal_notification(self):
        """Shows a brief '🔔 New signal generated' banner above the
        signal grid, colored by direction, and auto-hides it after a
        few seconds. Cancels any banner already in flight so rapid
        back-to-back signal changes don't stack timers."""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if self._notification_after_id:
            try:
                self.after_cancel(self._notification_after_id)
            except Exception:
                pass
            self._notification_after_id = None

        sig_upper = self.cached_signal.upper()
        if "BUY" in sig_upper:
            bg, fg = Colors.BUY, Colors.ON_BUY
        elif "SELL" in sig_upper:
            bg, fg = Colors.SELL, Colors.ON_SELL
        else:
            bg, fg = Colors.PRIMARY, Colors.ON_BUY

        self.notification_banner.configure(
            text=f"🔔 New signal generated -- {self.cached_signal} ({self.cached_strategy})",
            fg_color=bg, text_color=fg,
        )
        self.notification_banner.pack(fill="x", padx=Spacing.MD(), pady=(0, 6), before=self.grid_container)
        self._notification_after_id = self.after(6000, self._hide_new_signal_notification)

    def _hide_new_signal_notification(self):
        self.notification_banner.pack_forget()
        self._notification_after_id = None

    def launch_deep_analysis_report(self):
        """Opens the detailed analysis modal for the active asset."""
        parent_win = self.winfo_toplevel()
        asset_name = getattr(parent_win, "current_coin", "EUR/USD")

        AIDeepAnalysisModal(
            parent=self.winfo_toplevel(),
            asset=asset_name,
            strategy=self.cached_strategy,
            signal=self.cached_signal,
            confidence=self.cached_confidence,
            reasoning=self.cached_reasoning,
            rr=self.cached_rr,
        )
