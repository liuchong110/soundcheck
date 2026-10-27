#!/usr/bin/env python3
"""Render the 1280x640 social preview (GitHub Settings -> Social preview)."""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "social-preview.png"
W, H = 1280, 640

BG_TOP, BG_BOT = (9, 13, 18), (15, 22, 31)
INK = (236, 241, 246)
MUTED = (138, 148, 166)
GREEN = (61, 220, 151)
RED = (255, 107, 107)
CARD = (18, 24, 33)
LINE = (38, 48, 62)

BOLD = "C:/Windows/Fonts/segoeuib.ttf"
SANS = "C:/Windows/Fonts/segoeui.ttf"
MONO = "C:/Windows/Fonts/consolab.ttf"


def font(path, size):
    return ImageFont.truetype(path, size)


def waveform(path, width, height):
    ff = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    x = np.frombuffer(ff, "<f4")
    if not x.size:
        return np.zeros(width)
    x = x / max(float(np.max(np.abs(x))), 1e-9)
    edges = np.linspace(0, len(x), width + 1).astype(int)
    peaks = np.array([np.max(np.abs(x[a:b])) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    return peaks * (height / 2)


def main():
    # background gradient
    bg = Image.new("RGB", (W, H))
    px = bg.load()
    for y in range(H):
        t = y / (H - 1)
        px_row = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = px_row
    img = bg
    d = ImageDraw.Draw(img)

    # faint dot grid
    for gy in range(40, H, 40):
        for gx in range(40, W, 40):
            d.point((gx, gy), fill=(22, 30, 40))

    # title
    d.text((72, 64), "soundcheck", font=font(BOLD, 78), fill=INK)
    d.text((76, 168), "Your AI video sounds AI.", font=font(SANS, 34), fill=INK)
    d.text((76, 212), "7 tells, one deterministic fix, then verify.", font=font(SANS, 28), fill=MUTED)

    # chips
    chips = ["7 AI audio tells", "measure, fix, verify", "20/20 self-test"]
    x = 76
    for label in chips:
        f = font(SANS, 21)
        tw = d.textlength(label, font=f)
        box = [x, 268, x + tw + 32, 312]
        d.rounded_rectangle(box, radius=22, fill=(20, 28, 38), outline=LINE)
        d.text((x + 16, 277), label, font=f, fill=(190, 200, 214))
        x = box[2] + 12

    # score card
    card = [700, 92, 1208, 392]
    d.rounded_rectangle(card, radius=18, fill=CARD, outline=LINE, width=2)
    d.text((732, 118), "BEFORE", font=font(MONO, 18), fill=MUTED)
    d.text((732, 142), "48", font=font(BOLD, 76), fill=RED)
    d.text((822, 186), "/100", font=font(SANS, 26), fill=MUTED)
    d.text((732, 228), "sounds AI", font=font(SANS, 24), fill=RED)

    d.line([(732, 274), (1176, 274)], fill=LINE, width=2)
    d.text((732, 292), "AFTER", font=font(MONO, 18), fill=MUTED)
    d.text((732, 314), "100", font=font(BOLD, 56), fill=GREEN)
    d.text((846, 336), "/100", font=font(SANS, 22), fill=MUTED)
    d.text((940, 346), "broadcast-ready", font=font(SANS, 22), fill=GREEN)

    d.text((76, 356), "Video in, video out. Verified, not vibes.",
           font=font(SANS, 22), fill=MUTED)

    # waveform
    peaks = waveform(HERE.parent / "drama_neural_fixed.mp4", W - 144, 96)
    base = 470
    for i, p in enumerate(peaks):
        xx = 72 + i
        d.line([(xx, base - p), (xx, base + p)], fill=(28, 92, 68), width=1)
    for i, p in enumerate(peaks):
        xx = 72 + i
        if p > 6:
            d.line([(xx, base - p * 0.55), (xx, base + p * 0.55)], fill=(44, 150, 108), width=1)

    # install line
    d.text((72, 580), "npx skills add liuchong110/soundcheck", font=font(MONO, 22), fill=(200, 210, 224))
    url = "github.com/liuchong110/soundcheck"
    f = font(SANS, 20)
    d.text((W - 72 - d.textlength(url, font=f), 583), url, font=f, fill=MUTED)

    img.save(OUT, optimize=True)
    print("wrote", OUT, img.size)


if __name__ == "__main__":
    main()
