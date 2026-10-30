"""Approximate native-process peak working set, without psutil."""
import ctypes
import os
from pathlib import Path
import threading


def resident_bytes(process):
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in ("peak", "working", "qpeak", "quota", "pppeak", "pp", "page", "pagepeak")]
        values = Counters()
        values.cb = ctypes.sizeof(values)
        call = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        call.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if call(int(process._handle), ctypes.byref(values), values.cb): return values.peak
        return 0
    try:
        lines = Path(f"/proc/{process.pid}/status").read_text().splitlines()
        return max(int(line.split()[1]) * 1024 for line in lines if line.startswith(("VmRSS:", "VmHWM:")))
    except (OSError, ValueError): return 0


class MemorySampler:
    def __init__(self, process):
        self.process, self.peak, self.stop = process, 0, threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        while not self.stop.is_set():
            self.peak = max(self.peak, resident_bytes(self.process))
            self.stop.wait(0.02)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
