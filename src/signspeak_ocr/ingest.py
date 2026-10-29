"""Decode, orient and normalize one uploaded image before model inference."""
from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import ImageTooLargeError, InputError, UnsupportedImageError

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_INPUT_PIXELS = 80_000_000


@dataclass
class LoadedImage:
    working: Image.Image
    metadata: dict


def load_image(source: str | Path | bytes) -> LoadedImage:
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        path = Path(source)
        if not path.is_file():
            raise InputError("Input image not found")
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ImageTooLargeError("Image exceeds the 10 MB limit")
        data = path.read_bytes()
    if not data:
        raise InputError("Input image is empty")
    if len(data) > MAX_INPUT_BYTES:
        raise ImageTooLargeError("Image exceeds the 10 MB limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.width * original.height > MAX_INPUT_PIXELS:
                    raise ImageTooLargeError("Image exceeds the pixel limit")
                raw_size = list(original.size)
                image = ImageOps.exif_transpose(original)
                if image.mode in {"P", "RGBA", "LA", "PA", "RGBa", "La"}:
                    rgba = image.convert("RGBA")
                    background = Image.new("RGBA", rgba.size, "white")
                    image = Image.alpha_composite(background, rgba).convert("RGB")
                else:
                    image = image.convert("RGB")
                image.load()
    except ImageTooLargeError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, OSError, SyntaxError, ValueError) as error:
        raise UnsupportedImageError("Cannot decode this image") from error
    return LoadedImage(image, {
        "sha256": hashlib.sha256(data).hexdigest(),
        "raw_size": raw_size, "oriented_size": list(image.size),
    })
