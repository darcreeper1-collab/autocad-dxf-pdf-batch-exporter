"""Merge one-page PDF outputs into a single PDF while preserving page order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge one-page PDF files into a combined PDF.")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pattern", default="page_*.pdf")
    parser.add_argument("--expected-count", type=int, default=0)
    args = parser.parse_args()

    files = sorted(args.input_dir.glob(args.pattern))
    if args.expected_count and len(files) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} page PDFs, found {len(files)} in {args.input_dir}")
    if not files:
        raise SystemExit(f"No PDFs matched {args.pattern} in {args.input_dir}")

    writer = PdfWriter()
    sizes = []
    for file in files:
        reader = PdfReader(str(file))
        if len(reader.pages) != 1:
            raise SystemExit(f"{file.name} has {len(reader.pages)} pages; expected 1")
        page = reader.pages[0]
        sizes.append([round(float(page.mediabox.width), 3), round(float(page.mediabox.height), 3)])
        writer.add_page(page)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as handle:
        writer.write(handle)

    merged = PdfReader(str(args.output))
    summary = {
        "output": str(args.output),
        "pages": len(merged.pages),
        "sourcePages": len(files),
        "firstPageSizePt": sizes[0],
        "uniqueSourceSizesPt": sorted({tuple(size) for size in sizes}),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
