# Changelog

All notable changes to WisprTool are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

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
