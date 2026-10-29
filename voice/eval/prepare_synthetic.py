"""Piper-generated questions: integration fixtures, never human STT evidence."""
from array import array
import io
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"speech/src")]
from signspeak_speech import PiperSpeech

QUESTIONS = [
    {"id": "english", "language": "en", "text": "On which day does the library reopen?"},
    {"id": "english-followup", "language": "en", "text": "Can you repeat that time?"},
    {"id": "french", "language": "fr", "text": "Quel jour la bibliothèque est-elle fermée ?"},
]


def prepare(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    tts = PiperSpeech()
    manifest = {"kind": "synthetic Piper speech; not human microphone recordings", "questions": []}
    for item in QUESTIONS:
        audio = tts.synthesize(item["text"], item["language"])
        audio.write_wav(directory/f"{item['id']}-source-22050.wav")
        with wave.open(io.BytesIO(audio.wav_bytes), "rb") as wav:
            rate = wav.getframerate()
            values = array("h", wav.readframes(wav.getnframes()))
        if sys.byteorder != "little": values.byteswap()
        output = array("h")
        for i in range(round(len(values)*16000/rate)):
            position = i*rate/16000
            left = min(int(position), len(values)-1)
            fraction = position-left
            output.append(round(values[left]*(1-fraction)+values[min(left+1,len(values)-1)]*fraction))
        if sys.byteorder != "little": output.byteswap()
        path = directory/f"{item['id']}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1,2,16000,0,"NONE","not compressed")); wav.writeframes(output.tobytes())
        manifest["questions"].append({**item, "file": path.name,
            "conversion": "mono PCM16 22050 to 16000 Hz, linear interpolation, evaluation only", "source": audio.metadata})
    (directory/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": prepare(sys.argv[1])
