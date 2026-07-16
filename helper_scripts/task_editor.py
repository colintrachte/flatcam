"""
task_editor.py — Quest Board task editing mechanics and diff-gated Tk dialogs.

The pure helpers build candidate roadmap content without writing. The dialog's
apply boundary delegates the guarded atomic write to route_tasks.write_roadmap().
"""

import difflib
import re
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
from typing import TYPE_CHECKING

import gui_theme
import route_tasks
from task_records import (
    CHARS_VALUE_RE,
    FENCE_END_RE,
    FENCE_START_RE,
    FILE_LIST_RE,
    HEADER_ATTR_RE,
    HEADER_RE,
    ROUTE_VALUE_RE,
    SECTION_RE,
    Task,
)

if TYPE_CHECKING:
    from pack_task import App


def _wrap_with_parent(label, parent, inset=0):
    """Keep a label's wrap length aligned with the width its parent actually receives."""

    def resize(event):
        label.configure(wraplength=max(120, event.width - inset))

    parent.bind("<Configure>", resize, add="+")


# ── task editor: pure parse/build/splice helpers (no Tkinter) ──
#
# These back TaskEditorDialog's Save path. Kept free of Tkinter so they're unit-testable
# headlessly (see tests/test_task_editor.py) -- this repo's own REVIEW_TIERS.md Class 3
# rule for any docs/roadmap.md write path requires a round-trip test, and a function tied
# to live widgets can't be driven without a display.

FILE_FIELD_LABELS = ("Implement", "Context", "Write", "Read", "Evidence")
FILE_FIELD_DISPLAY = {
    "Implement": "Mutable",
    "Context": "Input",
    "Write": "Output",
    "Read": "Input (additional)",
    "Evidence": "Evidence",
}
_LABEL_CANON = {label.lower(): label for label in FILE_FIELD_LABELS}
# A file-list line using a parenthetical suffix, e.g. "**Implement (Class 3 — ...):**"
# (see ROADMAP.template.md's format convention) -- a real, exercised case this editor's
# flat per-label model can't preserve; parse_task_fields() flags it so the dialog can warn
# instead of silently dropping the annotation on save.
FIELD_SUFFIX_RE = re.compile(
    r"^\s+\*\*(?:Implement|Write|Context|Read|Evidence)\s*\(", re.IGNORECASE
)
MANUAL_ROUTE_SUFFIX_RE = re.compile(r"^(.*?)\s*\(manual\)\s*$")
SECTION_BOUNDARY_RE = re.compile(r"^#{2,4}\s|^---\s*$")
TEXT_FIELD_RE = re.compile(
    r"^\s+\*\*(Outcome|Rationale|Acceptance|Expected evidence|Execution mode|Execution size|Uncertainty|"
    r"Capability|Constraint|Dependency|Blocked by|Parent|Supersedes|Related):\*\*\s*(.*)$",
    re.IGNORECASE,
)
TEXT_FIELD_KEYS = {
    "outcome": "outcome",
    "rationale": "rationale",
    "acceptance": "acceptance_conditions",
    "expected evidence": "acceptance_evidence",
    "execution mode": "execution_mode",
    "execution size": "execution_size",
    "uncertainty": "uncertainty",
    "capability": "capabilities",
    "constraint": "constraints",
    "dependency": "dependencies",
    "blocked by": "dependencies",
    "parent": "parents",
    "supersedes": "supersedes",
    "related": "related",
}
LIST_TASK_FIELDS = {
    "acceptance_conditions",
    "acceptance_evidence",
    "capabilities",
    "constraints",
    "dependencies",
    "parents",
    "supersedes",
    "related",
}


def parse_task_fields(block_lines: list[str]) -> dict:
    """Parse a task block (header line first, e.g. roadmap_lines[task.start:task.end])
    into an editable field-dict -- the inverse of build_task_lines(). Unlike
    parse_tasks()/Task.files, file-list values are kept as raw backtick strings bucketed
    per label rather than resolved Paths, since **Write:** targets and `<name>/...`
    external refs often don't exist on disk yet and still need to round-trip through the
    editor. Returns {score, task_class, title, body, is_fenced, file_fields, manual_route,
    has_field_suffix} -- callers fill in "section" themselves (Task.section, not
    derivable from the block alone)."""
    header_m = HEADER_RE.match(block_lines[0])
    attr_m = HEADER_ATTR_RE.match(header_m.group(2)) if header_m else None
    class_m = route_tasks.CLASS_RE.search(block_lines[0])

    file_fields = {label: [] for label in FILE_FIELD_LABELS}
    task_id = None
    status = None
    logical = {
        "outcome": "",
        "rationale": "",
        "acceptance_conditions": [],
        "acceptance_evidence": [],
        "execution_mode": "",
        "execution_size": "",
        "uncertainty": "",
        "capabilities": [],
        "constraints": [],
        "dependencies": [],
        "parents": [],
        "supersedes": [],
        "related": [],
    }
    manual_route = None
    has_field_suffix = False
    in_fence = False
    fence_lines = []
    body_lines = []

    for bl in block_lines[1:]:
        idm = route_tasks.ID_RE.match(bl)
        if idm:
            task_id = idm.group(1)
            continue
        statusm = route_tasks.STATUS_RE.match(bl)
        if statusm:
            status = route_tasks.task_status_of([bl])
            continue
        tm = TEXT_FIELD_RE.match(bl)
        if tm:
            key = TEXT_FIELD_KEYS[tm.group(1).lower()]
            value = tm.group(2).strip()
            if key in LIST_TASK_FIELDS:
                logical[key].append(value)
            else:
                logical[key] = value
            continue
        rm = ROUTE_VALUE_RE.match(bl)
        if rm:
            mm = MANUAL_ROUTE_SUFFIX_RE.match(rm.group(1))
            if mm and rm.group(1).endswith("(manual)"):
                manual_route = mm.group(1).strip()
            continue
        if (
            route_tasks.EFFORT_RE.match(bl)
            or route_tasks.CONTEXT_LOAD_RE.match(bl)
            or CHARS_VALUE_RE.match(bl)
        ):
            continue
        fm = FILE_LIST_RE.match(bl)
        if fm:
            if FIELD_SUFFIX_RE.match(bl):
                has_field_suffix = True
            label = _LABEL_CANON[fm.group(1).lower()]
            file_fields[label].extend(route_tasks.BACKTICK_RE.findall(fm.group(2)))
            continue
        if FENCE_START_RE.match(bl):
            in_fence = True
            continue
        if in_fence and FENCE_END_RE.match(bl):
            in_fence = False
            continue
        if in_fence:
            fence_lines.append(bl)
        else:
            body_lines.append(bl)

    fenced_body = "".join(fence_lines).strip()
    is_fenced = bool(fenced_body)
    if is_fenced:
        body = fenced_body
    else:
        # header_tail mirrors parse_tasks()'s own fallback (see its comment above) --
        # build_task_lines() never emits one, so on a round-trip this is always "".
        header_tail = block_lines[0][header_m.end() :].strip(" \t\n-—") if header_m else ""
        desc = "".join(body_lines).strip()
        body = f"{header_tail} {desc}".strip() if header_tail else desc

    return {
        "score": attr_m.group("score") if attr_m else "",
        "task_class": class_m.group(1) if class_m else "",
        "title": (attr_m.group("title") if attr_m else header_m.group(2) if header_m else ""),
        "body": body,
        "is_fenced": is_fenced,
        "file_fields": file_fields,
        "manual_route": manual_route,
        "has_field_suffix": has_field_suffix,
        "id": task_id,
        "status": status,
        **logical,
    }


def build_task_lines(fields: dict) -> list[str]:
    """Render a field-dict (see parse_task_fields()) into a well-formed task block ending
    in exactly one blank line. Never emits Context Load/Chars, and emits Route only when
    a manual override is set -- those stay generated, left to the App's
    refresh_routes()/_load_tasks() pipeline on the next reload.

    Known simplification: hand-authored items in this repo's own docs/roadmap.md often
    keep the description as an inline continuation of the header line; this always emits
    it as a separate paragraph instead. parse_tasks() concatenates header_tail + body
    either way, so this is cosmetic re-wrapping on save, not a semantic change."""
    medal = route_tasks._medal(fields["score"])
    lines = [
        f"- [ ] **Score {fields['score']} {medal} · Class {fields['task_class']} "
        f"— {fields['title']}**\n",
    ]
    if fields.get("id"):
        lines.append(f"  **ID:** {fields['id']}\n")
    if fields.get("status"):
        lines.append(f"  **Status:** {fields['status']}\n")
    for label, key in (("Outcome", "outcome"), ("Rationale", "rationale")):
        if fields.get(key):
            lines.append(f"  **{label}:** {fields[key].strip()}\n")
    for label, key in (
        ("Acceptance", "acceptance_conditions"),
        ("Expected evidence", "acceptance_evidence"),
    ):
        for value in fields.get(key, []):
            if value.strip():
                lines.append(f"  **{label}:** {value.strip()}\n")
    if fields.get("execution_mode"):
        lines.append(f"  **Execution mode:** {fields['execution_mode'].strip()}\n")
    if fields.get("execution_size"):
        lines.append(f"  **Execution size:** {fields['execution_size'].strip()}\n")
    if fields.get("uncertainty"):
        lines.append(f"  **Uncertainty:** {fields['uncertainty'].strip()}\n")
    for label, key in (
        ("Capability", "capabilities"),
        ("Constraint", "constraints"),
        ("Blocked by", "dependencies"),
        ("Parent", "parents"),
        ("Supersedes", "supersedes"),
        ("Related", "related"),
    ):
        for value in fields.get(key, []):
            if value.strip():
                lines.append(f"  **{label}:** {value.strip()}\n")
    lines.append("\n")

    for label in FILE_FIELD_LABELS:
        paths = fields["file_fields"].get(label) or []
        if paths:
            joined = " · ".join(f"`{p}`" for p in paths)
            lines.append(f"  **{label}:** {joined}\n")
    if fields.get("manual_route"):
        lines.append(f"  **Route:** {fields['manual_route']} (manual)\n")

    body = (fields.get("body") or "").strip()
    if body:
        lines.append("\n")
        if fields.get("is_fenced"):
            lines.append("  ```text\n")
            for bline in body.splitlines():
                lines.append(f"  {bline}\n" if bline else "\n")
            lines.append("  ```\n")
        else:
            for bline in body.splitlines():
                lines.append(f"  {bline}\n" if bline else "\n")
    lines.append("\n")
    return lines


def validate_task_fields(fields: dict, existing_ids: set[str] | None = None) -> str | None:
    """Save-button validation, per ROADMAP.template.md's format convention. Returns the
    first violation's user-facing message, or None if the fields are savable."""
    if not fields.get("title", "").strip():
        return "Title cannot be empty."
    if fields.get("score") not in {"1", "2", "3", "4", "5"}:
        return "Score must be 1-5."
    if fields.get("task_class") not in {"1", "2", "3"}:
        return "Class must be 1-3."
    if not fields.get("section", "").strip():
        return "Choose a section to file this task under."
    task_id = fields.get("id")
    if task_id and not route_tasks.TASK_ID_RE.fullmatch(task_id):
        return "ID must be task_ followed by 32 lowercase hexadecimal characters."
    if task_id and existing_ids is not None and task_id in existing_ids:
        return f"Task ID {task_id} already exists."
    status = fields.get("status")
    if status and status not in route_tasks.LIFECYCLE_STATUSES:
        return "Status is not a supported lifecycle value."
    if status == "Shipped":
        return "Use Mark Complete to move a task into Shipped history."
    for relationship_field in ("dependencies", "parents", "supersedes", "related"):
        for reference in fields.get(relationship_field, []):
            if not route_tasks.TASK_ID_RE.fullmatch(reference):
                label = relationship_field.replace("_", " ").title()
                return f"{label} reference {reference!r} is invalid."
            if reference == task_id:
                return f"A task cannot reference itself in {relationship_field.replace('_', ' ')}."
    if not any(fields.get("file_fields", {}).get(label) for label in FILE_FIELD_LABELS):
        return "At least one file path is required (Implement/Context/Write/Read)."
    return None


def readiness_diagnostics(fields: dict, root: Path, task_status_map: dict[str, str] | None = None):
    """Return every readiness gap. Drafts may be saved with gaps; Ready may not."""
    gaps = []
    if not fields.get("outcome", "").strip():
        gaps.append("Outcome is required before Ready.")
    if not any(value.strip() for value in fields.get("acceptance_conditions", [])):
        gaps.append("At least one acceptance condition is required before Ready.")
    if not any(value.strip() for value in fields.get("acceptance_evidence", [])):
        gaps.append("Expected acceptance evidence is required before Ready.")
    for label in ("Implement", "Context", "Read"):
        for ref in fields.get("file_fields", {}).get(label, []):
            files, missing = route_tasks.resolve_file_list(f"`{ref}`", root)
            if not files and missing:
                gaps.append(
                    f"Required {FILE_FIELD_DISPLAY[label].lower()} artifact is unresolved: {ref}"
                )
    if fields.get("status") == "Blocked":
        gaps.append("A Blocked task cannot be Ready.")
    if task_status_map is not None:
        for dependency in fields.get("dependencies", []):
            dep_status = task_status_map.get(dependency)
            if dep_status is None:
                gaps.append(f"Dependency does not resolve: {dependency}")
            elif dep_status != "Shipped":
                gaps.append(f"Dependency is not Shipped: {dependency} ({dep_status})")
    return gaps


def derive_task_readiness(
    tasks: list[Task], lines: list[str], root: Path, status_map: dict[str, str]
) -> None:
    """Attach the editor's mechanical readiness diagnostics to parsed tasks.

    The result is display/filter state only. Authored status and relationship fields remain
    untouched, so Quest Board can explain an inconsistency without silently rewriting it.
    """
    for task in tasks:
        if not task.status:
            task.readiness_gaps = []
            continue
        fields = parse_task_fields(lines[task.start : task.end])
        task.readiness_gaps = readiness_diagnostics(fields, root, status_map)


def task_statuses(lines: list[str]) -> dict[str, str]:
    """Map permanent IDs to explicit status, treating checked history as Shipped."""
    result = {}
    i = 0
    while i < len(lines):
        match = route_tasks.TASK_RE.match(lines[i])
        if not match:
            i += 1
            continue
        end = route_tasks.scan_block_end(lines, i + 1)
        task_id = route_tasks.task_id_of(lines[i:end])
        if task_id:
            result[task_id] = (
                "Shipped"
                if match.group(1) == "x"
                else route_tasks.task_status_of(lines[i:end]) or "Legacy"
            )
        i = end
    return result


def roadmap_diff(before: list[str], after: list[str], path: str = "docs/roadmap.md") -> str:
    """Exact unified diff for the candidate lines the save path would write."""
    return "".join(difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}"))


def compute_context_load(file_fields: dict, root: Path) -> int:
    """Live Context Load preview -- the same packaging formula route_tasks.py
    stamps on refresh (max(1, round(total_files * total_chars / 1000))), computed from
    whatever paths currently sit in the dialog's four file-list fields. total_files counts
    every listed entry regardless of whether it resolves (matching route_tasks._count_entries);
    total_chars only counts entries that currently resolve to a real file on disk -- a
    **Write:** target named ahead of creation contributes 0 chars here, same as it will
    once route_tasks.py re-stamps the saved task for real."""
    total_files = sum(len(v) for v in file_fields.values())
    if total_files == 0:
        return 1
    seen = set()
    resolved = []
    for paths in file_fields.values():
        if not paths:
            continue
        joined = " · ".join(f"`{p}`" for p in paths)
        files, _missing = route_tasks.resolve_file_list(joined, root)
        for f in files:
            key = f.as_posix()
            if key not in seen:
                seen.add(key)
                resolved.append(f)
    total_chars = sum(c for _, c in route_tasks._char_sizes(resolved, root))
    return route_tasks.context_load(total_files, total_chars)


compute_task_effort = compute_context_load  # legacy import compatibility


def _section_headings(lines: list[str]) -> list[str]:
    """Distinct ##/### heading texts in document order, for the editor's Section combobox."""
    seen = []
    for line in lines:
        m = SECTION_RE.match(line)
        if m and m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def find_section_end(lines: list[str], section_heading: str) -> int:
    """Index just before the next ##/###/--- boundary after `section_heading`'s own
    heading line. Raises ValueError if the heading isn't found. Matches the first
    occurrence if the same heading text appears more than once in the file."""
    i = 0
    while i < len(lines):
        m = SECTION_RE.match(lines[i])
        if m and m.group(1) == section_heading:
            j = i + 1
            while j < len(lines) and not SECTION_BOUNDARY_RE.match(lines[j]):
                j += 1
            return j
        i += 1
    raise ValueError(f"section heading not found: {section_heading!r}")


def insert_task_block(lines: list[str], section_heading: str, block_lines: list[str]) -> list[str]:
    """Insert a new task block (see build_task_lines()) at the end of `section_heading`,
    trimming any trailing blank lines immediately before the section boundary first and
    inserting exactly one blank-line separator -- so spacing stays consistent with the
    rest of the file regardless of how much trailing whitespace was already there."""
    end = find_section_end(lines, section_heading)
    while end > 0 and lines[end - 1].strip() == "":
        end -= 1
    return lines[:end] + ["\n"] + block_lines + lines[end:]


def replace_task_block(lines: list[str], start: int, end: int, block_lines: list[str]) -> list[str]:
    """Splice a rebuilt block over an existing task's [start, end) span (from
    Task.start/Task.end, which already includes the trailing blank line before the next
    header/boundary per route_tasks.scan_block_end) -- block_lines' own trailing blank
    line keeps spacing consistent with what it replaces."""
    return lines[:start] + block_lines + lines[end:]


def delete_task_block(lines: list[str], start: int, end: int) -> list[str]:
    """Remove exactly one parsed task's [start, end) span from a roadmap copy."""
    return lines[:start] + lines[end:]


def move_task_block(
    lines: list[str], start: int, end: int, new_section: str, block_lines: list[str]
) -> list[str]:
    """Edit-save when the section changed: remove [start, end) first, then insert into
    new_section fresh -- avoids stale-index interaction with find_section_end's own scan
    of what would otherwise be an already-mutated list."""
    remaining = lines[:start] + lines[end:]
    return insert_task_block(remaining, new_section, block_lines)


class TaskEditorDialog(tk.Toplevel):
    """Modal create/edit dialog behind the picker screen's "+ New Task"/"Edit" buttons.
    A class (deviating from the file's usual inline-function dialog pattern, e.g.
    _show_response) given the field/widget count. Builds a field-dict via the pure
    parse_task_fields()/build_task_lines()/validate_task_fields() helpers above and writes
    through route_tasks.write_roadmap() -- the same guarded atomic-write path
    refresh_routes()/_on_mark_complete() already use, per REVIEW_TIERS.md's Class 3 rule
    for any docs/roadmap.md write path. Modal (transient + grab_set) so app.roadmap_lines
    can't be mutated by another picker action while open -- what makes using it directly
    as write_roadmap()'s original_lines safe."""

    SCORE_VALUES = ("1", "2", "3", "4", "5")
    CLASS_VALUES = ("1", "2", "3")
    FILE_GROUP_BREAKPOINT = 680

    def __init__(self, app: "App", task: Task | None, clone: bool = False):
        super().__init__(app)
        self.app = app
        self.task = None if clone else task
        self.source_task = task
        self.clone = clone
        self._manual_route = None  # round-tripped from an existing task, not settable here
        self.title("Clone Task" if clone else "Edit Task" if task is not None else "New Task")
        self.geometry("860x760")  # initial size only
        self.resizable(True, True)

        sections = _section_headings(app.roadmap_lines)
        if not sections:
            messagebox.showerror(
                "No sections found",
                "roadmap.md has no ##/### section headings to file a task under -- "
                "add one by hand first.",
                parent=app,
            )
            self.destroy()
            return

        self.file_lists = {label: [] for label in FILE_FIELD_LABELS}
        self.listboxes = {}
        self.file_group_boxes = {}
        self._file_group_columns = None
        self.suffix_warning = None

        self.score_var = tk.StringVar(value="3")
        self.class_var = tk.StringVar(value="2")
        self.title_var = tk.StringVar()
        self.section_var = tk.StringVar(value=sections[0])
        self.id_var = tk.StringVar(value=f"task_{uuid.uuid4().hex}")
        self.status_var = tk.StringVar(value="Draft")
        self.outcome_var = tk.StringVar()
        self.rationale_var = tk.StringVar()
        self.execution_mode_var = tk.StringVar()
        self.execution_size_var = tk.StringVar()
        self.uncertainty_var = tk.StringVar()
        self.is_fenced_var = tk.BooleanVar(value=False)
        self.context_load_var = tk.StringVar()

        self._build_widgets(sections)
        if task is not None:
            self._prefill(task)
            if clone:
                self.id_var.set(f"task_{uuid.uuid4().hex}")
                self.status_var.set("Draft")
                self._manual_route = None
        self._refresh_context_load_preview()

        self.transient(app)
        self.grab_set()

    # ── layout ──

    def _build_widgets(self, sections):
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)

        # Claim the action row first so shrinking the dialog never pushes Save/Cancel
        # below the window. The content above receives whatever height remains.
        bottom = ttk.Frame(f)
        bottom.pack(side="bottom", fill="x", pady=(4, 0))
        bottom.columnconfigure(0, weight=1)
        effort_label = ttk.Label(
            bottom,
            textvariable=self.context_load_var,
            foreground=gui_theme.COLOR_MUTED,
            justify="left",
        )
        effort_label.grid(row=0, column=0, sticky="ew")
        ttk.Button(bottom, text="Validate", command=self._on_validate_clicked).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Button(bottom, text="Preview Diff", command=self._on_preview_clicked).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Button(bottom, text="Preview & Save", command=self._on_save_clicked).grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk.Button(bottom, text="Cancel", command=self.destroy).grid(row=0, column=4, padx=(6, 0))
        _wrap_with_parent(effort_label, bottom, inset=350)

        tabs = ttk.Notebook(f)
        self.tabs = tabs
        tabs.pack(fill="both", expand=True, pady=(0, 8))
        record_tab = ttk.Frame(tabs, padding=8)
        artifacts_tab = ttk.Frame(tabs, padding=8)
        self.artifacts_tab = artifacts_tab
        requirements_tab = ttk.Frame(tabs, padding=8)
        tabs.add(record_tab, text="Task record")
        tabs.add(artifacts_tab, text="Artifacts")
        tabs.add(requirements_tab, text="Requirements")

        top = ttk.Frame(record_tab)
        top.pack(fill="x", pady=(0, 8))
        top.columnconfigure(1, weight=1)
        score_class = ttk.Frame(top)
        score_class.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(score_class, text="Score:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            score_class,
            textvariable=self.score_var,
            values=self.SCORE_VALUES,
            state="readonly",
            width=4,
        ).grid(row=0, column=1, padx=(4, 16))
        ttk.Label(score_class, text="Class:").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            score_class,
            textvariable=self.class_var,
            values=self.CLASS_VALUES,
            state="readonly",
            width=4,
        ).grid(row=0, column=3, padx=(4, 16))
        ttk.Label(top, text="Section:").grid(row=1, column=0, sticky="w")
        ttk.Combobox(top, textvariable=self.section_var, values=sections, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(6, 0)
        )
        ttk.Label(top, text="Status:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            top,
            textvariable=self.status_var,
            values=tuple(s for s in route_tasks.LIFECYCLE_STATUSES if s != "Shipped"),
            state="readonly",
        ).grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        ttk.Label(top, text="ID:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.id_var, state="readonly").grid(
            row=3, column=1, sticky="ew", padx=(6, 0), pady=(6, 0)
        )

        title_row = ttk.Frame(record_tab)
        title_row.pack(fill="x", pady=(0, 8))
        ttk.Label(title_row, text="Title:").pack(side="left")
        ttk.Entry(title_row, textvariable=self.title_var).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )

        if self.source_task is not None:
            self.suffix_warning = ttk.Label(record_tab, text="", foreground="#a00", justify="left")
            self.suffix_warning.pack(fill="x", pady=(0, 4))
            _wrap_with_parent(self.suffix_warning, record_tab)

        for label, variable in (("Outcome", self.outcome_var), ("Rationale", self.rationale_var)):
            row = ttk.Frame(record_tab)
            row.pack(fill="x", pady=(0, 6))
            ttk.Label(row, text=f"{label}:", width=10).pack(side="left")
            ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)

        record_lists = ttk.PanedWindow(record_tab, orient="horizontal")
        record_lists.pack(fill="both", expand=True, pady=(0, 6))
        acceptance_box = ttk.LabelFrame(record_lists, text="Acceptance conditions (one per line)")
        evidence_box = ttk.LabelFrame(record_lists, text="Expected evidence (one per line)")
        self.acceptance_text = scrolledtext.ScrolledText(acceptance_box, wrap="word", height=7)
        self.acceptance_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.acceptance_evidence_text = scrolledtext.ScrolledText(
            evidence_box, wrap="word", height=7
        )
        self.acceptance_evidence_text.pack(fill="both", expand=True, padx=4, pady=4)
        record_lists.add(acceptance_box, weight=1)
        record_lists.add(evidence_box, weight=1)

        ttk.Label(artifacts_tab, text="Description / execution notes:").pack(anchor="w")
        self.body_text = scrolledtext.ScrolledText(artifacts_tab, wrap="word", height=4)
        self.body_text.pack(fill="x", pady=(2, 4))
        fenced_row = ttk.Frame(artifacts_tab)
        fenced_row.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(
            fenced_row,
            text="Treat description as a fenced ```text prompt block",
            variable=self.is_fenced_var,
        ).pack(side="left")
        ttk.Label(
            fenced_row,
            text="(sent to the model verbatim)",
            foreground=gui_theme.COLOR_MUTED,
        ).pack(side="left", padx=(6, 0))

        file_view = ttk.Frame(artifacts_tab)
        file_view.pack(fill="both", expand=True, pady=(0, 8))
        file_view.columnconfigure(0, weight=1)
        file_view.rowconfigure(0, weight=1)
        self.file_canvas = tk.Canvas(
            file_view,
            background=gui_theme.COLOR_BG,
            borderwidth=0,
            highlightthickness=0,
        )
        file_scroll = ttk.Scrollbar(file_view, orient="vertical", command=self.file_canvas.yview)
        self.file_canvas.configure(yscrollcommand=file_scroll.set)
        self.file_canvas.grid(row=0, column=0, sticky="nsew")
        file_scroll.grid(row=0, column=1, sticky="ns")

        self.file_grid = ttk.Frame(self.file_canvas)
        self.file_grid_window = self.file_canvas.create_window(
            (0, 0), window=self.file_grid, anchor="nw"
        )
        for idx, label in enumerate(FILE_FIELD_LABELS):
            self._build_file_group(self.file_grid, label, idx // 2, idx % 2)
        self.file_canvas.bind("<Configure>", self._resize_file_view)
        self.file_grid.bind(
            "<Configure>",
            lambda _event: self.file_canvas.configure(scrollregion=self.file_canvas.bbox("all")),
        )

        mode_row = ttk.Frame(requirements_tab)
        mode_row.pack(fill="x", pady=(0, 8))
        ttk.Label(mode_row, text="Execution mode:").pack(side="left")
        ttk.Combobox(
            mode_row,
            textvariable=self.execution_mode_var,
            values=(
                "",
                "human-judgment",
                "human-physical",
                "deterministic-tooling",
                "local-ai",
                "network-ai",
            ),
            state="readonly",
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))
        judgment_row = ttk.Frame(requirements_tab)
        judgment_row.pack(fill="x", pady=(0, 8))
        ttk.Label(judgment_row, text="Execution size:").pack(side="left")
        ttk.Combobox(
            judgment_row,
            textvariable=self.execution_size_var,
            values=("", "Small", "Medium", "Large"),
            state="readonly",
            width=12,
        ).pack(side="left", padx=(6, 18))
        ttk.Label(judgment_row, text="Uncertainty:").pack(side="left")
        ttk.Combobox(
            judgment_row,
            textvariable=self.uncertainty_var,
            values=("", "Low", "Medium", "High"),
            state="readonly",
            width=12,
        ).pack(side="left", padx=(6, 0))
        requirements_lists = ttk.Frame(requirements_tab)
        requirements_lists.pack(fill="both", expand=True)
        requirements_lists.columnconfigure(0, weight=1, uniform="requirement")
        requirements_lists.columnconfigure(1, weight=1, uniform="requirement")
        for index, (label, attr) in enumerate(
            (
                ("Capabilities (one per line)", "capabilities_text"),
                ("Constraints (one per line)", "constraints_text"),
                ("Blocked by task IDs (one per line)", "dependencies_text"),
                ("Parent task IDs (one per line)", "parents_text"),
                ("Supersedes task IDs (one per line)", "supersedes_text"),
                ("Related task IDs (one per line)", "related_text"),
            )
        ):
            row, column = divmod(index, 2)
            requirements_lists.rowconfigure(row, weight=1, uniform="requirement")
            box = ttk.LabelFrame(requirements_lists, text=label)
            box.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 3, 3 if column == 0 else 0),
                pady=(0, 6),
            )
            widget = scrolledtext.ScrolledText(box, wrap="word", height=3)
            widget.pack(fill="both", expand=True, padx=4, pady=4)
            setattr(self, attr, widget)

    def _build_file_group(self, parent, label, row, col):
        box = ttk.LabelFrame(parent, text=FILE_FIELD_DISPLAY[label], padding=6)
        box.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
        self.file_group_boxes[label] = box

        lb_frame = ttk.Frame(box)
        lb_frame.pack(fill="both", expand=True)
        lb = tk.Listbox(lb_frame, selectmode="extended", height=4)
        vsb = ttk.Scrollbar(lb_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=vsb.set)
        lb.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.listboxes[label] = lb

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Add Files...", command=lambda: self._add_files(label)).pack(
            side="left"
        )
        ttk.Button(btns, text="Add Path...", command=lambda: self._add_path(label)).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Remove Selected", command=lambda: self._remove_selected(label)).pack(
            side="left"
        )

    def _resize_file_view(self, event):
        self.file_canvas.itemconfigure(self.file_grid_window, width=event.width)
        self._reflow_file_groups(event.width)
        self.after_idle(self._sync_file_view)

    def _sync_file_view(self):
        if not self.file_canvas.winfo_exists():
            return
        width = max(1, self.file_canvas.winfo_width())
        height = max(self.file_canvas.winfo_height(), self.file_grid.winfo_reqheight())
        self.file_canvas.itemconfigure(self.file_grid_window, width=width, height=height)
        self.file_canvas.configure(scrollregion=(0, 0, width, height))

    def _reflow_file_groups(self, width):
        """Switch file selectors between two columns and one as usable width changes."""
        columns = 2 if width >= self.FILE_GROUP_BREAKPOINT else 1
        if columns == self._file_group_columns:
            return
        self._file_group_columns = columns
        rows = (len(FILE_FIELD_LABELS) + columns - 1) // columns
        for idx, label in enumerate(FILE_FIELD_LABELS):
            self.file_group_boxes[label].grid_configure(
                row=idx // columns,
                column=idx % columns,
            )
        for col in range(2):
            self.file_grid.columnconfigure(col, weight=1 if col < columns else 0)
        for row in range(len(FILE_FIELD_LABELS)):
            self.file_grid.rowconfigure(
                row,
                weight=1 if row < rows else 0,
                uniform="file_group" if row < rows else "",
            )
        self.after_idle(self._sync_file_view)

    # ── prefill (edit only) ──

    def _prefill(self, task: Task):
        block = self.app.roadmap_lines[task.start : task.end]
        fields = parse_task_fields(block)
        self.score_var.set(fields["score"] or "3")
        self.class_var.set(fields["task_class"] or "2")
        self.title_var.set(fields["title"])
        self.section_var.set(task.section or self.section_var.get())
        if fields["id"]:
            self.id_var.set(fields["id"])
        self.status_var.set(fields["status"] or "Draft")
        self.outcome_var.set(fields["outcome"])
        self.rationale_var.set(fields["rationale"])
        self.execution_mode_var.set(fields["execution_mode"])
        self.execution_size_var.set(fields["execution_size"])
        self.uncertainty_var.set(fields["uncertainty"])
        self._set_lines(self.acceptance_text, fields["acceptance_conditions"])
        self._set_lines(self.acceptance_evidence_text, fields["acceptance_evidence"])
        self._set_lines(self.capabilities_text, fields["capabilities"])
        self._set_lines(self.constraints_text, fields["constraints"])
        self._set_lines(self.dependencies_text, fields["dependencies"])
        self._set_lines(self.parents_text, fields["parents"])
        self._set_lines(self.supersedes_text, fields["supersedes"])
        self._set_lines(self.related_text, fields["related"])
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", fields["body"])
        self.is_fenced_var.set(fields["is_fenced"])
        self.file_lists = {k: list(v) for k, v in fields["file_fields"].items()}
        self._manual_route = fields["manual_route"]
        for label in FILE_FIELD_LABELS:
            self._refresh_listbox(label)
        if fields["has_field_suffix"] and self.suffix_warning is not None:
            self.suffix_warning.config(
                text="This task uses a per-line class-suffix annotation (e.g. "
                '"Implement (Class 3 — ...):") that this editor does not support -- '
                "saving will drop it."
            )

    @staticmethod
    def _set_lines(widget, values):
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(values))

    @staticmethod
    def _get_lines(widget):
        return [line.strip() for line in widget.get("1.0", "end").splitlines() if line.strip()]

    # ── file-list helpers ──

    def _refresh_listbox(self, label):
        lb = self.listboxes[label]
        lb.delete(0, "end")
        for p in self.file_lists[label]:
            lb.insert("end", p)

    def _relativize(self, raw_path: str) -> str:
        try:
            return Path(raw_path).resolve().relative_to(self.app.root_dir.resolve()).as_posix()
        except ValueError:
            return Path(raw_path).as_posix()

    def _add_files(self, label):
        paths = filedialog.askopenfilenames(
            initialdir=str(self.app.root_dir), title=f"Add {label} files", parent=self
        )
        if not paths:
            return
        for p in paths:
            rel = self._relativize(p)
            if rel not in self.file_lists[label]:
                self.file_lists[label].append(rel)
        self._refresh_listbox(label)
        self._refresh_context_load_preview()

    def _add_path(self, label):
        raw = simpledialog.askstring(
            f"Add {label} path",
            "Path relative to the repo root (or <name>/... for an external reference) -- "
            "for a not-yet-created file a file picker can't select:",
            parent=self,
        )
        if not raw:
            return
        raw = raw.strip()
        if raw and raw not in self.file_lists[label]:
            self.file_lists[label].append(raw)
        self._refresh_listbox(label)
        self._refresh_context_load_preview()

    def _remove_selected(self, label):
        lb = self.listboxes[label]
        for idx in reversed(lb.curselection()):
            del self.file_lists[label][idx]
        self._refresh_listbox(label)
        self._refresh_context_load_preview()

    def _refresh_context_load_preview(self):
        load = compute_context_load(self.file_lists, self.app.root_dir)
        self.context_load_var.set(f"Context Load (auto-computed on save): ~{load}")

    # ── save ──

    def _collect_fields(self) -> dict:
        return {
            "id": self.id_var.get(),
            "status": self.status_var.get(),
            "score": self.score_var.get(),
            "task_class": self.class_var.get(),
            "title": self.title_var.get().strip(),
            "section": self.section_var.get(),
            "body": self.body_text.get("1.0", "end").strip(),
            "is_fenced": self.is_fenced_var.get(),
            "file_fields": self.file_lists,
            "manual_route": self._manual_route,
            "outcome": self.outcome_var.get().strip(),
            "rationale": self.rationale_var.get().strip(),
            "acceptance_conditions": self._get_lines(self.acceptance_text),
            "acceptance_evidence": self._get_lines(self.acceptance_evidence_text),
            "execution_mode": self.execution_mode_var.get(),
            "execution_size": self.execution_size_var.get(),
            "uncertainty": self.uncertainty_var.get(),
            "capabilities": self._get_lines(self.capabilities_text),
            "constraints": self._get_lines(self.constraints_text),
            "dependencies": self._get_lines(self.dependencies_text),
            "parents": self._get_lines(self.parents_text),
            "supersedes": self._get_lines(self.supersedes_text),
            "related": self._get_lines(self.related_text),
        }

    def _candidate(self):
        fields = self._collect_fields()
        lifecycle_lines = list(self.app.roadmap_lines)
        if self.app.SHIPPED_PATH.is_file():
            lifecycle_lines.extend(
                self.app.SHIPPED_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            )
        existing_ids = route_tasks.collect_task_ids(lifecycle_lines)
        if self.task is not None and fields["id"]:
            existing_ids.discard(fields["id"])
        err = validate_task_fields(fields, existing_ids)
        if err:
            raise ValueError(err)
        gaps = readiness_diagnostics(fields, self.app.root_dir, task_statuses(lifecycle_lines))
        if fields["status"] == "Ready" and gaps:
            raise ValueError("Cannot mark Ready:\n\n" + "\n".join(f"- {gap}" for gap in gaps))

        block = build_task_lines(fields)
        if self.task is None:
            result = insert_task_block(self.app.roadmap_lines, fields["section"], block)
        elif fields["section"] == self.task.section:
            result = replace_task_block(
                self.app.roadmap_lines, self.task.start, self.task.end, block
            )
        else:
            result = move_task_block(
                self.app.roadmap_lines,
                self.task.start,
                self.task.end,
                fields["section"],
                block,
            )
        # Preview the same fully routed bytes the post-save refresh would otherwise
        # derive afterward. The displayed diff is therefore the exact write, including
        # generated annotations for Ready tasks rather than an intermediate draft.
        result = route_tasks.process_roadmap(result, self.app.ROADMAP_PATH, root=self.app.root_dir)
        relationship_lines = list(result)
        if self.app.SHIPPED_PATH.is_file():
            relationship_lines.extend(
                self.app.SHIPPED_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            )
        relationship_errors = route_tasks.validate_task_relationships(relationship_lines)
        if relationship_errors:
            raise ValueError(
                "Relationship validation failed:\n\n"
                + "\n".join(f"- {error}" for error in relationship_errors)
            )
        return fields, gaps, result

    def _on_validate_clicked(self):
        try:
            fields, gaps, _result = self._candidate()
        except ValueError as exc:
            messagebox.showerror("Validation failed", str(exc), parent=self)
            return
        if gaps:
            messagebox.showinfo(
                "Valid Draft; not Ready",
                "The record is structurally valid and nothing was written. Readiness gaps:\n\n"
                + "\n".join(f"- {gap}" for gap in gaps),
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Validation passed",
                f"This {fields['status']} record is structurally valid and Ready-complete. "
                "Nothing was written.",
                parent=self,
            )

    def _on_preview_clicked(self):
        try:
            _fields, gaps, result = self._candidate()
        except ValueError as exc:
            messagebox.showerror("Cannot preview", str(exc), parent=self)
            return
        diff = roadmap_diff(self.app.roadmap_lines, result, self.app.ROADMAP_PATH.as_posix())
        DiffPreviewDialog(self, diff, gaps)

    def _on_save_clicked(self):
        try:
            _fields, gaps, result = self._candidate()
        except ValueError as exc:
            messagebox.showerror("Cannot save", str(exc), parent=self)
            return
        diff = roadmap_diff(self.app.roadmap_lines, result, self.app.ROADMAP_PATH.as_posix())
        DiffPreviewDialog(self, diff, gaps, on_apply=lambda: self._apply_candidate(result))

    def _apply_candidate(self, result):
        try:
            current = self.app.ROADMAP_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            if current != self.app.roadmap_lines:
                messagebox.showerror(
                    "Roadmap changed",
                    "roadmap.md changed after this editor opened. Reload and preview again; "
                    "nothing was written.",
                    parent=self,
                )
                return False
            route_tasks.write_roadmap(self.app.ROADMAP_PATH, self.app.roadmap_lines, result)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return False
        self.app._load_tasks()
        self.destroy()
        return True


class DiffPreviewDialog(tk.Toplevel):
    """Exact roadmap diff gate. Apply is available only when a save requested it."""

    def __init__(self, parent, diff, readiness_gaps, on_apply=None):
        super().__init__(parent)
        self.on_apply = on_apply
        self.title("Exact roadmap diff")
        self.geometry("900x650")
        self.resizable(True, True)
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        if readiness_gaps:
            ttk.Label(
                frame,
                text="Draft readiness gaps: " + "; ".join(readiness_gaps),
                foreground="#a65b00",
                justify="left",
                wraplength=850,
            ).pack(fill="x", pady=(0, 6))
        view = scrolledtext.ScrolledText(frame, wrap="none")
        view.pack(fill="both", expand=True)
        view.insert("1.0", diff or "(no changes)")
        view.configure(state="disabled")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right")
        if on_apply is not None and diff:
            ttk.Button(actions, text="Apply This Diff", command=self._apply).pack(
                side="right", padx=(0, 6)
            )
        self.transient(parent)
        self.grab_set()

    def _apply(self):
        if self.on_apply and self.on_apply() and self.winfo_exists():
            self.destroy()
