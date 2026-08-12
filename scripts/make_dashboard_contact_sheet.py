#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

from f1_quote0.config import DASHBOARDS


def load_label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        os.environ.get("CONTACT_SHEET_FONT", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a labeled contact sheet for dashboard visual QA.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    scale, columns, label_height, gap = 2, 3, 30, 12
    cell_width, cell_height = 296 * scale, 152 * scale + label_height
    rows = (len(DASHBOARDS) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * cell_width + (columns + 1) * gap, rows * cell_height + (rows + 1) * gap),
        "#d8d8d8",
    )
    draw = ImageDraw.Draw(sheet)
    font = load_label_font(16)
    for index, name in enumerate(DASHBOARDS):
        column, row = index % columns, index // columns
        x = gap + column * (cell_width + gap)
        y = gap + row * (cell_height + gap)
        with Image.open(args.source / f"{name}.png") as source:
            preview = source.convert("RGB").resize((296 * scale, 152 * scale), Image.Resampling.NEAREST)
        sheet.paste(preview, (x, y))
        draw.text((x, y + 152 * scale + 5), name, font=font, fill="black")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, format="PNG", optimize=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
