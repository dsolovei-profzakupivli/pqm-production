"""Build sandbox PQM favicon rasters from a purpose-drawn 16-pixel monogram."""
from pathlib import Path
from PIL import Image, ImageDraw


ASSETS = Path(__file__).resolve().parents[1] / "assets"
GLYPHS = {
    "P": ("1110", "1001", "1001", "1110", "1000", "1000", "1000"),
    "Q": ("0110", "1001", "1001", "1001", "1011", "0111", "0001"),
    "M": ("1001", "1111", "1111", "1001", "1001", "1001", "1001"),
}


def icon(size):
    canvas = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, 15, 15), radius=3, fill="#132840")
    for letter, x_offset, color in (("P", 1, "#ffffff"), ("Q", 6, "#86bdff"), ("M", 11, "#ffffff")):
        for y, row in enumerate(GLYPHS[letter], start=4):
            for x, pixel in enumerate(row, start=x_offset):
                if pixel == "1":
                    draw.point((x, y), fill=color)
    return canvas.resize((size, size), Image.Resampling.NEAREST)


if __name__ == "__main__":
    for size in (16, 32, 180, 192):
        icon(size).save(ASSETS / f"pqm-q-favicon-{size}.png")
