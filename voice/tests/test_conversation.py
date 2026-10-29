"""Orchestration boundaries; stubs exercise failures without model benchmarks."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/f"{name}/src") for name in ("voice", "llm", "speech", "stt")]
from signspeak_voice import DocumentSession, VoiceConversation


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.views = {"llm_context": {"selected_text": "Reopens Tuesday at 9 AM.",
                       "regions": [{"id": "R1", "text": "Reopens Tuesday at 9 AM."}]},
                      "speech": {"requires_attention": False}}
        self.original = deepcopy(self.views)
        self.session = DocumentSession(self.views, records={"ocr": {"untouched": True}})
        self.stt, self.llm, self.speech = Mock(), Mock(), Mock()
        self.stt.transcribe.return_value = {"status": "ok", "text": "At 110?", "language": "fr"}
        self.llm.answer.return_value = {"answer": "Tuesday at 9 AM.", "warnings": [], "verification": "not_performed"}
        self.speech.synthesize_segments.return_value = SimpleNamespace(wav_bytes=b"WAV", metadata={"voices_loaded": ["en"]})
        self.voice = VoiceConversation(stt=self.stt, llm=self.llm, speech=self.speech)

    def test_prepare_does_not_answer_or_mutate_history(self):
        prepared = self.voice.prepare_question(b"audio", "en")
        self.assertEqual(prepared["status"], "ready_for_review")
        self.assertEqual(prepared["suggested_language"], "en")
        self.assertTrue(prepared["confirmation_required"])
        self.assertEqual(self.session.history, [])
        self.llm.answer.assert_not_called(); self.speech.synthesize_segments.assert_not_called()

    def test_no_speech_and_errors_cannot_trigger_answer(self):
        for status in ("no_speech", "error"):
            self.stt.transcribe.return_value = {"status": status, "text": "", "language": None}
            prepared = self.voice.prepare_question(b"audio")
            with self.assertRaises(ValueError):
                self.voice.answer_question(self.session, "Do not submit", prepared=prepared, language="en")
        self.llm.answer.assert_not_called()

    def test_corrected_question_and_user_language_reach_both_models(self):
        prepared = self.voice.prepare_question(b"audio", "en")
        result = self.voice.answer_question(self.session, "At 9?", prepared=prepared)
        self.assertEqual(self.llm.answer.call_args.args[1], "At 9?")
        self.assertEqual(self.llm.answer.call_args.kwargs["language"], "en")
        self.assertEqual(self.speech.synthesize_segments.call_args.args[0][0]["language"], "en")
        self.assertEqual(result["transcription"]["review_text"], "At 110?")
        self.assertEqual(self.session.history[0]["content"], "At 9?")

    def test_tts_failure_preserves_answer_and_history_for_followup(self):
        self.speech.synthesize_segments.side_effect = RuntimeError("voice missing")
        result = self.voice.answer_question(self.session, "When?", language="en")
        self.assertEqual(result["status"], "text_only")
        self.assertEqual(result["answer"], "Tuesday at 9 AM.")
        self.assertIsNone(result["wav_bytes"])
        self.assertEqual(result["errors"][0]["stage"], "piper")
        self.voice.answer_question(self.session, "And at what time?", language="en")
        self.assertEqual(len(self.llm.answer.call_args.kwargs["history"]), 2)

    def test_qwen_failure_does_not_commit_partial_turn(self):
        self.llm.answer.side_effect = RuntimeError("server unavailable")
        result = self.voice.answer_question(self.session, "When?", language="fr")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.session.history, [])
        self.speech.synthesize_segments.assert_not_called()

    def test_uncertainty_reaches_speech_without_technical_fields(self):
        self.views["llm_context"]["numeric_conflicts"] = [{"text": "1,5", "alternatives": ["15"]}]
        session = DocumentSession(self.views)
        self.voice.answer_question(session, "How much?", language="fr")
        args = self.speech.synthesize_segments.call_args
        self.assertTrue(args.kwargs["requires_attention"])
        self.assertEqual(args.kwargs["numeric_conflicts"], [True])
        self.assertEqual(set(args.args[0][0]), {"text", "language"})

    def test_typed_and_spoken_questions_share_document_and_history(self):
        self.voice.answer_question(self.session, "On which day?", language="en")
        prepared = self.voice.prepare_question(b"audio", "fr")
        self.voice.answer_question(self.session, "Et à quelle heure ?", prepared=prepared)
        self.assertEqual(self.llm.answer.call_args.kwargs["language"], "fr")
        self.assertEqual(self.llm.answer.call_args.kwargs["history"][0]["content"], "On which day?")
        self.assertEqual(self.views, self.original)
        self.assertEqual(self.session.document["records"], {"ocr": {"untouched": True}})
        exposed = self.session.history; exposed.clear()
        self.assertEqual(len(self.session.history), 4)

    def test_missing_confirmed_text_or_response_language_is_rejected(self):
        for text, language in [("", "en"), (None, "fr"), ("When?", "auto"), ("When?", None)]:
            with self.assertRaises(ValueError): self.voice.answer_question(self.session, text, language=language)
        self.llm.answer.assert_not_called()


if __name__ == "__main__": unittest.main()
