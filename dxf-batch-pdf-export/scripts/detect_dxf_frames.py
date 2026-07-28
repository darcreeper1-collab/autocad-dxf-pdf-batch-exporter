"""Detect model-space page windows for AutoCAD window plotting.
The strategy order is block frames, color frames, then entity clusters as a fallback."""

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


def parse_color_set(value: str) -> set[int]:
    colors: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            colors.add(int(item))
        except ValueError:
            raise RuntimeError(f"Invalid AutoCAD color index: {item}")
    return colors


def parse_layer_filters(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def size_matches(width: float, height: float, frame_width: float, frame_height: float, tolerance: float) -> bool:
    return abs(width - frame_width) <= tolerance and abs(height - frame_height) <= tolerance


def approximate_size_matches(width: float, height: float, frame_width: float, frame_height: float, tolerance: float) -> bool:
    if size_matches(width, height, frame_width, frame_height, tolerance):
        return True
    return size_matches(width, height, frame_height, frame_width, tolerance)


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
    pad_x = abs(width) * padding
    pad_y = abs(height) * padding
    window = bbox_pad(bbox, pad_x, pad_y)
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
        duplicate = False
        for existing in kept:
            other = existing["rawWindow"]
            if all(abs(raw[index] - other[index]) <= tolerance for index in range(4)):
                duplicate = True
                break
        if not duplicate:
            kept.append(frame)
    return kept


def attach_page_numbers(frames: list[dict], sort_mode: str) -> list[dict]:
    sort_frames(frames, sort_mode)
    for index, frame in enumerate(frames, start=1):
        frame["page"] = index
    return frames


def find_block_candidates(args, entities, blocks) -> list[dict]:
    insert_counts = Counter(first(entity, "2") for entity_type, entity in entities if entity_type == "INSERT")
    candidates = []
    names = [args.frame_block] if args.frame_block else [name for name, _ in insert_counts.most_common()]
    for name in names:
        if not name:
            continue
        if name not in blocks:
            continue
        count = insert_counts.get(name, 0)
        if count < args.min_count:
            continue
        try:
            bbox = block_geometry_bbox(blocks[name])
        except RuntimeError:
            continue
        width, height = bbox_size(bbox)
        if approximate_size_matches(width, height, args.frame_width, args.frame_height, args.tolerance):
            candidates.append({"name": name, "insertCount": count, "bbox": bbox, "size": [width, height]})
    return candidates


def frames_from_block_candidate(args, entities, candidate: dict) -> tuple[list[dict], list[str]]:
    frames = []
    warnings = []
    name = candidate["name"]
    bx0, by0, bx1, by1 = candidate["bbox"]
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
        bbox = transform_bbox((bx0, by0, bx1, by1), x, y, sx, sy, rotation)
        frames.append(
            frame_from_bbox(
                bbox,
                args.padding,
                "block",
                {"blockName": name, "scale": [round(sx, 6), round(sy, 6)], "rotation": round(rotation, 6)},
            )
        )
    return frames, warnings


def entity_matches_filter(entity, colors: set[int], layer_filters: list[str]) -> bool:
    color = entity_color(entity)
    layer = entity_layer(entity).lower()
    color_match = bool(colors) and color in colors
    layer_match = bool(layer_filters) and any(token in layer for token in layer_filters)
    return color_match or layer_match


def connected_components(records: list[dict], gap: float) -> list[list[dict]]:
    components: list[list[dict]] = []
    for record in records:
        attached = []
        for index, component in enumerate(components):
            component_bbox = bbox_union([item["bbox"] for item in component])
            if component_bbox is not None and boxes_touch(component_bbox, record["bbox"], gap):
                attached.append(index)
        if not attached:
            components.append([record])
            continue
        first_index = attached[0]
        components[first_index].append(record)
        for index in reversed(attached[1:]):
            components[first_index].extend(components.pop(index))
    return components


def find_color_frame_candidates(args, entities, blocks) -> list[dict]:
    colors = parse_color_set(args.frame_color)
    layer_filters = parse_layer_filters(args.frame_layer)
    if not colors and not layer_filters:
        return []
    records = []
    for index, (entity_type, entity) in enumerate(entities):
        if entity_type not in {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "INSERT"}:
            continue
        if not entity_matches_filter(entity, colors, layer_filters):
            continue
        bbox = entity_bbox(entity_type, entity, blocks=blocks)
        if bbox is None:
            continue
        width, height = bbox_size(bbox)
        if width <= 0 and height <= 0:
            continue
        records.append({"index": index, "type": entity_type, "layer": entity_layer(entity), "color": entity_color(entity), "bbox": bbox})

    direct = []
    for record in records:
        width, height = bbox_size(record["bbox"])
        if approximate_size_matches(width, height, args.frame_width, args.frame_height, args.tolerance):
            direct.append({"bbox": record["bbox"], "entityCount": 1, "match": "single-entity", "records": [record]})

    clustered = []
    for component in connected_components(records, args.color_cluster_gap):
        component_bbox = bbox_union([record["bbox"] for record in component])
        if component_bbox is None:
            continue
        width, height = bbox_size(component_bbox)
        if approximate_size_matches(width, height, args.frame_width, args.frame_height, args.tolerance):
            clustered.append({"bbox": component_bbox, "entityCount": len(component), "match": "colored-component", "records": component})

    candidates = []
    for item in direct + clustered:
        colors_seen = Counter(str(record.get("color")) for record in item["records"])
        layers_seen = Counter(record.get("layer", "") for record in item["records"])
        candidates.append(
            {
                "bbox": item["bbox"],
                "entityCount": item["entityCount"],
                "match": item["match"],
                "topColors": sorted_counter_items(colors_seen, 5),
                "topLayers": sorted_counter_items(layers_seen, 5),
            }
        )
    return candidates


def frames_from_color_candidates(args, candidates: list[dict]) -> list[dict]:
    frames = []
    for candidate in candidates:
        frames.append(
            frame_from_bbox(
                candidate["bbox"],
                args.padding,
                "color",
                {"match": candidate["match"], "entityCount": candidate["entityCount"], "topLayers": candidate["topLayers"], "topColors": candidate["topColors"]},
            )
        )
    return dedupe_frames(frames, args.tolerance)


def find_entity_cluster_candidates(args, entities, blocks) -> list[dict]:
    records = []
    ignored_types = {"POINT", "VERTEX"}
    for index, (entity_type, entity) in enumerate(entities):
        if entity_type in ignored_types:
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
        component_bbox = bbox_union([record["bbox"] for record in component])
        if component_bbox is None:
            continue
        width, height = bbox_size(component_bbox)
        if width < min_width or height < min_height:
            continue
        layers_seen = Counter(record.get("layer", "") for record in component)
        types_seen = Counter(record.get("type", "") for record in component)
        candidates.append(
            {
                "bbox": component_bbox,
                "entityCount": len(component),
                "size": [width, height],
                "topLayers": sorted_counter_items(layers_seen, 8),
                "topTypes": sorted_counter_items(types_seen, 8),
            }
        )
    return candidates


def frames_from_cluster_candidates(args, candidates: list[dict]) -> list[dict]:
    frames = []
    for candidate in candidates:
        frames.append(
            frame_from_bbox(
                candidate["bbox"],
                args.padding,
                "cluster",
                {"entityCount": candidate["entityCount"], "topLayers": candidate["topLayers"], "topTypes": candidate["topTypes"]},
            )
        )
    return dedupe_frames(frames, args.tolerance)


def summarize_block_candidates(candidates: list[dict]) -> list[dict]:
    return [
        {
            "name": item["name"],
            "insertCount": item["insertCount"],
            "size": [round(item["size"][0], 6), round(item["size"][1], 6)],
        }
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


def choose_frames(args, entities, blocks):
    diagnostics = {"blockCandidates": [], "colorCandidates": [], "clusterCandidates": []}
    warnings = []

    block_candidates = find_block_candidates(args, entities, blocks)
    diagnostics["blockCandidates"] = summarize_block_candidates(block_candidates)
    if args.frame_block and not block_candidates:
        raise RuntimeError(f"Requested frame block was not found or did not match page size: {args.frame_block}")
    if args.strategy in {"auto", "block"} and block_candidates:
        frames, block_warnings = frames_from_block_candidate(args, entities, block_candidates[0])
        warnings.extend(block_warnings)
        if frames:
            return attach_page_numbers(frames, args.sort), "block", block_candidates[0], diagnostics, warnings
    if args.strategy == "block":
        raise RuntimeError("Block frame detection failed; try --strategy auto or pass --frame-block/--tolerance.")

    color_candidates = find_color_frame_candidates(args, entities, blocks)
    diagnostics["colorCandidates"] = summarize_bbox_candidates(color_candidates)
    if args.strategy in {"auto", "color"} and color_candidates:
        frames = frames_from_color_candidates(args, color_candidates)
        if frames:
            return attach_page_numbers(frames, args.sort), "color", None, diagnostics, warnings
    if args.strategy == "color":
        raise RuntimeError("Color frame detection failed; adjust --frame-color, --frame-layer, or --tolerance.")

    cluster_candidates = find_entity_cluster_candidates(args, entities, blocks)
    diagnostics["clusterCandidates"] = summarize_bbox_candidates(cluster_candidates)
    if args.strategy in {"auto", "cluster"} and cluster_candidates:
        frames = frames_from_cluster_candidates(args, cluster_candidates)
        if frames:
            return attach_page_numbers(frames, args.sort), "cluster", None, diagnostics, warnings
    if args.strategy == "cluster":
        raise RuntimeError("Entity cluster frame detection failed; adjust --cluster-gap or --min-cluster-entities.")

    raise RuntimeError(
        "Could not detect drawing frames with block, color, or entity-cluster strategies. "
        f"Diagnostics: {json.dumps(diagnostics, ensure_ascii=False)}"
    )


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
    parser.add_argument("--strategy", choices=["auto", "block", "color", "cluster"], default="auto")
    parser.add_argument("--frame-color", default="6")
    parser.add_argument("--frame-layer", default="")
    parser.add_argument("--color-cluster-gap", type=float, default=2.0)
    parser.add_argument("--cluster-gap", type=float, default=30.0)
    parser.add_argument("--min-cluster-entities", type=int, default=20)
    parser.add_argument("--min-cluster-width", type=float, default=0.0)
    parser.add_argument("--min-cluster-height", type=float, default=0.0)
    parser.add_argument("--min-entity-size", type=float, default=0.0)
    parser.add_argument("--sort", choices=["top-left", "bottom-left", "left-bottom", "input"], default="top-left")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input DXF not found: {args.input}")
    entities, blocks, tables, encoding = parse_sections(args.input)
    frames, strategy, block_candidate, diagnostics, warnings = choose_frames(args, entities, blocks)
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
        "pageCount": len(frames),
        "warnings": warnings,
        "diagnostics": diagnostics,
        "frames": frames,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"detectionStrategy": strategy, "frameBlockName": block_name, "pageCount": len(frames), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()