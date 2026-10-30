"""Upload once: OCR evidence + independent vision -> saved vision document."""
from collections import Counter
import base64
from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
import unicodedata
import uuid

from .client import LocalLLM
from .reconcile import Reconciler, SYSTEM, VERSION as RECONCILE_VERSION, prepare_image
from .reconciliation_checks import critical_literals, compare_transcription
from .grounding import numeric_disputes
from . import guardrails

VERSION = "signspeak-selected-document-2"
LEGACY_VERSION = "signspeak-selected-document-1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _tokens(text):
    # Comparison only: accents/punctuation in selected output are never rewritten.
    plain = ''.join(c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c))
    return Counter(re.findall(r"[^\W_]+", plain))


def select_reading(context, readings):
    """Conservative presentation selection, never a claim of visual verification.

    Prefer strict model-to-model coverage dominance only when extra words occur
    in OCR and critical literals match. Otherwise present independent vision as
    a provisional reading, retaining every other reading/disagreement for review.
    No majority vote, fabricated coordinate, automatic numeric repair or merge.
    """
    valid = {mode: r for mode, r in readings.items() if r.get("status") in ("ok", "needs_review")
             and isinstance(r.get("model_text"), str) and r["model_text"].strip() and r.get("model_text") == r.get("text")
             and isinstance(r.get("sections"), list) and r["sections"]
             and all(isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip() for s in r["sections"])
             and "\n\n".join(s["text"] for s in r["sections"]) == r["text"]}
    if not valid:
        return "ocr_fallback", [{"text": context["selected_text"], "origin": "ocr_unreviewed_fallback"}], "both_visual_readings_failed"
    if len(valid) == 1:
        mode = next(iter(valid))
        return mode, deepcopy(valid[mode]["sections"]), "only_one_complete_visual_reading_available"
    vision, hybrid = valid["vision_only"], valid["hybrid"]
    mode, reason = "vision_only", "independent_vision_provisional; no reliable automatic winner"
    a, b, ocr = _tokens(vision["text"]), _tokens(hybrid["text"]), _tokens(context["selected_text"])
    if vision["text"] == hybrid["text"]:
        reason = "visual_readings_agree; correlated_agreement_is_not_verification"
    elif Counter(critical_literals(vision["text"])) == Counter(critical_literals(hybrid["text"])):
        if not (a-b) and (b-a) and not ((b-a)-ocr):
            mode, reason = "hybrid", "hybrid_has_strict_lexical_coverage_with_ocr_support; unverified"
        elif not (b-a) and (a-b) and not ((a-b)-ocr):
            reason = "vision_has_strict_lexical_coverage_with_ocr_support; unverified"
    return mode, deepcopy(valid[mode]["sections"]), reason


def selected_views(text, sections, *, document_id, warnings, disputes, fallback=False,
                   visual_descriptions=(), text_observations=(), ocr_discrepancies=None, schema_version=LEGACY_VERSION):
    """Compatibility adapter with model section IDs, never OCR word geometry."""
    from signspeak_ocr.language import detect_line_language
    regions, speech = [], []
    for index, section in enumerate(sections, 1):
        identifier = f"S{index}"
        details = detect_line_language(section["text"])
        region = {"id": identifier, "text": section["text"], "language": details["code"],
                  "text_state": section.get("text_state", "plain"),
                  "origin": "ocr_unreviewed_fallback" if fallback else "model_interpretation",
                  "verification": "not_performed", "source_region_ids": section.get("source_region_ids", []),
                  "flags": ["interpretation_requires_review"] if warnings else []}
        regions.append(region)
        # Line boundaries preserve order and permit bilingual sections without
        # inventing word coordinates or guessing an unsupported language.
        for line in section["text"].splitlines():
            if not line.strip(): continue
            language = detect_line_language(line)
            segment = {"text": line, "language": language["code"], "language_details": language, "content_type": "literal_text"}
            if section.get("text_state") in {"crossed_out", "uncertain"}:
                code = language["code"] if language["code"] in ("en", "fr") else "en"
                segment["warnings"] = [{"language": code, "text": "Texte barré ou incertain. La valeur actuelle n'est pas confirmée." if code == "fr" else "Crossed-out or uncertain text. The current value is not confirmed."}]
            speech.append(segment)
    source = {"document_id": document_id, "origin": "ocr_unreviewed_fallback" if fallback else "selected_document", "document_schema": schema_version}
    context = {"source": source, "selected_text": text, "regions": deepcopy(regions),
               "reading_order": {"sequence": [r["id"] for r in regions]},
               "numeric_conflicts": deepcopy(disputes), "warnings": deepcopy(warnings),
               "visual_descriptions": deepcopy(list(visual_descriptions)), "text_observations": deepcopy(list(text_observations)),
               "ocr_discrepancies": deepcopy(ocr_discrepancies or {}),
               "verification": "not_performed", "validation": {"overall_status": "partial" if warnings else "ok"}}
    notices = []
    if fallback:
        for code in dict.fromkeys(item["language"] for item in speech if item["language"] in ("en", "fr")):
            notices.append({"language": code, "text": "L'interprétation visuelle a échoué. Lecture OCR non vérifiée." if code == "fr" else
                            "Visual interpretation failed. This is the unreviewed OCR reading."})
    visual_speech = []
    for description in visual_descriptions:
        code = description.get("language", "unknown")
        prefix = "Description visuelle, pas un texte imprimé : " if code == "fr" else "Visual description, not printed text: "
        visual_speech.append({"text": prefix+description["text"], "language": code, "content_type": "visual_description"})
    read_aloud = {"text": "\n\n".join(s["text"] for s in speech+visual_speech), "literal_text": text,
                  "segments": deepcopy(speech+visual_speech), "notices": deepcopy(notices),
                  "requires_attention": bool(warnings), "numeric_conflicts": deepcopy(disputes)}
    return {"source": source, "display": {"text": text, "sections": deepcopy(regions), "warnings": deepcopy(warnings),
                                          "visual_descriptions": deepcopy(list(visual_descriptions)), "text_observations": deepcopy(list(text_observations)),
                                          "status": "ocr_unreviewed_fallback" if fallback else "interpreted"},
            "speech": {"text": text, "segments": speech, "notices": notices, "requires_attention": bool(warnings), "numeric_conflicts": deepcopy(disputes)},
            "read_aloud": read_aloud,
            "llm_context": context}


def build_document(context, readings, document_id):
    mode, sections, reason = select_reading(context, readings)
    text = "\n\n".join(s["text"] for s in sections)
    warnings = ["Interpretation is unverified; agreement between readings is not independent verification."]
    uncertain, disputes = [], []
    alternatives = {"ocr_only": context["selected_text"], **{m: r.get("model_text") for m, r in readings.items()}}
    for name, other in alternatives.items():
        if other is None:
            warnings.append(f"{name} failed: {readings[name].get('error', 'incomplete visual result')}")
            continue
        if other == text: continue
        changes = []
        left, right = text.split(), other.split()
        for kind, i, j, k, l in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
            if kind == "equal": continue
            chosen, alternative = " ".join(left[i:j]), " ".join(right[k:l])
            record = {"selected": chosen, "alternative": alternative, "alternative_source": name,
                      "kind": kind, "basis": "sequence difference, not verified word correspondence"}
            changes.append(record)
            if critical_literals(chosen) or critical_literals(alternative):
                disputes.append({"text": chosen or "[not read]", "alternatives": [{"text": alternative or "[not read]"}],
                                 "source": name, "basis": record["basis"]})
        uncertain.append({"source": name, "changes": changes, "complete_alternative": other,
                          "reading_order_may_differ": True})
    # Relevant uncertainty enters the stable Q&A context, not just UI metadata.
    if uncertain: warnings.append({"message": "Readings differ. Selected text is provisional; omitted/changed passages and order need review.", "disagreements": uncertain})
    if context.get("warnings") or context.get("errors"):
        warnings.append({"source_ocr_warnings": deepcopy(context.get("warnings") or []), "source_ocr_errors": deepcopy(context.get("errors") or [])})
    for mode_name, reading in readings.items():
        preparation = reading.get("image_preparation") or {}
        if preparation.get("prepared_size") != preparation.get("oriented_size") and preparation:
            warnings.append(f"{mode_name}: image was downscaled; small text may be unrecoverable. See preserved image_preparation.")
        if reading.get("uncertain_readings"): warnings.append({"source": mode_name, "model_unclear_markers": reading["uncertain_readings"]})
    # Preserve OCR's existing disputes without reassigning OCR coordinates to text.
    for dispute in numeric_disputes(context):
        literals = dispute["literal_readings"]
        disputes.append({"text": literals[0], "alternatives": [{"text": value} for value in literals[1:]], "source": "original_ocr"})
    fallback = mode == "ocr_fallback"
    if fallback: warnings.insert(0, "AI interpretation failed. This is unreviewed original OCR fallback, not corrected text.")
    views = selected_views(text, sections, document_id=document_id, warnings=warnings, disputes=disputes, fallback=fallback)
    return {"schema_version": LEGACY_VERSION, "document_id": document_id, "status": "ocr_unreviewed_fallback" if fallback else "needs_review",
            "text": text, "sections": sections, "language": [r["language"] for r in views["llm_context"]["regions"]],
            "selected_method": mode, "selection_reason": reason, "verification": "not_performed",
            "uncertain_readings": uncertain, "warnings": warnings,
            "selected_views": views}


def build_vision_document(context, vision, document_id):
    """Vision is primary. OCR differences are advisory and never merged/replaced."""
    valid = vision.get("status") in ("ok", "needs_review") and vision.get("printed_text_status") in ("present", "none", "uncertain")
    valid = valid and isinstance(vision.get("model_text"), str) and isinstance(vision.get("sections"), list)
    if valid:
        text, sections = vision["model_text"], deepcopy(vision["sections"])
        if text != "\n\n".join(s["text"] for s in sections): raise ValueError("Vision sections disagree with transcription")
        if vision["printed_text_status"] == "none" and text: raise ValueError("Symbol-only result cannot claim printed words")
        descriptions = [{**deepcopy(x), "origin": "visual_interpretation", "verification": "not_performed"} for x in vision.get("visual_descriptions", [])]
        observations = [{**deepcopy(x), "basis": "vision_interpretation_unverified", "verification": "not_performed"} for x in vision.get("text_observations", [])]
    else:
        text = context["selected_text"]
        sections = [{"text": text, "text_state": "uncertain", "origin": "ocr_unreviewed_fallback"}] if text else []
        descriptions, observations = [], []
    warnings = ["Vision transcription and visual descriptions remain unverified; agreement is not verification."]
    if not valid: warnings.insert(0, "Vision failed. This is explicitly unreviewed OCR fallback, not a vision result.")
    for section in sections:
        if section.get("text_state") in ("crossed_out", "uncertain"):
            observations.append({"kind": section["text_state"], "text": section["text"], "alternatives": [],
                "note": "Do not assume this reading is the current effective value.", "basis": "vision_interpretation_unverified" if valid else "unreviewed_ocr_fallback", "verification": "not_performed"})
    for match in re.finditer(r"(?<!\d)(\d{1,2})\s*(?::|h)\s*(\d{2})(?!\d)", text):
        if int(match[1]) > 23 or int(match[2]) > 59:
            observations.append({"kind": "critical_value", "text": match[0], "alternatives": [],
                "note": "Outside a 24-hour clock range if intended as a time; a duration is also possible. No correction was made.",
                "basis": "deterministic_plausibility_check", "verification": "not_performed"})
    for match in re.finditer(r"(?m)^\s*([^:\n]{1,80}):[ \t]*$", text):
        observations.append({"kind": "unfilled_field", "text": match[1], "alternatives": [],
            "note": "No value transcribed; blank versus obscured cannot be established from text. Do not invent a value.",
            "basis": "deterministic_empty_label_check", "verification": "not_performed"})
    comparison = compare_transcription(context, text) if valid else None
    advisory = deepcopy(comparison["numeric_disagreements"]) if comparison else {}
    if comparison and comparison.get("source_numeric_disputes"):
        advisory["source_numeric_disputes"] = deepcopy(comparison["source_numeric_disputes"])
    if advisory and any(advisory[k] for k in ("ocr_literals_missing_or_changed", "model_literals_introduced_or_changed")):
        warnings.append("OCR and vision critical literals differ. OCR is fallible advisory evidence; selected vision text was not changed.")
    if context.get("warnings") or context.get("errors"): warnings.append({"source_ocr_warnings": context.get("warnings", []), "source_ocr_errors": context.get("errors", [])})
    if vision.get("warnings"): warnings.append({"source_vision_warnings": deepcopy(vision["warnings"])})
    if observations: warnings.append({"message": "Uncertain visual markings/values require review; no current value is independently established.", "observations": observations})
    preparation = vision.get("image_preparation") or {}
    if preparation and preparation.get("prepared_size") != preparation.get("oriented_size"):
        warnings.append("Vision input was resized; small text may be missing.")
    # Section-level uncertainty can contain a whole paragraph. Only its actual
    # numeric literals belong in numeric conflicts; keep full text in observations.
    disputes = []
    for observation in observations:
        if observation["kind"] in {"unfilled_field", "redacted"}: continue
        alternatives = list(dict.fromkeys(v for a in observation.get("alternatives", []) for v in critical_literals(a)))
        for literal in dict.fromkeys(critical_literals(observation.get("text", ""))):
            disputes.append({"text": literal, "alternatives": [{"text": v} for v in alternatives if v != literal],
                             "source": "uncertain_vision_reading"})
    views = selected_views(text, sections, document_id=document_id, warnings=warnings, disputes=disputes,
        fallback=not valid, visual_descriptions=descriptions, text_observations=observations, ocr_discrepancies=advisory, schema_version=VERSION)
    document = {"schema_version": VERSION, "document_id": document_id, "status": "needs_review" if valid else "ocr_unreviewed_fallback",
        "selected_method": "vision_only" if valid else "ocr_fallback", "analysis_mode": "ocr_then_independent_vision",
        "text": text, "sections": sections, "printed_text_status": vision.get("printed_text_status", "uncertain") if valid else "uncertain",
        "visual_descriptions": descriptions, "text_observations": observations, "ocr_comparison": comparison,
        "warnings": warnings, "verification": "not_performed", "selected_views": views,
        "vision_error": vision.get("error") if not valid else None}
    return secure_document(document, context)


def secure_document(document, ocr_context):
    """Add metadata only, including on cached documents; never reprocess images."""
    security = guardrails.enforce(guardrails.check_document, {
        "selected_document": document["selected_views"]["llm_context"], "ocr_evidence": ocr_context})
    document["guardrails"] = security
    document["selected_views"]["llm_context"]["guardrails"] = deepcopy(security)
    return document


class DocumentProcessor:
    """Retain one instance and one vision-enabled server; process only on upload.

    Completed results INCLUDING explicit fallback are cached. Reprocessing needs
    a deliberate cache invalidation/configuration change, never a question call.
    """
    def __init__(self, *, reconciler=None, cache_dir=None, ocr=None, ocr_config=None, wait_seconds=900,
                 processing_timeout_seconds=None, worker_python=None, isolate=True):
        self.reconciler = reconciler or Reconciler(LocalLLM(context_size=8192, max_tokens=1536, timeout=480), max_edge=2048)
        self.cache_dir = Path(cache_dir or os.getenv("SIGNSPEAK_DOCUMENT_CACHE", str(Path.home()/".cache/signspeak/documents")))
        self.ocr, self.ocr_config, self.wait_seconds = ocr, ocr_config, wait_seconds
        self.processing_timeout_seconds = float(processing_timeout_seconds if processing_timeout_seconds is not None else os.getenv("SIGNSPEAK_UPLOAD_DEADLINE_SECONDS", "600"))
        if not math.isfinite(self.processing_timeout_seconds) or self.processing_timeout_seconds <= 0: raise ValueError("Upload deadline must be finite and positive")
        self.worker_python = str(worker_python or os.getenv("SIGNSPEAK_DOCUMENT_PYTHON", sys.executable))
        self.isolate = isolate
        self._lock = threading.Lock()

    def process(self, image_bytes):
        if not isinstance(image_bytes, bytes) or not image_bytes or len(image_bytes) > 25_000_000:
            raise ValueError("Supply original image bytes, at most 25 MB")
        if not self.isolate: return self._process_inline(image_bytes)
        if self.ocr is not None or type(self.reconciler) is not Reconciler or type(self.reconciler.client) is not LocalLLM:
            raise ValueError("Custom callback/client injection needs explicit isolate=False for controlled tests/debugging; production uses the bounded standard worker")
        from .deadline import run_bounded
        started = time.monotonic()
        jobs = self.cache_dir/"jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        job_file = jobs/(uuid.uuid4().hex+".json")
        client = self.reconciler.client
        payload = {"image": base64.b64encode(image_bytes).decode("ascii"), "cache_dir": str(self.cache_dir.resolve()),
            "deadline_at": started+self.processing_timeout_seconds,
            "job_file": str(job_file.resolve()), "wait_seconds": self.wait_seconds, "max_edge": self.reconciler.max_edge,
            "model_fingerprint": self.reconciler.model_fingerprint, "ocr_config": self.ocr_config.to_dict() if self.ocr_config else None,
            "client": {k: getattr(client, k) for k in ("base_url", "context_size", "max_tokens", "timeout", "model", "cache_prompt", "context_mode", "safeguards", "thinking", "policy")}}
        env = dict(os.environ)
        sources = [str(Path(__file__).resolve().parents[1])]
        ocr_source = Path(__file__).resolve().parents[3]/"ocr/src"
        if ocr_source.is_dir(): sources.append(str(ocr_source))
        env["PYTHONPATH"] = os.pathsep.join(sources+[env.get("PYTHONPATH", "")])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        remaining = self.processing_timeout_seconds-(time.monotonic()-started)
        if remaining <= 0: raise TimeoutError("Upload deadline exhausted before worker startup")
        execution = run_bounded([self.worker_python, "-B", "-m", "signspeak_llm.document_worker"], payload, seconds=remaining, env=env)
        elapsed = time.monotonic()-started
        if execution["ok"]:
            result = json.loads(execution["stdout"])
            result.update(request_wall_seconds=round(elapsed, 4), deadline_seconds=self.processing_timeout_seconds)
            return result
        progress = {}
        try: progress = json.loads(job_file.read_text(encoding="utf-8"))
        except (OSError, ValueError): pass
        failure = {"schema_version": VERSION, "status": "deadline_exceeded" if execution.get("deadline_exceeded") else "processing_failed",
            "final_document_available": False, "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "error": execution["error"], "stage": progress.get("stage", "worker_startup"),
            "request_wall_seconds": round(elapsed, 4), "deadline_seconds": self.processing_timeout_seconds,
            "cancellation": execution.get("cancellation"), "partial_evidence": progress.get("directory"),
            "warnings": ["No completed vision document was returned. Partial OCR is unverified and must not be presented as the vision result."]}
        self._save(job_file, json.dumps(failure).encode())
        directory = Path(progress["directory"]) if progress.get("directory") else None
        if directory and self.cache_dir.resolve() in directory.resolve().parents and progress.get("owns_lock"):
            if not (directory/"document.json").exists(): self._save(directory/"failure.json", json.dumps(failure).encode())
            if execution.get("cancellation", {}).get("worker_stopped"):
                (directory/"processing.lock").unlink(missing_ok=True)
        return failure

    def _stage(self, stage, directory, owns_lock=False):
        if getattr(self, "_deadline_at", float("inf")) <= time.monotonic(): raise TimeoutError("Upload deadline exhausted; no late document will be committed")
        if getattr(self, "_job_file", None):
            self._save(Path(self._job_file), json.dumps({"stage": stage, "directory": str(directory.resolve()), "owns_lock": owns_lock}).encode())

    def _process_inline(self, image_bytes):
        from signspeak_ocr import PipelineConfig, PreprocessConfig, extract_image
        from signspeak_ocr.integration import adapt_result
        if not isinstance(image_bytes, bytes) or not image_bytes: raise ValueError("Supply original image bytes")
        config = self.ocr_config or PipelineConfig(preprocessing=PreprocessConfig(enabled=True))
        r, client = self.reconciler, self.reconciler.client
        signature = {"version": VERSION, "analysis_mode": "ocr_then_independent_vision", "reconciler_version": RECONCILE_VERSION, "prompt": _digest(SYSTEM),
                     "ocr_config": config.to_dict(), "max_edge": r.max_edge, "model": r.model_fingerprint,
                     "endpoint": client.base_url, "alias": client.model, "context_size": client.context_size,
                     "max_tokens": client.max_tokens, "thinking": client.thinking}
        image_sha = hashlib.sha256(image_bytes).hexdigest()
        key = _digest({"image": image_sha, "configuration": signature})
        directory = self.cache_dir/key
        with self._lock:
            directory.mkdir(parents=True, exist_ok=True)
            self._stage("waiting_for_cache", directory)
            lock = directory/"processing.lock"
            started = time.perf_counter()
            while True:
                cached = self._load(directory, key)
                if cached is not None: return {**cached, "cache_hit": True, "execution_this_call": {"ocr": 0, "vision": 0, "hybrid": 0}}
                try:
                    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd); break
                except FileExistsError:
                    if time.perf_counter()-started > self.wait_seconds:
                        raise TimeoutError("Upload processing still locked; no duplicate analysis started. Inspect processing.lock after a crashed worker.")
                    time.sleep(.1)
            try:
                cached = self._load(directory, key)
                if cached is not None: return {**cached, "cache_hit": True, "execution_this_call": {"ocr": 0, "vision": 0, "hybrid": 0}}
                # Validate limits before OCR; only one independent visual pass.
                self._stage("image_preparation", directory, True)
                _, preparation = prepare_image(image_bytes, r.max_edge)
                self._save(directory/"attempt.json", json.dumps({"image_sha256": image_sha, "configuration": signature}).encode())
                self._save(directory/"image.bin", image_bytes)
                self._stage("ocr", directory, True)
                source = (self.ocr or extract_image)(image_bytes, config)
                views = adapt_result(source)
                context = views["llm_context"]
                self._save(directory/"ocr.json", json.dumps({"source": source, "views": views}, ensure_ascii=False).encode())
                self._stage("independent_vision", directory, True)
                vision = r.reconcile(image_bytes, context, mode="vision_only", use_cache=False)
                self._save(directory/"vision_only.json", json.dumps(vision, ensure_ascii=False).encode())
                readings = {"vision_only": vision}
                evidence = {"original_ocr": source, "original_views": views, "readings": readings,
                            "image_sha256": image_sha, "configuration": signature, "image_preparation": preparation}
                self._stage("final_document", directory, True)
                document = build_vision_document(context, vision, key)
                document.update(image_sha256=image_sha, processing_seconds=round(time.perf_counter()-started, 4),
                                evidence_ref=str(directory/"evidence.json"), evidence_sha256=_digest(evidence), cache_hit=False,
                                execution_this_call={"ocr": 1, "vision": 1, "hybrid": 0})
                self._save(directory/"evidence.json", json.dumps(evidence, ensure_ascii=False, allow_nan=False).encode())
                self._stage("commit_document", directory, True)
                self._save(directory/"document.json", json.dumps(document, ensure_ascii=False, allow_nan=False).encode())
                return deepcopy(document)
            finally:
                lock.unlink(missing_ok=True)

    @staticmethod
    def _save(path, data):
        temporary = path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(data)
            # Windows scanners can briefly hold a just-written checkpoint open.
            # Retry only the atomic rename; never rerun OCR or inference.
            for attempt in range(5):
                try: temporary.replace(path); break
                except PermissionError:
                    if attempt == 4: raise
                    time.sleep(.02*(attempt+1))
        finally: temporary.unlink(missing_ok=True)

    @staticmethod
    def _load(directory, key):
        path = directory/"document.json"
        if not path.exists():
            if (directory/"failure.json").exists(): return json.loads((directory/"failure.json").read_text(encoding="utf-8"))
            if any((directory/name).exists() for name in ("attempt.json", "evidence.json", "image.bin")) and not (directory/"processing.lock").exists():
                raise ValueError("Incomplete upload cache; explicit repair required, analysis was not repeated")
            return None
        # Never silently rerun OCR/VLM for a damaged completed cache.
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            evidence = json.loads((directory/"evidence.json").read_text(encoding="utf-8"))
            if document["document_id"] != key or document["schema_version"] != VERSION or document["evidence_sha256"] != _digest(evidence):
                raise ValueError("Document identity/evidence mismatch")
            selected = document["selected_views"]
            if document["text"] != selected["display"]["text"] or document["text"] != selected["llm_context"]["selected_text"] or document["text"] != selected["speech"]["text"]:
                raise ValueError("Selected consumer views disagree")
            return secure_document(document, evidence.get("original_views", {}).get("llm_context", {}))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("Damaged document cache; explicit repair required, analysis was not repeated") from exc
