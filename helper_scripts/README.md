# helper_scripts

The mechanical half of the AI harness described in `templates/AI_HARNESS.template.md`. Copy
the `*.py` files into a new project's repo (alongside the instantiated `docs/roadmap.md`
and `CLAUDE.md`) and they work with no code changes for the common case — see "One-time setup
per project" below for the one file you should add. Prefer `setup_wizard.py`, which does
this for you; if copying by hand, take pristine `external_refs.json`/`effort_ceiling.txt`
from `templates/seed.*` and do **not** copy `system_prompt.txt` — those three are this
kit's own live per-project state (see the root README's "Self-hosting: which copy is
which").

## What's here

| File                                                    | What it does                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `context_pack.py`                                       | Assembles an explicit file list into one paste-ready block for a free-tier model, with per-model budget warnings and automatic chunking. Fully generic — no per-project edits needed.                                                                                                                |
| `route_tasks.py`                                        | Parses `docs/roadmap.md`, stamps `**Route:**`/`**Effort:**`/`**Chars:**` on every open item per the routing rules, self-heals the score→medal mapping. Fully generic.                                                                                                                                |
| `query_model.py`                                        | Sends a context pack + task to a programmatic endpoint (local LM Studio / OpenRouter free tier) and captures the raw response. Reads `system_prompt.txt` (see below) for its guardrail prompt.                                                                                                       |
| `pack_task.py`                                          | The Quest Board — a GUI wrapping the three scripts above: pick roadmap tasks from a sortable/filterable table, preview the assembled pack, page through chunks, edit the prompt, copy/save for manual paste or send straight to a programmatic model. Run with `python helper_scripts/pack_task.py`. |
| `effort_ceiling.txt`                                    | Persisted high-water mark for the largest `Effort` score ever seen, so the picker's value-density column stays on a stable scale across sessions. Starts at `1` in this template — it self-updates, don't hand-edit it beyond the initial reset.                                                     |
| `external_refs.json`                                    | `name -> search hint` for roadmap file-list entries that point outside this repo (a reference implementation, a vendor SDK, a spec doc). Starts empty in this template.                                                                                                                              |
| `external_ref_paths.txt` (not committed — gitignore it) | `name=local/path` — when set, an external reference resolves straight from a local clone instead of only being described to a model as something to search for. Machine-specific, not a project fact.                                                                                                |

## One-time setup per project

1. Copy this folder into the project alongside `docs/roadmap.md` (from
   `templates/ROADMAP.template.md`) and `CLAUDE.md` (from `templates/CLAUDE.template.md`,
   which should already have this project's review tiers filled in).
2. **Create `helper_scripts/system_prompt.txt`** with this project's actual hard
   constraints — language/runtime restrictions, forbidden patterns, dependency policy, the
   same things named in `AI_HARNESS.template.md` §4's prompt template. `query_model.py` and
   `pack_task.py` both read this file and fall back to a generic guardrail prompt if it
   doesn't exist yet, so the tools work immediately but give better-guarded answers once
   this is filled in. Example:

   ```text
   You are a senior engineer assisting with <project>, <one-line description>.
   Read the provided context files carefully, then answer the task precisely.
   Rules: cite every claim with file:line; write [NOT FOUND] when you cannot locate something.
   <project> is <language>, <any hard constraints — no exceptions, no dynamic allocation, etc.>.
   Do not propose new dependencies without explicit instruction.
   Do not propose implementation for this project's top review tier — read-only research only.
   ```

3. If this project forks/tracks an upstream with reference material you'll want to pull
   into context packs, add entries to `external_refs.json` as you discover them.
4. That's it — `route_tasks.py` and `pack_task.py` default to `docs/roadmap.md` and need no
   further configuration.
