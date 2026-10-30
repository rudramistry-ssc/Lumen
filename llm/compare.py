"""Controlled full/compact comparison, including uncached and cached requests."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from benchmark import cases, contexts, hardware, save
from challenge_cases import challenge_cases, challenge_contexts
from final_validation import final_cases, final_contexts
from signspeak_llm import LocalLLM
from signspeak_llm.server import Server, process_memory

ROOT = Path(__file__).resolve().parent


def run(model, mode, challenge=False, selected=None, tag=None, policy="baseline", final=False):
    data, items = contexts(), cases()
    if challenge:
        data.update(challenge_contexts())
        items += challenge_cases()
    if final:
        data.update(final_contexts())
        items += final_cases()
    if selected:
        items = [c for c in items if c["id"] in selected]
    output = ROOT / "runtime/phase31" / ((tag or f"{model}-{mode}") + ".json")
    if output.exists():
        raise FileExistsError(f"Preserving existing results: {output}. Use another --tag.")
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "model_key": model,
              "context_mode": mode, "policy": policy, "hardware": hardware(), "rows": [],
              "method": "Every case first uses cache_prompt=false (check cache_n); immediate repeat uses true. Same 4 threads, 4096 slot, temp 0, seed 42, 192 max output. Raw and application answers kept separately. No automatic accuracy score.",
              "source_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT / "src").rglob("*")) if p.suffix in {".py", ".json"}},
              "suite_hash": hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    save(output.parent / "contexts.json", data)
    save(output.parent / "suite.json", items)
    with Server(model_key=model) as server:
        report["server"] = server.metadata
        client = LocalLLM(context_mode=mode, safeguards=True, thinking=False, policy=policy)
        for case in items:
            context = data[case["context"]]
            diagnostic = client.inspect_prompt(context, case["question"], case["history"], language=case["language"])
            # Save the actual serialized prompt once per model/mode/case. Synthetic only.
            save(output.parent / "prompts" / f"{tag or model + '-' + mode}-{case['id']}.json", diagnostic)
            for repeat in range(2):
                client.cache_prompt = bool(repeat)
                row = {k:v for k,v in case.items() if k != "text"}
                row.update(repetition=repeat, cache_prompt=client.cache_prompt,
                           token_breakdown=diagnostic["token_breakdown"])
                try:
                    row["result"] = client.answer(context, case["question"], case["history"], language=case["language"])
                except Exception as error:
                    row["error"] = f"{type(error).__name__}: {error}"
                row["memory"] = process_memory(server.process)
                report["rows"].append(row)
                save(output, report)
                result = row.get("result", {})
                print(json.dumps({"id": case["id"], "repeat": repeat,
                                  "raw": result.get("raw_answer"), "answer": result.get("answer"),
                                  "ms": result.get("total_latency_ms"), "tokens": result.get("prompt_tokens_counted"),
                                  "cache_n": result.get("server_timings", {}).get("cache_n"),
                                  "error": row.get("error")}, ensure_ascii=False), flush=True)
        report["final_memory"] = process_memory(server.process)
        report["thinking_check"] = {"requested": False,
            "reasoning_content_empty_all": all(not r.get("result", {}).get("reasoning_content") for r in report["rows"]),
            "note": "Inspect saved rendered Qwen3 prompt for empty <think></think> prefill and compare token count to usage; no hidden reasoning text expected."}
    save(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["vl", "text"], default="vl")
    parser.add_argument("--mode", choices=["full", "compact"], default="compact")
    parser.add_argument("--challenge", action="store_true")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--tag")
    parser.add_argument("--policy", choices=["baseline", "strict"], default="baseline")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    run(args.model, args.mode, args.challenge, args.cases, args.tag, args.policy, args.final)
