"""Default upload analysis once; Q&A uses the cached final interpretation."""
import json
from pathlib import Path

from signspeak_llm import DocumentProcessor, LocalLLM

root = Path(__file__).resolve().parent
document = DocumentProcessor().process((root.parent/"ocr/eval/benchmark/images/english_clean.png").read_bytes())
if document["status"] != "needs_review":
    raise RuntimeError(f"Upload failed or requires explicit fallback review: {document}")
result = LocalLLM(context_size=8192).answer(document["selected_views"]["llm_context"], "When does the library reopen?", language="en")
print(json.dumps(result, ensure_ascii=False, indent=2))
