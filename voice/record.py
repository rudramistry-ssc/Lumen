"""User-run Windows microphone capture; WinMM + Python standard library only."""
import argparse
import ctypes
from ctypes import wintypes as wt
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path
import time
import wave


class WaveFormat(ctypes.Structure):
    _fields_ = [("format", wt.WORD), ("channels", wt.WORD), ("rate", wt.DWORD),
                ("bytes_per_second", wt.DWORD), ("alignment", wt.WORD), ("bits", wt.WORD), ("extra", wt.WORD)]


class Header(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("length", wt.DWORD), ("recorded", wt.DWORD),
                ("user", ctypes.c_size_t), ("flags", wt.DWORD), ("loops", wt.DWORD),
                ("next", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]


class Device(ctypes.Structure):
    _fields_ = [("manufacturer", wt.WORD), ("product", wt.WORD), ("version", wt.DWORD),
                ("name", wt.WCHAR*32), ("formats", wt.DWORD), ("channels", wt.WORD), ("reserved", wt.WORD)]


def api():
    if os.name != "nt": raise OSError("This optional recorder uses Windows WinMM; supply saved WAVs on other systems")
    dll = ctypes.WinDLL("winmm")
    dll.waveInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(Device), wt.UINT]
    dll.waveInOpen.argtypes = [ctypes.POINTER(wt.HANDLE), wt.UINT, ctypes.POINTER(WaveFormat), ctypes.c_size_t, ctypes.c_size_t, wt.DWORD]
    for name in ("waveInPrepareHeader", "waveInAddBuffer", "waveInUnprepareHeader"):
        getattr(dll, name).argtypes = [wt.HANDLE, ctypes.POINTER(Header), wt.UINT]
    for name in ("waveInStart", "waveInStop", "waveInReset", "waveInClose"):
        getattr(dll, name).argtypes = [wt.HANDLE]
    dll.waveInGetErrorTextW.argtypes = [wt.UINT, wt.LPWSTR, wt.UINT]
    return dll


def checked(dll, result):
    if result:
        message = ctypes.create_unicode_buffer(256)
        dll.waveInGetErrorTextW(result, message, len(message))
        raise OSError(f"Microphone error {result}: {message.value}. Check Windows microphone privacy settings/device and 16 kHz mono support.")


def devices(dll):
    result = []
    for index in range(dll.waveInGetNumDevs()):
        device = Device()
        checked(dll, dll.waveInGetDevCapsW(index, ctypes.byref(device), ctypes.sizeof(device)))
        result.append({"id": index, "name": device.name, "input_channels": device.channels})
    return result


def record(dll, device, seconds, path):
    if path.exists(): raise FileExistsError(f"Refusing to overwrite {path}")
    fmt, handle = WaveFormat(1, 1, 16000, 32000, 2, 16, 0), wt.HANDLE()
    checked(dll, dll.waveInOpen(ctypes.byref(handle), device, ctypes.byref(fmt), 0, 0, 0))
    buffer = ctypes.create_string_buffer(round(seconds*32000))
    header = Header(data=ctypes.addressof(buffer), length=len(buffer))
    prepared = False
    try:
        checked(dll, dll.waveInPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))); prepared = True
        checked(dll, dll.waveInAddBuffer(handle, ctypes.byref(header), ctypes.sizeof(header)))
        for count in (3, 2, 1): print(f"Starting in {count}...", flush=True); time.sleep(1)
        checked(dll, dll.waveInStart(handle))
        print(f"RECORDING for {seconds:g} seconds. Speak now.", flush=True)
        deadline = time.perf_counter()+seconds+3
        while not header.flags & 1:  # WHDR_DONE
            if time.perf_counter() > deadline: raise TimeoutError("Microphone buffer did not complete; no recording saved")
            time.sleep(.05)
        print("Recording stopped.", flush=True)
        payload = bytes(buffer[:header.recorded])
    finally:
        dll.waveInStop(handle)
        dll.waveInReset(handle)
        if prepared: dll.waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
        dll.waveInClose(handle)
    if len(payload) < 3200 or len(payload) % 2: raise ValueError("Microphone returned empty or invalid audio")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed")); wav.writeframes(payload)
    return len(payload)/32000


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--device", type=int, default=-1, help="Listed device ID; -1 selects Windows default")
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 15: parser.error("Use 10–15 seconds per question")
    dll = api()
    available = devices(dll)
    if args.list_devices:
        print(json.dumps(available, ensure_ascii=False, indent=2)); return
    if not available: raise OSError("No Windows recording devices available")
    if args.device < -1 or args.device >= len(available): parser.error("Choose a listed device ID or -1")
    directory = args.output_dir or Path(__file__).parent/"runtime"/f"microphone-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    prompts = [("english", "en", "On which day does the library reopen?"),
               ("french", "fr", "Quel jour la bibliothèque est-elle fermée ?")]
    manifest = {"kind": "user microphone recordings", "device": args.device, "available_devices": available, "recordings": []}
    for name, language, question in prompts:
        print(f"\n{name.upper()} question: {question}")
        input("Press Enter when ready for the countdown (Ctrl+C to cancel): ")
        path = directory/f"{name}.wav"
        duration = record(dll, args.device, args.seconds, path)
        manifest["recordings"].append({"file": str(path.resolve()), "language": language, "prompt": question,
            "reference_status": "prompt only; manually check what was actually spoken", "audio_seconds": duration,
            "format": "16 kHz mono PCM16 WAV, native capture, no conversion"})
        (directory/"manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Saved:", path.resolve())
    print("\nBoth recordings saved locally. Provide these WAV paths for real-voice evaluation.")


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\nCancelled; microphone closed."); raise SystemExit(130)
    except (OSError, ValueError, TimeoutError) as exc: print(str(exc)); raise SystemExit(1)
