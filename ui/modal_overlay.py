"""
ui/modal_overlay.py
====================
AI Trader Pro — Shared Modal / Dialog Infrastructure

Root-cause fix for the black-screen flash that appeared whenever any
popup dialog was opened or closed.

WHY THE BLACK FLASH OCCURRED
─────────────────────────────
Every CTkToplevel dialog in the codebase called two things immediately
inside __init__, before the window was even mapped by the OS:

    self.update_idletasks()          ← flushes the Tk event queue
    self.attributes("-topmost", True)  ← then later sets it False
    self.lift()                      ← premature Z-order change
    self.focus_force()               ← forces compositor redraw

On Windows, CTkToplevel.__init__ itself already triggers a DWM
(Desktop Window Manager) composition event.  Adding update_idletasks()
on top of that forces the main window to repaint synchronously *while*
the new dialog is being built — its compositor buffer is momentarily
empty (pure black).  The -topmost True→False toggle and focus_force()
each cause additional compositor Z-order round-trips, producing
repeated black frames.

Additionally, paper_trading_panel._confirm_reset() referenced an
undefined name `win` (the dialog was named `confirm`), silently raising
NameError on every reset attempt.

THE FIX
────────
1.  BaseDialog — a lightweight mixin for all CTkToplevel subclasses:
    •  Never calls update_idletasks() or update() during __init__
    •  Never calls lift(), focus_force(), or -topmost during __init__
    •  Defers focus to a single `after(10, _deferred_show)` call that
       runs *after* the event loop has mapped and painted the window
    •  Preserves grab_set() where dialogs already used it (modal lock)
    •  Centers on parent using winfo_root* — no extra repaint needed

2.  dialog_center() — pure geometry helper, zero side-effects.

3.  make_dialog() — factory that applies BaseDialog conventions to any
    inline CTkToplevel (the confirm/reset dialogs in paper_trading_panel
    and algo_trading_panel that aren't subclasses).

USAGE
──────
    # Subclass approach (preferred):
    class MyDialog(BaseDialog):
        def __init__(self, parent):
            super().__init__(parent, title="My Dialog", size=(480, 320))
            # build widgets here — no grab, no focus, no update needed

    # Inline approach (for one-off Toplevels):
    win = ctk.CTkToplevel(parent)
    make_dialog(win, parent, title="Confirm", size=(380, 150))
    # build widgets ... then nothing else needed

WHAT IS PRESERVED
──────────────────
•  CustomTkinter UI and architecture — completely unchanged
•  grab_set() on MT5InstructionsDialog — still blocks main window
•  transient() — still set so dialog minimises with parent
•  All dialog content, buttons, logic — untouched
•  chart_widget fullscreen: uses withdraw/deiconify for a canvas-paint
   reason, not a focus reason — that path is left alone
•  splash_screen.update() — runs before MainWindow exists, safe
"""

from __future__ import annotations
import customtkinter as ctk


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────

def dialog_center(dialog: ctk.CTkToplevel, parent, width: int, height: int) -> None:
    """
    Position *dialog* centred over *parent* without forcing any repaints.

    Uses winfo_rootx/y which are already known from the parent's existing
    geometry — no update_idletasks() required.
    """
    try:
        px = parent.winfo_rootx() + (parent.winfo_width()  - width)  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        # Keep on-screen
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        px = max(0, min(px, sw - width))
        py = max(0, min(py, sh - height))
        dialog.geometry(f"{width}x{height}+{px}+{py}")
    except Exception:
        dialog.geometry(f"{width}x{height}")


def make_dialog(
    win: ctk.CTkToplevel,
    parent,
    *,
    title: str = "",
    size: tuple[int, int] | None = None,
    resizable: tuple[bool, bool] = (False, False),
    use_grab: bool = False,
) -> None:
    """
    Apply consistent, flash-free modal setup to an *already-created*
    CTkToplevel that is not a BaseDialog subclass.

    Call this immediately after ``ctk.CTkToplevel(parent)`` and before
    adding any child widgets.  Do **not** call update_idletasks(),
    update(), lift(), focus_force(), or set -topmost anywhere else.
    """
    # Withdraw immediately — prevents the blank default-root window that
    # Windows/CTk shows before the dialog is fully constructed.
    win.withdraw()

    if title:
        win.title(title)
    win.resizable(*resizable)
    win.transient(parent)
    win.protocol("WM_DELETE_WINDOW", win.destroy)

    if size:
        dialog_center(win, parent, size[0], size[1])

    if use_grab:
        try:
            win.grab_set()
        except Exception:
            pass

    # Single deferred focus — runs after the event loop maps the window,
    # so the compositor already has a valid buffer to show.
    win.after(10, lambda: _deferred_show(win))


def _deferred_show(win: ctk.CTkToplevel) -> None:
    """
    Called once, ~10 ms after the dialog is created, by which time the
    OS has mapped and composited the window.  We deiconify (un-withdraw),
    then lift and focus — no topmost toggle, no update_idletasks.
    """
    try:
        if not win.winfo_exists():
            return
        win.deiconify()   # un-withdraw so the fully-built window appears
        win.lift()
        win.focus_set()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# BaseDialog mixin
# ─────────────────────────────────────────────────────────────────────────────

class BaseDialog(ctk.CTkToplevel):
    """
    Drop-in base class for every modal dialog in AI Trader Pro.

    Guarantees:
    •  No update_idletasks() / update() during construction
    •  No premature lift() / focus_force() / -topmost during construction
    •  Centered on parent without extra repaints
    •  Single deferred focus after OS maps the window
    •  grab_set() only when use_grab=True

    Subclasses call super().__init__() and then build their widgets.
    Nothing else is needed.
    """

    def __init__(
        self,
        parent,
        *,
        title: str = "",
        size: tuple[int, int] | None = None,
        resizable: tuple[bool, bool] = (False, False),
        use_grab: bool = False,
    ):
        super().__init__(parent)

        # Withdraw immediately to prevent the blank default-root flash
        # that Windows/CTk shows before the dialog is styled and positioned.
        self.withdraw()

        if title:
            self.title(title)
        self.resizable(*resizable)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        if size:
            dialog_center(self, parent, size[0], size[1])

        if use_grab:
            try:
                self.grab_set()
            except Exception:
                pass

        # Deferred focus — single call, no topmost toggling
        self.after(10, self._on_mapped)

    # ------------------------------------------------------------------
    def _on_mapped(self) -> None:
        """Runs once after the event loop maps the window."""
        try:
            if not self.winfo_exists():
                return
            self.deiconify()   # un-withdraw — dialog is fully built now
            self.lift()
            self.focus_set()
        except Exception:
            pass

    # Convenience so subclasses that override WM_DELETE_WINDOW can also
    # release the grab before destroying.
    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
