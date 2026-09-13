# AutoCAD DXF PDF Batch Exporter

A Codex skill for high-fidelity, one-drawing-per-page PDF export from model-space DXF and DWG files on Windows. AutoCAD performs the final plot, preserving native colors, SHX/TTF fonts, line types, text positioning, dimensions, and block display better than lightweight DXF renderers.

中文简介：本项目通过 AutoCAD 原生 `PlotToFile` 批量输出 PDF。它对图框进行预检、识别和排序，并在输出后校验页数、页面尺寸、颜色、居中与铺满程度。源 DXF/DWG 始终保持不变。

## What it does

- Plots one model-space drawing frame per PDF page with `DWG To PDF.pc3`.
- Detects frames in this order: repeated frame blocks, colored geometry, standard-size geometry on layers containing `图框`, then entity clusters.
- Requires confirmation for any single fallback cluster, including drawings on unknown `FRAME/BORDER/TK` layers.
- Supports classic `POLYLINE`/`VERTEX` frames in model space and blocks, as well as `LWPOLYLINE`.
- Reads title-block text such as `第3张 共8张`, `第3张，共8张`, or `第 3 张 / 共 8 张`; reorders only a consistent complete `1..N / N` sequence.
- Fails on rejected or mismatched critical plot settings instead of silently using drawing defaults.
- Supervises blocking AutoCAD calls in a separate hidden PowerShell process with a finite no-progress timeout and recovery logs.
- Uses a `.codexplot` temporary extension before renaming output to PDF, reducing WPS/default-viewer popups without terminating unrelated applications.
- Makes a temporary AutoCAD-exported DXF mirror for DWG preflight and frame detection; it plots the original DWG for final fidelity.
- Records `input_route.json`, `preflight_report.json`, `frames.json`, `plot_results.json`, and verification reports in the work directory.

## Regression tests

Issue #2 fix: successful DWG mirror conversion no longer fails because of a null or stale native exit code. The regression suite runs the actual controller with mocked AutoCAD boundaries and real DXF preflight/detection; it does not validate real AutoCAD plotting.

The additional Issue #2 regressions cover strict plot settings, single-cluster rejection, classic polylines, page punctuation/conflicts, cached clustering, pixel-statistics equivalence, bounded Poppler discovery, and actual subprocess watchdog behavior (success, failure, hang, progress). These are simulated tests, not proof of real AutoCAD fidelity.

Run the tests on Windows with Python and the packages from `requirements.txt` available:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_simulated_tests.ps1 -PythonExe python
```

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

The workflow creates a new AutoCAD instance, records its window/process identity before hiding it, waits for `AcadState.IsQuiescent` when available, and retries only temporary COM-busy errors. Normal completion and caught errors attempt document close without saving and owned-instance quit in `finally`. `autoCad.cleanupFailed` and `comEvents` report cleanup failures rather than claiming the instance necessarily closed.

Both standalone AutoCAD scripts and the controller use a supervised worker. `-ComTimeoutSeconds 120` bounds busy retries; `-ComCallTimeoutSeconds 300` bounds a period without a new COM operation, including a non-returning call, startup, or cleanup. Long batches may exceed 300 seconds in total while making progress. Set the latter above expected single-call/file-wait durations, not just the retry budget.

On a watchdog timeout only the owned PowerShell worker is stopped. The supervisor requests visibility for an owned AutoCAD window only after matching its HWND, PID, and process start time. It never kills AutoCAD or alters a reused instance. Inspect the retained `.acad-worker/<run-id>/` logs beneath the plot output or DWG mirror directory. A blocked COM activation before window identification cannot be recovered automatically; inspect AutoCAD manually before retrying. Forced worker termination cannot guarantee AutoCAD `finally` cleanup.

Reuse is opt-in:

```powershell
-ReuseExistingAutoCAD 1 -AutoCadProgId 'AutoCAD.Application.24'
```

When reuse is selected, the workflow does not hide, quit, or alter the existing application instance; it only opens and later closes its own conversion document. Modal dialogs, license prompts, unsaved-document prompts, and long-running commands in that user session can still block automation.

`-AutoCadProgId` is optional. When omitted, the scripts inspect registered `AutoCAD.Application.*` ProgIDs and choose the highest discovered version. The actual selected ProgID and reported AutoCAD version are recorded in `plot_results.json`.

## Safety model

- Never modify the source DXF or DWG.
- Do not kill WPS, PDF viewers, or unrelated AutoCAD processes.
- Do not silently accept a single unverified fallback cluster, regardless of the layer names. Even a genuine one-sheet cluster requires explicit confirmation; verified block/color/layer single sheets are unaffected.
- Use a small AutoCAD sample before a full export, especially for custom fonts, rotated frames, proxy objects, or a new printer/media configuration.

## Limitations

- The diagnostic DXF mirror of a DWG is produced by AutoCAD and is non-destructive, but proxy/custom objects can still need visual checking. Final plotting remains on the original DWG.
- AutoCAD modal dialogs are not dismissed automatically. A watchdog prevents indefinite waiting and attempts to expose an identified owned window; manual dialog handling and residual-instance cleanup may still be necessary.
- Classic straight 2D polyline frame extents are supported. Curved/bulged, non-world-plane, mesh, or proxy geometry is not a CAD geometry-kernel substitute and still needs sample review.
- Rotated or deeply nested frames may require a manual frame strategy or sample review.
- A partially missing/ambiguous title-block sequence falls back to geometric ordering and records a warning.

## Large-drawing verification

Clustering caches component bounds instead of rescanning their members on every insertion. This removes repeated work for growing components, but many disconnected components still have quadratic worst-case comparisons. PDF image checks use Pillow channel masks/histograms with the same pixel thresholds, without adding NumPy.

Poppler lookup checks an explicit `--pdftoppm` file first, then PATH, then a bounded set of known locations under at most three Python parent directories. It never recursively scans a user profile or disk. For the controller, put Poppler on PATH; the standalone `verify_pdf_pages.py` also accepts `--pdftoppm`.

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
