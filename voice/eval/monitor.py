"""Sample simultaneous working sets for Python/Piper, Whisper children and Qwen."""
import ctypes
import os
from pathlib import Path
import threading
import time


def processes():
    if os.name != "nt":
        result = {}
        for entry in Path("/proc").glob("[0-9]*"):
            try:
                fields = dict(line.split(":", 1) for line in (entry/"status").read_text().splitlines())
                result[int(entry.name)] = (int(fields["PPid"]), fields["Name"].strip())
            except (OSError, KeyError, ValueError): pass
        return result
    from ctypes import wintypes as wt
    class Entry(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("usage", wt.DWORD), ("pid", wt.DWORD), ("heap", ctypes.c_size_t),
                    ("module", wt.DWORD), ("threads", wt.DWORD), ("parent", wt.DWORD), ("priority", wt.LONG),
                    ("flags", wt.DWORD), ("name", wt.WCHAR*260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value: raise OSError("Cannot enumerate benchmark processes")
    result, entry = {}, Entry()
    entry.size = ctypes.sizeof(entry)
    try:
        valid = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while valid:
            result[entry.pid] = (entry.parent, entry.name)
            valid = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally: kernel.CloseHandle(handle)
    return result


def working_set(pid):
    if os.name != "nt":
        try:
            line = next(x for x in Path(f"/proc/{pid}/status").read_text().splitlines() if x.startswith("VmRSS:"))
            return int(line.split()[1])*1024
        except (OSError, StopIteration): return None
    from ctypes import wintypes as wt
    class Counters(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("faults", wt.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak", "working", "qpeak", "quota", "npeak", "nonpaged", "page", "pagepeak")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle: return None
    try:
        info = Counters(); info.size = ctypes.sizeof(info)
        call = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        call.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
        return info.working if call(handle, ctypes.byref(info), info.size) else None
    finally: kernel.CloseHandle(handle)


class CombinedMemory:
    def __init__(self, qwen_pid=None):
        self.roots = {os.getpid()} | ({qwen_pid} if qwen_pid else set())
        self.stop = threading.Event()
        self.report = {"peak_combined_working_set_mib": 0, "components_at_peak": [], "samples": 0,
                       "sampling_interval_seconds": .1, "qwen_pid_included": qwen_pid, "warnings": []}
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def sample(self):
        tree, selected = processes(), set(self.roots)
        while True:
            expanded = selected | {pid for pid, (parent, _) in tree.items() if parent in selected}
            if expanded == selected: break
            selected = expanded
        values = []
        for pid in selected:
            size = working_set(pid)
            if size is not None: values.append({"pid": pid, "name": tree.get(pid, (None, "unknown"))[1], "working_set_mib": size/1048576})
        total = sum(x["working_set_mib"] for x in values)
        if total > self.report["peak_combined_working_set_mib"]:
            self.report.update(peak_combined_working_set_mib=total, components_at_peak=values)
        self.report["samples"] += 1

    def _loop(self):
        while not self.stop.is_set():
            try: self.sample()
            except Exception as exc:
                if str(exc) not in self.report["warnings"]: self.report["warnings"].append(str(exc))
            self.stop.wait(.1)

    def __enter__(self): self.thread.start(); return self
    def __exit__(self, *_): self.stop.set(); self.thread.join()
