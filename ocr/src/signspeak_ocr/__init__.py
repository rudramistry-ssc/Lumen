"""SignSpeak OCR: classical, CPU-only OCR with structured JSON output."""

__version__ = "0.1.0"

from .config import IngestConfig, PipelineConfig, PreprocessConfig, QualityConfig, TesseractConfig  # noqa: E402
from .pipeline import extract_image  # noqa: E402

__all__ = [
    "IngestConfig",
    "PipelineConfig",
    "PreprocessConfig",
    "QualityConfig",
    "TesseractConfig",
    "__version__",
    "extract_image",
]
