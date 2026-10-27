# Launch copy — soundcheck v0.1.0

Repo: https://github.com/liuchong110/soundcheck
Asset: `docs/demo-ab.gif` (0.6 MB, autoplays) · `docs/demo-ab.mp4` (0.65 MB, with sound)
Best window: Tue–Thu, 13:00–15:00 UTC (US morning) for HN/X; 20:00–22:00 CST for Chinese channels.

---

## X / Twitter (attach docs/demo-ab.gif, then the mp4 in a reply)

Your AI video sounds AI.

soundcheck scores a clip against 7 measurable audio tells, fixes what is measurable, then re-measures before you ship.

64/100 → 98/100 on the same 15 s clip. Level-matched. No model in the loop.

npx skills add liuchong110/soundcheck

---

## Show HN

**Title:** Show HN: Soundcheck – measure and fix the audio of AI video

**Body:**

I kept shipping AI-generated videos that looked finished and sounded wrong: TTS takes glued together at different levels, a music bed that never ducks under the voice, a mix pushed into the limiter until it clips, 6–10 kHz hiss on every "s". None of that is taste — most of it is measurable.

soundcheck is an Agent Skill (SKILL.md + a small Python/ffmpeg tool). It measures seven things — integrated loudness, true peak, sibilance ratio, low-mid mud, take-to-take level mismatch, noise floor, phase — scores them against a per-platform delivery target (YouTube/TikTok −14, podcast −16/−19, EBU R128 −23, CN short drama −24), applies a corrective chain, then re-measures and exits non-zero if anything is still out of spec.

Two things worth calling out:

- The verification is the feature. It re-checks the delivered file with the same meters and refuses to say "done" while a tell is still off. CI compares our meters against ffmpeg's ebur128, so a 3 dB channel-summing bug was caught before release.
- It cannot fix a bad voice. On the bundled fixture a 2010 SAPI voice and a neural voice both hit −24 LKFS and score ~100, and only one sounds like a person. The analyzer prints a band-limited warning when a source has almost nothing above 8 kHz, because no EQ brings that back.

Video in, video out: the corrected audio is muxed against the original video stream, copied not re-encoded.

Feedback on the thresholds very welcome — especially from people doing short drama, podcast or OTT delivery.

---

## Reddit — r/ClaudeAI

**Title:** I built a skill that scores AI video audio against 7 tells, then fixes it

**Body:**
Every AI video tool optimises the picture. The sound is still: three TTS takes at three levels, a music bed that never ducks, a limiter doing the loudness, and hiss on every sibilant.

I turned that into 7 measurements and a deterministic chain. `/soundcheck clip.mp4` gives you a score and the failing tells; `--fix` corrects them and re-measures; it exits non-zero if it did not actually hit the spec.

It also tells you when the source is the problem: if a clip has ~0.005% of its energy above 8 kHz (a 16/22 kHz TTS), no mastering will make it sound human — the analyzer says so instead of handing you a 100/100.

Free, MIT, works in Claude Code / Codex / Cursor.

---

## V2EX（分享创造）

**标题：** 给 AI 视频「修声音」的 skill：7 个可测量的 AI 音频破绽

**正文：**
画面越来越像样，声音还停在「能出声」：TTS 分段拼接电平不齐、BGM 不给人声让路、为了响度顶到削波、6–10 kHz 齿音、100–300 Hz 浑浊。

这些不是审美，是可测的。我把它拆成 7 项（综合响度、真峰值、齿音比、低中频、段间电平差、噪声底、相位），按交付标准打分（YouTube/TikTok −14、播客 −16/−19、EBU R128 −23、国内短剧 −24），跑一条确定性处理链，**然后复测**——没达标就 exit 1，不说「已完成」。

一个诚实的点：它救不了声源。同一个剧本，SAPI 2010 和神经音色都能做到 −24 LKFS、接近满分，但只有一个像人。检测到高频几乎为空（16/22 kHz 的 TTS）会直接警告「换声源」，而不是给你一个虚假的 100 分。

MIT，Claude Code / Codex / Cursor 都能装：`npx skills add liuchong110/soundcheck`

---

## 即刻 / 小红书（短版）

AI 视频现在最大的破绽不在画面，在声音。

我做了个 skill：给一条片子打「声音分」，7 项可测指标，不够就修，修完**复测**，不达标直接报错——不是那种「已帮你优化」的假完成。

同一段 15 秒素材：64 分 → 98 分，-11.8 LUFS 削波 → -14.0 LUFS 干净交付。

它也会老实告诉你：这条片子声音闷，是因为声源只有 22 kHz，换 TTS 比修母带有用。

开源：github.com/liuchong110/soundcheck

---

## 提交 awesome list 的 PR 文案

> **awesome-claude-code / awesome-agent-skills**
> Add: [soundcheck](https://github.com/liuchong110/soundcheck) — measures 7 audio tells in AI video (loudness, true peak, sibilance, mud, take drift, noise floor, phase), applies a deterministic ffmpeg chain, then re-measures and fails the command if the delivery spec was not met. 20 self-tests; video in, video out.
