"""
query_model.py — send a context pack to a programmatic AI endpoint

Assembles the given files into a context pack (same file-header format as
context_pack.py) and posts it to an OpenAI-compatible chat completions API.
The raw response is written to --out or printed to stdout. Claude then runs
the fusion protocol (docs/ai-harness.md §5) before any output touches the
codebase — this script eliminates the manual paste step, not the verification step.

Usage:
    python helper_scripts/query_model.py --model qwen --task "..." FILE [FILE ...]
    python helper_scripts/query_model.py \\
        --model openrouter/qwen/qwen3-coder:free \\
        --task "..." --out response.md FILE [FILE ...]
    python helper_scripts/query_model.py --model qwen --task-file task.txt FILE [FILE ...]

Models:
    qwen                         LM Studio on home PC, reached via Tailscale.
                                 No auth key required. The loaded model is queried
                                 automatically via GET /v1/models.
    openrouter/<model-id>        OpenRouter free tier. Model ID is passed through
                                 verbatim (e.g. openrouter/meta-llama/llama-3.3-70b-instruct:free).

Environment variables:
    QWEN_LM_STUDIO_URL           LM Studio base URL including /v1.
                                 Default: http://localhost:1234/v1
                                 Override with your Tailscale address when away from home,
                                 e.g. http://<tailscale-ip>:1234/v1
    OPENROUTER_API_KEY           Required for openrouter/* models.

A transient failure (connection error, HTTP 5xx) is retried up to 3 times
with exponential backoff; a 4xx response is not retried since it means the
request itself is wrong.

No dependencies beyond the Python standard library.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_pack  # noqa: E402

# System prompt applied to every request. Mirrors the AI_HARNESS.md §4 template guardrails.
# Project-specific: create helper_scripts/system_prompt.txt (see helper_scripts/README.md)
# to state this project's actual hard constraints (language/runtime restrictions, forbidden
# patterns, dependency policy). Falls back to a generic guardrail prompt when that file
# doesn't exist yet — e.g. right after instantiating this toolkit into a new project.
_DEFAULT_SYSTEM = (
    "You are a senior software engineer assisting with this project. "
    "Read the provided context files carefully, then answer the task precisely. "
    "Rules: cite every claim with file:line; write [NOT FOUND] when you cannot locate something; "
    "do not propose new dependencies without explicit instruction; "
    "do not propose implementation for the project's top review tier (see CLAUDE.md's "
    "change-class taxonomy) — read-only research only for that tier."
)


def _load_system_prompt() -> str:
    override = Path(__file__).resolve().parent / "system_prompt.txt"
    try:
        text = override.read_text(encoding="utf-8").strip()
        if text:
            return text
    except FileNotFoundError:
        pass
    return _DEFAULT_SYSTEM


_SYSTEM = _load_system_prompt()


# ── model resolution ──


def _lm_studio_model(base_url):
    """Query LM Studio's /v1/models endpoint to get the currently loaded model ID."""
    req = urllib.request.Request(f"{base_url}/models")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot reach LM Studio at {base_url}: {e}\n"
            "Check that LM Studio is running and QWEN_LM_STUDIO_URL is correct."
        ) from e
    models = data.get("data", [])
    if not models:
        raise RuntimeError(f"LM Studio at {base_url}: no model is currently loaded.")
    model_id = models[0]["id"]
    print(f"LM Studio model: {model_id}", file=sys.stderr)
    return model_id


def _openrouter_free_models(base_url="https://openrouter.ai/api/v1", api_key=None, timeout=10):
    """Return the sorted list of currently-live OpenRouter model ids ending in ':free',
    each prefixed with 'openrouter/' so it matches the --model form _resolve_endpoint
    expects. OpenRouter's /models endpoint is public — no API key is required (a key is
    sent if given, but only as a courtesy). This is what makes the hardcoded free-model
    list in pack_task.py a mere offline fallback rather than something to hand-verify."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base_url}/models", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot reach OpenRouter at {base_url}: {e}\n"
            "Check your network connection and the endpoint URL."
        ) from e
    free = [
        f"openrouter/{m['id']}"
        for m in data.get("data", [])
        if isinstance(m.get("id"), str) and m["id"].endswith(":free")
    ]
    return sorted(free)


def _resolve_endpoint(model_arg):
    """Return (base_url, model_id, extra_headers) for the given --model argument."""
    if model_arg == "qwen":
        base_url = os.environ.get("QWEN_LM_STUDIO_URL", "http://localhost:1234/v1").rstrip("/")
        return base_url, _lm_studio_model(base_url), {}
    if model_arg.startswith("openrouter/"):
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise RuntimeError(
                "OPENROUTER_API_KEY environment variable is not set. "
                "Export it before running: set OPENROUTER_API_KEY=<your-key>"
            )
        model_id = model_arg[len("openrouter/") :]
        return "https://openrouter.ai/api/v1", model_id, {"Authorization": f"Bearer {key}"}
    raise ValueError(
        f"Unknown model: {model_arg!r}\n"
        'Use "qwen" or "openrouter/<model-id>" (e.g. openrouter/meta-llama/llama-3.3-70b-instruct:free).'
    )


# ── HTTP call ──


def _chat(base_url, model_id, extra_headers, system_msg, user_msg, max_tokens, max_retries=3):
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", **extra_headers}
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )
    print(f"sending to {base_url} model={model_id} ...", file=sys.stderr)

    # Only retry transient failures (connection errors, 5xx) — a 4xx means
    # the request itself is wrong and retrying won't fix it.
    resp = None
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                resp = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == max_retries:
                body = e.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {e.code} from {base_url}: {body}") from e
            wait = 2**attempt
            print(
                f"HTTP {e.code} from {base_url} (attempt {attempt}/{max_retries}), retrying in {wait}s...",
                file=sys.stderr,
            )
            time.sleep(wait)
        except urllib.error.URLError as e:
            if attempt == max_retries:
                raise RuntimeError(f"Cannot reach {base_url}: {e}") from e
            wait = 2**attempt
            print(
                f"Connection error to {base_url} (attempt {attempt}/{max_retries}): {e}, retrying in {wait}s...",
                file=sys.stderr,
            )
            time.sleep(wait)

    if resp is None:
        raise RuntimeError(f"no response received from {base_url} (max_retries={max_retries})")

    # A 200 response isn't necessarily a completion — some endpoints return an error
    # object or an empty choices list with a success status. Fail with the actual
    # payload rather than a bare KeyError that says nothing about what came back.
    choices = resp.get("choices") or []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}

    message_obj = first_choice.get("message")
    if not isinstance(message_obj, dict):
        message_obj = {}

    content = message_obj.get("content")
    if content is None:
        snippet = json.dumps(resp)[:1500]
        raise RuntimeError(
            f"unexpected response shape from {base_url} (no choices[0].message.content): {snippet}"
        )

    finish = first_choice.get("finish_reason", "?")
    usage = resp.get("usage", {}) or {}
    print(
        f"done: finish_reason={finish} "
        f"prompt_tokens={usage.get('prompt_tokens', '?')} "
        f"completion_tokens={usage.get('completion_tokens', '?')}",
        file=sys.stderr,
    )
    return content


# ── CLI ──


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--model",
        required=True,
        help='Target model: "qwen" or "openrouter/<model-id>".',
    )
    ap.add_argument(
        "--task",
        help="Task description text. Use the §4 prompt template from docs/ai-harness.md.",
    )
    ap.add_argument(
        "--task-file",
        help="File containing the task description (alternative to --task).",
    )
    ap.add_argument(
        "--out",
        help="Write raw model response to this file. Default: stdout.",
    )
    ap.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Maximum completion tokens (default: 4096).",
    )
    ap.add_argument(
        "files",
        nargs="*",
        help="Project files to include in the context pack.",
    )
    args = ap.parse_args()

    # Task text
    if args.task:
        task = args.task
    elif args.task_file:
        task = Path(args.task_file).read_text(encoding="utf-8")
    else:
        ap.error("Provide the task via --task TEXT or --task-file PATH.")

    # Build context pack
    root = context_pack.repo_root()
    paths = [Path(f) for f in args.files]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        for p in missing:
            print(f"error: not found: {p}", file=sys.stderr)
        sys.exit(1)

    pack = context_pack.build_pack(paths, root, fence=True)[0] if paths else ""
    user_msg = task + ("\n\n---\n\n" + pack if pack else "")

    # Resolve model and send
    try:
        base_url, model_id, extra_headers = _resolve_endpoint(args.model)
        response = _chat(base_url, model_id, extra_headers, _SYSTEM, user_msg, args.max_tokens)
    except (RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        Path(args.out).write_text(response, encoding="utf-8")
        print(f"response written to {args.out}", file=sys.stderr)
    else:
        print(response)


if __name__ == "__main__":
    main()
