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

import contextlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_pack  # noqa: E402
import gui_theme  # noqa: E402
import query_model  # noqa: E402
import route_tasks  # noqa: E402

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROADMAP = SCRIPT_ROOT / "docs" / "roadmap.md"
DEFAULT_SHIPPED = SCRIPT_ROOT / "docs" / "shipped.md"
# Forward-only high-water mark for **Effort:**, persisted here because docs/shipped.md
# doesn't retain Effort once a task ships — this file is the only durable record of the
# highest Effort ever seen, so the combined-score column's 1-5 effort scale (see
# _combined_score) stays stable across sessions instead of rescaling every refresh.
EFFORT_CEILING_PATH = Path(__file__).resolve().parent / "effort_ceiling.txt"

HEADER_RE = re.compile(r"^- \[([ x])\]\s*\*\*(.+?)\*\*")
# Splits a header (per roadmap.md's format convention) into its packed attributes:
# "Score <1-5> <medal> · Class <1-3> — <title>" -> score, title (class is already
# pulled separately via route_tasks.CLASS_RE; the medal glyph is matched generically
# and not trusted — the picker recomputes it from score via route_tasks._medal()).
HEADER_ATTR_RE = re.compile(
    r"^Score\s+(?P<score>[1-5])\s+\S+\s*·\s*Class\s+(?P<cls>[123])\s*—\s*(?P<title>.+)$"
)
# Any ## or ### heading line, used to tag each task with the section it falls under
# (e.g. "Upstream architecture study") so the picker's filter box can match on it —
# a task's own title often doesn't contain its section's theme word.
SECTION_RE = re.compile(r"^#{2,4}\s+(.+?)\s*$")
FILE_LIST_RE = re.compile(
    r"^\s+\*\*(Implement|Write|Context|Read)[^*]*\*\*:?\s*(.+)", re.IGNORECASE
)
ROUTE_VALUE_RE = re.compile(r"^\s*\*\*Route:\*\*\s*(.+?)\s*$")
EFFORT_VALUE_RE = re.compile(r"^\s*\*\*Effort:\*\*\s*(.+?)\s*$")
CHARS_VALUE_RE = re.compile(r"^\s*\*\*Chars:\*\*\s*(.+?)\s*$")
FENCE_START_RE = re.compile(r"^\s*```text\s*$")
FENCE_END_RE = re.compile(r"^\s*```\s*$")

CHECK_EMPTY = "☐"  # ☐
CHECK_FULL = "☑"  # ☑


def split_header(header: str) -> tuple[str, str]:
    """Break a task header into (score, title), for table columns."""
    m = HEADER_ATTR_RE.match(header)
    if not m:
        return "", header
    return m.group("score"), m.group("title")


def _score_int(t: "Task") -> int:
    score, _ = split_header(t.header)
    return int(score) if score.isdigit() else 0


def _effort_int(t: "Task") -> int | None:
    return int(t.effort) if t.effort.isdigit() else None


def _read_effort_ceiling() -> int:
    try:
        return max(1, int(EFFORT_CEILING_PATH.read_text(encoding="utf-8").strip()))
    except (FileNotFoundError, ValueError):
        return 1


def _update_effort_ceiling(tasks: list["Task"]) -> int:
    """Raise the persisted ceiling if any currently-open task's Effort exceeds it; never
    lowers it. Returns the effective ceiling to normalize against."""
    stored = _read_effort_ceiling()
    seen_max = max((_effort_int(t) or 0 for t in tasks), default=0)
    ceiling = max(stored, seen_max)
    if ceiling != stored:
        EFFORT_CEILING_PATH.write_text(str(ceiling), encoding="utf-8")
    return ceiling


def _combined_score(t: "Task", effort_ceiling: int) -> float:
    """Value-density, with effort normalized onto the same 1-5 scale as score (the
    persisted effort_ceiling maps to 5) before dividing — otherwise effort's much larger
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
    """Highest score first; lowest effort breaks ties within the same score.
    Unrouted (unknown) effort sorts last within its score tier."""
    effort = _effort_int(t)
    return (-_score_int(t), effort if effort is not None else 10**9)


# Offline seed/fallback for the OpenRouter model combobox: the "Fetch free models" button
# (query_model._openrouter_free_models) pulls the live ':free' list at runtime, so this
# list only matters when offline or before a fetch. Verified live 2026-07-05 (the previous
# llama-3.1-8b / qwen-2.5-72b / gemma-2-9b IDs were all retired).
OPENROUTER_MODELS = [
    "openrouter/qwen/qwen3-coder:free",
    "openrouter/deepseek/deepseek-r1:free",
    "openrouter/meta-llama/llama-3.3-70b-instruct:free",
]


# Opt-in OpenRouter key persistence. Stored in the user's home dir — deliberately OUTSIDE
# any repo, so a plaintext secret can never be accidentally committed (the earlier design
# kept the key session-only for exactly this reason; persistence is now opt-in via the
# "Remember" checkbox, off by default, and a home-dir file is the safe way to allow it).
OPENROUTER_KEY_FILE = Path.home() / ".pmt_openrouter_key"


def _load_saved_key() -> str:
    try:
        return OPENROUTER_KEY_FILE.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""


def _save_key(key: str) -> None:
    OPENROUTER_KEY_FILE.write_text(key, encoding="utf-8")
    # best-effort; a no-op on Windows
    with contextlib.suppress(OSError):
        os.chmod(OPENROUTER_KEY_FILE, 0o600)


def _forget_saved_key() -> None:
    with contextlib.suppress(FileNotFoundError, OSError):
        OPENROUTER_KEY_FILE.unlink()


# Mirrors context_pack.py's own --max-chars default (docs/ai-harness.md §3.1):
# packs under this size stay a single paste, larger ones split between files.
CHUNK_MAX_CHARS = 100_000


def _chunk_budget(routes):
    """Tightest known per-message char budget among the given model routes, capped at
    CHUNK_MAX_CHARS — so a pack auto-chunks at whichever routed model's real paste
    ceiling is smallest, instead of always waiting for the generic 100k mark. A Kimi-
    routed pack sailing through at ~46k chars unchunked (well past Kimi's own measured
    ceiling, see docs/ai-harness.md §1) is exactly the failure this closes."""
    known = [
        context_pack.MODEL_BUDGETS[r]["chars"]
        for r in routes
        if r in context_pack.MODEL_BUDGETS and context_pack.MODEL_BUDGETS[r]["chars"] is not None
    ]
    return min([CHUNK_MAX_CHARS, *known]) if known else CHUNK_MAX_CHARS


@dataclass
class Task:
    header: str
    task_class: str
    section: str = ""  # nearest preceding ##/### heading this task falls under
    route: str = "?"
    effort: str = "?"
    files: list[Path] = field(default_factory=list)  # resolved, existing paths, in file-list order
    missing: list[str] = field(
        default_factory=list
    )  # raw backtick strings that didn't resolve to a file
    prompt: str = ""  # extracted ```text block body, if the item has one
    start: int = -1  # index into the parsed lines[] of this task's header
    end: int = -1  # exclusive end index (route_tasks.scan_block_end)


def parse_tasks(lines: list[str], root: Path) -> list[Task]:
    """Walk freshly-routed roadmap.md lines into open Task objects."""
    tasks = []
    i = 0
    section = ""
    while i < len(lines):
        sm = SECTION_RE.match(lines[i])
        if sm:
            section = sm.group(1)
            i += 1
            continue

        m = HEADER_RE.match(lines[i])
        if not m or m.group(1) == "x":
            i += 1
            continue

        class_m = route_tasks.CLASS_RE.search(lines[i])
        task = Task(
            header=m.group(2),
            task_class=class_m.group(1) if class_m else "?",
            section=section,
            start=i,
        )

        # Shared fence-aware block scan (route_tasks.scan_block_end) — so this parser
        # and route_tasks._process()/find_task_block() can't disagree about where one
        # task ends and the next begins.
        j = route_tasks.scan_block_end(lines, i + 1)
        task.end = j
        block = lines[i + 1 : j]

        seen = set()
        in_fence = False
        fence_lines = []
        body_lines = []
        for bl in block:
            rm = ROUTE_VALUE_RE.match(bl)
            if rm:
                task.route = rm.group(1)
                continue
            em = EFFORT_VALUE_RE.match(bl)
            if em:
                task.effort = em.group(1)
                continue
            if CHARS_VALUE_RE.match(bl):
                continue
            fm = FILE_LIST_RE.match(bl)
            if fm:
                files, missing = route_tasks.resolve_file_list(fm.group(2), root)
                for p in files:
                    key = p.as_posix()
                    if key in seen:
                        continue
                    seen.add(key)
                    task.files.append(p)
                for raw in missing:
                    if raw in seen:
                        continue
                    seen.add(raw)
                    task.missing.append(raw)
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

        # A fenced ```text block (a ready-made, model-facing prompt) takes priority when
        # present; most items have no fence at all, so fall back to the plain description
        # paragraph under the header — otherwise those tasks packed with an empty prompt box.
        task.prompt = "".join(fence_lines).strip()
        if not task.prompt:
            # header_tail is the word-wrapped start of the same sentence the body
            # continues (the roadmap's line-wrap convention splits mid-sentence, not
            # at a paragraph boundary) — join with a space, not a blank line, or it
            # reads as two sentence fragments instead of one.
            header_tail = lines[i][m.end() :].strip(" \t\n-—")
            desc = "".join(body_lines).strip()
            task.prompt = f"{header_tail} {desc}".strip() if header_tail else desc
        tasks.append(task)
        i = j
    return tasks


# ── task editor: pure parse/build/splice helpers (no Tkinter) ──
#
# These back TaskEditorDialog's Save path. Kept free of Tkinter so they're unit-testable
# headlessly (see tests/test_task_editor.py) -- this repo's own REVIEW_TIERS.md Class 3
# rule for any docs/roadmap.md write path requires a round-trip test, and a function tied
# to live widgets can't be driven without a display.

FILE_FIELD_LABELS = ("Implement", "Context", "Write", "Read")
_LABEL_CANON = {label.lower(): label for label in FILE_FIELD_LABELS}
# A file-list line using a parenthetical suffix, e.g. "**Implement (Class 3 — ...):**"
# (see ROADMAP.template.md's format convention) -- a real, exercised case this editor's
# flat per-label model can't preserve; parse_task_fields() flags it so the dialog can warn
# instead of silently dropping the annotation on save.
FIELD_SUFFIX_RE = re.compile(r"^\s+\*\*(?:Implement|Write|Context|Read)\s*\(", re.IGNORECASE)
MANUAL_ROUTE_SUFFIX_RE = re.compile(r"^(.*?)\s*\(manual\)\s*$")
SECTION_BOUNDARY_RE = re.compile(r"^#{2,4}\s|^---\s*$")


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
    manual_route = None
    has_field_suffix = False
    in_fence = False
    fence_lines = []
    body_lines = []

    for bl in block_lines[1:]:
        rm = ROUTE_VALUE_RE.match(bl)
        if rm:
            mm = MANUAL_ROUTE_SUFFIX_RE.match(rm.group(1))
            if mm and rm.group(1).endswith("(manual)"):
                manual_route = mm.group(1).strip()
            continue
        if EFFORT_VALUE_RE.match(bl) or CHARS_VALUE_RE.match(bl):
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
    }


def build_task_lines(fields: dict) -> list[str]:
    """Render a field-dict (see parse_task_fields()) into a well-formed task block ending
    in exactly one blank line. Never emits Effort/Chars, and only emits a Route line when
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
        "\n",
    ]

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


def validate_task_fields(fields: dict) -> str | None:
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
    if not any(fields.get("file_fields", {}).get(label) for label in FILE_FIELD_LABELS):
        return "At least one file path is required (Implement/Context/Write/Read)."
    return None


def compute_task_effort(file_fields: dict, root: Path) -> int:
    """Live Effort preview for the editor dialog -- the same formula route_tasks.py
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
    return max(1, round(total_files * total_chars / 1000))


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


def move_task_block(
    lines: list[str], start: int, end: int, new_section: str, block_lines: list[str]
) -> list[str]:
    """Edit-save when the section changed: remove [start, end) first, then insert into
    new_section fresh -- avoids stale-index interaction with find_section_end's own scan
    of what would otherwise be an already-mutated list."""
    remaining = lines[:start] + lines[end:]
    return insert_task_block(remaining, new_section, block_lines)


# ── AI response inbox: pure helpers (no Tkinter) ──
#
# ai-harness.md §3.2 step 5 says to copy a model's response into "a scratch file" but
# never pins down where -- this gives that step a fixed, per-task home so responses from
# separate manual paste-back chat sessions accumulate in one place until there's budget to
# run the §5 fusion pass. One growing file per task, not one file per response: simplest
# mental model for a human skimming what's been collected so far. Gitignored (see
# .gitignore) -- working material for the fusion step, not permanent project history,
# same role scratch.txt already plays.

AI_INBOX_DIRNAME = "ai_inbox"
TASK_SLUG_RE = re.compile(r"[^a-z0-9]+")


def task_slug(title: str) -> str:
    """Filesystem-safe, stable identifier for a task's inbox file -- derived from its
    title so the same task lands in the same file across sessions with no separate id
    scheme to keep in sync."""
    slug = TASK_SLUG_RE.sub("-", title.lower()).strip("-")
    return slug[:60].strip("-") or "task"


def inbox_path(root: Path, title: str) -> Path:
    return root / AI_INBOX_DIRNAME / f"{task_slug(title)}.md"


def count_inbox_responses(path: Path) -> int:
    """Number of responses already saved for a task, for the GUI's status line -- counts
    the '<!-- saved ... -->' markers append_inbox_response() writes; 0 if the file doesn't
    exist yet."""
    if not path.is_file():
        return 0
    return path.read_text(encoding="utf-8").count("<!-- saved ")


def append_inbox_response(path: Path, title: str, response_text: str) -> None:
    """Append one pasted AI response to a task's inbox file, atomically (temp-file-then-
    rename, matching route_tasks._atomic_write's own pattern) -- creates ai_inbox/ and the
    file on first use. Never overwrites a previous response, only adds. Raises ValueError
    on empty input so the GUI can show a clear message instead of writing a blank entry."""
    response_text = response_text.strip()
    if not response_text:
        raise ValueError("response text is empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = path.read_text(encoding="utf-8") if path.is_file() else f"<!-- task: {title} -->\n"
    if not existing.endswith("\n"):
        existing += "\n"
    block = f"\n<!-- saved {timestamp} -->\n\n{response_text}\n"
    route_tasks._atomic_write(path, existing + block)


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
        self.geometry("960x720")
        gui_theme.configure_style(self)
        self.root_dir = context_pack.repo_root()
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
        updated = route_tasks._process(lines, context_pack.repo_root())
        route_tasks.write_roadmap(self.ROADMAP_PATH, lines, updated)
        return updated

    # ── picker screen ──

    def _build_picker_frame(self):
        f = self.picker_frame

        # One toolbar, above the table (matches setup_wizard_gui.py's convention): view
        # utilities and task CRUD on the left, the checked-selection workflow actions
        # (Mark Complete, Pack) grouped on the right with Pack outermost as the primary
        # "move forward" action.
        toolbar = ttk.Frame(f)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="↻ Refresh", command=self._load_tasks).pack(side="left")
        ttk.Button(toolbar, text="Check All", command=lambda: self._set_all_checked(True)).pack(
            side="left", padx=6
        )
        ttk.Button(toolbar, text="Clear", command=lambda: self._set_all_checked(False)).pack(
            side="left"
        )
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=12)
        ttk.Button(toolbar, text="+ New Task", command=self._on_new_task).pack(side="left")
        ttk.Button(toolbar, text="✎ Edit", command=self._on_edit_task).pack(side="left", padx=6)

        ttk.Button(toolbar, text="Pack →", style="Accent.TButton", command=self._on_pack).pack(
            side="right"
        )
        ttk.Separator(toolbar, orient="vertical").pack(side="right", fill="y", padx=12)
        ttk.Button(toolbar, text="Mark Complete →", command=self._on_mark_complete).pack(
            side="right"
        )

        ttk.Label(
            f,
            text="Pick one or more roadmap tasks (check the box to include in the pack):",
            font=("", 11, "bold"),
        ).pack(anchor="w")

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
            "route",
            "files",
            "section",
            "title",
        )
        # (heading label, width, whether this column absorbs extra widget width)
        col_spec = {
            "sel": ("", 26, False),
            "score": ("Score", 60, False),
            "effort": ("Effort", 55, False),
            "combined": ("Value/Effort", 80, False),
            "class": ("Class", 50, False),
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
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        gui_theme.tag_stripes(self.tree)

    def _load_tasks(self):
        self.tasks = []
        self.filtered_tasks = []
        try:
            lines = self.refresh_routes()
        except FileNotFoundError:
            messagebox.showerror("roadmap.md not found", f"Could not find {self.ROADMAP_PATH}")
            self.tree.delete(*self.tree.get_children())
            return
        except RuntimeError as e:
            # write_roadmap refused a truncated-looking rewrite — the file on disk is
            # untouched; surface the refusal instead of showing silently stale routes.
            messagebox.showerror("Roadmap refresh failed", str(e))
            self.tree.delete(*self.tree.get_children())
            return
        self.roadmap_lines = lines  # what task.start/task.end index into — see _on_mark_complete
        self.tasks = parse_tasks(lines, self.root_dir)
        self.effort_ceiling = _update_effort_ceiling(self.tasks)
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
                or q in t.route.lower()
            ]
        else:
            self.filtered_tasks = list(self.tasks)

        # Default order: highest score first, lowest effort breaks ties among equally-
        # scored tasks. Re-applied on every load/filter change; an explicit header click
        # below overrides it until the next load/filter.
        self.filtered_tasks.sort(key=_default_sort_key)

        self.checked.clear()
        self.tree.delete(*self.tree.get_children())
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
        """Edit's selection rule is stricter than _selected_tasks()'s (which accepts any
        count): exactly one task, checked or focused. Shows an info dialog and returns
        None otherwise."""
        tasks = self._selected_tasks()
        if len(tasks) != 1:
            messagebox.showinfo(
                "Select exactly one task",
                f"Check exactly one task (or click a single row) before editing — "
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

        # Full-contrast text, not the muted gray fit_label below it — this line carries
        # actionable warnings (missing files, Class 3 notice) that need to stay legible.
        self.status_label = ttk.Label(f, text="", foreground=gui_theme.COLOR_TEXT, wraplength=900)
        self.status_label.pack(anchor="w")

        self.fit_label = ttk.Label(f, text="", foreground=gui_theme.COLOR_MUTED, wraplength=900)
        self.fit_label.pack(anchor="w", pady=(0, 6))

        ttk.Checkbutton(
            f,
            text="Ignore char limit (show one concatenated block instead of paged chunks — "
            "burns file-upload budget instead of chunking)",
            variable=self.ignore_char_limit,
            command=self._refresh_pack_view,
        ).pack(anchor="w", pady=(0, 6))

        # pack_text (checked / default) and chunk_frame (unchecked) occupy the same
        # spot in the layout — only one is packed at a time, toggled in _refresh_pack_view().
        self.pack_text = scrolledtext.ScrolledText(f, wrap="word", height=18)

        # Paginated view (docs/ai-harness.md §3.1) — one page at a time via large
        # Prev/Next, so a pack that would otherwise be a monster paste never lands in
        # the box unannounced. Independent of prompt_text: Copy/Save below keep
        # working on the whole pack regardless of which view is showing.
        self.chunk_frame = ttk.Frame(f)
        ttk.Label(
            self.chunk_frame,
            text='Paged view — step through with Prev/Next below. Use "Copy This Chunk" / '
            '"Copy && Advance" to paste each page as its own chat message, in order, '
            "then the prompt as the closing message (docs/ai-harness.md §3.1):",
            wraplength=900,
        ).pack(anchor="w")
        chunknav = ttk.Frame(self.chunk_frame)
        chunknav.pack(fill="x", pady=(4, 4))
        self.btn_chunk_prev = ttk.Button(
            chunknav, text="<< Prev", style="Big.TButton", command=self._on_prev_chunk
        )
        self.btn_chunk_prev.pack(side="left")
        self.chunk_label = ttk.Label(chunknav, text="", font=("", 11, "bold"))
        self.chunk_label.pack(side="left", padx=12)
        self.btn_chunk_next = ttk.Button(
            chunknav, text="Next >>", style="Big.TButton", command=self._on_next_chunk
        )
        self.btn_chunk_next.pack(side="left")
        ttk.Button(chunknav, text="Copy This Chunk", command=self._on_copy_chunk).pack(
            side="left", padx=(20, 0)
        )
        ttk.Button(chunknav, text="Copy && Advance", command=self._on_copy_chunk_advance).pack(
            side="left", padx=6
        )
        self.chunk_preview = scrolledtext.ScrolledText(self.chunk_frame, wrap="word", height=18)
        self.chunk_preview.pack(fill="both", expand=True, pady=(8, 8))

        self.prompt_label = ttk.Label(f, text="Prompt / task description (editable):")
        self.prompt_label.pack(anchor="w")
        self.prompt_text = scrolledtext.ScrolledText(f, wrap="word", height=6)
        self.prompt_text.pack(fill="x", pady=(2, 8))

        self._build_inbox_section(f)

    def _build_inbox_section(self, f):
        """Paste-back area for manually-collected AI chat responses (see the
        AI_INBOX_DIRNAME module comment). inbox_frame and inbox_unavailable_label occupy
        the same slot below the prompt box -- _refresh_inbox_section() (called from
        _on_pack) shows exactly one, since paste-back only makes sense for a single task.
        inbox_frame's body is itself collapsible (via the ▾/▸ toggle button) so this
        section doesn't have to claim screen space on every visit."""
        self.inbox_frame = ttk.Frame(f)
        self.inbox_expanded = True

        ttk.Separator(self.inbox_frame, orient="horizontal").pack(fill="x", pady=(0, 6))
        header = ttk.Frame(self.inbox_frame)
        header.pack(fill="x")
        self.inbox_toggle_btn = ttk.Button(
            header,
            text="▾  AI response inbox",
            command=self._toggle_inbox_expanded,
        )
        self.inbox_toggle_btn.pack(side="left")

        self.inbox_body = ttk.Frame(self.inbox_frame, padding=(4, 6, 0, 0))
        self.inbox_body.pack(fill="x")

        self.inbox_status_label = ttk.Label(
            self.inbox_body, text="", foreground=gui_theme.COLOR_MUTED
        )
        self.inbox_status_label.pack(anchor="w")

        ttk.Label(
            self.inbox_body,
            text="Paste a model's full response here, then Save — collect as many as you "
            "like across separate chat sessions, then run the fusion pass "
            "(docs/ai-harness.md §5) later, when there's budget.",
            wraplength=880,
        ).pack(anchor="w", pady=(2, 4))

        self.inbox_paste_text = scrolledtext.ScrolledText(self.inbox_body, wrap="word", height=6)
        self.inbox_paste_text.pack(fill="x", pady=(0, 4))

        inbox_btns = ttk.Frame(self.inbox_body)
        inbox_btns.pack(fill="x")
        ttk.Button(inbox_btns, text="Save to Inbox", command=self._on_save_to_inbox).pack(
            side="left"
        )
        ttk.Button(inbox_btns, text="Open Inbox Folder", command=self._on_open_inbox_folder).pack(
            side="left", padx=6
        )

        self.inbox_unavailable_label = ttk.Label(
            f,
            text="Inbox paste-back is available when exactly one task is packed.",
            foreground=gui_theme.COLOR_MUTED,
        )

    def _toggle_inbox_expanded(self):
        self.inbox_expanded = not self.inbox_expanded
        if self.inbox_expanded:
            self.inbox_body.pack(fill="x")
            self.inbox_toggle_btn.config(text="▾  AI response inbox")
        else:
            self.inbox_body.pack_forget()
            self.inbox_toggle_btn.config(text="▸  AI response inbox")

    def _refresh_inbox_section(self):
        self.inbox_frame.pack_forget()
        self.inbox_unavailable_label.pack_forget()
        if len(self.current_tasks) == 1:
            self.inbox_paste_text.delete("1.0", "end")
            self._current_inbox_path = inbox_path(self.root_dir, self.current_tasks[0].header)
            self._refresh_inbox_status()
            self.inbox_frame.pack(fill="x", pady=(0, 4))
        else:
            self._current_inbox_path = None
            self.inbox_unavailable_label.pack(anchor="w", pady=(0, 4))

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

    def _on_save_to_inbox(self):
        if self._current_inbox_path is None:
            return
        text = self.inbox_paste_text.get("1.0", "end")
        title = self.current_tasks[0].header
        try:
            append_inbox_response(self._current_inbox_path, title, text)
        except ValueError:
            messagebox.showinfo("Nothing to save", "Paste a response before saving.")
            return
        self.inbox_paste_text.delete("1.0", "end")
        self._refresh_inbox_status()
        self._append_status("[saved response to inbox]")

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

        files = []
        seen = set()
        for t in tasks:
            for p in t.files:
                key = p.as_posix()
                if key not in seen:
                    seen.add(key)
                    files.append(p)

        body, total_lines, per_file, bodies = context_pack.build_pack(
            files, self.root_dir, fence=True
        )
        self.current_tasks = tasks
        self._refresh_inbox_section()

        self.pack_text.delete("1.0", "end")
        self.pack_text.insert("1.0", body)

        prompt_body = "\n\n".join(t.prompt for t in tasks if t.prompt)
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

        self.status_label.config(text=self._status_text(tasks, per_file, total_lines, len(body)))
        self.fit_label.config(text=self._fit_text(per_file, len(body)))
        self.picker_frame.pack_forget()
        self.pack_frame.pack(fill="both", expand=True)

    def _status_text(self, tasks, per_file, total_lines, n_chars):
        classes = sorted({t.task_class for t in tasks})
        routes = sorted({t.route for t in tasks})
        title = tasks[0].header if len(tasks) == 1 else f"{len(tasks)} tasks"
        parts = [
            f"{title} · Class {'/'.join(classes)} · routed to {'/'.join(routes)} · "
            f"{len(per_file)} files, {total_lines} lines, {n_chars} chars"
        ]
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

    def _append_status(self, extra):
        self.status_label.config(text=self.status_label.cget("text") + "\n" + extra)

    def _on_back_to_picker(self):
        self.pack_frame.pack_forget()
        self.picker_frame.pack(fill="both", expand=True)

    def _refresh_pack_view(self):
        """Toggle between the full-text box (checked) and the paginated chunk stepper
        (unchecked) — only one occupies the pack screen's main content area at a time.
        Anchored after=prompt_text (not before=prompt_label) so the editable prompt/task
        description always reads above the read-only context blob, regardless of
        whether the inbox section below has already been packed by this point."""
        if self.ignore_char_limit.get():
            self.chunk_frame.pack_forget()
            self.pack_text.pack(fill="both", expand=True, pady=(6, 6), after=self.prompt_text)
        else:
            self.pack_text.pack_forget()
            self.chunk_frame.pack(fill="both", expand=True, pady=(6, 6), after=self.prompt_text)
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

    def _combined_text(self):
        """Prompt plus whichever pack view is currently active — the full concatenated
        block when ignore_char_limit is checked, or just the on-screen chunk when it's
        not, so Copy/Save actually track what pagination is showing instead of always
        grabbing the whole pack behind the paginated view's back."""
        prompt = self.prompt_text.get("1.0", "end").strip()
        if self.ignore_char_limit.get():
            pack = self.pack_text.get("1.0", "end").strip()
        else:
            pack = self.chunks[self.chunk_idx].strip() if self.chunks else ""
        return (prompt + "\n\n---\n\n" + pack) if prompt else pack

    def _on_copy(self):
        self.clipboard_clear()
        self.clipboard_append(self._combined_text())
        self._append_status("[copied to clipboard]")

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
        win.geometry("820x640")
        box = scrolledtext.ScrolledText(win, wrap="word")
        box.pack(fill="both", expand=True)
        box.insert("1.0", text)

        def copy():
            self.clipboard_clear()
            self.clipboard_append(text)

        def save():
            path = filedialog.asksaveasfilename(defaultextension=".md", initialfile="response.md")
            if path:
                Path(path).write_text(text, encoding="utf-8")

        btns = ttk.Frame(win)
        btns.pack(fill="x")
        ttk.Button(btns, text="Copy", command=copy).pack(side="left", padx=6, pady=6)
        ttk.Button(btns, text="Save", command=save).pack(side="left")
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right", padx=6)

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
            bottom, text="Send", style="Big.TButton", command=self._on_send_from_settings
        )
        self.btn_send.pack(side="right")
        self.send_status_label = ttk.Label(bottom, text="", foreground=gui_theme.COLOR_MUTED)
        self.send_status_label.pack(side="right", padx=12)

        ttk.Label(
            f,
            text="Where this pack gets sent, and what it'll look like on the wire:",
            font=("", 11, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        target_row = ttk.Frame(f)
        target_row.pack(anchor="w", pady=(0, 6))
        ttk.Label(target_row, text="Send target:").pack(side="left")
        ttk.Radiobutton(
            target_row,
            text="Qwen (local LM Studio)",
            value="qwen",
            variable=self.send_target,
            command=self._on_target_changed,
        ).pack(side="left", padx=(6, 12))
        ttk.Radiobutton(
            target_row,
            text="OpenRouter (cloud)",
            value="openrouter",
            variable=self.send_target,
            command=self._on_target_changed,
        ).pack(side="left")

        endpoint_row = ttk.Frame(f)
        endpoint_row.pack(fill="x", pady=(0, 6))
        ttk.Label(endpoint_row, text="Endpoint URL:").pack(side="left")
        ttk.Entry(endpoint_row, textvariable=self.send_endpoint, width=50).pack(side="left", padx=6)
        ttk.Button(endpoint_row, text="Reset to default", command=self._reset_endpoint).pack(
            side="left"
        )

        self.model_row = ttk.Frame(f)
        self.model_row.pack(fill="x", pady=(0, 6))

        key_row = ttk.Frame(f)
        key_row.pack(fill="x", pady=(0, 6))
        ttk.Label(key_row, text="OpenRouter API key:").pack(side="left")
        self.api_key_entry = ttk.Entry(key_row, textvariable=self.send_api_key, show="*", width=40)
        self.api_key_entry.pack(side="left", padx=6)
        self.remember_check = ttk.Checkbutton(
            key_row,
            text=f"Remember on this machine (plaintext {OPENROUTER_KEY_FILE.name} in home dir)",
            variable=self.remember_key,
            command=self._on_remember_toggled,
        )
        self.remember_check.pack(side="left", padx=(6, 0))

        tokens_row = ttk.Frame(f)
        tokens_row.pack(fill="x", pady=(0, 6))
        ttk.Label(tokens_row, text="Max tokens:").pack(side="left")
        ttk.Entry(tokens_row, textvariable=self.send_max_tokens, width=8).pack(side="left", padx=6)

        ttk.Button(f, text="Refresh Preview", command=self._refresh_send_preview).pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(f, text="Request preview (API key masked):").pack(anchor="w")
        self.send_preview = scrolledtext.ScrolledText(f, wrap="word", height=18, state="disabled")
        self.send_preview.pack(fill="both", expand=True, pady=(2, 0))

        self._on_target_changed()

    def _build_model_row(self):
        """Rebuilds model_row's contents for the current target — a free-text combobox
        for openrouter, or a read-only detected value + Detect button for qwen, whose
        model comes from LM Studio's /v1/models rather than being chosen here."""
        for child in self.model_row.winfo_children():
            child.destroy()
        ttk.Label(self.model_row, text="Model:").pack(side="left")
        if self.send_target.get() == "openrouter":
            ttk.Combobox(
                self.model_row,
                textvariable=self.send_model_or,
                values=self.openrouter_models,
                width=36,
            ).pack(side="left", padx=6)
            ttk.Button(
                self.model_row,
                text="Fetch free models",
                command=self._fetch_openrouter_models,
            ).pack(side="left", padx=(6, 0))
        else:
            label = self.qwen_detected_model or "(auto-detected at send time)"
            ttk.Label(self.model_row, text=label, foreground=gui_theme.COLOR_MUTED).pack(
                side="left", padx=6
            )
            ttk.Button(self.model_row, text="Detect Now", command=self._detect_qwen_model).pack(
                side="left"
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
        user_msg = self._combined_text()
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

    def __init__(self, app: "App", task: Task | None):
        super().__init__(app)
        self.app = app
        self.task = task
        self._manual_route = None  # round-tripped from an existing task, not settable here
        self.title("Edit Task" if task is not None else "New Task")
        self.geometry("780x700")

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
        self.suffix_warning = None

        self.score_var = tk.StringVar(value="3")
        self.class_var = tk.StringVar(value="2")
        self.title_var = tk.StringVar()
        self.section_var = tk.StringVar(value=sections[0])
        self.is_fenced_var = tk.BooleanVar(value=False)
        self.effort_var = tk.StringVar()

        self._build_widgets(sections)
        if task is not None:
            self._prefill(task)
        self._refresh_effort_preview()

        self.transient(app)
        self.grab_set()

    # ── layout ──

    def _build_widgets(self, sections):
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)

        top = ttk.Frame(f)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Score:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            top, textvariable=self.score_var, values=self.SCORE_VALUES, state="readonly", width=4
        ).grid(row=0, column=1, padx=(4, 16))
        ttk.Label(top, text="Class:").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            top, textvariable=self.class_var, values=self.CLASS_VALUES, state="readonly", width=4
        ).grid(row=0, column=3, padx=(4, 16))
        ttk.Label(top, text="Section:").grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            top, textvariable=self.section_var, values=sections, state="readonly", width=32
        ).grid(row=0, column=5, padx=(4, 0))

        title_row = ttk.Frame(f)
        title_row.pack(fill="x", pady=(0, 8))
        ttk.Label(title_row, text="Title:").pack(side="left")
        ttk.Entry(title_row, textvariable=self.title_var).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )

        if self.task is not None:
            self.suffix_warning = ttk.Label(f, text="", foreground="#a00", wraplength=740)
            self.suffix_warning.pack(anchor="w", pady=(0, 4))

        ttk.Label(f, text="Description:").pack(anchor="w")
        self.body_text = scrolledtext.ScrolledText(f, wrap="word", height=6)
        self.body_text.pack(fill="x", pady=(2, 4))
        ttk.Checkbutton(
            f,
            text="Treat description as a fenced ```text prompt block (sent to the model verbatim)",
            variable=self.is_fenced_var,
        ).pack(anchor="w", pady=(0, 8))

        grid = ttk.Frame(f)
        grid.pack(fill="both", expand=True, pady=(0, 8))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)
        positions = {"Implement": (0, 0), "Context": (0, 1), "Write": (1, 0), "Read": (1, 1)}
        for label, (row, col) in positions.items():
            self._build_file_group(grid, label, row, col)

        bottom = ttk.Frame(f)
        bottom.pack(fill="x", pady=(4, 0))
        ttk.Label(bottom, textvariable=self.effort_var, foreground=gui_theme.COLOR_MUTED).pack(
            side="left"
        )
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Save", command=self._on_save_clicked).pack(
            side="right", padx=(0, 6)
        )

    def _build_file_group(self, parent, label, row, col):
        box = ttk.LabelFrame(parent, text=label, padding=6)
        box.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)

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

    # ── prefill (edit only) ──

    def _prefill(self, task: Task):
        block = self.app.roadmap_lines[task.start : task.end]
        fields = parse_task_fields(block)
        self.score_var.set(fields["score"] or "3")
        self.class_var.set(fields["task_class"] or "2")
        self.title_var.set(fields["title"])
        self.section_var.set(task.section or self.section_var.get())
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
        self._refresh_effort_preview()

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
        self._refresh_effort_preview()

    def _remove_selected(self, label):
        lb = self.listboxes[label]
        for idx in reversed(lb.curselection()):
            del self.file_lists[label][idx]
        self._refresh_listbox(label)
        self._refresh_effort_preview()

    def _refresh_effort_preview(self):
        effort = compute_task_effort(self.file_lists, self.app.root_dir)
        self.effort_var.set(f"Effort (auto-computed on save): ~{effort}")

    # ── save ──

    def _collect_fields(self) -> dict:
        return {
            "score": self.score_var.get(),
            "task_class": self.class_var.get(),
            "title": self.title_var.get().strip(),
            "section": self.section_var.get(),
            "body": self.body_text.get("1.0", "end").strip(),
            "is_fenced": self.is_fenced_var.get(),
            "file_fields": self.file_lists,
            "manual_route": self._manual_route,
        }

    def _on_save_clicked(self):
        fields = self._collect_fields()
        err = validate_task_fields(fields)
        if err:
            messagebox.showerror("Cannot save", err, parent=self)
            return

        block = build_task_lines(fields)
        try:
            if self.task is None:
                result = insert_task_block(self.app.roadmap_lines, fields["section"], block)
                # pure addition -- no overwrite, no confirm needed
            else:
                if not messagebox.askyesno(
                    "Overwrite task?",
                    "This replaces the existing task's content in roadmap.md. This cannot "
                    "be undone from within Quest Board. Continue?",
                    parent=self,
                ):
                    return
                if fields["section"] == self.task.section:
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
        except ValueError as e:
            messagebox.showerror("Cannot save", str(e), parent=self)
            return

        try:
            route_tasks.write_roadmap(self.app.ROADMAP_PATH, self.app.roadmap_lines, result)
        except RuntimeError as e:
            messagebox.showerror("Save failed", str(e), parent=self)
            return
        self.app._load_tasks()  # re-derives Route/Effort/Chars via the existing refresh pipeline
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
