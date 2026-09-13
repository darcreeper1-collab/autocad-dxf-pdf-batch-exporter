"""Verify exported PDFs after AutoCAD plotting by checking pages, sizes, and rendered samples."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader


def find_pdftoppm(explicit: str | None) -> str | None:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate)
        raise SystemExit(f"Explicit pdftoppm executable not found: {candidate}")
    on_path = shutil.which("pdftoppm.exe") or shutil.which("pdftoppm")
    if on_path:
        return on_path
    candidates = []
    exe = Path(sys.executable).resolve()
    for parent in list(exe.parents)[:3]:
        for rel in (
            Path("native/poppler/Library/bin/pdftoppm.exe"),
            Path("dependencies/native/poppler/Library/bin/pdftoppm.exe"),
            Path("bin/override/pdftoppm.exe"),
            Path("bin/fallback/pdftoppm.exe"),
        ):
            candidate = parent / rel
            if candidate.exists():
                candidates.append(candidate)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def parse_sample_pages(value: str, page_count: int) -> list[int]:
    if value == "auto":
        return sorted({1, max(1, (page_count + 1) // 2), page_count})
    pages = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        page = int(item)
        if page < 1 or page > page_count:
            raise SystemExit(f"Sample page {page} is outside PDF page range 1..{page_count}")
        pages.append(page)
    return sorted(set(pages))


def image_stats(path: Path) -> dict:
    try:
        from PIL import Image, ImageChops
    except Exception:
        return {"image": str(path), "statsAvailable": False}
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        r, g, b = rgb.split()
        low = ImageChops.darker(ImageChops.darker(r, g), b)
        high = ImageChops.lighter(ImageChops.lighter(r, g), b)
        ink = low.point([255 if value < 245 else 0 for value in range(256)])
        chroma = ImageChops.subtract(high, low).point([255 if value > 10 else 0 for value in range(256)])
        nonwhite = ink.histogram()[255]
        color_pixels = ImageChops.darker(ink, chroma).histogram()[255]
        box = ink.getbbox()
    bbox = None if box is None else [box[0], box[1], box[2] - 1, box[3] - 1]
    if bbox is not None:
        min_x, min_y, max_x, max_y = bbox
    margins = None
    margin_fractions = None
    bbox_fraction = None
    if bbox is not None:
        left = min_x
        top = min_y
        right = width - 1 - max_x
        bottom = height - 1 - max_y
        margins = [left, top, right, bottom]
        margin_fractions = [round(left / width, 6), round(top / height, 6), round(right / width, 6), round(bottom / height, 6)]
        bbox_fraction = [
            round((max_x - min_x + 1) / width, 6),
            round((max_y - min_y + 1) / height, 6),
        ]
    return {
        "image": str(path),
        "statsAvailable": True,
        "sizePx": [width, height],
        "nonwhitePixels": nonwhite,
        "colorPixels": color_pixels,
        "contentBBoxPx": bbox,
        "contentMarginsPx": margins,
        "contentMarginFractions": margin_fractions,
        "contentBBoxFractions": bbox_fraction,
    }


def render_page(pdftoppm: str, pdf: Path, page: int, render_dir: Path, dpi: int) -> Path:
    render_dir.mkdir(parents=True, exist_ok=True)
    prefix = render_dir / f"page_{page:03d}"
    cmd = [pdftoppm, "-png", "-r", str(dpi), "-f", str(page), "-l", str(page), str(pdf), str(prefix)]
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise SystemExit(f"pdftoppm failed for page {page}: {completed.stderr.strip()}")
    outputs = sorted(render_dir.glob(f"page_{page:03d}-*.png"))
    if not outputs:
        outputs = sorted(render_dir.glob(f"page_{page:03d}.png"))
    if not outputs:
        raise SystemExit(f"pdftoppm did not create a PNG for page {page}")
    return outputs[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify PDF page count, page sizes, and optional rendered samples.")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--expected-pages", type=int, default=0)
    parser.add_argument("--expected-width-pt", type=float, default=0)
    parser.add_argument("--expected-height-pt", type=float, default=0)
    parser.add_argument("--size-tolerance-pt", type=float, default=2.0)
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--sample-pages", default="auto")
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--pdftoppm")
    parser.add_argument("--max-margin-fraction", type=float, default=0.0)
    args = parser.parse_args()

    reader = PdfReader(str(args.pdf))
    page_count = len(reader.pages)
    if args.expected_pages and page_count != args.expected_pages:
        raise SystemExit(f"Expected {args.expected_pages} pages, found {page_count}")

    sizes = []
    for page in reader.pages:
        sizes.append([round(float(page.mediabox.width), 3), round(float(page.mediabox.height), 3)])
    unique_sizes = sorted({tuple(size) for size in sizes})
    if args.expected_width_pt and args.expected_height_pt:
        for index, (width, height) in enumerate(sizes, start=1):
            if abs(width - args.expected_width_pt) > args.size_tolerance_pt or abs(height - args.expected_height_pt) > args.size_tolerance_pt:
                raise SystemExit(f"Page {index} size {width} x {height} pt differs from expected {args.expected_width_pt} x {args.expected_height_pt} pt")

    rendered = []
    if args.render_dir:
        pdftoppm = find_pdftoppm(args.pdftoppm)
        if not pdftoppm:
            raise SystemExit("pdftoppm was not found; provide --pdftoppm or put Poppler on PATH")
        for page in parse_sample_pages(args.sample_pages, page_count):
            png = render_page(pdftoppm, args.pdf, page, args.render_dir, args.dpi)
            stats = image_stats(png)
            if stats.get("statsAvailable") and stats.get("nonwhitePixels", 0) == 0:
                raise SystemExit(f"Rendered sample page {page} appears blank")
            if args.max_margin_fraction and stats.get("contentMarginFractions"):
                max_margin = max(stats["contentMarginFractions"])
                if max_margin > args.max_margin_fraction:
                    raise SystemExit(
                        f"Rendered sample page {page} has max content margin fraction {max_margin}, "
                        f"above threshold {args.max_margin_fraction}"
                    )
            rendered.append({"page": page, **stats})

    summary = {
        "pdf": str(args.pdf),
        "pages": page_count,
        "uniquePageSizesPt": unique_sizes,
        "renderedSamples": rendered,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
