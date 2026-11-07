#!/usr/bin/env python3
"""The package's icon (512x512) and background (1920x1080): original art (a sea, waves and a low sun, the
lettering "WWHD"), nothing from the game. Also the Maker's Windows icon.
    make-art.py <out dir>     -> icon0.png, pic1.png, maker.ico
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def sea(w, h):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        top, bottom = (24, 120, 196), (6, 34, 92)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    return img


def waves(d, w, h, y0, rows, amp, color):
    for r in range(rows):
        y = y0 + r * (h - y0) / rows
        pts = []
        for x in range(0, w + 8, 8):
            pts.append((x, y + amp * math.sin(x / (w / 7.0) + r * 1.3)))
        d.line(pts, fill=color, width=max(2, w // 160))


def swirl(d, cx, cy, size, color, width):
    """A wind swirl: an Archimedean spiral of two and a half turns with a tail."""
    pts = []
    turns = 2.5
    for i in range(0, 400):
        a = i / 400.0 * turns * 2 * math.pi
        rad = size * 0.42 * (a / (turns * 2 * math.pi))
        pts.append((cx + rad * math.cos(a), cy - rad * math.sin(a)))
    ex, ey = pts[-1]
    for i in range(1, 60):
        pts.append((ex + i * size * 0.012, ey - math.sin(i / 9.0) * size * 0.04))
    d.line(pts, fill=color, width=width, joint="curve")


def card(w, h, title_size, sub):
    img = sea(w, h)
    d = ImageDraw.Draw(img)
    waves(d, w, h, int(h * 0.62), 5, h * 0.025, (150, 210, 245))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = min(w, h) * 0.16  # a low sun over the sea
    cx, cy = w * 0.5, h * 0.36
    gd.ellipse((cx - r * 1.6, cy - r * 1.6, cx + r * 1.6, cy + r * 1.6), fill=(255, 230, 150, 70))
    gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 240, 190, 235))
    glow = glow.filter(ImageFilter.GaussianBlur(max(1, w // 400)))
    img.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, title_size)
    text = "WWHD"
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2 + 3, h * 0.66 + 3), text, font=f, fill=(4, 20, 60))
    d.text(((w - tw) / 2, h * 0.66), text, font=f, fill=(255, 236, 160))
    if sub:
        fs = ImageFont.truetype(FONT, title_size // 3)
        sw = d.textlength(sub, font=fs)
        d.text(((w - sw) / 2, h * 0.66 + title_size * 1.1), sub, font=fs, fill=(220, 240, 255))
    return img


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    card(512, 512, 120, "PS4").save(os.path.join(out, "icon0.png"))
    card(1920, 1080, 200, "homebrew").save(os.path.join(out, "pic1.png"))
    card(256, 256, 60, "").save(os.path.join(out, "maker.ico"), sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])


if __name__ == "__main__":
    main()
