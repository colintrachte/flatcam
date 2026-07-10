"""
context_pack.py — assemble a paste-ready context bundle for a free-tier AI model

Concatenates a list of project files into one text block, each preceded by a
relative-path header and line count, so it can be pasted into Gemini, Kimi,
ChatGPT, Meta.ai, Perplexity, or piped into query_model.py for programmatic
delivery to Qwen (LM Studio) or OpenRouter. Free-tier models cannot browse
this repo (see docs/ai-harness.md) — every delegation needs an explicit,
self-contained file set, the same Context:/Implement: lists docs/roadmap.md
already uses for every item.

Usage:
    python helper_scripts/context_pack.py FILE [FILE ...]
    python helper_scripts/context_pack.py --model kimi FILE [FILE ...]
    python helper_scripts/context_pack.py --out scratch.txt FILE [FILE ...]
    python helper_scripts/context_pack.py --max-chars 100000 FILE [FILE ...]

With --model, warns (does not block) if the file count or character count
exceeds that model's known session budget. By default the bundle is written
to scratch.txt (paste its contents from there); pass --stdout to print it to
the terminal instead. The summary lines always go to stderr so they don't
pollute the pasted text. The file list stays explicit by design —
this script does not expand directories or globs, because the whole point
of a context pack is a deliberately scoped, self-contained file set (see
docs/ai-harness.md §3), not "everything in this folder."

--max-chars splits the bundle into multiple paste-sized chunks when the
total exceeds the given character count; it defaults to 100000 (~25k
tokens, comfortably under every chat UI's paste limit per docs/ai-harness.md
§3.1) so chunking kicks in automatically for an oversized pack. Chunk
boundaries always fall between files — a single file is never split
mid-content, even if that file alone exceeds --max-chars (a warning is
printed in that case, and the oversized file becomes its own chunk). Each
chunk is wrapped with a banner telling the model whether more chunks
follow, per the paste workflow in docs/ai-harness.md §3. Pass --max-chars 0
to force the whole bundle into a single block regardless of size.
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Windows consoles default to a legacy codepage that can't print en/em dashes
# or arrows from source comments; force UTF-8 so the bundle prints intact.
for _stream in (sys.stdout, sys.stderr):
    _reconfig = getattr(_stream, "reconfigure", None)
    if callable(_reconfig):
        _reconfig(encoding="utf-8")

# Default --max-chars: the point at which a pack needs splitting into
# multiple paste-sized chunks (~25k tokens, comfortably under every chat
# UI's paste limit — see docs/ai-harness.md §3.1). route_tasks.py reuses
# this exact constant as its char-weighted routing threshold rather than
# inventing a second number for the same underlying constraint.
DEFAULT_MAX_CHARS = 100_000

# Budgets — must stay in sync with docs/ai-harness.md §1.
# Last re-verified against provider behavior: 2026-07-05. The chat-UI paste/upload
# caps below are community-reported and drift with provider policy — re-verify and
# restamp this date when a value stops matching reality (docs/ai-harness.md §7).
MODEL_BUDGETS = {
    # Gemini web app: up to 10 files per prompt (Google's own Gemini Apps help page,
    # 2026 — this one IS documented, unlike the char cap). Pasting past ~30,000
    # characters produces a "message too long" error (community-reported, approximate).
    # The router's ≤3-file cutoff for Gemini is a task-size heuristic (small,
    # mechanical), not this upload cap.
    "gemini": {
        "files": 10,
        "chars": 30_000,
        "chars_note": 'approximate — community-reported "message too long" threshold, not an official spec',
    },
    # Kimi web app: a 45,821-char pack (task text + files) was flagged by Kimi itself as
    # "17% over the limit" for a regular chat entry, auto-converting to a file attachment
    # instead. Implies a real ceiling around ~39,000 chars; budgeted here with a margin
    # since this is a single observation, not a measured spec. Update if more data comes in.
    "kimi": {
        "files": 20,
        "chars": 35_000,
        "chars_note": 'single observed data point (author hit "17% over" at ~45.8k chars, implying ~39k) — not an official spec, refine if it recurs',
    },
    # ChatGPT Free: pasting more than ~5,000 characters into the message box
    # silently turns the paste into a file attachment instead of inline text,
    # which both burns one of the account-wide 3-uploads/24h and breaks the
    # one-shot/message-1 workflow (docs/ai-harness.md §1, §4). The "5K rule" is
    # widely community-reported in 2026 (down from the ~10k seen earlier); some
    # sources tie the paste-to-attachment behavior to paid tiers, so treat 5,000
    # as a conservative floor, not a hard spec.
    "chatgpt": {
        "files": 3,
        "chars": 5_000,
        "chars_note": 'community-reported "5K rule" (2026); paste past this becomes a file attachment, burning one of the 3-uploads/24h cap — conservative floor, not an official spec',
    },
    "meta": {
        "files": 0,
        "chars": None,
    },  # no upload at all — paste the text body directly into chat
    # Perplexity free: pasting more than ~8,000 tokens (~20,000 chars) prompts
    # a switch to file upload instead. Community-reported (aggregator sites,
    # not Perplexity's own docs) — treat as approximate, not exact.
    "perplexity": {
        "files": None,
        "chars": 20_000,
        "chars_note": "approximate — community-reported threshold before it prompts a file upload instead of inline paste",
    },
    "qwen": {"files": None, "chars": None},  # programmatic via query_model.py — no paste-step limit
    "openrouter": {
        "files": None,
        "chars": None,
    },  # programmatic via query_model.py — no paste-step limit
}

LANG_MAP = {
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "bash",
    ".ini": "ini",
}


def repo_root() -> Path:
    """Resolve the repo root via git so headers stay repo-relative regardless of cwd."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        )
        return Path(out.decode().strip())
    except Exception:
        # Not fatal — but headers/relative paths now depend on where this was run from,
        # which is worth knowing when a pack's paths look wrong.
        print(
            "note: not inside a git repository — paths resolve relative to the "
            "current directory instead of a repo root.",
            file=sys.stderr,
        )
        return Path.cwd()


def is_binary(p: Path) -> bool:
    try:
        return b"\0" in p.read_bytes()[:2048]
    except Exception:
        return True


def build_pack(paths, root: Path, fence: bool):
    bodies = []
    total_lines = 0
    per_file = []
    for p in paths:
        if is_binary(p):
            print(f"skip: binary {p}", file=sys.stderr)
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        n_lines = text.count("\n") + 1
        total_lines += n_lines
        resolved = p.resolve()
        rel = (
            resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else p.as_posix()
        )
        if fence:
            lang = LANG_MAP.get(p.suffix.lower(), "")
            # A file that already contains a ``` fence (e.g. markdown with an
            # embedded code block) would otherwise close our fence early.
            marker = "~~~" if "```" in text else "```"
            body = f"===== {rel} ({n_lines} lines) =====\n{marker}{lang}\n{text.rstrip()}\n{marker}"
        else:
            body = f"===== {rel} ({n_lines} lines) =====\n{text}"
        bodies.append(body)
        per_file.append((rel, n_lines, len(text)))
    return "\n\n".join(bodies), total_lines, per_file, bodies


def model_fitness(per_file, n_chars):
    """Classify this exact pack against every model's budget in MODEL_BUDGETS.

    Returns {model: (label, detail)}. label is one of:
      "fits"       - within the model's file-count and char budgets.
      "trim"       - exceeds a whole-pack budget, but could fit if the file
                     set were trimmed (or, for a paste-based model, split
                     across chunks/messages).
      "not viable" - a single file alone already exceeds the model's char
                     budget. Chunking only bins whole files together and
                     never splits one, so no amount of trimming helps —
                     that file needs a different model or delivery path.
    """
    fitness = {}
    for model, budget in MODEL_BUDGETS.items():
        if budget["chars"] is not None:
            oversized = next((rel for rel, _, chars in per_file if chars > budget["chars"]), None)
            if oversized is not None:
                fitness[model] = (
                    "not viable",
                    f"{oversized} alone exceeds the ~{budget['chars']:,}-char budget",
                )
                continue
        over_files = budget["files"] not in (None, 0) and len(per_file) > budget["files"]
        over_chars = budget["chars"] is not None and n_chars > budget["chars"]
        if over_files or over_chars:
            fitness[model] = (
                "trim",
                "exceeds the pack-wide budget; trim the file set or split across sessions",
            )
        else:
            fitness[model] = ("fits", "")
    return fitness


def chunk_bodies(bodies, max_chars: int):
    """Greedily bin-pack whole file bodies into chunks no larger than max_chars.

    Never splits a single file's body across chunks — a file larger than
    max_chars on its own becomes an oversized chunk by itself, with a warning.
    """
    chunks = []
    current = []
    current_len = 0
    for body in bodies:
        body_len = len(body)
        if current and current_len + 2 + body_len > max_chars:
            chunks.append(current)
            current = []
            current_len = 0
        if not current and body_len > max_chars:
            print(
                f"warning: a single file ({body_len} chars) exceeds --max-chars "
                f"({max_chars}) on its own — it will not be split, its chunk will be oversized.",
                file=sys.stderr,
            )
        current.append(body)
        current_len += (2 if current_len else 0) + body_len
    if current:
        chunks.append(current)
    return chunks


def wrap_chunk(bodies, index: int, total: int) -> str:
    """Wrap a chunk's file bodies with a banner telling the model what to do with it."""
    content = "\n\n".join(bodies)
    if total == 1:
        return content
    if index < total:
        note = (
            f"===== CONTEXT PACK — CHUNK {index} of {total} =====\n"
            "More chunks follow. Acknowledge receipt only — do not attempt the task yet.\n"
        )
    else:
        note = (
            f"===== CONTEXT PACK — CHUNK {index} of {total} (FINAL) =====\n"
            "This is the last chunk. You now have the complete context pack; "
            "the task instructions will follow in the next message.\n"
        )
    return note + "\n" + content


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("files", nargs="+", help="Project-relative or absolute file paths to include.")
    ap.add_argument(
        "--model",
        choices=sorted(MODEL_BUDGETS),
        help="Warn if the bundle exceeds this model's known budget.",
    )
    ap.add_argument(
        "--out", default="scratch.txt", help="Write the bundle here (default: scratch.txt)."
    )
    ap.add_argument(
        "--stdout", action="store_true", help="Print the bundle to stdout instead of writing --out."
    )
    ap.add_argument(
        "--no-fence", action="store_true", help="Disable markdown code fences around each file."
    )
    ap.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=f"Split the bundle into multiple paste-sized chunks of at most this many "
        f"characters each (default: {DEFAULT_MAX_CHARS}, ~25k tokens — comfortably under every "
        f"chat UI's paste limit). Chunk boundaries always fall between files, never "
        f"mid-file. Pass 0 to disable chunking and keep a single block.",
    )
    args = ap.parse_args()

    paths = [Path(f) for f in args.files]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        for p in missing:
            print(f"error: not found: {p}", file=sys.stderr)
        sys.exit(1)

    root = repo_root()
    body, total_lines, per_file, bodies = build_pack(paths, root, fence=not args.no_fence)
    n_files = len(per_file)
    n_chars = len(body)

    for rel, lines, chars in per_file:
        print(f"# {rel:<50} {lines:5} lines {chars:7} chars", file=sys.stderr)

    if args.model:
        budget = MODEL_BUDGETS[args.model]
        if budget["files"] == 0:
            print(
                f"warning: {args.model} does not accept file uploads - paste this text directly into chat.",
                file=sys.stderr,
            )
        elif budget["files"] is not None and n_files > budget["files"]:
            print(
                f"warning: {n_files} files exceeds {args.model}'s ~{budget['files']}-file budget - trim the set or split across sessions.",
                file=sys.stderr,
            )
        if budget["chars"] is not None:
            oversized = next((rel for rel, _, chars in per_file if chars > budget["chars"]), None)
            if oversized is not None:
                print(
                    f"warning: {oversized} alone exceeds {args.model}'s ~{budget['chars']}-char budget - "
                    f"chunking can't split a single file, so no amount of trimming fixes this; "
                    f"that file needs a different model.",
                    file=sys.stderr,
                )
            elif n_chars > budget["chars"]:
                note = budget.get("chars_note")
                suffix = f" ({note})" if note else " - trim the set."
                print(
                    f"warning: {n_chars} chars exceeds {args.model}'s ~{budget['chars']}-char budget{suffix}",
                    file=sys.stderr,
                )

    print(f"# {n_files} files, {total_lines} lines, {n_chars} chars", file=sys.stderr)

    if args.max_chars and n_chars > args.max_chars:
        file_chunks = chunk_bodies(bodies, args.max_chars)
        total = len(file_chunks)
        print(f"# split into {total} chunk(s) at --max-chars={args.max_chars}", file=sys.stderr)
        for idx, fc in enumerate(file_chunks, start=1):
            chunk_text = wrap_chunk(fc, idx, total)
            print(
                f"# chunk {idx}/{total}: {len(fc)} file(s), {len(chunk_text)} chars",
                file=sys.stderr,
            )
            if len(chunk_text) > args.max_chars:
                print(
                    f"warning: chunk {idx}/{total} is {len(chunk_text)} chars, over "
                    f"--max-chars={args.max_chars} once the banner is added.",
                    file=sys.stderr,
                )
            if args.stdout:
                print(chunk_text)
                print(file=sys.stderr)
            else:
                out_path = Path(args.out)
                chunk_path = out_path.with_name(
                    f"{out_path.stem}.part{idx}of{total}{out_path.suffix}"
                )
                chunk_path.write_text(chunk_text, encoding="utf-8")
                print(f"written to {chunk_path}", file=sys.stderr)
        return

    if args.stdout:
        print(body)
    else:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
