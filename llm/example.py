"""OCR once, cache source and views, then ask without repeating extraction."""
import json
from pathlib import Path

from signspeak_llm import LocalLLM
from signspeak_ocr import PipelineConfig, PreprocessConfig, extract_image
from signspeak_ocr.integration import adapt_result

root = Path(__file__).resolve().parent
cache = root / "runtime/example-views.json"
cache.parent.mkdir(exist_ok=True)
if not cache.exists():
    source = extract_image(root.parent / "ocr/eval/benchmark/images/english_clean.png",
                           PipelineConfig(preprocessing=PreprocessConfig(enabled=True)))
    if source["validation"]["overall_status"] == "failed":
        raise RuntimeError(source["errors"])
    (cache.parent / "example-source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    cache.write_text(json.dumps(adapt_result(source), ensure_ascii=False, indent=2), encoding="utf-8")
context = json.loads(cache.read_text(encoding="utf-8"))["llm_context"]
result = LocalLLM().answer(context, "When does the library reopen?", language="en")
print(json.dumps(result, ensure_ascii=False, indent=2))
