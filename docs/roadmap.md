# FlatCAM Evo Beta — Roadmap

> Fork: colintrachte/flatcam (branch `mstanciu_Beta_8.995`)
> Last reviewed: 2026-07-08

Re-prioritized against this fork's own use — a solo fork-and-maintain effort, not upstream's
issue labels or milestone order. Items originate from the jpcgt/Stanciu Bitbucket tracker,
open upstream PRs worth cherry-picking, and gaps found while working the codebase; see
`docs/shipped.md` for what's already landed.

---

## Format convention

`helper_scripts/route_tasks.py` parses this file; `helper_scripts/context_pack.py` and
`helper_scripts/pack_task.py` consume the file lists you write into it. Keep new items
matching this shape:

- **Header line:** `- [ ] **Score <1-5> <medal> · Class <1-3> — <title>**`. `Class <n>`
  must appear in the header line itself, not just the body.
- **File-list fields** are their own line(s), starting with `  **Implement:**`,
  `  **Context:**`, `  **Write:**`, or `  **Read:**`, each a `·`-separated list of
  backtick-quoted paths. Every item needs at least one such line — a routing tool with no
  file list can't route it.
- **`**Route:**`** is a generated annotation, not hand-authored — stamped by
  `route_tasks.py` per `docs/ai-harness.md` §2. Re-run the script after adding or editing
  items rather than filling it in by hand. To pin a route the script can't auto-detect,
  append ` (manual)` to the value, e.g. `**Route:** perplexity (manual)`.
- **`**Effort:**`** and **`**Chars:**`** are likewise generated, stamped right after
  `**Route:**` — see `route_tasks.py`'s module docstring for the formulas.
- When a todo item is marked complete `[x]`, move it to `shipped.md` — do this
  mechanically via `python helper_scripts/route_tasks.py --complete "<title fragment>"`
  rather than hand-editing both files.
- `route_tasks.py --check` exits non-zero if this file's `Route`/`Effort`/`Chars`
  annotations are stale, without writing anything.

### Writing task descriptions

The prose under each header is what `pack_task.py` drops straight into the model-facing
prompt box — write it as an instruction to the model, not a spec written about the model.
Lead with an imperative verb, state what "done" looks like up front, number ordered steps,
and say plainly when you want the model to act rather than propose.

## Scoring

### Score (1–5)

5 = highest priority.

- **5** — crash, data-loss, or silently-wrong-output risk; protects Class 3 surface
- **3** — expands real capability or fixes a real workflow annoyance
- **1** — polish, or a low-confidence/deferred item

The medal glyph is mechanically derived by `route_tasks.py` from the score (≥4 → 🥇, =3 →
🥈, ≤2 → 🥉) — never hand-typed.

### Class (1–3)

This fork has no separate `REVIEW_TIERS.md` — tiers are defined here directly, since it's a
single-maintainer project:

- **Class 3** — touches G-code/toolpath generation, cut geometry, Z-depth/safety logic, or
  project save/load (data loss risk). Never unattended; author review mandatory before
  merge, plus a live test cut/job where the description calls for it.
- **Class 2** — UI/editor logic, plugin behavior, TCL commands — wrong output is visible
  and correctable, not silently baked into a job. AI may propose and stage; author approves
  before merge.
- **Class 1** — packaging, preferences, docs, parsers for cosmetic/metadata fields. AI may
  merge if tests/build pass and the change stays confined to this class.

When a change spans classes, it takes the bar of the highest class it touches.

### Effort (generated, not hand-typed)

```
effort = max(1, round(total_files * total_chars / 1000))
```

---

## How this roadmap is organized

Grouped by the fork-and-maintain triage categories from the old `TODO.md`: **Major PCB
Workflow Bugs** (Class 2/3 correctness) → **Upstream PRs** (cherry-pick candidates) →
**Quality of Life** (Class 1/2 polish) → **Windows Installer** (packaging) →
**Verification Needed** (confirm-before-fixing items — read first, only reclassify to a
code change once reproduced).

---

## 1. Major PCB Workflow Bugs

_Correctness bugs in the core Gerber/Excellon/G-code pipeline — highest score, since a
silent wrong-output bug here damages physical boards._

- [ ] **Score 5 🥇 · Class 3 — Fix isolation tool path offset inconsistency (Issue #539)**
      `ToolIsolation` uses a `2.0000001` divisor in its iso_offset formula while the
      rest-machining path uses `2.0`. Change all four occurrences to `2.0` so both paths
      agree. Deliberately deferred until now — subtle, affects cut quality, needs a live
      test cut to confirm no regression before merging.

  **Implement:** `appPlugins/ToolIsolation.py`
  **Context:** `camlib.py`
  **Route:** claude
  **Effort:** 1067
  **Chars:** ~533,745 total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 3 — Investigate cutout multi-depth wrong output (Issue #591)**
      Reproduce the reported bad multi-depth cutout output. The `while depth > z_cut:` loop
      in the cutout path looks correct on inspection (exits when depth equals z_cut) — this
      may be a user config issue rather than a code bug. Get a real reproduction case before
      touching the code; if no repro surfaces, close as not-a-bug.

  **Implement:** `appPlugins/ToolCutOut.py`
  **Context:** `camlib.py`
  **Route:** claude
  **Effort:** 968
  **Chars:** ~484,004 total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Fix aperture size edit blocked by DIM parameters (Issue #682)**
      In the Gerber editor, aperture editing is blocked whenever the aperture has DIM
      parameters, because `on_aptype_changed` isn't called with the current index on init.
      Fix the init path so DIM-parameter apertures are editable like any other.

  **Implement:** `appEditors/appGerberEditor.py`
  **Route:** kimi
  **Effort:** 345
  **Chars:** ~345,020 total (largest: appEditors/appGerberEditor.py ~345,020) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 2. Upstream PRs Worth Applying

_Open PRs on the upstream tracker worth cherry-picking into this fork, re-scored against
this fork's own priorities._

- [ ] **Score 5 🥇 · Class 3 — Add tool size validation against hole size (PR #346)**
      Milling currently proceeds silently when the tool diameter equals the hole size,
      producing bad output with no warning. Add a check that warns or aborts when tool
      diameter >= hole size. Safety fix — author: Mike Evans.

  **Implement:** `appPlugins/ToolDrilling.py`
  **Context:** `appDatabase.py`
  **Route:** claude
  **Effort:** 596
  **Chars:** ~298,025 total (largest: appDatabase.py ~161,228) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Merge drilling tools when not all found in DB (PR #345)**
      When multiple Excellon tools map to one tool-DB entry, the app currently creates
      phantom duplicate tools instead of merging them. Merge tools that resolve to the same
      DB entry. Author: Andrei Besfamilny.

  **Implement:** `appPlugins/ToolDrilling.py`
  **Context:** `appDatabase.py`
  **Route:** kimi
  **Effort:** 596
  **Chars:** ~298,025 total (largest: appDatabase.py ~161,228) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Better slot-to-drill distribution + TCL parity (PR #351)**
      Distribute slot drill points evenly along slot length instead of the current
      distribution, and make the `drillcncjob` TCL command match the UI's slot-handling
      behavior. Also partially overlaps the now-shipped #619 fix — check for duplication
      before applying. Author: phdussud.

  **Implement:** `appPlugins/ToolDrilling.py` · `tclCommands/TclCommandDrillcncjob.py`
  **Route:** kimi
  **Effort:** 314
  **Chars:** ~156,910 total (largest: appPlugins/ToolDrilling.py ~136,797) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 2 — Compare nearest-neighbor drill path optimization (PR #352)**
      PR claims ~75% traverse-distance reduction on its examples. This fork already runs an
      OR-Tools-based optimizer in `camlib.py` (`RoutingIndexManager`/`IndexToNode`) — compare
      both algorithms on a real job before deciding whether this PR adds anything. Author:
      Ben Buxton.

  **Context:** `camlib.py`
  **Route:** kimi
  **Effort:** 355
  **Chars:** ~354,578 total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Support opening multiple files per format in one dialog (PR #127)**
      QoL: currently files must be opened one at a time in some dialogs. Note the Gerber/
      Excellon/G-Code/HPGL2 open dialogs already call `getOpenFileNames` (plural) in
      `appIO.py` — confirm whether this PR still adds anything before applying. Author:
      Travers Carter.

  **Implement:** `appHandlers/appIO.py`
  **Route:** kimi
  **Effort:** 126
  **Chars:** ~126,194 total (largest: appHandlers/appIO.py ~126,194) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 3. Quality of Life

- [ ] **Score 3 🥈 · Class 2 — Fix SVG export missing inner isolation passes (Issue #609)**
      Running a 2-pass isolation job and exporting SVG only emits the outermost pass; inner
      passes are missing from the export. Fix `export_svg` so every pass is included.

  **Implement:** `camlib.py`
  **Context:** `appObjects/CNCJobObject.py` · `tclCommands/TclCommandExportSVG.py`
  **Route:** kimi
  **Effort:** 1270
  **Chars:** ~423,448 total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Fix Excellon editor diameter change one-click lag (Issue #530)**
      Changing a tool's diameter in the Excellon editor takes effect one click late —
      off-by-one in the diameter spinbox's signal/slot wiring. Fix the wiring so the change
      applies immediately.

  **Implement:** `appEditors/appExcEditor.py`
  **Route:** kimi
  **Effort:** 235
  **Chars:** ~234,948 total (largest: appEditors/appExcEditor.py ~234,948) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Recognize EasyEDA non-standard .DRL files (Issue #504)**
      EasyEDA exports Excellon `.DRL` files with a non-standard header, so they're currently
      treated as non-Gerber/rejected. Add header detection for the EasyEDA variant to the
      Excellon parser.

  **Implement:** `appParsers/ParseExcellon.py`
  **Route:** gemini
  **Effort:** 73
  **Chars:** ~73,367 total (largest: appParsers/ParseExcellon.py ~73,367) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Verify drillcncjob toolchange Z is not hardcoded (Issue #413)**
      Reported: toolchange Z height hardcoded at 0.1 in the `drillcncjob` TCL command.
      Inspection found no hardcoded 0.1 — `toolchangez` already reads from args or
      `options["tools_drill_toolchangez"]`. Confirm with a live TCL run using a non-default
      toolchangez value; likely already fixed or never a real bug, close if confirmed.

  **Implement:** `tclCommands/TclCommandDrillcncjob.py`
  **Route:** gemini
  **Effort:** 20
  **Chars:** ~20,113 total (largest: tclCommands/TclCommandDrillcncjob.py ~20,113) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 4. Windows Installer

- [ ] **Score 3 🥈 · Class 1 — Build a distributable Windows installer (cx_Freeze + Inno Setup)**
      Package the app as a distributable Windows installer. Runtime detection hooks
      (`sys.frozen`, `languages_dir_cx_freeze`) already exist in the codebase; a template
      `setup_cx.py` and `flatcam.iss` are documented in `INSTALLER.md` but not yet written.
      Key gotchas to handle: the VisPy private import in `appGUI/VisPyPatches.py`, the
      preprocessors dynamic-load path, and bundling the OR-Tools native DLLs.

  **Write:** `setup_cx.py` · `flatcam.iss`
  **Context:** `INSTALLER.md` · `appGUI/VisPyPatches.py` · `appTranslation.py`
  **Route:** kimi
  **Effort:** 114
  **Chars:** ~22,714 total (largest: appTranslation.py ~9,919) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 5. Verification Needed

_These may already be fixed — confirm with a real reproduction before spending time on a
code change. Class reflects what a fix would touch if the bug is confirmed real, not the
verification step itself._

- [ ] **Score 3 🥈 · Class 2 — Verify NCC settings default-loading (Issue #696)**
      NCC milling settings reportedly revert to wrong defaults on re-open. A Jan 2024
      changelog entry mentions NCC fixes — spot-check the current default-loading code
      against a fresh reopen before assuming this is still broken.

  **Implement:** `appPlugins/ToolNCC.py`
  **Route:** kimi
  **Effort:** 226
  **Chars:** ~225,580 total (largest: appPlugins/ToolNCC.py ~225,580) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 3 — Verify check_zcut() None-return crash is fixed (Issue #567)**
      Reported: `check_zcut()` could return `None`, crashing on arithmetic. Current code
      (around `camlib.py:3260`) appears to return a value on every branch. Test with
      `zcut=0` to confirm; if genuinely still reachable, the fix is Class 3 (Z-depth safety
      logic).

  **Implement:** `camlib.py`
  **Route:** claude
  **Effort:** 355
  **Chars:** ~354,578 total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 3 — Verify 1mm cutout gaps not generated (Issue #532)**
      Reported: cutout gaps aren't generated in some configurations. Check `ToolCutOut`'s
      gap-generation logic against a real 1mm-gap job before assuming this is still broken
      — a fix here directly affects cut geometry.

  **Implement:** `appPlugins/ToolCutOut.py`
  **Route:** claude
  **Effort:** 129
  **Chars:** ~129,426 total (largest: appPlugins/ToolCutOut.py ~129,426) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Verify pikepdf 10.8.0 API compatibility**
      `requirements.txt` pins `pikepdf>=2.0`; pikepdf 10.x has changed some APIs since then.
      Test PDF import (`ToolPDF`) against a real multi-layer PDF before assuming it still
      works.

  **Implement:** `appPlugins/ToolPDF.py`
  **Context:** `requirements.txt`
  **Route:** gemini
  **Effort:** 42
  **Chars:** ~20,809 total (largest: appPlugins/ToolPDF.py ~18,698) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## Notes

- **Shipped**: Completed items live in `docs/shipped.md` — moved there via
  `route_tasks.py --complete`, not by hand.
- **Parent repo** (fork lineage): jpcgt (original) → Marius Stanciu FlatCAM Evo Beta →
  dwrobel fork → this repo (`colintrachte/flatcam`, branch `mstanciu_Beta_8.995`). See
  `docs/shipped.md` for the pre-tracking fix log.
- **Do NOT touch**: vendored preprocessors under `preprocessors/` unless a specific bug
  names one; locale `.po`/`.pot` files (translation-managed, not hand-edited); anything
  under `flatcam_core/` without reading `HEADLESS_DECOUPLING_AUDIT.md` first.
- **Build**: no build step for running from source; see `INSTALLER.md` for the Windows
  installer packaging path (cx_Freeze + Inno Setup, not yet implemented — see §4 above).
- **Test framework**: `pytest` (see `tests/`).
- **CI**: none configured yet.
