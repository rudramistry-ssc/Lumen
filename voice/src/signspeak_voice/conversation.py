"""Compose existing components without reprocessing or modifying document data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from signspeak_llm import LocalLLM
from signspeak_llm import guardrails
from signspeak_llm.client import SYSTEM, STRICT_SYSTEM
from signspeak_speech import PiperSpeech
from signspeak_stt import WhisperSTT


class DocumentSession:
    """Application-owned document snapshot and shared typed/spoken history."""
    def __init__(self, views, *, session_id=None, records=None, history=None, allow_legacy_ocr=False):
        context = views.get("llm_context") if isinstance(views, dict) else None
        if not isinstance(context, dict) or not isinstance(context.get("selected_text"), str) or not isinstance(context.get("regions"), list):
            raise ValueError("Expected existing adapter views containing llm_context")
        if (context.get("source") or {}).get("origin") not in {"selected_document", "ocr_unreviewed_fallback"} and not allow_legacy_ocr:
            raise ValueError("OCR-only session disabled by default. Use DocumentProcessor.process then DocumentSession.from_document; legacy tests may explicitly set allow_legacy_ocr=True")
        if not allow_legacy_ocr and (context.get("source") or {}).get("document_schema") != "signspeak-selected-document-2":
            raise ValueError("Legacy selected views require explicit review/reclassification before normal use")
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
    def from_document(cls, document, *, allow_fallback=False):
        """New upload path: consume ONLY selected views, keep evidence separate."""
        if not isinstance(document, dict) or not isinstance(document.get("selected_views"), dict):
            raise ValueError("Expected a completed DocumentProcessor result")
        if document.get("schema_version") != "signspeak-selected-document-2":
            raise ValueError("Legacy mixed-format document preserved but requires explicit review/reclassification; it is not a typed literal/visual document and will not be reanalyzed automatically")
        if document.get("status") == "ocr_unreviewed_fallback" and not allow_fallback:
            raise ValueError("AI interpretation failed; explicitly allow labelled OCR fallback or request review")
        views = document["selected_views"]
        if any(document.get("text") != views.get(name, {}).get(key) for name, key in
               (("llm_context", "selected_text"), ("display", "text"), ("speech", "text"))):
            raise ValueError("Final text and selected consumer views disagree")
        return cls(views, records={"document_id": document["document_id"], "evidence_ref": document.get("evidence_ref"),
                                   "status": document["status"], "warnings": deepcopy(document.get("warnings", []))})

    @classmethod
    def from_file(cls, path, *, allow_fallback=False, allow_legacy_ocr=False):
        """Read cached adapter output or existing {views, source} evaluation cache."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "selected_views" in data:
            return cls.from_document(data, allow_fallback=allow_fallback)
        if "views" in data:
            return cls(data["views"], records={k: v for k, v in data.items() if k != "views"}, allow_legacy_ocr=allow_legacy_ocr)
        return cls(data, allow_legacy_ocr=allow_legacy_ocr)

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

    def read_document(self, session, *, language=None, include_visual_descriptions=True):
        """Read cached vision content; interpretations are labelled, no LLM call."""
        if not isinstance(session, DocumentSession): raise ValueError("Expected DocumentSession")
        key = "read_aloud" if include_visual_descriptions else "speech"
        return self.speech.synthesize_view(session.document["views"][key], default_language=language)

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
                checks = {
                    "question": guardrails.enforce(guardrails.check_question, result["question"]),
                    "document": guardrails.enforce(guardrails.check_document, session._views["llm_context"]),
                    "history": guardrails.enforce(guardrails.check_history, session._history, session._views["llm_context"],
                                                 trusted_instructions=(SYSTEM, STRICT_SYSTEM, guardrails.BOUNDARY))}
                # Failed upload security checks cannot be lost when rescanning.
                saved_security = session._views["llm_context"].get("guardrails", {})
                if saved_security.get("blocked"):
                    checks["document"] = saved_security
                blocked = next((c for c in checks.values() if c["blocked"]), None)
                if blocked:
                    return self._blocked(result, blocked, session, started)
                answer = self.llm.answer(deepcopy(session._views["llm_context"]), result["question"],
                                         history=deepcopy(session._history), language=language)
                if not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
                    raise ValueError("Qwen returned no usable answer")
                if answer.get("status") == "blocked" or (answer.get("guardrails") or {}).get("blocked"):
                    return self._blocked(result, answer.get("guardrails") or guardrails.decision("blocked", "qwen_guardrail"), session, started)
                checks["output"] = guardrails.enforce(guardrails.check_output, answer["answer"], session._views["llm_context"],
                                                     trusted_instructions=(SYSTEM, STRICT_SYSTEM, guardrails.BOUNDARY))
                if checks["output"]["blocked"]:
                    return self._blocked(result, checks["output"], session, started)
                result["guardrails"] = {**guardrails.decision(
                    "needs_review" if any(c["needs_review"] for c in checks.values()) else "allowed",
                    "qa_checks_completed", [r for c in checks.values() for r in c["detected_risks"]]), "checks": checks}
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

    @staticmethod
    def _blocked(result, security, session, started):
        """Return displayable text, with no history turn and no Piper invocation."""
        result.update(guardrails.refusal(security, result["language"]))
        result["history_turns"] = len(session._history)//2
        result["timings"]["qwen_seconds"] = round(time.perf_counter()-started, 4)
        result["timings"]["answer_total_seconds"] = round(time.perf_counter()-started, 4)
        result["timings"]["total_processing_seconds"] = round(result["timings"]["stt_seconds"] + result["timings"]["answer_total_seconds"], 4)
        return result
