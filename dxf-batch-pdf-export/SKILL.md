---
name: dxf-batch-pdf-export
description: Export DXF or DWG model-space drawing frames to batch PDFs with AutoCAD fidelity on Windows. Use for PFD, P&ID, plant-layout, process, and equipment drawings that need one frame per PDF page, colored/SHX-accurate plotting, standard A1 frame detection, title-block page ordering, WPS-popup avoidance, and rendered-PDF verification.
---

# DXF Batch PDF Export

Use this skill for Windows AutoCAD plotting where visual fidelity matters. AutoCAD is always the final renderer. DXF parsing is used only for non-destructive preflight and page-window detection.

## Core workflow

1. Confirm input/output paths, page size/orientation, page order, and separate versus merged PDFs.
2. Run `convert_dxf_to_pdf_set.ps1` with PowerShell's process-local execution-policy override: `powershell -NoProfile -ExecutionPolicy Bypass -File ...`.
3. For DWG input, let the controller create a temporary AutoCAD-exported DXF mirror inside `WorkDir`. Run preflight and frame detection on the mirror, then plot the original DWG. Never replace or save the source drawing.
4. Read `preflight_report.json`, `input_route.json`, and `frames.json` before full plotting. Start with `-MaxPages 1` whenever font, frame, plotter, or strategy uncertainty exists.
5. Use `-DetectionStrategy auto` unless a known block/layer is specified. The safe automatic order is `block → color → layer containing 图框 → cluster`.
6. Check `frames.json.pageOrder`. If every frame has a coherent title-block form such as `第x张 共x张`, output pages are sorted by that sequence. Otherwise the selected geometric sort is retained and a warning is recorded.
7. After a visually acceptable sample, run the full plot. Keep `.codexplot` intermediate files unless a raw PDF printer extension is essential.
8. Merge and verify outputs. Inspect first/middle/last rendered samples, page count, colors, and margin ratios before calling the job complete.

## AutoCAD COM and instance policy

- Default behavior creates a dedicated hidden AutoCAD instance. It waits for `AcadState.IsQuiescent` where available and retries only transient COM busy errors with bounded exponential backoff.
- The owned instance and conversion document are released in `finally`, including on page-level plot errors.
- Reuse requires explicit opt-in: `-ReuseExistingAutoCAD 1`. In that mode do not hide, close, or alter the user's application instance; only the document opened by this job is closed.
- Pass `-AutoCadProgId 'AutoCAD.Application.24'` for a known version. If omitted, the scripts discover registered ProgIDs and select the highest available one. Inspect `plot_results.json.autoCad` for the selected ProgID and reported version.
- Do not attempt to kill WPS, PDF viewers, or arbitrary AutoCAD processes. Clear genuine AutoCAD modal/license dialogs manually, then rerun.

## Detection safeguards

- `block`: preferred for repeated, correctly sized INSERT frame blocks.
- `color`: for frame geometry with an explicit AutoCAD color or requested layer filter.
- `layer`: finds standard-size components on layers whose name contains `图框` by default. Change this with `-FrameLayerToken`.
- `cluster`: last resort only. If it yields one window covering the model while multiple standard frame-layer candidates exist, the detector stops rather than silently producing an all-model PDF. Use `-DetectionStrategy layer`, or explicitly pass `-AllowSuspiciousCluster 1` only after manual confirmation.
- Use `-FrameWidth 841 -FrameHeight 594 -FrameTolerance 5` as A1 landscape starting values for PFD/P&ID work.

## Defaults that preserve fidelity

- `DWG To PDF.pc3`, `ISO_full_bleed_A1_(841.00_x_594.00_MM)`, window plot, center plot, fit-to-paper scale, lineweights on, plot styles off by default.
- Temporary `.codexplot` files are renamed to `.pdf` only after AutoCAD finishes, minimizing WPS/default-viewer popups.
- Source files remain untouched; all mirrors, reports, split pages, merged PDFs, and PNG samples reside in the chosen output/work directories.

## References

Read `references/diagnostics-and-detection.md` for strategy conflicts, named frame layers, page-number evidence, and DWG mirrors. Read `references/autocad-pdf-settings.md` for plotter/media/SHX behavior. Read `references/troubleshooting.md` for COM busy errors, execution policy, viewer popups, DWG mirrors, and recovery.