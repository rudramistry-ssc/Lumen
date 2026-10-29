"""Boundary and safety contract checks; no models or network required."""
import io
from pathlib import Path
import sys
import unittest
from unittest import mock
import tempfile
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from signspeak_stt import WhisperSTT, convert_audio
from signspeak_stt.provision import executable, model_path


def wav(rate=16000, seconds=1, value=0):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(value.to_bytes(2, "little", signed=True) * int(seconds*rate))
    return stream.getvalue()


class Contract(unittest.TestCase):
    def setUp(self):
        self.engine = WhisperSTT(cli="absent-whisper", model="absent-model")

    def test_silence_without_inference(self):
        result = self.engine.transcribe(wav())
        self.assertEqual((result["status"], result["text"], result["language"]), ("no_speech", "", None))

    def test_quiet_human_speech_not_rejected_as_silence(self):
        # This amplitude is below -60 dBFS and must reach the missing-engine check.
        result = self.engine.transcribe(wav(value=16))
        self.assertEqual(result["status"], "error")
        self.assertIn("whisper-cli missing", result["error"])

    def test_truncated_payload_not_accepted(self):
        self.assertIn("truncated", self.engine.transcribe(wav()[:-2])["error"])

    def test_language_and_audio_boundaries(self):
        for audio, language, error in [(b"", "auto", "empty_audio"), (b"bad", "auto", "corrupt"),
               (wav(rate=8000), "auto", "unsupported_format"), (wav(), "de", "unsupported_language"),
               (wav(seconds=61), "en", "recording_too_long"), (b"x"*8_000_001, "fr", "input_too_large")]:
            with self.subTest(error=error):
                result = self.engine.transcribe(audio, language)
                self.assertEqual((result["status"], result["text"]), ("error", ""))
                self.assertIn(error, result["error"])

    def test_missing_optional_converter_is_actionable(self):
        with self.assertRaisesRegex(ValueError, "FFmpeg missing"):
            convert_audio(wav(), ffmpeg="absent-ffmpeg-signspeak")

    @unittest.skipUnless(executable().is_file() and model_path().is_file(), "Optional installed-runtime timeout check")
    def test_native_timeout_cleans_temporary_recording(self):
        original = tempfile.TemporaryDirectory
        directories = []
        def capture(*args, **kwargs):
            context = original(*args, **kwargs)
            directories.append(Path(context.name))
            return context
        with mock.patch("signspeak_stt.engine.tempfile.TemporaryDirectory", side_effect=capture):
            result = WhisperSTT(timeout=.001).transcribe(wav(value=1000))
        self.assertEqual(result["status"], "error")
        self.assertIn("timeout", result["error"])
        self.assertTrue(directories)
        self.assertTrue(all(not p.exists() for p in directories))


if __name__ == "__main__": unittest.main()
