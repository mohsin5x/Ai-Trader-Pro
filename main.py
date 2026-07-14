"""
AI Trader Pro — Main Entry Point
Professional AI Trading Terminal
"""
import sys
import os

def _set_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

_set_dpi_awareness()

import customtkinter as ctk

# Disable ctk's own DPI scaling — our scaling.py handles all size math.
try:
    ctk.deactivate_automatic_dpi_awareness()
except Exception:
    pass

# CTkLabel.destroy() patch for customtkinter 5.2.2
def _ctk_label_destroy_patch(self):
    if getattr(self, "_font", None) is not None:
        try:
            from customtkinter.windows.widgets.font import CTkFont
            if isinstance(self._font, CTkFont):
                self._font.remove_size_configure_callback(self._update_font)
        except Exception:
            pass
    try:
        super(ctk.CTkLabel, self).destroy()
    except Exception:
        pass

ctk.CTkLabel.destroy = _ctk_label_destroy_patch


def _install_global_keyboard_nav(app):
    TEXT_WIDGETS = (ctk.CTkEntry, ctk.CTkTextbox)
    try:
        import tkinter as tk
        TEXT_WIDGETS = (ctk.CTkEntry, ctk.CTkTextbox, tk.Entry, tk.Text)
    except Exception:
        pass

    def _find_scrollable_parent(widget):
        w = widget
        for _ in range(20):
            if isinstance(w, ctk.CTkScrollableFrame):
                return w
            try:
                w = w.master
                if w is None:
                    break
            except Exception:
                break
        return None

    def _get_canvas(sf):
        for attr in ("_parent_canvas", "_canvas", "canvas"):
            if hasattr(sf, attr):
                c = getattr(sf, attr)
                if hasattr(c, "yview_scroll"):
                    return c
        return None

    def _on_key(event):
        focused = app.focus_get()
        if isinstance(focused, TEXT_WIDGETS):
            return
        sf = _find_scrollable_parent(focused)
        if sf is None:
            try:
                for key, frame in app.pages.items():
                    try:
                        if frame.winfo_ismapped():
                            for child in frame.winfo_children():
                                if isinstance(child, ctk.CTkScrollableFrame):
                                    sf = child
                                    break
                            if sf:
                                break
                    except Exception:
                        pass
            except Exception:
                pass
        if sf is None:
            return
        canvas = _get_canvas(sf)
        if canvas is None:
            return
        key = event.keysym
        try:
            if key == "Up":
                canvas.yview_scroll(-3, "units"); return "break"
            elif key == "Down":
                canvas.yview_scroll(3, "units"); return "break"
            elif key == "Left":
                canvas.xview_scroll(-3, "units"); return "break"
            elif key == "Right":
                canvas.xview_scroll(3, "units"); return "break"
            elif key == "Prior":
                canvas.yview_scroll(-15, "units"); return "break"
            elif key == "Next":
                canvas.yview_scroll(15, "units"); return "break"
            elif key == "Home":
                canvas.yview_moveto(0.0); return "break"
            elif key == "End":
                canvas.yview_moveto(1.0); return "break"
        except Exception:
            pass

    for seq in ("<Up>","<Down>","<Left>","<Right>","<Prior>","<Next>","<Home>","<End>"):
        app.bind_all(seq, _on_key, add="+")


def _install_global_shortcuts(app):
    _PAGE_SHORTCUTS = {
        "1":"dashboard","2":"ai_signals","3":"signal_history",
        "4":"market_scanner","5":"manual_scanner",
        "6":"watchlist","7":"news","8":"settings",
    }
    def _nav(p):
        try:
            if hasattr(app,"show_page"): app.show_page(p)
        except Exception: pass
    def _refresh():
        try:
            if hasattr(app,"trigger_pipeline"): app.trigger_pipeline()
        except Exception: pass
    def _fs():
        try:
            if hasattr(app,"toggle_chart_fullscreen"): app.toggle_chart_fullscreen()
        except Exception: pass
    
    for digit, page in _PAGE_SHORTCUTS.items():
        app.bind_all(f"<Control-{digit}>", lambda _e,p=page: _nav(p), add="+")
    app.bind_all("<Control-r>", lambda _e: _refresh(), add="+")
    app.bind_all("<F5>",        lambda _e: _refresh(), add="+")
    app.bind_all("<F11>",       lambda _e: _fs(), add="+")
    app.bind_all("<Control-q>", lambda _e: app._on_close(), add="+")


def main():
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    splash = None
    try:
        from ui.splash_screen import SplashScreen
        splash = SplashScreen()
        splash.show()
        if splash._win:
            splash._win.update()
    except Exception:
        pass

    # Build the main window (Phase 1 UI Shell Only - No backend services yet)
    from ui.main_window import MainWindow
    try:
        app = MainWindow()
    except Exception as _mw_err:
        if splash:
            try: splash.close()
            except Exception: pass
        raise _mw_err

    # Finalize scaling lock-in
    try:
        from ui import scaling as _scaling
        _scaling.poll_monitor_change(app, interval_ms=4000)
        _mw, _mh = _scaling.compute_min_size()
        app.minsize(_mw, _mh)
    except Exception:
        pass

    if splash:
        try: splash.close()
        except Exception: pass

    # Window Management Sequence
    def _do_maximize():
        try:
            app.state("zoomed")
        except Exception:
            try:
                app.attributes("-zoomed", True)
            except Exception:
                w = app.winfo_screenwidth()
                h = app.winfo_screenheight()
                app.geometry(f"{w}x{h}+0+0")

        def _remeasure():
            try:
                from ui import scaling as _sc
                _sc._measure(app)
                if hasattr(app, "sidebar_frame"):
                    app.sidebar_frame.configure(width=_sc.S.SIDEBAR_W())
                mw2, mh2 = _sc.compute_min_size()
                app.minsize(mw2, mh2)
                app.update_idletasks()
            except Exception:
                pass

        app.after(350, _remeasure)
        app.after(750, _remeasure)
        
        # Initiate the professional staggered startup lifecycle
        app.after(1000, app.start_lifecycle)

    app.after(100, _do_maximize)

    # Keyboard helpers
    app.after(500, lambda: _install_global_keyboard_nav(app))
    app.after(600, lambda: _install_global_shortcuts(app))

    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("\nAI Trader Pro terminated by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()