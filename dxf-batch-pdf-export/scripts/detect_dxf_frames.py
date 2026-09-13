"""Detect model-space page windows for AutoCAD window plotting.

The automatic order is block frames, colored frames, named frame layers, then
entity clusters. Frame-layer candidates are deliberately preferred over a
cluster fallback because a model-wide cluster can silently combine many sheets.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from dxf_scan_utils import (
    bbox_pad,
    bbox_size,
    bbox_union,
    block_geometry_bbox,
    boxes_touch,
    entity_bbox,
    entity_color,
    entity_layer,
    first,
    parse_float,
    parse_sections,
    sorted_counter_items,
    transform_bbox,
)
from page_ordering import apply_page_number_sort

FRAME_GEOMETRY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "INSERT"}


def parse_color_set(value: str) -> set[int]:
    colors: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            colors.add(int(item))
        except ValueError as exc:
            raise RuntimeError(f"Invalid AutoCAD color index: {item}") from exc
    return colors


def parse_layer_filters(value: str) -> list[str]:
    return [item.strip().casefold() for item in value.split(",") if item.strip()]


def size_matches(width: float, height: float, frame_width: float, frame_height: float, tolerance: float) -> bool:
    return abs(width - frame_width) <= tolerance and abs(height - frame_height) <= tolerance


def approximate_size_matches(width: float, height: float, frame_width: float, frame_height: float, tolerance: float) -> bool:
    return size_matches(width, height, frame_width, frame_height, tolerance) or size_matches(
        width, height, frame_height, frame_width, tolerance
    )


def sort_frames(frames: list[dict], sort_mode: str) -> None:
    if sort_mode == "input":
        return
    if sort_mode == "top-left":
        frames.sort(key=lambda item: (-item["insert"][1], item["insert"][0]))
    elif sort_mode == "bottom-left":
        frames.sort(key=lambda item: (item["insert"][1], item["insert"][0]))
    elif sort_mode == "left-bottom":
        frames.sort(key=lambda item: (item["insert"][0], item["insert"][1]))
    else:
        raise RuntimeError(f"Unsupported sort mode: {sort_mode}")


def frame_from_bbox(bbox, padding: float, page_source: str, source_detail: dict | None = None) -> dict:
    width, height = bbox_size(bbox)
    window = bbox_pad(bbox, abs(width) * padding, abs(height) * padding)
    frame = {
        "insert": [round(bbox[0], 6), round(bbox[1], 6)],
        "window": [round(value, 6) for value in window],
        "rawWindow": [round(value, 6) for value in bbox],
        "source": page_source,
    }
    if source_detail:
        frame["sourceDetail"] = source_detail
    return frame


def dedupe_frames(frames: list[dict], tolerance: float) -> list[dict]:
    kept: list[dict] = []
    for frame in frames:
        raw = frame["rawWindow"]
        if not any(all(abs(raw[index] - other["rawWindow"][index]) <= tolerance for index in range(4)) for other in kept):
            kept.append(frame)
    return kept


def attach_page_numbers(frames: list[dict], sort_mode: str, entities) -> tuple[list[dict], dict, list[str]]:
    sort_frames(frames, sort_mode)
    frames, page_order, warnings = apply_page_number_sort(frames, entities)
    for index, frame in enumerate(frames, start=1):
        frame["page"] = index
    return frames, page_order, warnings


def find_block_candidates(args, entities, blocks) -> list[dict]:
    insert_counts = Counter(first(entity, "2") for entity_type, entity in entities if entity_type == "INSERT")
    candidates = []
    names = [args.frame_block] if args.frame_block else [name for name, _ in insert_counts.most_common()]
    for name in names:
        if not name or name not in blocks or insert_counts.get(name, 0) < args.min_count:
            continue
        try:
            bbox = block_geometry_bbox(blocks[name])
        except RuntimeError:
            continue
        width, height = bbox_size(bbox)
        if approximate_size_matches(width, height, args.frame_width, args.frame_height, args.tolerance):
            candidates.append({"name": name, "insertCount": insert_counts[name], "bbox": bbox, "size": [width, height]})
    return candidates


def frames_from_block_candidate(args, entities, candidate: dict) -> tuple[list[dict], list[str]]:
    frames = []
    warnings = []
    name = candidate["name"]
    for entity_type, entity in entities:
        if entity_type != "INSERT" or first(entity, "2") != name:
            continue
        x = parse_float(first(entity, "10", "0"), 0.0) or 0.0
        y = parse_float(first(entity, "20", "0"), 0.0) or 0.0
        sx = parse_float(first(entity, "41", "1"), 1.0) or 1.0
        sy = parse_float(first(entity, "42", "1"), 1.0) or 1.0
        rotation = parse_float(first(entity, "50", "0"), 0.0) or 0.0
        if abs(rotation) > 1e-6:
            warnings.append(f"Frame block {name} has rotated INSERT at ({x}, {y}); window uses axis-aligned bounds.")
        bbox = transform_bbox(candidate["bbox"], x, y, sx, sy, rotation)
        frames.append(
            frame_from_bbox(
                bbox,
                args.padding,
                "block",
                {"blockName": name, "scale": [round(sx, 6), round(sy, 6)], "rotation": round(rotation, 6)},
            )
        )
    return dedupe_frames(frames, args.tolerance), warnings


def connected_components(records: list[dict], gap: float) -> list[list[dict]]:
    components: list[list[dict]] = []
    bounds = []
    for record in records:
        attached = []
        for index, component_bbox in enumerate(bounds):
            if component_bbox is not None and boxes_touch(component_bbox, record["bbox"], gap):
                attached.append(index)
        if not attached:
            components.append([record])
            bounds.append(record["bbox"])
            continue
        first_index = attached[0]
        components[first_index].append(record)
        bounds[first_index] = bbox_union([bounds[first_index], record["bbox"]])
        for index in reversed(attached[1:]):
            components[first_index].extend(components.pop(index))
            bounds[first_index] = bbox_union([bounds[first_index], bounds.pop(index)])
    return components


def build_frame_candidates(args, records: list[dict], gap: float, direct_match: str, component_match: str) -> list[dict]:
    direct = []
    for record in records:
        width, height = bbox_size(record["bbox"])
        if approximate_size_matches(width, height, args.frame_width, args.frame_height, args.tolerance):
            direct.append({"bbox": record["bbox"], "entityCount": 1, "match": direct_match, "records": [record]})
    grouped = []
    for component in connected_components(records, gap):
        bbox = bbox_union([record["bbox"] for record in component])
        if bbox is None:
            continue
        width, height = bbox_size(bbox)
        if approximate_size_matches(width, height, args.frame_width, args.frame_height, args.tolerance):
            grouped.append({"bbox": bbox, "entityCount": len(component), "match": component_match, "records": component})
    candidates = []
    for item in direct + grouped:
        colors = Counter(str(record.get("color")) for record in item["records"])
        layers = Counter(record.get("layer", "") for record in item["records"])
        candidates.append(
            {
                "bbox": item["bbox"],
                "entityCount": item["entityCount"],
                "match": item["match"],
                "topColors": sorted_counter_items(colors, 5),
                "topLayers": sorted_counter_items(layers, 8),
            }
        )
    return candidates


def find_color_frame_candidates(args, entities, blocks) -> list[dict]:
    colors = parse_color_set(args.frame_color)
    layer_filters = parse_layer_filters(args.frame_layer)
    if not colors and not layer_filters:
        return []
    records = []
    for index, (entity_type, entity) in enumerate(entities):
        if entity_type not in FRAME_GEOMETRY_TYPES:
            continue
        layer = entity_layer(entity)
        color = entity_color(entity)
        if not ((colors and color in colors) or (layer_filters and any(token in layer.casefold() for token in layer_filters))):
            continue
        bbox = entity_bbox(entity_type, entity, blocks=blocks)
        if bbox is None:
            continue
        width, height = bbox_size(bbox)
        if width <= 0 and height <= 0:
            continue
        records.append({"index": index, "type": entity_type, "layer": layer, "color": color, "bbox": bbox})
    return build_frame_candidates(args, records, args.color_cluster_gap, "single-colored-entity", "colored-component")


def find_named_layer_frame_candidates(args, entities, blocks) -> list[dict]:
    token = args.frame_layer_token.casefold().strip()
    if not token:
        return []
    records = []
    for index, (entity_type, entity) in enumerate(entities):
        if entity_type not in FRAME_GEOMETRY_TYPES:
            continue
        layer = entity_layer(entity)
        if token not in layer.casefold():
            continue
        bbox = entity_bbox(entity_type, entity, blocks=blocks)
        if bbox is None:
            continue
        width, height = bbox_size(bbox)
        if width <= 0 and height <= 0:
            continue
        records.append(
            {"index": index, "type": entity_type, "layer": layer, "color": entity_color(entity), "bbox": bbox}
        )
    return build_frame_candidates(args, records, args.color_cluster_gap, "single-frame-layer-entity", "frame-layer-component")


def frames_from_geometry_candidates(args, candidates: list[dict], source: str) -> list[dict]:
    frames = [
        frame_from_bbox(
            candidate["bbox"],
            args.padding,
            source,
            {"match": candidate["match"], "entityCount": candidate["entityCount"], "topLayers": candidate["topLayers"], "topColors": candidate["topColors"]},
        )
        for candidate in candidates
    ]
    return dedupe_frames(frames, args.tolerance)


def find_entity_cluster_candidates(args, entities, blocks) -> list[dict]:
    records = []
    for index, (entity_type, entity) in enumerate(entities):
        if entity_type in {"POINT", "VERTEX"}:
            continue
        bbox = entity_bbox(entity_type, entity, blocks=blocks)
        if bbox is None:
            continue
        width, height = bbox_size(bbox)
        if width < args.min_entity_size and height < args.min_entity_size:
            continue
        records.append({"index": index, "type": entity_type, "layer": entity_layer(entity), "bbox": bbox})

    candidates = []
    min_width = args.min_cluster_width or args.frame_width * 0.45
    min_height = args.min_cluster_height or args.frame_height * 0.45
    for component in connected_components(records, args.cluster_gap):
        if len(component) < args.min_cluster_entities:
            continue
        bbox = bbox_union([record["bbox"] for record in component])
        if bbox is None:
            continue
        width, height = bbox_size(bbox)
        if width < min_width or height < min_height:
            continue
        candidates.append(
            {
                "bbox": bbox,
                "entityCount": len(component),
                "size": [width, height],
                "topLayers": sorted_counter_items(Counter(record["layer"] for record in component), 8),
                "topTypes": sorted_counter_items(Counter(record["type"] for record in component), 8),
            }
        )
    return candidates


def frames_from_cluster_candidates(args, candidates: list[dict]) -> list[dict]:
    frames = [
        frame_from_bbox(
            candidate["bbox"],
            args.padding,
            "cluster",
            {"entityCount": candidate["entityCount"], "topLayers": candidate["topLayers"], "topTypes": candidate["topTypes"]},
        )
        for candidate in candidates
    ]
    return dedupe_frames(frames, args.tolerance)


def summarize_block_candidates(candidates: list[dict]) -> list[dict]:
    return [
        {"name": item["name"], "insertCount": item["insertCount"], "size": [round(item["size"][0], 6), round(item["size"][1], 6)]}
        for item in candidates[:20]
    ]


def summarize_bbox_candidates(candidates: list[dict], limit: int = 20) -> list[dict]:
    result = []
    for item in candidates[:limit]:
        width, height = bbox_size(item["bbox"])
        summary = {key: value for key, value in item.items() if key != "bbox"}
        summary["bbox"] = [round(value, 6) for value in item["bbox"]]
        summary["size"] = [round(width, 6), round(height, 6)]
        result.append(summary)
    return result


def raw_bbox_union(frames: list[dict]):
    return bbox_union([tuple(frame["rawWindow"]) for frame in frames]) if frames else None


def covers(outer, inner, tolerance: float) -> bool:
    return outer is not None and inner is not None and all(
        (outer[0] <= inner[0] + tolerance, outer[1] <= inner[1] + tolerance, outer[2] >= inner[2] - tolerance, outer[3] >= inner[3] - tolerance)
    )


def choose_frames(args, entities, blocks):
    warnings: list[str] = []
    block_candidates = find_block_candidates(args, entities, blocks)
    block_frames: list[dict] = []
    block_warnings: list[str] = []
    if block_candidates:
        block_frames, block_warnings = frames_from_block_candidate(args, entities, block_candidates[0])
    color_candidates = find_color_frame_candidates(args, entities, blocks)
    color_frames = frames_from_geometry_candidates(args, color_candidates, "color")
    layer_candidates = find_named_layer_frame_candidates(args, entities, blocks)
    layer_frames = frames_from_geometry_candidates(args, layer_candidates, "layer")
    cluster_candidates = find_entity_cluster_candidates(args, entities, blocks)
    cluster_frames = frames_from_cluster_candidates(args, cluster_candidates)

    counts = {"block": len(block_frames), "color": len(color_frames), "layer": len(layer_frames), "cluster": len(cluster_frames)}
    conflicts = []
    reliable_counts = {key: value for key, value in counts.items() if key in {"block", "color", "layer"} and value}
    if len(set(reliable_counts.values())) > 1:
        conflicts.append({"type": "candidate-count-mismatch", "counts": reliable_counts})
    diagnostics = {
        "blockCandidates": summarize_block_candidates(block_candidates),
        "colorCandidates": summarize_bbox_candidates(color_candidates),
        "layerCandidates": summarize_bbox_candidates(layer_candidates),
        "clusterCandidates": summarize_bbox_candidates(cluster_candidates),
        "candidateFrameCounts": counts,
        "frameLayerToken": args.frame_layer_token,
        "conflicts": conflicts,
    }

    if args.frame_block and not block_candidates:
        raise RuntimeError(f"Requested frame block was not found or did not match page size: {args.frame_block}")
    available = {"block": block_frames, "color": color_frames, "layer": layer_frames, "cluster": cluster_frames}
    selected = ""
    if args.strategy == "auto":
        for strategy in ("block", "color", "layer", "cluster"):
            if available[strategy]:
                selected = strategy
                break
    elif available.get(args.strategy):
        selected = args.strategy
    if not selected:
        raise RuntimeError(
            "Could not detect drawing frames with block, color, named-frame-layer, or entity-cluster strategies. "
            f"Diagnostics: {json.dumps(diagnostics, ensure_ascii=False)}"
        )

    selected_frames = available[selected]
    if selected == "cluster" and len(selected_frames) == 1:
        # A fallback cluster has no independent sheet evidence, regardless of layer names.
        message = (
            "Cluster detection produced a single unverified window that may combine multiple sheets. "
            "Specify --frame-layer FRAME,BORDER,TK (or the actual layer), use verified frames, "
            "or pass --allow-suspicious-cluster only after manual confirmation. "
            f"Candidate counts: {counts}."
        )
        diagnostics["conflicts"].append({"type": "unverified-single-cluster", "clusterFrames": 1, "layerFrames": len(layer_frames)})
        if not args.allow_suspicious_cluster:
            raise RuntimeError(message)
        warnings.append(message)

    if selected == "block":
        warnings.extend(block_warnings)
    frames, page_order, order_warnings = attach_page_numbers(selected_frames, args.sort, entities)
    warnings.extend(order_warnings)
    diagnostics["selection"] = {"strategy": selected, "sort": args.sort, "pageOrder": page_order}
    return frames, selected, block_candidates[0] if selected == "block" else None, diagnostics, warnings, page_order


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect model-space drawing frames in a DXF file.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frame-width", type=float, default=841.0)
    parser.add_argument("--frame-height", type=float, default=594.0)
    parser.add_argument("--tolerance", type=float, default=5.0)
    parser.add_argument("--padding", type=float, default=0.01)
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--frame-block", default="")
    parser.add_argument("--strategy", choices=["auto", "block", "color", "layer", "cluster"], default="auto")
    parser.add_argument("--frame-color", default="6")
    parser.add_argument("--frame-layer", default="")
    parser.add_argument("--frame-layer-token", default="图框")
    parser.add_argument("--color-cluster-gap", type=float, default=2.0)
    parser.add_argument("--cluster-gap", type=float, default=30.0)
    parser.add_argument("--min-cluster-entities", type=int, default=20)
    parser.add_argument("--min-cluster-width", type=float, default=0.0)
    parser.add_argument("--min-cluster-height", type=float, default=0.0)
    parser.add_argument("--min-entity-size", type=float, default=0.0)
    parser.add_argument("--allow-suspicious-cluster", action="store_true")
    parser.add_argument("--sort", choices=["top-left", "bottom-left", "left-bottom", "input"], default="top-left")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input DXF not found: {args.input}")
    entities, blocks, tables, encoding = parse_sections(args.input)
    frames, strategy, block_candidate, diagnostics, warnings, page_order = choose_frames(args, entities, blocks)
    block_size = None
    block_name = None
    if block_candidate:
        block_name = block_candidate["name"]
        block_size = [round(block_candidate["size"][0], 6), round(block_candidate["size"][1], 6)]
    result = {
        "input": str(args.input.resolve()),
        "encoding": encoding,
        "detectionStrategy": strategy,
        "frameBlockName": block_name,
        "frameBlockSize": block_size,
        "frameSizeTarget": [args.frame_width, args.frame_height],
        "tolerance": args.tolerance,
        "paddingFraction": args.padding,
        "sort": args.sort,
        "pageOrder": page_order,
        "pageCount": len(frames),
        "warnings": warnings,
        "diagnostics": diagnostics,
        "frames": frames,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"detectionStrategy": strategy, "frameBlockName": block_name, "pageCount": len(frames), "pageOrder": page_order["method"], "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
