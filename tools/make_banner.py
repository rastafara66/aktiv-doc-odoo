# -*- coding: utf-8 -*-
"""Банер-картка «Актив Doc» для магазину (`aktiv_doc/static/description/banner.png`).

    python tools/make_banner.py

Макет родини (як `yellow-edr-connector/tools/make_banner.py`): іконка зліва,
праворуч назва, що робить, уточнення — англійською, 560×315, без зразків даних
(код і назва організації на картинці виглядали б справжнім записом на вітрині).
Тло — темніший відтінок іконки, тож після її зміни перегенерувати й банер.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
DESC = os.path.join(os.path.dirname(HERE), "aktiv_doc", "static", "description")

SS = 4
TOP, BOTTOM = (30, 22, 60), (48, 36, 92)
WHITE = (250, 248, 255)
ACCENT = (255, 210, 90)
MUTED = (196, 188, 228)

TITLE = "Active Doc"
SUBTITLE = "KEP e-signature inside Odoo \u00b7 Ukraine"
DETAIL = "sign \u00b7 send \u00b7 incoming \u00b7 signed archive"


def vertical_gradient(size, top, bottom):
    width, height = size
    strip = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(height - 1, 1)
        strip.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return strip.resize(size, Image.BICUBIC)


def load_font(px, bold=False):
    names = ("arialbd.ttf", "calibrib.ttf") if bold else ("arial.ttf", "calibri.ttf")
    for name in names:
        path = os.path.join(r"C:\Windows\Fonts", name)
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


def fit_font(draw, text, max_width, start_px, bold=False):
    px = start_px
    while px > 8:
        font = load_font(px, bold=bold)
        if draw.textlength(text, font=font) <= max_width:
            return font
        px = int(px * 0.94)
    return load_font(px, bold=bold)


def build_banner(icon, width=560, height=315):
    w, h = width * SS, height * SS
    canvas = vertical_gradient((w, h), TOP, BOTTOM).convert("RGBA")
    margin = int(w * 0.07)
    mark_px = int(h * 0.42)
    mark_y = (h - mark_px) // 2
    mark = icon.convert("RGBA").resize((mark_px, mark_px), Image.LANCZOS)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", (mark_px, mark_px), (0, 0, 0, 110)),
                 (margin, mark_y + int(h * 0.022)), mark.split()[3])
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(int(h * 0.022))))
    canvas.paste(mark, (margin, mark_y), mark)

    draw = ImageDraw.Draw(canvas)
    text_x = margin + mark_px + int(w * 0.05)
    column = w - text_x - margin
    title_font = fit_font(draw, TITLE, column, int(h * 0.135), bold=True)
    sub_font = fit_font(draw, SUBTITLE, column, int(h * 0.058))
    detail_font = fit_font(draw, DETAIL, column, int(h * 0.046))
    gap_a, gap_b = int(h * 0.055), int(h * 0.048)
    y = (h - (title_font.size + gap_a + sub_font.size + gap_b + detail_font.size)) // 2
    draw.text((text_x, y), TITLE, font=title_font, fill=WHITE, anchor="la")
    y += title_font.size + gap_a
    draw.text((text_x, y), SUBTITLE, font=sub_font, fill=ACCENT, anchor="la")
    y += sub_font.size + gap_b
    draw.text((text_x, y), DETAIL, font=detail_font, fill=MUTED, anchor="la")
    return canvas.resize((width, height), Image.LANCZOS).convert("RGB")


def main():
    icon = Image.open(os.path.join(DESC, "icon.png"))
    out = os.path.join(DESC, "banner.png")
    build_banner(icon).save(out, optimize=True)
    print("banner.png 560x315 %.1f KB" % (os.path.getsize(out) / 1024))


if __name__ == "__main__":
    main()
