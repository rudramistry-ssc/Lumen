"""Coordinate transforms between the raw file, the reference image and working images.

Spaces:

* ``raw``       - pixel grid as stored in the file (before EXIF orientation).
* ``reference`` - the image as a viewer displays it (after EXIF orientation).
  All output coordinates are in this space.
* ``working``   - the image actually given to OCR (after downscaling and,
  in later phases, rotation/perspective/deskew/crops).

Coordinates are continuous pixel-edge coordinates: a pixel (i, j) covers
[i, i+1) x [j, j+1). Each step is a 3x3 homogeneous matrix mapping its source
space into its target space, so perspective corrections fit the same model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

Point = tuple[float, float]
BBox = tuple[float, float, float, float]

# EXIF orientation tag value -> (description, Pillow transpose method name).
EXIF_ORIENTATIONS: dict[int, tuple[str, str | None]] = {
    1: ("identity", None),
    2: ("mirror_horizontal", "FLIP_LEFT_RIGHT"),
    3: ("rotate_180", "ROTATE_180"),
    4: ("mirror_vertical", "FLIP_TOP_BOTTOM"),
    5: ("transpose", "TRANSPOSE"),
    6: ("rotate_90_cw", "ROTATE_270"),
    7: ("transverse", "TRANSVERSE"),
    8: ("rotate_90_ccw", "ROTATE_90"),
}


def exif_orientation_matrix(orientation: int, width: int, height: int) -> np.ndarray:
    """Matrix mapping raw (width x height) coordinates to displayed coordinates."""

    w, h = float(width), float(height)
    matrices = {
        1: [[1, 0, 0], [0, 1, 0]],
        2: [[-1, 0, w], [0, 1, 0]],
        3: [[-1, 0, w], [0, -1, h]],
        4: [[1, 0, 0], [0, -1, h]],
        5: [[0, 1, 0], [1, 0, 0]],
        6: [[0, -1, h], [1, 0, 0]],
        7: [[0, -1, h], [-1, 0, w]],
        8: [[0, 1, 0], [-1, 0, w]],
    }
    if orientation not in matrices:
        raise ValueError(f"Invalid EXIF orientation: {orientation}")
    return np.array(matrices[orientation] + [[0, 0, 1]], dtype=float)


def scale_matrix(sx: float, sy: float) -> np.ndarray:
    return np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], dtype=float)


def translation_matrix(tx: float, ty: float) -> np.ndarray:
    return np.array([[1, 0, tx], [0, 1, ty], [0, 0, 1]], dtype=float)


def apply_matrix(matrix: np.ndarray, points: Iterable[Point]) -> list[Point]:
    array = np.asarray(list(points), dtype=float)
    if array.size == 0:
        return []
    homogeneous = np.hstack([array, np.ones((len(array), 1))])
    mapped = homogeneous @ matrix.T
    w = mapped[:, 2:3]
    if np.any(np.abs(w) < 1e-12):
        raise ValueError("Point maps to infinity under this transform")
    mapped = mapped[:, :2] / w
    return [(float(x), float(y)) for x, y in mapped]


@dataclass(frozen=True)
class Transform:
    name: str
    matrix: np.ndarray
    source_size: tuple[int, int]
    target_size: tuple[int, int]
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.name,
            "matrix": [[round(float(v), 9) for v in row] for row in self.matrix],
            "source_size": list(self.source_size),
            "target_size": list(self.target_size),
            **({"params": self.params} if self.params else {}),
        }


class TransformChain:
    """Ordered transforms from the raw file to the current working image."""

    def __init__(self, raw_size: tuple[int, int]) -> None:
        self.raw_size = (int(raw_size[0]), int(raw_size[1]))
        self.steps: list[Transform] = []
        self._reference_index: int | None = None

    @property
    def current_size(self) -> tuple[int, int]:
        return self.steps[-1].target_size if self.steps else self.raw_size

    @property
    def reference_size(self) -> tuple[int, int]:
        if self._reference_index is None:
            raise RuntimeError("Reference space has not been marked")
        index = self._reference_index
        return self.steps[index - 1].target_size if index else self.raw_size

    def append(
        self,
        name: str,
        matrix: np.ndarray,
        target_size: tuple[int, int],
        params: dict[str, Any] | None = None,
    ) -> Transform:
        matrix = np.asarray(matrix, dtype=float)
        if matrix.shape != (3, 3) or abs(np.linalg.det(matrix)) < 1e-12:
            raise ValueError(f"Transform {name!r} must be an invertible 3x3 matrix")
        step = Transform(name, matrix, self.current_size, (int(target_size[0]), int(target_size[1])), params or {})
        self.steps.append(step)
        return step

    def mark_reference(self) -> None:
        """Declare the current space as the output (reference) space."""

        self._reference_index = len(self.steps)

    def _product(self, steps: Sequence[Transform]) -> np.ndarray:
        matrix = np.eye(3)
        for step in steps:
            matrix = step.matrix @ matrix
        return matrix

    def reference_to_working(self) -> np.ndarray:
        if self._reference_index is None:
            raise RuntimeError("Reference space has not been marked")
        return self._product(self.steps[self._reference_index:])

    def working_to_reference(self) -> np.ndarray:
        return np.linalg.inv(self.reference_to_working())

    def raw_to_reference(self) -> np.ndarray:
        if self._reference_index is None:
            raise RuntimeError("Reference space has not been marked")
        return self._product(self.steps[: self._reference_index])

    def map_box_to_reference(self, box: BBox, working_matrix: np.ndarray | None = None) -> "MappedBox":
        """Map an axis-aligned working-space box to the reference image.

        ``working_matrix`` maps working coordinates to reference coordinates;
        pass a precomputed one when mapping many boxes.
        """

        matrix = self.working_to_reference() if working_matrix is None else working_matrix
        x0, y0, x1, y1 = box
        corners = apply_matrix(matrix, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        return MappedBox.from_polygon(corners, self.reference_size)

    def to_dict(self) -> list[dict[str, Any]]:
        records = []
        for index, step in enumerate(self.steps):
            record = step.to_dict()
            record["space"] = (
                "raw_to_reference"
                if self._reference_index is not None and index < self._reference_index
                else "reference_to_working"
            )
            records.append(record)
        return records


@dataclass(frozen=True)
class MappedBox:
    polygon: tuple[Point, ...]
    bbox: BBox
    bbox_norm: BBox

    @classmethod
    def from_polygon(cls, polygon: Sequence[Point], size: tuple[int, int]) -> "MappedBox":
        width, height = size
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        bbox = (
            _clip(min(xs), width),
            _clip(min(ys), height),
            _clip(max(xs), width),
            _clip(max(ys), height),
        )
        clipped = tuple((_clip(x, width), _clip(y, height)) for x, y in polygon)
        norm = (bbox[0] / width, bbox[1] / height, bbox[2] / width, bbox[3] / height)
        return cls(clipped, bbox, norm)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bbox": [_round(v) for v in self.bbox],
            "polygon": [[_round(x), _round(y)] for x, y in self.polygon],
            "bbox_norm": [round(v, 6) for v in self.bbox_norm],
        }


def union_box(boxes: Iterable[BBox]) -> BBox | None:
    boxes = list(boxes)
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _clip(value: float, limit: float) -> float:
    return min(max(float(value), 0.0), float(limit))


def _round(value: float) -> float | int:
    rounded = round(float(value), 1)
    return int(rounded) if rounded.is_integer() else rounded
