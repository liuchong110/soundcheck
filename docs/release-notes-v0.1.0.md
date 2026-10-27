# soundcheck v0.1.0

**Your AI video sounds AI. Here are the 7 tells — and the fix.**

A soundcheck measures a generated clip against seven measurable audio defects, corrects the ones a
mastering chain can correct, then re-measures and tells you the truth about what is left.

```bash
npx skills add liuchong110/soundcheck
python scripts/soundcheck.py demo
python scripts/soundcheck.py fix clip.mp4 --target youtube   # video in, video out
```

## What's in it

- **The 7 AI audio tells**: loudness drift, no headroom, voice/music fight, sibilance, low-mid mud,
  noise floor, phase.
- **The loudness ladder**: YouTube/TikTok −14, Spotify −14, Apple −16, podcast −16/−19, EBU R128 −23,
  CN short drama −24, cinema −27, always −1 dBTP.
- **A deterministic chain**: corrective EQ derived from the measurement, static gain computed on the
  chain output, limiter at −2 dBFS sample peak. No model in the loop.
- **Verification as a feature**: the delivered file is re-measured, and `fix` exits non-zero while any
  tell is still outside spec. It says no when it failed.
- **Video in, video out**: the corrected audio is muxed against the original video stream, copied, never
  re-encoded.
- **`--level`** for dialogue assembled line by line: one gain per spoken take, 30 ms ramps, ±9 dB.
- **`--naturalize`** for dry TTS: a small room, a breath floor, a little air. Off by default.

## What is actually verified

20 checks in CI on Ubuntu, plus an independent meter:

- our LUFS and true peak agree with ffmpeg `ebur128`
- `fix` exits 0 only when every measured tell passes
- the **delivered** file is re-checked, not our own claim about it
- glued takes are flagged as drift; even takes and a gradual swell are not
- silence is rejected, not scored as fine; sub‑1 s clips are flagged
- WAVE_FORMAT_EXTENSIBLE (Linux 24-bit PCM), mono 24-bit, mp4 input, missing file, video remux

## What it cannot fix

A perfect score does not mean it sounds human. On the bundled drama fixture a Windows SAPI voice and a
neural voice both master to −24.0 LKFS and score 99–100, and only one sounds like a person:

| | SAPI 2010, 22 kHz | Edge neural, 24 kHz |
|---|---|---|
| energy above 8 kHz | 0.005% | 1.231% |
| source LRA | 2.8 LU | 7.7 LU |

`analyze` prints a band-limited warning when a source has almost nothing above 8 kHz. Re-render the
voice first; master second.

Tell 1 compares spoken takes, so a music-led edit with hard breaks can trip it. The scorecard prints the
timestamps of the largest jumps: listen before you level anything.

## Known limitations

- Tell 3 (voice/music) needs an isolated music stem.
- True peak is 4× oversampled; broadcast deliveries requiring 8× should double-check with their own meter.
- `--naturalize` cannot invent prosody and will not rescue a robotic source.
