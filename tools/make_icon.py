# -*- coding: utf-8 -*-
"""Іконка «Active Doc» (`aktiv_doc/static/description/icon.png`).

    python tools/make_icon.py

Родина «Активів» (`aktiv/tools/make_icon.py`): заокруглена плитка з градієнтом,
біла «А» і золота лінія під нею; модулі різняться лише відтінком плитки. Тут —
фіолетово-індиговий, щоб у каталозі «Active Doc» не зливався з бірюзовими
«Активом» і Pro.

🔴 Іконка — джерело кольору для банера: після зміни перегенерувати
`tools/make_banner.py` і широкий банер у 3A (`tools/store/make_wide_banner.py`).
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
DESC = os.path.join(os.path.dirname(HERE), "aktiv_doc", "static", "description")

SIZE = 256
SS = 4
TOP = (64, 50, 122)
BOTTOM = (78, 62, 138)   # яскравість ≤ 0,55: інакше піпетка широкого банера бере плитку за акцент
GOLD = (255, 210, 90)
WHITE = (255, 255, 255)
RADIUS = 0.22
LETTER = "А"
LETTER_H = 0.58
BAR_W = 0.42
BAR_H = 0.052
GAP = 0.045


def load_font(px):
    for name in ("arialbd.ttf", "calibrib.ttf", "seguisb.ttf"):
        path = os.path.join(r"C:\Windows\Fonts", name)
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


def vertical_gradient(size, top, bottom):
    width, height = size
    strip = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(height - 1, 1)
        strip.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return strip.resize(size, Image.BICUBIC)


def letter_layer(side, height_px):
    """Літера на прозорому шарі, обрізана до реальних пікселів (кегль ≠ висота знака)."""
    px = height_px
    for _ in range(40):
        layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((side // 2, side // 2), LETTER, font=load_font(px),
                                   fill=WHITE, anchor="mm")
        box = layer.getbbox()
        if not box:
            break
        got = box[3] - box[1]
        if abs(got - height_px) <= 1:
            return layer.crop(box)
        px = max(1, int(px * height_px / got))
    return layer.crop(layer.getbbox())


def build_icon():
    side = SIZE * SS
    tile = vertical_gradient((side, side), TOP, BOTTOM).convert("RGBA")
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1),
                                           radius=int(side * RADIUS), fill=255)
    icon = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    icon.paste(tile, (0, 0), mask)
    letter = letter_layer(side, int(side * LETTER_H))
    bar_w, bar_h, gap = int(side * BAR_W), int(side * BAR_H), int(side * GAP)
    block_h = letter.height + gap + bar_h
    top = (side - block_h) // 2
    icon.paste(letter, ((side - letter.width) // 2, top), letter)
    bar_y = top + letter.height + gap
    ImageDraw.Draw(icon).rounded_rectangle(
        ((side - bar_w) // 2, bar_y, (side + bar_w) // 2, bar_y + bar_h),
        radius=bar_h // 2, fill=GOLD)
    assert block_h < side * 0.80 and letter.width < side * 0.72 and bar_w < side * 0.62
    return icon.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(DESC, exist_ok=True)
    out = os.path.join(DESC, "icon.png")
    build_icon().save(out, optimize=True)
    print("icon.png %dx%d %.1f KB" % (SIZE, SIZE, os.path.getsize(out) / 1024))


if __name__ == "__main__":
    main()
