#!/usr/bin/env python3
"""Same scene, but with neural (Edge) voices instead of Windows SAPI.

Proves the point: most of the "AI sound" lives in the source voice, not the master.
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import soundcheck as sc  # noqa: E402

FF = r"C:\ffmpeg\bin\ffmpeg.exe"
FP = r"C:\ffmpeg\bin\ffprobe.exe"

LINES = [
    ("zh-CN-XiaoxiaoNeural", "你终于来了。", "-6%", "-2Hz"),
    ("zh-CN-YunxiNeural", "三年了，你一点都没变。", "-10%", "-4Hz"),
    ("zh-CN-XiaoxiaoNeural", "有些事，变了就是变了。", "-2%", "+0Hz"),
    ("zh-CN-YunxiNeural", "那这个孩子……", "-14%", "-6Hz"),
    ("zh-CN-XiaoxiaoNeural", "他不是你的。", "-12%", "-3Hz"),
    ("zh-CN-YunxiNeural", "你说什么？", "+4%", "+2Hz"),
]


def run(*a):
    p = subprocess.run(a, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit("failed: %s\n%s" % (" ".join(a), p.stderr[-800:]))
    return p


def dur(path):
    return float(run(FP, "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(path)).stdout.strip())


async def synth():
    import edge_tts
    raw = HERE / "neural_raw"
    raw.mkdir(exist_ok=True)
    outs = []
    for i, (voice, text, rate, pitch) in enumerate(LINES):
        mp3 = raw / ("n%d.mp3" % i)
        await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(mp3))
        wav = raw / ("n%d.wav" % i)
        run(FF, "-v", "error", "-y", "-i", str(mp3), "-ar", "48000", "-ac", "1", str(wav))
        outs.append(wav)
        print("line %d %s %.2fs" % (i, voice.split("-")[2], dur(wav)))
    return outs


def main():
    files = asyncio.run(synth())
    sil = HERE / "neural_raw" / "gap.wav"
    run(FF, "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.35",
        "-c:a", "pcm_s16le", str(sil))
    seq = []
    for f in files:
        seq += [f, sil]
    lst = HERE / "neural_raw" / "concat.txt"
    lst.write_text("\n".join("file '%s'" % str(p).replace("\\", "/") for p in seq[:-1]), encoding="utf-8")
    voice = HERE / "neural_raw" / "voice.wav"
    run(FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(voice))
    D = dur(voice)
    print("dialogue %.2fs" % D)

    bgm = HERE / "neural_raw" / "bgm.wav"
    run(FF, "-v", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=55:duration=%.3f" % D,
        "-f", "lavfi", "-i", "sine=frequency=110:duration=%.3f" % D,
        "-f", "lavfi", "-i", "sine=frequency=164.81:duration=%.3f" % D,
        "-filter_complex",
        "[0][1][2]amix=inputs=3:normalize=0,tremolo=f=1.8:d=0.55,lowpass=f=900,volume=0.5[bgm]",
        "-map", "[bgm]", "-ar", "48000", "-ac", "2", str(bgm))

    mix = HERE / "neural_raw" / "mix.wav"
    run(FF, "-v", "error", "-y", "-i", str(voice), "-i", str(bgm),
        "-filter_complex",
        "[0:a]volume=1.0[vo];[1:a]volume=0.5[bg];[vo][bg]amix=inputs=2:normalize=0:duration=longest[m]",
        "-map", "[m]", "-ar", "48000", "-ac", "2", str(mix))

    x, r = sc.load_audio(str(mix))
    gain = -10.0 - sc.integrated_lufs(x, r)
    before = HERE / "neural_raw" / "before.wav"
    run(FF, "-v", "error", "-y", "-i", str(mix),
        "-af", "volume=%.2fdB,alimiter=limit=0.95:level=false" % gain,
        "-ar", "48000", "-ac", "2", str(before))

    out = HERE.parent / "drama_neural.mp4"
    run(FF, "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x11161f:s=540x960:r=25:d=%.3f" % dur(before),
        "-i", str(before),
        "-vf", "noise=alls=6:allf=t+u,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-c:a", "aac", "-b:a", "192k", "-shortest", str(out))
    print("wrote", out)


if __name__ == "__main__":
    main()
