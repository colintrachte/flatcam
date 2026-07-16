"""
task_records.py — Quest Board's domain task record and roadmap read model.

Owns task parsing, relationship derivation, and readiness views shared by the
Quest Board controller and task editor. It does not write roadmap files.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import route_tasks

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
    r"^\s+\*\*(Implement|Write|Context|Read|Evidence)"
    r"(?:\s+\([^*]*\))?:\*\*\s*(.+)",
    re.IGNORECASE,
)
ROUTE_VALUE_RE = re.compile(r"^\s*\*\*Route:\*\*\s*(.+?)\s*$")
CONTEXT_LOAD_VALUE_RE = re.compile(
    r"^\s*\*\*(?:Context Load|Effort):\*\*\s*(.+?)\s*$", re.IGNORECASE
)
EFFORT_VALUE_RE = CONTEXT_LOAD_VALUE_RE  # legacy import compatibility
CHARS_VALUE_RE = re.compile(r"^\s*\*\*Chars:\*\*\s*(.+?)\s*$")
FENCE_START_RE = re.compile(r"^\s*```text\s*$")
FENCE_END_RE = re.compile(r"^\s*```\s*$")


def split_header(header: str) -> tuple[str, str]:
    """Break a task header into (score, title), for table columns."""
    m = HEADER_ATTR_RE.match(header)
    if not m:
        return "", header
    return m.group("score"), m.group("title")


@dataclass
class Task:
    header: str
    task_class: str
    id: str = ""
    status: str = ""
    section: str = ""  # nearest preceding ##/### heading this task falls under
    route: str = "?"
    context_load: str = "?"
    files: list[Path] = field(default_factory=list)  # resolved, existing paths, in file-list order
    missing: list[str] = field(
        default_factory=list
    )  # raw backtick strings that didn't resolve to a file
    prompt: str = ""  # extracted ```text block body, if the item has one
    start: int = -1  # index into the parsed lines[] of this task's header
    end: int = -1  # exclusive end index (route_tasks.scan_block_end)
    dependencies: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    readiness_gaps: list[str] = field(default_factory=list)
    artifacts: list[dict[str, str]] = field(default_factory=list)

    @property
    def effort(self) -> str:
        """Read-compatible alias for callers migrating from generated Effort."""
        return self.context_load


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
        relationships = route_tasks.task_relationships_of(block)
        task.dependencies = relationships["dependencies"]
        task.parents = relationships["parents"]
        task.supersedes = relationships["supersedes"]
        task.related = relationships["related"]

        seen = set()
        in_fence = False
        fence_lines = []
        body_lines = []
        for bl in block:
            idm = route_tasks.ID_RE.match(bl)
            if idm:
                task.id = idm.group(1)
                continue
            statusm = route_tasks.STATUS_RE.match(bl)
            if statusm:
                task.status = route_tasks.task_status_of([bl]) or ""
                continue
            rm = ROUTE_VALUE_RE.match(bl)
            if rm:
                task.route = rm.group(1)
                continue
            load_match = CONTEXT_LOAD_VALUE_RE.match(bl)
            if load_match:
                task.context_load = load_match.group(1)
                continue
            if CHARS_VALUE_RE.match(bl):
                continue
            fm = FILE_LIST_RE.match(bl)
            if fm:
                for raw in route_tasks.BACKTICK_RE.findall(fm.group(2)):
                    task.artifacts.append({"role": fm.group(1).lower(), "path": raw})
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


def derive_reverse_relationships(tasks: list[Task]) -> None:
    """Populate reverse and symmetric in-memory edges from authored forward edges."""
    by_id = {task.id: task for task in tasks if task.id}
    for task in tasks:
        task.blocks = []
        task.children = []
        task.superseded_by = []
        task.related = list(dict.fromkeys(task.related))
    for task in tasks:
        if not task.id:
            continue
        for relationship_field, reverse in (
            ("dependencies", "blocks"),
            ("parents", "children"),
            ("supersedes", "superseded_by"),
        ):
            for target_id in getattr(task, relationship_field):
                target = by_id.get(target_id)
                if target is not None and task.id not in getattr(target, reverse):
                    getattr(target, reverse).append(task.id)
        for target_id in list(task.related):
            target = by_id.get(target_id)
            if target is not None and task.id not in target.related:
                target.related.append(task.id)


def ready_tasks(tasks: list[Task], status_map: dict[str, str]) -> list[Task]:
    """Return explicitly Ready tasks whose blocking dependencies are all Shipped."""
    return [
        task
        for task in tasks
        if task.status == "Ready"
        and all(status_map.get(task_id) == "Shipped" for task_id in task.dependencies)
    ]


def blocker_summary(task: Task, tasks_by_id: dict[str, Task], status_map: dict[str, str]) -> str:
    """Describe dependency and readiness blockers in the picker's derived column."""
    blockers = []
    for dependency in task.dependencies:
        status = status_map.get(dependency)
        if status == "Shipped":
            continue
        target = tasks_by_id.get(dependency)
        label = split_header(target.header)[1] if target is not None else dependency
        blockers.append(f"{label} ({status or 'missing'})")
    blockers.extend(
        gap.removesuffix(".")
        for gap in task.readiness_gaps
        if not gap.startswith("Dependency ") and gap != "A Blocked task cannot be Ready."
    )
    if blockers:
        return "; ".join(blockers)
    if task.status == "Blocked":
        return "Blocked status has no dependency/reason"
    if task.status in {"Draft", "Defined"}:
        return "No readiness gap — promote to Ready"
    return ""


def task_order_advisories(tasks: list[Task], status_map: dict[str, str]) -> list[str]:
    """Return advisory reasons selected tasks have unresolved execution blockers."""
    advisories = []
    for task in tasks:
        _, title = split_header(task.header)
        reasons = []
        if task.status == "Blocked":
            reasons.append("status is Blocked")
        open_dependencies = [
            dependency
            for dependency in task.dependencies
            if status_map.get(dependency) != "Shipped"
        ]
        if open_dependencies:
            reasons.append(f"{len(open_dependencies)} open blocker(s)")
        if reasons:
            advisories.append(f"{title}: {', '.join(reasons)}")
    return advisories
