from copy import deepcopy
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from signspeak_speech import MissingVoiceError, PiperSpeech, SpeechError, UnsupportedLanguageError
from signspeak_speech.engine import plan_segments
from signspeak_speech.text import spoken_text


class SpeechTests(unittest.TestCase):
    def test_ordered_adapter_content_and_notices_without_technical_fields(self):
        segments = [{"id": "R1:L1", "text": "Fat 1.5 g.", "language": "en", "bbox": [0,0,1,1], "confidence": 42,
                     "warnings": [{"text": "This value is uncertain.", "language": "en", "word_ids": ["W2"]}]},
                    {"text": "Lipides 1,5 g.", "language": "fr"}]
        before = deepcopy(segments)
        plan = plan_segments(segments, notices=[{"text": "Check this reading.", "language": "en"}], numeric_conflicts=[{"raw": "1.5"}])
        self.assertEqual([p["text"] for p in plan], ["Check this reading.", "This value is uncertain.", "Fat 1.5 g.", "Lipides 1,5 g."])
        self.assertEqual([p["language"] for p in plan], ["en", "en", "en", "fr"])
        self.assertEqual(segments, before)
        self.assertTrue(all(set(p)=={"text","language","kind"} for p in plan))

    def test_unknown_language_needs_explicit_choice_and_invalid_tags_fail(self):
        engine = PiperSpeech()
        with patch.object(engine, "_load") as load:
            for tag in (None, "unknown", "mixed", "de", 3):
                with self.subTest(tag=tag), self.assertRaises(UnsupportedLanguageError):
                    engine.synthesize("Text", tag)
            load.assert_not_called()
        plan = plan_segments([{"text": "Uncertain language", "language": "unknown"}], default_language="fr-CA")
        self.assertEqual(plan[0]["language"], "fr")
        with self.assertRaises(UnsupportedLanguageError):
            plan_segments([{"text": "German", "language": "de"}], default_language="en")

    def test_mixed_identified_subsegments_keep_order_and_cover_original(self):
        segment = {"text": "Exit / Sortie", "language": "mixed", "language_details": {"segments": [
            {"text": "Exit", "code": "en"}, {"text": "Sortie", "code": "fr"}]}}
        plan = plan_segments([segment])
        self.assertEqual([(p["text"],p["language"]) for p in plan], [("Exit","en"),("Sortie","fr")])
        segment["language_details"]["segments"].pop()
        with self.assertRaises(UnsupportedLanguageError):
            plan_segments([segment])

    def test_notice_only_failed_ocr_can_be_spoken(self):
        plan = plan_segments([], notices=[{"text": "Cette lecture est incomplète.", "language": "fr"}], requires_attention=True)
        self.assertEqual(len(plan),1)
        self.assertEqual(plan[0]["kind"],"uncertainty_notice")

    def test_missing_voice_has_useful_error_without_downloading(self):
        engine = PiperSpeech(voice_paths={"en": Path(__file__).parent / "missing-voice.onnx"})
        with self.assertRaisesRegex(MissingVoiceError, "synthesis never downloads"):
            engine.synthesize("Test", "en")

    def test_voice_reuse_wav_format_and_no_partial_output(self):
        def chunks(text):
            yield SimpleNamespace(sample_rate=22050,sample_width=2,sample_channels=1,audio_int16_bytes=b"\x01\x00"*2205)
        voice=SimpleNamespace(config=SimpleNamespace(sample_rate=22050), session=SimpleNamespace(get_providers=lambda:["CPUExecutionProvider"]), synthesize=chunks)
        engine=PiperSpeech()
        with patch.object(engine,"_paths",return_value=(Path("voice.onnx"),Path("voice.onnx.json"))), \
             patch("signspeak_speech.engine.verify"), patch("piper.PiperVoice.load",return_value=voice) as load:
            result=engine.synthesize_segments([{"text":"First","language":"en"},{"text":"Deuxième","language":"fr"},{"text":"Last","language":"en"}])
            engine.synthesize("Again","en")
            self.assertEqual(load.call_count,2)
            self.assertTrue(all(call.kwargs['use_cuda'] is False for call in load.call_args_list))
            with wave.open(io.BytesIO(result.wav_bytes),"rb") as wav:
                self.assertEqual((wav.getframerate(),wav.getnchannels(),wav.getsampwidth()),(22050,1,2))
                self.assertGreater(wav.getnframes(),3*2205)
            self.assertEqual([s["text"] for s in result.metadata["segments"]],["First","Deuxième","Last"])

    def test_reconciled_numeric_review_announced_in_both_languages(self):
        engine=PiperSpeech()
        source={"requires_review":True,"sections":[{"text":"Price $12.50"},{"text":"Prix 12,50 $"}],
                "comparison":{"numeric_disagreements":{"model_literals_introduced_or_changed":["$12.50"]}}}
        before=deepcopy(source)
        with patch.object(engine,"_synthesize",side_effect=lambda plan:plan):
            plan=engine.synthesize_reconciled(source,section_languages=["en","fr"])
        self.assertEqual([p['kind'] for p in plan],['uncertainty_notice','uncertainty_notice','content','content'])
        self.assertEqual([p['language'] for p in plan],['en','fr','en','fr'])
        self.assertEqual(source,before)

    def test_speech_expansions_do_not_translate_or_guess_values(self):
        text="La bibliothèque rouvre à 9 h 00. Le 2026-11-03, sodium 230 mg et lipides 1,5 g. Prix 12,50 $."
        prepared=spoken_text(text,"fr")
        self.assertIn("9 heures",prepared)
        self.assertIn("3 novembre 2026",prepared)
        self.assertIn("230 milligrammes",prepared)
        self.assertIn("1,5 grammes",prepared)
        self.assertIn("12,50 dollars",prepared)
        self.assertIn("bibliothèque",prepared)
        self.assertEqual(spoken_text("Date 2026-13-40 or 11/03/2026.","en"),"Date 2026-13-40 or 11/03/2026.")
        self.assertIn("9 AM",spoken_text("Open at 9:00 AM.","en"))


if __name__ == "__main__":
    unittest.main()
