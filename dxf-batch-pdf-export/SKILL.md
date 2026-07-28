---
name: dxf-batch-pdf-export
description: Export DXF or DWG drawing frames to batch PDFs with one drawing per PDF page on Windows. Use when Codex needs AutoCAD-based high-fidelity conversion of model-space drawing sheets, PFD/P&ID/process/plant-layout DXF files, centered/full-paper output, color and SHX font preservation, DXF preflight diagnostics, block/color/entity-cluster frame detection, default PDF viewer or WPS popup suppression, split-page PDFs, merged PDF sets, or PDF render verification.
---

# DXF Batch PDF Export

Use this skill for repeatable Windows DXF/DWG to PDF conversion when the source drawing contains one or more sheet frames and the result must be one drawing per PDF page. Preserve AutoCAD as the final rendering engine; use DXF parsing only for preflight diagnostics and page-window detection.

## Core Workflow

1. Resolve the real input path, output path, paper size, page order, and whether the user wants separate page PDFs, a merged PDF, or both.
2. Run `scripts/analyze_dxf_features.py` or the one-command workflow's default preflight to capture encoding, text/code risks, style fonts, entity distribution, and frame candidates in `preflight_report.json`.
3. Detect page windows with `scripts/detect_dxf_frames.py`. Use `--strategy auto` by default: block-frame detection first, then color-frame detection, then entity-cluster detection. Start with A1 landscape defaults for PFD/P&ID: `--frame-width 841 --frame-height 594 --tolerance 5 --sort top-left`.
4. Run a small AutoCAD sample first with `scripts/plot_dxf_windows_acad.ps1 -MaxPages 1` or the controller's `-MaxPages 1`. Use escalation because it controls AutoCAD through COM and may open GUI-owned resources.
5. If the sample is centered, colored, readable, and quiet, run the full plot. Keep `-IntermediateExtension .codexplot` unless the user explicitly needs a raw printer PDF extension.
6. Merge page PDFs with `scripts/merge_pdf_pages.py` when a combined PDF is required.
7. Verify with `scripts/verify_pdf_pages.py`: check page count and paper size; render first/middle/last pages when layout quality matters; review content margins and color pixels for centering/full-page issues.
8. If AutoCAD was started only for the conversion, use `scripts/cleanup_acad_if_idle.ps1` to close only an idle hidden AutoCAD instance.

For the common one-command path, use `scripts/convert_dxf_to_pdf_set.ps1`; it runs preflight, detection, AutoCAD plotting, merge, and verification while preserving per-step JSON logs in a work directory.

## Detection Strategy

- Prefer `block`: repeated inserted frame blocks are the most reliable and keep page order stable.
- Use `color`: when frames are drawn as colored lines/polylines rather than reusable blocks. Default color probe is AutoCAD color index `6` and can be changed with `-FrameColor` or `--frame-color`.
- Use `cluster`: when neither block nor color frames are reliable. Treat this as a last-resort window proposal and require sample plotting.
- Do not automatically modify the source drawing. If text, dimension, or symbol repair is needed, create a separate repaired DXF copy only after explicit user approval.

## Defaults That Preserve Fidelity

- Use AutoCAD plotting rather than lightweight DXF rendering when color, SHX fonts, text placement, linetypes, and CAD plotting rules matter.
- Use `DWG To PDF.pc3`, `ISO_full_bleed_A1_(841.00_x_594.00_MM)`, window plot, center plot, standard scale fit-to-paper, lineweights on, plot styles off by default.
- Use temporary `.codexplot` files and rename them to `.pdf` after `PlotToFile`; this avoids triggering WPS or the default PDF viewer for every generated page.
- Do not terminate WPS or other viewer processes. If suppression is needed, only close/minimize title-matched generated-page viewer windows, or ask the user before broader action.

## Information To Confirm

Confirm or infer these before full conversion: DXF/DWG file path, output folder/name, frame size and orientation, frame block if detection is ambiguous, frame color/layer when using color detection, page order, paper media name, color/plot-style expectations, whether to merge pages, verification scope, and whether an AutoCAD session can be reused.

## References

Read `references/diagnostics-and-detection.md` when preflight, color frames, cluster windows, text risks, or frame conflicts matter. Read `references/autocad-pdf-settings.md` when printer/media/SHX/color behavior is uncertain. Read `references/troubleshooting.md` when frame detection, AutoCAD COM, WPS popups, file locks, or Unicode paths cause failures.