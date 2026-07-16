"""
pack_delivery.py — Quest Board prompt, chunk, send-key, and response-inbox mechanics.

Keeps model-facing pack preparation and response capture independent from the
Tk controller. Network request execution remains in query_model.py.
"""

import contextlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import context_pack
import executor_registry
import route_tasks
from task_records import Task, split_header

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


def compact_context_body(text: str) -> str:
    """Collapse consecutive empty lines in a model-facing context body.

    Preserve every nonempty line verbatim, including whitespace-bearing lines: those may
    be meaningful inside a string literal or as Markdown hard breaks. The source file and
    context_pack.py's CLI output remain untouched; Pack Task applies this only to page 2.
    """
    result = []
    previous_empty = False
    for line in text.splitlines():
        if line == "":
            if previous_empty:
                continue
            previous_empty = True
        else:
            previous_empty = False
        result.append(line)
    return "\n".join(result)


def build_task_prompt(tasks: list[Task]) -> str:
    """Build the editable, model-facing prompt for one or more packed tasks.

    The roadmap description remains the main instruction, but the title, section, and
    review class previously existed only in non-selectable GUI labels. Include that
    task-defining metadata here so manual Copy/Save and programmatic sends carry it too.
    UI-only routing and model-fit diagnostics deliberately stay out of the prompt.
    """
    prompts = []
    for task in tasks:
        _, title = split_header(task.header)
        lines = [f"Task: {title}"]
        if task.section:
            lines.append(f"Roadmap section: {task.section}")
        if task.id:
            lines.append(f"Task ID: {task.id}")
        if task.status:
            lines.append(f"Status: {task.status}")
        lines.append(f"Review class: Class {task.task_class}")
        if task.task_class == "3":
            lines.append(
                "Review boundary: model output is research only and must not be applied "
                "without human review."
            )
        if task.prompt:
            lines.extend(["", task.prompt])
        prompts.append("\n".join(lines))
    return "\n\n---\n\n".join(prompts)


PORTABLE_MODE = "portable"
REPOSITORY_MODE = "repository-aware"


def build_repository_handoff(tasks: list[Task], executor_id: str) -> str:
    """Build a stable compact handoff containing task records and artifact paths only."""
    resolved = executor_registry.resolve_pool(executor_id)
    if not executor_registry.executor_has_capability(resolved, "repository-access"):
        raise ValueError(f"executor {executor_id!r} is not repository-aware")
    records = []
    for task in tasks:
        _score, title = split_header(task.header)
        records.append(
            {
                "task_id": task.id,
                "title": title,
                "section": task.section,
                "status": task.status,
                "review_class": int(task.task_class),
                "route": task.route,
                "task_text": task.prompt,
                "artifacts": task.artifacts,
            }
        )
    payload = {
        "schema_version": 1,
        "delivery_mode": REPOSITORY_MODE,
        "executor": resolved,
        "tasks": records,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def select_handoff(tasks, portable_text: str, executor_id: str, requested_mode: str):
    """Return (text, effective mode), falling back safely for ineligible executors."""
    if requested_mode != REPOSITORY_MODE:
        return portable_text, PORTABLE_MODE
    try:
        return build_repository_handoff(tasks, executor_id), REPOSITORY_MODE
    except ValueError:
        return portable_text, PORTABLE_MODE


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
ASSIMILATED_DIRNAME = "assimilated"
TASK_SLUG_RE = re.compile(r"[^a-z0-9]+")
INBOX_FILENAME_MAX = 20
INBOX_ID_CHARS = 8
SLOP_FILTER_OFF = "Off (verbatim)"
SLOP_FILTER_CONSERVATIVE = "Conservative"
SLOP_FILTER_MODES = (SLOP_FILTER_OFF, SLOP_FILTER_CONSERVATIVE)
FENCE_MARKER_RE = re.compile(r"^\s*(?P<marker>`{3,}|~{3,})")

# Exact boundary paragraphs only. Broader "sounds like filler" matching risks deleting a
# caveat or proposed next step, which would violate the filter's meaning-preservation rule.
CHAT_PREAMBLES = {
    "absolutely!",
    "certainly!",
    "here is the requested response:",
    "here's the requested response:",
    "of course!",
    "sure!",
    "sure, here is the requested response:",
    "sure, here's the requested response:",
    "sure — here is the requested response:",
    "sure — here's the requested response:",
}
CHAT_FOLLOWUPS = {
    "hope this helps!",
    "i hope this helps!",
    "let me know if you'd like anything else.",
    "let me know if you need anything else.",
}
# Exact non-content artifacts observed in saved responses. These can occur between useful
# sections when several model outputs are pasted into one inbox save, so boundary-only
# matching is insufficient. Keep this a whitelist: generic "download" or question matching
# could remove real implementation instructions.
CHAT_UI_ARTIFACTS = {
    "download the implementation bundle",
    "download the unified patch",
}
CHAT_INLINE_OFFERS = {
    "would you like to adjust the error logging behavior to bubble up an explicit "
    "exception instead of printing to stderr and continuing with the remaining files?",
}


def task_slug(title: str) -> str:
    """Return a lowercase, filesystem-safe rendering of a task title."""
    slug = TASK_SLUG_RE.sub("-", title.lower()).strip("-")
    return slug[:60].strip("-") or "task"


def response_work_dirs(root: Path) -> tuple[Path, Path]:
    """Return the inbox and assimilated directories beside the helper scripts."""
    helper_dir = root / "helper_scripts"
    return helper_dir / AI_INBOX_DIRNAME, helper_dir / ASSIMILATED_DIRNAME


def ensure_response_work_dirs(root: Path) -> tuple[Path, Path]:
    """Create Pack Task's local response directories when either is missing."""
    directories = response_work_dirs(root)
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def inbox_path(root: Path, title: str, task_id: str = "") -> Path:
    """Return a short, recognizable inbox path; identity remains inside the file."""
    inbox_dir, _assimilated_dir = response_work_dirs(root)
    extension = ".md"
    stem_chars = INBOX_FILENAME_MAX - len(extension)
    title_part = task_slug(title)
    if task_id:
        id_part = task_id.removeprefix("task_")[:INBOX_ID_CHARS]
        title_chars = stem_chars - len(id_part) - 1
        stem = f"{id_part}-{title_part[:title_chars]}"
    else:
        stem = title_part[:stem_chars]
    return inbox_dir / f"{stem}{extension}"


def _boundary_paragraph(lines: list[str], first: bool) -> tuple[int, int, str]:
    """Return (start, end, normalized text) for the first/last nonblank paragraph."""
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    if start == end:
        return start, end, ""
    if first:
        para_end = start
        while para_end < end and lines[para_end].strip():
            para_end += 1
        end = para_end
    else:
        para_start = end - 1
        while para_start > start and lines[para_start - 1].strip():
            para_start -= 1
        start = para_start
    normalized = " ".join(line.strip() for line in lines[start:end]).casefold()
    return start, end, normalized.replace("’", "'")


def _remove_exact_chat_boilerplate(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start, end, paragraph = _boundary_paragraph(lines, first=True)
    if paragraph in CHAT_PREAMBLES:
        del lines[start:end]
    start, end, paragraph = _boundary_paragraph(lines, first=False)
    if paragraph in CHAT_FOLLOWUPS:
        del lines[start:end]
    return "".join(lines)


def _remove_exact_chat_artifacts(text: str) -> str:
    """Remove whitelisted UI/interaction artifacts outside fenced code.

    An inline offer may be glued to the next response's heading on the same line. Remove
    only its exact prefix and retain the suffix; unknown questions and download references
    remain untouched.
    """
    result = []
    fence_char = None
    fence_length = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        ending = raw_line[len(line) :]
        marker_match = FENCE_MARKER_RE.match(line)
        marker = marker_match.group("marker") if marker_match else ""
        if fence_char is not None:
            result.append(raw_line)
            if marker and marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
                fence_length = 0
            continue
        if marker:
            fence_char = marker[0]
            fence_length = len(marker)
            result.append(raw_line)
            continue

        normalized = " ".join(line.strip().split()).casefold().replace("’", "'")
        if normalized in CHAT_UI_ARTIFACTS:
            continue
        offer = next((item for item in CHAT_INLINE_OFFERS if normalized.startswith(item)), None)
        if offer is not None:
            # The whitelist is normalized, so locate the question mark in the original
            # line rather than slicing it by the normalized string's length.
            question_end = line.find("?")
            suffix = line[question_end + 1 :].lstrip()
            if suffix:
                result.append(suffix + ending)
            continue
        result.append(raw_line)
    return "".join(result)


def _collapse_blank_lines_outside_fences(text: str) -> str:
    """Collapse repeated blank lines while preserving code-fence contents line-for-line."""
    result = []
    fence_char = None
    fence_length = 0
    unclosed_start = None
    unclosed_result_index = None
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        marker_match = FENCE_MARKER_RE.match(line)
        marker = marker_match.group("marker") if marker_match else ""
        if fence_char is not None:
            result.append(line)
            if marker and marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
                fence_length = 0
                unclosed_start = None
                unclosed_result_index = None
            offset += len(raw_line)
            continue
        if marker:
            fence_char = marker[0]
            fence_length = len(marker)
            unclosed_start = offset
            unclosed_result_index = len(result)
            result.append(line)
        elif line.strip():
            result.append(line)
        elif result and result[-1] != "":
            result.append("")
        offset += len(raw_line)
    if fence_char is not None:
        prefix = "\n".join(result[:unclosed_result_index])
        remainder = text[unclosed_start:]
        return f"{prefix}\n{remainder}" if prefix else remainder
    while result and result[-1] == "":
        result.pop()
    return "\n".join(result)


def filter_response_text(response_text: str, mode: str) -> str:
    """Apply the selected deterministic slop filter without summarizing or paraphrasing.

    Conservative mode removes only exact conversational boundary paragraphs, whitelisted
    UI/interaction artifacts, and excess blank lines outside fenced code. Off returns the
    supplied response character-for-character; callers are responsible for excluding a
    text widget's synthetic trailing newline.
    """
    if mode == SLOP_FILTER_OFF:
        return response_text
    if mode != SLOP_FILTER_CONSERVATIVE:
        raise ValueError(f"unknown slop filter mode: {mode}")
    without_boilerplate = _remove_exact_chat_boilerplate(response_text)
    without_artifacts = _remove_exact_chat_artifacts(without_boilerplate)
    return _collapse_blank_lines_outside_fences(without_artifacts)


def count_inbox_responses(path: Path) -> int:
    """Number of responses already saved for a task, for the GUI's status line -- counts
    the '<!-- saved ... -->' markers append_inbox_response() writes; 0 if the file doesn't
    exist yet."""
    if not path.is_file():
        return 0
    return path.read_text(encoding="utf-8").count("<!-- saved ")


def append_inbox_response(
    path: Path,
    title: str,
    response_text: str,
    filter_mode: str = SLOP_FILTER_OFF,
    task_id: str = "",
) -> int:
    """Append one pasted AI response to a task's inbox file, atomically (temp-file-then-
    rename, matching route_tasks._atomic_write's own pattern) -- creates ai_inbox/ and the
    file on first use. Never drops a previous response, only adds. Returns the number of
    characters removed by the selected filter; raises ValueError on empty filtered input.
    """
    filtered = filter_response_text(response_text, filter_mode)
    if not filtered.strip():
        raise ValueError("response text is empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        if task_id:
            recorded_id = f"**Task ID:** {task_id}"
            if not existing.startswith(recorded_id + "\n"):
                raise ValueError(
                    f"inbox filename collision: {path.name} does not belong to {task_id}"
                )
    else:
        identity = f"**Task ID:** {task_id}\n\n" if task_id else ""
        existing = f"{identity}# {title}\n"
    if not existing.endswith("\n"):
        existing += "\n"
    removed = max(0, len(response_text) - len(filtered))
    block = (
        f"\n<!-- saved {timestamp} · slop filter: {filter_mode} · "
        f"removed {removed} chars -->\n\n{filtered}"
    )
    if not block.endswith("\n"):
        block += "\n"
    route_tasks._atomic_write(path, existing + block)
    return removed
