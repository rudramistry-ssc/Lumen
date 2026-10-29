"""Image ingestion: decode, guard, EXIF-orient, normalize mode, bound size."""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .config import IngestConfig
from .errors import ImageTooLargeError, InputError, UnsupportedImageError
from .geometry import EXIF_ORIENTATIONS, TransformChain, exif_orientation_matrix, scale_matrix

EXIF_ORIENTATION_TAG = 0x0112


@dataclass
class LoadedImage:
    working: Image.Image
    """RGB image given to OCR (after orientation and optional downscale)."""
    reference_size: tuple[int, int]
    chain: TransformChain
    metadata: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def read_source(source: str | Path | bytes, config: IngestConfig) -> tuple[bytes, str | None]:
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        name = None
    else:
        path = Path(source)
        if not path.is_file():
            raise InputError(f"Input image not found: {path}")
        size = path.stat().st_size
        if size > config.max_input_bytes:
            raise ImageTooLargeError(
                f"Input file is {size} bytes; limit is {config.max_input_bytes}",
                details={"bytes": size, "limit": config.max_input_bytes},
            )
        data = path.read_bytes()
        name = path.name
    if not data:
        raise InputError("Input image is empty")
    if len(data) > config.max_input_bytes:
        raise ImageTooLargeError(
            f"Input is {len(data)} bytes; limit is {config.max_input_bytes}",
            details={"bytes": len(data), "limit": config.max_input_bytes},
        )
    return data, name


def load_image(
    source: str | Path | bytes,
    config: IngestConfig | None = None,
    *,
    file_name: str | None = None,
) -> LoadedImage:
    config = config or IngestConfig()
    data, path_name = read_source(source, config)
    notes: list[str] = []

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            image_format = image.format
            raw_size = image.size
            if raw_size[0] * raw_size[1] > config.max_input_pixels:
                raise ImageTooLargeError(
                    f"Image has {raw_size[0] * raw_size[1]} pixels; limit is {config.max_input_pixels}",
                    details={"size": list(raw_size), "limit_pixels": config.max_input_pixels},
                )
            frames = getattr(image, "n_frames", 1)
            if frames > 1:
                notes.append("multi_frame_input_first_frame_used")
            exif = image.getexif()
            dpi = image.info.get("dpi")
            image.load()
    except ImageTooLargeError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as error:
        raise UnsupportedImageError(f"Cannot decode image: {error}") from error

    orientation = exif.get(EXIF_ORIENTATION_TAG, 1) if exif else 1
    try:
        orientation = int(orientation)
    except (TypeError, ValueError):
        orientation = 1
    if orientation not in EXIF_ORIENTATIONS:
        notes.append(f"invalid_exif_orientation_ignored:{orientation}")
        orientation = 1

    chain = TransformChain(raw_size)
    description, method = EXIF_ORIENTATIONS[orientation]
    if method is not None:
        image = image.transpose(getattr(Image.Transpose, method))
        chain.append(
            "exif_orientation",
            exif_orientation_matrix(orientation, *raw_size),
            image.size,
            {"orientation": orientation, "operation": description},
        )
    chain.mark_reference()
    reference_size = image.size

    original_mode = image.mode
    image, mode_notes = normalize_mode(image)
    notes.extend(mode_notes)

    width, height = image.size
    longest = max(width, height)
    if longest > config.max_working_edge:
        factor = config.max_working_edge / longest
        target = (max(1, round(width * factor)), max(1, round(height * factor)))
        image = image.resize(target, Image.Resampling.LANCZOS)
        chain.append(
            "downscale",
            scale_matrix(target[0] / width, target[1] / height),
            target,
            {"reason": "max_working_edge", "max_working_edge": config.max_working_edge},
        )
        notes.append("downscaled_for_processing")
    if min(reference_size) < config.min_edge_warning:
        notes.append("very_small_image")

    metadata = {
        "file_name": file_name or path_name,
        "media_type": Image.MIME.get(image_format or "", None),
        "format": image_format,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "raw_size": list(raw_size),
        "exif_orientation": orientation,
        "oriented_size": list(reference_size),
        "mode": original_mode,
        "dpi": [float(v) for v in dpi] if isinstance(dpi, tuple) and len(dpi) == 2 else None,
        "frames": frames,
    }
    return LoadedImage(image, reference_size, chain, metadata, notes)


def normalize_mode(image: Image.Image) -> tuple[Image.Image, list[str]]:
    """Return an 8-bit RGB image; alpha is flattened onto white."""

    notes: list[str] = []
    mode = image.mode
    if mode in {"I;16", "I;16B", "I;16L", "I;16N", "I", "F"}:
        array = np.asarray(image, dtype=np.float64)
        maximum = float(array.max()) if array.size else 0.0
        if mode.startswith("I;16"):
            array = array / 257.0
        elif maximum > 255.0:
            array = array * (255.0 / maximum)
        image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), mode="L")
        notes.append("high_bit_depth_scaled_to_8bit")
    if image.mode == "P":
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    if image.mode in {"RGBA", "LA", "PA", "RGBa", "La"}:
        rgba = image.convert("RGBA")
        alpha = np.asarray(rgba)[:, :, 3]
        if alpha.min() < 255:
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            image = Image.alpha_composite(background, rgba)
            notes.append("alpha_flattened_on_white")
        image = image.convert("RGB")
    elif image.mode == "CMYK":
        image = image.convert("RGB")
        notes.append("cmyk_converted_to_rgb")
    elif image.mode != "RGB":
        image = image.convert("RGB")
    return image, notes
