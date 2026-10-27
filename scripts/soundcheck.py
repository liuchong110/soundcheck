#!/usr/bin/env python3
"""soundcheck - measure and fix the "AI sound" of generated video / voiceover / podcast audio.

Pure-Python analysis (numpy + optional scipy) so it runs anywhere.
Fixing uses ffmpeg when available.

Commands:
  analyze FILE [--target youtube] [--music STEM] [--json]
  fix     FILE [--target youtube] [--music STEM] [--out PATH] [--level] [--no-verify]
  demo    [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

try:
    from scipy.signal import lfilter, resample_poly  # type: ignore
    HAVE_SCIPY = True
except Exception:  # pragma: no cover
    HAVE_SCIPY = False

TARGETS = {
    "youtube":   (-14.0, -1.0, "streaming"),
    "tiktok":    (-14.0, -1.0, "streaming"),
    "reels":     (-14.0, -1.0, "streaming"),
    "spotify":   (-14.0, -1.0, "streaming"),
    "apple":     (-16.0, -1.0, "streaming"),
    "podcast":   (-16.0, -1.0, "podcast"),
    "podcast-mono": (-19.0, -1.0, "podcast"),
    "broadcast": (-23.0, -1.0, "broadcast"),
    "drama":     (-24.0, -1.0, "ott"),
    "cinema":    (-27.0, -2.0, "cinema"),
}

# ----------------------------------------------------------------------------- io

def read_wav(path: str):
    """RIFF reader that also understands WAVE_FORMAT_EXTENSIBLE.

    Python's stdlib wave module rejects extensible headers ("unknown format: 65534"),
    which is what ffmpeg on Linux writes for 24-bit / multichannel PCM.
    """
    buf = Path(path).read_bytes()
    if buf[:4] != b"RIFF" or buf[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file: %s" % path)
    fmt = None
    raw = None
    pos = 12
    while pos + 8 <= len(buf):
        cid = buf[pos:pos + 4]
        size = int.from_bytes(buf[pos + 4:pos + 8], "little")
        body = buf[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None or len(fmt) < 16:
        raise ValueError("incomplete RIFF file: %s" % path)

    tag, nch, sr, _rate, _align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 26:          # extensible: real format in the GUID
        tag = struct.unpack("<H", fmt[24:26])[0]
    if tag != 1:                                   # 1 = integer PCM; 3 = float, unsupported here
        raise ValueError("unsupported WAV format tag: %s" % tag)
    sw = bits // 8

    if sw == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float64) - 128.0) / 128.0
    elif sw == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float64) / 32768.0
    elif sw == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v >= (1 << 23), v - (1 << 24), v)
        x = v.astype(np.float64) / float(1 << 23)
    elif sw == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float64) / 2147483648.0
    else:
        raise SystemExit("unsupported wav sample width: %s" % sw)
    return x.reshape(-1, nch), sr


def load_audio(path: str):
    p = Path(path)
    if p.suffix.lower() == ".wav":
        try:
            return read_wav(str(p))
        except Exception:
            pass  # float / exotic WAV: let ffmpeg normalise it below
    ff = shutil.which("ffmpeg")
    if not ff:
        raise SystemExit("need ffmpeg to decode %s (or convert to wav first)" % p.suffix)
    tmp = Path(tempfile.mkdtemp(prefix="soundcheck_")) / "in.wav"
    subprocess.run([ff, "-v", "error", "-y", "-i", str(p), "-ac", "2", "-ar", "48000",
                    "-c:a", "pcm_s16le", str(tmp)], check=True)
    return read_wav(str(tmp))


def write_wav(path: str, x: np.ndarray, sr: int):
    y = np.clip(x, -1.0, 1.0)
    pcm = (y * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())

# ------------------------------------------------------------------------ filters

def _biquad(x, b, a):
    if HAVE_SCIPY:
        return lfilter(b, a, x, axis=0)
    y = np.empty_like(x)
    for ch in range(x.shape[1]):
        xc = x[:, ch]
        yc = np.empty_like(xc)
        x1 = x2 = y1 = y2 = 0.0
        for i in range(len(xc)):
            v = b[0] * xc[i] + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2
            yc[i] = v
            x2, x1 = x1, xc[i]
            y2, y1 = y1, v
        y[:, ch] = yc
    return y


def k_weight(x, sr):
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10.0 ** (G / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / Q + K * K
    b1 = [(Vh + Vb * K / Q + K * K) / a0, 2.0 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a1 = [1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    a0 = 1.0 + K / Q + K * K
    b2 = [1.0 / a0, -2.0 / a0, 1.0 / a0]
    a2 = [1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    return _biquad(_biquad(x, b1, a1), b2, a2)

# ------------------------------------------------------------------------ metrics

def integrated_lufs(x, sr):
    y = k_weight(x, sr)
    block, hop = int(0.4 * sr), int(0.1 * sr)
    if len(y) < block:
        # shorter than one gating block: measure the whole clip as a single block
        ms = float(np.mean(y ** 2, axis=0).sum())
        return float(-0.691 + 10.0 * math.log10(max(ms, 1e-12)))
    starts = range(0, len(y) - block + 1, hop)
    # sum channel mean-squares (BS.1770): stereo dual-mono must read 3 dB louder than mono
    ms = np.array([float(np.mean(y[i:i + block] ** 2, axis=0).sum()) for i in starts])
    with np.errstate(divide="ignore"):
        l = -0.691 + 10.0 * np.log10(np.maximum(ms, 1e-12))
    ok = l > -70.0
    if not ok.any():
        return -70.0
    rel = -0.691 + 10.0 * np.log10(max(float(np.mean(ms[ok])), 1e-12)) - 10.0
    gated = ms[ok & (l > rel)]
    if gated.size == 0:
        gated = ms[ok]
    return float(-0.691 + 10.0 * np.log10(max(float(np.mean(gated)), 1e-12)))


def true_peak(x, sr):
    if HAVE_SCIPY:
        up = resample_poly(x, 4, 1, axis=0)
    else:
        t = np.arange(len(x))
        up = np.stack([np.interp(np.linspace(0, len(x) - 1, len(x) * 4), t, x[:, c]) for c in range(x.shape[1])], 1)
    peak = float(np.max(np.abs(up))) if up.size else 0.0
    return 20.0 * math.log10(max(peak, 1e-9))


def short_term_lra(x, sr):
    block, hop = int(3.0 * sr), int(1.0 * sr)
    if len(x) < block:
        return 0.0
    vals = [integrated_lufs(x[i:i + block], sr) for i in range(0, len(x) - block + 1, hop)]
    vals = [v for v in vals if v > -70]
    if len(vals) < 3:
        return 0.0
    return float(np.percentile(vals, 95) - np.percentile(vals, 10))


def spectrum_stats(x, sr):
    mono = x.mean(axis=1) if x.shape[1] > 1 else x[:, 0]
    n = 4096
    if len(mono) < n:
        mono = np.pad(mono, (0, n - len(mono)))
    win = np.hanning(n)
    frames = [mono[i:i + n] * win for i in range(0, len(mono) - n + 1, n // 2)]
    if not frames:
        frames = [np.pad(mono, (0, n - len(mono))) * win]
    spec = np.mean([np.abs(np.fft.rfft(f)) ** 2 for f in frames], axis=0)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)

    def band(a, b):
        # energy sum: independent of how many bins the band happens to contain
        m = (freqs >= a) & (freqs < b)
        return float(np.sum(spec[m])) if m.any() else 0.0

    sib = band(5000, 9000) / max(band(1000, 4000), 1e-12)
    mud = band(100, 300) / max(band(300, 3000), 1e-12)
    return {"sibilance": sib, "mud": mud, "low": band(20, 100), "high": band(9000, 16000)}


def noise_floor_db(x, sr, lufs):
    """Noise floor only means something when there is a real silent passage.

    Quiet music is not noise. We look for frames at least 50 dB below program
    loudness; if the material has none, the answer is "cannot assess", not a pass.
    """
    n = max(int(0.02 * sr), 1)
    mono = x.mean(axis=1)
    frames = [mono[i:i + n] for i in range(0, len(mono) - n + 1, n)]
    rms_db = np.array([20.0 * math.log10(max(float(np.sqrt(np.mean(f ** 2))), 1e-9)) for f in frames])
    quiet = rms_db[rms_db < (lufs - 50.0)]
    if quiet.size < max(3, int(0.02 * len(rms_db))):
        return None
    return float(np.median(quiet))


def stereo_corr(x):
    if x.shape[1] < 2:
        return 1.0
    l, r = x[:, 0], x[:, 1]
    d = math.sqrt(float(np.mean(l ** 2)) * float(np.mean(r ** 2))) + 1e-12
    return float(np.mean(l * r) / d)


def _speech_regions(x, sr):
    """Split the take into spoken regions using speech-band energy.

    Returns [(start_sample, end_sample, level_db)]. Regions shorter than 0.3 s apart
    are merged, because a breath inside a line is not a new take.
    """
    mono = x.mean(axis=1)
    spec = np.fft.rfft(mono)
    f = np.fft.rfftfreq(len(mono), 1.0 / sr)
    spec[(f < 300.0) | (f > 3000.0)] = 0.0
    band = np.fft.irfft(spec, len(mono))

    hop, win = int(0.02 * sr), int(0.05 * sr)
    starts = np.arange(0, len(band) - win + 1, hop)
    if starts.size < 5:
        return []
    db = np.array([20.0 * math.log10(max(float(np.sqrt(np.mean(band[i:i + win] ** 2))), 1e-9))
                   for i in starts])
    active = db > (float(np.max(db)) - 30.0)

    regs = []
    i = 0
    while i < len(active):
        if not active[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(active) and active[j + 1]:
            j += 1
        regs.append([int(starts[i]), int(starts[j]) + win])
        i = j + 1
    merged = []
    for r in regs:
        if merged and r[0] - merged[-1][1] < int(0.3 * sr):
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    out = []
    for a, b in merged:
        lvl = 20.0 * math.log10(max(float(np.sqrt(np.mean(band[a:b] ** 2))), 1e-9))
        out.append((a, b, lvl))
    return out


def segment_drift(x, sr):
    """Level mismatch between neighbouring spoken takes.

    This is deliberately not the content's dynamic range: a swell, a pause or a
    music build must not count. Only take-to-take jumps do.
    """
    regs = _speech_regions(x, sr)
    if len(regs) < 2 or len(regs) > 40:
        return 0.0
    levels = [r[2] for r in regs]
    deltas = [abs(levels[i] - levels[i - 1]) for i in range(1, len(levels))]
    return float(np.percentile(deltas, 90)) if deltas else 0.0


def drift_jumps(x, sr, top=2):
    """Where the take-to-take jumps are, so a human can go listen at that timestamp."""
    regs = _speech_regions(x, sr)
    if len(regs) < 2:
        return []
    d = [(regs[i][0] / sr, regs[i][2] - regs[i - 1][2]) for i in range(1, len(regs))]
    d.sort(key=lambda p: -abs(p[1]))
    return [(round(t, 1), round(v, 1)) for t, v in d[:top]]

# ------------------------------------------------------------------------- score

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def analyze(x, sr, target="youtube", music_lufs=None):
    t_lufs, t_tp, kind = TARGETS.get(target, TARGETS["youtube"])
    lufs = integrated_lufs(x, sr)
    tp = true_peak(x, sr)
    spec = spectrum_stats(x, sr)
    tell = {}
    pen = {}

    d = abs(lufs - t_lufs)
    tell["loudness"] = {"value": round(lufs, 1), "target": t_lufs, "ok": d <= 0.8}
    pen["loudness"] = clamp((d - 0.5) / 3.5 * 25.0, 0, 25)

    tell["true_peak"] = {"value": round(tp, 1), "target": t_tp, "ok": tp <= t_tp}
    pen["true_peak"] = clamp((tp - t_tp) / 2.5 * 20.0, 0, 20)

    sib = spec["sibilance"]
    tell["sibilance"] = {"value": round(sib, 2), "target": 0.45, "ok": sib <= 0.45}
    pen["sibilance"] = clamp((sib - 0.35) / 0.6 * 12.0, 0, 12)

    mud = spec["mud"]
    tell["mud"] = {"value": round(mud, 2), "target": 0.40, "ok": mud <= 0.40}
    pen["mud"] = clamp((mud - 0.30) / 0.6 * 10.0, 0, 10)

    drift = segment_drift(x, sr)
    tell["drift"] = {"value": round(drift, 1), "target": 3.0, "ok": drift <= 3.0}
    pen["drift"] = clamp((drift - 3.0) / 6.0 * 12.0, 0, 12)
    if not tell["drift"]["ok"]:
        jumps = drift_jumps(x, sr)
        if jumps:
            tell["drift"]["note"] = "largest jumps at " + ", ".join(
                "%.1fs (%+.1f dB)" % (t, v) for t, v in jumps)

    nf = noise_floor_db(x, sr, lufs)
    if nf is None:
        tell["noise_floor"] = {"value": None, "target": 45.0, "ok": True,
                               "note": "no silent passage, cannot separate noise from content"}
        pen["noise_floor"] = 0.0
    else:
        snr = lufs - nf
        tell["noise_floor"] = {"value": round(snr, 1), "target": 45.0, "ok": snr >= 45.0}
        pen["noise_floor"] = clamp((45.0 - snr) / 20.0 * 8.0, 0, 8)

    corr = stereo_corr(x)
    tell["phase"] = {"value": round(corr, 2), "target": 0.2, "ok": corr >= 0.2}
    pen["phase"] = clamp((0.2 - corr) / 0.8 * 6.0, 0, 6)

    if music_lufs is not None:
        gap = lufs - music_lufs
        tell["voice_music"] = {"value": round(gap, 1), "target": 4.0, "ok": gap >= 4.0}
        pen["voice_music"] = clamp((4.0 - gap) / 8.0 * 16.0, 0, 16)

    total = 100.0 - sum(pen.values())
    score = int(round(clamp(total, 0, 100)))
    label = ("broadcast-ready" if score >= 85 else "solid" if score >= 70
             else "needs work" if score >= 50 else "sounds AI")

    duration = len(x) / sr
    warnings = []

    mono = x.mean(axis=1)
    sp = np.abs(np.fft.rfft(mono)) ** 2
    fr = np.fft.rfftfreq(len(mono), 1.0 / sr)
    air = float(sp[(fr >= 8000) & (fr < 16000)].sum() / max(sp[fr < 16000].sum(), 1e-12))
    if air < 0.0005:
        warnings.append("source is band-limited: %.3f%% of its energy is above 8 kHz "
                        "(a 16/22 kHz TTS upsampled). No mastering can restore air - use a better voice."
                        % (air * 100.0))
    if lufs <= -50.0:
        score, label = 0, "silent"
        warnings.append("no usable signal (silent or near-silent) - nothing to fix")
    if duration < 1.0:
        warnings.append("clip shorter than 1s - measurements are indicative only")

    return {
        "warnings": warnings,
        "target": target,
        "profile": kind,
        "score": score,
        "label": label,
        "lufs": round(lufs, 1),
        "true_peak": round(tp, 1),
        "lra": round(short_term_lra(x, sr), 1),
        "duration_sec": round(len(x) / sr, 2),
        "sample_rate": sr,
        "channels": x.shape[1],
        "tells": tell,
        "penalties": {k: round(v, 1) for k, v in pen.items()},
    }

# --------------------------------------------------------------------------- fix

def _pre_chain(spec, deep=0):
    """Corrective EQ whose depth is driven by what we actually measured."""
    sib = spec.get("sibilance", 0.3)
    mud = spec.get("mud", 0.3)
    sib_g = -3.0 if sib <= 0.45 else -min(14.0, 3.0 + (sib - 0.45) * 12.0)
    mud_g = -2.5 if mud <= 0.40 else -min(15.0, 2.5 + (mud - 0.40) * 18.0)
    if deep:  # second pass: the first correction did not clear the tell
        sib_g -= 4.0
        mud_g -= 4.0
    return [
        "highpass=f=60",
        "lowshelf=f=260:g=%.1f" % mud_g,
        "equalizer=f=350:width_type=q:w=1.4:g=-1.5",
        "equalizer=f=7200:width_type=q:w=1.3:g=%.1f" % sib_g,
        "equalizer=f=10500:width_type=q:w=1.2:g=-1.5",
        "alimiter=limit=0.891:level=false",
    ]


def level_regions(x, sr, max_db=9.0):
    """Match the level of each spoken take, not the level of every 0.4 s window.

    Finds speech-band energy regions separated by pauses, gives each region one
    constant gain (30 ms ramps at the edges), and targets their median. Within a
    line the performance keeps its dynamics; between lines the mismatch goes away.
    Returns the input unchanged when the material does not look like separate takes.
    """
    regs = _speech_regions(x, sr)
    if len(regs) < 2 or len(regs) > 40:
        return x  # continuous material, not separate takes

    levels = [r[2] for r in regs]
    target = float(np.median(levels))
    gains_db = np.clip(target - np.array(levels), -max_db, max_db)

    gain = np.zeros(len(x))
    ramp = int(0.03 * sr)
    for (a, b, _), gdb in zip(regs, gains_db):
        gain[a:b] = gdb
        if a - ramp >= 0:
            gain[a - ramp:a] = np.linspace(0.0, gdb, ramp)
        if b + ramp <= len(x):
            gain[b:b + ramp] = np.linspace(gdb, 0.0, ramp)
    return x * (10.0 ** (gain / 20.0))[:, None]


def level_segments(x, sr, max_db=8.0):
    """Slow gain that pulls glued takes toward one level.

    Deliberately conservative: big slow moves only, clamped to +/-8 dB, and paused
    frames hold the neighbouring gain instead of amplifying room tone. Meant for
    dialogue with mismatched takes, not for music, where a swell is the point.
    """
    win, hop = int(0.4 * sr), int(0.1 * sr)
    if len(x) < win * 2:
        return x
    mono = x.mean(axis=1)
    spec = np.fft.rfft(mono)
    f = np.fft.rfftfreq(len(mono), 1.0 / sr)
    spec[(f < 300.0) | (f > 3000.0)] = 0.0
    band = np.fft.irfft(spec, len(mono))  # speech band: music beds must not drive the leveler

    starts = list(range(0, len(x) - win + 1, hop))
    levels = np.array([20.0 * math.log10(max(float(np.sqrt(np.mean(band[i:i + win] ** 2))), 1e-9))
                       for i in starts])
    active = levels > (float(np.max(levels)) - 35.0)
    if active.sum() < 3:
        return x
    target = float(np.percentile(levels[active], 60))
    gains = np.clip(target - levels, -max_db, max_db)
    idx = np.where(active)[0]
    gains = np.interp(np.arange(len(levels)), idx, gains[idx])
    k = max(int(0.35 * sr / hop), 1)
    gains = np.convolve(np.pad(gains, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    centers = np.array(starts) + win // 2
    g = np.interp(np.arange(len(x)), centers, gains)
    return x * (10.0 ** (g / 20.0))[:, None]


def naturalize_audio(x, sr, room=0.12, breath_db=-56.0):
    """Put the voice in a room and give it a floor.

    Dry, digitally silent, band-limited speech is the acoustic signature of naive TTS.
    This adds a short synthetic room, a low breath/room-tone bed and a little HF air.
    It cannot invent prosody or restore a 16 kHz source - see the band-limited warning.
    """
    rng = np.random.default_rng(3)
    n_ir = int(0.35 * sr)
    t = np.arange(n_ir) / sr
    ir = rng.normal(0, 1, n_ir) * np.exp(-t / 0.09)
    ir[: int(0.004 * sr)] = 0.0
    ir /= max(float(np.max(np.abs(ir))), 1e-9)

    n = 2 * len(x)
    wet = np.empty_like(x)
    for c in range(x.shape[1]):
        conv = np.fft.irfft(np.fft.rfft(x[:, c], n) * np.fft.rfft(ir, n))[: len(x)]
        wet[:, c] = conv
    wet /= max(float(np.max(np.abs(wet))), 1e-9)
    y = x + room * wet * float(np.max(np.abs(x)))

    # breath / room tone, plus a whisper of HF air (a 16 kHz source has none)
    noise = rng.normal(0, 1, len(x))
    spec = np.fft.rfft(noise)
    f = np.fft.rfftfreq(len(noise), 1.0 / sr)
    spec[f < 150.0] = 0.0
    noise = np.fft.irfft(spec, len(noise))
    noise /= max(float(np.max(np.abs(noise))), 1e-9)
    y = y + (10.0 ** (breath_db / 20.0)) * noise[:, None]

    hf = rng.normal(0, 1, len(x))
    hs = np.fft.rfft(hf)
    hs[f < 6000.0] = 0.0
    hf = np.fft.irfft(hs, len(hf))
    hf /= max(float(np.max(np.abs(hf))), 1e-9)
    y = y + (10.0 ** ((breath_db - 8.0) / 20.0)) * hf[:, None]
    return y


def _render(ff, src, dst, pre, target, music=None, level=False, naturalize=False):
    """One render: corrective chain -> measure -> static gain -> limiter."""
    t_lufs, _, _ = TARGETS[target]
    workdir = Path(tempfile.mkdtemp(prefix="soundcheck_"))
    try:
        tmp = workdir / "pre.wav"
        chain_src = src
        if music:
            fc = ("[0:a]%s[voice];[1:a]volume=-9dB[bed];"
                  "[bed][voice]sidechaincompress=threshold=0.04:ratio=8:attack=15:release=350[ducked];"
                  "[voice][ducked]amix=inputs=2:normalize=0[out]" % pre)
            subprocess.run([ff, "-v", "error", "-y", "-i", src, "-i", music,
                            "-filter_complex", fc, "-map", "[out]", "-ar", "48000", "-ac", "2", str(tmp)],
                           check=True)
        else:
            subprocess.run([ff, "-v", "error", "-y", "-i", chain_src, "-af", pre,
                            "-ar", "48000", "-ac", "2", str(tmp)], check=True)

        xp, srp = load_audio(str(tmp))
        if level:
            xp = level_regions(xp, srp)
        if naturalize:
            xp = naturalize_audio(xp, srp)
        if level or naturalize:
            write_wav(str(tmp), xp, srp)
        gain = t_lufs - integrated_lufs(xp, srp)
        subprocess.run([ff, "-v", "error", "-y", "-i", str(tmp),
                        "-af", "volume=%.2fdB,alimiter=limit=0.79:level=false" % gain,
                        "-ar", "48000", "-ac", "2", str(dst)], check=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}


def run_fix(src, dst, target, music=None, level=False, naturalize=False):
    """Corrective chain, static gain from our own measurement, limiter, then re-measure.

    Deliberately not loudnorm's dynamic mode: it pumps on short clips. If the first
    pass leaves sibilance or mud above target, one deeper pass is rendered from the
    original (never from the processed file, so no generation loss).

    When dst is a video container, the corrected audio is muxed back against the
    original video stream (copied, not re-encoded).
    """
    ff = shutil.which("ffmpeg")
    if not ff:
        raise SystemExit("ffmpeg not found - install it to use --fix (analysis works without it)")
    x, sr = load_audio(src)
    spec = spectrum_stats(x, sr)

    mux = Path(dst).suffix.lower() in VIDEO_EXT and Path(src).suffix.lower() in VIDEO_EXT
    workdir = Path(tempfile.mkdtemp(prefix="soundcheck_out_"))
    audio_dst = str(workdir / "master.wav") if mux else dst
    res = None
    try:
        for deep in (0, 1):
            pre = ",".join(_pre_chain(spec, deep))
            _render(ff, src, audio_dst, pre, target, music, level, naturalize)
            xa, sra = load_audio(audio_dst)
            res = analyze(xa, sra, target)
            if all(res["tells"][k]["ok"] for k in ("sibilance", "mud")):
                break
        if mux:
            subprocess.run([ff, "-v", "error", "-y", "-i", src, "-i", audio_dst,
                            "-map", "0:v:0", "-map", "1:a", "-c:v", "copy",
                            "-c:a", "aac", "-b:a", "192k", "-shortest", dst], check=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return res

# -------------------------------------------------------------------------- demo

def make_demo(path):
    sr = 48000
    dur = 9.0
    n = int(sr * dur)
    t = np.arange(n) / sr
    rng = np.random.default_rng(7)

    # "voice": formant-shaped harmonic stack + syllabic envelope + harsh sibilance bursts
    f0 = 118.0 + 4.0 * np.sin(2 * np.pi * 0.31 * t)
    phase = 2 * np.pi * np.cumsum(f0) / sr
    formants = [(650, 130, 1.0), (1150, 170, 0.75), (2500, 240, 0.55), (3600, 320, 0.35)]
    voice = np.zeros(n)
    for k in range(2, 41):
        fk = f0 * k
        gain = sum(a * np.exp(-0.5 * ((fk - f) / w) ** 2) for f, w, a in formants) + 0.02
        voice += (0.9 / k ** 0.6) * gain * np.sin(k * phase + k * 0.7)
    # three takes glued together with different gain: the classic AI segment drift
    seg_gain = np.where(t < 3.0, 0.42, np.where(t < 6.0, 1.0, 0.48))
    voice *= seg_gain
    syl = np.clip(np.sin(2 * np.pi * 4.2 * t), 0, 1) ** 0.35
    voice *= 0.35 + 0.65 * syl
    voice /= max(np.sqrt(np.mean(voice ** 2)), 1e-9)
    # sibilance: band-limited noise bursts
    noise = rng.normal(0, 1, n)
    b = np.fft.rfft(noise)
    fr = np.fft.rfftfreq(n, 1 / sr)
    b[(fr < 6000) | (fr > 10000)] = 0
    sib = np.fft.irfft(b, n)
    sib /= max(np.max(np.abs(sib)), 1e-9)
    gate = (np.sin(2 * np.pi * 4.2 * t + 0.6) > 0.45).astype(float)
    # proximity-effect boom: the other classic AI-voice tell
    boom = 0.45 * np.sin(2 * np.pi * 125 * t) * (0.4 + 0.6 * syl)
    voice = voice * 0.55 + 0.9 * sib * gate + boom

    # "music": bass-heavy bed with a 140-220 Hz mud bump, no ducking
    music = (0.22 * np.sin(2 * np.pi * 82 * t) + 0.15 * np.sin(2 * np.pi * 110 * t)
             + 0.14 * np.sin(2 * np.pi * 140 * t) + 0.11 * np.sin(2 * np.pi * 220 * t)
             + 0.09 * np.sin(2 * np.pi * 164 * t) + 0.05 * np.sin(2 * np.pi * 330 * t))
    music *= 1.0 + 0.15 * np.sin(2 * np.pi * 0.7 * t)

    mix = voice + 0.8 * music

    # inject the two remaining tells at measurable levels: a full worst case
    def _band_energy(sig, lo, hi):
        s = np.abs(np.fft.rfft(sig)) ** 2
        f = np.fft.rfftfreq(len(sig), 1.0 / sr)
        m = (f >= lo) & (f < hi)
        return float(s[m].sum())

    mid_e = _band_energy(mix, 1000, 4000)
    low_e = _band_energy(mix, 300, 3000)

    harsh = rng.normal(0, 1, n)
    hb = np.fft.rfft(harsh)
    hf = np.fft.rfftfreq(n, 1.0 / sr)
    hb[(hf < 6000) | (hf > 10000)] = 0
    harsh = np.fft.irfft(hb, n)
    harsh *= math.sqrt(0.55 * mid_e / max(_band_energy(harsh, 6000, 10000), 1e-12))

    mud_tone = np.sin(2 * np.pi * 150 * t) + 0.6 * np.sin(2 * np.pi * 215 * t)
    mud_tone *= math.sqrt(0.35 * low_e / max(_band_energy(mud_tone, 100, 300), 1e-12))

    mix = mix + harsh + mud_tone
    stereo = np.stack([mix, mix * 0.98], 1)
    # master it like someone chasing loudness: push into the ceiling and hard clip
    stereo /= max(float(np.max(np.abs(stereo))), 1e-9)
    cur = integrated_lufs(stereo, sr)
    stereo *= 10.0 ** ((-7.5 - cur) / 20.0)
    stereo = np.clip(stereo * 1.15, -1.0, 1.0)
    write_wav(path, stereo, sr)
    return path

# --------------------------------------------------------------------------- cli

def fmt(res):
    lines = []
    lines.append("soundcheck - target %s (%s)" % (res["target"], res["profile"]))
    lines.append("  duration %.1fs  %.0f Hz  %d ch" % (res["duration_sec"], res["sample_rate"], res["channels"]))
    lines.append("")
    for k, v in res["tells"].items():
        mark = "ok  " if v["ok"] else "FAIL"
        val = "n/a" if v["value"] is None else v["value"]
        extra = "  (%s)" % v["note"] if v.get("note") else ""
        lines.append("  %-12s %8s   target %-8s %s%s" % (k, val, v["target"], mark, extra))
    lines.append("")
    lines.append("  LRA %.1f LU" % res["lra"])
    lines.append("  SCORE %d/100 - %s" % (res["score"], res["label"]))
    for w in res.get("warnings", []):
        lines.append("  warning: %s" % w)
    if 0 < res["score"] < 85:
        lines.append("  -> run: soundcheck fix <file> --target %s" % res["target"])
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="soundcheck", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze")
    a.add_argument("file")
    a.add_argument("--target", default="youtube", choices=sorted(TARGETS))
    a.add_argument("--music", help="separate music stem (enables the voice/music tell)")
    a.add_argument("--json", action="store_true")

    f = sub.add_parser("fix")
    f.add_argument("file")
    f.add_argument("--target", default="youtube", choices=sorted(TARGETS))
    f.add_argument("--music")
    f.add_argument("--out")
    f.add_argument("--level", action="store_true",
                   help="level mismatched dialogue takes (skip for music-led content)")
    f.add_argument("--naturalize", action="store_true",
                   help="add room, breath floor and air to dry TTS (does not fix prosody)")
    f.add_argument("--no-verify", action="store_true")

    d = sub.add_parser("demo")
    d.add_argument("--out", default="demo_ai_voice.wav")

    args = ap.parse_args(argv)

    if args.cmd == "demo":
        p = make_demo(args.out)
        x, sr = load_audio(p)
        print(fmt(analyze(x, sr, "youtube")))
        print("\n  wrote %s" % p)
        return 0

    if not Path(args.file).exists():
        raise SystemExit("no such file: %s" % args.file)

    if args.cmd == "analyze":
        x, sr = load_audio(args.file)
        music_lufs = None
        if args.music:
            mx, msr = load_audio(args.music)
            music_lufs = integrated_lufs(mx, msr)
        res = analyze(x, sr, args.target, music_lufs)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(fmt(res))
        return 0 if res["score"] >= 85 else 1

    if args.cmd == "fix":
        src_path = Path(args.file)
        default_ext = src_path.suffix.lower() if src_path.suffix.lower() in VIDEO_EXT else ".wav"
        out = args.out or str(src_path.with_name(src_path.stem + ".soundcheck" + default_ext))
        res = run_fix(args.file, out, args.target, args.music, args.level, args.naturalize)
        if args.no_verify:
            print("wrote %s" % out)
            return 0
        if res is None:
            x, sr = load_audio(out)
            res = analyze(x, sr, args.target)
        print("wrote %s\n" % out)
        print(fmt(res))
        bad = [k for k, v in res["tells"].items() if not v["ok"]]
        if bad:
            print("\n  verification: %d tell(s) still off: %s" % (len(bad), ", ".join(bad)))
            return 1
        print("\n  verification: all measured tells within target")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
