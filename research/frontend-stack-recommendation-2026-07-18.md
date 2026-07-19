# Research brief: FlatCAM frontend technology direction

**Status:** Independent research pass
**Date:** 2026-07-18
**Question:** Should FlatCAM adopt a newer Qt version, move from Qt Widgets to Qt Quick, or replace its Python desktop frontend?
**Method:** Inspected the local runtime and UI coupling, then checked current first-party Qt, Qt for Python, PyQt, Electron, and Flutter documentation. Recommendations distinguish observed facts from inference.

## Executive finding

FlatCAM should not abandon Python or Qt for the planned makeover. The checkout already runs Python 3.12.10, PyQt 6.11.0, Qt 6.11.0, and VisPy 0.16.2. Qt 6.11 is the current stable feature line; Qt 6.12 is still in beta with a planned final release on 2026-09-22.[1][2] There is no major Qt upgrade waiting to make the application look modern.

The recommended path is:

1. Keep Qt Widgets and VisPy for the main application and modernize the shell incrementally.
2. First separate operation state and commands from QWidget construction so screens become testable and replaceable.
3. Evaluate a PyQt6-to-PySide6 binding migration as a separate licensing and maintainability project, not as a visual redesign dependency.
4. Pilot Qt Quick/QML only for a self-contained surface after the architecture boundary exists; do not mix QML into the VisPy-heavy main window without performance measurements.
5. Reconsider a web or non-Python shell only if FlatCAM adopts a product requirement that Qt cannot economically serve, such as a browser version, cloud collaboration, or a shared desktop/web UI team.

## Observed local facts

- The active virtual environment reports Python 3.12.10, PyQt 6.11.0, Qt 6.11.0, and VisPy 0.16.2.
- The repository contains 178 Python files mentioning PyQt6, 154 mentioning QtWidgets, and 45 using PyQt-specific signal/slot decorators.
- `appGUI/MainGUI.py` is 5,630 lines; `appGUI/GUIElements.py` is 6,340 lines. The main window constructs ten toolbars and hundreds of actions, while style calls are distributed through the UI and plugins.
- The VisPy canvas is embedded as a native Qt widget, and `appGUI/VisPyPatches.py` imports a private VisPy PyQt6 backend. The installed VisPy package also includes a PySide6 backend, so a binding migration is plausible but not zero-cost.
- The application license file is MIT. PyQt is GPLv3/commercial rather than LGPL; PySide6 is the official Qt binding and is offered under LGPLv3/GPLv3 or commercial terms.[3][4] Distribution implications need legal review; they are not resolved by this technical brief.

## Current Qt choices

### Qt 6.11 and 6.12

Qt 6.11 shipped on 2026-03-23, and Qt 6.11.1 followed with bug and security fixes.[1][5] PyQt 6.11 added Qt 6.11 support on 2026-03-30.[3] Qt 6.12 is currently beta, so it should be watched but not used as the production baseline before a stable release and dependency compatibility testing.[2]

Qt 6.10 improved high-contrast integration for both Widgets and Quick, which is relevant to accessibility but does not replace application-level information architecture and component work.[6]

### Qt Widgets

Qt's current documentation describes Widgets as mature, feature-rich, and suited to complex desktop applications. It has the stronger stock desktop control set and comprehensive model/view widgets.[7] That matches FlatCAM's dense property editors, trees, tables, menus, file dialogs, and keyboard/mouse workflow.

Widgets are not inherently responsible for the current visual age. FlatCAM's visual debt comes primarily from crowded permanent toolbars, plugin-by-plugin form construction, PNG-heavy iconography, globally reset spacing, and scattered inline styles. A semantic token layer, consistent components, contextual commands, and redesigned workflow panels can materially modernize it without replacing the toolkit.

## Maintainability assessment

The main maintainability problem is not Python. It is that presentation, widget construction, application state, command wiring, persistence, and domain operations are interleaved. Evidence includes 5,630 lines in the main-window module, 6,340 lines in the shared widget module, 178 PyQt-coupled files, private VisPy backend imports, and plugin panels that construct and wire large forms directly.

This makes a framework rewrite especially risky: a new frontend would first have to discover and reproduce behavior that is not expressed through stable interfaces. Rewriting before extracting those interfaces trades visible legacy code for hidden compatibility bugs.

### What improves maintainability most

1. **Create a binding compatibility seam.** Application code should import Qt types from one local compatibility module. That localizes a future PyQt6/PySide6 change and removes direct dependence on binding-specific names.
2. **Separate commands from controls.** Define application commands once—with stable ID, label, icon, shortcut, availability, handler, and danger level—and let menus, toolbars, command search, and context menus render the same command objects.
3. **Introduce workflow view models.** A panel should render state and emit intents; it should not own geometry operations, project mutation, persistence, and notifications. Start with isolation, drilling, and export.
4. **Split large modules by responsibility.** `MainGUI.py` should become a shell composed from navigation, canvas host, inspector, task center, and window-state services. `GUIElements.py` should become focused control modules with explicit public APIs.
5. **Replace style scatter with semantic tokens and components.** Theme values such as surface, text, focus, warning, spacing, and density should have one source. Feature code should not contain arbitrary colors or widget-specific style sheets.
6. **Put third-party integrations behind adapters.** VisPy, serial communication, file dialogs, settings, and background jobs need narrow interfaces and contract tests. Private VisPy APIs should be isolated to a single adapter.
7. **Add characterization tests before relocation.** Capture current command availability, option mapping, project mutation, and generated artifacts before moving UI code. Visual smoke tests should complement, not replace, output-equivalence tests.

### Maintainability by technology choice

- **PyQt6 + Widgets:** one language and the smallest change surface. It is maintainable if the code is decomposed; keeping the current structure would merely preserve the debt.
- **PySide6 + Widgets:** still one language and the same Qt mental model. The official binding and deployment tooling are attractive, but the migration should follow the compatibility seam so it is mechanical and testable.
- **Python + QML:** can enforce a useful presentation/view-model boundary, but introduces QML and some JavaScript alongside Python. This is a net maintainability gain only if the team will maintain QML expertise and avoids putting domain logic into QML.
- **Web shell + Python backend:** gives strong frontend component and testing ecosystems, but creates two applications, two dependency graphs, an IPC/API compatibility contract, and desktop security/packaging work. For a small desktop-focused project, that is usually a maintainability loss even if TypeScript UI recruitment is easier.
- **C++/Rust/.NET rewrite:** stronger static tooling can improve local correctness, but the rewrite cost, Python-domain bridging, and loss of behavioral knowledge dominate for years. Static typing can be introduced incrementally in the existing Python boundaries without replacing the frontend.

The key sequencing rule is therefore: **extract stable behavior first; choose rendering technology second**. Once commands and view models are toolkit-neutral, the team can compare Widgets, QML, and a web shell with a real vertical slice rather than betting the whole product.

### Qt Quick/QML

Qt Quick provides declarative composition, GPU-accelerated animation, and more flexible custom visuals; Qt recommends it for fluid and touch-oriented interfaces.[7] It is a credible option for new, self-contained experiences such as onboarding, a job progress center, or a future touch controller.

It is not a free visual upgrade for this codebase. Mixing QML into a QWidget window via `QQuickWidget` adds an offscreen render pass and disables Qt Quick's threaded render loop.[8] FlatCAM already embeds a GPU-backed VisPy canvas, so a hybrid main window must be prototyped and profiled before adoption. A full QML shell would also require view-model and command boundaries that the current QWidget-heavy code does not yet provide.

## Python binding choice

PyQt 6.11 is current and technically viable.[3] Staying on it minimizes risk during the makeover.

PySide6 deserves a separate evaluation because it is the official Qt for Python binding, follows Qt releases, supports both Widgets and Quick, and has an official deployment tool based on Nuitka.[4][9] It may also align licensing more naturally with an MIT application, subject to actual LGPL compliance and legal review. The migration still touches imports, signal/slot names, ownership/lifetime behavior, tests, packaging, and the private VisPy backend patch, so it should not be bundled into the visual redesign.

## Alternatives outside Qt

### Electron or Tauri-style web shell

Electron embeds Chromium and Node and splits the application across main and renderer processes.[10] A web shell would enable a large design ecosystem and could share UI with a future browser product. For FlatCAM today it would also require a new IPC contract, frontend state model, canvas/rendering strategy, native file and serial integration, packaging pipeline, and likely parallel Python and JavaScript runtimes. The existing `flatcam_core` and service API are useful seeds, but they do not make the current UI replaceable yet.

This becomes rational only if browser delivery or cloud collaboration is a strategic requirement. It is poor economics for a desktop-only visual refresh.

### Flutter, Rust-native, C++, or .NET UI

Flutter supports Windows, macOS, and Linux desktop builds.[11] Other native stacks can also produce excellent desktop applications. None offers an incremental migration path for the existing PyQt/VisPy UI. Each turns a makeover into a product rewrite and forces integration or replacement of the Python geometry, plugin, editor, and rendering layers.

C++ Qt would reduce interpreter overhead in UI code but would not automatically improve usability, and UI latency should be profiled before attributing it to Python. Rust or .NET can make sense for a new product with a new team and architecture; they do not solve FlatCAM's immediate navigation and workflow problems.

## Decision matrix

| Option | Visual ceiling | Migration risk | Ongoing stack complexity | Reuses current canvas/UI | Recommendation |
|---|---:|---:|---:|---:|---|
| PyQt6 + Widgets redesign | High | Low | Low, after decomposition | Very high | Start here |
| PySide6 + Widgets | High | Medium | Low | High | Evaluate separately |
| Python + full Qt Quick shell | Very high | High | Medium: Python + QML | Medium/low | Prototype later |
| Electron/Tauri + Python service | Very high | Very high | High: web + IPC + Python | Low | Only for web strategy |
| Flutter/Rust/.NET/C++ rewrite | Very high | Extreme | Medium/high during long transition | Very low | Do not pursue now |

## Suggested decision and experiment

Adopt Qt 6.11.x as the current stable target and test Qt 6.12 only after its stable release. Keep PyQt6 during the first modernization slice.

Before choosing QML or a different toolkit, build one vertical slice in Widgets using the proposed architecture:

- a command registry independent of toolbar construction;
- a view model for one golden workflow (Gerber import to isolation geometry);
- a modern shell with project tree, canvas, contextual inspector, and job status;
- semantic design tokens and reusable controls;
- UI tests that drive the workflow without CAM output changes.

Measure startup time, canvas frame rate, workflow completion time, error rate, memory, and implementation effort. Then reproduce only the shell or one panel in Qt Quick as a time-boxed prototype. A toolkit change should win on measured usability and delivery cost, not screenshots.

## Contradictions and uncertainty

- Qt Quick has a higher ceiling for animation and bespoke visuals, while Widgets better match dense desktop controls. Which wins for FlatCAM depends on how much animation/touch matters; the proposed desktop workflow does not require much.
- PySide6 licensing appears more compatible with permissive distribution than PyQt's GPL/commercial model, but exact obligations depend on how FlatCAM is distributed and must be reviewed by qualified counsel.
- No prototype benchmark was run. In particular, Qt Quick/VisPy composition behavior on target Windows GPUs remains an evidence gap.

## Sources

1. Qt 6.11 release announcement: https://www.qt.io/blog/qt-6.11-released
2. Qt 6.12 release plan: https://wiki.qt.io/Qt_6.12_Release
3. PyQt 6.11 release announcement: https://riverbankcomputing.com/news/PyQt_v6.11.0_Released
4. Qt for Python overview and licensing: https://doc.qt.io/qtforpython-6/
5. Qt 6.11.1 release announcement: https://www.qt.io/blog/qt-6.11.1-released
6. Qt 6.10 release announcement: https://www.qt.io/blog/qt-6.10-released
7. Qt UI technology comparison: https://doc.qt.io/qt-6/topics-ui.html
8. QQuickWidget performance considerations: https://doc.qt.io/qt-6/qquickwidget.html
9. PySide6 deployment tool: https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html
10. Electron process model: https://www.electronjs.org/docs/latest/tutorial/process-model
11. Flutter desktop support: https://docs.flutter.dev/platform-integration/desktop
