# Troubleshooting

## PowerShell refuses to run a script

Run this workflow with a process-local policy override:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\dxf-batch-pdf-export\scripts\convert_dxf_to_pdf_set.ps1 ...
```

This changes neither the machine-wide nor user-wide execution policy.

## `0x80010001`, `RPC_E_CALL_REJECTED`, or `RPC_E_SERVERCALL_RETRYLATER`

The updated scripts treat these as temporary AutoCAD busy states. They use bounded retry, exponential backoff, and `AcadState.IsQuiescent` where the installed AutoCAD version exposes it. Inspect `plot_results.json.comEvents` or the DWG conversion result for the operation, attempts, and final timeout.

If the timeout remains:

- Clear AutoCAD modal dialogs, licensing dialogs, unresolved reference prompts, and open commands.
- Run the default isolated mode rather than `-ReuseExistingAutoCAD 1`.
- Increase `-ComTimeoutSeconds` for unusually large drawings.
- Pass a known registered ProgID, for example `-AutoCadProgId 'AutoCAD.Application.24'`.

The retry layer deliberately does not retry arbitrary errors such as invalid paths, unsupported plot devices, or access denied failures.

## AutoCAD version is not `.25`

Do not rely on a hard-coded version. Omit `-AutoCadProgId` to select the highest registered `AutoCAD.Application.*` ProgID, or pass the specific installed version. The selected ProgID and the AutoCAD-reported version appear in `plot_results.json.autoCad`.

## A user AutoCAD session must remain untouched

Leave `-ReuseExistingAutoCAD` at its default `0`. The workflow starts and later quits only its own hidden instance. Reuse is explicit because a busy user session can still delay the opened conversion document. The cleanup helper no longer quits any active AutoCAD instance by default.

## DWG input has no preflight report or no frames

DWG detection is DXF-based. The controller creates `input_mirror\*_diagnostic.dxf` under `WorkDir`, records the relationship in `input_route.json`, preflights that mirror, and plots the original DWG. The DWG is never modified.

If AutoCAD saves a non-text DXF mirror, rerun with `-DxfSaveAsFormat` set to a DXF `AcSaveAsType` supported by the installed AutoCAD release. Verify the mirror with `analyze_dxf_features.py` before plotting.

## Frame detection fails or yields one model-wide window

- Prefer a known frame block with `-FrameBlock` when available.
- Set `-FrameLayerToken '图框'` (or the project's equivalent) to identify repeated standard-size A1 geometry on frame layers.
- Use `-DetectionStrategy layer` to inspect those candidates directly.
- Check `frames.json.diagnostics.candidateFrameCounts`, `layerCandidates`, and `conflicts`.
- A single `cluster` window that covers several detected standard frame-layer sheets is blocked by default. Do not bypass it with `-AllowSuspiciousCluster 1` until a sample plot has been reviewed.
- Rotated frame INSERTs still need manual checking because AutoCAD window plots are axis-aligned.

## Page order is wrong

`frames.json.pageOrder.method` is `title-block-page-number` only when every detected frame contains a single consistent sequence matching `第1张 共N张` through `第N张 共N张`. Otherwise the workflow uses the requested geometric sort and adds a warning. Inspect each frame's `pageNumberEvidence`; correct title-block text or set `-Sort` deliberately.

## Output is not centered, lacks color, or does not fill the page

- Verify each `window` in `frames.json` and reduce/increase `-Padding` only after a sample.
- Confirm the selected device/media in `plot_results.json.pages`.
- Keep `DWG To PDF.pc3`, ensure the A1 media matches the detected orientation, and inspect rendered samples plus `contentMarginFractions`.
- Missing SHX/TTF files remain an AutoCAD environment issue; AutoCAD can substitute fonts even though the skill uses native plotting.

## WPS or another viewer opens repeatedly

Keep `-IntermediateExtension .codexplot`. The script renames completed files to PDF and only minimizes/closes windows whose title matches the generated page filename. It never terminates WPS or another viewer process.

## Verification cannot render samples

Install Poppler or provide `--pdftoppm`. `pypdf` can still check pages and media boxes, but rendered images are necessary for claims about centering, blank pages, and color.