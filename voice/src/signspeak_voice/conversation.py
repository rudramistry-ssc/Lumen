"""Compose existing components without reprocessing or modifying document data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from signspeak_llm import LocalLLM
from signspeak_speech import PiperSpeech
from signspeak_stt import WhisperSTT


class DocumentSession:
    """Application-owned document snapshot and shared typed/spoken history."""
    def __init__(self, views, *, session_id=None, records=None, history=None):
        context = views.get("llm_context") if isinstance(views, dict) else None
        if not isinstance(context, dict) or not isinstance(context.get("selected_text"), str) or not isinstance(context.get("regions"), list):
            raise ValueError("Expected existing adapter views containing llm_context")
        history = history if history is not None else []
        if not isinstance(history, list) or len(history) % 2 or any(
            not isinstance(item, dict) or item.get("role") != ("user" if i % 2 == 0 else "assistant")
            or not isinstance(item.get("content"), str) or not item["content"].strip() for i, item in enumerate(history)):
            raise ValueError("History must contain complete chronological user/assistant text pairs")
        self.session_id = session_id or uuid.uuid4().hex
        self._views, self._records, self._history = deepcopy(views), deepcopy(records or {}), deepcopy(history)
        self.context_sha256 = hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        self._lock = threading.RLock()

    @classmethod
    def from_file(cls, path):
        """Read cached adapter output or existing {views, source} evaluation cache."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "views" in data:
            return cls(data["views"], records={k: v for k, v in data.items() if k != "views"})
        return cls(data)

    @property
    def history(self):
        with self._lock: return deepcopy(self._history)

    @property
    def document(self):
        return {"views": deepcopy(self._views), "records": deepcopy(self._records)}


class VoiceConversation:
    def __init__(self, *, stt=None, llm=None, speech=None):
        self.stt = stt if stt is not None else WhisperSTT()
        self.llm = llm if llm is not None else LocalLLM()
        self.speech = speech if speech is not None else PiperSpeech()

    def prepare_question(self, audio_bytes, language="auto"):
        """STT only. Never calls Qwen, speaks, or appends conversation history."""
        if language not in ("auto", "en", "fr"): raise ValueError("Use auto, en or fr")
        started = time.perf_counter()
        transcript = self.stt.transcribe(audio_bytes, language)
        target = language if language != "auto" else transcript.get("language")
        status = transcript.get("status")
        ready = status == "ok" and bool(transcript.get("text", "").strip()) and target in ("en", "fr")
        return {"status": "ready_for_review" if ready else "unsupported_language" if status == "ok" else status,
                "review_text": transcript.get("text", ""), "requested_language": language,
                "suggested_language": target if target in ("en", "fr") else None,
                "confirmation_required": True, "transcription": deepcopy(transcript),
                "processing_seconds": round(time.perf_counter()-started, 4)}

    def answer_question(self, session, confirmed_text, *, language=None, prepared=None):
        """Explicit confirmation boundary, also used directly for typed questions.

        Providing confirmed_text is the caller's explicit submission. No raw STT
        hypothesis is submitted automatically. The latest explicit language wins.
        """
        if not isinstance(session, DocumentSession): raise ValueError("Expected DocumentSession")
        if not isinstance(confirmed_text, str) or not confirmed_text.strip() or "\0" in confirmed_text:
            raise ValueError("Provide a nonempty, explicitly confirmed question")
        if prepared is not None and (not isinstance(prepared, dict) or prepared.get("status") != "ready_for_review"):
            raise ValueError("No reviewable speech: do not call Qwen; submit separately as typed text if needed")
        if language is None and prepared is not None:
            language = prepared.get("requested_language")
            if language == "auto": language = prepared.get("suggested_language")
        if language not in ("en", "fr"):
            raise ValueError("Choose response language en/fr; typed questions need an explicit language")
        started = time.perf_counter()
        result = {"status": "error", "session_id": session.session_id, "context_sha256": session.context_sha256,
                  "question": confirmed_text.strip(), "language": language, "answer": "", "wav_bytes": None,
                  "audio_mime_type": None, "llm": None, "speech": None, "warnings": [], "errors": [],
                  "verification": "not_performed", "transcription": deepcopy(prepared),
                  "timings": {"stt_seconds": prepared.get("processing_seconds", 0) if prepared else 0,
                              "qwen_seconds": 0, "piper_seconds": 0}}
        # Protect a complete turn, including a recoverable TTS failure, against
        # concurrent typed/spoken calls to the same session.
        with session._lock:
            llm_started = time.perf_counter()
            try:
                answer = self.llm.answer(deepcopy(session._views["llm_context"]), result["question"],
                                         history=deepcopy(session._history), language=language)
                if not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
                    raise ValueError("Qwen returned no usable answer")
            except Exception as exc:
                result["errors"].append({"stage": "qwen", "message": str(exc)})
            else:
                result.update(answer=answer["answer"], llm=answer, warnings=list(answer.get("warnings") or []))
                session._history.extend([{"role": "user", "content": result["question"]},
                                         {"role": "assistant", "content": result["answer"]}])
            result["timings"]["qwen_seconds"] = round(time.perf_counter()-llm_started, 4)
            if result["answer"]:
                speech_view = session._views.get("speech") or {}
                context = session._views["llm_context"]
                numeric = bool(answer.get("numeric_disputes") or context.get("numeric_conflicts") or speech_view.get("numeric_conflicts"))
                attention = bool(numeric or speech_view.get("requires_attention") or context.get("errors") or
                                 "source_contains_tentative_readings" in result["warnings"] or
                                 "generation_limit_reached" in result["warnings"])
                result["speech_requires_attention"] = attention
                tts_started = time.perf_counter()
                try:
                    audio = self.speech.synthesize_segments([{"text": result["answer"], "language": language}],
                               requires_attention=attention, numeric_conflicts=[True] if numeric else [])
                    result.update(status="ok", wav_bytes=audio.wav_bytes, audio_mime_type="audio/wav", speech=audio.metadata)
                except Exception as exc:
                    result["status"] = "text_only"
                    result["errors"].append({"stage": "piper", "message": str(exc)})
                result["timings"]["piper_seconds"] = round(time.perf_counter()-tts_started, 4)
            result["history_turns"] = len(session._history)//2
        result["timings"]["answer_total_seconds"] = round(time.perf_counter()-started, 4)
        result["timings"]["total_processing_seconds"] = round(result["timings"]["stt_seconds"] + result["timings"]["answer_total_seconds"], 4)
        return result
