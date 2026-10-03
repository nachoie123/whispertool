import os
import multiprocessing

# Packaged app: tqdm (inside huggingface_hub/mlx-whisper) starts
# multiprocessing's resource tracker, which re-runs THIS executable. Without
# freeze_support() that child would open a second WhisperTool (and its child
# a third...). It must run before anything else.
if __name__ == "__main__":
    multiprocessing.freeze_support()

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import sys
import re
import json
import math
import time
import wave
import tempfile
import threading
import platform
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

import tkinter as tk
from tkinter import ttk

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

try:
    import mlx_whisper  # Apple-Silicon GPU backend
except ImportError:
    mlx_whisper = None

# large-v3-turbo on the M-series GPU: better accuracy than "small" AND
# faster than it runs on CPU (benchmarked 1.8s vs 2.2-4.8s for 11s audio;
# the same turbo model on CPU took 9.3s).
MLX_REPO = "mlx-community/whisper-large-v3-turbo"
MLX_SIZE = "~1.6 GB"
# Vocabulary hint so proper nouns the user says beat lookalikes (e.g. a name
# heard as "NATO"). Per user, in config.json "vocabulary"; empty by default so
# nobody else's dictation is nudged towards someone's names.
from pynput import keyboard as pynput_kb
import pyperclip
import pyautogui

from text_processor import process_text

try:
    from AppKit import NSApplication, NSColor
except ImportError:
    NSApplication = None
    NSColor = None

# ── Platform ────────────────────────────────────────────────────────
IS_MAC = platform.system() == "Darwin"
PASTE_KEYS = ("command", "v") if IS_MAC else ("ctrl", "v")

# ── Paths ───────────────────────────────────────────────────────────
# Packaged WhisperTool.app: user data (config.json with the API keys, cue
# sounds) lives in ~/Library/Application Support/WhisperTool — never inside
# the bundle. Run from the repo: next to main.py, as before.
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    APP_DIR = os.path.expanduser("~/Library/Application Support/WhisperTool")
    os.makedirs(APP_DIR, mode=0o700, exist_ok=True)
    # python.org Python ships no CA certificates: without this the model
    # download and the AI calls fail with CERTIFICATE_VERIFY_FAILED.
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

SAMPLE_RATE = 16000
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
SHOW_FLAG = os.path.join(APP_DIR, ".show")  # touched by the Dock launcher
MAX_HISTORY = 100

# Start/stop cue tones. Pre-rendered to WAV once and played with `afplay`
# (a separate process) — NEVER through sounddevice: sharing PortAudio with
# the mic InputStream deadlocked CoreAudio's HAL mutex (Pa_Terminate stuck
# in HALB_Mutex::Lock when the beep's output stream and the mic input stream
# stopped concurrently), which froze the whole app.
BEEP_START = os.path.join(APP_DIR, "beep_start.wav")  # rising cue
BEEP_STOP = os.path.join(APP_DIR, "beep_stop.wav")    # falling cue


def _make_tone_wav(path, f0, f1, dur=0.09, vol=0.18, sr=44100):
    """Render a short sine glissando (5 ms fades to avoid clicks) to a
    16-bit mono WAV. f0->f1 rising = start cue, falling = stop cue."""
    n = int(sr * dur)
    freqs = np.linspace(f0, f1, n)
    phase = 2 * np.pi * np.cumsum(freqs) / sr
    tone = np.sin(phase)
    fade = max(1, int(sr * 0.005))
    env = np.ones(n)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    pcm = (tone * env * vol * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _ensure_beeps():
    """Generate the cue WAVs on first run (cached thereafter)."""
    try:
        if not os.path.exists(BEEP_START):
            _make_tone_wav(BEEP_START, 520, 830)
        if not os.path.exists(BEEP_STOP):
            _make_tone_wav(BEEP_STOP, 830, 520)
    except Exception as e:
        print(f"[!] beep wav generation failed: {e}", flush=True)


def fetch_model(repo, on_progress=None, cache_dir=None):
    """Make sure a Hugging Face model is in the local cache. First run only:
    downloads it (>1 GB for the GPU model) calling on_progress(mb_written),
    so the UI can say "Downloading…" instead of looking frozen. Returns the
    local snapshot folder."""
    from huggingface_hub import snapshot_download
    from io import StringIO
    from tqdm import tqdm
    try:
        return snapshot_download(repo, local_files_only=True,
                                 cache_dir=cache_dir)
    except Exception:
        pass  # not cached yet -> download

    class Progress(tqdm):
        # A plain tqdm (not huggingface's) is never auto-disabled, even with
        # no terminal attached as in the .app; its text goes nowhere.
        # snapshot_download sums every file into two byte bars: "Downloading
        # bytes" (network, ~10 updates/s) and "Reconstructing" (written to
        # disk, can jump at the end with Xet). Report the furthest of both.
        def __init__(self, *args, **kwargs):
            kwargs.update(disable=False, file=StringIO())
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            out = super().update(n)
            if on_progress and self.unit == "B" and self.n > best[0]:
                best[0] = self.n
                on_progress(self.n / 1e6)
            return out

    best = [0]

    return snapshot_download(repo, cache_dir=cache_dir, tqdm_class=Progress)


# ── Version ────────────────────────────────────────────────────────
# When frozen, --add-data bundles VERSION inside the temp extraction dir
_BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
try:
    with open(os.path.join(_BUNDLE_DIR, "VERSION")) as _vf:
        APP_VERSION = _vf.read().strip()
except FileNotFoundError:
    APP_VERSION = "dev"

PROVIDERS = ["Gemini", "OpenAI", "Claude"]

DEFAULT_CONFIG = {
    "hotkey": ["alt", "ctrl"],
    "model_size": "base",
    "language": "en",
    "remove_fillers": True,
    "backtrack": True,
    "numbered_lists": True,
    "smart_punctuation": True,
    "ai_rewrite": False,
    "ai_provider": "Gemini",
    "ai_api_keys": {"Gemini": "", "OpenAI": "", "Claude": ""},
    "ai_style": "",
    "vocabulary": "",
}

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False

# ── Key normalisation ───────────────────────────────────────────────

PYNPUT_KEY_MAP = {}
for _attr, _name in [
    ("ctrl_l", "ctrl"), ("ctrl_r", "ctrl"),
    ("alt_l", "alt"), ("alt_r", "alt"), ("alt_gr", "alt"),
    ("shift_l", "shift"), ("shift_r", "shift"),
    ("cmd", "cmd"), ("cmd_l", "cmd"), ("cmd_r", "cmd"),
]:
    _key = getattr(pynput_kb.Key, _attr, None)
    if _key is not None:
        PYNPUT_KEY_MAP[_key] = _name

TK_KEYSYM_MAP = {
    "Control_L": "ctrl", "Control_R": "ctrl",
    "Alt_L": "alt", "Alt_R": "alt",
    "Shift_L": "shift", "Shift_R": "shift",
    "Super_L": "cmd", "Super_R": "cmd",
    "Meta_L": "cmd", "Meta_R": "cmd",
}


def normalize_pynput(key):
    return PYNPUT_KEY_MAP.get(key)


def normalize_tk(keysym):
    return TK_KEYSYM_MAP.get(keysym)


def hotkey_label(keys):
    order = {"ctrl": 0, "alt": 1, "shift": 2, "cmd": 3}
    return " + ".join(
        k.capitalize() for k in sorted(keys, key=lambda k: order.get(k, 9))
    )


# ── Config ──────────────────────────────────────────────────────────

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        # Migrate old single-key config
        if "gemini_api_key" in cfg and cfg["gemini_api_key"]:
            cfg.setdefault("ai_api_keys", {})
            if not cfg["ai_api_keys"].get("Gemini"):
                cfg["ai_api_keys"]["Gemini"] = cfg["gemini_api_key"]
        for p in PROVIDERS:
            cfg["ai_api_keys"].setdefault(p, "")
        return cfg
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    # config.json holds API keys in plaintext. Restrict it to the owner only
    # (0600) so no other local account — or a synced/shared folder — can read
    # them: created 0600 from the start (no world-readable window), and
    # chmod'ed for files from older versions. No-op on Windows.
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


# ── AI Providers ────────────────────────────────────────────────────

DEFAULT_AI_PROMPT = (
    "Rewrite the following text to make it clear, well-structured, "
    "and free of any grammatical or language errors. "
    "Preserve the original meaning and intent. "
    "Only return the rewritten text, nothing else."
)


def _system_prompt(style=""):
    prompt = DEFAULT_AI_PROMPT
    if style.strip():
        prompt += f"\n\nAdditional style and tone instructions: {style.strip()}"
    return prompt


# Email formatting style, applied instead of the casual-cleanup style when
# the dictation opens by announcing it's an email. Bounded on purpose: the
# "improve/expand" style once made Gemini invent flowery openings.
EMAIL_STYLE = (
    "Format this as a well-structured email, in the SAME language as the text. "
    "Start with an appropriate greeting line (e.g. 'Hola,' or 'Hi,') followed "
    "by a blank line; organize the body into short paragraphs separated by "
    "blank lines; end with a short closing line (e.g. 'Un saludo,' / 'Best,'). "
    "Do NOT invent facts, names, recipients, or content that were not dictated "
    "— only structure and lightly clean what is there. Keep it concise and "
    "natural, never flowery. Return only the email text."
)

# Leading phrase that switches on email formatting, e.g. "estoy escribiendo un
# email, ...", "esto es un correo: ...", "en formato email ...". Either an
# explicit trigger phrase + the email word, or a bare "email"/"correo" that is
# clearly a lead-in (followed by punctuation), so "email service ..." dictated
# into a terminal does NOT trip it.
_EMAIL_KW = r"(?:e-?mails?|correos?(?:\s+electr[oó]nicos?)?|mails?)"
_EMAIL_PHRASE = (
    r"(?:esto|este)\s+es\s+(?:un\s+)?|estoy\s+escribiendo\s+(?:un\s+)?|"
    r"escr[ií]b(?:e|o|iendo)(?:me)?\s+(?:un\s+)?|redacta(?:me)?\s+(?:un\s+)?|"
    r"haz(?:me)?\s+(?:un\s+)?|(?:en\s+)?formato\s+(?:de\s+)?|modo\s+|"
    r"this\s+is\s+an?\s+|i'?m\s+writing\s+an?\s+|write\s+(?:me\s+)?an?\s+|"
    r"format\s+as\s+an?\s+"
)
_EMAIL_TRIGGER = re.compile(
    r"^\s*(?:"
    r"(?:" + _EMAIL_PHRASE + r")" + _EMAIL_KW + r"[\s,.:;¡!¿?-]*"
    r"|" + _EMAIL_KW + r"\s*[,.:;-]+\s*"
    r")",
    re.IGNORECASE,
)


def detect_email_mode(text):
    """If the dictation opens by announcing it's an email, return
    (True, text_without_that_lead-in); otherwise (False, text)."""
    m = _EMAIL_TRIGGER.match(text)
    if m and text[m.end():].strip():
        return True, text[m.end():].lstrip()
    return False, text


def rewrite_with_ai(text, provider, api_key, style=""):
    system = _system_prompt(style)
    user_content = f"Text to rewrite:\n{text}"

    if provider == "Gemini":
        # Gemini: combine system + user into a single user turn
        combined = f"{system}\n\n{user_content}"
        url = ("https://generativelanguage.googleapis.com/v1beta/"
               "models/gemini-flash-lite-latest:generateContent")
        body = json.dumps(
            {"contents": [{"parts": [{"text": combined}]}]}
        ).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    elif provider == "OpenAI":
        url = "https://api.openai.com/v1/chat/completions"
        body = json.dumps({
            "model": "gpt-5-nano-2025-08-07",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()

    elif provider == "Claude":
        url = "https://api.anthropic.com/v1/messages"
        body = json.dumps({
            "model": "claude-haiku-4-5",
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["content"][0]["text"].strip()

    raise ValueError(f"Unknown provider: {provider}")


# ── Floating Overlay (capsule waveform, Whisper-style) ──────────────

class FloatingOverlay:
    """Capsule overlay with animated vertical bars while recording.

    Show/hide is done by moving the window on/off screen (never
    withdraw/deiconify) so that showing it does NOT pull the Python app
    to the foreground and steal keyboard focus from the app the user is
    dictating into.
    """

    PILL_W = 150
    PILL_H = 44
    BAR_COUNT = 18

    WIN_BG = "#F4EEDD"       # Same as capsule: no dark frame
    PILL_BG = "#F4EEDD"      # Cream capsule
    PILL_OUTLINE = "#000000"
    BAR = "#111111"          # Dark bars
    BAR_LOADING = "#8b7355"

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        # Solid window (no macOS window-transparency trick — that renders
        # nothing on many macOS builds, which is why the capsule was invisible).
        self.win.configure(bg=self.WIN_BG)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        self._on_x = (sw - self.PILL_W) // 2
        self._on_y = sh - self.PILL_H - 110   # Above the dock
        self._off_y = sh + 400                 # Parked below the screen
        # Start parked off-screen, but stay mapped (no withdraw) so that
        # revealing it later is a cheap geometry move, not a re-activation.
        self.win.geometry(
            f"{self.PILL_W}x{self.PILL_H}+{self._on_x}+{self._off_y}"
        )

        self.canvas = tk.Canvas(
            self.win, width=self.PILL_W, height=self.PILL_H,
            bg=self.WIN_BG, highlightthickness=0,
        )
        self.canvas.pack()

        self.visible = False
        self.mode = "idle"  # idle | recording | loading
        self.phase = 0.0
        self.audio_level = 0.0
        self._want_mode = None  # Thread-safe mode requests
        self._nswindow = None  # Cached native NSWindow (see _ensure_native_topmost)
        self._nswindow_warned = False

    def request_recording(self):
        print("[i] overlay: recording requested", flush=True)
        self._want_mode = "recording"

    def request_loading(self):
        self._want_mode = "loading"

    def request_hide(self):
        self._want_mode = "idle"

    def set_audio_level(self, level):
        self.audio_level = min(1.0, level)

    def _move_onscreen(self):
        print("[i] overlay: moved onscreen", flush=True)
        self._diag_pending = True
        self.win.geometry(
            f"{self.PILL_W}x{self.PILL_H}+{self._on_x}+{self._on_y}"
        )
        self._ensure_native_topmost()

    def _find_nswindow(self):
        """Locate this Toplevel's underlying NSWindow by matching its pill
        frame size (with a small tolerance for HiDPI scaling/borders)."""
        self.win.update_idletasks()
        tol = 6
        app = NSApplication.sharedApplication()
        for w in app.windows():
            size = w.frame().size
            if (abs(size.width - self.PILL_W) <= tol
                    and abs(size.height - self.PILL_H) <= tol):
                return w
        return None

    def _ensure_native_topmost(self):
        """Force the overlay to order-front even when this app is not the
        active/foreground app, without activating it (which would steal
        keyboard focus from whatever the user is dictating into).

        Plain Tk `-topmost` only orders forward within the app's own layer
        on macOS; when the app isn't frontmost, the window just never
        surfaces. NSWindow.orderFrontRegardless() bypasses that.
        """
        if not IS_MAC or NSApplication is None:
            return
        try:
            if self._nswindow is None:
                self._nswindow = self._find_nswindow()
                if self._nswindow is not None:
                    print("[i] overlay NSWindow found: native ordering on",
                          flush=True)
                elif not self._nswindow_warned:
                    self._nswindow_warned = True
                    print("[!] overlay NSWindow NOT found: icon cannot be "
                          "raised above other apps", flush=True)
            if self._nswindow is not None:
                self._nswindow.setLevel_(101)  # NSPopUpMenuWindowLevel
                # 1 = can-join-all-spaces, 8 = transient, 16 = stationary,
                # 256 = full-screen auxiliary. Without these the overlay
                # stays in the Space it was created on and never shows over
                # full-screen apps.
                self._nswindow.setCollectionBehavior_(1 | 8 | 16 | 256)
                self._nswindow.setIgnoresMouseEvents_(True)
                # Rounded transparent-corner capsule: non-opaque window with
                # a clear backdrop and a corner-radius mask on the content
                # view, so there is no square frame around the pill.
                try:
                    if NSColor is not None:
                        self._nswindow.setOpaque_(False)
                        self._nswindow.setBackgroundColor_(
                            NSColor.clearColor())
                    cv = self._nswindow.contentView()
                    cv.setWantsLayer_(True)
                    layer = cv.layer()
                    if layer is not None:
                        layer.setCornerRadius_(self.PILL_H / 2.0)
                        layer.setMasksToBounds_(True)
                except Exception:
                    pass
                self._nswindow.orderFrontRegardless()
                if getattr(self, "_diag_pending", False):
                    self._diag_pending = False
                    print(
                        "[d] overlay diag: "
                        f"behavior={self._nswindow.collectionBehavior()} "
                        f"level={self._nswindow.level()} "
                        f"visible={self._nswindow.isVisible()} "
                        f"onActiveSpace={self._nswindow.isOnActiveSpace()}",
                        flush=True,
                    )
        except Exception as e:
            print(f"[!] FloatingOverlay: native order-front failed: {e}")

    def _move_offscreen(self):
        self.win.geometry(
            f"{self.PILL_W}x{self.PILL_H}+{self._on_x}+{self._off_y}"
        )

    def tick(self):
        wm = self._want_mode
        if wm is not None:
            self._want_mode = None
            if wm == "idle":
                if self.visible:
                    self.visible = False
                    self.mode = "idle"
                    self._move_offscreen()
            else:
                self.mode = wm
                self.phase = 0.0
                if not self.visible:
                    self.visible = True
                    self._move_onscreen()
        if self.visible:
            # Re-assert native ordering every frame: Tk resets the window
            # level/order when it processes geometry changes, which is why
            # a single order-front on show was not enough in real use.
            self._ensure_native_topmost()
            self._draw()

    def _pill(self, x0, y0, x1, y1, r, **kw):
        """Rounded-rectangle (capsule) via a smoothed polygon."""
        pts = [
            x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
            x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
            x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
        ]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        # The window itself is the capsule (cream bg + native rounded-corner
        # mask), so only the bars are drawn here.
        self.canvas.delete("all")
        W, H = self.PILL_W, self.PILL_H

        if self.mode == "recording":
            self._draw_bars(W, H, self.BAR, audio=True)
        elif self.mode == "loading":
            self._draw_bars(W, H, self.BAR_LOADING, audio=False)

    def _draw_bars(self, W, H, color, audio=True):
        self.phase += 0.30
        cy = H / 2
        n = self.BAR_COUNT
        left, right = 18, W - 18
        span = right - left
        max_h = H * 0.34
        level = max(0.18, self.audio_level) if audio else 0.42

        for i in range(n):
            x = left + span * i / (n - 1)
            # Envelope taller in the centre, animated wobble, scaled by mic.
            env = math.sin(math.pi * i / (n - 1))
            wob = 0.5 + 0.5 * math.sin(self.phase * 2 + i * 0.65)
            h = 2 + env * wob * level * max_h * 2.2
            h = min(h, max_h)
            self.canvas.create_line(
                x, cy - h, x, cy + h, fill=color, width=3, capstyle="round",
            )


# ── Native overlay (NSPanel — floats over full-screen Spaces) ───────

class NativeOverlay:
    """Capsule overlay drawn with a native non-activating NSPanel.

    Tk Toplevels are plain NSWindows, and macOS silently refuses to let a
    regular window join OTHER apps' full-screen Spaces (canJoinAllSpaces
    is ignored: onActiveSpace stays False). Non-activating borderless
    NSPanels — what Spotlight/screenshot thumbnails use — do get that
    privilege, so the capsule is rebuilt natively with CALayers. Same
    public API as FloatingOverlay; animation is still driven by the Tk
    after() loop calling tick().
    """

    PILL_W = 150
    PILL_H = 44
    BAR_COUNT = 18
    BAR_W = 3.0

    def __init__(self, root):
        self.visible = False
        self.mode = "idle"
        self.phase = 0.0
        self.audio_level = 0.0
        self._want_mode = None
        self._panel = None
        self._bars = []
        self._diag_pending = False
        self._bar_color = None
        self._bar_color_loading = None
        try:
            self._build_panel()
        except Exception as e:
            print(f"[!] NativeOverlay build failed: {e}", flush=True)
            self._panel = None

    def _build_panel(self):
        from AppKit import NSPanel, NSColor, NSScreen
        from Quartz import CALayer

        screen = NSScreen.mainScreen().frame()
        x = (screen.size.width - self.PILL_W) / 2.0
        y = 90.0  # Cocoa origin is bottom-left: 90pt above screen bottom
        style = 128  # NSWindowStyleMaskNonactivatingPanel (borderless)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((x, y), (self.PILL_W, self.PILL_H)), style, 2, False)
        panel.setLevel_(101)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setCanHide_(False)
        # 1 join-all-spaces | 16 stationary | 256 full-screen auxiliary
        panel.setCollectionBehavior_(1 | 16 | 256)

        cv = panel.contentView()
        cv.setWantsLayer_(True)
        rootlayer = cv.layer()

        cream = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.957, 0.933, 0.867, 1.0).CGColor()
        dark = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.067, 0.067, 0.067, 1.0).CGColor()
        brown = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.545, 0.451, 0.333, 1.0).CGColor()
        self._bar_color = dark
        self._bar_color_loading = brown

        pill = CALayer.layer()
        pill.setFrame_(((0, 0), (self.PILL_W, self.PILL_H)))
        pill.setBackgroundColor_(cream)
        pill.setCornerRadius_(self.PILL_H / 2.0)
        rootlayer.addSublayer_(pill)

        left, right = 18.0, self.PILL_W - 18.0
        span = right - left
        for i in range(self.BAR_COUNT):
            bar = CALayer.layer()
            bx = left + span * i / (self.BAR_COUNT - 1) - self.BAR_W / 2
            bar.setFrame_(((bx, self.PILL_H / 2 - 1), (self.BAR_W, 2)))
            bar.setBackgroundColor_(dark)
            bar.setCornerRadius_(self.BAR_W / 2.0)
            pill.addSublayer_(bar)
            self._bars.append(bar)

        self._panel = panel

    # ── Public API (same as FloatingOverlay) ─────────────────────────

    def request_recording(self):
        print("[i] overlay: recording requested", flush=True)
        self._want_mode = "recording"

    def request_loading(self):
        self._want_mode = "loading"

    def request_hide(self):
        self._want_mode = "idle"

    def set_audio_level(self, level):
        self.audio_level = min(1.0, level)

    def tick(self):
        if self._panel is None:
            self._want_mode = None
            return
        wm = self._want_mode
        if wm is not None:
            self._want_mode = None
            if wm == "idle":
                if self.visible:
                    self.visible = False
                    self.mode = "idle"
                    self._panel.orderOut_(None)
            else:
                self.mode = wm
                self.phase = 0.0
                if not self.visible:
                    self.visible = True
                    self._diag_pending = True
                    self._panel.orderFrontRegardless()
        if self.visible:
            if self._diag_pending:
                self._diag_pending = False
                print(
                    f"[d] native overlay: visible={self._panel.isVisible()} "
                    f"onActiveSpace={self._panel.isOnActiveSpace()}",
                    flush=True,
                )
            self._animate()

    def _animate(self):
        from Quartz import CATransaction
        self.phase += 0.30
        n = self.BAR_COUNT
        max_h = self.PILL_H * 0.68
        if self.mode == "recording":
            level = max(0.18, self.audio_level)
            color = self._bar_color
        else:
            level = 0.42
            color = self._bar_color_loading
        cy = self.PILL_H / 2.0
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        for i, bar in enumerate(self._bars):
            env = math.sin(math.pi * i / (n - 1))
            wob = 0.5 + 0.5 * math.sin(self.phase * 2 + i * 0.65)
            h = 2 + env * wob * level * max_h * 1.1
            h = min(h, max_h)
            f = bar.frame()
            bar.setFrame_(((f.origin.x, cy - h / 2), (self.BAR_W, h)))
            bar.setBackgroundColor_(color)
        CATransaction.commit()


# ── Application ─────────────────────────────────────────────────────

class App:
    def __init__(self, hooks=True):
        self.cfg = load_config()
        self.hotkey_set = set(self.cfg["hotkey"])

        # State
        self.model = None
        self.recording = False
        self.busy = False
        self.audio_frames = []
        self.stream = None
        self.pressed_keys: set[str] = set()
        self.lock = threading.Lock()
        self._audio_lock = threading.Lock()  # serialises mic start/stop
        self.history: list[tuple[str, str]] = []

        # Hotkey capture state
        self.capturing_hotkey = False
        self._capture_keys: set[str] = set()
        self._capture_max: set[str] = set()

        # AI provider tracking (needed to correctly save key on switch)
        self._last_provider = self.cfg.get("ai_provider", "Gemini")

        # Pending UI updates from background threads
        self._pending_status = "loading"
        self._pending_history = None
        self._pending_ai_error = None  # Error text from AI call, shown in UI
        self._perm_missing = []  # macOS permissions still off (UI banner)
        self._pending_perm = False
        self._last_show_check = 0.0  # throttle for the .show flag poll in _tick
        _ensure_beeps()  # render cue WAVs once (played via afplay, not sounddevice)

        # ── Root window ──────────────────────────────────────────────
        self.root = tk.Tk()
        self.root.title(f"WhisperTool v{APP_VERSION} (by FuturMinds)")
        self.root.geometry("880x1260")
        self.root.minsize(500, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        try:
            style.theme_use("vista" if not IS_MAC else "aqua")
        except tk.TclError:
            pass

        # ── Variables ────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Loading model...")
        self.hotkey_var = tk.StringVar(value=hotkey_label(self.hotkey_set))
        self.filler_var = tk.BooleanVar(value=self.cfg["remove_fillers"])
        self.backtrack_var = tk.BooleanVar(value=self.cfg["backtrack"])
        self.lists_var = tk.BooleanVar(value=self.cfg["numbered_lists"])
        self.punct_var = tk.BooleanVar(value=self.cfg["smart_punctuation"])
        self.ai_var = tk.BooleanVar(value=self.cfg["ai_rewrite"])
        self.provider_var = tk.StringVar(value=self.cfg.get("ai_provider", "Gemini"))

        self._build_ui()
        # NOTE: AppKit must only be touched AFTER tk.Tk() exists — creating
        # NSApplication before Tk initializes crashes Tk with an
        # NSException.
        if IS_MAC:
            try:
                # App Nap off: occluded apps get their Tk timers throttled,
                # which stalls the overlay tick loop.
                from Foundation import NSProcessInfo
                opts = (0x00FFFFFF          # NSActivityUserInitiated
                        | (1 << 20)          # idle-system-sleep disabled
                        | 0xFF00000000)      # NSActivityLatencyCritical
                self._nap_token = NSProcessInfo.processInfo() \
                    .beginActivityWithOptions_reason_(
                        opts, "WhisperTool dictation overlay")
                print("[i] App Nap disabled", flush=True)
            except Exception as e:
                print(f"[!] App Nap disable failed: {e}", flush=True)
            if not FROZEN:
                try:
                    # Accessory policy: the Python process gets NO Dock icon
                    # or Cmd+Tab entry of its own — the WhisperTool.app
                    # applet (with the custom logo) is the single Dock
                    # presence. The settings window still shows and works
                    # normally. Clicking the Dock logo while running touches
                    # the .show flag file, which _tick() watches to raise
                    # this window. (The packaged .app IS its own Dock icon,
                    # so it stays a regular app.)
                    if NSApplication is not None:
                        NSApplication.sharedApplication() \
                            .setActivationPolicy_(1)
                        print("[i] activation policy: accessory "
                              "(single Dock icon via applet)", flush=True)
                except Exception as e:
                    print(f"[!] accessory policy failed: {e}", flush=True)
            # Dock click on the running app -> show the window; Cmd+Q ->
            # the same clean shutdown as closing the window.
            self.root.createcommand("::tk::mac::ReopenApplication",
                                    self._show_window)
            self.root.createcommand("::tk::mac::Quit", self._on_close)
        if IS_MAC and hooks:
            try:
                # Explicitly request microphone access at startup. Script
                # bundles confuse TCC attribution, so PortAudio alone never
                # triggers the system prompt — it just records silence.
                # AVCaptureDevice fires the prompt with proper attribution.
                from AVFoundation import AVCaptureDevice
                st = AVCaptureDevice.authorizationStatusForMediaType_("soun")
                # 0=not determined 1=restricted 2=denied 3=authorized
                print(f"[i] mic auth status: {st}", flush=True)
                if st == 0:
                    AVCaptureDevice \
                        .requestAccessForMediaType_completionHandler_(
                            "soun", self._mic_answer)
                elif st in (1, 2):
                    self._mic_answer(False)
            except Exception as e:
                print(f"[!] mic request failed: {e}", flush=True)
            try:
                # Pasting (synthetic Cmd+V) needs Accessibility. Prompt=True
                # shows macOS's own "Open System Settings" dialog once.
                from HIServices import (AXIsProcessTrustedWithOptions,
                                        kAXTrustedCheckOptionPrompt)
                if not AXIsProcessTrustedWithOptions(
                        {kAXTrustedCheckOptionPrompt: True}):
                    self._warn_permission("Accessibility")
            except Exception as e:
                print(f"[!] accessibility check failed: {e}", flush=True)

        self.overlay = NativeOverlay(self.root)

        # Load model in background
        threading.Thread(target=self._load_model, daemon=True).start()

        # Global hotkey listener. Off in --selftest (no hotkey, no keys).
        self.listener = None
        if hooks:
            self.listener = pynput_kb.Listener(
                on_press=self._on_press, on_release=self._on_release,
            )
            self.listener.start()
            self.root.after(1500, self._check_listener)

        self._tick()

    # ── UI ───────────────────────────────────────────────────────────

    def _build_ui(self):
        px, py = 14, 6
        ipx, ipy = 12, 8
        mono = "Consolas" if not IS_MAC else "Menlo"

        # ── Status ───────────────────────────────────────────────────
        sf = ttk.LabelFrame(self.root, text="Status")
        sf.pack(fill="x", padx=px, pady=py)
        row = ttk.Frame(sf)
        row.pack(fill="x", padx=ipx, pady=ipy)
        self.status_dot = tk.Canvas(row, width=14, height=14,
                                    highlightthickness=0)
        self.status_dot.pack(side="left")
        self.status_dot.create_oval(2, 2, 12, 12, fill="gray", tags="dot")
        ttk.Label(row, textvariable=self.status_var,
                  font=("", 10)).pack(side="left", padx=8)
        # Missing macOS permissions: says exactly where to switch them on.
        self.perm_var = tk.StringVar()
        self.perm_lbl = ttk.Label(sf, textvariable=self.perm_var,
                                  foreground="#b91c1c", wraplength=820,
                                  justify="left")

        # ── Hotkey ───────────────────────────────────────────────────
        hf = ttk.LabelFrame(self.root, text="Hotkey (hold to record)")
        hf.pack(fill="x", padx=px, pady=py)
        row = ttk.Frame(hf)
        row.pack(fill="x", padx=ipx, pady=ipy)
        self.hotkey_display = ttk.Label(
            row, textvariable=self.hotkey_var, font=(mono, 14, "bold"),
        )
        self.hotkey_display.pack(side="left")
        self.hotkey_btn = ttk.Button(
            row, text="Change", command=self._start_hotkey_capture,
        )
        self.hotkey_btn.pack(side="right")
        self.root.bind("<KeyPress>", self._on_tk_keypress)
        self.root.bind("<KeyRelease>", self._on_tk_keyrelease)

        # ── Features ─────────────────────────────────────────────────
        ff = ttk.LabelFrame(self.root, text="Features")
        ff.pack(fill="x", padx=px, pady=py)
        for var, label in [
            (self.filler_var, "Remove fillers (um, uh, you know...)"),
            (self.backtrack_var, 'Smart corrections ("actually", "I mean")'),
            (self.lists_var, "Format numbered lists"),
            (self.punct_var, 'Smart punctuation ("comma", "period")'),
        ]:
            ttk.Checkbutton(
                ff, text=label, variable=var, command=self._save_features,
            ).pack(anchor="w", padx=16, pady=3)
        ttk.Frame(ff).pack(pady=2)

        # ── AI Rewriting ─────────────────────────────────────────────
        self.ai_frame = ttk.LabelFrame(self.root, text="AI Rewriting")
        self.ai_frame.pack(fill="x", padx=px, pady=py)

        ttk.Checkbutton(
            self.ai_frame, text="Enable AI rewriting",
            variable=self.ai_var, command=self._toggle_ai_section,
        ).pack(anchor="w", padx=16, pady=(6, 4))

        # Collapsible details
        self.ai_details = ttk.Frame(self.ai_frame)

        # Provider row
        prov_row = ttk.Frame(self.ai_details)
        prov_row.pack(fill="x", padx=20, pady=(6, 4))
        ttk.Label(prov_row, text="Provider:").pack(side="left")
        self.provider_combo = ttk.Combobox(
            prov_row, textvariable=self.provider_var,
            values=PROVIDERS, state="readonly", width=12,
        )
        self.provider_combo.pack(side="left", padx=(8, 0))
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_change)

        # API Key row
        key_row = ttk.Frame(self.ai_details)
        key_row.pack(fill="x", padx=20, pady=(4, 4))
        ttk.Label(key_row, text="API Key:").pack(side="left")
        cur_provider = self.provider_var.get()
        cur_key = self.cfg.get("ai_api_keys", {}).get(cur_provider, "")
        self.api_key_var = tk.StringVar(value=cur_key)
        self.api_key_entry = ttk.Entry(
            key_row, textvariable=self.api_key_var, show="*", width=36,
        )
        self.api_key_entry.pack(side="left", padx=(8, 0), fill="x", expand=True)

        # Style / Tone
        ttk.Label(
            self.ai_details, text="Style & tone instructions (optional):",
        ).pack(anchor="w", padx=20, pady=(8, 3))

        sf2 = ttk.Frame(self.ai_details)
        sf2.pack(fill="x", padx=20, pady=(0, 4))
        self.style_text = tk.Text(sf2, height=3, wrap="word", font=(mono, 9))
        self.style_text.pack(fill="x")
        saved_style = self.cfg.get("ai_style", "")
        if saved_style:
            self.style_text.insert("1.0", saved_style)

        ttk.Label(
            self.ai_details,
            text='e.g. "Professional and concise" or "Casual, friendly tone"',
            foreground="gray", font=("", 8),
        ).pack(anchor="w", padx=20, pady=(2, 6))

        # Apply button + feedback row
        apply_row = ttk.Frame(self.ai_details)
        apply_row.pack(fill="x", padx=20, pady=(0, 4))
        ttk.Button(
            apply_row, text="Apply Settings", command=self._apply_ai_config,
        ).pack(side="left")
        self.ai_feedback_var = tk.StringVar()
        self.ai_feedback_lbl = ttk.Label(
            apply_row, textvariable=self.ai_feedback_var,
            font=("", 9), foreground="green",
        )
        self.ai_feedback_lbl.pack(side="left", padx=(12, 0))

        # Error display row
        self.ai_error_var = tk.StringVar()
        self.ai_error_lbl = ttk.Label(
            self.ai_details, textvariable=self.ai_error_var,
            font=("", 8), foreground="red", wraplength=700, justify="left",
        )
        self.ai_error_lbl.pack(anchor="w", padx=20, pady=(0, 6))

        if self.ai_var.get():
            self.ai_details.pack(fill="x")

        # ── History ──────────────────────────────────────────────────
        hist_frame = ttk.LabelFrame(self.root, text="Recent Transcriptions")
        hist_frame.pack(fill="both", expand=True, padx=px, pady=py)

        lc = ttk.Frame(hist_frame)
        lc.pack(fill="both", expand=True, padx=ipx, pady=ipy)
        sb = ttk.Scrollbar(lc)
        sb.pack(side="right", fill="y")
        self.history_list = tk.Listbox(
            lc, yscrollcommand=sb.set, font=(mono, 9), selectmode="browse",
        )
        self.history_list.pack(fill="both", expand=True)
        sb.config(command=self.history_list.yview)
        self.history_list.bind("<Double-1>", self._copy_history_item)

        btn_row = ttk.Frame(hist_frame)
        btn_row.pack(fill="x", padx=ipx, pady=(0, ipy))
        ttk.Button(btn_row, text="Copy Selected",
                   command=self._copy_history_item).pack(side="left")
        ttk.Button(btn_row, text="Clear",
                   command=self._clear_history).pack(side="right")

        ttk.Label(
            self.root, text="Double-click a transcription to copy it",
            foreground="gray",
        ).pack(pady=(0, 8))

    # ── Hotkey capture ───────────────────────────────────────────────

    def _start_hotkey_capture(self):
        self.capturing_hotkey = True
        self._capture_keys.clear()
        self._capture_max.clear()
        self.hotkey_var.set("Press modifier keys...")
        self.hotkey_btn.config(state="disabled")
        self.root.focus_force()

    def _on_tk_keypress(self, event):
        if not self.capturing_hotkey:
            return
        name = normalize_tk(event.keysym)
        if name:
            self._capture_keys.add(name)
            self._capture_max.update(self._capture_keys)
            self.hotkey_var.set(hotkey_label(self._capture_keys))

    def _on_tk_keyrelease(self, event):
        if not self.capturing_hotkey:
            return
        name = normalize_tk(event.keysym)
        if name:
            self._capture_keys.discard(name)
        if not self._capture_keys and len(self._capture_max) >= 2:
            self.cfg["hotkey"] = sorted(self._capture_max)
            self.hotkey_set = set(self._capture_max)
            self.hotkey_var.set(hotkey_label(self.hotkey_set))
            save_config(self.cfg)
            self.capturing_hotkey = False
            self.hotkey_btn.config(state="normal")

    # ── AI config ────────────────────────────────────────────────────

    def _toggle_ai_section(self):
        if self.ai_var.get():
            self.ai_details.pack(fill="x")
        else:
            self.ai_details.pack_forget()
        self.cfg["ai_rewrite"] = self.ai_var.get()
        save_config(self.cfg)
        self.root.update_idletasks()

    def _on_provider_change(self, _event=None):
        # 1. Save the current API key under the PREVIOUSLY shown provider
        #    (provider_var already holds the new value at this point, so we
        #     must use _last_provider to avoid key cross-contamination)
        old_prov = self._last_provider
        self.cfg.setdefault("ai_api_keys", {})[old_prov] = self.api_key_var.get()

        # 2. Switch to the new provider and load its saved key
        new_prov = self.provider_var.get()
        self._last_provider = new_prov
        self.cfg["ai_provider"] = new_prov
        key = self.cfg["ai_api_keys"].get(new_prov, "")
        self.api_key_var.set(key)

        # Clear any stale error/feedback from the previous provider
        self.ai_error_var.set("")
        self.ai_feedback_var.set("(unsaved)")
        self.ai_feedback_lbl.config(foreground="gray")

    def _apply_ai_config(self):
        """Explicitly save all AI settings and give visual confirmation."""
        self._save_ai_config()
        self.ai_feedback_var.set("✓ Settings applied")
        self.ai_feedback_lbl.config(foreground="green")
        self.ai_error_var.set("")
        # Clear confirmation after 3 s
        self.root.after(3000, lambda: self.ai_feedback_var.set(""))

    def _save_ai_config(self):
        provider = self.provider_var.get()
        self._last_provider = provider
        self.cfg["ai_rewrite"] = self.ai_var.get()
        self.cfg["ai_provider"] = provider
        self.cfg.setdefault("ai_api_keys", {})
        self.cfg["ai_api_keys"][provider] = self.api_key_var.get()
        self.cfg["ai_style"] = self.style_text.get("1.0", "end-1c").strip()
        save_config(self.cfg)

    def _save_features(self):
        self.cfg["remove_fillers"] = self.filler_var.get()
        self.cfg["backtrack"] = self.backtrack_var.get()
        self.cfg["numbered_lists"] = self.lists_var.get()
        self.cfg["smart_punctuation"] = self.punct_var.get()
        save_config(self.cfg)

    # ── History ──────────────────────────────────────────────────────

    def _add_history(self, text):
        ts = datetime.now().strftime("%H:%M:%S")
        self.history.append((ts, text))
        if len(self.history) > MAX_HISTORY:
            self.history.pop(0)
            self.history_list.delete(0)
        self.history_list.insert("end", f"[{ts}]  {text[:200]}")
        self.history_list.see("end")

    def _copy_history_item(self, _event=None):
        sel = self.history_list.curselection()
        if sel:
            _, text = self.history[sel[0]]
            pyperclip.copy(text)

    def _clear_history(self):
        self.history.clear()
        self.history_list.delete(0, "end")

    # ── Model ────────────────────────────────────────────────────────

    def _load_model(self):
        if mlx_whisper is not None:
            try:
                # First run: the GPU model (~1.6 GB) is downloaded from
                # Hugging Face; the status line shows the MB so far.
                fetch_model(MLX_REPO, lambda mb: setattr(
                    self, "_pending_status", ("downloading", mb)))
                self._pending_status = "loading"
                # Warm-up on half a second of silence preloads the weights
                # so the first real dictation is already fast.
                mlx_whisper.transcribe(
                    np.zeros(SAMPLE_RATE // 2, dtype=np.float32),
                    path_or_hf_repo=MLX_REPO)
                self.model = "mlx"
                print("[i] whisper backend: MLX large-v3-turbo (GPU)",
                      flush=True)
                self._pending_status = "ready"
                return
            except Exception as e:
                print(f"[!] MLX init failed, using CPU fallback: {e}",
                      flush=True)
        try:
            sz = self.cfg.get("model_size", "base")
            self.model = WhisperModel(sz, device="cpu", compute_type="int8")
            self._pending_status = "ready"
        except Exception as e:
            # Typically: first run with no internet, so neither model could
            # be downloaded. Say so instead of "Loading model..." forever.
            print(f"[!] model load failed: {e}", flush=True)
            self._pending_status = "error"

    # ── Audio & Transcription ────────────────────────────────────────

    def _audio_cb(self, indata, frames, time_info, status):
        if self.recording:
            self.audio_frames.append(indata.copy())
            level = float(np.abs(indata).mean()) * 15
            self.overlay.set_audio_level(level)

    def _play_beep(self, path):
        """Play a cue tone via `afplay` — a SEPARATE process with its own
        audio path, so it never shares PortAudio with the mic InputStream.
        (Playing via sounddevice deadlocked CoreAudio's HAL mutex when the
        output and input streams stopped concurrently, freezing the app.)
        Fire-and-forget: Popen returns immediately and can never block us."""
        try:
            subprocess.Popen(
                ["/usr/bin/afplay", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[!] beep failed: {e}", flush=True)

    def _ensure_stream(self):
        """Create the mic InputStream ONCE and reuse it for the app's life.
        A brand-new stream per dictation churned CoreAudio's device
        open/start/stop path and eventually deadlocked its HAL mutex
        (stop() ↔ the HAL IO thread on the same lock). One long-lived stream,
        only started/stopped (never closed) between dictations, removes that
        churn. Stopping — not closing — still turns the mic indicator off."""
        if self.stream is None:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                callback=self._audio_cb,
            )

    def _start_recording(self):
        with self.lock:
            if self.recording or self.busy:
                return
            self.recording = True
            self.audio_frames = []

        # Rising cue on start. Played before opening the mic; any brief tail
        # that bleeds in is caught by the RMS silence gate / ignored by Whisper.
        self._play_beep(BEEP_START)

        # Serialise start/stop so they never overlap across the pynput and
        # transcription threads (that overlap was half of the race).
        with self._audio_lock:
            self._ensure_stream()
            if not self.stream.active:
                self.stream.start()
        self.overlay.request_recording()
        self._pending_status = "recording"

    def _stop_and_transcribe(self):
        with self.lock:
            if not self.recording:
                return
            self.recording = False
            self.busy = True

        # Switch overlay to loading spinner
        self.overlay.request_loading()
        self._pending_status = "transcribing"

        # Stop capturing (mic indicator off) but keep the stream object so the
        # next dictation just restarts it — no per-use open/close of the device.
        with self._audio_lock:
            if self.stream is not None and self.stream.active:
                self.stream.stop()

        # Falling cue on release. Mic stream is already closed, so it is
        # never captured; fires on every release regardless of what follows.
        self._play_beep(BEEP_STOP)

        if not self.audio_frames:
            self.busy = False
            self.overlay.request_hide()
            self._pending_status = "ready"
            return

        audio = np.concatenate(self.audio_frames, axis=0).flatten()
        if len(audio) < SAMPLE_RATE * 0.3:
            self.busy = False
            self.overlay.request_hide()
            self._pending_status = "ready"
            return
        # Near-silence gate: Whisper hallucinates fluent nonsense on silent
        # audio (the MLX path has no VAD), so bail out before transcribing.
        if float(np.sqrt(np.mean(audio ** 2))) < 0.003:
            self.busy = False
            self.overlay.request_hide()
            self._pending_status = "ready"
            return

        try:
            # language=None -> Whisper auto-detects per utterance, so Spanish
            # speech comes back in Spanish and English in English.
            # condition_on_previous_text=False stops the repeated-phrase
            # loops Whisper falls into on short/pausey dictation.
            if self.model == "mlx":
                # GPU path: transcribe the in-memory float32 buffer directly
                # (no ffmpeg dependency, no extra file read).
                result = mlx_whisper.transcribe(
                    audio, path_or_hf_repo=MLX_REPO, language=None,
                    temperature=0.0, condition_on_previous_text=False,
                    initial_prompt=self.cfg.get("vocabulary") or None,
                )
                raw = result["text"].strip()
            else:
                # CPU path: same in-memory buffer (16 kHz float32). Passing a
                # WAV path made faster-whisper decode it with PyAV, whose
                # newer releases dropped an argument it uses.
                segments, _ = self.model.transcribe(
                    audio, beam_size=1, language=None, vad_filter=True,
                    condition_on_previous_text=False, temperature=0.0,
                    initial_prompt=self.cfg.get("vocabulary") or None,
                )
                raw = " ".join(s.text for s in segments).strip()

            if raw:
                # Email mode: if the dictation opens with "estoy escribiendo
                # un email" (or similar), strip that lead-in and format the
                # rest as an email via the AI step.
                email_mode, raw = detect_email_mode(raw)
                if email_mode:
                    print("[i] email mode: on", flush=True)

                # Step 1: Local text processing
                text = process_text(
                    raw,
                    remove_fillers_on=self.cfg["remove_fillers"],
                    backtrack_on=self.cfg["backtrack"],
                    numbered_lists_on=self.cfg["numbered_lists"],
                    smart_punctuation_on=self.cfg["smart_punctuation"],
                )

                # Step 2: AI rewriting (if enabled). Email mode swaps the
                # casual-cleanup style for the email-formatting style.
                provider = self.cfg.get("ai_provider", "Gemini")
                # Prefer an environment variable (e.g. WISPRTOOL_GEMINI_API_KEY)
                # so the key never has to be stored on disk; fall back to the
                # value in config.json.
                api_key = (
                    os.environ.get(
                        f"WISPRTOOL_{provider.upper()}_API_KEY", ""
                    ).strip()
                    or self.cfg.get("ai_api_keys", {}).get(provider, "").strip()
                )
                if self.cfg.get("ai_rewrite") and api_key:
                    self._pending_status = "polishing"
                    try:
                        style = EMAIL_STYLE if email_mode \
                            else self.cfg.get("ai_style", "")
                        text = rewrite_with_ai(text, provider, api_key, style)
                        self._pending_ai_error = ""  # Clear any previous error
                    except urllib.error.HTTPError as e:
                        body = e.read().decode("utf-8", errors="replace")
                        # Try to extract a clean message from JSON error body
                        try:
                            msg = json.loads(body).get("error", {}).get(
                                "message", body[:200]
                            )
                        except Exception:
                            msg = body[:200]
                        self._pending_ai_error = (
                            f"{provider} HTTP {e.code}: {msg}"
                        )
                    except Exception as e:
                        self._pending_ai_error = f"{provider} error: {e}"
                elif self.cfg.get("ai_rewrite") and not api_key:
                    self._pending_ai_error = (
                        f"No API key set for {provider}. "
                        "Enter your key and click Apply Settings."
                    )

                # Step 3: Paste at cursor.
                # First make sure NO modifier is still held: if the user is
                # still pressing (or has just pressed) a key when the synthetic
                # paste fires, Cmd+V turns into Cmd+Alt+V / Ctrl+Cmd+V and
                # pastes nothing — silently dropping the whole transcription.
                # Wait briefly for the hotkey to be released, then hard-release
                # every modifier so the shortcut is always clean.
                self._release_modifiers_for_paste()

                old_clip = pyperclip.paste()
                pyperclip.copy(text)
                pyautogui.hotkey(*PASTE_KEYS)
                # Keep the transcription on the clipboard a touch longer so the
                # paste reliably lands before the previous clipboard is
                # restored — and if anything still went wrong, the text is right
                # there to paste manually. It is never lost.
                time.sleep(0.15)
                pyperclip.copy(old_clip)

                self._pending_history = text

        except Exception as e:
            print(f"[!] Transcription error: {e}")
        finally:
            self.busy = False
            self.overlay.request_hide()
            self._pending_status = "ready"

    def _release_modifiers_for_paste(self, timeout=0.6):
        """Guarantee a clean Cmd/Ctrl+V paste: wait (briefly) for the user to
        let go of the hotkey, then force-release every modifier key. Without
        this, a modifier still physically held when the paste fires corrupts the
        shortcut and the transcription is dropped — the reported bug where
        pressing any key while it is transcribing 'cancels' the result."""
        deadline = time.time() + timeout
        while time.time() < deadline and (self.pressed_keys & self.hotkey_set):
            time.sleep(0.02)
        for mod in (
            "ctrl", "ctrlleft", "ctrlright",
            "alt", "altleft", "altright", "option",
            "shift", "shiftleft", "shiftright",
            "command", "winleft", "winright",
        ):
            try:
                pyautogui.keyUp(mod)
            except Exception:
                pass

    # ── macOS permissions ────────────────────────────────────────────

    PERM_HELP = {
        "Microphone": "Microphone is off for WhisperTool, so it can't hear "
                      "you. Turn it on in System Settings › Privacy & "
                      "Security › Microphone.",
        "Accessibility": "WhisperTool can't paste the text yet. Turn it on "
                         "in System Settings › Privacy & Security › "
                         "Accessibility, then quit and reopen WhisperTool.",
        "Input Monitoring": "WhisperTool can't see the hotkey yet. Turn it "
                            "on in System Settings › Privacy & Security › "
                            "Input Monitoring, then quit and reopen "
                            "WhisperTool.",
    }

    def _warn_permission(self, name):
        """Any thread: queue a banner line for a permission that is off."""
        print(f"[!] permission missing: {name}", flush=True)
        if name not in self._perm_missing:
            self._perm_missing.append(name)
            self._pending_perm = True

    def _mic_answer(self, ok):
        print(f"[i] mic granted: {ok}", flush=True)
        if not ok:
            self._warn_permission("Microphone")

    def _check_listener(self):
        # Without Input Monitoring macOS refuses pynput's event tap and the
        # listener thread just ends: ask for it and say where to turn it on.
        if self.listener is not None and not self.listener.is_alive():
            try:
                from Quartz import CGRequestListenEventAccess
                CGRequestListenEventAccess()
            except Exception:
                pass
            self._warn_permission("Input Monitoring")

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        if NSApplication is not None:
            try:
                NSApplication.sharedApplication() \
                    .activateIgnoringOtherApps_(True)
            except Exception:
                pass

    # ── Pynput handlers ──────────────────────────────────────────────

    def _on_press(self, key):
        # While a transcription is in flight (busy), ignore all key presses so
        # nothing the user types can re-trigger recording or pollute the
        # pressed-keys state. The transcription always runs to completion.
        if self.capturing_hotkey or self.busy:
            return
        name = normalize_pynput(key)
        if name:
            self.pressed_keys.add(name)
            if self.pressed_keys >= self.hotkey_set:
                self._start_recording()

    def _on_release(self, key):
        if self.capturing_hotkey:
            return
        name = normalize_pynput(key)
        if name:
            if self.recording and name in self.hotkey_set:
                threading.Thread(
                    target=self._stop_and_transcribe, daemon=True,
                ).start()
            self.pressed_keys.discard(name)

    # ── Main-thread tick ─────────────────────────────────────────────

    def _tick(self):
        st = self._pending_status
        if st:
            self._pending_status = None
            dot = self.status_dot
            dot.delete("dot")
            colours = {
                "loading": ("gray", "Loading model..."),
                "ready": ("#22c55e", "Ready"),
                "recording": ("#ef4444", "Recording..."),
                "transcribing": ("#f59e0b", "Transcribing..."),
                "polishing": ("#8b5cf6", "AI polishing..."),
                "error": ("#ef4444", "Couldn't download the speech model. "
                          "Check your internet connection and reopen "
                          "WhisperTool."),
            }
            if isinstance(st, tuple):  # ("downloading", mb so far)
                c, lbl = "#3b82f6", (
                    f"Downloading the speech model (first run only, "
                    f"{MLX_SIZE}): {st[1]:,.0f} MB so far...")
            else:
                c, lbl = colours.get(st, ("#22c55e", "Ready"))
            dot.create_oval(2, 2, 12, 12, fill=c, tags="dot")
            self.status_var.set(lbl)

        h = self._pending_history
        if h:
            self._pending_history = None
            self._add_history(h)

        ai_err = self._pending_ai_error
        if ai_err is not None:
            self._pending_ai_error = None
            self.ai_error_var.set(ai_err)
            if ai_err:
                self.ai_feedback_var.set("")

        # Dock-icon click while already running: applaunch.sh touches the
        # .show flag (there's no separate Python Dock icon to activate any
        # more). Poll at ~2 Hz, not every 30 ms tick, and raise the window.
        now = time.monotonic()
        if now - self._last_show_check > 0.5:
            self._last_show_check = now
            if os.path.exists(SHOW_FLAG):
                try:
                    os.unlink(SHOW_FLAG)
                except OSError:
                    pass
                self._show_window()

        if self._pending_perm:
            self._pending_perm = False
            self.perm_var.set("\n".join(
                "⚠ " + self.PERM_HELP[p] for p in self._perm_missing))
            self.perm_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        self.overlay.tick()
        self.root.after(30, self._tick)

    # ── Lifecycle ────────────────────────────────────────────────────

    def _on_close(self):
        self._save_ai_config()
        if self.listener is not None:
            self.listener.stop()
        # Tear the mic stream down once, on the main thread, before exit — a
        # controlled close beats leaving it to PortAudio's atexit Pa_Terminate
        # (which is where the CoreAudio HAL teardown deadlocked).
        with self._audio_lock:
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ── Selftest (packaged app, no human needed) ────────────────────────

def selftest(out):
    """`WhisperTool --selftest out.json`: checks the build end to end WITHOUT
    the global hotkey, the microphone or any keystroke/paste, and writes
    what it saw as JSON (tools/seguridad.py reads it):
      1. every native piece imports (MLX + its Metal kernels on the GPU,
         faster-whisper/CTranslate2/ONNX Runtime/PyAV, PortAudio, pynput,
         pyobjc) — imported, never started;
      2. config.json is written 0600 (in a temp folder, not the user's);
      3. text_processor + email mode give the expected text;
      4. if the GPU model is already cached, it transcribes English speech
         made with `say` (no download of gigabytes just for a test);
      5. first-run download path: fetches the small faster-whisper "tiny"
         model (~75 MB) into a temp cache with the progress callback, and
         transcribes the same audio with it on the CPU (the fallback path);
      6. opens the real window (hooks off) and the capsule overlay for
         WT_SELFTEST_HOLD seconds so they can be screenshotted, then closes.
    """
    global CONFIG_PATH, BEEP_START, BEEP_STOP, SHOW_FLAG
    import importlib
    import shutil
    r = {"frozen": FROZEN, "data_dir": APP_DIR, "version": APP_VERSION}

    def dump():
        with open(out, "w") as f:
            json.dump(r, f, indent=1, ensure_ascii=False)

    def err(e):
        return f"{type(e).__name__}: {e}"[:300]

    tmp = tempfile.mkdtemp(prefix="whispertool-selftest-")
    CONFIG_PATH = os.path.join(tmp, "config.json")
    BEEP_START = os.path.join(tmp, "beep_start.wav")
    BEEP_STOP = os.path.join(tmp, "beep_stop.wav")
    SHOW_FLAG = os.path.join(tmp, ".show")

    # 1. Native pieces
    r["imports"] = {}
    for mod in ("mlx.core", "mlx_whisper", "faster_whisper", "ctranslate2",
                "onnxruntime", "av", "sounddevice", "pynput.keyboard",
                "pyautogui", "pyperclip", "AppKit", "Quartz", "AVFoundation",
                "HIServices", "huggingface_hub", "hf_xet", "certifi"):
        try:
            importlib.import_module(mod)
            r["imports"][mod] = "ok"
        except Exception as e:
            r["imports"][mod] = err(e)
    try:
        import mlx.core as mx
        r["mlx_gpu"] = {"device": str(mx.default_device()),
                        "sum": float((mx.array([1.0, 2.0, 3.0]) * 2).sum())}
    except Exception as e:
        r["mlx_gpu"] = {"error": err(e)}
    r["portaudio"] = sd.get_portaudio_version()[1]
    dump()

    # 2. Config file permissions
    try:
        cfg = load_config()
        cfg["ai_api_keys"]["Gemini"] = "selftest-not-a-real-key"
        save_config(cfg)
        r["config"] = {"mode": oct(os.stat(CONFIG_PATH).st_mode & 0o777),
                       "roundtrip": load_config() == cfg}
    except Exception as e:
        r["config"] = {"error": err(e)}

    # 3. Text processing
    sample = ("um so I want to meet at 2 actually 3 period "
              "send it to John I mean Mike")
    r["text_processor"] = {"in": sample, "out": process_text(sample)}
    r["email_mode"] = list(detect_email_mode(
        "Estoy escribiendo un email, hola Ana, nos vemos mañana"))
    dump()

    # 4-5. Speech made with `say`
    phrase = "Hello, this is a quick test of the dictation tool."
    aiff, wav = os.path.join(tmp, "say.aiff"), os.path.join(tmp, "say.wav")
    subprocess.run(["/usr/bin/say", "-v", "Samantha", "-o", aiff, phrase],
                   check=True, timeout=60)
    subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@16000",
                    "-c", "1", aiff, wav], check=True, timeout=60)
    with wave.open(wav) as wf:
        audio = np.frombuffer(wf.readframes(wf.getnframes()),
                              np.int16).astype(np.float32) / 32768.0
    r["say"] = {"phrase": phrase, "secs": round(len(audio) / SAMPLE_RATE, 1)}
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(MLX_REPO, local_files_only=True)
        cached = True
    except Exception:
        cached = False
    if not cached:
        r["mlx"] = {"skip": "modelo no en caché"}
        # Step 6 must not download 1.6 GB either: the window opens without
        # loading any model.
        App._load_model = lambda self: setattr(self, "model", "skipped")
    else:
        try:
            t = time.time()
            res = mlx_whisper.transcribe(
                audio, path_or_hf_repo=MLX_REPO, language=None,
                temperature=0.0, condition_on_previous_text=False)
            r["mlx"] = {"text": res["text"].strip(),
                        "language": res.get("language"),
                        "secs": round(time.time() - t, 1)}
        except Exception as e:
            r["mlx"] = {"error": err(e)}
    dump()
    try:
        prog, t = [], time.time()
        hf = os.path.join(tmp, "hf")
        path = fetch_model("Systran/faster-whisper-tiny", prog.append,
                           cache_dir=hf)
        r["download"] = {"repo": "Systran/faster-whisper-tiny",
                         "secs": round(time.time() - t, 1),
                         "files": sorted(os.listdir(path)),
                         "progress_calls": len(prog),
                         "progress_mb": [round(x, 1) for x in
                                         prog[::max(1, len(prog) // 8)]]
                         + [round(prog[-1], 1)] if prog else []}
        m = WhisperModel(path, device="cpu", compute_type="int8")
        t = time.time()
        segs, info = m.transcribe(audio, beam_size=1, vad_filter=True,
                                  language=None, temperature=0.0,
                                  condition_on_previous_text=False)
        r["cpu"] = {"text": " ".join(x.text for x in segs).strip(),
                    "language": info.language,
                    "secs": round(time.time() - t, 1)}
    except Exception as e:
        r["download"] = r.get("download") or {"error": err(e)}
        r["cpu"] = {"error": err(e)}
    dump()

    # 6. The real window + overlay, hooks off
    hold = float(os.environ.get("WT_SELFTEST_HOLD", "0"))
    app = App(hooks=False)
    t0 = time.time()

    def windows():
        return [{"title": str(w.title()), "number": int(w.windowNumber()),
                 "visible": bool(w.isVisible())}
                for w in NSApplication.sharedApplication().windows()]

    def close():
        r["ui"]["status_at_close"] = app.status_var.get()
        r["ui"]["overlay_visible"] = bool(
            app.overlay._panel is not None and app.overlay._panel.isVisible())
        r["ui"]["windows"] = windows()
        dump()
        app._on_close()

    def probe():
        if app.model is None and time.time() - t0 < 120:
            app.root.after(300, probe)
            return
        app.overlay.request_loading()
        r["ui"] = {"model": app.model if isinstance(app.model, str)
                   else type(app.model).__name__,
                   "load_secs": round(time.time() - t0, 1),
                   "title": app.root.title(), "windows": windows()}
        dump()
        app.root.after(int(hold * 1000) + 400, close)

    app.root.after(300, probe)
    app.run()
    r["ui"]["closed"] = True
    dump()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(
            tempfile.gettempdir(), "whispertool-selftest.json"))
        sys.exit(0)
    app = App()
    app.run()
