"""Global image-quality measurements. Measurement only: pixels are never changed.

Thresholds are provisional heuristics, to be calibrated on the team's
evaluation set. Metrics are computed on a copy bounded to
``QualityConfig.analysis_max_edge`` so values are comparable across sizes.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image

from .config import QualityConfig

QUALITY_VERSION = "quality-heuristics-0.1-provisional"


def _gray(image: Image.Image, max_edge: int) -> tuple[np.ndarray, np.ndarray, float]:
    analysis = image.copy()
    analysis.thumbnail((max_edge, max_edge), Image.Resampling.BILINEAR)
    rgb = np.asarray(analysis.convert("RGB"), dtype=np.float64)
    gray = rgb @ np.array([0.299, 0.587, 0.114])
    scale = analysis.width / image.width
    return gray, rgb, scale


def _convolve3(array: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Valid-mode 3x3 convolution (kernels here are symmetric)."""

    height, width = array.shape
    if height < 3 or width < 3:
        return np.zeros((0, 0))
    out = np.zeros((height - 2, width - 2))
    for dy in range(3):
        for dx in range(3):
            weight = kernel[dy, dx]
            if weight:
                out += weight * array[dy:dy + height - 2, dx:dx + width - 2]
    return out


_LAPLACIAN = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=float)
_NOISE = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=float)


def laplacian_variance(gray: np.ndarray) -> float:
    response = _convolve3(gray, _LAPLACIAN)
    return float(response.var()) if response.size else 0.0


def noise_sigma(gray: np.ndarray) -> float:
    """Immerkaer (1996) fast noise estimate; text edges inflate it somewhat."""

    response = _convolve3(gray, _NOISE)
    if not response.size:
        return 0.0
    height, width = gray.shape
    return float(math.sqrt(math.pi / 2.0) * np.abs(response).sum() / (6.0 * (width - 2) * (height - 2)))


def illumination_nonuniformity(gray: np.ndarray, grid: int = 16) -> float:
    """Spread of local background brightness (per-block 90th percentile)."""

    height, width = gray.shape
    if height < grid or width < grid:
        return 0.0
    rows = np.array_split(np.arange(height), grid)
    cols = np.array_split(np.arange(width), grid)
    backgrounds = np.array([
        np.percentile(gray[r[0]:r[-1] + 1, c[0]:c[-1] + 1], 90) for r in rows for c in cols
    ])
    spread = np.percentile(backgrounds, 95) - np.percentile(backgrounds, 5)
    return float(spread / max(np.mean(backgrounds), 1.0))


def colourfulness(rgb: np.ndarray) -> float:
    """Hasler & Suesstrunk (2003) colourfulness metric."""

    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    rg = r - g
    yb = 0.5 * (r + g) - b
    return float(math.hypot(rg.std(), yb.std()) + 0.3 * math.hypot(rg.mean(), yb.mean()))


def assess_image(image: Image.Image, config: QualityConfig | None = None) -> dict[str, Any]:
    config = config or QualityConfig()
    gray, rgb, scale = _gray(image, config.analysis_max_edge)
    normalized = gray / 255.0
    saturated = np.all(rgb >= 250.0, axis=-1)
    metrics = {
        "analysis_size": [int(gray.shape[1]), int(gray.shape[0])],
        "analysis_scale": round(scale, 6),
        "min_edge_px": int(min(image.size)),
        "megapixels": round(image.width * image.height / 1e6, 3),
        "brightness_mean": round(float(normalized.mean()), 4),
        "brightness_p05": round(float(np.percentile(normalized, 5)), 4),
        "brightness_p95": round(float(np.percentile(normalized, 95)), 4),
        "rms_contrast": round(float(normalized.std()), 4),
        "dark_clip_fraction": round(float((gray <= 5).mean()), 5),
        "bright_clip_fraction": round(float((gray >= 250).mean()), 5),
        "glare_fraction": round(float(saturated.mean()), 5),
        "laplacian_var": round(laplacian_variance(gray), 2),
        "noise_sigma": round(noise_sigma(gray), 3),
        "illumination_nonuniformity": round(illumination_nonuniformity(gray), 4),
        "colourfulness": round(colourfulness(rgb), 2),
    }

    reasons: list[str] = []
    severe: list[str] = []
    if metrics["laplacian_var"] < config.blur_laplacian_var:
        severe.append("blurry")
    elif metrics["laplacian_var"] < config.slight_blur_laplacian_var:
        reasons.append("slightly_blurry")
    if metrics["rms_contrast"] < config.low_contrast_rms:
        severe.append("low_contrast")
    if metrics["brightness_mean"] < config.dark_mean:
        reasons.append("underexposed")
    if metrics["bright_clip_fraction"] > config.overexposed_fraction and metrics["brightness_p05"] > config.washed_out_p05:
        # White paper is legitimately clipped; only flag when even the ink is pale.
        reasons.append("overexposed")
    if metrics["glare_fraction"] > config.glare_fraction and metrics["colourfulness"] > 15:
        # A white page is "saturated" everywhere; glare is only meaningful on
        # images that otherwise contain colour or mid-tones.
        reasons.append("possible_glare")
    if metrics["illumination_nonuniformity"] > config.uneven_illumination:
        reasons.append("uneven_illumination")
    if metrics["noise_sigma"] > config.noise_sigma:
        reasons.append("noisy")
    if metrics["min_edge_px"] < config.low_resolution_min_edge:
        reasons.append("low_resolution")

    assessment = "poor" if severe else "fair" if reasons else "good"
    return {
        "version": QUALITY_VERSION,
        "metrics": metrics,
        "assessment": assessment,
        "reasons": severe + reasons,
    }


def text_metrics(line_heights_px: list[float], config: QualityConfig | None = None) -> dict[str, Any]:
    """OCR-derived resolution evidence (line heights are in working pixels)."""

    config = config or QualityConfig()
    if not line_heights_px:
        return {"line_count": 0, "median_line_height_px": None, "reasons": []}
    median = float(np.median(line_heights_px))
    reasons = ["small_text"] if median < config.small_text_line_height_px else []
    return {
        "line_count": len(line_heights_px),
        "median_line_height_px": round(median, 1),
        "reasons": reasons,
    }
