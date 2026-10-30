"""Offline whisper.cpp adapter; standard library only, temporary audio only."""
from array import array
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave
import hashlib
import re
from .provision import MODEL, RUNTIME, executable, model_path
from .metrics import MemorySampler


def wav_info(audio, max_seconds=60, max_bytes=8_000_000):
    if not isinstance(audio, bytes) or not audio:
        raise ValueError("empty_audio: provide nonempty WAV bytes")
    if len(audio) > max_bytes: raise ValueError("input_too_large: maximum input size exceeded")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getcomptype()) != (16000, 1, 2, "NONE"):
                raise ValueError("unsupported_format: require 16 kHz mono PCM16 WAV; convert explicitly first")
            duration = wav.getnframes() / 16000
            if duration <= 0: raise ValueError("empty_audio: WAV contains no samples")
            if duration > max_seconds: raise ValueError("recording_too_long: maximum duration exceeded")
            pcm = wav.readframes(wav.getnframes())
            if len(pcm) != wav.getnframes() * 2: raise ValueError("corrupt_audio: truncated WAV payload")
    except (wave.Error, EOFError) as exc:
        raise ValueError("unsupported_or_corrupt_audio: require PCM WAV") from exc
    samples = array("h", pcm)
    if sys.byteorder != "little": samples.byteswap()
    rms = math.sqrt(sum(float(x) * x for x in samples) / len(samples)) / 32768
    return duration, 20 * math.log10(max(rms, 1e-12))


def windows_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class WhisperSTT:
    def __init__(self, *, cli=None, model=None, threads=4, timeout=120, max_seconds=60):
        self.cli = Path(cli) if cli else executable()
        self.model = Path(model) if model else model_path()
        self.threads, self.timeout, self.max_seconds = threads, timeout, max_seconds
        if threads < 1 or timeout <= 0 or max_seconds <= 0: raise ValueError("Options must be positive")
        self.model_hash = None
        self.cli_hash = None
        if self.model.is_file():
            with self.model.open("rb") as source: self.model_hash = hashlib.file_digest(source, "sha256").hexdigest()
        if self.cli.is_file():
            with self.cli.open("rb") as source: self.cli_hash = hashlib.file_digest(source, "sha256").hexdigest()

    def transcribe(self, audio_bytes, language="auto"):
        started = time.perf_counter()
        result = {"status": "error", "text": "", "language": None, "requested_language": language,
                  "audio_seconds": None, "processing_seconds": None, "segments": [], "warnings": [], "error": None,
                  "model": {"file": self.model.name, "sha256": self.model_hash},
                  "runtime": {"executable": self.cli.name, "sha256": self.cli_hash}, "mode": "cli_fresh_context"}
        if self.model_hash == MODEL["sha256"]: result["model"]["revision"] = MODEL["revision"]
        if "b5454" in self.cli.parts:
            result["runtime"].update(release=RUNTIME["tag"], source_commit=RUNTIME["commit"])
        try:
            if language not in ("auto", "en", "fr"): raise ValueError("unsupported_language: use auto, en or fr")
            duration, dbfs = wav_info(audio_bytes, self.max_seconds)
            result.update(audio_seconds=duration, rms_dbfs=round(dbfs, 2))
            if dbfs < -90:
                result.update(status="no_speech", warnings=["Near-digital silence; transcription skipped. This is not general voice activity detection."])
                return result
            if not self.cli.is_file(): raise FileNotFoundError("whisper-cli missing; provision once or configure SIGNSPEAK_WHISPER_CLI")
            if not self.model.is_file(): raise FileNotFoundError("Whisper model missing; provision once or configure SIGNSPEAK_WHISPER_MODEL")
            with tempfile.TemporaryDirectory(prefix="signspeak-stt-") as directory:
                source, output = Path(directory) / "input.wav", Path(directory) / "transcript"
                source.write_bytes(audio_bytes)
                command = [str(self.cli), "-m", str(self.model), "-f", str(source), "-l", language,
                           "-t", str(self.threads), "-ng", "-sns", "-mc", "0", "-bo", "5", "-bs", "5",
                           "-tp", "0", "-tpi", "0", "-ojf", "-of", str(output)]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=windows_flags())
                with MemorySampler(process) as memory:
                    try:
                        stdout, stderr = process.communicate(timeout=self.timeout)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.communicate()
                        raise
                result["native_peak_working_set_mib"] = round(memory.peak / 1048576, 2) if memory.peak else None
                logs = stderr.decode("utf-8", errors="replace")
                match = re.search(r"load time\s*=\s*([\d.]+) ms", logs)
                result["native_model_load_seconds"] = float(match[1]) / 1000 if match else None
                if process.returncode: raise RuntimeError("whisper-cli failed: " + logs[-1200:])
                data = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            result["language"] = data.get("result", {}).get("language", language if language != "auto" else None)
            segments = data.get("transcription")
            if not isinstance(segments, list): raise ValueError("invalid_runtime_output: missing transcription list")
            for segment in segments:
                result["segments"].append({"text": segment["text"].strip(), "offsets_ms": segment.get("offsets")})
            result["text"] = " ".join(s["text"] for s in result["segments"]).strip()
            result["status"] = "ok" if result["text"] else "no_speech"
            if duration < 2: result["warnings"].append("Short speech: automatic language detection may be unreliable.")
            if result["language"] not in ("en", "fr"):
                result["warnings"].append("Detected language outside English/French scope; review before use.")
            result["warnings"].append("Unverified hypothesis: review critical names and numbers; OCR agreement is not verification.")
            if re.search(r"\d", result["text"]):
                result["warnings"].append("Contains numeric readings; confirm against the recording before acting on them.")
        except subprocess.TimeoutExpired:
            result["error"] = "timeout: whisper-cli exceeded timeout and was terminated"
        except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
            result.update(status="error", text="", segments=[], error=str(exc))
        finally:
            result["processing_seconds"] = round(time.perf_counter() - started, 4)
        return result


def transcribe(audio_bytes, language="auto", **options):
    return WhisperSTT(**options).transcribe(audio_bytes, language)


def convert_audio(audio_bytes, *, ffmpeg=None, max_seconds=60, max_bytes=8_000_000):
    """Explicit optional WebM/Opus boundary; never called by transcribe()."""
    if not audio_bytes or len(audio_bytes) > max_bytes: raise ValueError("Empty or oversized input")
    command = [str(ffmpeg or os.getenv("SIGNSPEAK_FFMPEG", "ffmpeg")), "-nostdin", "-hide_banner", "-loglevel", "error",
               "-protocol_whitelist", "pipe", "-i", "pipe:0", "-t", str(max_seconds + 1), "-vn", "-ac", "1", "-ar", "16000",
               "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"]
    try:
        process = subprocess.run(command, input=audio_bytes, capture_output=True, timeout=30, creationflags=windows_flags())
    except FileNotFoundError as exc:
        raise ValueError("FFmpeg missing: configure SIGNSPEAK_FFMPEG for optional conversion") from exc
    if process.returncode: raise ValueError("Audio conversion failed: " + process.stderr.decode(errors="replace")[-500:])
    if len(process.stdout) > max_seconds * 32000: raise ValueError("Recording exceeds maximum duration")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(process.stdout)
    wav_info(output.getvalue(), max_seconds)
    return output.getvalue()
