"""Tesseract CLI discovery and invocation (portable: Linux, macOS, Windows)."""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .config import TesseractConfig
from .errors import (
    TesseractExecutionError,
    TesseractLanguageError,
    TesseractNotFoundError,
    TesseractTimeoutError,
)

ENV_CMD = "SIGNSPEAK_TESSERACT_CMD"
ENV_TESSDATA = "SIGNSPEAK_TESSDATA_DIR"
_VERSION = re.compile(r"tesseract\s+v?(\d+(?:\.\d+)*\S*)", re.IGNORECASE)
_MAX_STDERR_LINES = 20


def _windows_candidates() -> list[Path]:
    roots = [os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    candidates = []
    for root in filter(None, roots):
        candidates.append(Path(root) / "Tesseract-OCR" / "tesseract.exe")
        candidates.append(Path(root) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    return candidates


def resolve_tesseract_cmd(cmd: str | None = None) -> str:
    """Explicit value > SIGNSPEAK_TESSERACT_CMD > PATH > Windows install dirs."""

    for candidate in (cmd, os.environ.get(ENV_CMD)):
        if candidate:
            found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
            if not found:
                raise TesseractNotFoundError(
                    f"Configured Tesseract binary not found: {candidate}",
                    details={"configured": candidate},
                )
            return found
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform.startswith("win"):
        for path in _windows_candidates():
            if path.is_file():
                return str(path)
    raise TesseractNotFoundError(
        "Tesseract was not found. Install it (Windows: UB Mannheim build) and add it "
        f"to PATH, or set {ENV_CMD} to the full path of tesseract(.exe)."
    )


def resolve_tessdata_dir(tessdata_dir: str | None = None) -> str | None:
    value = tessdata_dir or os.environ.get(ENV_TESSDATA)
    if value and not Path(value).is_dir():
        raise TesseractLanguageError(f"tessdata directory not found: {value}", details={"tessdata_dir": value})
    return value or None


@dataclass(frozen=True)
class TesseractInfo:
    cmd: str
    version: str
    languages: tuple[str, ...]
    tessdata_dir: str | None


@dataclass(frozen=True)
class TesseractRun:
    tsv: str
    command: list[str]
    return_code: int
    stderr_lines: list[str]
    duration_ms: float
    input_size: tuple[int, int]


def _creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0


def _run(command: list[str], timeout: float, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
            creationflags=_creationflags(),
        )
    except FileNotFoundError as error:
        raise TesseractNotFoundError(f"Cannot execute Tesseract: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise TesseractTimeoutError(
            f"Tesseract exceeded {timeout:g} s", details={"timeout_seconds": timeout}
        ) from error
    except OSError as error:
        raise TesseractExecutionError(f"Cannot execute Tesseract: {error}") from error


@functools.lru_cache(maxsize=8)
def _probe(cmd: str, tessdata_dir: str | None) -> TesseractInfo:
    version_run = _run([cmd, "--version"], timeout=30)
    output = (version_run.stdout or "") + (version_run.stderr or "")
    match = _VERSION.search(output)
    if version_run.returncode != 0 or not match:
        raise TesseractExecutionError(
            "Could not determine Tesseract version", details={"output": output.strip()[:500]}
        )
    list_command = [cmd]
    if tessdata_dir:
        list_command += ["--tessdata-dir", tessdata_dir]
    list_run = _run(list_command + ["--list-langs"], timeout=30)
    if list_run.returncode != 0:
        raise TesseractLanguageError(
            "Could not list Tesseract languages", details={"stderr": list_run.stderr.strip()[:500]}
        )
    lines = [line.strip() for line in (list_run.stdout or "").splitlines() if line.strip()]
    languages = tuple(sorted(line for line in lines if not line.lower().startswith("list of")))
    return TesseractInfo(cmd, match.group(1), languages, tessdata_dir)


def get_tesseract_info(config: TesseractConfig, *, require_languages: bool = True) -> TesseractInfo:
    cmd = resolve_tesseract_cmd(config.cmd)
    info = _probe(cmd, resolve_tessdata_dir(config.tessdata_dir))
    if require_languages:
        missing = [language for language in config.languages if language not in info.languages]
        if missing:
            raise TesseractLanguageError(
                f"Tesseract language data missing: {', '.join(missing)}. "
                "Install the matching .traineddata files (e.g. fra.traineddata) into tessdata.",
                details={"missing": missing, "available": list(info.languages)},
            )
    return info


def build_command(image_path: str, config: TesseractConfig, info: TesseractInfo) -> list[str]:
    command = [info.cmd, image_path, "stdout"]
    if info.tessdata_dir:
        command += ["--tessdata-dir", info.tessdata_dir]
    command += ["-l", "+".join(config.languages), "--oem", str(config.oem), "--psm", str(config.psm)]
    if config.dpi:
        command += ["--dpi", str(config.dpi)]
    for name, value in config.variables:
        command += ["-c", f"{name}={value}"]
    command.append("tsv")
    return command


def run_tesseract_tsv(image: Image.Image, config: TesseractConfig, info: TesseractInfo) -> TesseractRun:
    """OCR one in-memory image and return raw TSV plus invocation evidence."""

    env = None
    if config.omp_thread_limit is not None:
        env = dict(os.environ, OMP_THREAD_LIMIT=str(config.omp_thread_limit))
    with tempfile.TemporaryDirectory(prefix="signspeak-ocr-") as folder:
        image_path = os.path.join(folder, "input.png")
        image.save(image_path, format="PNG")
        command = build_command(image_path, config, info)
        started = time.perf_counter()
        completed = _run(command, config.timeout_seconds, env)
        duration = (time.perf_counter() - started) * 1000.0
    stderr_lines = [line.strip() for line in (completed.stderr or "").splitlines() if line.strip()]
    if completed.returncode != 0:
        raise TesseractExecutionError(
            f"Tesseract exited with code {completed.returncode}",
            details={"stderr": stderr_lines[:_MAX_STDERR_LINES], "return_code": completed.returncode},
        )
    # The temporary file path is meaningless after cleanup.
    recorded = [part if part != image_path else "<working-image.png>" for part in command]
    return TesseractRun(
        completed.stdout or "",
        recorded,
        completed.returncode,
        stderr_lines[:_MAX_STDERR_LINES],
        round(duration, 1),
        image.size,
    )
