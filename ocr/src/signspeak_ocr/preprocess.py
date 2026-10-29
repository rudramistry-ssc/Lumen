"""One diagnostic-driven, same-size candidate; OpenCV is an optional extra."""
from __future__ import annotations

import numpy as np
from PIL import Image


def candidate_kind(quality: dict | None) -> str | None:
    if not quality:
        return None
    metrics = quality['metrics']
    # Dark sign backgrounds take precedence over the shadow heuristic.
    if metrics['brightness_mean'] < 0.22 and metrics['rms_contrast'] > 0.08:
        return 'invert'
    if 'uneven_illumination' in quality['reasons']:
        return 'background_normalize'
    if 'low_contrast' in quality['reasons']:
        return 'clahe'
    return None


def make_candidate(image: Image.Image, kind: str) -> Image.Image:
    import cv2  # Lazy import: Phase 1 needs no OpenCV installation.

    gray = np.asarray(image.convert('L'))
    if kind == 'invert':
        output = cv2.bitwise_not(gray)
    elif kind == 'background_normalize':
        # Estimate slowly varying illumination, then divide it out. No resizing,
        # warping, cropping or geometry changes are performed.
        sigma = max(3.0, min(image.size) / 30.0)
        background = cv2.GaussianBlur(gray, (0, 0), sigma)
        output = cv2.divide(gray, np.maximum(background, 1), scale=255)
    elif kind == 'clahe':
        output = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    else:
        raise ValueError(f'Unknown preprocessing candidate: {kind}')
    return Image.fromarray(output)
