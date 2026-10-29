"""Pipeline configuration. Every value has a portable default; no HPC paths."""

from __future__ import annotations

import re
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import ConfigError

_LANGUAGE_CODE = re.compile(r"^[A-Za-z0-9_]+$")
_VARIABLE_NAME = re.compile(r"^[A-Za-z0-9_]+$")
# PSM 0 (OSD only) and 2 (segmentation without OCR) produce no words.
_OCR_PSMS = {1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13}


@dataclass(frozen=True)
class TesseractConfig:
    cmd: str | None = None
    """Explicit binary. Falls back to SIGNSPEAK_TESSERACT_CMD, PATH, then
    standard Windows install locations."""
    tessdata_dir: str | None = None
    """Explicit tessdata folder. Falls back to SIGNSPEAK_TESSDATA_DIR, then
    Tesseract's own default / TESSDATA_PREFIX."""
    languages: tuple[str, ...] = ("eng", "fra")
    psm: int = 3
    oem: int = 1
    dpi: int | None = 300
    timeout_seconds: float = 120.0
    variables: tuple[tuple[str, str], ...] = (("preserve_interword_spaces", "1"),)
    omp_thread_limit: int | None = None

    def validate(self) -> None:
        if not self.languages:
            raise ConfigError("At least one Tesseract language is required")
        for language in self.languages:
            if not _LANGUAGE_CODE.match(language):
                raise ConfigError(f"Invalid Tesseract language code: {language!r}")
        if self.psm not in _OCR_PSMS:
            raise ConfigError(f"Unsupported page segmentation mode for OCR: {self.psm}")
        if self.oem not in {0, 1, 2, 3}:
            raise ConfigError(f"Unsupported OCR engine mode: {self.oem}")
        if self.dpi is not None and not 30 <= self.dpi <= 2400:
            raise ConfigError(f"DPI must be between 30 and 2400: {self.dpi}")
        if self.timeout_seconds <= 0:
            raise ConfigError("Tesseract timeout must be positive")
        for name, value in self.variables:
            if not _VARIABLE_NAME.match(name) or any(c in str(value) for c in "\r\n\0"):
                raise ConfigError(f"Invalid Tesseract variable: {name}={value!r}")
        if self.omp_thread_limit is not None and self.omp_thread_limit < 1:
            raise ConfigError("omp_thread_limit must be >= 1")


@dataclass(frozen=True)
class IngestConfig:
    max_input_bytes: int = 100_000_000
    max_input_pixels: int = 80_000_000
    max_working_edge: int = 4200
    """Larger images are downscaled for processing; boxes are mapped back."""
    min_edge_warning: int = 300

    def validate(self) -> None:
        if self.max_input_bytes <= 0 or self.max_input_pixels <= 0:
            raise ConfigError("Input limits must be positive")
        if self.max_working_edge < 256:
            raise ConfigError("max_working_edge must be at least 256 pixels")


@dataclass(frozen=True)
class QualityConfig:
    analysis_max_edge: int = 1600
    """Metrics are computed on a copy bounded to this edge so they are
    comparable across camera resolutions."""
    blur_laplacian_var: float = 60.0
    slight_blur_laplacian_var: float = 150.0
    low_contrast_rms: float = 0.08
    dark_mean: float = 0.22
    overexposed_fraction: float = 0.30
    washed_out_p05: float = 0.55
    glare_fraction: float = 0.02
    uneven_illumination: float = 0.35
    noise_sigma: float = 8.0
    low_resolution_min_edge: int = 600
    small_text_line_height_px: float = 20.0


@dataclass(frozen=True)
class PreprocessConfig:
    enabled: bool = False
    max_pixels: int = 4_000_000
    max_extra_calls: int = 3
    max_scale: float = 3.0
    extra_seconds: float = 8.0
    """Additional-pass budget; baseline OCR has its own timeout."""

    def validate(self) -> None:
        if not isinstance(self.max_extra_calls, int) or not 1 <= self.max_extra_calls <= 4:
            raise ConfigError("max_extra_calls must be an integer in 1..4")
        if not math.isfinite(self.max_scale) or not 1 <= self.max_scale <= 3:
            raise ConfigError("max_scale must be finite in 1..3")
        if not isinstance(self.max_pixels, int) or self.max_pixels <= 0:
            raise ConfigError("preprocessing max_pixels must be a positive integer")
        if not math.isfinite(self.extra_seconds) or self.extra_seconds <= 0:
            raise ConfigError("preprocessing extra_seconds must be finite and positive")


@dataclass(frozen=True)
class PipelineConfig:
    tesseract: TesseractConfig = field(default_factory=TesseractConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    preprocessing: PreprocessConfig = field(default_factory=PreprocessConfig)
    low_confidence_threshold: float = 60.0
    region_low_mean_confidence: float = 70.0
    region_many_low_conf_fraction: float = 0.30

    def validate(self) -> None:
        self.tesseract.validate()
        self.ingest.validate()
        self.preprocessing.validate()
        if not 0 <= self.low_confidence_threshold <= 100:
            raise ConfigError("low_confidence_threshold must be within 0-100")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tesseract"]["languages"] = list(self.tesseract.languages)
        data["tesseract"]["variables"] = dict(self.tesseract.variables)
        return data
