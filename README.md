# AutoCAD DXF PDF Batch Exporter

A Codex skill for high-fidelity, one-drawing-per-page PDF export from model-space DXF and DWG files on Windows. AutoCAD performs the final plot, preserving native colors, SHX/TTF fonts, line types, text positioning, dimensions, and block display better than lightweight DXF renderers.

中文简介：本项目通过 AutoCAD 原生 `PlotToFile` 批量输出 PDF。它对图框进行预检、识别和排序，并在输出后校验页数、页面尺寸、颜色、居中与铺满程度。源 DXF/DWG 始终保持不变。

## What it does

- Plots one model-space drawing frame per PDF page with `DWG To PDF.pc3`.
- Detects frames in this order: repeated frame blocks, colored geometry, standard-size geometry on layers containing `图框`, then entity clusters.
- Stops a suspicious one-window cluster result when multiple standard frame-layer sheets exist, unless explicitly overridden.
- Reads complete title-block text such as `第3张 共8张` and uses it for output order only when all frames form a consistent `1..N / N` sequence.
- Uses a `.codexplot` temporary extension before renaming output to PDF, reducing WPS/default-viewer popups without terminating unrelated applications.
- Makes a temporary AutoCAD-exported DXF mirror for DWG preflight and frame detection; it plots the original DWG for final fidelity.
- Records `input_route.json`, `preflight_report.json`, `frames.json`, `plot_results.json`, and verification reports in the work directory.

## Requirements

- Windows, PowerShell, Python 3.10+.
- AutoCAD installed with COM automation and `DWG To PDF.pc3`.
- Python packages in `requirements.txt`.
- Poppler `pdftoppm.exe` for rendered-page quality checks.

Run the supplied PowerShell scripts with a process-local execution-policy override:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\dxf-batch-pdf-export\scripts\convert_dxf_to_pdf_set.ps1 ...
```

`-ExecutionPolicy Bypass` applies only to that command process. It does not change the computer-wide or user-wide PowerShell policy.

## Installation as a Codex skill

```powershell
Copy-Item -Recurse .\dxf-batch-pdf-export "$env:USERPROFILE\.codex\skills\dxf-batch-pdf-export"
```

Restart or refresh Codex after copying.

## Typical DXF use

Start with one page, inspect it, then run the complete set:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\dxf-batch-pdf-export\scripts\convert_dxf_to_pdf_set.ps1 `
  -InputDxf 'C:\drawings\process-flow.dxf' `
  -OutputPdf 'C:\drawings\process-flow.pdf' `
  -PythonExe 'python' `
  -FrameWidth 841 -FrameHeight 594 `
  -DetectionStrategy auto `
  -MaxPages 1 -RenderSamples 1
```

After the sample passes visual review, remove `-MaxPages 1` and rerun to a new output/work directory.

## Complete DWG to multi-frame A1 PDF example

The source DWG is not changed. A temporary `input_mirror\<name>_diagnostic.dxf` is created under `WorkDir` for preflight and detection, while the original DWG is passed to AutoCAD for plotting.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\dxf-batch-pdf-export\scripts\convert_dxf_to_pdf_set.ps1 `
  -InputDxf 'D:\CAD\unit-layout.dwg' `
  -OutputPdf 'D:\CAD\out\unit-layout-A1.pdf' `
  -WorkDir 'D:\CAD\out\unit-layout-A1_work' `
  -PythonExe 'python' `
  -FrameWidth 841 -FrameHeight 594 -FrameTolerance 5 `
  -DetectionStrategy auto `
  -FrameLayerToken '图框' `
  -Sort top-left `
  -RenderSamples 1 -MaxMarginFraction 0.05
```

Inspect `input_route.json` and `frames.json`. If all title blocks contain a consistent form such as `第x张 共8张`, `frames.json.pageOrder.method` becomes `title-block-page-number` and the merged PDF follows that sequence.

## AutoCAD instance and COM policy

The default is safe isolation: the workflow creates a new hidden AutoCAD instance, waits for `AcadState.IsQuiescent` when available, retries only temporary COM-busy errors such as `RPC_E_CALL_REJECTED`, and closes that owned instance in `finally`.

Reuse is opt-in:

```powershell
-ReuseExistingAutoCAD 1 -AutoCadProgId 'AutoCAD.Application.24'
```

When reuse is selected, the workflow does not hide, quit, or alter the existing application instance; it only opens and later closes its own conversion document. Modal dialogs, license prompts, unsaved-document prompts, and long-running commands in that user session can still block automation.

`-AutoCadProgId` is optional. When omitted, the scripts inspect registered `AutoCAD.Application.*` ProgIDs and choose the highest discovered version. The actual selected ProgID and reported AutoCAD version are recorded in `plot_results.json`.

## Safety model

- Never modify the source DXF or DWG.
- Do not kill WPS, PDF viewers, or unrelated AutoCAD processes.
- Do not silently export a model-space-wide cluster when multiple standard sheets are detectable on `图框` layers.
- Use a small AutoCAD sample before a full export, especially for custom fonts, rotated frames, proxy objects, or a new printer/media configuration.

## Limitations

- The diagnostic DXF mirror of a DWG is produced by AutoCAD and is non-destructive, but proxy/custom objects can still need visual checking. Final plotting remains on the original DWG.
- AutoCAD modal dialogs cannot be dismissed safely by the skill; clear them manually and rerun.
- Rotated or deeply nested frames may require a manual frame strategy or sample review.
- A partially missing/ambiguous title-block sequence falls back to geometric ordering and records a warning.

## Repository layout

```text
dxf-batch-pdf-export/
  SKILL.md
  agents/openai.yaml
  scripts/
  references/
  tests/
```

## License

MIT. See `LICENSE`.