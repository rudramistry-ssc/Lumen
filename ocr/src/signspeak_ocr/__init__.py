"""Single-image transcription and summaries through a vision model (local or remote)."""
__version__ = "0.3.0"

from .config import VlmConfig
from .analysis import analyze_image, render_report

__all__ = ["VlmConfig", "analyze_image", "render_report"]
