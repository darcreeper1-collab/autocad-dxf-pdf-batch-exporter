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

A single fallback cluster can combine several sheets even when no `图框` layer exists. Every single-cluster fallback now stops for confirmation. Use `--frame-layer FRAME,BORDER,TK` (or the real layer) or an explicit frame block to supply independent frame evidence. `--allow-suspicious-cluster` is an override only for a manually reviewed drawing, including a genuine single sheet. Verified block/color/layer single sheets are unaffected.

Classic `POLYLINE` geometry now collects its subsequent `VERTEX` records through `SEQEND`, excluding the non-geometric header point, in both ENTITIES and BLOCKS. This covers straight 2D frame outlines; bulges and non-world-plane geometry remain sample-review cases. Connected components cache bounds, preserving existing grouping semantics without rescanning every member on insertion; worst-case comparisons across many isolated components remain quadratic.

## Page-order evidence

After frame geometry is selected, the detector searches direct TEXT/MTEXT/ATTRIB/ATTDEF inside each raw frame for `第x张 共x张`. It only changes output order when every frame yields exactly one coherent, complete sequence from `1` through the detected count. `frames.json.pageOrder` records the chosen method, while each successful frame contains `pageNumberEvidence` with the matched text, layer, and coordinate.

Separators also accept comma/Chinese comma, slash/full-width slash, and semicolon with optional spaces. MTEXT paragraph/nonbreaking-space escapes are normalized, and long MTEXT chunks are read before the final text chunk. Conflicting matches within one text entity are rejected, not silently reduced to the first match.

Any missing, duplicate, conflicting, or inconsistent evidence leaves the requested geometric sort intact and adds a warning. This prevents a local annotation from reordering a full PDF set.

## Recommended checks

- Compare `preflight_report.json.frameCandidates` and `frames.json.diagnostics` before a large plot.
- Review `input_route.json` for DWG input and confirm the source DWG is the `plotInput`.
- Start with `-MaxPages 1` after a new device/media/strategy selection.
- Use first/middle/last rendered PDF samples and margin statistics before releasing the full output.
