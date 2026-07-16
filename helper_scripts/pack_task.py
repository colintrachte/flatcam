"""
pack_task.py — GUI: pick a roadmap task, get a pastable context pack.

Closes the manual gap between route_tasks.py (parses roadmap.md, stamps
**Route:**) and context_pack.py (needs an explicit file list typed on the
command line). This wraps both behind one window: refresh routing -> check
one or more tasks in a sortable/filterable table -> preview the assembled
pack -> copy / save / send.

Usage:
    python helper_scripts/pack_task.py

No new dependencies: tkinter is stdlib; network calls reuse query_model.py's
existing urllib-based client.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_pack  # noqa: E402
import gui_theme  # noqa: E402
import query_model  # noqa: E402
import route_tasks  # noqa: E402
from pack_delivery import (
    INBOX_FILENAME_MAX as INBOX_FILENAME_MAX,
)
from pack_delivery import (
    OPENROUTER_KEY_FILE,
    OPENROUTER_MODELS,
    PORTABLE_MODE,
    REPOSITORY_MODE,
    SLOP_FILTER_CONSERVATIVE,
    SLOP_FILTER_MODES,
    _chunk_budget,
    _forget_saved_key,
    _load_saved_key,
    _save_key,
    append_inbox_response,
    build_repository_handoff,
    build_task_prompt,
    compact_context_body,
    count_inbox_responses,
    ensure_response_work_dirs,
    inbox_path,
    select_handoff,
)
from pack_delivery import (
    SLOP_FILTER_OFF as SLOP_FILTER_OFF,
)
from pack_delivery import (
    filter_response_text as filter_response_text,
)
from pack_delivery import (
    response_work_dirs as response_work_dirs,
)
from pack_delivery import (
    task_slug as task_slug,
)
from task_editor import (
    DiffPreviewDialog as DiffPreviewDialog,
)
from task_editor import (
    TaskEditorDialog,
    _wrap_with_parent,
    delete_task_block,
    derive_task_readiness,
    task_statuses,
)
from task_editor import (
    build_task_lines as build_task_lines,
)
from task_editor import (
    compute_task_effort as compute_task_effort,
)
from task_editor import (
    find_section_end as find_section_end,
)
from task_editor import (
    insert_task_block as insert_task_block,
)
from task_editor import (
    move_task_block as move_task_block,
)
from task_editor import (
    parse_task_fields as parse_task_fields,
)
from task_editor import (
    readiness_diagnostics as readiness_diagnostics,
)
from task_editor import (
    replace_task_block as replace_task_block,
)
from task_editor import (
    roadmap_diff as roadmap_diff,
)
from task_editor import (
    validate_task_fields as validate_task_fields,
)
from task_records import (
    Task,
    blocker_summary,
    derive_reverse_relationships,
    parse_tasks,
    ready_tasks,
    split_header,
    task_order_advisories,
)

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROADMAP = SCRIPT_ROOT / "docs" / "roadmap.md"
DEFAULT_SHIPPED = SCRIPT_ROOT / "docs" / "shipped.md"
# Forward-only high-water mark for generated **Context Load:**. The legacy filename is
# read once during migration so existing projects keep their established ordering scale.
# _combined_score) stays stable across sessions instead of rescaling every refresh.
CONTEXT_LOAD_CEILING_PATH = Path(__file__).resolve().parent / "context_load_ceiling.txt"
LEGACY_EFFORT_CEILING_PATH = Path(__file__).resolve().parent / "effort_ceiling.txt"

CHECK_EMPTY = "☐"  # ☐
CHECK_FULL = "☑"  # ☑


def _score_int(t: "Task") -> int:
    score, _ = split_header(t.header)
    return int(score) if score.isdigit() else 0


def _effort_int(t: "Task") -> int | None:
    return int(t.effort) if t.effort.isdigit() else None


def _read_effort_ceiling() -> int:
    for path in (CONTEXT_LOAD_CEILING_PATH, LEGACY_EFFORT_CEILING_PATH):
        try:
            value = max(1, int(path.read_text(encoding="utf-8").strip()))
        except (FileNotFoundError, ValueError):
            continue
        if path == LEGACY_EFFORT_CEILING_PATH and not CONTEXT_LOAD_CEILING_PATH.exists():
            CONTEXT_LOAD_CEILING_PATH.write_text(str(value), encoding="utf-8")
        return value
    return 1


def _update_effort_ceiling(tasks: list["Task"]) -> int:
    """Raise the persisted ceiling if any open task's Context Load exceeds it; never
    lowers it. Returns the effective ceiling to normalize against."""
    stored = _read_effort_ceiling()
    seen_max = max((_effort_int(t) or 0 for t in tasks), default=0)
    ceiling = max(stored, seen_max)
    if ceiling != stored:
        CONTEXT_LOAD_CEILING_PATH.write_text(str(ceiling), encoding="utf-8")
    return ceiling


def _combined_score(t: "Task", effort_ceiling: int) -> float:
    """Value-density, with Context Load normalized onto the same 1-5 scale as score (the
    persisted ceiling maps to 5) before dividing — otherwise the metric's much larger
    raw range (1 to 1000+) swamps score's 1-5 range and the ratio is effectively just
    1/effort. Squared, not linear: a task twice as complex costs more than twice as much
    once you're past small/mechanical size (route_tasks.py's own tier bumps aren't linear
    either). 0 when effort isn't known yet (unrouted)."""
    effort = _effort_int(t)
    score = _score_int(t)
    if effort is None or score == 0:
        return 0.0
    effort_scaled = 1 + 4 * (min(effort, effort_ceiling) / effort_ceiling) ** 2
    return score / effort_scaled


def _model_breakdown(t: "Task") -> bool:
    """True when the task got bumped all the way to claude purely for size (too many
    files or too many chars — route_tasks.py's own routing rules), not because it's
    Class 3. This is the dividing line where free/local models stop being viable at all,
    as opposed to gemini->kimi bumps which just move within free-tier capacity."""
    return t.task_class != "3" and t.route == "claude"


def _default_sort_key(t: "Task") -> tuple[int, int]:
    """Highest score first; lowest Context Load breaks ties within the same score.
    Unrouted (unknown) load sorts last within its score tier."""
    effort = _effort_int(t)
    return (-_score_int(t), effort if effort is not None else 10**9)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        import argparse

        p = argparse.ArgumentParser(add_help=False)
        p.add_argument("--roadmap")
        p.add_argument("--shipped")
        cli, _ = p.parse_known_args()
        self.ROADMAP_PATH = (
            Path(cli.roadmap).expanduser().resolve() if cli.roadmap else DEFAULT_ROADMAP
        )
        self.SHIPPED_PATH = (
            Path(cli.shipped).expanduser().resolve() if cli.shipped else DEFAULT_SHIPPED
        )
        self.title("Quest Board")
        self.geometry("960x720")  # initial size only; every page remains freely resizable
        self.resizable(True, True)
        gui_theme.configure_style(self)
        self.root_dir = context_pack.repo_root()
        self.inbox_dir, self.assimilated_dir = ensure_response_work_dirs(self.root_dir)
        self.result_queue = queue.Queue()
        self.tasks = []
        self.filtered_tasks = []
        self.roadmap_lines = []  # backing lines for task.start/task.end — set by _load_tasks
        self.effort_ceiling = _read_effort_ceiling()
        self.checked = set()  # iids (str index into filtered_tasks) checked in the picker table
        self.current_tasks = []  # the task(s) behind the pack currently shown on the pack screen
        self._current_inbox_path = (
            None  # set by _refresh_inbox_section when exactly 1 task is packed
        )
        self.chunks = []  # paste-sized chunks of the current pack, banner-wrapped
        self.chunk_idx = 0
        # When checked (default), the pack screen shows one concatenated block, even
        # past a model's char budget — e.g. to deliberately spend one of chatgpt's
        # file-upload slots (docs/ai-harness.md §1) instead of pasting in chunks. When
        # unchecked, the pack screen instead shows only the paginated chunk view (large
        # Prev/Next) so a monster paste never lands in the box by surprise. Lives on the
        # pack screen (not the picker) since it only controls that screen's display mode;
        # chunks are always computed in _on_pack regardless of this value.
        self.ignore_char_limit = tk.BooleanVar(value=True)
        self.slop_filter_mode = tk.StringVar(value=SLOP_FILTER_CONSERVATIVE)
        self.delivery_mode = tk.StringVar(value=PORTABLE_MODE)
        self.delivery_executor = tk.StringVar(value="paid-ai")

        # send/settings screen state. Most of it is session-only; the OpenRouter key is
        # the exception — it may be persisted, but only when the user opts in via the
        # "Remember" checkbox (see _on_remember_toggled). The key is prefilled from the
        # OPENROUTER_API_KEY env var first, then a previously-saved file, so the env var
        # still wins and default behavior is unchanged when nothing was saved.
        self.send_target = tk.StringVar(value="qwen")
        self.send_endpoint = tk.StringVar(value=self._default_endpoint("qwen"))
        self.openrouter_models = list(
            OPENROUTER_MODELS
        )  # combobox values; replaced by a live fetch
        self.send_model_or = tk.StringVar(value=self.openrouter_models[0])
        _saved_key = _load_saved_key()
        self.send_api_key = tk.StringVar(
            value=os.environ.get("OPENROUTER_API_KEY", "") or _saved_key
        )
        self.remember_key = tk.BooleanVar(
            value=bool(_saved_key)
        )  # ticked if a key was previously saved
        self.send_max_tokens = tk.StringVar(value="4096")
        self.qwen_detected_model = None  # set by "Detect Now", used only for the preview
        self._delete_undo = None

        self.picker_frame = ttk.Frame(self, padding=12)
        self.pack_frame = ttk.Frame(self, padding=12)
        self.send_frame = ttk.Frame(self, padding=12)
        self._build_picker_frame()
        self._build_pack_frame()
        self._build_send_frame()
        self._load_tasks()
        self.picker_frame.pack(fill="both", expand=True)

    def refresh_routes(self) -> list[str]:
        """Re-stamp **Route:**/**Chars:** in roadmap.md (same effect as route_tasks.py's
        default run). The write goes through route_tasks.write_roadmap — the same truncation
        sanity check and atomic temp-file-then-rename as the CLI — so the GUI never has a
        laxer write path than the CLI. Raises RuntimeError if the output looks truncated."""
        text = self.ROADMAP_PATH.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        updated = route_tasks.process_roadmap(lines, self.ROADMAP_PATH, context_pack.repo_root())
        route_tasks.write_roadmap(self.ROADMAP_PATH, lines, updated)
        return updated

    # ── picker screen ──

    def _build_picker_frame(self):
        f = self.picker_frame

        # Give each kind of action its own full-width group. The groups share one row
        # when there is room and stack at narrow widths, while their buttons divide the
        # available group width evenly instead of collecting in the outer corners.
        self.picker_toolbar = ttk.Frame(f)
        self.picker_toolbar.pack(fill="x", pady=(0, 6))
        self.picker_action_groups = []

        selection_actions = self._picker_action_group(
            (
                ("↻ Refresh", self._load_tasks, None),
                ("Check All", lambda: self._set_all_checked(True), None),
                ("Clear", lambda: self._set_all_checked(False), None),
                ("Ready View", self._on_ready_view_toggle, "ready_view_button"),
            )
        )
        task_actions = self._picker_action_group(
            (
                ("+ New Task", self._on_new_task, None),
                ("✎ Edit", self._on_edit_task, None),
                ("Clone", self._on_clone_task, None),
                ("Delete Task", self._on_delete_task, None),
                ("Undo Delete", self._on_undo_delete, "undo_delete_button"),
            )
        )
        workflow_actions = self._picker_action_group(
            (
                ("Mark Complete →", self._on_mark_complete, None),
                ("Pack →", self._on_pack, "pack_button"),
            )
        )
        self.pack_button.configure(style="Accent.TButton")
        self.undo_delete_button.configure(state="disabled")
        self.picker_action_groups.extend((selection_actions, task_actions, workflow_actions))
        self._picker_group_rows = None
        self.picker_toolbar.bind("<Configure>", self._reflow_picker_actions)

        picker_help = ttk.Label(
            f,
            text=(
                "Pick one or more roadmap tasks (check the box to include in the pack). "
                "Ready View is advisory; Show All lets you pack work in any order:"
            ),
            font=("", 11, "bold"),
            justify="left",
        )
        picker_help.pack(fill="x")
        _wrap_with_parent(picker_help, f)

        search_row = ttk.Frame(f)
        search_row.pack(fill="x", pady=(4, 4))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(search_row, textvariable=self.filter_var).pack(side="left", fill="x", expand=True)
        ttk.Button(search_row, text="×", width=3, command=lambda: self.filter_var.set("")).pack(
            side="left", padx=(4, 0)
        )

        tree_frame = ttk.Frame(f)
        tree_frame.pack(fill="both", expand=True, pady=(0, 6))

        columns = (
            "sel",
            "score",
            "effort",
            "combined",
            "class",
            "status",
            "blocked_by",
            "route",
            "files",
            "section",
            "title",
        )
        # (heading label, width, whether this column absorbs extra widget width)
        col_spec = {
            "sel": ("", 26, False),
            "score": ("Score", 60, False),
            "effort": ("Context Load", 85, False),
            "combined": ("Value/Load", 80, False),
            "class": ("Class", 50, False),
            "status": ("Status", 80, False),
            "blocked_by": ("Warnings", 260, False),
            "route": ("Route", 80, False),
            "files": ("Files", 60, False),
            "section": ("Section", 170, False),
            "title": ("Title", 400, True),
        }
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        for col in columns:
            label, width, stretch = col_spec[col]
            self.tree.column(col, width=width, anchor="w", stretch=stretch)
            if col == "sel":
                self.tree.heading(col, text=label)  # not sortable — it's the checkbox column
            else:
                self.tree.heading(col, text=label, command=lambda c=col: self._sort_by(c, False))
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Button-1>", self._on_tree_click)
        gui_theme.tag_stripes(self.tree)

    def _picker_action_group(self, actions):
        group = ttk.Frame(self.picker_toolbar)
        for col, (text, command, attr) in enumerate(actions):
            button = ttk.Button(group, text=text, command=command)
            button.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 3, 0))
            group.columnconfigure(col, weight=1, uniform="picker_action")
            if attr:
                setattr(self, attr, button)
        return group

    def _reflow_picker_actions(self, event):
        """Keep action groups distributed at wide sizes and stacked when narrow."""
        rows = 1 if event.width >= 900 else 3
        if rows == self._picker_group_rows:
            return
        self._picker_group_rows = rows
        for group in self.picker_action_groups:
            group.grid_forget()
        if rows == 1:
            for col, group in enumerate(self.picker_action_groups):
                group.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
                self.picker_toolbar.columnconfigure(col, weight=1)
        else:
            for row, group in enumerate(self.picker_action_groups):
                group.grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else 4, 0))
            self.picker_toolbar.columnconfigure(0, weight=1)
            for col in (1, 2):
                self.picker_toolbar.columnconfigure(col, weight=0)

    def _load_tasks(self):
        self.tasks = []
        self.filtered_tasks = []
        try:
            lines = self.refresh_routes()
        except FileNotFoundError:
            messagebox.showerror("roadmap.md not found", f"Could not find {self.ROADMAP_PATH}")
            self.tree.delete(*self.tree.get_children())
            return
        except (RuntimeError, ValueError) as e:
            # write_roadmap refused a truncated-looking rewrite — the file on disk is
            # untouched; surface the refusal instead of showing silently stale routes.
            messagebox.showerror("Roadmap refresh failed", str(e))
            self.tree.delete(*self.tree.get_children())
            return
        self.roadmap_lines = lines  # what task.start/task.end index into — see _on_mark_complete
        self.tasks = parse_tasks(lines, self.root_dir)
        derive_reverse_relationships(self.tasks)
        lifecycle_lines = list(lines)
        if self.SHIPPED_PATH.is_file():
            lifecycle_lines.extend(
                self.SHIPPED_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            )
        derive_task_readiness(self.tasks, lines, self.root_dir, task_statuses(lifecycle_lines))
        self.effort_ceiling = _update_effort_ceiling(self.tasks)
        self._apply_filter()

    def _on_ready_view_toggle(self):
        self._ready_view_mode = not getattr(self, "_ready_view_mode", False)
        self.ready_view_button.configure(text="Show All" if self._ready_view_mode else "Ready View")
        self._apply_filter()

    def _apply_filter(self):
        q = self.filter_var.get().strip().lower()
        if q:
            # Matches header/title, section heading, class, and route — not just the
            # header. A research task's own title rarely contains its section's theme
            # word; that word only lives in the section heading above it.
            self.filtered_tasks = [
                t
                for t in self.tasks
                if q in t.header.lower()
                or q in t.section.lower()
                or q in t.task_class.lower()
                or q in t.status.lower()
                or q in t.id.lower()
                or q in t.route.lower()
            ]
        else:
            self.filtered_tasks = list(self.tasks)

        if getattr(self, "_ready_view_mode", False):
            lifecycle_lines = list(self.roadmap_lines)
            if self.SHIPPED_PATH.is_file():
                lifecycle_lines.extend(
                    self.SHIPPED_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
                )
            self.filtered_tasks = ready_tasks(self.filtered_tasks, task_statuses(lifecycle_lines))

        # Default order: highest score first, lowest effort breaks ties among equally-
        # scored tasks. Re-applied on every load/filter change; an explicit header click
        # below overrides it until the next load/filter.
        self.filtered_tasks.sort(key=_default_sort_key)

        self.checked.clear()
        self.tree.delete(*self.tree.get_children())
        lifecycle_lines = list(self.roadmap_lines)
        if self.SHIPPED_PATH.is_file():
            lifecycle_lines.extend(
                self.SHIPPED_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            )
        status_map = task_statuses(lifecycle_lines)
        tasks_by_id = {task.id: task for task in self.tasks if task.id}
        for idx, t in enumerate(self.filtered_tasks):
            score, title = split_header(t.header)
            score_col = f"{score} {route_tasks._medal(score)}" if score else ""
            files_col = str(len(t.files)) + (f" (+{len(t.missing)})" if t.missing else "")
            combined = _combined_score(t, self.effort_ceiling)
            combined_col = f"{combined:.2f}" if combined else ""
            # ⚠ marks tasks bumped to claude purely for size — past the point where
            # free/local models are viable at all, not just a routing preference.
            route_col = t.route
            if _model_breakdown(t):
                route_col += " ⚠"
            elif t.route.lower().startswith("me"):
                route_col = "👤 me"
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                tags=(gui_theme.stripe_tag(idx),),
                values=(
                    CHECK_EMPTY,
                    score_col,
                    t.effort,
                    combined_col,
                    t.task_class,
                    t.status or "Legacy",
                    blocker_summary(t, tasks_by_id, status_map),
                    route_col,
                    files_col,
                    t.section,
                    title,
                ),
            )
        children = self.tree.get_children()
        if children:
            self.tree.focus(children[0])
            self.tree.selection_set(children[0])

    NUMERIC_COLS = {"score", "effort", "combined", "files"}

    @staticmethod
    def _cell_sort_key(col, value):
        """Numeric columns sort on their leading number (score's medal glyph and files'
        "N (+M)" suffix are ignored), not lexicographically — "780" must sort after "120",
        not before it. Unknown/blank cells (e.g. unrouted effort) sort as lowest."""
        if col in App.NUMERIC_COLS:
            m = re.match(r"\d+(\.\d+)?", value.strip())
            return float(m.group()) if m else -1.0
        return value.lower()

    def _sort_by(self, col, reverse):
        """Click-to-sort a column header. Rows keep their iid (the filtered_tasks index),
        so this only reorders the display — checked state and _selected_tasks still resolve
        correctly afterward."""
        rows = [(self.tree.set(iid, col), iid) for iid in self.tree.get_children()]
        rows.sort(key=lambda r: self._cell_sort_key(col, r[0]), reverse=reverse)
        for pos, (_, iid) in enumerate(rows):
            self.tree.move(iid, "", pos)
        self.tree.heading(col, command=lambda: self._sort_by(col, not reverse))

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if self.tree.identify_column(event.x) == "#1":  # the checkbox column
            self._toggle_checked(row)

    def _toggle_checked(self, iid):
        if iid in self.checked:
            self.checked.discard(iid)
            self.tree.set(iid, "sel", CHECK_EMPTY)
        else:
            self.checked.add(iid)
            self.tree.set(iid, "sel", CHECK_FULL)

    def _set_all_checked(self, state):
        for iid in self.tree.get_children():
            if state:
                self.checked.add(iid)
                self.tree.set(iid, "sel", CHECK_FULL)
            else:
                self.checked.discard(iid)
                self.tree.set(iid, "sel", CHECK_EMPTY)

    def _selected_tasks(self):
        """Checked rows if any are checked, else the single focused/clicked row."""
        if self.checked:
            idxs = sorted(int(i) for i in self.checked)
        else:
            focus = self.tree.focus()
            idxs = [int(focus)] if focus else []
        return [self.filtered_tasks[i] for i in idxs]

    def _one_selected_task(self):
        """Single-task actions are stricter than _selected_tasks() (which accepts any
        count): exactly one task, checked or focused. Shows an info dialog and returns
        None otherwise."""
        tasks = self._selected_tasks()
        if len(tasks) != 1:
            messagebox.showinfo(
                "Select exactly one task",
                f"Check exactly one task (or click a single row) before continuing — "
                f"{len(tasks)} currently selected.",
            )
            return None
        return tasks[0]

    def _on_new_task(self):
        TaskEditorDialog(self, task=None)

    def _on_edit_task(self):
        task = self._one_selected_task()
        if task is not None:
            TaskEditorDialog(self, task=task)

    def _on_clone_task(self):
        task = self._one_selected_task()
        if task is not None:
            TaskEditorDialog(self, task=task, clone=True)

    def _on_delete_task(self):
        task = self._one_selected_task()
        if task is None:
            return
        result = delete_task_block(self.roadmap_lines, task.start, task.end)
        title = split_header(task.header)[1]
        self._apply_delete(result, title)

    def _apply_delete(self, result, title):
        before = list(self.roadmap_lines)
        try:
            current = self.ROADMAP_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            if current != before:
                messagebox.showerror(
                    "Roadmap changed",
                    "roadmap.md changed since the task list was loaded. Reload and try again; "
                    "nothing was deleted.",
                )
                return False
            # Deliberate task removal can exceed write_roadmap()'s truncation threshold
            # (especially in a one-task roadmap), so use the same atomic primitive as
            # route_tasks' explicit completion/removal path after the stale-file check.
            route_tasks._atomic_write(self.ROADMAP_PATH, "".join(result))
        except OSError as exc:
            messagebox.showerror("Delete failed", str(exc))
            return False
        self._delete_undo = (before, list(result), title)
        self.undo_delete_button.configure(state="normal")
        self._load_tasks()
        # _load_tasks may normalize generated annotations; undo must compare against
        # the exact post-refresh file before restoring the saved snapshot.
        expected = self.ROADMAP_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
        self._delete_undo = (before, expected, title)
        return True

    def _on_undo_delete(self):
        if self._delete_undo is None:
            return
        before, expected, title = self._delete_undo
        try:
            current = self.ROADMAP_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            if current != expected:
                messagebox.showerror(
                    "Cannot undo delete",
                    "roadmap.md changed after the task was deleted. Undo refused to avoid "
                    "overwriting newer work.",
                )
                return
            route_tasks.write_roadmap(self.ROADMAP_PATH, expected, before)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("Undo failed", str(exc))
            return
        self._delete_undo = None
        self.undo_delete_button.configure(state="disabled")
        self._load_tasks()
        messagebox.showinfo("Delete undone", f"Restored task: {title}")

    def _on_mark_complete(self):
        """Human override for route_tasks.py's --complete: mark the checked/focused
        task(s) done and move them into shipped.md, gated behind an explicit warning
        since this removes content from the roadmap and can't be undone from here."""
        tasks = self._selected_tasks()
        if not tasks:
            messagebox.showinfo(
                "No task selected",
                "Check one or more tasks (or click a row) before marking complete.",
            )
            return

        titles = "\n".join(f"- {split_header(t.header)[1]}" for t in tasks)
        if not messagebox.askyesno(
            "Mark complete?",
            f"Mark {len(tasks)} task(s) as done and move them into {self.SHIPPED_PATH.name}?\n\n"
            f"{titles}\n\n"
            "This removes them from the active roadmap and cannot be undone from within "
            "Quest Board (you'd have to edit the files by hand to reverse it). Continue?",
        ):
            return

        shipped_lines = (
            self.SHIPPED_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            if self.SHIPPED_PATH.is_file()
            else []
        )
        roadmap_lines = list(self.roadmap_lines)
        # Remove back-to-front so each task's (start, end) indices — computed against
        # the original roadmap_lines — stay valid as earlier removals shift later lines.
        for t in sorted(tasks, key=lambda t: t.start, reverse=True):
            roadmap_lines, shipped_lines = route_tasks.move_to_shipped(
                roadmap_lines,
                shipped_lines,
                t.start,
                t.end,
            )

        # Write shipped.md first: a crash between the two writes leaves a recoverable
        # duplicate rather than deleting a task with nothing recorded in shipped.md.
        route_tasks._atomic_write(self.SHIPPED_PATH, "".join(shipped_lines))
        route_tasks._atomic_write(self.ROADMAP_PATH, "".join(roadmap_lines))
        self._load_tasks()

    # ── pack screen ──

    def _build_pack_frame(self):
        f = self.pack_frame

        topnav = ttk.Frame(f)
        topnav.pack(side="top", fill="x", pady=(0, 6))
        ttk.Button(topnav, text="← Back", command=self._on_back_to_picker).pack(side="left")
        ttk.Button(
            topnav, text="Configure & Send →", style="Accent.TButton", command=self._on_goto_send
        ).pack(side="right")

        # Bottom-anchored action row — packed (side="bottom") before the expandable
        # middle content below, so it always claims its space at the bottom of the
        # frame instead of being pushed off-screen when the paginated chunk view
        # (taller than the single pack_text box) is showing.
        btns = ttk.Frame(f)
        btns.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(btns, text="Copy to Clipboard", command=self._on_copy).pack(side="left")
        ttk.Button(btns, text="Save to Text", command=self._on_save).pack(side="left", padx=6)

        ttk.Label(
            f,
            text="Pack summary (selectable; model-facing task details are in the prompt):",
        ).pack(anchor="w")
        self.pack_summary_text = scrolledtext.ScrolledText(
            f, wrap="word", height=4, state="disabled", takefocus=True
        )
        self.pack_summary_text.pack(fill="x", pady=(2, 6))

        limit_row = ttk.Frame(f)
        limit_row.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(
            limit_row,
            text="Ignore char limit",
            variable=self.ignore_char_limit,
            command=self._refresh_pack_view,
        ).grid(row=0, column=0, sticky="nw")
        limit_row.columnconfigure(1, weight=1)
        self.limit_help = ttk.Label(
            limit_row,
            text=context_pack.IGNORE_CHAR_LIMIT_WARNING,
            foreground=gui_theme.COLOR_MUTED,
            justify="left",
        )
        self.limit_help.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        _wrap_with_parent(self.limit_help, limit_row, inset=150)

        delivery_row = ttk.Frame(f)
        delivery_row.pack(fill="x", pady=(0, 6))
        ttk.Label(delivery_row, text="Handoff:").pack(side="left")
        ttk.Radiobutton(
            delivery_row,
            text="Portable pack",
            value=PORTABLE_MODE,
            variable=self.delivery_mode,
        ).pack(side="left", padx=(6, 10))
        ttk.Radiobutton(
            delivery_row,
            text="Repository-aware (explicit)",
            value=REPOSITORY_MODE,
            variable=self.delivery_mode,
        ).pack(side="left")
        ttk.Combobox(
            delivery_row,
            textvariable=self.delivery_executor,
            values=("paid-ai", "codex", "claude"),
            state="readonly",
            width=10,
        ).pack(side="left", padx=6)

        # All three editable/readable regions share the remaining height. Expanded rows
        # receive equal space; collapsed rows retain only enough room for their header.
        self.pack_sections = ttk.Frame(f)
        self.pack_sections.pack(fill="both", expand=True)
        self.pack_sections.columnconfigure(0, weight=1)

        self.prompt_frame = ttk.Frame(self.pack_sections)
        self.prompt_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        self.prompt_header = ttk.Frame(self.prompt_frame)
        self.prompt_header.pack(fill="x")
        self.prompt_expanded = True
        self.prompt_toggle_btn = ttk.Button(
            self.prompt_header,
            text="▾  Prompt / task description (editable)",
            command=self._toggle_prompt_expanded,
        )
        self.prompt_toggle_btn.pack(side="left")
        self.prompt_body = ttk.Frame(self.prompt_frame, padding=(4, 4, 0, 0))
        self.prompt_body.pack(fill="both", expand=True)
        self.prompt_text = scrolledtext.ScrolledText(self.prompt_body, wrap="word", height=6)
        self.prompt_text.pack(fill="both", expand=True)

        self._build_inbox_section(self.pack_sections)

        self.context_frame = ttk.Frame(self.pack_sections)
        self.context_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
        self.context_header = ttk.Frame(self.context_frame)
        self.context_header.pack(fill="x")
        self.context_expanded = True
        self.context_toggle_btn = ttk.Button(
            self.context_header,
            text="▾  Context pack",
            command=self._toggle_context_expanded,
        )
        self.context_toggle_btn.pack(side="left")
        self.context_body = ttk.Frame(self.context_frame, padding=(4, 4, 0, 0))
        self.context_body.pack(fill="both", expand=True)

        # pack_text (checked / default) and chunk_frame (unchecked) occupy the same
        # spot in context_body — only one is packed at a time by _refresh_pack_view().
        self.pack_text = scrolledtext.ScrolledText(self.context_body, wrap="word", height=12)

        # Paginated view (docs/ai-harness.md §3.1) — one page at a time via large
        # Prev/Next, so a pack that would otherwise be a monster paste never lands in
        # the box unannounced. Independent of prompt_text: Copy/Save below keep
        # working on the whole pack regardless of which view is showing.
        self.chunk_frame = ttk.Frame(self.context_body)
        self.chunk_frame.columnconfigure(0, weight=1)
        self.chunk_frame.rowconfigure(2, weight=1)
        self.chunk_help = ttk.Label(
            self.chunk_frame,
            text='Paged view — step through with Prev/Next below. Use "Copy This Chunk" / '
            '"Copy && Advance" to paste each page as its own chat message, in order, '
            "then the prompt as the closing message (docs/ai-harness.md §3.1):",
            justify="left",
        )
        self.chunk_help.grid(row=0, column=0, sticky="ew")
        _wrap_with_parent(self.chunk_help, self.chunk_frame)
        chunknav = ttk.Frame(self.chunk_frame)
        chunknav.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        chunknav.columnconfigure(1, weight=1)
        self.btn_chunk_prev = ttk.Button(
            chunknav, text="<< Prev", style="Big.TButton", command=self._on_prev_chunk
        )
        self.btn_chunk_prev.grid(row=0, column=0, sticky="w")
        self.chunk_label = ttk.Label(chunknav, text="", font=("", 11, "bold"))
        self.chunk_label.grid(row=0, column=1, padx=12)
        self.btn_chunk_next = ttk.Button(
            chunknav, text="Next >>", style="Big.TButton", command=self._on_next_chunk
        )
        self.btn_chunk_next.grid(row=0, column=2, sticky="e")
        chunk_actions = ttk.Frame(chunknav)
        chunk_actions.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(chunk_actions, text="Copy This Chunk", command=self._on_copy_chunk).pack(
            side="left"
        )
        ttk.Button(chunk_actions, text="Copy && Advance", command=self._on_copy_chunk_advance).pack(
            side="left", padx=6
        )
        self.chunk_preview = scrolledtext.ScrolledText(self.chunk_frame, wrap="word", height=12)
        self.chunk_preview.grid(row=2, column=0, sticky="nsew", pady=(8, 8))

        self._pack_compact = None
        f.bind("<Configure>", self._resize_pack_layout, add="+")
        self._update_pack_section_rows()

    def _resize_pack_layout(self, event):
        """Drop optional explanations before editors become unusably short."""
        compact = event.height < 620
        if compact == self._pack_compact:
            return
        self._pack_compact = compact
        self.pack_summary_text.configure(height=2 if compact else 4)
        optional_labels = (
            self.limit_help,
            self.chunk_help,
            self.inbox_status_label,
            self.inbox_help,
            self.filter_help,
        )
        for label in optional_labels:
            if compact:
                label.grid_remove()
            else:
                label.grid()

    def _toggle_prompt_expanded(self):
        self.prompt_expanded = not self.prompt_expanded
        if self.prompt_expanded:
            self.prompt_body.pack(fill="both", expand=True)
            self.prompt_toggle_btn.config(text="▾  Prompt / task description (editable)")
        else:
            self.prompt_body.pack_forget()
            self.prompt_toggle_btn.config(text="▸  Prompt / task description (editable)")
        self._update_pack_section_rows()

    def _toggle_context_expanded(self):
        self.context_expanded = not self.context_expanded
        if self.context_expanded:
            self.context_body.pack(fill="both", expand=True)
            self.context_toggle_btn.config(text="▾  Context pack")
        else:
            self.context_body.pack_forget()
            self.context_toggle_btn.config(text="▸  Context pack")
        self._update_pack_section_rows()

    def _update_pack_section_rows(self):
        """Share free height between expanded pack sections without clipping headers."""
        sections = (
            (0, self.prompt_expanded, 1, self.prompt_toggle_btn),
            (1, self.context_expanded, 1, self.context_toggle_btn),
            (
                2,
                self.inbox_expanded and len(self.current_tasks) == 1,
                3,
                self.inbox_toggle_btn
                if len(self.current_tasks) == 1
                else self.inbox_unavailable_label,
            ),
        )
        for row, expanded, expanded_weight, header_widget in sections:
            self.pack_sections.rowconfigure(
                row,
                weight=expanded_weight if expanded else 0,
                uniform="pack_section" if expanded else "",
                minsize=header_widget.winfo_reqheight(),
            )

    def _build_inbox_section(self, f):
        """Paste-back area for manually-collected AI chat responses (see the
        AI_INBOX_DIRNAME module comment). inbox_frame and inbox_unavailable_label occupy
        the same responsive grid slot -- _refresh_inbox_section() (called from _on_pack)
        shows exactly one, since paste-back only makes sense for a single task."""
        self.inbox_slot = ttk.Frame(f)
        self.inbox_slot.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        self.inbox_frame = ttk.Frame(self.inbox_slot)
        self.inbox_expanded = False

        ttk.Separator(self.inbox_frame, orient="horizontal").pack(fill="x", pady=(0, 6))
        self.inbox_header = ttk.Frame(self.inbox_frame)
        self.inbox_header.pack(fill="x")
        self.inbox_toggle_btn = ttk.Button(
            self.inbox_header,
            text="▸  AI response inbox",
            command=self._toggle_inbox_expanded,
        )
        self.inbox_toggle_btn.pack(side="left")

        self.inbox_body = ttk.Frame(self.inbox_frame, padding=(4, 6, 0, 0))
        self.inbox_body.columnconfigure(0, weight=1)
        self.inbox_body.rowconfigure(3, weight=1)

        self.inbox_status_label = ttk.Label(
            self.inbox_body, text="", foreground=gui_theme.COLOR_MUTED, justify="left"
        )
        self.inbox_status_label.grid(row=0, column=0, sticky="ew")
        _wrap_with_parent(self.inbox_status_label, self.inbox_body)

        self.inbox_help = ttk.Label(
            self.inbox_body,
            text="Paste a model response here; Save appends it to this task's inbox for "
            "the later fusion pass (docs/ai-harness.md §5).",
            justify="left",
        )
        self.inbox_help.grid(row=1, column=0, sticky="ew", pady=(2, 4))
        _wrap_with_parent(self.inbox_help, self.inbox_body)

        filter_row = ttk.Frame(self.inbox_body)
        filter_row.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        filter_row.columnconfigure(2, weight=1)
        ttk.Label(filter_row, text="Slop filter:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            filter_row,
            textvariable=self.slop_filter_mode,
            values=SLOP_FILTER_MODES,
            state="readonly",
            width=20,
        ).grid(row=0, column=1, sticky="w", padx=6)
        self.filter_help = ttk.Label(
            filter_row,
            text="Conservative trims excess blank lines and exact chat/UI boilerplate.",
            foreground=gui_theme.COLOR_MUTED,
            justify="left",
        )
        self.filter_help.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        _wrap_with_parent(self.filter_help, filter_row, inset=300)

        self.inbox_paste_text = scrolledtext.ScrolledText(self.inbox_body, wrap="word", height=6)
        self.inbox_paste_text.grid(row=3, column=0, sticky="nsew", pady=(0, 4))

        inbox_btns = ttk.Frame(self.inbox_body)
        inbox_btns.grid(row=4, column=0, sticky="ew")
        ttk.Button(
            inbox_btns,
            text="Paste from Clipboard",
            command=self._on_paste_from_clipboard,
        ).pack(side="left")
        ttk.Button(inbox_btns, text="Save to Inbox", command=self._on_save_to_inbox).pack(
            side="left", padx=6
        )
        ttk.Button(inbox_btns, text="Open Inbox Folder", command=self._on_open_inbox_folder).pack(
            side="left"
        )

        self.inbox_unavailable_label = ttk.Label(
            self.inbox_slot,
            text="Inbox paste-back is available when exactly one task is packed.",
            foreground=gui_theme.COLOR_MUTED,
            justify="left",
        )
        _wrap_with_parent(self.inbox_unavailable_label, self.inbox_slot)

    def _toggle_inbox_expanded(self):
        self.inbox_expanded = not self.inbox_expanded
        if self.inbox_expanded:
            self.inbox_body.pack(fill="both", expand=True)
            self.inbox_toggle_btn.config(text="▾  AI response inbox")
        else:
            self.inbox_body.pack_forget()
            self.inbox_toggle_btn.config(text="▸  AI response inbox")
        self._update_pack_section_rows()

    def _refresh_inbox_section(self):
        self.inbox_frame.pack_forget()
        self.inbox_unavailable_label.pack_forget()
        if len(self.current_tasks) == 1:
            self.inbox_paste_text.delete("1.0", "end")
            _, title = split_header(self.current_tasks[0].header)
            self._current_inbox_path = inbox_path(self.root_dir, title, self.current_tasks[0].id)
            self._refresh_inbox_status()
            self.inbox_frame.pack(fill="both", expand=True)
        else:
            self._current_inbox_path = None
            self.inbox_unavailable_label.pack(fill="x")
        self._update_pack_section_rows()

    def _refresh_inbox_status(self):
        if self._current_inbox_path is None:
            return
        rel = self._current_inbox_path.relative_to(self.root_dir).as_posix()
        n = count_inbox_responses(self._current_inbox_path)
        if n:
            text = f"{n} response{'s' if n != 1 else ''} already saved for this task ({rel})"
        else:
            text = f"No responses saved yet for this task — will be created at {rel}"
        self.inbox_status_label.config(text=text)

    def _on_paste_from_clipboard(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(
                "Clipboard unavailable",
                "The clipboard does not currently contain text to paste.",
            )
            return
        self.inbox_paste_text.delete("1.0", "end")
        self.inbox_paste_text.insert("1.0", text)

    def _on_save_to_inbox(self):
        if self._current_inbox_path is None:
            return
        text = self.inbox_paste_text.get("1.0", "end-1c")
        _, title = split_header(self.current_tasks[0].header)
        try:
            removed = append_inbox_response(
                self._current_inbox_path,
                title,
                text,
                filter_mode=self.slop_filter_mode.get(),
                task_id=self.current_tasks[0].id,
            )
        except ValueError as e:
            if "empty" in str(e):
                messagebox.showinfo(
                    "Nothing to save",
                    "Paste a response with content before saving. The selected filter may "
                    "have removed a boilerplate-only response.",
                )
            else:
                messagebox.showerror("Save failed", str(e))
            return
        except OSError as e:
            messagebox.showerror("Save failed", str(e))
            return
        self.inbox_paste_text.delete("1.0", "end")
        self._refresh_inbox_status()
        self._append_status(
            f"[saved response to inbox · {self.slop_filter_mode.get()} slop filter removed "
            f"{removed} chars]"
        )

    def _on_open_inbox_folder(self):
        if self._current_inbox_path is None:
            return
        folder = self._current_inbox_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 -- opening a local folder in Explorer
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)])
        else:
            subprocess.run(["xdg-open", str(folder)])

    def _on_pack(self):
        tasks = self._selected_tasks()
        if not tasks:
            messagebox.showinfo(
                "No task selected", "Check one or more tasks (or click a row) before packing."
            )
            return
        lifecycle_lines = list(self.roadmap_lines)
        if self.SHIPPED_PATH.is_file():
            lifecycle_lines.extend(
                self.SHIPPED_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            )
        advisories = task_order_advisories(tasks, task_statuses(lifecycle_lines))
        if advisories and not messagebox.askyesno(
            "Pack blocked work?",
            "Quest Board found unresolved blockers:\n\n"
            + "\n".join(f"- {advisory}" for advisory in advisories)
            + "\n\nThis warning is advisory. Pack the selected task(s) anyway?",
        ):
            return

        files = []
        seen = set()
        for t in tasks:
            for p in t.files:
                key = p.as_posix()
                if key not in seen:
                    seen.add(key)
                    files.append(p)

        raw_body, total_lines, per_file, bodies = context_pack.build_pack(
            files, self.root_dir, fence=True
        )
        compact_bodies = [compact_context_body(file_body) for file_body in bodies]
        body = "\n\n".join(compact_bodies)
        context_chars_removed = len(raw_body) - len(body)
        per_file = [
            (rel, lines, max(0, chars - (len(raw) - len(compact))))
            for (rel, lines, chars), raw, compact in zip(
                per_file, bodies, compact_bodies, strict=False
            )
        ]
        bodies = compact_bodies
        self.current_tasks = tasks
        self._refresh_inbox_section()

        self.pack_text.delete("1.0", "end")
        self.pack_text.insert("1.0", body)

        prompt_body = build_task_prompt(tasks)
        external_missing = []
        seen_external = set()
        for t in tasks:
            for m in t.missing:
                if route_tasks.external_ref_name(m) and m not in seen_external:
                    seen_external.add(m)
                    external_missing.append(m)
        if external_missing:
            lines = []
            for m in external_missing:
                hint = route_tasks.external_search_hint(m)
                if hint:
                    lines.append(f"- {m} — search: {hint}")
                else:
                    name = route_tasks.external_ref_name(m)
                    lines.append(
                        f"- {m} — unregistered reference `{name}`; search for it "
                        f"yourself, or add a hint to helper_scripts/external_refs.json"
                    )
            prompt_body += (
                "\n\nThe following referenced files are not bundled in the context pack above "
                "(no local clone configured on this machine). Search for them yourself before "
                "answering. If a lookup fails or isn't available, don't refuse the task — answer "
                "from what you already know and mark those specific claims [UNVERIFIED]:\n"
                + "\n".join(lines)
            )
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", prompt_body)

        # Always chunked, regardless of ignore_char_limit — that checkbox (on the pack
        # screen) only toggles which view is displayed; see _refresh_pack_view. Chunk size
        # is model-aware (_chunk_budget) so a tight-budget route (e.g. kimi) splits before
        # its own paste ceiling, not just the generic 100k mark.
        file_chunks = context_pack.chunk_bodies(bodies, _chunk_budget({t.route for t in tasks}))
        self.chunks = [
            context_pack.wrap_chunk(fc, i + 1, len(file_chunks)) for i, fc in enumerate(file_chunks)
        ]
        self._refresh_pack_view()

        self._set_pack_summary(
            self._status_text(tasks, per_file, total_lines, len(body), context_chars_removed),
            self._fit_text(per_file, len(body)),
        )
        portable_chars = len(f"{prompt_body}\n\n---\n\n{body}")
        compact_chars = len(build_repository_handoff(tasks, self.delivery_executor.get()))
        self._append_status(
            f"[full portable load {portable_chars:,} chars · repository-aware "
            f"transmission {compact_chars:,} chars]"
        )
        self.picker_frame.pack_forget()
        self.pack_frame.pack(fill="both", expand=True)

    def _status_text(self, tasks, per_file, total_lines, n_chars, context_chars_removed=0):
        classes = sorted({t.task_class for t in tasks})
        routes = sorted({t.route for t in tasks})
        title = tasks[0].header if len(tasks) == 1 else f"{len(tasks)} tasks"
        parts = [
            f"{title} · Class {'/'.join(classes)} · routed to {'/'.join(routes)} · "
            f"{len(per_file)} files, {total_lines} lines, {n_chars} chars"
        ]
        parts.append(
            f"[context filter removed {context_chars_removed:,} repeated empty-line "
            f"character{'s' if context_chars_removed != 1 else ''}]"
        )
        if any(r.lower().startswith("me") for r in routes):
            parts.append("[human-routed — pack for maintainer context only]")
        if not per_file:
            parts.append(
                "[warning: no resolvable file paths in selected task(s) — packing prompt only, no file context]"
            )
        missing = [m for t in tasks for m in t.missing]
        # `<name>` external-reference entries are a distinct case from genuine new/placeholder
        # paths: they're not missing because they don't exist yet, but because no local clone
        # is configured for that name (route_tasks.EXTERNAL_REF_PATHS_FILE) — say so, or "not
        # on disk yet" reads as if these files were supposed to be created by this task.
        external_missing = [m for m in missing if route_tasks.external_ref_name(m)]
        other_missing = [m for m in missing if not route_tasks.external_ref_name(m)]
        if external_missing:
            parts.append(
                f"[{len(external_missing)} external reference file(s) not bundled — search "
                f"hints included in the prompt below for the AI to find them itself; or add a "
                f"local clone path to helper_scripts/external_ref_paths.txt to bundle them instead]"
            )
        if other_missing:
            shown = ", ".join(other_missing[:3])
            more = "..." if len(other_missing) > 3 else ""
            parts.append(
                f"[{len(other_missing)} listed path(s) not on disk yet (new/placeholder), excluded: {shown}{more}]"
            )
        for route in routes:
            budget = context_pack.MODEL_BUDGETS.get(route)
            if budget and budget["files"] == 0:
                parts.append(
                    f"[{route} takes no file uploads — paste the pack text directly into chat]"
                )
            if route in context_pack.MODEL_BUDGETS:
                label, detail = context_pack.model_fitness(per_file, n_chars)[route]
                if label != "fits":
                    parts.append(f"[WARNING: routed model {route} — {detail}]")
        if "3" in classes:
            parts.append(
                "[CLASS 3 — safety-critical: model output is research only, never applied without author review]"
            )
        # One clause per line (was a "  "-joined run-on) — a title line followed by a
        # stack of bracketed warnings reads as a short list, not a wall of text.
        return "\n".join(parts)

    def _fit_text(self, per_file, n_chars):
        """One label per model in MODEL_BUDGETS, so a model that's outright unusable for this
        exact pack (e.g. chatgpt when a single file alone exceeds its char budget) is visible
        at a glance, not just the one model route_tasks.py happened to route this task to."""
        tags = {"fits": "OK", "trim": "TRIM", "not viable": "NOT VIABLE"}
        parts = []
        for model, (label, detail) in context_pack.model_fitness(per_file, n_chars).items():
            tag = tags[label]
            parts.append(f"{model}: {tag}" + (f" ({detail})" if detail else ""))
        return "Model fit — " + " · ".join(parts)

    @staticmethod
    def _replace_read_only_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _set_pack_summary(self, status, fit):
        self._replace_read_only_text(self.pack_summary_text, f"{status}\n{fit}")

    def _append_status(self, extra):
        current = self.pack_summary_text.get("1.0", "end-1c")
        self._replace_read_only_text(self.pack_summary_text, f"{current}\n{extra}")

    def _on_back_to_picker(self):
        self.pack_frame.pack_forget()
        self.picker_frame.pack(fill="both", expand=True)

    def _refresh_pack_view(self):
        """Toggle the widget shown inside the independently-collapsible context pane."""
        if self.ignore_char_limit.get():
            self.limit_help.configure(text=context_pack.IGNORE_CHAR_LIMIT_WARNING)
            self.chunk_frame.pack_forget()
            self.pack_text.pack(fill="both", expand=True)
        else:
            self.limit_help.configure(
                text="Paged chunks stay within the routed model's known inline-paste budget."
            )
            self.pack_text.pack_forget()
            self.chunk_frame.pack(fill="both", expand=True)
            self._show_chunk(0)

    def _show_chunk(self, idx):
        self.chunk_idx = idx
        total = len(self.chunks)
        self.chunk_preview.delete("1.0", "end")
        if total == 0:
            self.chunk_preview.insert("1.0", "(no file content — prompt only)")
            self.chunk_label.config(text="No chunks")
            self.btn_chunk_prev.state(["disabled"])
            self.btn_chunk_next.state(["disabled"])
            return
        self.chunk_preview.insert("1.0", self.chunks[idx])
        self.chunk_label.config(text=f"Chunk {idx + 1} of {total}")
        self.btn_chunk_prev.state(["disabled"] if idx == 0 else ["!disabled"])
        self.btn_chunk_next.state(["disabled"] if idx == total - 1 else ["!disabled"])

    def _on_prev_chunk(self):
        if self.chunk_idx > 0:
            self._show_chunk(self.chunk_idx - 1)

    def _on_next_chunk(self):
        if self.chunk_idx < len(self.chunks) - 1:
            self._show_chunk(self.chunk_idx + 1)

    def _on_copy_chunk(self):
        if not self.chunks:
            return
        self.clipboard_clear()
        self.clipboard_append(self.chunks[self.chunk_idx])
        self._append_status(f"[copied chunk {self.chunk_idx + 1} of {len(self.chunks)}]")

    def _on_copy_chunk_advance(self):
        self._on_copy_chunk()
        if self.chunk_idx < len(self.chunks) - 1:
            self._show_chunk(self.chunk_idx + 1)

    def _combined_text(self, executor_id=None):
        """Prompt plus whichever pack view is currently active — the full concatenated
        block when ignore_char_limit is checked, or just the on-screen chunk when it's
        not, so Copy/Save actually track what pagination is showing instead of always
        grabbing the whole pack behind the paginated view's back."""
        prompt = self.prompt_text.get("1.0", "end").strip()
        if self.ignore_char_limit.get():
            pack = self.pack_text.get("1.0", "end").strip()
        else:
            pack = self.chunks[self.chunk_idx].strip() if self.chunks else ""
        portable = (prompt + "\n\n---\n\n" + pack) if prompt else pack
        return select_handoff(
            self.current_tasks,
            portable,
            executor_id or self.delivery_executor.get(),
            self.delivery_mode.get(),
        )[0]

    def _on_copy(self):
        text = self._combined_text()
        self.clipboard_clear()
        self.clipboard_append(text)
        if self.ignore_char_limit.get() and len(text) > context_pack.DEFAULT_MAX_CHARS:
            self._append_status(
                f"[copied {len(text):,} chars to clipboard — the clipboard is complete, "
                "but the destination may truncate a paste this large; use Save to Text "
                "and upload it, or uncheck Ignore char limit to copy chunks]"
            )
        else:
            self._append_status(f"[copied {len(text):,} chars to clipboard]")

    def _on_save(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile="scratch.txt",
            initialdir=str(self.root_dir),
        )
        if not path:
            return
        Path(path).write_text(self._combined_text(), encoding="utf-8")
        self._append_status(f"[saved to {path}]")

    def _poll_result(self):
        try:
            status, payload = self.result_queue.get_nowait()
        except queue.Empty:
            self.after(200, self._poll_result)
            return
        self.btn_send.state(["!disabled"])
        if status == "error":
            self.send_status_label.config(text="[send failed]")
            messagebox.showerror("Send failed", payload)
            return
        self.send_status_label.config(text="[response received]")
        self._show_response(payload)

    def _show_response(self, text):
        win = tk.Toplevel(self)
        win.title("Model response")
        win.geometry("820x640")  # initial size only
        win.resizable(True, True)

        def copy():
            self.clipboard_clear()
            self.clipboard_append(text)

        def save():
            path = filedialog.asksaveasfilename(defaultextension=".md", initialfile="response.md")
            if path:
                Path(path).write_text(text, encoding="utf-8")

        btns = ttk.Frame(win)
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="Copy", command=copy).pack(side="left", padx=6, pady=6)
        ttk.Button(btns, text="Save", command=save).pack(side="left")
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right", padx=6)

        box = scrolledtext.ScrolledText(win, wrap="word")
        box.pack(fill="both", expand=True)
        box.insert("1.0", text)

    # ── send / settings screen ──

    @staticmethod
    def _default_endpoint(target):
        if target == "qwen":
            return os.environ.get("QWEN_LM_STUDIO_URL", "http://localhost:1234/v1").rstrip("/")
        return "https://openrouter.ai/api/v1"

    @staticmethod
    def _mask_key(key):
        if not key:
            return "(none set)"
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}...{key[-4:]}"

    def _on_goto_send(self):
        self.pack_frame.pack_forget()
        self.send_frame.pack(fill="both", expand=True)
        self._refresh_send_preview()

    def _on_back_from_send(self):
        self.send_frame.pack_forget()
        self.pack_frame.pack(fill="both", expand=True)

    def _build_send_frame(self):
        f = self.send_frame

        topnav = ttk.Frame(f)
        topnav.pack(side="top", fill="x", pady=(0, 6))
        ttk.Button(topnav, text="← Back", command=self._on_back_from_send).pack(side="left")

        bottom = ttk.Frame(f)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        # Right-aligned to match this wizard's other primary "move forward" actions
        # (Pack ->, Configure & Send -> are both right-aligned in their topnav).
        self.btn_send = ttk.Button(
            bottom, text="Send", style="Accent.TButton", command=self._on_send_from_settings
        )
        self.btn_send.pack(side="right")
        self.send_status_label = ttk.Label(bottom, text="", foreground=gui_theme.COLOR_MUTED)
        self.send_status_label.pack(side="right", padx=12)

        send_heading = ttk.Label(
            f,
            text="Where this pack gets sent, and what it'll look like on the wire:",
            font=("", 11, "bold"),
            justify="left",
        )
        send_heading.pack(fill="x", pady=(0, 6))
        _wrap_with_parent(send_heading, f)

        settings = ttk.Frame(f)
        settings.pack(fill="x", pady=(0, 6))
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="Send target:").grid(row=0, column=0, sticky="nw", pady=(0, 6))
        target_choices = ttk.Frame(settings)
        target_choices.grid(row=0, column=1, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Radiobutton(
            target_choices,
            text="Qwen (local LM Studio)",
            value="qwen",
            variable=self.send_target,
            command=self._on_target_changed,
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Radiobutton(
            target_choices,
            text="OpenRouter (cloud)",
            value="openrouter",
            variable=self.send_target,
            command=self._on_target_changed,
        ).grid(row=0, column=1, sticky="w")

        ttk.Label(settings, text="Endpoint URL:").grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.endpoint_entry = ttk.Entry(settings, textvariable=self.send_endpoint)
        self.endpoint_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=(0, 6))
        ttk.Button(settings, text="Reset to default", command=self._reset_endpoint).grid(
            row=1, column=2, sticky="e", pady=(0, 6)
        )

        self.model_row = ttk.Frame(settings)
        self.model_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        ttk.Label(settings, text="OpenRouter API key:").grid(
            row=3, column=0, sticky="w", pady=(0, 6)
        )
        self.api_key_entry = ttk.Entry(settings, textvariable=self.send_api_key, show="*")
        self.api_key_entry.grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(0, 6)
        )
        self.remember_check = ttk.Checkbutton(
            settings,
            text="Remember on this machine",
            variable=self.remember_key,
            command=self._on_remember_toggled,
        )
        self.remember_check.grid(row=4, column=1, columnspan=2, sticky="w", padx=(6, 0))
        self.remember_help = ttk.Label(
            settings,
            text=f"Stores plaintext {OPENROUTER_KEY_FILE.name} in the home directory.",
            foreground=gui_theme.COLOR_MUTED,
            justify="left",
        )
        self.remember_help.grid(
            row=5, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(0, 6)
        )
        _wrap_with_parent(self.remember_help, settings, inset=140)

        ttk.Label(settings, text="Max tokens:").grid(row=6, column=0, sticky="w")
        self.max_tokens_entry = ttk.Entry(settings, textvariable=self.send_max_tokens, width=8)
        self.max_tokens_entry.grid(row=6, column=1, sticky="w", padx=6)

        ttk.Button(f, text="Refresh Preview", command=self._refresh_send_preview).pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(f, text="Request preview (API key masked):").pack(anchor="w")
        self.send_preview = scrolledtext.ScrolledText(f, wrap="word", height=18, state="disabled")
        self.send_preview.pack(fill="both", expand=True, pady=(2, 0))

        self._send_compact = None
        f.bind("<Configure>", self._resize_send_layout, add="+")
        self._on_target_changed()

    def _resize_send_layout(self, event):
        """Preserve preview height in short windows by hiding optional key-storage prose."""
        compact = event.height < 620
        if compact == self._send_compact:
            return
        self._send_compact = compact
        if compact:
            self.remember_help.grid_remove()
        else:
            self.remember_help.grid()

    def _build_model_row(self):
        """Rebuilds model_row's contents for the current target — a free-text combobox
        for openrouter, or a read-only detected value + Detect button for qwen, whose
        model comes from LM Studio's /v1/models rather than being chosen here."""
        for child in self.model_row.winfo_children():
            child.destroy()
        self.model_row.columnconfigure(1, weight=1)
        ttk.Label(self.model_row, text="Model:").grid(row=0, column=0, sticky="w")
        if self.send_target.get() == "openrouter":
            ttk.Combobox(
                self.model_row,
                textvariable=self.send_model_or,
                values=self.openrouter_models,
            ).grid(row=0, column=1, sticky="ew", padx=6)
            ttk.Button(
                self.model_row,
                text="Fetch free models",
                command=self._fetch_openrouter_models,
            ).grid(row=0, column=2, sticky="e")
        else:
            label = self.qwen_detected_model or "(auto-detected at send time)"
            ttk.Label(self.model_row, text=label, foreground=gui_theme.COLOR_MUTED).grid(
                row=0, column=1, sticky="w", padx=6
            )
            ttk.Button(self.model_row, text="Detect Now", command=self._detect_qwen_model).grid(
                row=0, column=2, sticky="e"
            )

    def _reset_endpoint(self):
        self.send_endpoint.set(self._default_endpoint(self.send_target.get()))
        self._refresh_send_preview()

    def _on_target_changed(self):
        target = self.send_target.get()
        # Only auto-swap the endpoint if it still holds a known default (i.e. the user
        # hasn't customized it) — don't clobber a deliberately edited URL.
        known_defaults = {self._default_endpoint("qwen"), self._default_endpoint("openrouter")}
        if self.send_endpoint.get() in known_defaults:
            self.send_endpoint.set(self._default_endpoint(target))
        self.api_key_entry.state(["!disabled"] if target == "openrouter" else ["disabled"])
        self.remember_check.state(["!disabled"] if target == "openrouter" else ["disabled"])
        self._build_model_row()
        self._refresh_send_preview()

    def _detect_qwen_model(self):
        base_url = self.send_endpoint.get().strip().rstrip("/")
        try:
            self.qwen_detected_model = query_model._lm_studio_model(base_url)
        except RuntimeError as e:
            messagebox.showerror("Detect failed", str(e))
            return
        self._build_model_row()
        self._refresh_send_preview()

    def _fetch_openrouter_models(self):
        """Pull the live list of ':free' OpenRouter models and repopulate the combobox,
        so the hardcoded OPENROUTER_MODELS seed never has to be hand-verified. Mirrors
        _detect_qwen_model — no API key required (the models endpoint is public)."""
        base_url = self.send_endpoint.get().strip().rstrip("/")
        api_key = self.send_api_key.get().strip()
        try:
            models = query_model._openrouter_free_models(base_url, api_key or None)
        except RuntimeError as e:
            messagebox.showerror("Fetch failed", str(e))
            return
        if not models:
            messagebox.showinfo(
                "No free models", "OpenRouter returned no ':free' models right now."
            )
            return
        self.openrouter_models = models
        if self.send_model_or.get() not in models:
            self.send_model_or.set(models[0])
        self._build_model_row()
        self._refresh_send_preview()
        self.send_status_label.config(text=f"[fetched {len(models)} free model(s)]")

    def _current_send_settings(self):
        """(target, base_url, model_id_or_placeholder, api_key, max_tokens) from the
        settings screen's current field values."""
        target = self.send_target.get()
        base_url = self.send_endpoint.get().strip().rstrip("/")
        if target == "qwen":
            model_id = self.qwen_detected_model or "(auto-detected at send time)"
        else:
            model_id = self.send_model_or.get().strip()
        api_key = self.send_api_key.get().strip()
        try:
            max_tokens = int(self.send_max_tokens.get().strip())
        except ValueError:
            max_tokens = 4096
        return target, base_url, model_id, api_key, max_tokens

    def _build_request_payload(self, model_id, max_tokens):
        # Reuses _combined_text() so the request sent/previewed here is exactly what the
        # pack screen (page 2) shows and lets you Copy/Save — including which chunk is on
        # screen when the paginated view is active, not always the full unpaginated pack.
        # Programmatic targets are not repository-aware; an explicit compact selection
        # therefore falls back to the complete portable payload for these sends.
        user_msg = self._combined_text(self.send_target.get())
        return user_msg, {
            "model": model_id,
            "messages": [
                {"role": "system", "content": query_model._SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }

    def _refresh_send_preview(self):
        target, base_url, model_id, api_key, max_tokens = self._current_send_settings()
        _, payload = self._build_request_payload(model_id, max_tokens)
        headers = {"Content-Type": "application/json"}
        if target == "openrouter":
            headers["Authorization"] = f"Bearer {self._mask_key(api_key)}"
        preview = {"url": f"{base_url}/chat/completions", "headers": headers, "body": payload}
        text = json.dumps(preview, indent=2)
        self.send_preview.configure(state="normal")
        self.send_preview.delete("1.0", "end")
        self.send_preview.insert("1.0", text)
        self.send_preview.configure(state="disabled")

    def _on_remember_toggled(self):
        """Opt-in key persistence. Checked -> save the current key to the home-dir file;
        unchecked -> delete any saved copy. The file lives outside the repo so a plaintext
        secret can't be committed; it's still plaintext on disk, hence off by default."""
        if self.remember_key.get():
            key = self.send_api_key.get().strip()
            if key:
                _save_key(key)
        else:
            _forget_saved_key()

    def _on_send_from_settings(self):
        if any(t.task_class == "3" for t in self.current_tasks) and not messagebox.askyesno(
            "Class 3 task",
            "This is a Class 3 (top review tier) task. Per this project's CLAUDE.md, no "
            "free-tier model output may be applied to Class 3 code without author review "
            "and any checklist that tier requires — this send is for read-only research "
            "only. Continue?",
        ):
            return
        if any(t.route.lower().startswith("me") for t in self.current_tasks):
            messagebox.showinfo("Human-routed task", "Sending this to a model probably won't work.")
            return

        target, base_url, model_id, api_key, max_tokens = self._current_send_settings()
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning(
                "No prompt", "Write a task description in the prompt box before sending."
            )
            return
        if target == "openrouter" and not api_key:
            messagebox.showwarning("No API key", "Enter an OpenRouter API key before sending.")
            return
        # Keep the saved copy current with whatever's in the field now, if the user opted
        # to remember it (they may have typed or edited the key after ticking the box).
        if target == "openrouter" and self.remember_key.get() and api_key:
            _save_key(api_key)

        self.btn_send.state(["disabled"])
        self.send_status_label.config(text=f"sending to {model_id} ...")

        def worker():
            try:
                if target == "qwen":
                    resolved_model = query_model._lm_studio_model(base_url)
                    headers = {}
                else:
                    resolved_model = model_id
                    headers = {"Authorization": f"Bearer {api_key}"}
                user_msg, _ = self._build_request_payload(resolved_model, max_tokens)
                resp = query_model._chat(
                    base_url, resolved_model, headers, query_model._SYSTEM, user_msg, max_tokens
                )
                self.result_queue.put(("ok", resp))
            except Exception as e:  # noqa: BLE001 - message goes to the user; traceback goes to the console
                traceback.print_exc()
                self.result_queue.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(200, self._poll_result)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
