# Troubleshooting

## Frame detection fails

- Confirm the DXF contains model-space frame blocks, not only paper-space layouts.
- Pass `--frame-block` if the frame block is known.
- Increase `--tolerance` if the frame is slightly larger than the nominal paper size.
- Set `--min-count 1` for single-sheet drawings and a higher value for repeated PFD/P&ID frames.
- Rotated frame INSERTs are rejected by the detector; use AutoCAD layout plotting or add rotated-window handling before full conversion.

## Output is not centered or does not fill the page

- Re-check the detected `window` values in `frames.json`.
- Lower `--padding` for a fuller page or increase it if title blocks are clipped.
- Verify that `MediaName` matches the detected frame orientation and that `PlotRotation` is correct.

## WPS or another viewer opens repeatedly

- Keep `-IntermediateExtension .codexplot`; the final `.pdf` rename should not trigger per-page viewer launches.
- If popups persist, inspect `plot_results.json` for `suppressedViewerWindows`. Close only generated-page title matches; do not terminate unrelated WPS processes.

## AutoCAD COM errors

- Use escalation because AutoCAD is a GUI COM server.
- If `GetActiveObject` fails, the script starts AutoCAD with `New-Object -ComObject`.
- If the installed version is different, pass `-AutoCadProgId` such as `AutoCAD.Application.24`.
- If a previous AutoCAD instance is busy, close modal dialogs manually or retry after AutoCAD is idle.

## Unicode paths or garbled text

- Run commands from a stable ASCII working directory such as `C:\Users\<user>`.
- Pass paths with `-LiteralPath` where possible.
- Keep JSON files UTF-8. The scripts reconfigure Python stdout/stderr to UTF-8 when available.

## Verification cannot render samples

- Ensure Poppler `pdftoppm.exe` is available on PATH or pass `--pdftoppm`.
- Page-count checks still work through `pypdf`; rendered samples are needed for visual QA claims.
## Block, color, and cluster candidates disagree

- Prefer block candidates when they match expected page size and count.
- Use color candidates when the drawing frame is drawn with a consistent color or layer instead of an INSERT block.
- Use cluster candidates only as a fallback and always run `-MaxPages 1` or `-MaxPages 3` before full export.
- Compare `preflight_report.json` and `frames.json` to see which strategy was selected.

## Text or dimension risk is reported

- Keep AutoCAD plotting as the final renderer; do not switch to lightweight DXF rendering for fidelity-critical output.
- Verify rendered samples when `\U+`, `\M+`, or `%%` text escapes appear.
- If DIMENSION entities near origin are reported, inspect samples for displaced dimensions.
- Create a repaired DXF copy only after explicit user approval.
