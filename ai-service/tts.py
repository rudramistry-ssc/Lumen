"""Text to speech with the voices built into the computer, so it works offline.

macOS uses `say`, Windows uses the System.Speech engine through PowerShell,
Linux uses `espeak-ng` if installed. All three write a WAV file.
"""

import os
import platform
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

TIMEOUT_SECONDS = 60

# Windows: paths come in through env vars so no quoting can break the script.
_WINDOWS_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq $env:TTS_LANG } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.SetOutputToWaveFile($env:TTS_OUT)
$s.Speak([IO.File]::ReadAllText($env:TTS_IN, [Text.Encoding]::UTF8))
$s.Dispose()
"""


class TtsError(Exception):
    """No speech engine, or the engine failed."""


def engine() -> str | None:
    # Which engine this computer has, or None.
    system = platform.system()
    if system == "Darwin" and shutil.which("say"):
        return "macos-say"
    if system == "Windows" and shutil.which("powershell"):
        return "windows-sapi"
    if shutil.which("espeak-ng"):
        return "espeak-ng"
    return None


# Natural-sounding voices that ship with macOS, best first.
_MAC_PREFERRED = {"en": ["Samantha", "Alex", "Daniel", "Karen", "Moira"], "fr": ["Amélie", "Thomas", "Audrey"]}
# Novelty voices macOS lists alongside the real ones; never pick these.
_MAC_NOVELTY = {"Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Good News", "Jester",
                "Organ", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox", "Fred", "Junior", "Ralph", "Kathy"}


@lru_cache
def _mac_voice(language: str) -> str | None:
    # `say -v ?` lines look like: "Amélie              fr_CA    # Bonjour…".
    listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    voices = [(name.strip(), locale) for name, locale in re.findall(r"^(.+?)\s{2,}([a-z]{2,3}_[A-Z]{2,3})\s", listing, re.M)]
    available = {name for name, locale in voices if locale.startswith(f"{language}_")}
    for name in _MAC_PREFERRED.get(language, []):
        if name in available:
            return name
    # Otherwise any real voice for the language, Canadian first.
    for prefix in (f"{language}_CA", f"{language}_"):
        for name, locale in voices:
            if locale.startswith(prefix) and name.split(" (")[0] not in _MAC_NOVELTY:
                return name
    return None


def synthesize(text: str, language: str) -> bytes:
    """Return WAV bytes for `text`, using a voice for `language` when one exists."""
    kind = engine()
    if kind is None:
        raise TtsError("No speech engine found on this computer")
    language = "fr" if language == "fr" else "en"   # "mixed" reads with the English voice

    with tempfile.TemporaryDirectory() as tmp:
        source, out = Path(tmp) / "in.txt", Path(tmp) / "out.wav"
        source.write_text(text, encoding="utf-8")

        if kind == "macos-say":
            command = ["say", "-o", str(out), "--file-format=WAVE", "--data-format=LEI16@22050", "-f", str(source)]
            voice = _mac_voice(language)
            if voice:
                command[1:1] = ["-v", voice]
            env = None
        elif kind == "windows-sapi":
            command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_SCRIPT]
            env = {**os.environ, "TTS_IN": str(source), "TTS_OUT": str(out), "TTS_LANG": language}
        else:
            command = ["espeak-ng", "-v", language, "-w", str(out), "-f", str(source)]
            env = None

        try:
            subprocess.run(command, check=True, capture_output=True, timeout=TIMEOUT_SECONDS, env=env)
        except subprocess.TimeoutExpired as exc:
            raise TtsError("Speech engine timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode(errors="replace").strip()[:200]
            raise TtsError(f"Speech engine failed: {detail}") from exc

        if not out.is_file() or out.stat().st_size == 0:
            raise TtsError("Speech engine produced no audio")
        return out.read_bytes()
