"""Shared DXF parsing helpers used for diagnostics and page-window detection.
The final PDF rendering path intentionally remains AutoCAD-native for fidelity."""

from __future__ import annotations

import math
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TEXT_PERCENT_MAP = {
    "%%c": "Ø",
    "%%C": "Ø",
    "%%d": "°",
    "%%D": "°",
    "%%p": "±",
    "%%P": "±",
}


def read_dxf_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "cp936", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "SECTION" in text and "ENTITIES" in text:
            return text, encoding
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def read_pairs(path: Path) -> tuple[list[tuple[str, str]], str]:
    text, encoding = read_dxf_text(path)
    raw_lines = text.splitlines()
    if len(raw_lines) % 2 == 1:
        raw_lines = raw_lines[:-1]
    pairs = [(code.strip(), value.strip()) for code, value in zip(raw_lines[0::2], raw_lines[1::2])]
    return pairs, encoding


def parse_sections(path: Path):
    pairs, encoding = read_pairs(path)
    entities = []
    blocks = defaultdict(list)
    tables = defaultdict(list)
    section = None
    block_name = None
    table_name = None
    cur_type = None
    cur_data = []

    def flush_entity() -> None:
        nonlocal cur_type, cur_data
        if cur_type:
            entities.append((cur_type, cur_data))
        cur_type = None
        cur_data = []

    def flush_block_entity() -> None:
        nonlocal cur_type, cur_data
        if block_name and cur_type:
            blocks[block_name].append((cur_type, cur_data))
        cur_type = None
        cur_data = []

    def flush_table_record() -> None:
        nonlocal cur_type, cur_data
        if table_name and cur_type:
            tables[table_name].append((cur_type, cur_data))
        cur_type = None
        cur_data = []

    for code, value in pairs:
        if code == "0" and value == "SECTION":
            section = None
            block_name = None
            table_name = None
            cur_type = None
            cur_data = []
            continue
        if code == "2" and section is None:
            section = value
            continue
        if code == "0" and value == "ENDSEC":
            if section == "ENTITIES":
                flush_entity()
            elif section == "BLOCKS":
                flush_block_entity()
            elif section == "TABLES":
                flush_table_record()
            section = None
            block_name = None
            table_name = None
            cur_type = None
            cur_data = []
            continue

        if section == "ENTITIES":
            if code == "0":
                flush_entity()
                cur_type = value
                cur_data = []
            else:
                cur_data.append((code, value))
        elif section == "BLOCKS":
            if code == "0" and value == "BLOCK":
                flush_block_entity()
                block_name = None
                cur_type = None
                cur_data = []
                continue
            if code == "2" and block_name is None:
                block_name = value
                continue
            if code == "0" and value == "ENDBLK":
                flush_block_entity()
                block_name = None
                cur_type = None
                cur_data = []
                continue
            if block_name:
                if code == "0":
                    flush_block_entity()
                    cur_type = value
                    cur_data = []
                else:
                    cur_data.append((code, value))
        elif section == "TABLES":
            if code == "0" and value == "TABLE":
                flush_table_record()
                table_name = None
                cur_type = None
                cur_data = []
                continue
            if code == "2" and table_name is None:
                table_name = value
                continue
            if code == "0" and value == "ENDTAB":
                flush_table_record()
                table_name = None
                cur_type = None
                cur_data = []
                continue
            if table_name:
                if code == "0":
                    flush_table_record()
                    cur_type = value
                    cur_data = []
                else:
                    cur_data.append((code, value))

    return entities, blocks, tables, encoding


def first(entity: list[tuple[str, str]], code: str, default: str = "") -> str:
    for c, value in entity:
        if c == code:
            return value
    return default


def values_for_code(entity: list[tuple[str, str]], code: str) -> list[str]:
    return [value for c, value in entity if c == code]


def parse_float(value: str, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value: str, default: int | None = None) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def floats_for_code(entity: list[tuple[str, str]], code: str) -> list[float]:
    values = []
    for value in values_for_code(entity, code):
        parsed = parse_float(value)
        if parsed is not None:
            values.append(parsed)
    return values


def entity_layer(entity: list[tuple[str, str]]) -> str:
    return first(entity, "8", "")


def entity_color(entity: list[tuple[str, str]]) -> int | None:
    return parse_int(first(entity, "62", ""))


def add_point(xs: list[float], ys: list[float], x_value: str, y_value: str) -> None:
    x = parse_float(x_value)
    y = parse_float(y_value)
    if x is not None and y is not None:
        xs.append(x)
        ys.append(y)


def bbox_from_points(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def bbox_size(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def bbox_pad(bbox: tuple[float, float, float, float], pad_x: float, pad_y: float) -> tuple[float, float, float, float]:
    return bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y


def boxes_touch(a: tuple[float, float, float, float], b: tuple[float, float, float, float], gap: float) -> bool:
    return not (a[2] + gap < b[0] or b[2] + gap < a[0] or a[3] + gap < b[1] or b[3] + gap < a[1])


def transform_bbox(
    bbox: tuple[float, float, float, float],
    x: float,
    y: float,
    sx: float,
    sy: float,
    rotation_degrees: float,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    corners = [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
    angle = math.radians(rotation_degrees)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    points = []
    for px, py in corners:
        tx = px * sx
        ty = py * sy
        points.append((x + tx * cos_a - ty * sin_a, y + tx * sin_a + ty * cos_a))
    result = bbox_from_points(points)
    if result is None:
        raise RuntimeError("Could not transform empty bbox.")
    return result


def block_geometry_bbox(block_entities: list[tuple[str, list[tuple[str, str]]]]) -> tuple[float, float, float, float]:
    boxes = []
    for entity_type, entity in block_entities:
        bbox = entity_bbox(entity_type, entity, blocks=None)
        if bbox is not None:
            boxes.append(bbox)
    result = bbox_union(boxes)
    if result is None:
        raise RuntimeError("Could not derive block extents from drawable geometry.")
    return result


def entity_bbox(
    entity_type: str,
    entity: list[tuple[str, str]],
    blocks: dict[str, list[tuple[str, list[tuple[str, str]]]]] | None = None,
) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []
    if entity_type == "LINE":
        for x_code, y_code in (("10", "20"), ("11", "21")):
            x = parse_float(first(entity, x_code, ""))
            y = parse_float(first(entity, y_code, ""))
            if x is not None and y is not None:
                points.append((x, y))
    elif entity_type in {"LWPOLYLINE", "POLYLINE"}:
        xs = floats_for_code(entity, "10")
        ys = floats_for_code(entity, "20")
        points.extend(list(zip(xs, ys)))
    elif entity_type in {"VERTEX", "POINT", "TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
        x = parse_float(first(entity, "10", ""))
        y = parse_float(first(entity, "20", ""))
        if x is not None and y is not None:
            points.append((x, y))
    elif entity_type in {"CIRCLE", "ARC"}:
        cx = parse_float(first(entity, "10", ""))
        cy = parse_float(first(entity, "20", ""))
        radius = parse_float(first(entity, "40", ""), 0.0)
        if cx is not None and cy is not None and radius is not None:
            radius = abs(radius)
            return cx - radius, cy - radius, cx + radius, cy + radius
    elif entity_type == "DIMENSION":
        for x_code, y_code in (("10", "20"), ("11", "21"), ("13", "23"), ("14", "24")):
            x = parse_float(first(entity, x_code, ""))
            y = parse_float(first(entity, y_code, ""))
            if x is not None and y is not None:
                points.append((x, y))
    elif entity_type == "HATCH":
        xs = floats_for_code(entity, "10")
        ys = floats_for_code(entity, "20")
        points.extend(list(zip(xs, ys)))
    elif entity_type == "INSERT" and blocks is not None:
        name = first(entity, "2", "")
        if name in blocks:
            try:
                block_bbox = block_geometry_bbox(blocks[name])
            except RuntimeError:
                return None
            x = parse_float(first(entity, "10", "0"), 0.0) or 0.0
            y = parse_float(first(entity, "20", "0"), 0.0) or 0.0
            sx = parse_float(first(entity, "41", "1"), 1.0) or 1.0
            sy = parse_float(first(entity, "42", "1"), 1.0) or 1.0
            rotation = parse_float(first(entity, "50", "0"), 0.0) or 0.0
            return transform_bbox(block_bbox, x, y, sx, sy, rotation)
    return bbox_from_points(points)


def get_text_value(entity: list[tuple[str, str]]) -> str:
    parts = values_for_code(entity, "1") + values_for_code(entity, "3")
    return "".join(parts)


def decode_cad_text(value: str) -> tuple[str, dict[str, int]]:
    stats = {
        "percentCodes": 0,
        "unicodeEscapes": 0,
        "mbcsEscapes": 0,
    }
    result = value
    for key, replacement in TEXT_PERCENT_MAP.items():
        if key in result:
            stats["percentCodes"] += result.count(key)
            result = result.replace(key, replacement)
    unicode_matches = re.findall(r"\\U\+([0-9A-Fa-f]{4})", result)
    stats["unicodeEscapes"] += len(unicode_matches)
    result = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), result)

    def decode_mbcs(match: re.Match[str]) -> str:
        stats["mbcsEscapes"] += 1
        payload = match.group(1)
        if len(payload) % 2 == 0:
            try:
                return bytes.fromhex(payload).decode("gb18030")
            except Exception:
                pass
        return match.group(0)

    result = re.sub(r"\\M\+([0-9A-Fa-f]{4,})", decode_mbcs, result)
    return result, stats


def sorted_counter_items(counter, limit: int = 20) -> list[dict]:
    return [{"value": key, "count": value} for key, value in counter.most_common(limit)]