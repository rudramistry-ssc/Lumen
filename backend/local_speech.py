"""CPU-only Whisper + Kokoro. Audio/text never leave this app server."""
import io
import logging
import os
import re
import unicodedata
from pathlib import Path
from threading import Lock
import wave
from collections import OrderedDict
from hashlib import sha256
from time import monotonic

from fastapi import HTTPException

# Docker mounts the verified model volume at /models (see compose.yaml).
MODELS = Path(os.getenv("LUMEN_MODELS_DIR", str(Path(__file__).resolve().parents[1] / "models")))
MAX_AUDIO_SECONDS = 90
_stt = None
_tts = None
_g2p_en = None
_g2p_fr = None
_stt_lock = Lock()
_tts_lock = Lock()
_audio_cache = OrderedDict()
_audio_cache_lock = Lock()
_audio_cache_bytes = 0
CACHE_MAX_BYTES = 24 * 1024 * 1024
CACHE_TTL_SECONDS = 600


def _cached_audio(key):
    global _audio_cache_bytes
    with _audio_cache_lock:
        entry = _audio_cache.get(key)
        if entry is None:
            return None
        created, audio = entry
        if monotonic() - created >= CACHE_TTL_SECONDS:
            _audio_cache.pop(key)
            _audio_cache_bytes -= len(audio)
            return None
        _audio_cache.move_to_end(key)
        return audio


def _remember_audio(key, audio):
    global _audio_cache_bytes
    if len(audio) > CACHE_MAX_BYTES:
        return
    with _audio_cache_lock:
        old = _audio_cache.pop(key, None)
        if old is not None:
            _audio_cache_bytes -= len(old[1])
        _audio_cache[key] = (monotonic(), audio)
        _audio_cache_bytes += len(audio)
        while _audio_cache_bytes > CACHE_MAX_BYTES or len(_audio_cache) > 128:
            _, (_, evicted) = _audio_cache.popitem(last=False)
            _audio_cache_bytes -= len(evicted)


def _missing():
    return HTTPException(503, "Local speech models are missing. Run the models setup container (docker compose up models).")


def speech_status():
    from importlib.util import find_spec
    return {
        "local_only": True,
        "stt": bool(find_spec("faster_whisper") and (MODELS / "whisper-base/model.bin").is_file()),
        "tts": bool(all(find_spec(name) for name in ("kokoro_onnx", "misaki", "spacy", "en_core_web_sm"))
                    and all((MODELS / "kokoro" / name).is_file()
                    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"))),
    }


def decode_audio(data):
    """Decode browser WebM/Opus, Ogg or MP4 in memory, with a duration cap."""
    import av
    import numpy as np
    frames, count = [], 0
    try:
        with av.open(io.BytesIO(data)) as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in container.decode(audio=0):
                for mono in resampler.resample(frame):
                    samples = mono.to_ndarray().flatten()
                    count += samples.size
                    if count > MAX_AUDIO_SECONDS * 16000:
                        raise HTTPException(413, "Record a question shorter than 90 seconds.")
                    frames.append(samples)
            for mono in resampler.resample(None):
                frames.append(mono.to_ndarray().flatten())
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "This recording could not be read. Please record again.") from None
    if not frames:
        raise HTTPException(422, "No speech was recorded. Please try again.")
    return np.concatenate(frames).astype(np.float32) / 32768.0


def transcribe(data: bytes, language: str) -> str:
    global _stt
    if not _stt_lock.acquire(blocking=False):
        raise HTTPException(429, "Another recording is being transcribed. Please try again shortly.")
    try:
        if not speech_status()["stt"]:
            raise _missing()
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        from faster_whisper import WhisperModel
        if _stt is None:
            _stt = WhisperModel(str(MODELS / "whisper-base"), device="cpu", compute_type="int8",
                                cpu_threads=min(4, os.cpu_count() or 2), local_files_only=True)
        samples = decode_audio(data)
        segments, _ = _stt.transcribe(samples, language=language, beam_size=3,
                                     vad_filter=True, condition_on_previous_text=False)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            raise HTTPException(422, "No speech was detected. Please try again.")
        return text
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Local speech recognition failed. Check the speech installation and try again.") from None
    finally:
        _stt_lock.release()


def spoken_text(text: str) -> str:
    """Keep the wording; give OCR line endings and paragraphs natural pauses."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"(?m)^\s*[-•]\s+", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return " ".join(line if line[-1:] in ".!?,;:…" else line + "." for line in lines if line)


def synthesize(text: str, language: str) -> bytes:
    global _tts, _g2p_en, _g2p_fr
    key = sha256((language + "\0" + spoken_text(text)).encode("utf-8")).digest()
    cached = _cached_audio(key)
    if cached is not None:
        return cached
    # An aborted browser request cannot interrupt an ONNX inference already in
    # progress. Queue its replacement instead of rejecting the next click.
    if not _tts_lock.acquire(timeout=120):
        raise HTTPException(503, "The local voice is taking too long. Please try again.")
    try:
        # A matching request may have finished while this caller waited. Cache
        # hits above also bypass a busy model when unrelated text is generating.
        cached = _cached_audio(key)
        if cached is not None:
            return cached
        if not speech_status()["tts"]:
            raise _missing()
        import numpy as np
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        if _tts is None:
            options = ort.SessionOptions()
            options.intra_op_num_threads = min(2, os.cpu_count() or 2)
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            session = ort.InferenceSession(str(MODELS / "kokoro/kokoro-v1.0.onnx"),
                                           sess_options=options, providers=["CPUExecutionProvider"])
            _tts = Kokoro.from_session(session, str(MODELS / "kokoro/voices-v1.0.bin"))
            from speech_acceleration import accelerate
            accelerate(_tts, MODELS / "kokoro/kokoro-v1.0.onnx")
        # Kokoro initializes the bundled eSpeak DLL/data first. Misaki then maps
        # pronunciations to the phoneme alphabet Kokoro was trained with.
        from misaki import en, espeak
        if language == "fr":
            if _g2p_fr is None:
                _g2p_fr = espeak.EspeakG2P(language="fr-fr")
            phonemes = _g2p_fr(spoken_text(text))
            voice = "ff_siwis"
        else:
            if _g2p_en is None:
                import spacy
                # G2P otherwise auto-downloads a missing parser. Never do that
                # while serving private text; setup must install it beforehand.
                if not spacy.util.is_package("en_core_web_sm"):
                    raise _missing()
                _g2p_en = en.G2P(trf=False, british=False,
                                 fallback=espeak.EspeakFallback(british=False))
            phonemes, _ = _g2p_en(spoken_text(text))
            voice = 0.7 * _tts.get_voice_style("af_heart") + 0.3 * _tts.get_voice_style("af_bella")
        samples, rate = _tts.create(phonemes, voice=voice, is_phonemes=True,
                                    speed=0.96, sentence_pause=0.28, clause_pause=0.12)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(rate)
            audio.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        audio = buffer.getvalue()
        _remember_audio(key, audio)
        return audio
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "The local voice could not generate audio. Check the speech installation and try again.") from None
    finally:
        _tts_lock.release()


def prefer_full_speed():
    """Opt this server out of Windows 11 EcoQoS power throttling.

    Windows marks processes whose window is not in the foreground (this server's
    terminal while the user is in the browser) as "efficiency mode", moving them
    to slow E-cores at low clocks. Measured on a hybrid Intel laptop, that made
    local speech generation about 45% slower and very inconsistent.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class PowerThrottlingState(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                        ("StateMask", wintypes.ULONG)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        # ProcessPowerThrottling = 4; control EXECUTION_SPEED (1) with state 0 = never throttle.
        state = PowerThrottlingState(1, 1, 0)
        if not kernel32.SetProcessInformation(kernel32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state)):
            raise OSError(ctypes.get_last_error())
    except Exception:
        logging.getLogger(__name__).info("Could not disable Windows power throttling; speech may be slower in the background.")


def warm_speech():
    """Load both pronunciation paths and warm inference before serving the UI."""
    prefer_full_speed()
    if not speech_status()["tts"]:
        return
    try:
        synthesize("Hello, I am Lumen.", "en")
        synthesize("Bonjour, je suis Lumen.", "fr")
    except HTTPException as error:
        logging.getLogger(__name__).warning("Local voice warm-up failed: %s", error.detail)
