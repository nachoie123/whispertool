# WhisperTool

**A free, local voice-to-text tool for Mac. Hold a key, talk, let go — your words are transcribed on-device and typed straight into whatever app you're using.**

Email, chat, notes, code — anywhere you can type, you can talk instead. Transcription runs **100% locally on your Mac** (your voice never leaves the machine). An optional AI pass can clean up the "ums" and fix punctuation.

> This is a personal, **non-commercial** project — I built it to make my own day easier and I'm sharing it free for anyone who wants to try it. It's a heavily customized fork of [**WisprTool by FuturMinds**](https://github.com/futurminds/whispertool) — full credit to them for the original tool and idea.

---

## What it does

- **Hold-to-talk:** hold a hotkey (default **Option + Control**), speak, release. The text is transcribed and pasted at your cursor.
- **Local transcription:** runs on your Mac — no account, no cloud, no API cost for the transcription itself.
- **Works everywhere:** any app, including other apps in full-screen.
- **Clean output:** removes fillers (*um, uh, like*), handles self-corrections, dictated punctuation and numbered lists.
- **Optional AI polish:** if you add your own free API key, an AI pass tidies grammar/punctuation while keeping your wording and tone.

## What I added on top of the original

- **GPU transcription** with `mlx-whisper` (large-v3-turbo) on Apple Silicon — fast and accurate, with a CPU fallback.
- **Automatic language detection** per phrase (Spanish stays Spanish, English stays English).
- **A native floating overlay** (a small waveform capsule) showing recording status, that works even over other apps' full-screen spaces.
- **Start/stop cue sounds** so you know when it's listening.
- **Optional "email mode":** start your dictation by saying it's an email and the AI formats it with a greeting, paragraphs and a sign-off.

## Privacy

- **Audio never leaves your Mac.** Transcription is done locally.
- The **optional** AI polish step sends only the *transcribed text* (never the audio) to your chosen provider, and **only if you enable it and add your own key**. It's off unless you turn it on.
- Your API key lives only in your local `config.json`, which is git-ignored and never uploaded.

## Requirements & permissions

- A Mac with Apple Silicon (M1 or later) on macOS 14 or newer. From source: Python 3.12.
- The app asks for these macOS permissions on first run:
  - **Microphone** — to hear you.
  - **Accessibility** — to paste the text where your cursor is.
  - **Input Monitoring** — only if macOS asks for it, so the global hotkey can be heard.

## Mac app

Download `WhisperTool.dmg` from [Releases](https://github.com/nachoie123/whispertool/releases/latest). It isn't notarized by Apple: the first time, click *Done*, then *System Settings › Privacy & Security › Open Anyway*. The first launch downloads the speech model (~1.6 GB) once. Build it yourself with `./build.sh && tools/dmg.sh`; the security check of the bundle is in [tools/seguridad.md](tools/seguridad.md).

That's normal for a dictation tool, but worth knowing before you install.

## Install

```bash
git clone <your-fork-url> whispertool
cd whispertool
pip3 install -r requirements.txt
cp config.example.json config.json   # optional: edit to enable AI polish
python3 main.py
```

For the optional AI polish, get a **free** Gemini API key at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) and paste it into the
app's settings (or `config.json`). **Never commit `config.json`** — it's already git-ignored.

## Credit

Original tool by [FuturMinds](https://github.com/futurminds/whispertool)
([YouTube](https://www.youtube.com/channel/UCzsmpPhpoweC6itJd_oAt3w)). This fork adds the
Mac-specific GPU / overlay / AI changes listed above. Shared free, for anyone to use.
