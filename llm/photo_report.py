"""Readable private comparison report; never infer ground truth or accuracy scores."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    report = json.loads((root/"report.json").read_text(encoding="utf-8"))
    inspection = json.loads((root/"inspection.json").read_text(encoding="utf-8")) if (root/"inspection.json").exists() else {"images": {}}
    notes_path = root/"qualitative-review.json"
    qualitative = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}
    rows = report["rows"]
    total = len(json.loads((root/"images.json").read_text(encoding="utf-8")))
    state = report.get("run_status") or ('finished' if report.get('completed_utc') else 'in progress')
    paired = sum(len(row.get("model_status",{})) == 2 and all(v["status"] != "fallback" for v in row["model_status"].values()) for row in rows)
    failed = sum(any(v["status"] == "fallback" for v in row.get("model_status",{}).values()) for row in rows)
    lines = ["# Ten-image local photographic pilot", "", f"Completed upload records: **{len(rows)}/{total}**. Run state: **{state}**.", "",
             f"{paired} saved images have both complete visual readings; {failed} saved image(s) include a failed visual reading; {total-len(rows)} images are unfinished. The results below do not imply all methods succeeded.", "",
             "**Preliminary comparisons only. References are pending manual verification. No validated CER/WER or accuracy ranking is reported.**", "",
             "Originals were read locally; no cloud inference or model downloads. All images, raw readings, references and this report stay in Git-ignored evaluation storage.", "",
             "The four readings are preserved per image: original OCR, independent vision, hybrid, and provisional selected document. Missing complete VLM outputs are labelled failures, not replaced with OCR in model columns.", "",
             "## Processing summary", "", "Later photos use user-approved 1024-pixel previews for speed. Earlier completed full-detail readings are preserved. Each image's vision/hybrid modes use identical preparation, but mixed resolutions across images prevent a uniform full-resolution accuracy claim.", "",
             "| Image | Layout | Image detail | Status / selected | Upload s | Peak simultaneous MiB | Context checks |", "| --- | --- | --- | --- | ---: | ---: | --- |"]
    for row in rows:
        detail = inspection["images"].get(row["name"], {})
        checks = row.get("consumer_checks", {})
        checked = "pass (contract only)" if checks and all(checks.values()) and row.get("qa", {}).get("status") == "completed" else "blocked / incomplete"
        if checks and all(checks.values()) and row.get("qa", {}).get("status") == "contract_only": checked = "context pass; model Q&A skipped"
        peak = f"{row.get('memory',{}).get('peak_combined_working_set_mib',0):.0f}"
        if row.get("cache_hit_on_first_access"): peak = "not captured (cache resume)"
        if row.get("original_upload_partial_memory"):
            peak = f"{row['original_upload_partial_memory']['peak_combined_working_set_mib']:.0f} observed (partial)"
        edge = row.get("image_max_edge", 2048)
        prep = "1024 preview" if edge == 1024 else f"full detail (bound {edge})"
        lines.append(f"| {row['name']} | {detail.get('layout', 'not classified')} | {prep} | {row['status']} / {row.get('selected_method','—')} | {row.get('upload_seconds',0):.1f} | {peak} | {checked} |")
    for item in report.get("skipped_images", []):
        lines.append(f"| {item['name']} | {inspection['images'].get(item['name'],{}).get('layout','')} | unfinished | not evaluated / no selected result | — | — | not run |")
    lines += ["", "Memory is a sampled sum of simultaneous working sets for local Qwen, evaluation Python and OCR children; shared pages may be counted twice and brief peaks missed. It is not a sum of separate component peaks. This pilot tests Piper's actual content planner; it does not synthesize/play every photo. The separate hybrid smoke test exercises actual Piper WAV generation.", "",
              "## Per-image differences and manual review", ""]
    for row in rows:
        detail = inspection["images"].get(row["name"], {})
        base = "images/"+row["id"]
        final = "final-OCR-FALLBACK" if row["status"] == "ocr_unreviewed_fallback" else "final"
        lines += [f"### {row['name']}", "", f"Source: {row['path']}", "",
                  f"[OCR]({base}/ocr_only.txt) · [Vision-only]({base}/vision_only.txt) · [Hybrid]({base}/hybrid.txt) · [Final]({base}/{final}.txt) · [Complete record]({base}/document.json) · [Manual reference](references/{row['id']}.json)", ""]
        for risk in detail.get("risks", []): lines.append("- Visual inspection concern (unverified): "+risk)
        for mode, differences in row.get("method_differences", {}).items():
            if mode == "final" and row.get("texts",{}).get("final") == row.get("texts",{}).get(row.get("selected_method")): continue
            nums = differences["numeric_disagreements"]
            missing, added = nums["ocr_literals_missing_or_changed"], nums["model_literals_introduced_or_changed"]
            lines.append(f"- {mode}: {len(differences['omissions'])} OCR-token differences missing/changed and {len(differences['unsupported_additions'])} added/changed. These are comparisons against fallible OCR, **not proven errors**.")
            if missing or added:
                lines.append("  Critical literal examples vs OCR: missing/changed "+repr(missing[:4])+"; added/changed "+repr(added[:4])+". Full lists are in result.json; check image and label/value relationships.")
        for note in qualitative.get(row["name"], []): lines.append("- Preliminary reviewer observation: "+note)
        if row.get("error"): lines.append("- Failure/integration issue: "+row["error"])
        lines.append(f"- OCR calls: {row.get('ocr_calls')}; visual completions: {row.get('visual_calls')}; text Q&A attempts: {row.get('qa_text_requests')}; source unchanged: {row.get('original_unchanged')}.")
        if row.get("qa",{}).get("status") == "blocked": lines.append("- Q&A was deliberately blocked for unreviewed OCR fallback.")
        lines += [""]
    for item in report.get("skipped_images", []):
        lines += [f"### {item['name']} — unfinished", "", item["reason"], "",
                  f"[Blank manual reference](references/{item['id']}.json). Original remains at {item['path']}. No missing model reading or selected text has been fabricated.", ""]
    lines += ["## Important failures and integration limitations", ""]
    lines += ["- "+text for text in report.get("limitations", [])]
    lines += ["- Piper's content comparison preserves wording and values while ignoring spaced slash/pipe separators used for language switching. Its literal speech.text still equals final text. The original runtime literal comparison is retained separately for traceability."]
    lines += ["## Filling reference templates", "", "Edit each JSON under references/. Do not copy OCR/model output without checking the original. Fill exact_transcription, ordered_sections, languages, critical_values_and_label_relationships, crossed_out_or_corrected_text, and unreadable/redacted areas. For symbol-only scenes keep symbol meaning separate from printed text. Set review_status to reviewed, reviewer and reviewed_at only after checking; an empty transcript requires explicit no_printed_text=true.", "",
              "No reference is automatically approved by these tools. Current results cannot establish CER/WER, completeness, hallucination rates, or whether final/vision/hybrid is most accurate. Repeated agreement and API success do not establish correctness.", "",
              "## Workflow", "", "Each upload invokes the existing OCR pipeline and two visual modes once. Cache reads add no OCR/image inference. Q&A uses selected text/sections/warnings, not original OCR-only context; follow-ups receive the prior turn. Different images use independent context/history. Original OCR/model evidence remains separate. See report.json consumer_checks and saved Q&A history; dedicated lifecycle tests cover typed/spoken sessions and source isolation.", ""]
    (root/"REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(root/"REPORT.md")


if __name__ == "__main__": main()
