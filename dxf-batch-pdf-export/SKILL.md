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
6. Check `frames.json.pageOrder`. Complete consistent title-block sequences support whitespace, comma/Chinese comma, slash/full-width slash, and semicolon separators (for example `第3张，共8张`). Otherwise retain geometric order and inspect the warning; never infer missing page numbers.
7. After a visually acceptable sample, run the full plot. Keep `.codexplot` intermediate files unless a raw PDF printer extension is essential.
8. Merge and verify outputs. Inspect first/middle/last rendered samples, page count, colors, and margin ratios before calling the job complete.

## AutoCAD COM and instance policy

- Default behavior creates a dedicated hidden AutoCAD instance. It waits for `AcadState.IsQuiescent` where available and retries only transient COM busy errors with bounded exponential backoff.
- Normal/caught failures attempt cleanup in `finally`; check `autoCad.cleanupFailed` and `comEvents`. Do not report successful cleanup merely from ownership.
- Both AutoCAD entry scripts run in supervised PowerShell workers. `-ComTimeoutSeconds` (default 120) controls busy retries; `-ComCallTimeoutSeconds` (default 300) limits time without a new COM operation, including calls that never return. Do not use the internal `-WorkerMode`/`-WorkerStatePath` parameters directly.
- On hard timeout the supervisor stops only its worker, retains `.acad-worker/<run-id>/` logs, and requests visibility for an identified owned AutoCAD window after PID/start-time checks. It never kills AutoCAD. Forced termination cannot run worker `finally` reliably. Activation that hangs before window identification requires manual recovery. Inspect residual instances/dialogs before retrying; do not launch repeated retries blindly.
- Reuse requires explicit opt-in: `-ReuseExistingAutoCAD 1`. In that mode do not hide, close, or alter the user's application instance; only the document opened by this job is closed.
- Pass `-AutoCadProgId 'AutoCAD.Application.24'` for a known version. If omitted, the scripts discover registered ProgIDs and select the highest available one. Inspect `plot_results.json.autoCad` for the selected ProgID and reported version.
- Do not attempt to kill WPS, PDF viewers, or arbitrary AutoCAD processes. Clear genuine AutoCAD modal/license dialogs manually, then rerun.

## Detection safeguards

- `block`: preferred for repeated, correctly sized INSERT frame blocks.
- `color`: for frame geometry with an explicit AutoCAD color or requested layer filter.
- `layer`: finds standard-size components on layers whose name contains `图框` by default. Change this with `-FrameLayerToken`.
- `cluster`: last resort only. Any single fallback cluster is unverified and stops by default, even without a `图框` layer. Specify `-FrameLayer 'FRAME,BORDER,TK'` or the actual layer, use verified frames, or pass `-AllowSuspiciousCluster 1` only after manual confirmation. A verified single block/color/layer frame does not require this override.
- Classic `POLYLINE` vertices are assembled from `VERTEX` records through `SEQEND` in model space and blocks. Straight 2D frames are supported; curved or non-world-plane geometry needs visual review.
- Use `-FrameWidth 841 -FrameHeight 594 -FrameTolerance 5` as A1 landscape starting values for PFD/P&ID work.

## Defaults that preserve fidelity

- `DWG To PDF.pc3`, `ISO_full_bleed_A1_(841.00_x_594.00_MM)`, window plot, center plot, fit-to-paper scale, lineweights on, plot styles off by default.
- Critical plot properties must be accepted and read back correctly before `PlotToFile`. An unavailable media/device is an error, never permission to fall back silently. Select an installed media name and rerun a sample.
- Temporary `.codexplot` files are renamed to `.pdf` only after AutoCAD finishes, minimizing WPS/default-viewer popups.
- Source files remain untouched; all mirrors, reports, split pages, merged PDFs, and PNG samples reside in the chosen output/work directories.
- PDF pixel checks use Pillow masks; Poppler discovery uses explicit path, PATH, then a small fixed set of relative locations, never recursive directory scanning. Use `--pdftoppm` with the verifier or configure PATH for the controller.

## References

Read `references/diagnostics-and-detection.md` for strategy conflicts, named frame layers, page-number evidence, and DWG mirrors. Read `references/autocad-pdf-settings.md` for plotter/media/SHX behavior. Read `references/troubleshooting.md` for COM busy errors, execution policy, viewer popups, DWG mirrors, and recovery.
