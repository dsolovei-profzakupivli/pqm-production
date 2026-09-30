"""Build smooth, compact SANDBOX PQM favicon rasters."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ASSETS = Path(__file__).resolve().parents[1] / "assets"
FONT = Path("C:/Windows/Fonts/ARIALNB.TTF")
SCALE = 8


def icon(size):
    canvas = Image.new("RGBA", (32 * SCALE, 32 * SCALE), "#132840")
    mask = Image.new("RGBA", (50 * SCALE, 30 * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(mask)
    font = ImageFont.truetype(str(FONT), 23 * SCALE)
    x = 0
    for letter, color in (("P", "#ffffff"), ("Q", "#86bdff"), ("M", "#ffffff")):
        draw.text((x, 0), letter, font=font, fill=color)
        x += draw.textlength(letter, font=font)
    bounds = mask.getbbox()
    letters = mask.crop(bounds).resize((28 * SCALE, 21 * SCALE), Image.Resampling.LANCZOS)
    canvas.alpha_composite(letters, (2 * SCALE, 5 * SCALE))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    for size in (16, 32, 180, 192):
        icon(size).save(ASSETS / f"pqm-q-favicon-{size}.png")
