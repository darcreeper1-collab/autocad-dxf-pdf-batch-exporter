"""Title-block page-number extraction for detected DXF drawing frames."""

from __future__ import annotations

import re

from dxf_scan_utils import decode_cad_text, entity_layer, first, get_text_value, parse_float

TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
PAGE_NUMBER_PATTERN = re.compile("\u7b2c\\s*(\\d+)\\s*\u5f20\\s*\u5171\\s*(\\d+)\\s*\u5f20")


def apply_page_number_sort(frames: list[dict], entities) -> tuple[list[dict], dict, list[str]]:
    """Sort frames by title-block pages only when every page agrees on one sequence."""
    warnings: list[str] = []
    evidence_count = 0
    for frame in frames:
        x0, y0, x1, y1 = frame["rawWindow"]
        matches = []
        for entity_type, entity in entities:
            if entity_type not in TEXT_TYPES:
                continue
            x = parse_float(first(entity, "10", ""))
            y = parse_float(first(entity, "20", ""))
            if x is None or y is None or not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            text, _ = decode_cad_text(get_text_value(entity))
            match = PAGE_NUMBER_PATTERN.search(text)
            if not match:
                continue
            matches.append(
                {
                    "page": int(match.group(1)),
                    "total": int(match.group(2)),
                    "text": text[:160],
                    "layer": entity_layer(entity),
                    "point": [round(x, 6), round(y, 6)],
                }
            )
        if matches:
            unique = {(item["page"], item["total"]) for item in matches}
            if len(unique) == 1:
                frame["pageNumberEvidence"] = matches[0]
                evidence_count += 1
            else:
                frame["pageNumberEvidence"] = {"ambiguous": True, "matches": matches[:8]}
                warnings.append(f"Multiple conflicting title-block page numbers were found in frame at {frame['insert']}.")

    evidence = [frame for frame in frames if isinstance(frame.get("pageNumberEvidence"), dict) and "page" in frame["pageNumberEvidence"]]
    totals = {frame["pageNumberEvidence"]["total"] for frame in evidence}
    numbers = [frame["pageNumberEvidence"]["page"] for frame in evidence]
    expected = len(frames)
    valid = (
        evidence_count == expected
        and len(totals) == 1
        and next(iter(totals)) == expected
        and sorted(numbers) == list(range(1, expected + 1))
    )
    if valid:
        frames.sort(key=lambda item: item["pageNumberEvidence"]["page"])
        return frames, {"method": "title-block-page-number", "detected": evidence_count, "expectedTotal": expected}, warnings
    if evidence_count:
        warnings.append(
            f"Title-block page-number evidence was incomplete or inconsistent ({evidence_count}/{expected} frames); retained geometric ordering."
        )
    return frames, {"method": "geometry", "detected": evidence_count, "expectedTotal": expected}, warnings