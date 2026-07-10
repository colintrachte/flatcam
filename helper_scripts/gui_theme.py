"""
gui_theme.py — shared ttk look-and-feel for this kit's Tk GUIs (pack_task.py's Quest
Board, setup_wizard_gui.py's Project Wizard Manager).

Stdlib-only: restyles ttk's built-in 'clam' theme rather than pulling in a theme
package, so it stays safe to copy into every target project alongside the rest of
helper_scripts/ (see profiles.json's "helper_gui_theme" entry).

Usage:
    import gui_theme
    gui_theme.configure_style(self)   # self is the Tk root/App instance, call first
                                       # in __init__ before building any child widgets
"""

import tkinter as tk
from tkinter import ttk

FONT_FAMILY = "Segoe UI"
FONT_BASE = (FONT_FAMILY, 10)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_BIG_BOLD = (FONT_FAMILY, 16, "bold")

COLOR_BG = "#f6f7f9"
COLOR_SURFACE = "#ffffff"
COLOR_BORDER = "#d8dbe0"
COLOR_TEXT = "#1f2430"
COLOR_MUTED = "#6b7280"
COLOR_ACCENT = "#3562d4"
COLOR_ACCENT_HOVER = "#2a4fb0"
COLOR_ROW_ALT = "#eef1f5"
COLOR_SELECT_BG = "#dbe6ff"

# Treeview row-striping tag names + the pair of colors they map to — shared so every
# tree.insert(..., tags=(gui_theme.stripe_tag(idx),)) call across both GUIs agrees on
# which index is "even" without each file re-deriving it.
TAG_EVEN = "gui_theme_even"
TAG_ODD = "gui_theme_odd"


def stripe_tag(idx: int) -> str:
    return TAG_EVEN if idx % 2 == 0 else TAG_ODD


def tag_stripes(tree: ttk.Treeview) -> None:
    """Register the two row-stripe tags on a Treeview. Call once after creating it,
    then pass tags=(stripe_tag(idx),) on each tree.insert()."""
    tree.tag_configure(TAG_EVEN, background=COLOR_SURFACE)
    tree.tag_configure(TAG_ODD, background=COLOR_ROW_ALT)


def configure_style(root: tk.Tk) -> ttk.Style:
    """One-time ttk.Style pass so a window reads as one flat, modern UI instead of
    stock ttk defaults. Must run before any child widget is built -- option_add()
    only affects widgets created afterward. Returns the Style object in case a
    caller wants to layer on a one-off style (e.g. a semantic "Go" button color).
    """
    root.configure(bg=COLOR_BG)
    root.option_add("*Font", FONT_BASE)
    root.option_add("*Text.background", COLOR_SURFACE)
    root.option_add("*Text.foreground", COLOR_TEXT)
    root.option_add("*Text.relief", "flat")
    root.option_add("*Text.borderWidth", 1)
    root.option_add("*Text.highlightThickness", 1)
    root.option_add("*Text.highlightColor", COLOR_BORDER)
    root.option_add("*Text.highlightBackground", COLOR_BORDER)
    root.option_add("*Listbox.background", COLOR_SURFACE)
    root.option_add("*Menu.font", FONT_BASE)
    # scrolledtext.ScrolledText embeds a classic (non-ttk) Scrollbar, which Tk's newer
    # dark-mode-aware builds render near-black by default on Windows when the OS is in
    # dark mode -- same class of oversight the Listbox line above already worked around.
    root.option_add("*Scrollbar.background", COLOR_BORDER)
    root.option_add("*Scrollbar.troughColor", COLOR_BG)
    root.option_add("*Scrollbar.activeBackground", COLOR_ACCENT_HOVER)
    root.option_add("*Scrollbar.highlightThickness", 0)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=FONT_BASE, background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("TFrame", background=COLOR_BG)
    style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("TLabelframe", background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("TLabelframe.Label", background=COLOR_BG, foreground=COLOR_TEXT, font=FONT_BOLD)
    style.configure("TButton", font=FONT_BASE, padding=6)
    style.map("TButton", background=[("active", "#e4e7ec")])
    style.configure("TEntry", fieldbackground=COLOR_SURFACE, padding=4)
    style.configure("TCombobox", fieldbackground=COLOR_SURFACE, padding=4)
    style.configure("TCheckbutton", background=COLOR_BG, font=FONT_BASE)
    style.configure("TRadiobutton", background=COLOR_BG, font=FONT_BASE)

    style.configure(
        "Treeview",
        background=COLOR_SURFACE,
        fieldbackground=COLOR_SURFACE,
        foreground=COLOR_TEXT,
        rowheight=26,
        font=FONT_BASE,
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background=COLOR_BORDER,
        foreground=COLOR_TEXT,
        font=FONT_BOLD,
        relief="flat",
        padding=6,
    )
    style.map(
        "Treeview",
        background=[("selected", COLOR_SELECT_BG)],
        foreground=[("selected", COLOR_TEXT)],
    )
    style.map("Treeview.Heading", background=[("active", "#c9ced6")])

    # Primary "move forward" actions (Pack, Configure & Send, Send). Deliberately not
    # applied to irreversible writes (Mark Complete, Remove Tools' Confirm) -- those
    # stay plain TButton so the UI doesn't visually invite the riskier action.
    style.configure(
        "Accent.TButton", font=FONT_BOLD, padding=8, background=COLOR_ACCENT, foreground="white"
    )
    style.map(
        "Accent.TButton",
        background=[("active", COLOR_ACCENT_HOVER), ("disabled", COLOR_BORDER)],
        foreground=[("disabled", COLOR_MUTED)],
    )
    # Big.TButton predates this module (chunk Prev/Next stepper, Send) -- accent-color
    # it here too so all of its call sites pick up the same look for free.
    style.configure(
        "Big.TButton", font=FONT_BIG_BOLD, padding=14, background=COLOR_ACCENT, foreground="white"
    )
    style.map(
        "Big.TButton", background=[("active", COLOR_ACCENT_HOVER), ("disabled", COLOR_BORDER)]
    )

    return style
