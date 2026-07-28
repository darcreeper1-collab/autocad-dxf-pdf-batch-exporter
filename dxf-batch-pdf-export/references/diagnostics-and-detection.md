# Diagnostics And Detection

Use diagnostics to strengthen AutoCAD-based plotting without replacing AutoCAD as the renderer.

## Preflight report

Run `scripts/analyze_dxf_features.py` before full export or rely on `convert_dxf_to_pdf_set.ps1 -RunPreflight 1`. The report records:

- DXF text encoding used by the parser.
- Entity type, layer, and color distributions.
- STYLE table fonts and bigfonts when present.
- CAD text escape risks such as `\U+XXXX`, `\M+...`, and `%%c/%%d/%%p`.
- DIMENSION entities with definition points near origin.
- Block, color, and entity-cluster frame candidates.

Treat preflight as diagnostic. Do not change the source DXF by default.

## Frame detection hierarchy

`--strategy auto` means:

1. Block frames: repeated INSERT entities whose block extents match the requested paper size. This is preferred.
2. Color frames: entities matching `--frame-color` or `--frame-layer`, grouped into page-sized rectangles.
3. Entity clusters: connected geometry regions large enough to be plausible page windows. This is only a fallback proposal.

Use exact strategies for debugging: `--strategy block`, `--strategy color`, or `--strategy cluster`.

## Recommended checks

- Compare `preflight_report.json.frameCandidates.block` with `frames.json.diagnostics.blockCandidates` when page count is unexpected.
- If block and color candidates disagree, plot `-MaxPages 1` before full export.
- If cluster detection is used, inspect first/middle/last rendered pages and check content margins.
- If text risks appear, keep AutoCAD plotting and verify rendered samples; only generate a repaired DXF copy after explicit approval.