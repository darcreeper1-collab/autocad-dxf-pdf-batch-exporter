# Diagnostics And Detection

## Preflight and DWG routing

`convert_dxf_to_pdf_set.ps1` writes `input_route.json` before detection. For DXF, the source is used directly. For DWG, AutoCAD exports a temporary diagnostic DXF mirror under `WorkDir`; the source DWG remains unchanged and is still used for the final AutoCAD plot. The mirror is not a replacement drawing and may need a visual check for proxy/custom objects.

`preflight_report.json` records encoding, entity/layer/color distributions, STYLE fonts, CAD text escapes, DIMENSION risks, and block/color/layer/cluster frame candidates.

## Automatic frame hierarchy

`--strategy auto` selects the first viable source in this order:

1. Repeated INSERT blocks matching the requested page size.
2. Colored frame geometry or an explicitly requested `--frame-layer` filter.
3. Standard-size geometry on layer names containing `--frame-layer-token` (default `图框`).
4. Entity clusters, only as a final proposal.

`frames.json.diagnostics` reports all candidate sets, their converted frame counts, source layers, and count mismatches. It is normal for low-level candidates to disagree; the selection hierarchy is designed to prefer the more explicit drawing semantics.

## Cluster safeguard

A single cluster can cover the full model space even when it contains several drawing sheets. When that one cluster covers multiple standard-sized candidates found on `图框` layers, the detector fails with a readable message instead of silently exporting one oversized page. Use `--strategy layer` to inspect the pages. `--allow-suspicious-cluster` is an explicit override for a manually reviewed exceptional drawing.

## Page-order evidence

After frame geometry is selected, the detector searches direct TEXT/MTEXT/ATTRIB/ATTDEF inside each raw frame for `第x张 共x张`. It only changes output order when every frame yields exactly one coherent, complete sequence from `1` through the detected count. `frames.json.pageOrder` records the chosen method, while each successful frame contains `pageNumberEvidence` with the matched text, layer, and coordinate.

Any missing, duplicate, conflicting, or inconsistent evidence leaves the requested geometric sort intact and adds a warning. This prevents a local annotation from reordering a full PDF set.

## Recommended checks

- Compare `preflight_report.json.frameCandidates` and `frames.json.diagnostics` before a large plot.
- Review `input_route.json` for DWG input and confirm the source DWG is the `plotInput`.
- Start with `-MaxPages 1` after a new device/media/strategy selection.
- Use first/middle/last rendered PDF samples and margin statistics before releasing the full output.