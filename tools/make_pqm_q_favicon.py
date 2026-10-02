"""Build environment-specific favicon rasters from the approved Q geometry."""
from pathlib import Path
from PIL import Image, ImageDraw


ASSETS = Path(__file__).resolve().parents[1] / "assets"
SCALE = 8


def icon(size, background):
    canvas = Image.new("RGBA", (48 * SCALE, 48 * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, 48 * SCALE - 1, 48 * SCALE - 1), radius=10 * SCALE, fill=background)
    draw.ellipse((5 * SCALE, 3 * SCALE, 43 * SCALE, 41 * SCALE), fill="#63b2ff")
    draw.ellipse((14 * SCALE, 12 * SCALE, 34 * SCALE, 32 * SCALE), fill=background)
    draw.polygon([(24 * SCALE, 27 * SCALE), (31 * SCALE, 23 * SCALE),
                  (47 * SCALE, 46 * SCALE), (35 * SCALE, 46 * SCALE)], fill="#63b2ff")
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    for size in (16, 32, 180, 192):
        icon(size, "#f5f7f8").save(ASSETS / f"pqm-q-favicon-prod-{size}.png")
