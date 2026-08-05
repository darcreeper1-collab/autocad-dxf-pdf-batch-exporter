"""Generate a non-destructive DXF preflight report before AutoCAD plotting."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from detect_dxf_frames import (
    find_block_candidates,
    find_color_frame_candidates,
    find_entity_cluster_candidates,
    find_named_layer_frame_candidates,
    summarize_bbox_candidates,
    summarize_block_candidates,
)
from dxf_scan_utils import (
    bbox_size,
    bbox_union,
    decode_cad_text,
    entity_bbox,
    entity_color,
    entity_layer,
    first,
    get_text_value,
    parse_float,
    parse_sections,
    sorted_counter_items,
)

TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}


def limited_example(examples: list[dict], item: dict, limit: int) -> None:
    if len(examples) < limit:
        examples.append(item)


def collect_style_fonts(tables) -> list[dict]:
    styles = []
    for record_type, record in tables.get("STYLE", []):
        if record_type == "STYLE":
            name, font, bigfont = first(record, "2", ""), first(record, "3", ""), first(record, "4", "")
            if name or font or bigfont:
                styles.append({"style": name, "font": font, "bigfont": bigfont})
    return styles


def collect_text_risks(entities, limit: int) -> dict:
    counters, examples, style_counter = Counter(), [], Counter()
    for entity_type, entity in entities:
        if entity_type not in TEXT_TYPES:
            continue
        raw, style = get_text_value(entity), first(entity, "7", "")
        if style:
            style_counter[style] += 1
        decoded, stats = decode_cad_text(raw)
        for key, value in stats.items():
            if value:
                counters[key] += value
        if any(stats.values()):
            limited_example(examples, {"type": entity_type, "layer": entity_layer(entity), "style": style, "raw": raw[:160], "decodedPreview": decoded[:160], "stats": stats}, limit)
    return {"specialCodeCounts": dict(counters), "styleUsage": sorted_counter_items(style_counter, 20), "examples": examples}


def collect_dimension_risks(entities, limit: int) -> dict:
    near_origin, total, examples = 0, 0, []
    for entity_type, entity in entities:
        if entity_type != "DIMENSION":
            continue
        total += 1
        x, y = parse_float(first(entity, "10", ""), 0.0) or 0.0, parse_float(first(entity, "20", ""), 0.0) or 0.0
        if abs(x) < 1e-6 and abs(y) < 1e-6:
            near_origin += 1
            limited_example(examples, {"layer": entity_layer(entity), "point10": [x, y], "text": first(entity, "1", "")}, limit)
    return {"dimensionCount": total, "nearOriginCount": near_origin, "examples": examples}


def collect_entity_summary(entities, blocks) -> dict:
    types, layers, colors, boxes = Counter(), Counter(), Counter(), []
    for entity_type, entity in entities:
        types[entity_type] += 1
        layers[entity_layer(entity)] += 1
        color = entity_color(entity)
        colors[str(color if color is not None else "ByLayer/Unset")] += 1
        bbox = entity_bbox(entity_type, entity, blocks=blocks)
        if bbox is not None:
            boxes.append(bbox)
    model_bbox = bbox_union(boxes)
    model_size = None
    if model_bbox is not None:
        width, height = bbox_size(model_bbox)
        model_bbox, model_size = [round(value, 6) for value in model_bbox], [round(width, 6), round(height, 6)]
    return {"entityTypes": sorted_counter_items(types, 30), "layers": sorted_counter_items(layers, 30), "colors": sorted_counter_items(colors, 30), "modelBBox": model_bbox, "modelSize": model_size}


def build_detection_args(args) -> SimpleNamespace:
    return SimpleNamespace(
        frame_width=args.frame_width, frame_height=args.frame_height, tolerance=args.tolerance, padding=args.padding,
        min_count=args.min_count, frame_block=args.frame_block, frame_color=args.frame_color, frame_layer=args.frame_layer,
        frame_layer_token=args.frame_layer_token, color_cluster_gap=args.color_cluster_gap, cluster_gap=args.cluster_gap,
        min_cluster_entities=args.min_cluster_entities, min_cluster_width=args.min_cluster_width,
        min_cluster_height=args.min_cluster_height, min_entity_size=args.min_entity_size,
        allow_suspicious_cluster=False, sort="top-left", strategy="auto",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight a DXF before AutoCAD-based PDF export.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frame-width", type=float, default=841.0)
    parser.add_argument("--frame-height", type=float, default=594.0)
    parser.add_argument("--tolerance", type=float, default=5.0)
    parser.add_argument("--padding", type=float, default=0.01)
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--frame-block", default="")
    parser.add_argument("--frame-color", default="6")
    parser.add_argument("--frame-layer", default="")
    parser.add_argument("--frame-layer-token", default="图框")
    parser.add_argument("--color-cluster-gap", type=float, default=2.0)
    parser.add_argument("--cluster-gap", type=float, default=30.0)
    parser.add_argument("--min-cluster-entities", type=int, default=20)
    parser.add_argument("--min-cluster-width", type=float, default=0.0)
    parser.add_argument("--min-cluster-height", type=float, default=0.0)
    parser.add_argument("--min-entity-size", type=float, default=0.0)
    parser.add_argument("--example-limit", type=int, default=12)
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit(f"Input DXF not found: {args.input}")

    entities, blocks, tables, encoding = parse_sections(args.input)
    detect_args = build_detection_args(args)
    block = find_block_candidates(detect_args, entities, blocks)
    color = find_color_frame_candidates(detect_args, entities, blocks)
    layer = find_named_layer_frame_candidates(detect_args, entities, blocks)
    cluster = find_entity_cluster_candidates(detect_args, entities, blocks)
    result = {
        "input": str(args.input.resolve()), "encoding": encoding,
        "entitySummary": collect_entity_summary(entities, blocks), "styleFonts": collect_style_fonts(tables),
        "textRisks": collect_text_risks(entities, args.example_limit), "dimensionRisks": collect_dimension_risks(entities, args.example_limit),
        "frameCandidates": {"block": summarize_block_candidates(block), "color": summarize_bbox_candidates(color), "layer": summarize_bbox_candidates(layer), "cluster": summarize_bbox_candidates(cluster)},
        "recommendations": [],
    }
    if not block and color:
        result["recommendations"].append("Block-frame detection may fail; color-frame detection has candidates.")
    if not block and not color and layer:
        result["recommendations"].append("Standard-sized candidates were found on layers containing the frame token; automatic detection will prefer them over clusters.")
    if not block and not color and not layer and cluster:
        result["recommendations"].append("Use entity-cluster detection only as a last-resort page-window proposal and verify with AutoCAD samples.")
    if result["textRisks"]["specialCodeCounts"]:
        result["recommendations"].append("Text contains CAD escape codes; prefer AutoCAD plotting and verify rendered samples.")
    if result["dimensionRisks"]["nearOriginCount"]:
        result["recommendations"].append("Some DIMENSION entities have definition points near origin; inspect rendered samples for displaced dimensions.")
    if not result["styleFonts"]:
        result["recommendations"].append("No STYLE font table was parsed; rely on AutoCAD sample plotting to confirm font substitution behavior.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "encoding": encoding, "recommendations": len(result["recommendations"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()