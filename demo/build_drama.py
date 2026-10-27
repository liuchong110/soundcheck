#!/usr/bin/env python3
"""Build a short-drama style test clip locally: Chinese TTS dialogue + BGM, mastered hot.

No third-party media: voices come from Windows SAPI (zh-CN), music is synthesised.
This is a stand-in for a 短剧/OTT delivery so the drama profile can be verified.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import soundcheck as sc  # noqa: E402

FF = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or r"C:\ffmpeg\bin\ffmpeg.exe"
FP = os.environ.get("FFPROBE") or shutil.which("ffprobe") or r"C:\ffmpeg\bin\ffprobe.exe"


def run(*a):
    p = subprocess.run(a, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit("failed: %s\n%s" % (" ".join(a), p.stderr[-800:]))
    return p


def probe(path):
    out = run(FP, "-v", "error", "-show_entries", "stream=sample_rate,channels",
              "-of", "json", str(path)).stdout
    s = json.loads(out)["streams"][0]
    d = float(run(FP, "-v", "error", "-show_entries", "format=duration",
                  "-of", "csv=p=0", str(path)).stdout.strip())
    return int(s["sample_rate"]), int(s["channels"]), d


lines = sorted(HERE.glob("line_*.wav"))
sr, ch, _ = probe(lines[0])
sil = HERE / "silence.wav"
run(FF, "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=%d:cl=%s" % (sr, "mono" if ch == 1 else "stereo"),
    "-t", "0.35", "-c:a", "pcm_s16le", str(sil))

seq = []
for ln in lines:
    seq += [ln, sil]
seq = seq[:-1]
lst = HERE / "concat.txt"
lst.write_text("\n".join("file '%s'" % str(p).replace("\\", "/") for p in seq), encoding="utf-8")
voice = HERE / "voice.wav"
run(FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(voice))
_, _, dur = probe(voice)
print("dialogue: %.2fs at %d Hz %d ch" % (dur, sr, ch))

bgm = HERE / "bgm.wav"
run(FF, "-v", "error", "-y",
    "-f", "lavfi", "-i", "sine=frequency=55:duration=%.3f" % dur,
    "-f", "lavfi", "-i", "sine=frequency=110:duration=%.3f" % dur,
    "-f", "lavfi", "-i", "sine=frequency=164.81:duration=%.3f" % dur,
    "-filter_complex",
    "[0][1][2]amix=inputs=3:normalize=0,tremolo=f=1.8:d=0.55,lowpass=f=900,volume=0.5[bgm]",
    "-map", "[bgm]", "-ar", str(sr), "-ac", str(ch), str(bgm))

mix = HERE / "mix.wav"
run(FF, "-v", "error", "-y", "-i", str(voice), "-i", str(bgm),
    "-filter_complex",
    "[0:a]volume=1.0[vo];[1:a]volume=0.85[bg];[vo][bg]amix=inputs=2:normalize=0:duration=longest[m]",
    "-map", "[m]", "-ar", "48000", "-ac", "2", str(mix))

x, r = sc.load_audio(str(mix))
cur = sc.integrated_lufs(x, r)
gain = -10.0 - cur          # the way a short-drama master is usually pushed
print("mix %.1f LUFS -> gain %+.1f dB" % (cur, gain))

before = HERE / "drama_before.wav"
run(FF, "-v", "error", "-y", "-i", str(mix),
    "-af", "volume=%.2fdB,alimiter=limit=0.95:level=false" % gain,
    "-ar", "48000", "-ac", "2", str(before))

D = probe(before)[2]
video = HERE.parent / "drama_sample.mp4"
run(FF, "-v", "error", "-y",
    "-f", "lavfi", "-i", "color=c=0x11161f:s=540x960:r=25:d=%.3f" % D,
    "-i", str(before),
    "-vf", "noise=alls=6:allf=t+u,format=yuv420p",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
    "-c:a", "aac", "-b:a", "192k", "-shortest", str(video))
print("wrote", video)
