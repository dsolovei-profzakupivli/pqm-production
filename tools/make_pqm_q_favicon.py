"""Rebuild the approved small PQM Q raster favicon variants."""
from pathlib import Path
from PIL import Image, ImageDraw


ASSETS = Path(__file__).resolve().parents[1] / "assets"
SCALE = 8


def icon(size):
    canvas = Image.new("RGBA", (64 * SCALE, 64 * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, 64 * SCALE - 1, 64 * SCALE - 1),
                           radius=13 * SCALE, fill="#132840")
    draw.ellipse((13 * SCALE, 12 * SCALE, 47 * SCALE, 46 * SCALE),
                 outline="#86bdff", width=7 * SCALE)
    draw.line((39 * SCALE, 40 * SCALE, 52 * SCALE, 53 * SCALE),
              fill="#86bdff", width=7 * SCALE, joint="curve")
    draw.ellipse((48.5 * SCALE, 49.5 * SCALE, 55.5 * SCALE, 56.5 * SCALE),
                 fill="#86bdff")
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    for size in (32, 180, 192):
        icon(size).save(ASSETS / f"pqm-q-favicon-{size}.png")
