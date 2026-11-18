"""Repeated local audio bypasses inference, including while the model is busy."""
import sys
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import local_speech as speech


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setattr(speech, "_audio_cache", OrderedDict())
    monkeypatch.setattr(speech, "_audio_cache_bytes", 0)


def test_cache_hit_returns_audio_without_waiting_for_busy_voice(monkeypatch):
    key = sha256(("fr\0" + speech.spoken_text("Sortie.")).encode()).digest()
    speech._remember_audio(key, b"cached-WAV")

    class BusyVoice:
        def acquire(self, **kwargs):
            raise AssertionError("Cached audio must bypass the inference lock")

    monkeypatch.setattr(speech, "_tts_lock", BusyVoice())
    assert speech.synthesize("Sortie.", "fr") == b"cached-WAV"


def test_expired_audio_is_not_reused(monkeypatch):
    monkeypatch.setattr(speech, "monotonic", lambda: 100)
    speech._remember_audio(b"key", b"audio")
    monkeypatch.setattr(speech, "monotonic", lambda: 100 + speech.CACHE_TTL_SECONDS)
    assert speech._cached_audio(b"key") is None
    assert speech._audio_cache_bytes == 0


def test_cache_is_bounded_and_keeps_recently_used_audio(monkeypatch):
    monkeypatch.setattr(speech, "CACHE_MAX_BYTES", 10)
    speech._remember_audio(b"first", b"1234")
    speech._remember_audio(b"second", b"5678")
    assert speech._cached_audio(b"first") == b"1234"
    speech._remember_audio(b"third", b"abcd")
    assert speech._cached_audio(b"second") is None
    assert speech._cached_audio(b"first") == b"1234"
    assert speech._cached_audio(b"third") == b"abcd"
    assert speech._audio_cache_bytes == 8


def test_duplicate_requests_recheck_cache_after_waiting_for_model(monkeypatch):
    key = sha256(("en\0" + speech.spoken_text("Welcome.")).encode()).digest()

    class FinishingVoice:
        released = False
        def acquire(self, **kwargs):
            speech._remember_audio(key, b"just-finished-WAV")
            return True
        def release(self):
            self.released = True

    voice = FinishingVoice()
    monkeypatch.setattr(speech, "_tts_lock", voice)
    assert speech.synthesize("Welcome.", "en") == b"just-finished-WAV"
    assert voice.released
