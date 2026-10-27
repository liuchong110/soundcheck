---
name: soundcheck
description: Fix audio that sounds "AI". Use when a video, voiceover, podcast, short drama, screen recording or reel sounds harsh, muddy, thin, too quiet or too loud, clips, or changes level between segments - and before delivering to YouTube, TikTok, Spotify, Apple, podcast or broadcast. Measures integrated loudness (LUFS), true peak, sibilance, low-mid mud, segment drift and phase against the 7 AI Audio Tells, applies a corrective chain, then re-measures and reports whether the delivery spec was actually met.
license: MIT
---

# soundcheck

AI video looks finished long before it sounds finished. TTS takes are glued together at
different levels, the music bed never ducks, the mix is pushed into the limiter to sound
"loud", and the AI voice keeps its 6-10 kHz hiss and 100-300 Hz boom.

soundcheck turns that into numbers, fixes it, and proves the fix.

## Run it

```bash
python scripts/soundcheck.py analyze <file> [--target youtube] [--music music.wav] [--json]
python scripts/soundcheck.py fix     <file> [--target youtube] [--music music.wav] [--out out.wav] [--level] [--naturalize]
python scripts/soundcheck.py demo
```

`fix` needs `ffmpeg` on PATH. `analyze` and `demo` only need Python 3 + numpy
(scipy is used for faster filtering when present).

Give `fix` a video and it returns a video: the corrected audio is muxed against the
original video stream (copied, never re-encoded). Without `--out` it writes
`<name>.soundcheck.mp4` next to the source.

`--level` matches the level of separate spoken takes before mastering. Use it for dialogue
recorded or synthesised line by line; do not use it on music-led content, where a swell or a drop
is the arrangement, not a defect. `analyze` prints the timestamps of the largest take jumps so
you can decide.

## Verify before you trust it

```bash
python scripts/verify.py        # 19 checks, exit 0 = all good
```

The suite checks that our meters agree with ffmpeg's `ebur128`, that `fix` exits 0 only when
every tell passes, that the delivered file is re-measured with an independent meter, that dynamics
are not squashed, and that silence / short clips / mono 24-bit / mp4 / missing files behave.
If it fails on your machine, fix that before touching anyone's audio.

When you process real material, always A/B it. Measured compliance is necessary, not sufficient.

## Workflow

1. **Measure before touching anything.** Run `analyze`. Never start EQ-ing from a guess.
2. **Read the scorecard, not the score.** The score is a summary; the failing tells are the work.
3. **Fix.** Run `fix --target <platform>`. It picks corrective EQ depth from the measurement,
   applies the chain, computes a static gain from our own loudness measurement, limits, and re-measures.
4. **Verify.** `fix` exits non-zero when any measured tell is still outside spec. Do not report
   "done" on a non-zero exit - report the remaining tells instead.
5. **A/B.** Keep the original. If the fix sounds worse than the problem (over-EQ'd, pumping),
   reduce the corrective depth and re-run. Measured compliance is necessary, not sufficient.

## The 7 AI Audio Tells

| # | Tell | Measured as | Target | Usual cause |
|---|---|---|---|---|
| 1 | Take-to-take level mismatch | speech-band region levels, adjacent delta | <= 3 dB | TTS takes rendered separately |
| 2 | No headroom | true peak | <= -1 dBTP | "make it loud" mastering |
| 3 | Voice/music fight | voice LUFS - music LUFS | >= 4 dB | no sidechain ducking |
| 4 | Harsh sibilance | 6-10 kHz / 1-4 kHz energy | <= 0.45 | synthetic /s/ and /sh/ |
| 5 | Low-mid mud | 100-300 Hz / 300-3k energy | <= 0.40 | proximity boom, loud bass bed |
| 6 | No floor, no space | noise floor vs program level | >= 45 dB below | denoise artefacts, layered room tone |
| 7 | Phase / DC problems | L/R correlation, DC offset | corr >= 0.2 | concatenated takes, resampling |

Tell 3 only runs when you pass `--music` with an isolated music stem. Tell 6 reports `n/a`
when the material has no silent passage - quiet music is not noise, and an honest
"cannot assess" is not a pass. Tell 1 reports where the largest jumps are, so a human can listen.

## Loudness ladder

| Delivery | Integrated | True peak | Notes |
|---|---|---|---|
| YouTube / TikTok / Reels | -14 LUFS | -1 dBTP | platforms normalise here |
| Spotify | -14 LUFS | -1 dBTP | |
| Apple Music | -16 LUFS | -1 dBTP | |
| Podcast (stereo / mono) | -16 / -19 LUFS | -1 dBTP | |
| Broadcast (EBU R128) | -23 LUFS | -1 dBTP | |
| Short drama / OTT (CN) | -24 LKFS | -1 dBTP | |
| Cinema | -27 LUFS | -2 dBTP | dialogue-anchored |

## Chain order (it matters)

`high-pass 70 Hz -> subtractive EQ (mud, then sibilance) -> gentle compression -> limit -> static gain -> limit`

- Corrective EQ depth is derived from the measured tell, not from a fixed preset.
- Compression is gentle on purpose (2.5:1, ~3-6 dB gain reduction). This is post, not sound design.
- Gain is applied **after** the corrective chain and measured on the chain output, so the delivered
  file lands on spec even when EQ changed the loudness.
- The limiter sits at 0.79 (-2 dBFS sample peak) to survive inter-sample overshoot at -1 dBTP.

## Guardrails

- **Never claim success without a fresh measurement.** The script's exit code is the source of truth.
- **Do not re-encode lossy twice.** Decode to WAV once, work in WAV, encode once at the end.
- **Do not upsample to fake quality.** Output 48 kHz; loudnorm's 192 kHz internal rate is not a feature.
- **Do not flatten dynamics to hit a number.** If hitting -14 LUFS requires >6 dB of limiting, say so
  and deliver -16 instead - a squashed mix is worse than a quiet one.
- **Music stems stay separate.** Ducking a mixed track destroys the voice; ask for stems.
- **Keep the original.** Always write to a new file.

## What this cannot fix

`analyze` prints a warning when the source has almost no energy above 8 kHz - the signature of a
16/22 kHz TTS piped through a 48 kHz session. That dullness is not a mastering problem and no EQ
brings it back. If the warning fires, say so instead of "fixed": re-render the voice with a neural
TTS, then master.

`--naturalize` adds a small room, a breath/room-tone floor and a little HF air. It removes the
"dry, digitally silent" cue; it cannot invent prosody, and it will not rescue a robotic source.
Never enable it by default on music-led content.

## Limits

- The "music bed" tell needs a stem; without one, voice/music balance is not measured.
- Noise floor is only meaningful when there are real quiet passages.
- True peak is 4x oversampled; broadcasters requiring 8x should verify with their own meter.
- This is a delivery tool, not a creative mix. It will not make a bad performance good.
