#!/usr/bin/env python3
"""Render the 25 s launch demo: same clip, unmastered vs soundcheck, level-matched."""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
import soundcheck as sc  # noqa: E402

W, H, FPS = 1280, 720, 25
DUR = 25.0
SR = 48000

BG_TOP, BG_BOT = (9, 13, 18), (15, 22, 31)
INK, MUTED = (236, 241, 246), (138, 148, 166)
GREEN, RED = (61, 220, 151), (255, 107, 107)
LINE = (38, 48, 62)
BOLD = "C:/Windows/Fonts/segoeuib.ttf"
SANS = "C:/Windows/Fonts/segoeui.ttf"
MONO = "C:/Windows/Fonts/consolab.ttf"


def F(p, s):
    return ImageFont.truetype(p, s)


def base_image():
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)))
    for gy in range(40, H, 40):
        for gx in range(40, W, 40):
            d.point((gx, gy), fill=(22, 30, 40))
    return img


def smooth(peaks, k=2):
    if k <= 1:
        return peaks
    return np.convolve(peaks, np.ones(k) / k, mode="same")


def envelope(x, width, height):
    mono = np.abs(x.mean(axis=1))
    edges = np.linspace(0, len(mono), width + 1).astype(int)
    peaks = np.array([mono[a:b].max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    peaks = smooth(peaks / max(peaks.max(), 1e-9), 3)
    return peaks * (height * 0.46)


def wave_layer(peaks, color):
    img = Image.new("RGBA", (len(peaks), 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, p in enumerate(peaks):
        d.line([(i, 100 - p), (i, 100 + p)], fill=color + (255,), width=1)
    return img


def section_base(kind, score, verdict, metrics, caption, tags=()):
    img = base_image()
    d = ImageDraw.Draw(img)
    color = RED if kind == "BEFORE" else GREEN
    d.text((64, 58), kind, font=F(MONO, 20), fill=MUTED)
    d.text((64, 88), str(score), font=F(BOLD, 104), fill=color)
    sw = d.textlength(str(score), font=F(BOLD, 104))
    d.text((64 + sw + 14, 152), "/100", font=F(SANS, 28), fill=MUTED)
    d.text((64, 214), verdict, font=F(SANS, 28), fill=color)
    for i, line in enumerate(metrics):
        tw = d.textlength(line, font=F(MONO, 19))
        d.text((W - 64 - tw, 62 + i * 28), line, font=F(MONO, 19), fill=MUTED)
    x = 64
    for tag in tags:
        fnt = F(SANS, 20)
        tw = d.textlength(tag, font=fnt)
        d.rounded_rectangle([x, 266, x + tw + 28, 308], radius=21, outline=color, width=1)
        d.text((x + 14, 275), tag, font=fnt, fill=color)
        x += tw + 40
    d.text((64, 645), caption, font=F(SANS, 20), fill=MUTED)
    return img


def intro_base():
    img = base_image()
    d = ImageDraw.Draw(img)
    d.text((64, 140), "soundcheck", font=F(BOLD, 84), fill=INK)
    d.text((68, 258), "Your AI video sounds AI.", font=F(SANS, 38), fill=INK)
    d.text((68, 312), "One command measures it, fixes what is measurable, and re-checks.",
           font=F(SANS, 24), fill=MUTED)
    d.text((68, 348), "Same 15 s clip. Level-matched A/B. No model in the loop.",
           font=F(SANS, 22), fill=(96, 106, 122))
    return img


def outro_base():
    img = base_image()
    d = ImageDraw.Draw(img)
    d.text((64, 250), "npx skills add liuchong110/soundcheck", font=F(MONO, 34), fill=INK)
    d.text((64, 312), "20/20 self-test  ·  CI green  ·  MIT  ·  video in, video out",
           font=F(SANS, 24), fill=MUTED)
    d.text((64, 366), "github.com/liuchong110/soundcheck", font=F(MONO, 22), fill=(96, 106, 122))
    return img


def main():
    src = ROOT / "drama_neural.mp4"
    fix = HERE / "neural_youtube_master.mp4"
    xa, sr = sc.load_audio(str(src))
    xb, _ = sc.load_audio(str(fix))
    start = int(1.2 * sr)
    n = int(8.5 * sr)
    A = xa[start:start + n].copy()
    B = xb[start:start + n].copy()

    ga = 10 ** ((-14.0 - sc.integrated_lufs(A, sr)) / 20.0)
    gb = 10 ** ((-14.0 - sc.integrated_lufs(B, sr)) / 20.0)
    A *= ga
    B *= gb
    for sig in (A, B):                       # 20 ms edges, no clicks
        k = int(0.02 * sr)
        env = np.ones(len(sig))
        env[:k] = np.linspace(0, 1, k)
        env[-k:] = np.linspace(1, 0, k)
        sig *= env[:, None]

    total = np.zeros((int(DUR * sr), 2))
    def put(sig, at):
        i = int(at * sr)
        total[i:i + len(sig)] += sig[:len(total) - i]
    put(A, 2.5)
    put(B, 13.0)

    wav = HERE / "demo_audio.wav"
    sc.write_wav(str(wav), np.clip(total, -1, 1), sr)

    peaks = envelope(B, 1152, 200)
    dim = wave_layer(peaks, (45, 55, 66))
    bright_b = wave_layer(peaks, GREEN)
    bright_a = wave_layer(peaks, (200, 90, 90))

    i_img = intro_base()
    a_img = section_base("BEFORE", 64, "sounds AI",
                         ["-11.8 LUFS", "TP -0.3 dBTP", "mud 1.13"],
                         "The raw export: hot, clipped, muddy. Level-matched for a fair A/B.",
                         ("too loud", "clipping", "muddy"))
    b_img = section_base("AFTER", 98, "broadcast-ready",
                         ["-14.4 LUFS", "TP -1.8 dBTP", "mud 0.40"],
                         "After soundcheck: -14 LUFS, no clipping, mud under control.",
                         ("on spec", "no clipping", "clean"))
    o_img = outro_base()

    frames = int(DUR * FPS)
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
           "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
           str(HERE / "demo-ab.mp4")]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for f in range(frames):
        t = f / FPS
        if t < 2.5:
            img = i_img.copy()
        elif t < 11.0:
            img = a_img.copy()
            prog = (t - 2.5) / 8.5
            pw = int(1152 * prog)
            img.paste(dim, (64, 400), dim)
            if pw > 0:
                img.paste(bright_a.crop((0, 0, pw, 200)), (64, 400), bright_a.crop((0, 0, pw, 200)))
            d = ImageDraw.Draw(img)
            d.line([(64 + pw, 400), (64 + pw, 600)], fill=(120, 132, 148), width=1)
        elif t < 13.0:
            img = base_image()
            d = ImageDraw.Draw(img)
            prog = (t - 11.0) / 2.0
            cmd_txt = "soundcheck fix clip.mp4 --target youtube"
            shown = cmd_txt[: max(1, int(len(cmd_txt) * min(1.0, prog * 1.6)))]
            d.text((64, 300), "$ " + shown, font=F(MONO, 30), fill=INK)
            d.rectangle([64, 370, 1216, 378], outline=LINE)
            d.rectangle([64, 370, 64 + int(1152 * prog), 378], fill=GREEN)
            d.text((64, 400), "measure → correct → re-measure", font=F(SANS, 22), fill=MUTED)
        elif t < 21.5:
            img = b_img.copy()
            prog = (t - 13.0) / 8.5
            pw = int(1152 * prog)
            img.paste(dim, (64, 400), dim)
            if pw > 0:
                img.paste(bright_b.crop((0, 0, pw, 200)), (64, 400), bright_b.crop((0, 0, pw, 200)))
            d = ImageDraw.Draw(img)
            d.line([(64 + pw, 400), (64 + pw, 600)], fill=(120, 132, 148), width=1)
        else:
            img = o_img.copy()
        p.stdin.write(img.tobytes())

    p.stdin.close()
    p.wait()
    if p.returncode != 0:
        raise SystemExit("ffmpeg failed")
    print("wrote", HERE / "demo-ab.mp4")


if __name__ == "__main__":
    main()
