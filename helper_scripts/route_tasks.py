"""
route_tasks.py — annotate roadmap task items with AI routing recommendations

Reads docs/roadmap.md, applies the routing rules from docs/ai-harness.md §2,
and inserts or updates a **Route:** metadata line on each open task item.
Completed tasks (- [x]) and tasks with no parseable file lists are skipped.

Usage:
    python helper_scripts/route_tasks.py [--dry-run] [--check] [--roadmap PATH]
    python helper_scripts/route_tasks.py --migrate-ids [--dry-run] [--include-shipped]
    python helper_scripts/route_tasks.py --complete "ID" [--shipped PATH] [--dry-run]

With --dry-run, prints the annotated roadmap to stdout instead of updating the file.
With --check, exits non-zero (and prints nothing to the file) if any generated annotation
annotation would change — useful for a pre-commit or CI gate that catches a
roadmap edited without re-running this script.

With --complete "ID", marks the identified open task done and moves it into --shipped
(default docs/shipped.md), stripping its generated
Route/Context Load/Chars lines in the process (see ROADMAP.template.md's instantiation
note — those don't matter once a task has shipped). This is the mechanical half of
finishing a task: an implementing AI or human edits the task's own text first if its
scope changed during implementation, then runs --complete to do the flip-and-move
instead of hand-editing both files. Errors if zero or more than one open task
matches ID. Title-fragment lookup remains available only for legacy ID-less tasks.

With --migrate-ids, inserts deterministic permanent IDs into legacy tasks without
reformatting any other content. --dry-run is an exact preview; --include-shipped shares
the collision set with shipped history.

Routing (mirrors docs/ai-harness.md §2, first match wins):
    Class 3 in header    -> claude   (never free-tier for implementation)
    multiple projects    -> paid-ai  (Codex or Claude; free-tier cannot synthesize them)
    total files == 0     -> (skip)   (no file list to reason from; set manually)
    total files <= 3     -> gemini   (mechanical, small, well-specified)
    total files <= 20    -> kimi     (bounded component, one session)
    total files > 20     -> claude   (spans components, too large for free-tier)

    total chars exceeds context_pack.py's DEFAULT_MAX_CHARS (currently 100,000)
        -> bump one tier heavier (gemini->kimi, kimi->claude), regardless of
           file count alone -- see docs/ai-harness.md §2 rule 4a/5a and §7.

"Total files" = count of · -separated entries across all **Implement:**,
**Implement (...):**,  **Context:**, **Write:**, **Read:**, **Read (...):** lines.
The class is read from the task's header line (- [ ] **...**) only, not the body.
Lifecycle status controls readiness, not task analysis. Every open task receives generated
routing annotations when it has a parseable file list; only Ready tasks belong in the
derived execution queue.

The roadmap is written via a temp-file-then-atomic-rename (roadmap.md.new ->
roadmap.md) after a basic sanity check on the output, so a bug in this script
cannot leave the canonical planning doc half-written or truncated.

Judgment/tradeoff tasks and external-knowledge lookups are not auto-detected; set
their **Route:** manually to meta or perplexity after this script runs by appending
" (manual)" to the value (e.g. "**Route:** perplexity (manual)") — a Route line
ending in that suffix is a human override and is never re-stamped by a later run.
Context Load/Chars are still re-derived around it, since those stay mechanical either way.

Class 3 portions mentioned in a task body (e.g. "Class 3 for that one line")
do not change the routing — but they are never unattended regardless of what
**Route:** says. The routing annotation only governs which model drafts the
Class 2/1 portions.

Alongside **Route:**, this script also stamps **Chars:** — the total and
largest-single-file character counts for the task's resolved file list, per
context_pack.py's MODEL_BUDGETS. This surfaces a chatgpt-viability problem
(a single file already over its ~10,000-char inline-paste budget) without
having to run context_pack.py first: chunking bins whole files together and
never splits one, so an oversized single file makes chatgpt unusable for
that task no matter how the rest is trimmed.

It also stamps **Context Load:** — a packaging-burden score (not labor or time),
computed as max(1, round(total_files * total_text_chars / 1000)),
reusing the same resolved file list and char counts already gathered for
**Chars:** rather than any new file-classification logic.

The header's own `Score <1-5> <medal> · Class <1-3>` token is self-healing:
every run re-derives the medal from the parsed Score (score >= 4 -> gold,
score == 3 -> silver, score <= 2 -> bronze) and rewrites the header's medal
glyph if it doesn't match — the same spirit as the Route/Chars re-stamp.
The Score number is the single source of truth; the medal never drifts
independently.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_pack  # noqa: E402
import executor_registry  # noqa: E402

# Windows consoles default to CP1252; force UTF-8 so emoji in roadmap prints intact.
for _stream in (sys.stdout, sys.stderr):
    _reconfig = getattr(_stream, "reconfigure", None)
    if callable(_reconfig):
        _reconfig(encoding="utf-8")

# Matches any task list item (open or closed)
TASK_RE = re.compile(r"^- \[([ x])\]")

# Class extracted from the header line only
CLASS_RE = re.compile(r"Class\s+([123])")

# Score extracted from the header line only
SCORE_RE = re.compile(r"Score\s+([1-5])")

# Any bold metadata field that lists files: Implement, Write, Context, Read, Read (...)
FILE_META_RE = re.compile(
    r"^\s+\*\*(?:Implement|Write|Context|Read|Evidence)"
    r"(?:\s+\([^*]*\))?:\*\*\s*(.+)",
    re.IGNORECASE,
)

# Authored task-record fields. IDs are permanent once assigned; status and the other
# lifecycle fields are edited by a human-facing frontend and never mechanically restamped.
TASK_ID_RE = re.compile(r"^task_[0-9a-f]{32}$")
ID_RE = re.compile(r"^\s+\*\*ID:\*\*\s*(\S+)\s*$", re.IGNORECASE)
STATUS_RE = re.compile(r"^\s+\*\*Status:\*\*\s*(.+?)\s*$", re.IGNORECASE)
EXECUTION_MODE_RE = re.compile(r"^\s+\*\*Execution mode:\*\*\s*(.+?)\s*$", re.IGNORECASE)
CAPABILITY_RE = re.compile(r"^\s+\*\*Capability:\*\*\s*(.+?)\s*$", re.IGNORECASE)
CONSTRAINT_RE = re.compile(r"^\s+\*\*Constraint:\*\*\s*(.+?)\s*$", re.IGNORECASE)
RELATIONSHIP_RE = re.compile(
    r"^\s+\*\*(Dependency|Blocked by|Parent|Supersedes|Related):\*\*\s*(\S+)\s*$",
    re.IGNORECASE,
)
RELATIONSHIP_FIELDS = {
    "dependency": "dependencies",
    "blocked by": "dependencies",
    "parent": "parents",
    "supersedes": "supersedes",
    "related": "related",
}
LIFECYCLE_STATUSES = (
    "Draft",
    "Defined",
    "Ready",
    "In Progress",
    "Blocked",
    "Verification",
    "Shipped",
)

# Existing generated annotations. Effort remains a read/migration alias.
ROUTE_RE = re.compile(r"^\s+\*\*Route:\*\*.*")
EFFORT_RE = re.compile(r"^\s+\*\*Effort:\*\*.*")
CONTEXT_LOAD_RE = re.compile(r"^\s+\*\*Context Load:\*\*.*", re.IGNORECASE)
CHARS_RE = re.compile(r"^\s+\*\*Chars:\*\*.*")

# A **Route:** line ending in "(manual)" is a human override (see module docstring) —
# route_tasks.py must never clobber it, even though Route is otherwise fully generated.
MANUAL_ROUTE_RE = re.compile(r"^\s+\*\*Route:\*\*.*\(manual\)\s*$")

# Line patterns that terminate a task block
BLOCK_END_RE = re.compile(r"^(##|---)")

# Backtick span inside a file-list value. A span sometimes quotes a
# function/identifier instead of a path (e.g. "add `handle_api_scheduler_run`
# handler") — PATH_LIKE_RE filters those out, and LINE_RANGE_RE strips a
# trailing ":123-456" so the remainder resolves as a real file.
BACKTICK_RE = re.compile(r"`([^`]+)`")
PATH_LIKE_RE = re.compile(r"[/\\]|\.[A-Za-z0-9]{1,6}$")
LINE_RANGE_RE = re.compile(r":\d+(-\d+)?$")
URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

# A file-list entry like `<name>/relative/path` means "relative/path inside whatever
# external resource `name` refers to" — a reference repo (FluidNC), a vendor SDK, a spec
# doc, anything outside this tree. Not specific to any one such resource: `name` is
# whatever the roadmap author writes, looked up in EXTERNAL_REFS_FILE for what it means.
EXTERNAL_REF_TOKEN_RE = re.compile(r"^<([a-z][a-z0-9_-]*)>/?(.*)$")

# name -> free-text search hint, e.g. {"fluidnc": "FluidNC CNC firmware on GitHub
# (github.com/bdring/FluidNC)"}. Not necessarily a fetchable URL — it may take a model with
# web search to actually locate the file from this hint plus the relative path. Tracked in
# git: this is a project fact ("what does <fluidnc> mean"), not machine-specific state.
EXTERNAL_REFS_FILE = Path(__file__).resolve().parent / "external_refs.json"

# name -> local clone/checkout path, one "name=path" per line. Gitignored: specific to
# this machine. When a name has an entry here, its files resolve straight from disk
# instead of only being described to the AI as something to search for.
EXTERNAL_REF_PATHS_FILE = Path(__file__).resolve().parent / "external_ref_paths.txt"


def _external_refs() -> dict:
    try:
        return json.loads(EXTERNAL_REFS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _external_ref_paths() -> dict[str, str]:
    paths: dict[str, str] = {}
    try:
        text = EXTERNAL_REF_PATHS_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return paths
    for line in text.splitlines():
        name, sep, path = line.strip().partition("=")
        if sep and name:
            paths[name] = path
    return paths


def external_ref_name(missing_entry: str) -> str | None:
    """Extract the `<name>` placeholder from a resolve_file_list() `missing` entry, or
    None if it isn't an external-reference entry at all (a genuine new/placeholder path
    inside this repo)."""
    m = EXTERNAL_REF_TOKEN_RE.match(missing_entry)
    return m.group(1) if m else None


def external_search_hint(missing_entry: str) -> str | None:
    """The registered search hint for a `missing` entry's `<name>` (see EXTERNAL_REFS_FILE),
    or None if that name isn't registered yet."""
    name = external_ref_name(missing_entry)
    return _external_refs().get(name) if name else None


def _count_entries(text):
    """Count · -separated file entries in a metadata value string."""
    parts = [p.strip() for p in text.split("·") if p.strip()]
    return len(parts) if parts else 0


def resolve_file_list(value_text, root):
    """Resolve the backtick-quoted paths in one file-list line's value to real files.

    Returns (files, missing): `files` is existing Path objects (under `root`, or under a
    configured local clone for `<name>`-prefixed entries — see EXTERNAL_REF_PATHS_FILE),
    in encounter order (not de-duplicated — callers dedup across a whole task since the
    same path can recur across Implement:/Context:/etc. lines); `missing` is `<name>/rel`
    for unresolved external-reference entries (reconstructed so the directory-continuation
    shorthand below still yields a full relative path) or the raw backtick string for
    everything else (new/placeholder paths named ahead of creation, or non-path identifiers
    already filtered out by PATH_LIKE_RE).
    """
    ref_paths = _external_ref_paths()
    files = []
    missing = []
    # (name, dir) of the most recently seen `<name>/...` entry, so a bare filename right
    # after it (e.g. "Parser.md" following "<fluidnc>/FluidNC/src/Configuration/_Overview.md")
    # is understood as living in that same directory — the roadmap's own shorthand for
    # listing several files from one external directory without repeating the whole path.
    last_ref = None
    for raw in BACKTICK_RE.findall(value_text):
        if not PATH_LIKE_RE.search(raw):
            continue
        clean = LINE_RANGE_RE.sub("", raw)
        m = EXTERNAL_REF_TOKEN_RE.match(clean)
        name = rel = None
        if m:
            name, rel = m.group(1), m.group(2)
            last_ref = (name, rel.rsplit("/", 1)[0] if "/" in rel else "")
        elif (
            last_ref is not None
            and "/" not in clean
            and "\\" not in clean
            and not (root / clean).is_file()
        ):
            # Only treat a bare filename as "another file in that same external
            # directory" when it isn't already a real local file — otherwise a plain
            # local entry right after a `<name>/...` line (e.g. "main.py") would be
            # silently swallowed into the external ref and never resolved locally.
            name, last_dir = last_ref
            rel = f"{last_dir}/{clean}" if last_dir else clean
        else:
            last_ref = None

        if name is not None and rel is not None:
            local_root = ref_paths.get(name)
            p = Path(local_root) / rel if local_root else None
            if p is not None and p.is_file():
                files.append(p)
                continue
            missing.append(f"<{name}>/{rel}")
            continue

        p = root / clean
        if p.is_file():
            files.append(p)
        else:
            missing.append(raw)
    return files, missing


def scan_block_end(lines, start):
    """Find the end index (exclusive) of a task block beginning at `start` — the first
    line at or after `start` that is a new task header or section boundary, ignoring
    any that fall inside a ``` fence (a fenced code sample in a task body can otherwise
    look like one on its own and end the block early). Shared by every roadmap block
    scanner in this module and in pack_task.py's parse_tasks(), so they can't disagree
    about where one task ends and the next begins."""
    j = start
    in_fence = False
    while j < len(lines):
        if lines[j].lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and (TASK_RE.match(lines[j]) or BLOCK_END_RE.match(lines[j])):
            break
        j += 1
    return j


def task_id_of(block: list[str]) -> str | None:
    """Return one valid task ID, None for a legacy ID-less block, or raise for an
    invalid/multiple ID field. Failing closed keeps identity mistakes from silently
    becoming title-based lookups again."""
    values = [m.group(1) for line in block if (m := ID_RE.match(line))]
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("task has multiple **ID:** fields")
    if not TASK_ID_RE.fullmatch(values[0]):
        raise ValueError(f"invalid task ID {values[0]!r}; expected task_ plus 32 hex characters")
    return values[0]


def task_status_of(block: list[str]) -> str | None:
    """Return the canonical explicit lifecycle status, or None for a legacy task."""
    values = [m.group(1) for line in block if (m := STATUS_RE.match(line))]
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("task has multiple **Status:** fields")
    for status in LIFECYCLE_STATUSES:
        if status.lower() == values[0].lower():
            return status
    raise ValueError(f"unsupported task status {values[0]!r}")


def collect_task_ids(lines: list[str]) -> set[str]:
    """Collect and validate every task ID, rejecting duplicates across the document."""
    ids: set[str] = set()
    i = 0
    while i < len(lines):
        if not TASK_RE.match(lines[i]):
            i += 1
            continue
        end = scan_block_end(lines, i + 1)
        task_id = task_id_of(lines[i:end])
        if task_id:
            if task_id in ids:
                raise ValueError(f"duplicate task ID {task_id}")
            ids.add(task_id)
        i = end
    return ids


def task_relationships_of(block: list[str]) -> dict[str, list[str]]:
    """Return authored forward relationships from one task block.

    ``Dependency`` remains a read-compatible alias for the clearer ``Blocked by``
    presentation. Child, blocks, superseded-by, and reciprocal related edges are
    derived from these forward relationships rather than persisted twice.
    """
    relationships = {field: [] for field in set(RELATIONSHIP_FIELDS.values())}
    for line in block:
        match = RELATIONSHIP_RE.match(line)
        if match:
            relationships[RELATIONSHIP_FIELDS[match.group(1).lower()]].append(match.group(2))
    return relationships


def _relationship_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Return directed cycles, with the repeated start ID as the final element."""
    cycles = []
    state = {}
    path = []

    def visit(task_id):
        state[task_id] = "visiting"
        path.append(task_id)
        for reference in graph.get(task_id, []):
            if reference not in graph:
                continue
            if state.get(reference) == "visiting":
                start = path.index(reference)
                cycles.append(path[start:] + [reference])
            elif state.get(reference) is None:
                visit(reference)
        path.pop()
        state[task_id] = "visited"

    for task_id in graph:
        if state.get(task_id) is None:
            visit(task_id)
    return cycles


def validate_task_relationships(lines: list[str]) -> list[str]:
    """Return all missing, self-referential, and cyclic relationship errors."""
    task_ids = collect_task_ids(lines)
    graphs = {field: {} for field in ("dependencies", "parents", "supersedes")}
    errors = []
    i = 0
    while i < len(lines):
        if not TASK_RE.match(lines[i]):
            i += 1
            continue
        end = scan_block_end(lines, i + 1)
        block = lines[i:end]
        task_id = task_id_of(block)
        relationships = task_relationships_of(block)
        if task_id:
            for field, references in relationships.items():
                for reference in references:
                    if not TASK_ID_RE.fullmatch(reference):
                        errors.append(
                            f"{task_id}: {field} reference {reference!r} is not a valid task ID"
                        )
                    elif reference not in task_ids:
                        errors.append(f"{task_id}: {field} reference {reference} does not exist")
                    elif reference == task_id:
                        errors.append(f"{task_id}: self-reference in {field}")
            for field in graphs:
                graphs[field][task_id] = relationships[field]
        elif any(relationships.values()):
            errors.append(f"{block[0].strip()}: relationships require a permanent task ID")
        i = end

    for relationship_field, graph in graphs.items():
        for cycle in _relationship_cycles(graph):
            errors.append(f"cycle in {relationship_field}: {' -> '.join(cycle)}")
    return errors


def _migration_task_id(block: list[str], ordinal: int, existing: set[str]) -> str:
    """Derive a deterministic 128-bit ID for migration, including document order so
    duplicate legacy blocks still differ. Determinism makes --dry-run an exact preview."""
    nonce = 0
    while True:
        seed = f"{ordinal}\0{nonce}\0{''.join(block)}".encode()
        candidate = f"task_{hashlib.sha256(seed).hexdigest()[:32]}"
        if candidate not in existing:
            return candidate
        nonce += 1


def migrate_task_ids(lines: list[str], existing: set[str] | None = None) -> tuple[list[str], int]:
    """Insert only a permanent **ID:** line into each legacy task block.

    Existing blocks and all unrelated prose remain byte-for-byte unchanged. The result
    is idempotent and deterministic, which makes it safe to inspect before writing.
    """
    if existing is None:
        existing = collect_task_ids(lines)
    result: list[str] = []
    added = 0
    ordinal = 0
    i = 0
    while i < len(lines):
        if not TASK_RE.match(lines[i]):
            result.append(lines[i])
            i += 1
            continue
        end = scan_block_end(lines, i + 1)
        block = lines[i:end]
        if task_id_of(block) is None:
            task_id = _migration_task_id(block, ordinal, existing)
            existing.add(task_id)
            block = [block[0], f"  **ID:** {task_id}\n", *block[1:]]
            added += 1
        result.extend(block)
        ordinal += 1
        i = end
    return result, added


def _char_sizes(files, root, text_overrides=None):
    """Per-file (rel, chars) sizes for a task's resolved file list, skipping binaries."""
    text_overrides = text_overrides or {}
    sizes = []
    for f in files:
        if context_pack.is_binary(f):
            continue
        resolved = f.resolve()
        text = text_overrides.get(resolved)
        if text is None:
            text = f.read_text(encoding="utf-8", errors="replace")
        rel = (
            resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else f.as_posix()
        )
        sizes.append((rel, len(text)))
    return sizes


def _chars_line(sizes, binary_files=()):
    """Build text-context metadata and name non-text artifacts without sizing bytes as text."""
    if not sizes and not binary_files:
        return None
    parts = []
    total = sum(c for _, c in sizes)
    note = ""
    if sizes:
        largest_rel, largest_chars = max(sizes, key=lambda t: t[1])
        parts.append(f"~{total:,} text total (largest: {largest_rel} ~{largest_chars:,})")
        chatgpt_cap = context_pack.MODEL_BUDGETS["chatgpt"]["chars"]
        if chatgpt_cap is not None and largest_chars > chatgpt_cap:
            note = (
                f" — exceeds chatgpt's ~{chatgpt_cap:,}-char inline-paste budget; "
                f"that file can't go to chatgpt at all"
            )
    if binary_files:
        names = ", ".join(binary_files)
        parts.append(f"{len(binary_files)} non-text ({names}; preview/inspection required)")
    return f"  **Chars:** {'; '.join(parts)}{note}\n"


def _medal(score):
    """Map a 1-5 Score to its header medal glyph: 5/4 -> gold, 3 -> silver, 2/1 -> bronze."""
    score = int(score)
    if score >= 4:
        return "🥇"
    if score == 3:
        return "🥈"
    return "🥉"


def context_load(total_files, total_chars):
    """Packaging-burden metric; deliberately not an execution-effort estimate."""
    return max(1, round(total_files * total_chars / 1000))


def _context_load_line(total_files, total_chars):
    return f"  **Context Load:** {context_load(total_files, total_chars)}\n"


def _task_requirements(block):
    modes = [m.group(1) for line in block if (m := EXECUTION_MODE_RE.match(line))]
    if len(modes) > 1:
        raise ValueError("task has multiple **Execution mode:** fields")
    capabilities = [m.group(1) for line in block if (m := CAPABILITY_RE.match(line))]
    constraints = [m.group(1) for line in block if (m := CONSTRAINT_RE.match(line))]
    return (modes[0] if modes else "", capabilities, constraints)


def _recommend(
    task_class,
    total_files,
    total_chars,
    project_scopes=1,
    execution_mode="",
    capabilities=(),
    constraints=(),
):
    normalized_mode = executor_registry.normalize_mode(execution_mode) if execution_mode else ""
    if normalized_mode in {"human-judgment", "human-physical"}:
        preferred = "human"
    elif normalized_mode == "deterministic-tooling":
        preferred = "tooling"
    elif normalized_mode == "local-ai":
        preferred = "qwen"
    else:
        preferred = None

    has_authored_requirements = bool(normalized_mode or capabilities or constraints)
    durable_capabilities = list(capabilities)
    if task_class == "3":
        durable_capabilities.append("high-stakes-review")
    if project_scopes > 1:
        durable_capabilities.append("multi-project-synthesis")
    if has_authored_requirements:
        eligible = executor_registry.eligible_executors(
            normalized_mode, durable_capabilities, constraints
        )
        if not eligible:
            detail = ", ".join([normalized_mode, *durable_capabilities, *constraints]).strip(", ")
            raise ValueError(f"no executor satisfies task requirements: {detail}")
        if preferred and preferred in eligible:
            return preferred
        normalized_requirements = {
            executor_registry.normalize_requirement(value)
            for value in [*durable_capabilities, *constraints]
        }
        if normalized_requirements & {
            "high-stakes-review",
            "multi-project-synthesis",
            "paid-only-execution",
        }:
            return "paid-ai"
        return eligible[0]

    if task_class == "3":
        return "claude"
    if project_scopes > 1:
        return "paid-ai"
    if total_files == 0:
        return None  # no file list — skip; needs manual annotation
    if total_files <= 3:
        rec = "gemini"
    elif total_files <= 20:
        rec = "kimi"
    else:
        return "claude"
    # A pack this large needs multiple paste chunks even within a single
    # session (context_pack.py's own chunking threshold — see
    # docs/ai-harness.md §2 rule 4a/5a and §7 for why this reuses that
    # already-measured number instead of a new guess). That much
    # back-and-forth no longer fits the "one bounded session" assumption
    # behind the file-count rules alone, so bump to the next-heavier tier.
    if total_chars > context_pack.DEFAULT_MAX_CHARS:
        return "kimi" if rec == "gemini" else "claude"
    return rec


def _atomic_write(path: Path, text: str):
    """Temp-file-then-atomic-rename write — the one primitive every write of a
    canonical planning file builds on, so a crash mid-write can never leave one
    half-written."""
    tmp_path = path.with_suffix(path.suffix + ".new")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def write_roadmap(path: Path, original_lines: list, result_lines: list) -> int:
    """Safely write a processed roadmap back to disk. Returns the changed-line count.

    Every write of the canonical roadmap's annotations goes through this one function —
    main() below and pack_task.py's GUI refresh both call it, so the GUI can never have
    a laxer write path than the CLI. Guards: refuses to write when the output looks
    truncated (this script only inserts or replaces annotation lines, so a drastic
    shrink means a parsing bug, raised as RuntimeError). Writes nothing when nothing
    changed. (--complete's task removal is a deliberate, much larger shrink by
    construction — it goes through _atomic_write() directly instead of this guard;
    see complete_and_ship().)
    """
    output = "".join(result_lines)
    changed = sum(1 for a, b in zip(original_lines, result_lines, strict=False) if a != b)
    changed += abs(len(result_lines) - len(original_lines))
    if not changed:
        return 0
    if not output.strip() or len(result_lines) < len(original_lines) * 0.5:
        raise RuntimeError(
            f"refusing to write {path} — output looks truncated "
            f"({len(result_lines)} lines vs {len(original_lines)} original); no changes written"
        )
    _atomic_write(path, output)
    return changed


def find_task_block(lines, needle):
    """Locate one open task by exact permanent ID, or by title substring for a legacy
    ID-less task. Once a block has an ID its mutable title is no longer a lookup key."""
    needle = needle.strip()
    by_id = bool(TASK_ID_RE.fullmatch(needle))
    matches = []
    i = 0
    while i < len(lines):
        m = TASK_RE.match(lines[i])
        if not m:
            i += 1
            continue
        j = scan_block_end(lines, i + 1)
        if m.group(1) != "x":
            task_id = task_id_of(lines[i:j])
            if (
                by_id
                and task_id == needle
                or not by_id
                and task_id is None
                and needle.lower() in lines[i].lower()
            ):
                matches.append((i, j))
        i = j
    if not matches:
        kind = "task ID" if by_id else "legacy open task header"
        raise ValueError(f"no {kind} matches {needle!r}")
    if len(matches) > 1:
        titles = "; ".join(lines[s].strip()[:70] for s, _ in matches)
        raise ValueError(
            f"{len(matches)} open tasks contain {needle!r} — be more specific ({titles})"
        )
    return matches[0]


def _replace_status_line(line, status):
    ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    return f"  **Status:** {status}{ending}"


def complete_block(block):
    """Flip a task block's checkbox to [x] and strip Route/Context Load/Chars
    annotations — per ROADMAP.template.md's instantiation note, shipped items keep the
    same format minus those, since they no longer matter once a task is done. Returns
    a new list of lines; does not mutate `block`."""
    block = list(block)
    block[0] = TASK_RE.sub("- [x]", block[0], count=1)
    block = [_replace_status_line(bl, "Shipped") if STATUS_RE.match(bl) else bl for bl in block]
    return [
        bl
        for bl in block
        if not (
            ROUTE_RE.match(bl)
            or EFFORT_RE.match(bl)
            or CONTEXT_LOAD_RE.match(bl)
            or CHARS_RE.match(bl)
        )
    ]


def clear_completed_blocker(roadmap_lines, completed_id):
    """Remove one shipped task from dependent blocker lists.

    A dependent task authored as Blocked becomes Ready only when removing this
    relationship leaves no other blocking dependency. Other lifecycle states and
    non-blocking relationships are preserved.
    """
    result = []
    i = 0
    while i < len(roadmap_lines):
        if not TASK_RE.match(roadmap_lines[i]):
            result.append(roadmap_lines[i])
            i += 1
            continue

        end = scan_block_end(roadmap_lines, i + 1)
        block = []
        removed = False
        for line in roadmap_lines[i:end]:
            match = RELATIONSHIP_RE.match(line)
            if (
                match
                and RELATIONSHIP_FIELDS[match.group(1).lower()] == "dependencies"
                and match.group(2) == completed_id
            ):
                removed = True
                continue
            block.append(line)

        if (
            removed
            and task_status_of(block) == "Blocked"
            and not task_relationships_of(block)["dependencies"]
        ):
            block = [
                _replace_status_line(line, "Ready") if STATUS_RE.match(line) else line
                for line in block
            ]
        result.extend(block)
        i = end
    return result


def move_to_shipped(roadmap_lines, shipped_lines, start, end):
    """Remove the task block roadmap_lines[start:end], mark it done, strip its
    generated annotations, and append it to shipped_lines. Returns (new_roadmap_lines,
    new_shipped_lines); does not mutate either input or touch disk — see
    complete_and_ship() for the file-writing wrapper and its write-ordering rationale.
    """
    source_block = roadmap_lines[start:end]
    completed_id = task_id_of(source_block)
    block = complete_block(source_block)
    while block and not block[-1].strip():
        block.pop()
    new_roadmap_lines = roadmap_lines[:start] + roadmap_lines[end:]
    if completed_id:
        new_roadmap_lines = clear_completed_blocker(new_roadmap_lines, completed_id)
    new_shipped_lines = list(shipped_lines)
    if new_shipped_lines and not new_shipped_lines[-1].endswith("\n"):
        new_shipped_lines[-1] += "\n"
    if new_shipped_lines and new_shipped_lines[-1].strip() != "":
        new_shipped_lines.append("\n")
    new_shipped_lines.extend(block)
    return new_roadmap_lines, new_shipped_lines


def complete_and_ship(roadmap_path: Path, shipped_path: Path, start: int, end: int):
    """Move roadmap_path's task at [start, end) into shipped_path, on disk.

    Writes shipped_path *before* removing the block from roadmap_path. If this process
    is interrupted between the two writes, the task ends up duplicated in both files —
    an annoying but recoverable state a human can fix by hand. Writing in the other
    order would risk deleting the task from the roadmap with nothing durably recorded
    in shipped_path at all, which is unrecoverable. Both writes are individually atomic
    via _atomic_write().
    """
    roadmap_lines = roadmap_path.read_text(encoding="utf-8").splitlines(keepends=True)
    shipped_lines = (
        shipped_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if shipped_path.is_file()
        else []
    )
    new_roadmap_lines, new_shipped_lines = move_to_shipped(roadmap_lines, shipped_lines, start, end)
    _atomic_write(shipped_path, "".join(new_shipped_lines))
    _atomic_write(roadmap_path, "".join(new_roadmap_lines))


def _process(lines, root=None, verbose=False, text_overrides=None):
    if root is None:
        root = Path.cwd()
    collect_task_ids(lines)

    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = TASK_RE.match(line)
        if not m:
            out.append(line)
            i += 1
            continue

        done = m.group(1) == "x"

        # Collect the full task block (everything until the next task or section
        # boundary) via the same fence-aware scan pack_task.py's parser uses.
        j = scan_block_end(lines, i + 1)
        block = lines[i:j]

        if done:
            out.extend(block)
            i = j
            continue

        try:
            task_status_of(block)
        except ValueError as exc:
            raise ValueError(f"{block[0].strip()}: {exc}") from exc

        # Extract class from header line only
        header_m = CLASS_RE.search(block[0])
        task_class = header_m.group(1) if header_m else None

        # Self-heal the header's medal glyph against its Score — the Score number
        # is the source of truth, the medal is always re-derived from it, never
        # hand-trusted (same spirit as the Route/Chars re-stamp below).
        score_m = SCORE_RE.search(block[0])
        if score_m:
            correct_medal = _medal(score_m.group(1))
            token_m = re.search(r"Score\s+[1-5]\s+(\S+)", block[0])
            if token_m and token_m.group(1) != correct_medal:
                block[0] = block[0][: token_m.start(1)] + correct_medal + block[0][token_m.end(1) :]

        # Scan block for file counts, the resolved file list, and the last metadata line
        total_files = 0
        last_meta_idx = None
        resolved_files = []
        seen_paths = set()
        unresolved = []
        external_projects = set()
        has_local_project = False

        for k, bl in enumerate(block):
            fm = FILE_META_RE.match(bl)
            if fm:
                total_files += _count_entries(fm.group(1))
                last_meta_idx = k
                files, missing = resolve_file_list(fm.group(1), root)
                for raw in BACKTICK_RE.findall(fm.group(1)):
                    ref_m = EXTERNAL_REF_TOKEN_RE.match(LINE_RANGE_RE.sub("", raw))
                    if ref_m:
                        external_projects.add(ref_m.group(1))
                for f in files:
                    if f not in seen_paths:
                        seen_paths.add(f)
                        resolved_files.append(f)
                    if f.resolve().is_relative_to(root.resolve()):
                        has_local_project = True
                for m in missing:
                    if m not in unresolved:
                        unresolved.append(m)
                    if external_ref_name(m) is None and not URL_RE.match(m):
                        has_local_project = True

        sizes = _char_sizes(resolved_files, root, text_overrides)
        binary_files = []
        for file_path in resolved_files:
            if context_pack.is_binary(file_path):
                resolved = file_path.resolve()
                rel = (
                    resolved.relative_to(root.resolve()).as_posix()
                    if resolved.is_relative_to(root.resolve())
                    else file_path.as_posix()
                )
                binary_files.append(rel)
        total_chars = sum(c for _, c in sizes)
        project_scopes = len(external_projects) + int(has_local_project)
        execution_mode, capabilities, constraints = _task_requirements(block)
        rec = _recommend(
            task_class,
            total_files,
            total_chars,
            project_scopes,
            execution_mode,
            capabilities,
            constraints,
        )

        # Debug visibility: an unresolved path can be a legitimate new/placeholder file
        # (a **Write:** target named ahead of creation) or a typo silently skewing the
        # char counts and routing. --verbose traces every task; without it, warn only in
        # the clearly-degraded case where a task listed paths but *none* resolved, so
        # Chars/Context Load/Route are computed from nothing.
        title = block[0].strip()
        if verbose:
            print(f"task: {title[:100]}", file=sys.stderr)
            print(
                f"  class={task_class or '?'} entries={total_files} "
                f"projects={project_scopes} resolved={len(resolved_files)} "
                f"chars={total_chars} route={rec or '(skipped)'}",
                file=sys.stderr,
            )
            for m in unresolved:
                print(f"  unresolved: {m}", file=sys.stderr)
        elif unresolved and not resolved_files:
            shown = ", ".join(unresolved[:4]) + ("..." if len(unresolved) > 4 else "")
            print(
                f"warning: no listed path resolved to a file for task {title[:80]!r} — "
                f"Chars/Context Load/Route are computed from an empty set; new files or typos? ({shown})",
                file=sys.stderr,
            )
        if rec is None or last_meta_idx is None:
            # No parseable file-list line to anchor the stamp to (e.g. a Class
            # 3 task recommended regardless of total_files, but with no
            # **Implement:**/**Context:**/etc. line found) — leave it alone.
            out.extend(block)
            i = j
            continue

        # Route/Context Load/Chars are generated, never hand-authored (see roadmap.md's
        # format convention) — they only ever appear after last_meta_idx, so
        # dropping and re-stamping them fresh is safe and avoids index churn.
        # A Route line ending in "(manual)" is a human override (see module
        # docstring) and is left in place rather than dropped/re-stamped.
        has_manual_route = any(MANUAL_ROUTE_RE.match(bl) for bl in block)
        for k in reversed(range(len(block))):
            if (
                EFFORT_RE.match(block[k])
                or CONTEXT_LOAD_RE.match(block[k])
                or CHARS_RE.match(block[k])
                or (ROUTE_RE.match(block[k]) and not MANUAL_ROUTE_RE.match(block[k]))
            ):
                del block[k]

        last_meta_idx = max(k for k, bl in enumerate(block) if FILE_META_RE.match(bl))
        insert_at = last_meta_idx + 1
        if has_manual_route:
            insert_at += 1  # keep the manual Route; generated context metadata follows it
        else:
            block.insert(insert_at, f"  **Route:** {rec}\n")
            insert_at += 1
        block.insert(insert_at, _context_load_line(total_files, total_chars))
        chars_line = _chars_line(sizes, binary_files)
        if chars_line is not None:
            block.insert(insert_at + 1, chars_line)

        out.extend(block)
        i = j

    return out


def process_roadmap(lines, path: Path, root=None, verbose=False):
    """Process annotations to a fixed point when a task lists roadmap.md itself.

    Without the in-memory size override, the first write changes roadmap.md's character
    count and forces a one-line correction on the next run. Iterate against the candidate
    bytes so the single displayed/written result is already the stable second-pass result.
    """
    if root is None:
        root = Path.cwd()
    candidate = list(lines)
    resolved_path = path.resolve()
    for _attempt in range(10):
        result = _process(
            lines,
            root=root,
            verbose=verbose,
            text_overrides={resolved_path: "".join(candidate)},
        )
        if result == candidate:
            return result
        candidate = result
    raise RuntimeError("roadmap annotations did not converge after 10 in-memory passes")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # --- NEW: compute defaults relative to this file, not cwd ---
    SCRIPT_DIR = Path(__file__).resolve().parent
    DEFAULT_ROADMAP = (SCRIPT_DIR.parent / "docs" / "roadmap.md").resolve()
    DEFAULT_SHIPPED = (SCRIPT_DIR.parent / "docs" / "shipped.md").resolve()

    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print result to stdout instead of updating the file.",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any route/chars annotation is stale, without modifying the file.",
    )
    ap.add_argument(
        "--roadmap",
        default=str(DEFAULT_ROADMAP),
        help="Path to the roadmap file (default: <repo>/docs/roadmap.md, resolved relative to this script).",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Trace every task to stderr...",
    )
    ap.add_argument(
        "--complete",
        metavar="ID",
        help="Move one open identified task to shipped history (legacy title fragments still work).",
    )
    ap.add_argument(
        "--shipped",
        default=str(DEFAULT_SHIPPED),
        help="Path to the shipped-items file used by --complete (default: <repo>/docs/shipped.md).",
    )
    ap.add_argument(
        "--migrate-ids",
        action="store_true",
        help="Insert permanent IDs into legacy tasks without reformatting other content.",
    )
    ap.add_argument(
        "--include-shipped",
        action="store_true",
        help="With --migrate-ids, also migrate --shipped using the same collision set.",
    )
    args = ap.parse_args()

    path = Path(args.roadmap).expanduser()
    # if user passed a relative override, resolve it from cwd; default is already absolute
    if not path.is_absolute():
        path = path.resolve()

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    if args.migrate_ids:
        targets = [(path, lines)]
        shipped_path = Path(args.shipped).expanduser()
        if not shipped_path.is_absolute():
            shipped_path = shipped_path.resolve()
        if args.include_shipped and shipped_path.is_file():
            shipped_lines = shipped_path.read_text(encoding="utf-8").splitlines(keepends=True)
            targets.append((shipped_path, shipped_lines))
        try:
            existing: set[str] = set()
            for _target, target_lines in targets:
                overlap = existing & collect_task_ids(target_lines)
                if overlap:
                    raise ValueError(f"duplicate task ID across files: {sorted(overlap)[0]}")
                existing.update(collect_task_ids(target_lines))
            migrated = []
            for target, target_lines in targets:
                result_lines, added = migrate_task_ids(target_lines, existing)
                migrated.append((target, target_lines, result_lines, added))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)

        if args.check:
            total_added = sum(added for _target, _before, _after, added in migrated)
            if total_added:
                print(
                    f"{total_added} task ID(s) missing — run --migrate-ids",
                    file=sys.stderr,
                )
                sys.exit(1)
            print("all tasks have permanent IDs", file=sys.stderr)
            return
        if args.dry_run:
            for target, _before, result_lines, added in migrated:
                print(f"would assign {added} ID(s) in {target}", file=sys.stderr)
                sys.stdout.write("".join(result_lines))
            return
        for target, before, result_lines, added in migrated:
            write_roadmap(target, before, result_lines)
            print(f"assigned {added} ID(s) in {target}", file=sys.stderr)
        return

    if args.complete:
        try:
            start, end = find_task_block(lines, args.complete)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(1)
        title = lines[start].strip()
        if args.dry_run:
            print(f"would move to {args.shipped}:", file=sys.stderr)
            sys.stdout.write("".join(lines[start:end]))
            return
        shipped_path = Path(args.shipped).expanduser()
        if not shipped_path.is_absolute():
            shipped_path = shipped_path.resolve()
        complete_and_ship(path, shipped_path, start, end)
        print(f"moved to {args.shipped}: {title[:80]!r}", file=sys.stderr)
        return

    try:
        relationship_lines = list(lines)
        shipped_path = Path(args.shipped).expanduser()
        if shipped_path.is_file():
            relationship_lines.extend(
                shipped_path.read_text(encoding="utf-8").splitlines(keepends=True)
            )
        relationship_errors = validate_task_relationships(relationship_lines)
        if relationship_errors:
            raise ValueError(
                "relationship validation failed:\n- " + "\n- ".join(relationship_errors)
            )
        result = process_roadmap(lines, path, context_pack.repo_root(), verbose=args.verbose)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.check:
        changed = sum(1 for a, b in zip(lines, result, strict=False) if a != b)
        changed += abs(len(result) - len(lines))
        if changed:
            print(
                f"{path}: {changed} line(s) stale — run route_tasks.py to update", file=sys.stderr
            )
            sys.exit(1)
        print(f"{path}: routes up to date", file=sys.stderr)
        return

    if args.dry_run:
        sys.stdout.write("".join(result))
        return

    try:
        changed = write_roadmap(path, lines, result)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"updated {path}: {changed} line(s) changed", file=sys.stderr)


if __name__ == "__main__":
    main()
