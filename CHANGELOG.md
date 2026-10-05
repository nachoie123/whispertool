# Changelog

All notable changes to WisprTool are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

---

## [2.0.0] - 2026-10-05

### Changed
- Mac app rewritten in Swift (`mac/WhisperTool.swift`): menu-bar app, 23 MB and 0% CPU while idle (v1: 2.6 GB).
- Transcription with Whisper large-v3-turbo on Groq (own free key); Apple on-device recognition as fallback and as the no-key mode.
- Microphone only on while the hotkey is held.

### Added
- Live text in a black island under the notch while you talk.
- Recent dictations in the menu; the last audio is kept for a retry if transcription fails.
- Opens at login; settings window with permissions status and a vocabulary hint for names.

---

## [1.0.0] - 2026-02-17

### Added
- Hold-to-record global hotkey (configurable via UI)
- Local speech-to-text via faster-whisper (base model, CPU, int8)
- Text post-processing: filler removal, smart backtrack, numbered lists, smart punctuation
- AI rewriting with provider selector (Gemini, OpenAI, Claude)
- Per-provider API key storage with Apply button
- Circular floating overlay: teal waveform during recording, spinner during transcription
- Transcription history (last 100) with copy-on-click
- Cross-platform support (Windows + macOS)
- Single-file exe packaging via PyInstaller
- Optimized build with heavy-module exclusions (torch, matplotlib, pandas, etc.)
- Config persistence via config.json
- Error display for AI provider failures in the UI
