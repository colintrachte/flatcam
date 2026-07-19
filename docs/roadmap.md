# FlatCAM Evo Beta — Roadmap

> Fork: colintrachte/flatcam (branch `mstanciu_Beta_8.995`)
> Last reviewed: 2026-07-18

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
- **`ID:`** is permanent identity: `task_` plus 32 lowercase hexadecimal characters.
  Quest Board assigns IDs to new tasks; migrate legacy items with
  `python helper_scripts/route_tasks.py --migrate-ids` rather than inventing IDs by hand.
- **`Status:`** is one of `Draft`, `Defined`, `Ready`, `In Progress`, `Blocked`,
  `Verification`, or `Shipped`. Only unblocked `Ready` tasks enter the execution queue.
- Authored task records should state an **`Outcome:`**, one or more **`Acceptance:`**
  conditions, and **`Expected evidence:`**. They may also include rationale, execution
  size and uncertainty, execution requirements, and permanent-ID relationships such as
  **`Blocked by:`**, **`Parent:`**, **`Supersedes:`**, and **`Related:`**.
- **File-list fields** are their own line(s), starting with `  **Implement:**`,
  `  **Context:**`, `  **Write:**`, `  **Read:**`, or `  **Evidence:**`, each a `·`-separated list of
  backtick-quoted paths. Every item needs at least one such line — a routing tool with no
  file list can't route it.
- **`**Route:**`** is a generated annotation, not hand-authored — stamped by
  `route_tasks.py` per `docs/ai-harness.md` §2. Re-run the script after adding or editing
  items rather than filling it in by hand. To pin a route the script can't auto-detect,
  append ` (manual)` to the value, e.g. `**Route:** perplexity (manual)`.
- **`Context Load:`** and **`Chars:`** are likewise generated. Context Load measures
  packaging burden, not labor or duration; author `Execution size` and `Uncertainty`
  separately when those judgments matter.
- When a todo item is marked complete `[x]`, move it to `shipped.md` — do this
  mechanically via `python helper_scripts/route_tasks.py --complete "<task ID>"`
  rather than hand-editing both files.
- `route_tasks.py --check` exits non-zero if this file's `Route`/`Context Load`/`Chars`
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

### Context Load (generated, not hand-typed)

```
context_load = max(1, round(total_files * total_text_chars / 1000))
```

This is a context-packaging score only. It is not an estimate of implementation effort.

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
  **ID:** task_f5e91baa4d595421cd39536f136299ed
  **Status:** Ready
  **Outcome:** Isolation and rest-machining paths calculate the same tool offset.
  **Acceptance:** All four isolation divisors use `2.0`, with no contradictory offset formula remaining.
  **Expected evidence:** Focused test results plus a reviewed live test-cut comparison showing no regression.
      `ToolIsolation` uses a `2.0000001` divisor in its iso_offset formula while the
      rest-machining path uses `2.0`. Change all four occurrences to `2.0` so both paths
      agree. Deliberately deferred until now — subtle, affects cut quality, needs a live
      test cut to confirm no regression before merging.

  **Implement:** `appPlugins/ToolIsolation.py`
  **Context:** `camlib.py`
  **Route:** claude
  **Context Load:** 1068
  **Chars:** ~533,987 text total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 3 — Investigate cutout multi-depth wrong output (Issue #591)**
  **ID:** task_8a6ef86f7a8cdf74b07bdec9c2b31843
  **Status:** Ready
  **Outcome:** Issue #591 has a reproducible failing case or a documented not-a-bug conclusion.
  **Acceptance:** A representative multi-depth cutout is traced through every depth pass before any code change is made.
  **Expected evidence:** Reproduction inputs, generated output, and pass-by-pass findings or a not-a-bug report.
      Reproduce the reported bad multi-depth cutout output. The `while depth > z_cut:` loop
      in the cutout path looks correct on inspection (exits when depth equals z_cut) — this
      may be a user config issue rather than a code bug. Get a real reproduction case before
      touching the code; if no repro surfaces, close as not-a-bug.

  **Implement:** `appPlugins/ToolCutOut.py`
  **Context:** `camlib.py`
  **Route:** claude
  **Context Load:** 968
  **Chars:** ~484,004 text total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Fix aperture size edit blocked by DIM parameters (Issue #682)**
  **ID:** task_87ac772ada9a38981c4de0a3191b27c2
  **Status:** Ready
  **Outcome:** Gerber apertures with DIM parameters can be edited immediately after initialization.
  **Acceptance:** Initializing the editor applies the current aperture-type index and enables the expected size controls.
  **Expected evidence:** A focused regression test or recorded UI reproduction showing DIM and non-DIM apertures remain editable.
      In the Gerber editor, aperture editing is blocked whenever the aperture has DIM
      parameters, because `on_aptype_changed` isn't called with the current index on init.
      Fix the init path so DIM-parameter apertures are editable like any other.

  **Implement:** `appEditors/appGerberEditor.py`
  **Route:** kimi
  **Context Load:** 345
  **Chars:** ~345,020 text total (largest: appEditors/appGerberEditor.py ~345,020) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 2. Upstream PRs Worth Applying

_Open PRs on the upstream tracker worth cherry-picking into this fork, re-scored against
this fork's own priorities._

- [ ] **Score 5 🥇 · Class 3 — Add tool size validation against hole size (PR #346)**
  **ID:** task_b1286161de477ab025586fd98edd603d
  **Status:** Ready
  **Outcome:** Drilling cannot silently generate invalid milling output when the tool is not smaller than the hole.
  **Acceptance:** Tool diameter equal to or greater than hole diameter produces a clear warning or abort before toolpath generation.
  **Expected evidence:** Regression results covering smaller, equal, and larger tool diameters, plus reviewed generated output.
      Milling currently proceeds silently when the tool diameter equals the hole size,
      producing bad output with no warning. Add a check that warns or aborts when tool
      diameter >= hole size. Safety fix — author: Mike Evans.

  **Implement:** `appPlugins/ToolDrilling.py`
  **Context:** `appDatabase.py`
  **Route:** claude
  **Context Load:** 596
  **Chars:** ~298,025 text total (largest: appDatabase.py ~161,228) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Merge drilling tools when not all found in DB (PR #345)**
  **ID:** task_6256ed686f9131aa52ce69d8d3b052cb
  **Status:** Ready
  **Outcome:** Excellon tools resolving to one tool-database entry are represented by one merged tool.
  **Acceptance:** A multi-tool input mapped to the same database record creates no phantom duplicate tools.
  **Expected evidence:** Focused regression output showing the source-to-database mapping and final merged tool list.
      When multiple Excellon tools map to one tool-DB entry, the app currently creates
      phantom duplicate tools instead of merging them. Merge tools that resolve to the same
      DB entry. Author: Andrei Besfamilny.

  **Implement:** `appPlugins/ToolDrilling.py`
  **Context:** `appDatabase.py`
  **Route:** kimi
  **Context Load:** 596
  **Chars:** ~298,025 text total (largest: appDatabase.py ~161,228) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Better slot-to-drill distribution + TCL parity (PR #351)**
  **ID:** task_8de7d192de2c690a42325626b40fae65
  **Status:** Ready
  **Outcome:** Slot drill points are evenly distributed and the TCL command matches the UI behavior.
  **Acceptance:** UI and `drillcncjob` produce equivalent slot points without duplicating the shipped Issue #619 fix.
  **Expected evidence:** Comparative UI/TCL output for representative slots and a duplication review against the existing fix.
      Distribute slot drill points evenly along slot length instead of the current
      distribution, and make the `drillcncjob` TCL command match the UI's slot-handling
      behavior. Also partially overlaps the now-shipped #619 fix — check for duplication
      before applying. Author: phdussud.

  **Implement:** `appPlugins/ToolDrilling.py` · `tclCommands/TclCommandDrillcncjob.py`
  **Route:** kimi
  **Context Load:** 314
  **Chars:** ~156,910 text total (largest: appPlugins/ToolDrilling.py ~136,797) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 2 — Compare nearest-neighbor drill path optimization (PR #352)**
  **ID:** task_197ddc76bc3d5e49f9bd164690d8e744
  **Status:** Ready
  **Outcome:** The fork has an evidence-based decision on whether PR #352 improves its existing optimizer.
  **Acceptance:** Both algorithms are run on the same representative jobs and compared for path length and runtime.
  **Expected evidence:** A reproducible comparison table and a keep/reject recommendation tied to the measurements.
      PR claims ~75% traverse-distance reduction on its examples. This fork already runs an
      OR-Tools-based optimizer in `camlib.py` (`RoutingIndexManager`/`IndexToNode`) — compare
      both algorithms on a real job before deciding whether this PR adds anything. Author:
      Ben Buxton.

  **Context:** `camlib.py`
  **Route:** kimi
  **Context Load:** 355
  **Chars:** ~354,578 text total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Support opening multiple files per format in one dialog (PR #127)**
  **ID:** task_faba00ba3ceb96bb4c50927a90e787f0
  **Status:** Ready
  **Outcome:** Every relevant open dialog supports multiple files, or PR #127 is documented as obsolete.
  **Acceptance:** Gerber, Excellon, G-Code, and HPGL2 dialog behavior is verified before applying any remaining change.
  **Expected evidence:** UI verification results by format and, if needed, a focused regression test for the missing case.
      QoL: currently files must be opened one at a time in some dialogs. Note the Gerber/
      Excellon/G-Code/HPGL2 open dialogs already call `getOpenFileNames` (plural) in
      `appIO.py` — confirm whether this PR still adds anything before applying. Author:
      Travers Carter.

  **Implement:** `appHandlers/appIO.py`
  **Route:** kimi
  **Context Load:** 127
  **Chars:** ~126,691 text total (largest: appHandlers/appIO.py ~126,691) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 3. Quality of Life

- [ ] **Score 3 🥈 · Class 2 — Fix SVG export missing inner isolation passes (Issue #609)**
  **ID:** task_ce1a0b28ecc8fd949b8c0d50ee89dc18
  **Status:** Ready
  **Outcome:** SVG export preserves every geometry pass from a multi-pass isolation job.
  **Acceptance:** Exporting a two-pass isolation job includes both inner and outer passes in the SVG.
  **Expected evidence:** A regression test and inspected SVG output containing geometry for every pass.
      Running a 2-pass isolation job and exporting SVG only emits the outermost pass; inner
      passes are missing from the export. Fix `export_svg` so every pass is included.

  **Implement:** `camlib.py`
  **Context:** `appObjects/CNCJobObject.py` · `tclCommands/TclCommandExportSVG.py`
  **Route:** kimi
  **Context Load:** 1261
  **Chars:** ~420,468 text total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Fix Excellon editor diameter change one-click lag (Issue #530)**
  **ID:** task_82180ff7cc3cf5271b122c66d50900be
  **Status:** Ready
  **Outcome:** A tool-diameter edit takes effect on the same interaction that changes the value.
  **Acceptance:** The first spinbox change updates the selected tool without requiring a second click.
  **Expected evidence:** A focused signal/slot regression test or recorded UI reproduction before and after the fix.
      Changing a tool's diameter in the Excellon editor takes effect one click late —
      off-by-one in the diameter spinbox's signal/slot wiring. Fix the wiring so the change
      applies immediately.

  **Implement:** `appEditors/appExcEditor.py`
  **Route:** kimi
  **Context Load:** 235
  **Chars:** ~234,948 text total (largest: appEditors/appExcEditor.py ~234,948) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Recognize EasyEDA non-standard .DRL files (Issue #504)**
  **ID:** task_d78410567ec58ee597689476bcc9cb44
  **Status:** Ready
  **Outcome:** EasyEDA's non-standard `.DRL` variant is recognized and parsed as Excellon input.
  **Acceptance:** A representative EasyEDA file imports successfully without weakening detection for standard Excellon files.
  **Expected evidence:** Parser tests covering the EasyEDA sample, a standard sample, and a non-Excellon rejection case.
      EasyEDA exports Excellon `.DRL` files with a non-standard header, so they're currently
      treated as non-Gerber/rejected. Add header detection for the EasyEDA variant to the
      Excellon parser.

  **Implement:** `appParsers/ParseExcellon.py`
  **Route:** gemini
  **Context Load:** 73
  **Chars:** ~73,367 text total (largest: appParsers/ParseExcellon.py ~73,367) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Verify drillcncjob toolchange Z is not hardcoded (Issue #413)**
  **ID:** task_6c522aaf52cc0bb85ef2bf0b2a9bcb3e
  **Status:** Ready
  **Outcome:** `drillcncjob` demonstrably honors a non-default toolchange Z value.
  **Acceptance:** A live TCL run emits the configured non-default value, or a reproducible defect is isolated before fixing it.
  **Expected evidence:** The TCL invocation, configuration value, and resulting G-code or failure trace.
      Reported: toolchange Z height hardcoded at 0.1 in the `drillcncjob` TCL command.
      Inspection found no hardcoded 0.1 — `toolchangez` already reads from args or
      `options["tools_drill_toolchangez"]`. Confirm with a live TCL run using a non-default
      toolchangez value; likely already fixed or never a real bug, close if confirmed.

  **Implement:** `tclCommands/TclCommandDrillcncjob.py`
  **Route:** gemini
  **Context Load:** 20
  **Chars:** ~20,113 text total (largest: tclCommands/TclCommandDrillcncjob.py ~20,113) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 4. Windows Installer

- [ ] **Score 3 🥈 · Class 1 — Build a distributable Windows installer (cx_Freeze + Inno Setup)**
  **ID:** task_6072e47f1ac62032229350a5a54e1a1d
  **Status:** Ready
  **Outcome:** FlatCAM can be installed and launched on Windows without a source checkout or development environment.
  **Acceptance:** The installer bundles dynamic preprocessors and required native libraries, installs cleanly, and launches the app.
  **Expected evidence:** Successful cx_Freeze and Inno Setup logs plus a clean-machine install, launch, and basic workflow smoke test.
      Package the app as a distributable Windows installer. Runtime detection hooks
      (`sys.frozen`, `languages_dir_cx_freeze`) already exist in the codebase; a template
      `setup_cx.py` and `flatcam.iss` are documented in `INSTALLER.md` but not yet written.
      Key gotchas to handle: the VisPy private import in `appGUI/VisPyPatches.py`, the
      preprocessors dynamic-load path, and bundling the OR-Tools native DLLs.

  **Write:** `setup_cx.py` · `flatcam.iss`
  **Context:** `INSTALLER.md` · `appGUI/VisPyPatches.py` · `appTranslation.py`
  **Route:** kimi
  **Context Load:** 114
  **Chars:** ~22,714 text total (largest: appTranslation.py ~9,919) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 5. Verification Needed

_These may already be fixed — confirm with a real reproduction before spending time on a
code change. Class reflects what a fix would touch if the bug is confirmed real, not the
verification step itself._

- [ ] **Score 3 🥈 · Class 2 — Verify NCC settings default-loading (Issue #696)**
  **ID:** task_267629775c552133ebef73dd39b9e40a
  **Status:** Ready
  **Outcome:** NCC settings persist across reopen, or the remaining default-loading defect is reproduced precisely.
  **Acceptance:** A fresh project exercises save, close, and reopen with non-default NCC settings before any fix is attempted.
  **Expected evidence:** The test settings and before/after reopen values, with a failure trace if they differ.
      NCC milling settings reportedly revert to wrong defaults on re-open. A Jan 2024
      changelog entry mentions NCC fixes — spot-check the current default-loading code
      against a fresh reopen before assuming this is still broken.

  **Implement:** `appPlugins/ToolNCC.py`
  **Route:** kimi
  **Context Load:** 226
  **Chars:** ~225,580 text total (largest: appPlugins/ToolNCC.py ~225,580) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 3 — Verify check_zcut() None-return crash is fixed (Issue #567)**
  **ID:** task_fb8d095fc9cbbfed2d742bad7aee01d9
  **Status:** Ready
  **Outcome:** `check_zcut()` is proven to return a safe value for `zcut=0` on every reachable branch.
  **Acceptance:** The reported arithmetic crash cannot be reproduced, or a failing branch is isolated before changing Z-depth logic.
  **Expected evidence:** Focused branch-coverage results and the returned values or captured failure trace.
      Reported: `check_zcut()` could return `None`, crashing on arithmetic. Current code
      (around `camlib.py:3260`) appears to return a value on every branch. Test with
      `zcut=0` to confirm; if genuinely still reachable, the fix is Class 3 (Z-depth safety
      logic).

  **Implement:** `camlib.py`
  **Route:** claude
  **Context Load:** 355
  **Chars:** ~354,578 text total (largest: camlib.py ~354,578) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 3 — Verify 1mm cutout gaps not generated (Issue #532)**
  **ID:** task_6db1fe52113860ecada7cbdaf6cbcf09
  **Status:** Ready
  **Outcome:** A 1 mm cutout-gap job produces the requested gaps, or the failing configuration is isolated.
  **Acceptance:** Representative 1 mm gap configurations are generated and visually inspected before cut-geometry code changes.
  **Expected evidence:** Input settings and inspected geometry/G-code showing correct gaps or the reproducible omission.
      Reported: cutout gaps aren't generated in some configurations. Check `ToolCutOut`'s
      gap-generation logic against a real 1mm-gap job before assuming this is still broken
      — a fix here directly affects cut geometry.

  **Implement:** `appPlugins/ToolCutOut.py`
  **Route:** claude
  **Context Load:** 129
  **Chars:** ~129,426 text total (largest: appPlugins/ToolCutOut.py ~129,426) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 1 🥉 · Class 1 — Verify pikepdf 10.8.0 API compatibility**
  **ID:** task_3cba42b3da5e480ca1058cd79e2868d2
  **Status:** Ready
  **Outcome:** Multi-layer PDF import is verified against pikepdf 10.8.0 or its incompatibility is isolated.
  **Acceptance:** A representative multi-layer PDF imports with the expected layers and geometry under pikepdf 10.8.0.
  **Expected evidence:** Dependency version, import output, and layer/geometry verification or the captured API failure.
      `requirements.txt` pins `pikepdf>=2.0`; pikepdf 10.x has changed some APIs since then.
      Test PDF import (`ToolPDF`) against a real multi-layer PDF before assuming it still
      works.

  **Implement:** `appPlugins/ToolPDF.py`
  **Context:** `requirements.txt`
  **Route:** gemini
  **Context Load:** 42
  **Chars:** ~20,872 text total (largest: appPlugins/ToolPDF.py ~18,698) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

---

## 6. Frontend Modernization

_Modernize the desktop experience without changing CAM output. The execution strategy is
incremental: characterize behavior, introduce narrow seams, build one end-to-end workflow,
and compare alternative UI technologies only after the same behavior can be exercised through
stable commands and view models. A dependency is recorded only when work cannot be safely
started against an agreed interface or mock._

### 6.1 Independent foundations

- [ ] **Score 5 🥇 · Class 2 — Capture the frontend behavior baseline**
  **ID:** task_02fc0274af544b5e8f8740411ab1b346
  **Status:** Ready
  **Outcome:** Existing commands, shortcuts, window-state persistence, and the Gerber-to-isolation happy path have executable characterization coverage before UI relocation begins.
  **Acceptance:** Tests assert stable command IDs or labels, shortcut uniqueness, saved splitter/tab state, and the inputs and resulting project objects for one isolation run without asserting pixel layout.
  **Expected evidence:** Focused Qt test results plus a short manifest mapping each protected behavior to its test.
  **Execution size:** Medium
  **Uncertainty:** Medium — legacy construction may require a lightweight application fixture rather than a full startup.
      Preserve behavior, not implementation details. Do not change CAM algorithms or bless
      accidental visual geometry as a permanent contract. Where a full main-window fixture is
      impractical, capture the smallest observable contract and document the remaining gap.

  **Write:** `tests/test_frontend_characterization.py` · `docs/frontend/behavior-baseline.md`
  **Context:** `appGUI/MainGUI.py` · `appMain.py` · `tests/test_gcode_editor_lifecycle.py`
  **Route:** claude
  **Context Load:** 3185
  **Chars:** ~637,012 text total (largest: appMain.py ~362,144) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 5 🥇 · Class 1 — Define semantic frontend design tokens**
  **ID:** task_ea28c14f724cd108db7059b84d99670d
  **Status:** Ready
  **Outcome:** Light and dark interfaces share one typed vocabulary for color, typography, spacing, radius, density, focus, warning, and destructive states.
  **Acceptance:** Tokens contain no feature-specific names, both themes satisfy documented contrast targets, and a unit test rejects missing or asymmetric token keys.
  **Expected evidence:** Token-schema tests and generated light/dark token tables reviewed without launching the application.
  **Execution size:** Small
  **Uncertainty:** Low
      This task defines values and a stable access API only. It must not restyle existing
      screens or add another third-party theme package.

  **Write:** `appGUI/design/__init__.py` · `appGUI/design/tokens.py` · `tests/test_design_tokens.py`
  **Context:** `defaults.py` · `research/frontend-stack-recommendation-2026-07-18.md`
  **Route:** kimi
  **Context Load:** 288
  **Chars:** ~57,505 text total (largest: defaults.py ~43,710) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 5 🥇 · Class 2 — Add a central application command registry**
  **ID:** task_ad0548bbf75746bc41d7d2090f5f4eac
  **Status:** Blocked
  **Blocked by:** task_de4d4de89612656a6930c5994ad96e64
  **Outcome:** Menus, toolbars, shortcuts, context menus, and future command search can consume one toolkit-aware command definition instead of creating disconnected actions.
  **Acceptance:** The registry supports stable IDs, translated labels, icons, shortcuts, checked/enabled predicates, handlers, and duplicate-ID/shortcut detection without importing `MainGUI`.
  **Expected evidence:** Unit tests for registration, state refresh, duplicate rejection, and QAction binding.
  **Execution size:** Small
  **Uncertainty:** Low
      Build the registry and its tests only. Do not migrate legacy actions in this task.

  **Write:** `appGUI/commands/__init__.py` · `appGUI/commands/model.py` · `appGUI/commands/registry.py` · `tests/test_command_registry.py`
  **Context:** `appGUI/qt.py` · `research/frontend-stack-recommendation-2026-07-18.md`
  **Route:** kimi
  **Context Load:** 83
  **Chars:** ~13,795 text total (largest: research/frontend-stack-recommendation-2026-07-18.md ~13,795) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 1 — Add a Qt binding compatibility facade**
  **ID:** task_de4d4de89612656a6930c5994ad96e64
  **Status:** Ready
  **Outcome:** New frontend code depends on one local Qt import surface capable of representing PyQt6 and PySide6 naming differences.
  **Acceptance:** The facade exports the Qt modules and Signal/Slot/Property aliases used by new code, defaults to PyQt6, reports its selected binding, and has import-level tests.
  **Expected evidence:** Focused tests under the installed PyQt6 runtime and a documented list of intentionally unsupported binding-specific APIs.
  **Execution size:** Small
  **Uncertainty:** Low
      Do not bulk-rewrite existing imports or claim PySide6 runtime compatibility in this task.

  **Write:** `appGUI/qt.py` · `tests/test_qt_facade.py`
  **Context:** `requirements.txt` · `appGUI/VisPyPatches.py`
  **Route:** kimi
  **Context Load:** 30
  **Chars:** ~7,411 text total (largest: appGUI/VisPyPatches.py ~5,237) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 1 — Build a deterministic UI icon inventory**
  **ID:** task_9aef5cd32aa57a64f916edff3776e1ce
  **Status:** Ready
  **Outcome:** Maintainers can identify duplicate, unused, missing, raster-only, and dark-theme-specific icons before replacing the icon set.
  **Acceptance:** A read-only script scans Python resource references and both resource directories, emits stable JSON and Markdown summaries, and distinguishes dynamic references it cannot resolve.
  **Expected evidence:** Script tests using a temporary fixture plus a generated inventory committed under `docs/frontend/`.
  **Execution size:** Small
  **Uncertainty:** Low
      Inventory only; do not delete, rename, redraw, or relicense assets.

  **Write:** `helper_scripts/audit_ui_icons.py` · `tests/test_audit_ui_icons.py` · `docs/frontend/icon-inventory.md` · `docs/frontend/icon-inventory.json`
  **Context:** `assets/resources/app.svg`
  **Route:** kimi
  **Context Load:** 3
  **Chars:** ~629 text total (largest: assets/resources/app.svg ~629)

### 6.2 Parallel implementation seams

- [ ] **Score 5 🥇 · Class 1 — Build the first reusable frontend component primitives**
  **ID:** task_a1d96649d5aedf84e2b5f7ac845fb32b
  **Status:** Blocked
  **Blocked by:** task_ea28c14f724cd108db7059b84d99670d
  **Blocked by:** task_de4d4de89612656a6930c5994ad96e64
  **Outcome:** New screens use a small consistent set of token-backed section, button, field-row, empty-state, and status-badge components.
  **Acceptance:** Components expose accessible names and focus behavior, support compact and comfortable density, render in both themes, and contain no CAM workflow logic.
  **Expected evidence:** Component tests plus a standalone gallery showing all states in light and dark themes.
  **Execution size:** Medium
  **Uncertainty:** Low
      Use standard Qt widgets through the local facade. Do not modify `GUIElements.py` or
      silently replace legacy controls.

  **Write:** `appGUI/design/components.py` · `appGUI/design/gallery.py` · `tests/test_design_components.py`
  **Context:** `appGUI/design/tokens.py` · `appGUI/qt.py` · `research/frontend-stack-recommendation-2026-07-18.md`
  **Route:** kimi
  **Context Load:** 83
  **Chars:** ~13,795 text total (largest: research/frontend-stack-recommendation-2026-07-18.md ~13,795) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Migrate file and project actions to the command registry**
  **ID:** task_777c9c9f7c611234d664fbb31329a8be
  **Status:** Blocked
  **Blocked by:** task_ad0548bbf75746bc41d7d2090f5f4eac
  **Blocked by:** task_02fc0274af544b5e8f8740411ab1b346
  **Outcome:** Open, import, save, save-as, close, and project-object actions are defined once while preserving their current menus, shortcuts, handlers, and enablement.
  **Acceptance:** No migrated command is constructed twice, characterization tests remain green, and legacy saved GUI state still restores without warnings.
  **Expected evidence:** Command-registry and frontend-characterization results plus an old/new action manifest showing parity.
  **Execution size:** Medium
  **Uncertainty:** Medium
      Move one action group only. Do not reorganize menus, alter labels, or introduce the
      command palette in this task.

  **Implement:** `appGUI/MainGUI.py` · `appMain.py`
  **Context:** `appGUI/commands/registry.py` · `tests/test_frontend_characterization.py`
  **Route:** claude
  **Context Load:** 2536
  **Chars:** ~634,046 text total (largest: appMain.py ~362,144) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Migrate view and canvas actions to the command registry**
  **ID:** task_0c5d9c3ef31067084128745b884f856e
  **Status:** Blocked
  **Blocked by:** task_ad0548bbf75746bc41d7d2090f5f4eac
  **Blocked by:** task_02fc0274af544b5e8f8740411ab1b346
  **Outcome:** Zoom, fit, replot, clear, panel visibility, grid, axis, HUD, and workspace-view actions share registry definitions without changing canvas behavior.
  **Acceptance:** Existing shortcuts and checked states remain synchronized across menu and toolbar representations, with no VisPy drawing code moved.
  **Expected evidence:** Focused command tests and a recorded UI smoke run covering every migrated checked state.
  **Execution size:** Medium
  **Uncertainty:** Medium
      Keep this independent from file/project command migration except for the shared
      registry API, so both action groups can be implemented and reviewed separately.

  **Implement:** `appGUI/MainGUI.py` · `appMain.py`
  **Context:** `appGUI/commands/registry.py` · `appGUI/PlotCanvas.py` · `tests/test_frontend_characterization.py`
  **Route:** claude
  **Context Load:** 3305
  **Chars:** ~661,049 text total (largest: appMain.py ~362,144) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 1 — Migrate low-risk Qt imports through the facade**
  **ID:** task_f97fc8c9badf8b3b4e9ba0fff15c9540
  **Status:** Blocked
  **Blocked by:** task_de4d4de89612656a6930c5994ad96e64
  **Outcome:** A bounded set of non-canvas GUI modules proves that the compatibility facade can replace direct PyQt6 imports mechanically.
  **Acceptance:** Only import and binding-name changes are made, public behavior is unchanged, and targeted startup/layout tests pass under PyQt6.
  **Expected evidence:** A zero-functional-diff review plus focused tests importing and instantiating each migrated module.
  **Execution size:** Small
  **Uncertainty:** Low
      Limit the batch to the named files. Do not touch VisPy canvas modules, `MainGUI.py`,
      `GUIElements.py`, plugins, preferences, or editors.

  **Implement:** `appGUI/ColumnarFlowLayout.py` · `appGUI/StartupSplash.py`
  **Context:** `appGUI/qt.py` · `tests/test_startup_diagnostics.py`
  **Route:** kimi
  **Context Load:** 163
  **Chars:** ~40,821 text total (largest: appGUI/StartupSplash.py ~28,311) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 2 — Extract window layout persistence into a service**
  **ID:** task_b2a51ae161917cc9b7549e98560500f7
  **Status:** Blocked
  **Blocked by:** task_02fc0274af544b5e8f8740411ab1b346
  **Outcome:** Main-window geometry, dock/toolbar state, splitter sizes, and reset behavior are owned by a focused service rather than scattered QSettings calls.
  **Acceptance:** Existing settings keys remain compatible, corrupt or absent state falls back safely, and save/restore/reset are covered without launching CAM operations.
  **Expected evidence:** Service unit tests plus characterization results against a temporary QSettings scope.
  **Execution size:** Medium
  **Uncertainty:** Medium
      Preserve key names and defaults. Do not redesign the layout in this extraction task.

  **Write:** `appGUI/workspace/window_state.py` · `tests/test_window_state.py`
  **Implement:** `appGUI/MainGUI.py`
  **Context:** `tests/test_frontend_characterization.py`
  **Route:** claude
  **Context Load:** 1088
  **Chars:** ~271,902 text total (largest: appGUI/MainGUI.py ~271,902) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

### 6.3 Workspace shell and golden workflow

- [ ] **Score 5 🥇 · Class 1 — Build an isolated modern workspace shell prototype**
  **ID:** task_9cd4932d30bbf23710d82cfc8d02b33d
  **Status:** Blocked
  **Blocked by:** task_a1d96649d5aedf84e2b5f7ac845fb32b
  **Blocked by:** task_ad0548bbf75746bc41d7d2090f5f4eac
  **Outcome:** A non-production Qt Widgets prototype demonstrates the target project navigator, canvas host slot, contextual inspector, compact command bar, and task/status drawer.
  **Acceptance:** The shell resizes from 1280×720 through 4K, supports keyboard focus traversal and both density modes, and uses placeholders rather than importing `appMain` or VisPy.
  **Expected evidence:** Automated layout assertions and reviewed screenshots in light and dark themes at three viewport sizes.
  **Execution size:** Medium
  **Uncertainty:** Low
      This is an isolated prototype. It may use fake models and handlers but must use the
      production token/component APIs so it can be integrated rather than discarded.

  **Write:** `appGUI/workspace/__init__.py` · `appGUI/workspace/shell.py` · `tests/test_workspace_shell.py`
  **Context:** `appGUI/design/components.py` · `appGUI/commands/registry.py` · `research/frontend-stack-recommendation-2026-07-18.md`
  **Route:** kimi
  **Context Load:** 83
  **Chars:** ~13,795 text total (largest: research/frontend-stack-recommendation-2026-07-18.md ~13,795) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 5 🥇 · Class 2 — Wire the workspace shell behind an opt-in feature flag**
  **ID:** task_58e5f64b932af3db186eac8085580f26
  **Status:** Blocked
  **Blocked by:** task_9cd4932d30bbf23710d82cfc8d02b33d
  **Blocked by:** task_b2a51ae161917cc9b7549e98560500f7
  **Outcome:** Maintainers can launch either the legacy shell or the modern shell over the same project collection and VisPy canvas without changing the default experience.
  **Acceptance:** The flag defaults off, both shells open the same project and canvas, switching shells requires restart, and legacy saved window state is neither overwritten nor misread by the new shell.
  **Expected evidence:** Startup and project-open smoke results for both flag values plus screenshot comparison of the shared canvas content.
  **Execution size:** Large
  **Uncertainty:** High — current widget ownership and canvas parenting may expose hidden coupling.
      Stop and document the ownership boundary if integration requires duplicating project
      state or changing VisPy rendering. Do not fall back to two diverging application models.

  **Implement:** `appMain.py` · `appGUI/MainGUI.py` · `defaults.py`
  **Context:** `appGUI/workspace/shell.py` · `appGUI/workspace/window_state.py` · `tests/test_frontend_characterization.py`
  **Route:** claude
  **Context Load:** 4067
  **Chars:** ~677,756 text total (largest: appMain.py ~362,144) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 5 🥇 · Class 2 — Specify the isolation workflow view-model contract**
  **ID:** task_8a132b4fc5bdb30dd33332aa039aabee
  **Status:** Ready
  **Outcome:** The isolation workflow has a reviewed toolkit-neutral state, intent, validation, progress, and result contract before its widgets are replaced.
  **Acceptance:** The contract covers source selection, tool table editing, basic/advanced fields, validation messages, cancellation, progress, generated geometry, and every existing option consumed by the happy path.
  **Expected evidence:** A field/intent/result mapping with current code citations and explicit unresolved cases; no production-code change.
  **Execution size:** Medium
  **Uncertainty:** Medium
      Separate observed behavior from proposed behavior. Do not simplify or rename persisted
      option keys in the contract.

  **Write:** `docs/frontend/isolation-workflow-contract.md`
  **Context:** `appPlugins/ToolIsolation.py` · `defaults.py` · `tests/test_tool_isolation_defaults.py`
  **Route:** claude
  **Context Load:** 897
  **Chars:** ~224,353 text total (largest: appPlugins/ToolIsolation.py ~179,409) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 5 🥇 · Class 2 — Implement the isolation workflow view model**
  **ID:** task_18f5bdea25b7e2aa765099cdb2e93aa2
  **Status:** Blocked
  **Blocked by:** task_8a132b4fc5bdb30dd33332aa039aabee
  **Outcome:** Isolation state, validation, and operation intents can be exercised without constructing the isolation QWidget panel.
  **Acceptance:** The view model maps every contracted option bidirectionally, emits deterministic validation and progress state, and delegates geometry generation through an injected adapter rather than reimplementing it.
  **Expected evidence:** Unit tests using a fake generation adapter plus parity tests for defaults and option serialization.
  **Execution size:** Medium
  **Uncertainty:** Medium
      Do not move or modify geometry algorithms. Any behavior not covered by the contract is
      reported for review rather than guessed.

  **Write:** `appGUI/workflows/__init__.py` · `appGUI/workflows/isolation.py` · `tests/test_isolation_view_model.py`
  **Context:** `docs/frontend/isolation-workflow-contract.md` · `defaults.py`
  **Route:** kimi
  **Context Load:** 219
  **Chars:** ~43,710 text total (largest: defaults.py ~43,710) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 5 🥇 · Class 2 — Build the modern isolation workflow panel**
  **ID:** task_86945ddc6be840a170fa6b6afb28e637
  **Status:** Blocked
  **Blocked by:** task_18f5bdea25b7e2aa765099cdb2e93aa2
  **Blocked by:** task_a1d96649d5aedf84e2b5f7ac845fb32b
  **Outcome:** The new inspector panel presents isolation as a clear staged workflow with progressive disclosure while consuming only the view-model contract.
  **Acceptance:** Source, tools, cut parameters, preview/generate action, inline validation, progress, cancellation, and advanced disclosure are keyboard accessible and do not import `ToolIsolation` directly.
  **Expected evidence:** Panel tests against a fake view model plus reviewed light/dark screenshots at compact and comfortable density.
  **Execution size:** Medium
  **Uncertainty:** Low
      No real geometry generation or project mutation belongs in the panel.

  **Write:** `appGUI/workflows/isolation_panel.py` · `tests/test_isolation_panel.py`
  **Context:** `appGUI/workflows/isolation.py` · `appGUI/design/components.py` · `docs/frontend/isolation-workflow-contract.md` · `research/frontend-stack-recommendation-2026-07-18.md`
  **Route:** kimi
  **Context Load:** 83
  **Chars:** ~13,795 text total (largest: research/frontend-stack-recommendation-2026-07-18.md ~13,795) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 5 🥇 · Class 2 — Integrate and verify the modern Gerber-to-isolation vertical slice**
  **ID:** task_95562ad7d3c169502b643926d6a158bc
  **Status:** Blocked
  **Blocked by:** task_58e5f64b932af3db186eac8085580f26
  **Blocked by:** task_86945ddc6be840a170fa6b6afb28e637
  **Outcome:** With the feature flag enabled, a user can import a Gerber, configure isolation, preview/generate geometry, and obtain output equivalent to the legacy workflow.
  **Acceptance:** Representative basic, advanced, multi-tool, validation-error, cancel, and retry cases produce equivalent project state and geometry; the legacy path remains available.
  **Expected evidence:** Automated equivalence results, recorded UI run, reviewed geometry overlays, and a list of intentionally changed interactions.
  **Execution size:** Large
  **Uncertainty:** High
      This is a human/senior integration boundary. Compilation and tests do not establish
      machining safety; generated geometry requires explicit visual review and no physical
      operation is authorized by this task.

  **Implement:** `appPlugins/ToolIsolation.py` · `appGUI/workspace/shell.py` · `appMain.py`
  **Write:** `research/frontend-vertical-slice-results.md`
  **Context:** `appGUI/workflows/isolation.py` · `appGUI/workflows/isolation_panel.py` · `tests/test_frontend_characterization.py`
  **Route:** claude
  **Context Load:** 3791
  **Chars:** ~541,553 text total (largest: appMain.py ~362,144) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

### 6.4 Evidence-based stack checkpoints

- [ ] **Score 3 🥈 · Class 1 — Run a PySide6 compatibility and packaging spike**
  **ID:** task_4b78493aceb484a7f5fca8f1b8fd9bb3
  **Status:** Blocked
  **Blocked by:** task_9cd4932d30bbf23710d82cfc8d02b33d
  **Outcome:** The project has measured evidence for or against migrating from PyQt6 to the official PySide6 binding.
  **Acceptance:** An isolated environment imports the facade-selected binding, starts the shell prototype, hosts a VisPy canvas, runs representative tests, and produces a disposable Windows package attempt without changing production defaults.
  **Expected evidence:** Versioned command log, compatibility failures by category, package size/startup measurements, licensing questions, and a keep/defer recommendation.
  **Execution size:** Medium
  **Uncertainty:** Medium
      Keep experimental dependencies and generated packages out of production requirements.
      Licensing findings are inputs for counsel, not legal conclusions.

  **Write:** `research/pyside6-compatibility-spike.md`
  **Context:** `appGUI/qt.py` · `appGUI/VisPyPatches.py` · `appGUI/workspace/shell.py` · `requirements.txt`
  **Route:** kimi
  **Context Load:** 37
  **Chars:** ~7,411 text total (largest: appGUI/VisPyPatches.py ~5,237) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 3 🥈 · Class 1 — Benchmark a Qt Quick workspace shell spike**
  **ID:** task_ce6091623c73812a22a3f701e8aa81ca
  **Status:** Blocked
  **Blocked by:** task_9cd4932d30bbf23710d82cfc8d02b33d
  **Outcome:** Widgets and Qt Quick are compared using the same shell structure and representative canvas-host workload rather than generic demos.
  **Acceptance:** A disposable QML shell measures startup, idle memory, resize latency, focus/accessibility behavior, and VisPy embedding or composition constraints on the target Windows system.
  **Expected evidence:** Reproducible benchmark commands, results table, screenshots, and a keep/defer recommendation with failures retained.
  **Execution size:** Medium
  **Uncertainty:** High — VisPy and QQuickWidget composition may invalidate the hybrid approach.
      Keep the spike outside production startup and packaging. Do not port workflow logic to
      QML or use animation quality as the sole decision criterion.

  **Write:** `experiments/qml_workspace/Main.qml` · `experiments/qml_workspace/run.py` · `research/qml-workspace-benchmark.md`
  **Context:** `appGUI/workspace/shell.py` · `appGUI/PlotCanvas.py` · `research/frontend-stack-recommendation-2026-07-18.md`
  **Route:** kimi
  **Context Load:** 245
  **Chars:** ~40,798 text total (largest: appGUI/PlotCanvas.py ~27,003) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

- [ ] **Score 5 🥇 · Class 2 — Decide the maintained frontend stack after the vertical slice**
  **ID:** task_d02d2a442f4a0bc78953d5ceb74f3809
  **Status:** Blocked
  **Blocked by:** task_4b78493aceb484a7f5fca8f1b8fd9bb3
  **Blocked by:** task_ce6091623c73812a22a3f701e8aa81ca
  **Blocked by:** task_95562ad7d3c169502b643926d6a158bc
  **Outcome:** FlatCAM records an evidence-backed ADR choosing PyQt6 Widgets, PySide6 Widgets, Qt Quick, or a deliberately deferred decision for the remainder of the makeover.
  **Acceptance:** The decision compares implementation effort, contributor skill burden, testability, package size, startup and canvas performance, licensing constraints, migration reversibility, and golden-workflow parity.
  **Expected evidence:** A reviewed ADR citing both spikes and vertical-slice measurements, with explicit rejected alternatives and revisit triggers.
  **Execution size:** Small
  **Uncertainty:** Medium
      This is a reviewer-owned decision. AI may assemble evidence and challenge assumptions
      but must not select the stack unattended.

  **Write:** `docs/adr/frontend-stack.md`
  **Context:** `research/frontend-stack-recommendation-2026-07-18.md` · `research/frontend-vertical-slice-results.md` · `research/pyside6-compatibility-spike.md` · `research/qml-workspace-benchmark.md` · `docs/frontend/behavior-baseline.md`
  **Route:** kimi
  **Context Load:** 83
  **Chars:** ~13,795 text total (largest: research/frontend-stack-recommendation-2026-07-18.md ~13,795) — exceeds chatgpt's ~5,000-char inline-paste budget; that file can't go to chatgpt at all

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
