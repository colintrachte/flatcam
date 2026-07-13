# FlatCAM Headless Decoupling Audit (v2)

Stage 1, prompt 1D.1 — extended after review. Goal: run FlatCAM's CAM engine
with **no QApplication and no Qt event loop**, driven by a headless service.

**v2 reframes the objective.** The risk is *not* Qt — Qt coupling is small and
mechanical (§A). The real risk is extracting the engine without simultaneously
defining the **runtime-agnostic library** and **project/operation model** that
replace the GUI-centric object graph. So the target is no longer "remove Qt"; it
is: **the FlatCAM engine never depends on any runtime environment.** Qt-desktop,
headless service, CLI, and future cloud all become *adapters* over one library.

---

## A. Qt coupling (the easy part — unchanged findings)

- `camlib.py` domain classes inherit from `object`, not `QObject`
  (`class Geometry(object)`, `class CNCjob(Geometry)`). No `pyqtSignal`, no
  `QThread` in camlib.
- GUI is bolted on via mixins one level up: `GerberObject(FlatCAMObj, Gerber)`,
  etc., where `FlatCAMObj(QtCore.QObject)`.
- camlib coupling = the injected `self.app` (390 refs → ~13 members): `log`
  (136), `inform`/`.emit` (81+4), `options` (77, **read-only**), `proc_container`
  (34), `abort_flag` (32), `preprocessors` (7), `exc_areas` (7), units/format
  (~12), `ui`/`plotcanvas` (2). `QApplication.processEvents()` appears 5× in long
  loops.
- Threading lives in `appWorker.py`/`appWorkerStack.py`, **not** camlib. CAM
  functions are synchronous.
- Parsers are nearly Qt-free (`ParseSVG/DXF/Excellon` = 0 Qt refs).

Conclusion stands: camlib is a non-Qt library wearing a thin `self.app` coat.

---

## B. Target architecture: a runtime-agnostic library, not "headless mode"

Insert a library stage between the engine and any transport. **FastAPI is the
last step, and a thin one.**

```
camlib + parsers           (existing engine algorithms — keep, wrap)
      ↓
flatcam_core/              (NEW: pure-Python, runtime-agnostic library)
   ├─ AppContext           runtime PORT (logging, events, progress, cancel, config)
   ├─ Project / Document / Operation / Artifact   (durable model = contracts/v1 .lwf)
   ├─ OperationRunner      executes operations over the dependency graph
   ├─ ParserRegistry       file → native geometry
   ├─ GeometryEngine       offset/union/diff/simplify/repair/pocket (interface)
   └─ MachineBackend       preprocessors → G-code per controller flavor
      ↓
Adapters:  DesktopAdapter(Qt) · HeadlessAdapter · CLIAdapter · (CloudAdapter)
      ↓
FastAPI    (thin wrapper over flatcam_core — one of the adapters)
```

Two consequences:
1. **The transport API never sees `GerberObject`/`CNCJobObject`.** Those are
   implementation details behind `flatcam_core`. The API speaks
   `OperationRequest`/`OperationResult` (contracts/v1 types).
2. **`flatcam_core` is independently usable** — CLI, tests, scripting, and the
   future desktop reuse it without HTTP.

`flatcam_core`'s model is the **runtime twin of `contracts/v1`**: `Project`,
`Document`, `Operation`, `Artifact`, `MachineProfile`, `MaterialProfile`
serialize directly to/from `project.lwf`. Build the model and the contract
together so they never diverge.

---

## C. AppContext as the runtime port (centerpiece, not an aid)

`AppContext` is the single seam the engine depends on. Adapters implement it:

| Capability | Desktop adapter | Headless/CLI adapter |
|---|---|---|
| `log` | Qt console + file | stdlib logging |
| `events` (was `inform`) | Qt signals → UI | event stream → WS/stdout |
| `progress` (was `proc_container`) | progress widget | progress events |
| `cancel` (was `abort_flag`) | shared flag | **per-job** `threading.Event` |
| `config` (was `options`) | live settings | per-request snapshot (read-only) |
| `preprocessors` | registry | registry |
| `processEvents` | real call | no-op |

The engine imports none of these concretely — only the `AppContext` interface.

---

## D. Operation layer — move early (was step 5 → now step 2)

Define the operation vocabulary up front so extraction targets a stable surface:

```
OperationRequest(kind, inputs[], parameters{}, toolId, machineProfile, material)
OperationResult(status, outputs[], warnings[], events[], timings{})
```

Concrete operations (thin, declarative): `ImportGerber`, `ImportExcellon`,
`Isolation`, `Drill`, `Cutout`, `Pocket`, `NCCClear`, `Follow`, `ExportGCode`.
Each maps an `OperationRequest` onto camlib calls and returns contracts/v1
`Toolpath`/`GCodeProgram`. The headless API and the desktop GUI both submit
`OperationRequest`s — one execution path, two front-ends.

---

## E. Project model + dependency graph — not a dict

Do **not** reimplement `ObjectCollection` as `objects[id] = obj`; that is debt on
day one. Build the real model (it is the runtime form of `project.lwf`):

```
Project ├─ Documents  ├─ Operations (graph nodes)  ├─ Artifacts  └─ Metadata
```

Capture the **dependency graph** during extraction, because FlatCAM already
behaves like one (`Gerber → Isolation → Toolpath → GCode`):

```
OperationNode(inputs=[docIds|opIds], params) → ArtifactNode(toolpath|gcode)
```

This is the same DAG defined in `contracts/v1/project.lwf.schema.json`. Capturing
it now makes undo, regeneration (run stale nodes topologically), and multi-board
jobs trivial later instead of a retrofit. `OperationRunner` walks this graph.

---

## F. Geometry Core — extract before operations (NEW step)

Between parsers and operations, isolate the geometry primitives that operations
(and, later, laser workflows) all share:

```
GeometryEngine: offset · union · difference · intersection · simplify · repair · pocket
```

In Stage 1 this is an **interface** over the current shapely-backed
implementation — no behavior change, just a seam. It is the exact seam the plan's
**Stage 3A shared Clipper2 Geometry Service** swaps into later: define
`GeometryEngine` now (shapely impl) → replace the impl with Clipper2/`pyclipr`
in Stage 3 with zero call-site churn. This reconciles "extract geometry early"
(here) with "shared cross-stack geometry service later" (plan 3A) — same
interface, two implementations over time.

---

## G. MachineBackend (preprocessors) — elevate and audit separately

Preprocessors are not a "medium" detail; they are the **machine abstraction
layer** for G-code generation (GRBL, FluidNC, LinuxCNC, Marlin, custom). Audit
`preprocessors/` on its own before touching G-code emit, and model it as
`MachineBackend` in `flatcam_core`, selected by `MachineProfile.preprocessor`
(contracts/v1).

**Keep two machine layers distinct** (they are different concerns):
- `MachineBackend` / preprocessor = *how G-code is written* (dialect/flavor). Lives
  in `flatcam_core`.
- `lw.comm-server` firmware handling = *how G-code is streamed* to a live
  controller. Lives in the device gateway.
Both reference the same `dialect`/`firmware` enum in contracts/v1, but never
merge them.

---

## H. Structured events — richer than `inform(level, text)`

Status must be structured so REST/WS/CLI/desktop consume one stream:

```
Event(type="progress", source="isolation", level="info",
      message="Generating geometry", percent=42)
```

This is the runtime form of the `Job` progress/warnings in contracts/v1; add a
structured `progress` event to the contract so the `WS /jobs/{id}` stream and the
desktop status bar render from identical data. `AppContext.events` replaces the
raw `inform.emit` strings (which are currently gettext-wrapped — keep a `_()`
shim).

---

## I. Concurrency / global-state risk (grounded)

A service fails differently from a desktop app: the *first* request works, the
*second concurrent* one corrupts shared state. Evidence from the tree:

- **Good:** camlib has **0** `global` statements, **0** module-level mutable
  globals, **0** singletons/`lru_cache`. `defaults.py` uses instance-based
  `LoudDict` (not a module singleton). `options` is **read 75× / written 0×** in
  camlib — read-only config, safe to share or snapshot.
- **Real hazards (narrow):**
  1. `abort_flag` is a single shared cancel flag → **must be per-job** (one
     abort must not kill all jobs). Move onto `AppContext.cancel`.
  2. `AppContext` must **not** be a process singleton — instantiate **per
     request/job** so per-request material/machine params and the per-job cancel
     are isolated. `options` is read-only, so a per-request snapshot is safe.
  3. Per-instance geometry caches on camlib objects are fine **iff** objects are
     never shared across requests (the `Project`-per-request model guarantees
     this).

Action: add a **global-state audit** task and a concurrency smoke test (two
simultaneous isolation jobs, assert independent cancel + identical output).

---

## J. Performance instrumentation — before changing anything

A service layer adds overhead the desktop never had. Capture a baseline first so
extraction can't silently regress CAM by 10×. For every operation record:
`wall_ms`, `peak_rss`, input polygon/segment counts, output toolpath/segment
counts. Emit via `AppContext.events` (`timings{}` on `OperationResult`) and store
golden timings alongside the golden G-code files (plan 1F.1).

---

## K. Revised decoupling order

1. ✅ **AppContext** (runtime port) + structured `Event` model.
   → `flatcam_core/context.py`: `AppContext` ABC, `HeadlessAdapter`, `Event` dataclass.

2. ✅ **Operation layer** — `OperationRequest`/`OperationResult` + `OperationKind` enum.
   → `flatcam_core/operations.py`: declarative shells + `REQUIRED_PARAMS` table.

3. ✅ **Parsers** onto `AppContext` via `ParserRegistry`.
   → `flatcam_core/parsers.py`: registry with case-insensitive dispatch.

4. ✅ **Geometry Core** — `GeometryEngine` interface over current shapely impl.
   → `flatcam_core/geometry.py`: `GeometryEngine` ABC + `ShapelyGeometryEngine`.

5. ✅ **camlib base classes** (`Gerber/Excellon/Geometry/CNCjob`) on `AppContext`;
   smoke: Gerber → isolate → toolpath.
   → `flatcam_core/compat.py`: `AppContextFacade` + `HEADLESS_DEFAULTS`.
   → `tests/test_smoke_headless.py`: 26 passing tests (Gerber init, isolation, cancel).
   *Note: camlib unchanged — facade satisfies its duck-type `self.app` interface.*

6. ✅ **Project model + dependency graph** + `OperationRunner` (replaces
   `ObjectCollection` headless).
   → `flatcam_core/project.py`: `Project`, `Document`, `OperationNode`, `Artifact`.
   → `flatcam_core/runner.py`: `OperationRunner` with topological walk + dry-run.

7. ✅ **MachineBackend** — separate preprocessor audit → headless G-code emit.
   → `flatcam_core/machine.py`: `ToolpathParams` (typed `p` dataclass), `MachineBackend` ABC
     (11 abstract methods + shared `position_code`/`startz_code`/`dwell_code` defaults),
     `MachineRegistry` (`__getitem__` for legacy compat), `PreProcAdapter` (wraps all 28
     existing preprocessors without changing them), `load_machine_registry()`.
   → `tests/test_machine.py`: 36 passing tests (params, bed-skew math, registry, adapter,
     integration load of real preprocessors).

8. ✅ **Global-state + concurrency hardening** (per-job cancel, per-request context,
   concurrency test). *(medium)*
   → `tests/test_concurrency.py`: 14 passing tests.
   Confirmed: `HeadlessAdapter.cancel` is per-instance (`threading.Event`); `config` and
   `AppContextFacade.options` are `MappingProxyType` (immutable). Concurrent
   `isolation_geometry` on separate adapters is deterministic and cancel-isolated.
   `MachineRegistry` reads are thread-safe. No module-level mutable singletons found.

9. ⬜ **Lift logic out of `on_*` GUI handlers** in CNCJob/Geometry, guided by
   golden-file + golden-timing tests. *(hard, last)*

10. ⬜ **FastAPI** thin wrapper over `flatcam_core`. *(easy once 1–9 land)*

Steps 1–8 are complete; headless Gerber → isolation → toolpath is proven in CI,
all 28 preprocessors are loadable and callable without a QApplication, and
concurrent per-job isolation is verified with 14 concurrency tests.
Step 9 (lift logic from `on_*` GUI handlers) is the next frontier.

---

## L. What stays in the desktop app

`FlatCAMObj`, `ObjectCollection` (QAbstractItemModel), all `set_ui/build_ui`,
VisPy canvas, `appWorker*` — the desktop keeps these and provides the
`DesktopAdapter` implementation of `AppContext`. Desktop and `flatcam-core` then
share one engine and one operation model.

## Bottom line

Qt is the easy 20%. The valuable 80% is standing up `flatcam_core` as a
runtime-agnostic library whose `Project/Operation/Artifact` model **is** the
`contracts/v1` `.lwf` model, with `AppContext` as the only runtime dependency,
`GeometryEngine` and `MachineBackend` as swappable layers, structured events, and
per-request isolation. Do that and FlatCAM extraction, LaserWeb integration,
headless automation, scripting, and a future plugin system all hang off one
durable spine — without tying the design to either legacy codebase.
