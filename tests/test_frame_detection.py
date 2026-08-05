"""Synthetic regression: eight A1 frames on a named frame layer and reversed page numbers."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETECT = ROOT / "dxf-batch-pdf-export" / "scripts" / "detect_dxf_frames.py"
PREFLIGHT = ROOT / "dxf-batch-pdf-export" / "scripts" / "analyze_dxf_features.py"
FRAME_LAYER = "\u56fe\u6846-A1"
TITLE_LAYER = "\u6807\u9898\u680f"


def pair(code: int, value: object) -> list[str]:
    return [str(code), str(value)]


def line(layer: str, x0: float, y0: float, x1: float, y1: float) -> list[str]:
    return pair(0, "LINE") + pair(8, layer) + pair(10, x0) + pair(20, y0) + pair(11, x1) + pair(21, y1)


def text(x: float, y: float, value: str) -> list[str]:
    return pair(0, "TEXT") + pair(8, TITLE_LAYER) + pair(10, x) + pair(20, y) + pair(1, value)


def make_dxf(path: Path) -> dict[int, tuple[float, float]]:
    lines = pair(0, "SECTION") + pair(2, "ENTITIES")
    locations: dict[int, tuple[float, float]] = {}
    page = 8  # Geometry order is intentionally not title-block order.
    for row in range(2):
        for col in range(4):
            x, y = col * 900.0, (1 - row) * 700.0
            locations[page] = (x, y)
            lines += line(FRAME_LAYER, x, y, x + 841, y)
            lines += line(FRAME_LAYER, x + 841, y, x + 841, y + 594)
            lines += line(FRAME_LAYER, x + 841, y + 594, x, y + 594)
            lines += line(FRAME_LAYER, x, y + 594, x, y)
            lines += text(x + 600, y + 30, f"\u7b2c{page}\u5f20 \u51718\u5f20")
            page -= 1
    lines += pair(0, "ENDSEC") + pair(0, "EOF")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return locations


def main() -> None:
    scratch_parent = ROOT / ".test-output"
    scratch_parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=scratch_parent))
    try:
        source, output, preflight = work / "eight_a1.dxf", work / "frames.json", work / "preflight.json"
        locations = make_dxf(source)
        subprocess.run([sys.executable, str(DETECT), "--input", str(source), "--output", str(output), "--frame-width", "841", "--frame-height", "594", "--strategy", "auto"], check=True)
        subprocess.run([sys.executable, str(PREFLIGHT), "--input", str(source), "--output", str(preflight), "--frame-width", "841", "--frame-height", "594"], check=True)
        result = json.loads(output.read_text(encoding="utf-8"))
        report = json.loads(preflight.read_text(encoding="utf-8"))
        assert result["detectionStrategy"] == "layer", result
        assert result["pageCount"] == 8, result
        assert result["pageOrder"]["method"] == "title-block-page-number", result
        assert [frame["pageNumberEvidence"]["page"] for frame in result["frames"]] == list(range(1, 9)), result
        assert tuple(result["frames"][0]["insert"]) == locations[1], result["frames"][0]
        assert len(result["diagnostics"]["layerCandidates"]) == 8, result["diagnostics"]
        assert len(report["frameCandidates"]["layer"]) == 8, report["frameCandidates"]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("Python synthetic frame tests passed.")


if __name__ == "__main__":
    main()