# WhisperTool

**Free voice-to-text for Mac that lives in the menu bar. Hold ⌥ + ⌃, talk, let go — you see your words as you say them, and the text is typed straight into whatever app you're using.**

> This is a personal, **non-commercial** project — I built it to make my own day easier and I'm sharing it free for anyone who wants to try it. It started as a fork of [**WisprTool by FuturMinds**](https://github.com/futurminds/whispertool) — full credit to them for the original tool and idea.

---

## Version 2: native Mac app (`mac/`)

Version 1 was Python + Tk and kept the Whisper model loaded on the GPU all day: **2.6 GB of memory** even when you weren't talking. Version 2 is a single Swift file:

| | v1 (Python) | v2 (Swift) |
|---|---|---|
| Memory while idle | 2,588 MB | **23 MB** |
| CPU while idle | ~2% | **0%** |
| Microphone | on all day | **only while you hold the keys** |
| Download | 174 MB | **1 MB** |

- **Menu bar app:** no Dock icon, no window. Opens at login. Recent dictations one click away.
- **Live text:** while you hold the keys, a black island drops from the notch and shows what you're saying (Apple's on-device speech recognition).
- **Whisper on Groq:** with your own free [Groq key](https://console.groq.com/keys), the audio goes to Whisper large-v3-turbo (~0.3 s per phrase, language detected per phrase), then an AI pass removes ums and self-corrections and fixes punctuation. Start with "this is an email…" and it formats an email.
- **Nothing gets lost:** if Groq fails, it pastes what your Mac heard on-device; if both fail, the audio is kept and the menu offers *Retry the last audio*.
- **Never hangs on the mic:** the audio engine is stopped on a background thread, so a slow CoreAudio teardown can't freeze the app (that was v1's worst bug).

Build it: `cd mac && ./build.sh` (Xcode command line tools; it signs ad-hoc if you don't have a developer certificate).

## Privacy

- **Without a key**, transcription is Apple's on-device recognition: nothing leaves your Mac.
- **With your Groq key**, the audio of each dictation is sent to Groq to be transcribed, and the text to Groq to be tidied. Nothing goes to me.
- Your key lives only in a local `config.json` (permissions 600), which is git-ignored.

## Permissions

Microphone (to hear you), Speech Recognition (live text) and Accessibility (the global hotkey and pasting).

## Mac app

Download `WhisperTool.dmg` from [Releases](https://github.com/nachoie123/whispertool/releases/latest). It isn't notarized by Apple: the first time, click *Done*, then *System Settings › Privacy & Security › Open Anyway*. To build the DMG yourself: `mac/build.sh && tools/dmg.sh`.

## Version 1 (Python, cross-platform)

The original Python app (`main.py`) is still here, for Windows or for fully local transcription with mlx/faster-whisper.

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
