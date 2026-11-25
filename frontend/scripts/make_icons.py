"""Draws the app icons (public/icons/*.png) from the same picture as public/favicon.svg: a lead agent linked to three others, white on the brand red.

    python frontend/scripts/make_icons.py        (needs Pillow; the PNGs are committed, run it only to change the picture)

icon-192.png, icon-512.png   normal icons (rounded square)
maskable-512.png             full-bleed square with the picture inside the safe zone (the phone cuts its own shape out of it)
apple-touch-icon.png         180 x 180, full-bleed (iOS rounds it itself)
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
TOP, BOTTOM, DARK = (197, 53, 54), (234, 77, 78), (197, 53, 54)
SCALE = 4                                                    # draw large, shrink: smooth edges


def gradient(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size))
    px = image.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
    return image


def picture(size: int, inset: float) -> Image.Image:
    """The agents on a transparent square of `size`, scaled so the 64-unit picture fills (1 - inset) of it."""
    big = size * SCALE
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    scale = big * (1 - inset) / 64
    offset = big * inset / 2

    def p(x, y):
        return (offset + x * scale, offset + y * scale)

    def circle(x, y, r, fill):
        draw.ellipse([*p(x - r, y - r), *p(x + r, y + r)], fill=fill)

    for end in ((32, 15), (16.5, 44.5), (47.5, 44.5)):
        draw.line([p(32, 33), p(*end)], fill=(255, 255, 255, 217), width=round(3.2 * scale))
        circle(*end, 1.6, (255, 255, 255, 217))                       # round line ends
    for x, y in ((32, 14), (15, 46), (49, 46)):
        circle(x, y, 6, (255, 255, 255, 255))
    circle(32, 33, 9, (255, 255, 255, 255))
    circle(32, 33, 3.8, DARK + (255,))
    return layer.resize((size, size), Image.LANCZOS)


def make(size: int, name: str, rounded: bool, inset: float) -> None:
    base = gradient(size).convert("RGBA")
    base.alpha_composite(picture(size, inset))
    if rounded:
        mask = Image.new("L", (size * SCALE, size * SCALE), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size * SCALE - 1, size * SCALE - 1], radius=round(size * SCALE * 15 / 64), fill=255)
        base.putalpha(mask.resize((size, size), Image.LANCZOS))
    base.save(OUT / name, optimize=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make(192, "icon-192.png", True, 0.12)
    make(512, "icon-512.png", True, 0.12)
    make(512, "maskable-512.png", False, 0.34)                       # the central 80% is always kept: stay well inside it
    make(180, "apple-touch-icon.png", False, 0.26)
    print("icons written to", OUT)
