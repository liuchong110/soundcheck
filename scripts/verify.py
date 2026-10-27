#!/usr/bin/env python3
"""Self-test for soundcheck: proves the numbers, not just the plumbing.

Run:  python scripts/verify.py
Needs ffmpeg on PATH for the independent meter and the media fixtures.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import soundcheck as sc  # noqa: E402

FF = shutil.which("ffmpeg")

results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + ("  -- " + detail if detail else ""))


def run(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def ebur128(path):
    """Independent loudness meter: ffmpeg's EBU R128, not our own code."""
    p = run(FF, "-hide_banner", "-nostats", "-i", str(path),
            "-filter_complex", "ebur128=peak=true", "-f", "null", "-")
    txt = p.stderr
    i = re.findall(r"I:\s*(-?\d+\.\d+)\s*LUFS", txt)
    tp = re.findall(r"Peak:\s*(-?\d+\.\d+)\s*dBFS", txt)
    return (float(i[-1]) if i else None, float(tp[-1]) if tp else None)


def fixture(tmp: Path, name: str, *args):
    out = tmp / name
    p = run(FF, "-v", "error", "-y", *args, str(out))
    if p.returncode != 0:
        raise RuntimeError("fixture %s failed: %s" % (name, p.stderr[-300:]))
    return out


def main() -> int:
    if not FF:
        print("ffmpeg not found on PATH; cannot run the full self-test")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="soundcheck_verify_"))
    try:
        # 1. demo is a genuine worst case
        demo = tmp / "demo.wav"
        sc.make_demo(str(demo))
        x, sr = sc.load_audio(str(demo))
        res = sc.analyze(x, sr, "youtube")
        failed = [k for k, v in res["tells"].items() if not v["ok"]]
        check("demo scores as a bad mix", 25 <= res["score"] <= 50, "score=%d" % res["score"])
        check("demo fails loudness, peak, sibilance, mud",
              {"loudness", "true_peak", "sibilance", "mud"} <= set(failed), ",".join(failed))

        # 2. our own meters agree with ffmpeg's EBU R128
        i_ext, tp_ext = ebur128(demo)
        check("our LUFS matches ffmpeg ebur128", abs(i_ext - res["lufs"]) <= 0.6,
              "ours=%.1f ffmpeg=%.1f" % (res["lufs"], i_ext))
        check("our true peak is within 1 dB of ffmpeg",
              abs(tp_ext - res["true_peak"]) <= 1.0,
              "ours=%.1f ffmpeg=%.1f" % (res["true_peak"], tp_ext))

        # 3. fix lands on spec and says so
        fixed = tmp / "fixed.wav"
        rc = sc.main(["fix", str(demo), "--target", "youtube", "--out", str(fixed)])
        xf, srf = sc.load_audio(str(fixed))
        resf = sc.analyze(xf, srf, "youtube")
        bad = [k for k, v in resf["tells"].items() if not v["ok"]]
        check("fix exits 0 only when every tell passes", rc == 0 and not bad,
              "rc=%s remaining=%s" % (rc, ",".join(bad) or "none"))
        check("fix reaches a broadcast-ready score", resf["score"] >= 90, "score=%d" % resf["score"])

        # 4. independent meter confirms the delivered file, not our own claim
        i_ext, tp_ext = ebur128(fixed)
        check("delivered loudness verified independently", abs(i_ext - (-14.0)) <= 0.7,
              "ffmpeg I=%.1f LUFS" % i_ext)
        check("delivered true peak verified independently", tp_ext <= -1.0,
              "ffmpeg TP=%.1f dBFS" % tp_ext)

        # 5. dynamics are not squashed to hit the number (LRA is meaningless under ~4 LU)
        if res["lra"] >= 4.0:
            check("fix keeps some dynamics", resf["lra"] >= 0.5 * res["lra"],
                  "LRA %.1f -> %.1f" % (res["lra"], resf["lra"]))
        else:
            check("fix keeps some dynamics", True, "skipped: source LRA %.1f LU too short to judge" % res["lra"])

        # 5b. drift must catch glued takes, and ignore even takes / a gradual swell
        sr_t = 48000
        seg = int(2 * sr_t)
        gap = np.zeros(int(0.4 * sr_t))
        tone = lambda a: a * np.sin(2 * np.pi * 600 * np.arange(seg) / sr_t)  # noqa: E731

        def takes(gains):
            parts = []
            for g in gains:
                parts += [tone(g), gap]
            s = np.concatenate(parts[:-1])
            return np.stack([s, s], 1)

        glued = takes([0.05, 0.4, 0.03, 0.4])
        even = takes([0.2, 0.2, 0.2, 0.2])
        t = np.arange(int(8 * sr_t)) / sr_t
        swell = np.sin(2 * np.pi * 600 * t) * (10 ** (np.linspace(-30, -6, len(t)) / 20))
        swell = np.stack([swell, swell], 1)

        check("glued takes are flagged as drift", sc.segment_drift(glued, sr_t) > 8.0,
              "%.1f dB" % sc.segment_drift(glued, sr_t))
        check("even takes are not drift", sc.segment_drift(even, sr_t) < 1.0,
              "%.1f dB" % sc.segment_drift(even, sr_t))
        check("a gradual swell is not drift", sc.segment_drift(swell, sr_t) < 3.0,
              "%.1f dB" % sc.segment_drift(swell, sr_t))

        # 6. degenerate inputs must not crash
        cases = {
            "silence": ("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1"),
            "very short": ("-f", "lavfi", "-i", "sine=frequency=440", "-t", "0.3"),
            "mono 24-bit": ("-f", "lavfi", "-i", "sine=frequency=300", "-t", "2",
                            "-ac", "1", "-c:a", "pcm_s24le"),
        }
        for name, args in cases.items():
            try:
                f = fixture(tmp, name.replace(" ", "_") + ".wav", *args)
                x, sr = sc.load_audio(str(f))
                r = sc.analyze(x, sr, "youtube")
                if name == "silence":
                    check("silence is rejected, not scored as fine",
                          r["score"] == 0 and r["label"] == "silent", "score=%d" % r["score"])
                elif name == "very short":
                    check("short clip is flagged",
                          any("shorter than 1s" in w for w in r["warnings"]),
                          str(r["warnings"][:1]))
                else:
                    check("handles %s" % name, True, "score=%d ch=%d" % (r["score"], r["channels"]))
            except SystemExit as e:
                check("handles %s" % name, False, "SystemExit %s" % e)
            except Exception as e:  # noqa: BLE001
                check("handles %s" % name, False, repr(e))

        # 7. container input goes through the ffmpeg decode path
        try:
            mp4 = tmp / "clip.mp4"
            p = run(FF, "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(mp4))
            if p.returncode != 0:
                p = run(FF, "-v", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440",
                        "-t", "2", "-c:v", "mpeg4", "-c:a", "aac", str(mp4))
            x, sr = sc.load_audio(str(mp4))
            r = sc.analyze(x, sr, "youtube")
            check("analyzes an mp4 (decode path)", sr == 48000, "sr=%d" % sr)
        except Exception as e:  # noqa: BLE001
            check("analyzes an mp4 (decode path)", False, repr(e))

        # 8. failure is loud, not silent
        p = run(sys.executable, str(HERE / "soundcheck.py"), "analyze", str(tmp / "nope.wav"))
        check("missing file fails loudly", p.returncode != 0 and "no such file" in (p.stdout + p.stderr).lower(),
              "rc=%d" % p.returncode)

        # 9. spec compliance: analyze exits non-zero on a failing mix
        p = run(sys.executable, str(HERE / "soundcheck.py"), "analyze", str(demo), "--json")
        j = json.loads(p.stdout)
        check("analyze signals failure via exit code", p.returncode == 1 and j["score"] < 85,
              "rc=%d score=%d" % (p.returncode, j["score"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in results if not r[1]]
    print("\n%d/%d checks passed" % (len(results) - len(failed), len(results)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
