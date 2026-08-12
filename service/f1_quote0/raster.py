from __future__ import annotations

import io
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from .canvas import Assets


WIDTH = 296
HEIGHT = 152
SCALE = 4
TEXT_THRESHOLD = 176
DATA_URI_PREFIX_BYTES = len("data:image/png;base64,")

DEFAULT_REGULAR_FONTS = (
    "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/arial.ttf",
    "DejaVuSans.ttf",
)
DEFAULT_BOLD_FONTS = (
    "/usr/share/fonts/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "DejaVuSans-Bold.ttf",
)


def atkinson_dither(image: Image.Image, threshold: int = 128) -> Image.Image:
    """Convert an antialiased grayscale image to deterministic 1-bit Atkinson dots."""
    grayscale = image.convert("L")
    width, height = grayscale.size
    source_pixels = (
        grayscale.get_flattened_data()
        if hasattr(grayscale, "get_flattened_data")
        else grayscale.getdata()
    )
    pixels = [float(value) for value in source_pixels]
    output = [255] * (width * height)
    offsets = ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2))

    for y in range(height):
        row = y * width
        for x in range(width):
            index = row + x
            old = pixels[index]
            new = 255 if old >= threshold else 0
            output[index] = new
            share = (old - new) / 8.0
            for dx, dy in offsets:
                target_x, target_y = x + dx, y + dy
                if 0 <= target_x < width and 0 <= target_y < height:
                    target = target_y * width + target_x
                    pixels[target] = min(255.0, max(0.0, pixels[target] + share))

    result = Image.new("1", (width, height), 1)
    result.putdata(output)
    return result


def hard_threshold(image: Image.Image, threshold: int = TEXT_THRESHOLD) -> Image.Image:
    """Keep hinted glyph stems and rules continuous instead of diffusing their edge pixels."""
    return image.convert("L").point(
        [0 if value < threshold else 255 for value in range(256)],
        mode="1",
    )


class DashboardRasterRenderer:
    """Render every upstream dashboard presentation with one shared e-ink pipeline."""

    def __init__(self, assets: Assets):
        self.assets = assets
        self.regular_font = self._font_path("F1_FONT_REGULAR", DEFAULT_REGULAR_FONTS)
        self.bold_font = self._font_path("F1_FONT_BOLD", DEFAULT_BOLD_FONTS)
        self._art_regions: list[tuple[int, int, int, int]] = []

    @staticmethod
    def _font_path(variable: str, candidates: tuple[str, ...]) -> str:
        configured = os.environ.get(variable)
        if configured:
            if not Path(configured).is_file():
                raise RuntimeError(f"字体文件不存在：{configured}")
            return configured
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
            try:
                ImageFont.truetype(candidate, 12)
                return candidate
            except OSError:
                continue
        raise RuntimeError(f"找不到可用字体；请设置 {variable}")

    def _font(self, size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.bold_font if bold else self.regular_font, size * SCALE)

    @staticmethod
    def _bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
        return draw.textbbox((0, 0), text, font=font)

    def _width(self, draw: ImageDraw.ImageDraw, text: object, font: ImageFont.FreeTypeFont) -> int:
        left, _, right, _ = self._bbox(draw, str(text or ""), font)
        return right - left

    def _fit(self, draw: ImageDraw.ImageDraw, text: object, font: ImageFont.FreeTypeFont, max_width: int) -> str:
        value = str(text or "")
        limit = max_width * SCALE
        if self._width(draw, value, font) <= limit:
            return value
        suffix = "…"
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            if self._width(draw, value[:middle] + suffix, font) <= limit:
                low = middle
            else:
                high = middle - 1
        return value[:low] + suffix if low else suffix

    def _fit_font(
        self,
        draw: ImageDraw.ImageDraw,
        text: object,
        preferred: int,
        max_width: int,
        *,
        bold: bool,
        minimum: int,
    ) -> tuple[ImageFont.FreeTypeFont, str]:
        value = str(text or "")
        for size in range(preferred, minimum - 1, -1):
            font = self._font(size, bold=bold)
            if self._width(draw, value, font) <= max_width * SCALE:
                return font, value
        font = self._font(minimum, bold=bold)
        return font, self._fit(draw, value, font, max_width)

    def _draw_top_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: object,
        x: float,
        y: float,
        font: ImageFont.FreeTypeFont,
        *,
        fill: int = 0,
        max_width: int | None = None,
    ) -> str:
        value = self._fit(draw, text, font, max_width) if max_width else str(text or "")
        left, top, _, _ = self._bbox(draw, value, font)
        draw.text((round(x * SCALE - left), round(y * SCALE - top)), value, font=font, fill=fill)
        return value

    def _draw_right_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: object,
        right: float,
        y: float,
        font: ImageFont.FreeTypeFont,
        *,
        fill: int = 0,
        max_width: int | None = None,
    ) -> str:
        value = self._fit(draw, text, font, max_width) if max_width else str(text or "")
        left, top, text_right, _ = self._bbox(draw, value, font)
        x = right * SCALE - (text_right - left) - left
        draw.text((round(x), round(y * SCALE - top)), value, font=font, fill=fill)
        return value

    def _draw_centered_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: object,
        box: tuple[float, float, float, float],
        font: ImageFont.FreeTypeFont,
        *,
        fill: int,
    ) -> None:
        value = str(text or "")
        left, top, right, bottom = self._bbox(draw, value, font)
        x1, y1, x2, y2 = (coordinate * SCALE for coordinate in box)
        x = x1 + ((x2 - x1) - (right - left)) / 2 - left
        y = y1 + ((y2 - y1) - (bottom - top)) / 2 - top
        draw.text((round(x), round(y)), value, font=font, fill=fill)

    def _draw_asset(
        self,
        canvas: Image.Image,
        name: str | None,
        box: tuple[int, int, int, int],
        *,
        background: int = 255,
        padding: int = 0,
    ) -> None:
        path = self.assets.path(name)
        if not path:
            return
        x1, y1, x2, y2 = box
        target_width = max(1, (x2 - x1 - padding * 2) * SCALE)
        target_height = max(1, (y2 - y1 - padding * 2) * SCALE)
        with Image.open(path) as source:
            artwork = source.convert("RGBA")
            ratio = min(target_width / artwork.width, target_height / artwork.height)
            artwork = artwork.resize(
                (max(1, round(artwork.width * ratio)), max(1, round(artwork.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        surface = Image.new("RGBA", ((x2 - x1) * SCALE, (y2 - y1) * SCALE), (background,) * 3 + (255,))
        offset = ((surface.width - artwork.width) // 2, (surface.height - artwork.height) // 2)
        surface.alpha_composite(artwork, offset)
        canvas.paste(surface.convert("L"), (x1 * SCALE, y1 * SCALE))
        self._art_regions.append(box)

    def _frame(self, draw: ImageDraw.ImageDraw) -> None:
        draw.rounded_rectangle(
            (SCALE, SCALE, (WIDTH - 2) * SCALE, (HEIGHT - 2) * SCALE),
            radius=6 * SCALE,
            outline=0,
            width=2 * SCALE,
        )
        draw.line((2 * SCALE, 24 * SCALE, (WIDTH - 3) * SCALE, 24 * SCALE), fill=0, width=SCALE)

    def _masthead(self, draw: ImageDraw.ImageDraw, dashboard: dict) -> None:
        status_font = self._font(10, bold=True)
        status = str(dashboard.get("status", ""))
        status_width = round(self._width(draw, status, status_font) / SCALE)
        pill_width = min(142, max(46, status_width + 12))
        pill = (WIDTH - 10 - pill_width, 4, WIDTH - 10, 21)
        draw.rounded_rectangle(tuple(value * SCALE for value in pill), radius=8 * SCALE, fill=0)
        self._draw_centered_text(draw, status, pill, status_font, fill=255)
        self._draw_top_text(
            draw,
            dashboard.get("eyebrow", ""),
            10,
            7,
            self._font(10, bold=True),
            max_width=max(30, WIDTH - pill_width - 34),
        )

    def _countdown(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, dashboard: dict) -> None:
        self._draw_top_text(draw, dashboard.get("title", ""), 12, 32, self._font(45, bold=True), max_width=158)
        self._draw_top_text(draw, dashboard.get("subtitle", ""), 12, 83, self._font(20, bold=True), max_width=158)
        self._draw_top_text(draw, dashboard.get("detail_primary", ""), 12, 111, self._font(11), max_width=158)
        self._draw_top_text(draw, dashboard.get("detail_secondary", ""), 12, 131, self._font(11), max_width=158)
        self._draw_asset(canvas, dashboard.get("track_asset"), (176, 45, 290, 125))

    def _metric(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, dashboard: dict) -> None:
        side_asset = dashboard.get("side_asset")
        content_right = 204 if side_asset else WIDTH
        if side_asset:
            draw.rectangle((204 * SCALE, 25 * SCALE, (WIDTH - 2) * SCALE, (HEIGHT - 2) * SCALE), fill=0)
            self._draw_asset(canvas, side_asset, (208, 39, 291, 136), background=0, padding=8)

        unit_font = self._font(12, bold=True)
        unit_width = round(self._width(draw, "分", unit_font) / SCALE)
        metric_font, metric = self._fit_font(
            draw,
            dashboard.get("hero_metric", "0"),
            42,
            88 if side_asset else 112,
            bold=True,
            minimum=28,
        )
        metric_width = round(self._width(draw, metric, metric_font) / SCALE)
        metric_x = content_right - 12 - unit_width - 4 - metric_width
        title_font, title = self._fit_font(
            draw,
            dashboard.get("title", ""),
            46,
            max(42, metric_x - 22),
            bold=True,
            minimum=30,
        )
        self._draw_top_text(draw, title, 12, 33, title_font)
        self._draw_top_text(draw, metric, metric_x, 37, metric_font)
        self._draw_top_text(draw, "分", content_right - 12 - unit_width, 65, unit_font)

        divider_y = 96
        draw.line((12 * SCALE, divider_y * SCALE, (content_right - 12) * SCALE, divider_y * SCALE), fill=0, width=SCALE)
        primary = dashboard.get("detail_primary") or dashboard.get("subtitle", "")
        self._draw_top_text(draw, primary, 12, 103, self._font(15, bold=True), max_width=content_right - 24)
        self._draw_top_text(draw, dashboard.get("detail_secondary", ""), 12, 128, self._font(10, bold=True), max_width=content_right - 24)

    def _hero(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, dashboard: dict) -> None:
        has_details = bool(dashboard.get("detail_primary") or dashboard.get("detail_secondary"))
        title_size = 38 if has_details else 31
        mark_width = 58 if dashboard.get("decoration_asset") else 0
        self._draw_top_text(draw, dashboard.get("title", ""), 12, 40, self._font(title_size, bold=True), max_width=WIDTH - 24 - mark_width)
        self._draw_top_text(draw, dashboard.get("subtitle", ""), 12, 83, self._font(16, bold=True), max_width=WIDTH - 24 - mark_width)
        self._draw_top_text(draw, dashboard.get("detail_primary", ""), 12, 111, self._font(11), max_width=WIDTH - 24 - mark_width)
        self._draw_top_text(draw, dashboard.get("detail_secondary", ""), 12, 131, self._font(11), max_width=WIDTH - 24 - mark_width)
        if dashboard.get("decoration_asset"):
            self._draw_asset(canvas, dashboard.get("decoration_asset"), (WIDTH - 66, 61, WIDTH - 10, 99))

    def _headline(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, dashboard: dict, height: int) -> int:
        presentation = dashboard.get("presentation", "standard")
        title_size = 21 if presentation == "spotlight" else 19 if presentation == "ranking" else 18
        asset_width = 54 if dashboard.get("decoration_asset") else 0
        max_width = WIDTH - 20 - asset_width
        y0, bottom = 25, 25 + height
        self._draw_top_text(draw, dashboard.get("title", ""), 10, y0 + 5, self._font(title_size, bold=True), max_width=max_width)
        if dashboard.get("subtitle"):
            self._draw_top_text(draw, dashboard.get("subtitle", ""), 10, y0 + 28, self._font(9, bold=False), max_width=max_width)
        if dashboard.get("decoration_asset"):
            self._draw_asset(canvas, dashboard.get("decoration_asset"), (WIDTH - 62, y0 + 6, WIDTH - 10, bottom - 6))
        draw.line((2 * SCALE, bottom * SCALE, (WIDTH - 3) * SCALE, bottom * SCALE), fill=0, width=2 * SCALE)
        return bottom + 1

    def _standard_rows(self, draw: ImageDraw.ImageDraw, dashboard: dict, y0: int) -> None:
        rows = list(dashboard.get("rows") or [])[:3]
        if not rows:
            return
        detailed = any(row.get("tertiary") for row in rows)
        bottom = HEIGHT - 2
        row_height = (bottom - y0) / len(rows)
        for index, row in enumerate(rows):
            top = y0 + row_height * index
            row_bottom = y0 + row_height * (index + 1)
            value = str(row.get("value", ""))
            value_font = self._font(12, bold=True)
            value_width = round(self._width(draw, value, value_font) / SCALE) if value else 0
            rank_font, rank = self._fit_font(draw, row.get("rank", ""), 14, 36, bold=True, minimum=10)
            self._draw_top_text(draw, rank, 9, top + max(4, (row_height - 15) / 2), rank_font)
            text_x = 50
            text_width = WIDTH - text_x - 10 - (value_width + 8 if value else 0)
            if detailed:
                self._draw_top_text(draw, row.get("primary", ""), text_x, top + 3, self._font(12, bold=True), max_width=text_width)
                self._draw_top_text(draw, row.get("secondary", ""), text_x, top + 17, self._font(9), max_width=text_width)
                self._draw_top_text(draw, row.get("tertiary", ""), text_x, top + 29, self._font(9), max_width=text_width)
            else:
                primary_y = top + (4 if row_height <= 30 else 8)
                self._draw_top_text(draw, row.get("primary", ""), text_x, primary_y, self._font(12 if row_height <= 30 else 14, bold=True), max_width=text_width)
                if row.get("secondary"):
                    self._draw_top_text(draw, row.get("secondary", ""), text_x, primary_y + (14 if row_height <= 30 else 19), self._font(8 if row_height <= 30 else 10), max_width=text_width)
            if value:
                self._draw_right_text(draw, value, WIDTH - 10, top + max(5, (row_height - 14) / 2), value_font, max_width=74)
            if index < len(rows) - 1:
                draw.line((8 * SCALE, round(row_bottom * SCALE), (WIDTH - 8) * SCALE, round(row_bottom * SCALE)), fill=0, width=SCALE)

    def _spotlight_rows(self, draw: ImageDraw.ImageDraw, dashboard: dict, y0: int) -> None:
        rows = list(dashboard.get("rows") or [])[:1]
        if not rows:
            return
        row = rows[0]
        rank_font, rank = self._fit_font(draw, row.get("rank", ""), 46, 103, bold=True, minimum=32)
        self._draw_top_text(draw, rank, 15, y0 + 13, rank_font)
        divider_x = 126
        draw.line((divider_x * SCALE, (y0 + 10) * SCALE, divider_x * SCALE, (HEIGHT - 12) * SCALE), fill=0, width=2 * SCALE)
        primary_font, primary = self._fit_font(draw, row.get("primary", ""), 25, WIDTH - divider_x - 24, bold=True, minimum=18)
        self._draw_right_text(draw, primary, WIDTH - 12, y0 + 17, primary_font)
        self._draw_right_text(draw, row.get("secondary", ""), WIDTH - 12, y0 + 51, self._font(13, bold=True), max_width=WIDTH - divider_x - 24)

    def _ranking_rows(self, draw: ImageDraw.ImageDraw, dashboard: dict, y0: int) -> None:
        rows = list(dashboard.get("rows") or [])[:2]
        if not rows:
            return
        bottom = HEIGHT - 2
        row_height = (bottom - y0) / len(rows)
        for index, row in enumerate(rows):
            top = y0 + row_height * index
            row_bottom = y0 + row_height * (index + 1)
            value = str(row.get("value", ""))
            value_font, value = self._fit_font(draw, value, 18, 72, bold=True, minimum=13)
            value_width = round(self._width(draw, value, value_font) / SCALE) if value else 0
            rank_font, rank = self._fit_font(draw, row.get("rank", ""), 23, 52, bold=True, minimum=16)
            self._draw_top_text(draw, rank, 10, top + max(7, (row_height - 24) / 2), rank_font)
            text_x = 68
            text_width = WIDTH - text_x - 10 - (value_width + 10 if value else 0)
            primary_font, primary = self._fit_font(
                draw,
                row.get("primary", ""),
                15,
                text_width,
                bold=True,
                minimum=12,
            )
            self._draw_top_text(draw, primary, text_x, top + 5, primary_font)
            self._draw_top_text(draw, row.get("secondary", ""), text_x, top + 25, self._font(10, bold=True), max_width=text_width)
            if value:
                self._draw_right_text(draw, value, WIDTH - 10, top + max(8, (row_height - 20) / 2), value_font)
            if index < len(rows) - 1:
                draw.line((8 * SCALE, round(row_bottom * SCALE), (WIDTH - 8) * SCALE, round(row_bottom * SCALE)), fill=0, width=SCALE)

    def render(self, dashboard: dict) -> Image.Image:
        self._art_regions = []
        canvas = Image.new("L", (WIDTH * SCALE, HEIGHT * SCALE), 255)
        draw = ImageDraw.Draw(canvas)
        self._frame(draw)
        self._masthead(draw, dashboard)

        if dashboard.get("hero_metric") is not None:
            self._metric(canvas, draw, dashboard)
        elif dashboard.get("presentation") == "hero" and dashboard.get("track_asset"):
            self._countdown(canvas, draw, dashboard)
        elif dashboard.get("presentation") == "hero" and not dashboard.get("rows"):
            self._hero(canvas, draw, dashboard)
        elif dashboard.get("presentation") == "spotlight":
            y0 = self._headline(canvas, draw, dashboard, 46)
            self._spotlight_rows(draw, dashboard, y0)
        elif dashboard.get("presentation") == "ranking":
            y0 = self._headline(canvas, draw, dashboard, 40)
            self._ranking_rows(draw, dashboard, y0)
        else:
            y0 = self._headline(canvas, draw, dashboard, 42)
            self._standard_rows(draw, dashboard, y0)

        antialiased = canvas.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        result = hard_threshold(antialiased)
        for box in self._art_regions:
            artwork = atkinson_dither(antialiased.crop(box))
            result.paste(artwork, box[:2])
        return result

    @staticmethod
    def _png(image: Image.Image) -> bytes:
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True, compress_level=9)
        return output.getvalue()

    def png(self, dashboard: dict) -> bytes:
        return self._png(self.render(dashboard))

    def png_parts(self, dashboard: dict, max_data_uri_bytes: int) -> list[tuple[bytes, int]]:
        image = self.render(dashboard)
        whole = self._png(image)
        whole_uri_size = DATA_URI_PREFIX_BYTES + 4 * ((len(whole) + 2) // 3)
        if whole_uri_size < max_data_uri_bytes:
            return [(whole, HEIGHT)]

        boundaries = (0, 51, 102, HEIGHT)
        parts: list[tuple[bytes, int]] = []
        for top, bottom in zip(boundaries, boundaries[1:]):
            content = self._png(image.crop((0, top, WIDTH, bottom)))
            uri_size = DATA_URI_PREFIX_BYTES + 4 * ((len(content) + 2) // 3)
            if uri_size >= max_data_uri_bytes:
                raise RuntimeError(f"画板分片仍然过大：{uri_size}")
            parts.append((content, bottom - top))
        return parts
