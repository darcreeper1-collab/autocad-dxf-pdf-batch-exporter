# AutoCAD DXF PDF Batch Exporter

A Codex skill for high-fidelity batch export of model-space DXF/DWG drawing frames to one-page-per-drawing PDFs on Windows. It keeps AutoCAD as the final plotting engine and uses DXF parsing only for preflight diagnostics and page-window detection.

中文简介：这是一个面向化工设计图、PFD、P&ID、厂区布置图等 CAD 图纸的 Codex skill。它通过 AutoCAD 原生 `PlotToFile` 批量输出 PDF，尽量保留颜色、SHX/TTF 字体、线型、文字位置和块显示效果，同时支持图框自动识别、WPS 弹窗规避和 PDF 抽样校验。

## Why AutoCAD-based plotting

Lightweight DXF renderers are useful for quick previews, but they can lose fidelity in SHX fonts, text placement, linetypes, plot settings, dimensions, and block visibility. This skill therefore uses AutoCAD COM automation for final PDF output and treats DXF parsing as a diagnostic and window-detection layer.

## Features

- Batch export one drawing frame per PDF page.
- Preserve AutoCAD-native plotting fidelity through `DWG To PDF.pc3`.
- Detect model-space page windows using three strategies:
  - repeated inserted frame blocks,
  - colored frame geometry,
  - entity-cluster fallback windows.
- Generate DXF preflight reports for encoding, text escape codes, style fonts, dimensions, layers, colors, and frame candidates.
- Avoid repeated WPS/default PDF viewer popups by plotting to `.codexplot` first and renaming to `.pdf` afterward.
- Merge split page PDFs into a combined PDF.
- Verify page count, page size, rendered sample non-blankness, color pixels, and content margins.

## Requirements

- Windows.
- AutoCAD installed and accessible through COM automation.
- AutoCAD PDF plotter, normally `DWG To PDF.pc3`.
- PowerShell.
- Python 3.10+ recommended.
- Python packages in `requirements.txt`.
- Poppler `pdftoppm.exe` for rendered PDF sample verification.

External components such as AutoCAD, Autodesk files, plotter configuration files, fonts, and Poppler are not bundled in this repository.

## Installation as a Codex skill

Copy the `dxf-batch-pdf-export` folder into your Codex skills directory, for example:

```powershell
Copy-Item -Recurse .\dxf-batch-pdf-export "$env:USERPROFILE\.codex\skills\dxf-batch-pdf-export"
```

Restart or refresh Codex so the skill is discovered.

## Typical use

Ask Codex to use the skill, for example:

```text
Use dxf-batch-pdf-export to export C:\drawings\process-flow.dxf to a one-page-per-frame PDF set. Use A1 landscape, preserve color, and verify first/middle/last pages.
```

The one-command controller is available at:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\dxf-batch-pdf-export\scripts\convert_dxf_to_pdf_set.ps1 `
  -InputDxf 'C:\drawings\process-flow.dxf' `
  -OutputPdf 'C:\drawings\process-flow.pdf' `
  -PythonExe 'python' `
  -FrameWidth 841 `
  -FrameHeight 594 `
  -DetectionStrategy auto `
  -RenderSamples 1
```

## Safety model

The default workflow does not modify the source DXF/DWG. It writes intermediate JSON reports, split PDFs, rendered samples, and merged PDFs into the chosen work/output directories. Text or dimension repair should be done only on a copied DXF after explicit user approval.

## Limitations

- The robust path is DXF-first. DWG files can be plotted by AutoCAD, but text-based preflight and frame detection currently expect DXF input.
- Rotated or deeply nested frames may need manual checking or a custom detection strategy.
- Entity-cluster detection is a fallback proposal, not a guaranteed drawing-sheet detector.
- Missing SHX/TTF fonts can still cause AutoCAD font substitution.
- AutoCAD COM automation is GUI-adjacent and may require closing modal dialogs or license prompts.

## Repository layout

```text
dxf-batch-pdf-export/
  SKILL.md
  agents/openai.yaml
  scripts/
  references/
```

## License

MIT. See `LICENSE`.
