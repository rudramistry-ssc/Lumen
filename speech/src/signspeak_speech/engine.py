"""Ordered, offline English/French read-aloud through OHF-Voice Piper 1.8."""
from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import threading
import time
import unicodedata
import wave

from .voices import VOICES, verify, voice_directory
from .text import spoken_text


class SpeechError(RuntimeError):
    pass


class UnsupportedLanguageError(SpeechError):
    pass


class MissingVoiceError(SpeechError):
    pass


def language_code(tag, default=None):
    if tag in (None, "", "unknown", "mixed"):
        if default is None:
            raise UnsupportedLanguageError(f"Language {tag!r} needs identifiable subsegments or an explicit caller-selected default_language")
        tag = default
    if not isinstance(tag, str):
        raise UnsupportedLanguageError("Language must be an English/French tag")
    code = tag.replace("_", "-").lower().split("-")[0]
    if code not in VOICES:
        raise UnsupportedLanguageError(f"Unsupported language {tag!r}; supported languages: en, fr")
    return code


def _item(text, language, kind="content"):
    if not isinstance(text, str) or not text.strip() or "\0" in text:
        raise ValueError("Speech text must be nonempty and contain no NUL characters")
    return {"text": unicodedata.normalize("NFC", text), "language": language, "kind": kind}


def _notice(language, numeric=False):
    if language == "fr":
        return "Attention : certains nombres ou valeurs de cette lecture sont incertains. Vérifiez le document original." if numeric else "Attention : cette lecture est incomplète ou incertaine. Vérifiez le document original."
    return "Warning: some numbers or values in this reading are uncertain. Check the original document." if numeric else "Warning: this reading is incomplete or uncertain. Check the original document."


def plan_segments(segments, *, default_language=None, notices=(), requires_attention=False, numeric_conflicts=()):
    """Read only explicit text fields. Validate everything before any inference."""
    if not isinstance(segments, list):
        raise ValueError("segments must be an ordered list")
    contents = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError(f"Segment {index} must be an object with text and language")
        tag = segment.get("language")
        parts = (segment.get("language_details") or {}).get("segments") if tag == "mixed" else None
        if parts:
            spoken_parts = [_item(p["text"], language_code(p.get("code"), default_language)) for p in parts]
            # Separators such as '/' or '|' mark language switches, not spoken words.
            import re
            clean = lambda value: re.sub(r"[\s/|]+", "", value)
            if clean("".join(p["text"] for p in spoken_parts)) != clean(segment.get("text", "")):
                raise UnsupportedLanguageError(f"Segment {index}: language subsegments do not cover the original text")
        else:
            spoken_parts = [_item(segment.get("text"), language_code(tag, default_language))]
        preambles = []
        for warning in segment.get("warnings") or []:
            if not isinstance(warning, dict) or not warning.get("text"):
                raise ValueError("Segment warnings must have explicit human-readable text")
            preambles.append(_item(warning["text"], language_code(warning.get("language"), spoken_parts[0]["language"]), "uncertainty_notice"))
        if not preambles and (segment.get("flags") or any(v.get("status") == "numeric_disagreement" for v in segment.get("numeric_values") or [])):
            numeric = any(v.get("status") == "numeric_disagreement" for v in segment.get("numeric_values") or [])
            preambles.append(_item(_notice(spoken_parts[0]["language"], numeric), spoken_parts[0]["language"], "uncertainty_notice"))
        contents.extend(preambles + spoken_parts)
    lead_language = next((s["language"] for s in contents), None)
    if lead_language is None:
        lead_language = language_code(default_language) if default_language else None
    preambles = []
    for notice in notices or []:
        if not isinstance(notice, dict) or not notice.get("text"):
            raise ValueError("Global notices must have explicit text")
        preambles.append(_item(notice["text"], language_code(notice.get("language"), lead_language), "uncertainty_notice"))
    if (numeric_conflicts or (requires_attention and not any(s["kind"] == "uncertainty_notice" for s in contents))) and not preambles:
        if lead_language is None:
            raise UnsupportedLanguageError("An empty uncertain reading needs an explicit notice language")
        preambles.append(_item(_notice(lead_language, bool(numeric_conflicts)), lead_language, "uncertainty_notice"))
    if not preambles and not contents:
        raise ValueError("No speech text or notices provided")
    return preambles + contents


@dataclass
class SpeechResult:
    wav_bytes: bytes
    metadata: dict

    def write_wav(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.wav_bytes)
        return path


class PiperSpeech:
    def __init__(self, *, voice_dir=None, voice_paths=None, pause_ms=250, expand_notation=True):
        if not 0 <= pause_ms <= 2000:
            raise ValueError("pause_ms must be 0..2000")
        self.voice_dir, self.voice_paths, self.pause_ms = voice_dir, voice_paths or {}, pause_ms
        self.expand_notation = expand_notation
        self._voices = {}
        self._lock = threading.RLock()

    def _paths(self, language):
        item = VOICES[language]
        model = Path(self.voice_paths.get(language) or voice_directory(language, self.voice_dir) / item["files"][0]["filename"])
        config = Path(str(model) + ".json")
        if not model.is_file() or not config.is_file():
            raise MissingVoiceError(f"Missing {language} voice/config: {model}. Provision once with python -m signspeak_speech provision {language}; synthesis never downloads models.")
        return model, config

    def _load(self, language):
        if language in self._voices:
            return self._voices[language], 0.0
        started = time.perf_counter()
        model, config = self._paths(language)
        for path, artifact in zip((model, config), VOICES[language]["files"][:2]):
            try:
                verify(path, artifact)
            except (ValueError, OSError) as exc:
                raise MissingVoiceError(f"Invalid {language} voice artifact: {exc}") from exc
        try:
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from piper import PiperVoice
            voice = PiperVoice.load(model, config_path=config, use_cuda=False)
        except (ImportError, RuntimeError, OSError, ValueError) as exc:
            raise SpeechError(f"Cannot load Piper {language} voice: {exc}") from exc
        if voice.session.get_providers() != ["CPUExecutionProvider"]:
            raise SpeechError("Expected CPU-only ONNX execution")
        self._voices[language] = voice
        return voice, (time.perf_counter() - started) * 1000

    def synthesize(self, text, language):
        return self.synthesize_segments([{"text": text, "language": language}])

    def synthesize_segments(self, segments, *, default_language=None, notices=(), requires_attention=False, numeric_conflicts=()):
        plan = plan_segments(segments, default_language=default_language, notices=notices,
                             requires_attention=requires_attention, numeric_conflicts=numeric_conflicts)
        return self._synthesize(plan)

    def synthesize_view(self, speech_view, *, default_language=None):
        """Consume adapt_result(...)["speech"], including ordered warning preambles."""
        return self.synthesize_segments(speech_view["segments"], default_language=default_language,
            notices=speech_view.get("notices") or [], requires_attention=bool(speech_view.get("requires_attention") or speech_view.get("errors")),
            numeric_conflicts=speech_view.get("numeric_conflicts") or [])

    def synthesize_reconciled(self, result, *, language=None, section_languages=None):
        sections = result.get("sections") or [{"text": result.get("text", "")}]
        if section_languages is not None and len(section_languages) != len(sections):
            raise ValueError("section_languages must match the number of ordered sections")
        segments = [{"text": s["text"], "language": section_languages[i] if section_languages is not None else language}
                    for i, s in enumerate(sections)]
        comparison = result.get("comparison") or {}
        differences = comparison.get("numeric_disagreements") or {}
        numeric = bool(comparison.get("source_numeric_conflicts") or comparison.get("source_numeric_disputes")
                       or differences.get("ocr_literals_missing_or_changed") or differences.get("model_literals_introduced_or_changed"))
        attention = bool(result.get("requires_review") or result.get("status") == "fallback" or numeric)
        notices = [{"text": _notice(code, numeric), "language": code}
                   for code in dict.fromkeys(language_code(s["language"]) for s in segments)] if attention else []
        return self.synthesize_segments(segments, notices=notices, requires_attention=attention,
                                        numeric_conflicts=[True] if numeric else [])

    def _synthesize(self, plan):
        with self._lock:
            started = time.perf_counter()
            for language in dict.fromkeys(item["language"] for item in plan):
                self._paths(language)  # Fail before generating partial audio.
            loaded, load_ms = {}, {}
            for language in dict.fromkeys(item["language"] for item in plan):
                loaded[language], load_ms[language] = self._load(language)
            rates = {voice.config.sample_rate for voice in loaded.values()}
            if len(rates) != 1:
                raise SpeechError("Voices must share a sample rate for a single multilingual WAV")
            rate = rates.pop()
            frames = bytearray()
            timeline = []
            for index, item in enumerate(plan):
                if index:
                    frames.extend(b"\0\0" * round(rate * self.pause_ms / 1000))
                start_frame = len(frames) // 2
                synthesis_started = time.perf_counter()
                prepared = spoken_text(item["text"], item["language"]) if self.expand_notation else item["text"]
                try:
                    for chunk in loaded[item["language"]].synthesize(prepared):
                        if (chunk.sample_rate, chunk.sample_width, chunk.sample_channels) != (rate, 2, 1):
                            raise SpeechError("Unexpected Piper audio format")
                        frames.extend(chunk.audio_int16_bytes)
                except Exception as exc:
                    raise SpeechError(f"Piper synthesis failed for segment {index}: {exc}") from exc
                if len(frames) // 2 == start_frame:
                    raise SpeechError("Piper returned empty audio")
                timeline.append({**item, "spoken_text": prepared, "voice": VOICES[item["language"]]["name"],
                    "start_seconds": start_frame / rate, "end_seconds": len(frames) / 2 / rate,
                    "synthesis_ms": round((time.perf_counter() - synthesis_started) * 1000, 2)})
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(bytes(frames))
            return SpeechResult(output.getvalue(), {"engine": "OHF-Voice/piper1-gpl", "sample_rate": rate,
                "channels": 1, "sample_width": 2, "audio_duration_seconds": len(frames) / 2 / rate,
                "processing_ms": round((time.perf_counter() - started) * 1000, 2),
                "voice_load_ms": {k: round(v, 2) for k,v in load_ms.items()}, "segments": timeline,
                "voices_loaded": list(self._voices), "translation": "not_performed",
                "pronunciation_review": "manual listening required"})
