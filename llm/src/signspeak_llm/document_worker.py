"""Internal stdin/stdout worker for bounded uploads; never launches a model server."""
import base64
import json
import sys


def main():
    request = json.loads(sys.stdin.buffer.read())
    from .client import LocalLLM
    from .reconcile import Reconciler
    from .document import DocumentProcessor
    from signspeak_ocr.config import (PipelineConfig, TesseractConfig, IngestConfig, QualityConfig, PreprocessConfig)
    settings = request.get("ocr_config")
    config = None
    if settings:
        settings = dict(settings)
        tess = dict(settings.pop("tesseract"))
        tess["languages"] = tuple(tess["languages"])
        tess["variables"] = tuple(tess["variables"].items())
        config = PipelineConfig(tesseract=TesseractConfig(**tess), ingest=IngestConfig(**settings.pop("ingest")),
            quality=QualityConfig(**settings.pop("quality")), preprocessing=PreprocessConfig(**settings.pop("preprocessing")), **settings)
    reconciler = Reconciler(LocalLLM(**request["client"]), max_edge=request["max_edge"], model_fingerprint=request["model_fingerprint"])
    processor = DocumentProcessor(reconciler=reconciler, cache_dir=request["cache_dir"], ocr_config=config,
                                  wait_seconds=request["wait_seconds"], isolate=False)
    processor._job_file = request["job_file"]
    processor._deadline_at = request["deadline_at"]
    result = processor.process(base64.b64decode(request["image"]))
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}")
        raise SystemExit(1)
